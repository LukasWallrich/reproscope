"""Blind materials: the value-free contract, the local leak repair, the scan and the audit.

The redacted methods document itself is written by the combined contracts call
(`contracts.py`); this module never sees the paper text. When the scan finds a
reported value, only the offending sentences go to a cheap model for a rewrite.
"""

from __future__ import annotations

import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
from . import leakcheck

# Everything a replica must not see.
BLIND_DROP = (
    "source_quote", "source_anchor_quote", "source_anchor_scope", "source_region", "figure_panel", "figure_endpoints", "legend_quote", "source_validation", "abstain_reason",
    "occurrence_id", "quantity_id",
    "value",
    "precision",
    "uncertainty",
    "comparator",
    "extraction",  # the arbiter's note quotes the disputed numbers
    "importance",  # "headline" marks which tests the paper's conclusions rest on
    "meta",
)

REPAIR_ROUNDS = 2


class ScrubbedText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str


class ScrubOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ScrubbedText] = []


SCRUB_CHUNK = 40  # a host cuts a reply at about 300 s; 120 items ran past it

SCRUB_PROMPT = """You are preparing material for an analyst who must re-run a study's analyses
without learning what the study found. Each item below is one fragment of that material: a
description of a quantity the paper reports, or one field of an analysis contract.

Rewrite each fragment so that it says only WHAT is meant — which statistic, variable,
comparison, sample, model or analytical choice — and nothing about the outcome. Remove:

- every number that is a result, and every degree of freedom (write "t statistic for ...",
  never "t(27)"; a df discloses the analysis sample size);
- every direction ("higher", "increased", "positive relationship", "declined");
- every significance or effect-size statement, including quoted ones ("was not significant",
  "fully mediated", "no significant effects involving sex", "marginally significant"), and
  every statement that an effect was or was not found;
- every word revealing whether a finding supported a hypothesis.

Keep design parameters: scale ranges, item counts, numbers of conditions and eligibility or
scoring thresholds. Remove recruited, excluded and analysed participant counts, group counts,
observed sample percentages and descriptive sample summaries (including observed mean/SD age).
Keep the actual eligibility rule, study/condition labels, pairing and missingness procedure.
The analyst must derive realised sample sizes from the data; published N must not be a target. Where a fragment
describes a choice the authors justified by a result ("sex was dropped because ..."), keep the
choice and drop the justification. Keep the wording otherwise close to the original, and keep
each fragment's id unchanged. Return every id you were given.

Example: "Intimacy was higher in the attention condition (4.58) than in the no-attention
condition (2.82), t(27) = 5.91" becomes "t statistic for the comparison of intimacy between
the attention and no-attention conditions".

Items:
{items}

Return JSON: {{"items": [{{"id": "...", "text": "..."}}]}}. Output only JSON.
"""

# Contract fields that carry free text the authors may have justified with a result.
CONTRACT_TEXT_FIELDS = (
    "sample_rule",
    "outcome",
    "model_type",
    "estimator",
    "se_type",
    "weights",
    "missingness",
)


# --- local leak repair ----------------------------------------------------

_BREAK = re.compile(r"(?<=[.!?])\s+|\n")
_PATH_TOKEN = re.compile(r"\.([^.\[\]]+)|\[(\d+)\]")


def sentence_span(text: str, start: int, end: int) -> tuple[int, int]:
    """The sentence (or line) containing [start, end) in `text`."""
    left = 0
    for m in _BREAK.finditer(text[:start]):
        left = m.end()
    m = _BREAK.search(text[end:])
    return left, (end + m.start() if m else len(text))


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _json_set(obj: Any, path: str, value: str) -> None:
    tokens = [k or int(i) for k, i in _PATH_TOKEN.findall(path)]
    cur = obj
    for t in tokens[:-1]:
        cur = cur[t]
    cur[tokens[-1]] = value


def repair_items(files: list[Path], hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One repair item per passage that leaks: its text and the forms to remove.

    Markdown passages are sentences; JSON passages are whole string leaves, which are
    short enough to rewrite as a unit. Numeric JSON leaves have no text to rewrite and
    are left for the caller to abstain on.
    """
    by_name = {p.name: p for p in files}
    items: list[dict[str, Any]] = []
    for name in sorted({h["file"] for h in hits}):
        path = by_name.get(name)
        if path is None:
            continue
        file_hits = [h for h in hits if h["file"] == name]
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text())
            for location in sorted({h["location"] for h in file_hits}):
                leaf = _json_leaf(data, location)
                if not isinstance(leaf, str):
                    continue
                forms = sorted({h["value"] for h in file_hits if h["location"] == location})
                items.append(
                    {"id": f"{name}|{location}", "file": name, "span": None,
                     "location": location, "text": leaf, "forms": forms}
                )
        else:
            text = path.read_text()
            spans = _merge([sentence_span(text, h["start"], h["end"]) for h in file_hits])
            for a, b in spans:
                forms = sorted({h["value"] for h in file_hits if a <= h["start"] < b})
                items.append(
                    {"id": f"{name}|{a}", "file": name, "span": (a, b),
                     "location": None, "text": text[a:b], "forms": forms}
                )
    return items


def _json_leaf(obj: Any, path: str) -> Any:
    cur = obj
    for k, i in _PATH_TOKEN.findall(path):
        try:
            cur = cur[k or int(i)]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def apply_repairs(files: list[Path], items: list[dict[str, Any]], rewrites: dict[str, str]) -> None:
    by_name = {p.name: p for p in files}
    for name in sorted({i["file"] for i in items}):
        path = by_name[name]
        mine = [i for i in items if i["file"] == name and i["id"] in rewrites]
        if not mine:
            continue
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text())
            for item in mine:
                _json_set(data, item["location"], rewrites[item["id"]])
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        else:
            text = path.read_text()
            for item in sorted(mine, key=lambda i: -i["span"][0]):
                a, b = item["span"]
                text = text[:a] + rewrites[item["id"]] + text[b:]
            path.write_text(text)


def repair(
    manifest,
    files: list[Path],
    claims: list[artifacts.ClaimRecord],
    design: list[float],
    result_ids: set[str] | None = None,
    rounds: int = REPAIR_ROUNDS,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Rewrite the leaking passages in place, at most `rounds` times.

    Only the offending passages are sent to the model; the paper text is not in this
    module's reach. Returns the hits that survive and the ledger ids of the calls made.
    """
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    calls: list[str] = []
    result_ids = result_ids or set()
    hits = leakcheck.scan(files, claims, design, result_claim_ids=result_ids)
    for round_no in range(1, rounds + 1):
        if not hits:
            break
        items = repair_items(files, hits)
        if not items:
            break
        # Model-facing identifiers are opaque: file names and JSON paths are easy
        # to alter accidentally. Only this mapping decides where a rewrite lands.
        id_map = {f"r{n:04d}": item for n, item in enumerate(items)}
        payload = [{"id": key, "text": i["text"], "remove": i["forms"]}
                   for key, i in id_map.items()]
        def repair_chunk(chunk):
            from .. import provenance, response_cache
            prompt = artifacts.load_prompt(
                "stage0_leak_repair", items=json.dumps(chunk, indent=1, ensure_ascii=False))
            if round_no > 1:
                prompt += "\nA prior rewrite left the flagged results in these passages. Remove each flagged result while preserving methods."
            key = provenance.digest(prompt)[:16]
            fingerprint = response_cache.key(prompt, ScrubOut, [], "cheap")
            cache_path = stage_dir / "logs" / f"leak_repair_{key}.response.json"
            cached = response_cache.read(cache_path, fingerprint, ScrubOut)
            if cached is not None:
                return llm.LLMResult(text=cached[0].model_dump_json(), parsed=cached[0], ledger_id=cached[1])
            result = llm.call(
                f"leak_repair:{round_no}:{key}",
                prompt,
                paper_id=manifest.paper_id,
                stage="0",
                tier="cheap",
                schema=ScrubOut,
                cwd=manifest.dir,
                timeout_s=900,
                log_path=stage_dir / "logs" / f"leak_repair_{key}.log",
            )
            if result.parsed is not None:
                response_cache.write(cache_path, fingerprint, result.parsed, result.ledger_id)
            return result
        chunks = [payload[i:i+SCRUB_CHUNK] for i in range(0,len(payload),SCRUB_CHUNK)]
        with ThreadPoolExecutor(max_workers=min(4,len(chunks))) as pool:
            results = list(pool.map(repair_chunk, chunks))
        calls.extend(r.ledger_id or "" for r in results)
        if any(r.parsed is None for r in results):
            break
        for chunk, result in zip(chunks, results):
            ids = [item.id for item in result.parsed.items]
            if len(ids) != len(set(ids)) or set(ids) != {item["id"] for item in chunk}:
                raise llm.LLMError("leak repair returned missing, duplicate or unknown item IDs; no rewrites applied")
        returned = [t for r in results for t in r.parsed.items]
        returned_ids = [t.id for t in returned]
        if len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != set(id_map):
            raise llm.LLMError("leak repair returned missing, duplicate or unknown item IDs; no rewrites applied")
        apply_repairs(files, items, {id_map[t.id]["id"]: t.text for t in returned})
        hits = leakcheck.scan(files, claims, design, result_claim_ids=result_ids)
    return hits, calls


# --- description scrubbing ------------------------------------------------


def _scrub_chunk(manifest, items: list[dict[str, str]], index: int):
    r = llm.call(
        f"scrub:{index}",
        SCRUB_PROMPT.format(items=json.dumps(items, indent=1, ensure_ascii=False)),
        paper_id=manifest.paper_id,
        stage="0",
        tier="cheap",
        schema=ScrubOut,
        cwd=manifest.dir,
        timeout_s=1800,
        log_path=paths.run_dir(manifest.paper_id, 0) / "logs" / f"scrub{index}.log",
    )
    if r.parsed is None:
        raise llm.LLMError(f"text scrub failed on chunk {index}: {r.error}")
    if len(r.parsed.items)!=len(items) or {x.id for x in r.parsed.items}!={x['id'] for x in items}:
        raise llm.LLMError(f'text scrub changed the exact requested item scope in chunk {index}')
    return r.parsed, (r.ledger_id or "")


def scrub_texts(manifest, items: list[dict[str, str]]) -> tuple[dict[str, str], list[str]]:
    """Rewrite every fragment to name its quantity without disclosing any outcome.

    Rewrites are cached against the source text, so rebuilding the blind contract
    after a change elsewhere costs nothing.
    """
    if not items:
        return {}, []
    cache_path = paths.run_dir(manifest.paper_id, 0) / "scrub_cache.json"
    cache: dict[str, dict[str, str]] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            cache = {}
    from .. import config,provenance
    fingerprint=provenance.digest({'prompt':SCRUB_PROMPT,'model':config.tier('cheap').model_dump(),
        'schema':ScrubOut.model_json_schema(),'route_protocol':llm.ROUTE_PROTOCOL_VERSIONS.get(config.tier('cheap').route)})
    done={i['id']:cache[i['id']]['text'] for i in items if (cache.get(i['id'],{}).get('source')==i['text']
          or (i['id']=='methods_document' and cache.get(i['id'],{}).get('text','').strip()==i['text'].strip()))
          and cache[i['id']].get('fingerprint')==fingerprint}
    pending=[i for i in items if i['id'] not in done]
    if not pending:return done,[]
    if cache_path.exists():
        archive=cache_path.parent/'scrub_cache_superseded';archive.mkdir(exist_ok=True)
        shutil.copy2(cache_path,archive/(artifacts.sha256_file(cache_path)+'.json'))
    # The prompt sees fragments independently; identical text needs one rewrite.
    groups={}
    for item in pending:groups.setdefault(item['text'],[]).append(item)
    unique=[group[0] for group in groups.values()]
    by_id={item['id']:groups[item['text']] for item in unique}
    chunks=[unique[i:i+SCRUB_CHUNK] for i in range(0,len(unique),SCRUB_CHUNK)]
    calls=[];out=dict(done)
    with ThreadPoolExecutor(max_workers=min(4,len(chunks))) as pool:
        futures=[pool.submit(_scrub_chunk,manifest,chunk,index) for index,chunk in enumerate(chunks)]
        for future in as_completed(futures):
            parsed,cid=future.result();calls.append(cid)
            for entry in parsed.items:
                for original in by_id[entry.id]:
                    out[original['id']]=entry.text
                    cache[original['id']]={'source':original['text'],'text':entry.text,'fingerprint':fingerprint,'ledger_id':cid}
            cache_path.write_text(json.dumps(cache,indent=2,ensure_ascii=False)+'\n')
    return out,calls


def scrub_items(
    claims: list[artifacts.ClaimRecord], contract_records: list[artifacts.EstimandContract]
) -> list[dict[str, str]]:
    items = [
        {"id": f"claim:{c.claim_id}", "text": c.description}
        for c in claims
        if c.description
    ]
    for c in contract_records:
        for field in CONTRACT_TEXT_FIELDS:
            value = getattr(c, field, None)
            if isinstance(value, str) and value.strip():
                items.append({"id": f"contract:{c.analysis_id}:{field}", "text": value})
        for i, t in enumerate(c.transformations):
            items.append({"id": f"contract:{c.analysis_id}:transformations:{i}", "text": t})
        for i, a in enumerate(c.ambiguities):
            if a.note:
                items.append({"id": f"contract:{c.analysis_id}:ambiguities:{i}", "text": a.note})
        # Nested design evidence is prose, even though its surrounding structure is
        # typed. Source quotations can contain result verbs after numbers are removed.
        if c.design:
            for field in ("evidence", "contrast", "independent_unit"):
                value = getattr(c.design, field, None)
                if value:
                    items.append({"id": f"contract:{c.analysis_id}:design:{field}", "text": value})
        for field in ("analysis_label", "predictors", "covariates"):
            value = getattr(c, field, None)
            if isinstance(value, str) and value:
                items.append({"id": f"contract:{c.analysis_id}:{field}", "text": value})
            elif isinstance(value, list):
                items.extend({"id": f"contract:{c.analysis_id}:{field}:{i}", "text": text}
                             for i, text in enumerate(value) if text)
    return items


def blind_contracts(
    contract_records: list[artifacts.EstimandContract], scrubbed: dict[str, str]
) -> list[dict[str, Any]]:
    out = []
    for c in contract_records:
        d = {k: v for k, v in c.model_dump(exclude_none=True).items() if k != "meta"}
        # Canonical grouping keys are intake provenance, not analyst instructions.
        d.pop("identity", None)
        if isinstance(d.get('design'),dict):
            d['design'].pop('n_total',None)
            d['design'].pop('group_ns',None)
        for field in CONTRACT_TEXT_FIELDS:
            key = f"contract:{c.analysis_id}:{field}"
            if key in scrubbed:
                d[field] = scrubbed[key]
        d["transformations"] = [
            scrubbed.get(f"contract:{c.analysis_id}:transformations:{i}", t)
            for i, t in enumerate(c.transformations)
        ]
        for i, a in enumerate(d.get("ambiguities", [])):
            key = f"contract:{c.analysis_id}:ambiguities:{i}"
            if key in scrubbed:
                a["note"] = scrubbed[key]
        for field in ("evidence", "contrast", "independent_unit"):
            key = f"contract:{c.analysis_id}:design:{field}"
            if key in scrubbed:
                d["design"][field] = scrubbed[key]
        for field in ("analysis_label", "predictors", "covariates"):
            key = f"contract:{c.analysis_id}:{field}"
            if isinstance(d.get(field), str) and key in scrubbed:
                d[field] = scrubbed[key]
            elif isinstance(d.get(field), list):
                d[field] = [scrubbed.get(f"{key}:{i}", text) for i, text in enumerate(d[field])]
        out.append(d)
    return out


def blind_claims(
    claims: list[artifacts.ClaimRecord], scrubbed: dict[str, str]
) -> list[dict[str, Any]]:
    out = []
    for c in claims:
        d = c.model_dump(exclude_none=True)
        for f in BLIND_DROP:
            d.pop(f, None)
        d["description"] = scrubbed.get(f"claim:{c.claim_id}", "")
        out.append(d)
    return out


_REDACTION_MARK = re.compile(r"\[redacted: ([^\]]+)\]")


def removed_spans(methods_path: Path) -> list[dict[str, str]]:
    """One entry per inline redaction marker, located by its Markdown heading."""
    spans: list[dict[str, str]] = []
    heading = ""
    for line in methods_path.read_text().splitlines():
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
        for m in _REDACTION_MARK.finditer(line):
            spans.append({"kind": m.group(1).strip(), "location": heading})
    return spans


def build_blind_dir(stage_dir: Path) -> Path:
    """A directory holding only the two blind files, for an auditor with file access."""
    blind = stage_dir / "blind"
    if blind.exists():
        shutil.rmtree(blind)
    blind.mkdir(parents=True)
    from ..stage1.blind import blind_packet
    shutil.copy2(stage_dir / "redacted_methods.md", blind / "METHODS.md")
    (blind / "CONTRACT.json").write_text(json.dumps(
        blind_packet(stage_dir.parent.name, stage_dir / "blind_contract.json"), indent=2, ensure_ascii=False))
    from ..stage1.blind import replica_task
    (blind / "TASK.md").write_text(replica_task(stage_dir.parent.name))
    return blind


def audit_covers_packet(packet: dict, audited) -> bool:
    required = {a["analysis_id"] for a in packet.get("analyses", [])}
    visible = required | set(packet.get("analyses_without_data", []))
    return (isinstance(audited, list) and all(isinstance(a, str) for a in audited)
            and len(audited) == len(set(audited)) and required <= set(audited) <= visible)


def text_leaves(value,location='$'):
    if isinstance(value,str):yield location,value
    elif isinstance(value,dict):
        for key,child in value.items():yield from text_leaves(child,location+'.'+key)
    elif isinstance(value,list):
        for index,child in enumerate(value):yield from text_leaves(child,f'{location}[{index}]')


def semantic_repair_items(files,audit):
    """Locate exact audited leaks in prose; typed execution fields are never edited."""
    quotes=[p['quote'] for p in audit.get('passage_checks',[]) if p.get('anchored') and p.get('kind') in {'numeric_result','directional_result'}]
    norm=lambda s:' '.join(s.casefold().split())
    items=[]
    for path in files:
        leaves=list(text_leaves(json.loads(path.read_text()))) if path.suffix=='.json' else [(None,path.read_text())]
        for location,text in leaves:
            matches=[q for q in quotes if norm(q) in norm(text)]
            if matches:items.append({'id':f'{path.name}|{location or "document"}','file':path.name,'location':location,
                'span':None if location else (0,len(text)),'text':text,'forms':matches})
    return items


def leak_audit(manifest, blind_dir: Path) -> tuple[dict[str, Any], str]:
    """Audit the delivered packet; anchored result leaks block analytical acceptance."""
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    out_path = stage_dir / "leak_audit.json"
    material = "\n\n".join(
        f"--- {p.name} ---\n{p.read_text()}" for p in sorted(blind_dir.iterdir())
    )
    r = llm.call(
        "leak_audit",
        artifacts.load_prompt("stage0_leak_audit", blind_material=material),
        paper_id=manifest.paper_id,
        stage="0",
        tier="cheap",
        cwd=blind_dir,
        timeout_s=900,
        log_path=stage_dir / "logs" / "leak_audit.log",
        large_context=True,
    )
    verdict: dict[str, Any]
    if not r.ok:
        verdict = {"error": r.error, "leak_rating": None}
    else:
        try:
            verdict = json.loads(llm.first_json_object(r.text))
        except json.JSONDecodeError:
            verdict = {"error": "audit reply was not JSON", "raw": r.text[:2000], "leak_rating": None}
    from .. import provenance
    verdict["packet_fingerprint"] = provenance.files({p.name: p for p in blind_dir.iterdir() if p.is_file()})
    decoded_material=material+'\n'+'\n'.join(text for _,text in text_leaves(json.loads((blind_dir/'CONTRACT.json').read_text())))
    verified = []
    for passage in verdict.get("leaking_passages", []):
        quote = passage.get("quote", "") if isinstance(passage, dict) else passage
        kind = passage.get("kind", "unclassified") if isinstance(passage, dict) else "unclassified"
        anchored = bool(quote) and " ".join(str(quote).casefold().split()) in " ".join(decoded_material.casefold().split())
        verified.append({"quote": quote, "kind": kind, "anchored": anchored})
    verdict["passage_checks"] = verified
    packet = json.loads((blind_dir / "CONTRACT.json").read_text())
    audited = verdict.get("audited_analysis_ids")
    coverage_ok = audit_covers_packet(packet, audited)
    verdict["analysis_coverage_verified"] = coverage_ok
    explicit = any(x["anchored"] and x["kind"] in {"numeric_result", "directional_result"} for x in verified)
    verdict["blinding_status"] = ("blocked" if explicit else "unresolved" if not coverage_ok or verdict.get("leak_rating") is None
                                  else "limited" if verdict.get("leak_rating") != "none" else "no_leak_detected")
    verdict["isolation_status"] = "working-directory separation; OS access restrictions not established"
    out_path.write_text(json.dumps(verdict, indent=2) + "\n")
    return verdict, (r.ledger_id or "")


PROMPTS = ("stage0_leak_repair", "stage0_leak_audit")


def run(
    manifest,
    claims: list[artifacts.ClaimRecord],
    contract_records: list[artifacts.EstimandContract],
    inputs: dict[str, str] | None = None,
    force: bool = False,
) -> tuple[artifacts.RedactionReport, list[str]]:
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    methods_path = stage_dir / "redacted_methods.md"
    blind_path = stage_dir / "blind_contract.json"
    report_path = stage_dir / "redaction_report.json"
    design = leakcheck.design_numbers_from_manifest(manifest)
    calls: list[str] = []

    from ..stage1.blind import packet_fingerprint
    packet_audit_path = stage_dir / "leak_audit.json"
    packet_audit = json.loads(packet_audit_path.read_text()) if packet_audit_path.exists() else {}
    audit_matches = (blind_path.exists() and methods_path.exists()
                     and packet_audit.get("packet_fingerprint") == packet_fingerprint(manifest.paper_id))
    if report_path.exists() and blind_path.exists() and not force and audit_matches:
        existing = artifacts.load(artifacts.RedactionReport, report_path)
        if (
            not artifacts.prompt_stale(existing, PROMPTS)  # type: ignore[arg-type]
            and existing.meta is not None  # type: ignore[union-attr]
            and existing.meta.inputs == (inputs or {})  # type: ignore[union-attr]
            and (stage_dir / "leak_audit.json").exists()
            and json.loads((stage_dir / "leak_audit.json").read_text()).get("blinding_status") in {"limited", "no_leak_detected"}
        ):
            return existing, []  # type: ignore[return-value]

    scrubbed, scrub_calls = scrub_texts(manifest, scrub_items(claims, contract_records))
    calls += scrub_calls
    methods_key='methods_document'
    method_scrub,method_calls=scrub_texts(manifest,[{'id':methods_key,'text':methods_path.read_text()}])
    calls+=method_calls
    methods_path.write_text(method_scrub[methods_key].rstrip()+'\n')
    blind_path.write_text(
        json.dumps(
            {
                "contracts": blind_contracts(contract_records, scrubbed),
                "claims": blind_claims(claims, scrubbed),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    result_ids = leakcheck.result_claim_ids(claims, contract_records)
    hits, repair_calls = repair(manifest, [methods_path, blind_path], claims, design, result_ids)
    calls += repair_calls

    forbidden, skipped = leakcheck.forbidden_strings(claims, design, result_ids)
    blind_dir = build_blind_dir(stage_dir)
    delivered_files = [blind_dir / name for name in ("METHODS.md", "CONTRACT.json", "TASK.md")]
    method_collisions=[]
    delivered_hits = leakcheck.scan(delivered_files, claims, design, result_claim_ids=result_ids,method_collisions=method_collisions)
    hits += delivered_hits
    audit: dict[str, Any] = {}
    if not hits:
        audit, audit_call = leak_audit(manifest, blind_dir)
        if audit_call:
            calls.append(audit_call)
        for round_no in range(REPAIR_ROUNDS):
            if audit.get('blinding_status')!='blocked':break
            files=[methods_path,blind_path]
            items=semantic_repair_items(files,audit)
            if not items:break
            payload=[{'id':f'r{i}','text':item['text'],'remove':item['forms']} for i,item in enumerate(items)]
            result=llm.call('semantic_leak_repair',artifacts.load_prompt('stage0_leak_repair',items=json.dumps(payload)),
                paper_id=manifest.paper_id,stage='0',tier='cheap',schema=ScrubOut,timeout_s=900,
                log_path=stage_dir/'logs'/f'semantic_leak_repair{round_no+1}.log')
            if result.ledger_id:calls.append(result.ledger_id)
            expected={p['id'] for p in payload}
            if result.parsed is None or len(result.parsed.items)!=len(expected) or {p.id for p in result.parsed.items}!=expected:
                raise llm.LLMError('semantic leak repair failed exact requested scope')
            mapping={f'r{i}':item['id'] for i,item in enumerate(items)}
            apply_repairs(files,items,{mapping[p.id]:p.text for p in result.parsed.items})
            blind_dir=build_blind_dir(stage_dir)
            hits=leakcheck.scan([blind_dir/name for name in ('METHODS.md','CONTRACT.json','TASK.md')],claims,design,result_claim_ids=result_ids)
            if hits:break
            audit,audit_call=leak_audit(manifest,blind_dir)
            if audit_call:calls.append(audit_call)

    report = artifacts.RedactionReport.model_validate(
        {
            "meta": artifacts.ArtifactMeta(
                artifact="RedactionReport",
                stage="0",
                inputs=inputs or {},
                prompt_versions={n: artifacts.prompt_version(n) for n in PROMPTS},
                model_calls=calls,
            ).model_dump(),
            "removed_spans": removed_spans(methods_path),
            "scan_hits": [json.dumps(h) for h in hits],
            "scan_clean": not hits,
            "forbidden_count": len(forbidden),
            "forbidden_strings": sorted(forbidden),
            "skipped_values": skipped,
            "scanned_files": [methods_path.name, blind_path.name, *["blind/" + p.name for p in delivered_files]],
            "delivered_packet_scan_hits": delivered_hits,
            "registered_method_parameter_collisions":method_collisions,
            "leakage_audit_verdict": audit.get("leak_rating"),
            "leakage_audit_note": json.dumps(audit.get("leaking_passages") or audit.get("error"))
            if audit
            else None,
            "state": "complete" if not hits else "abstained",
            "abstain_reason": None if not hits else f"{len(hits)} forbidden values found",
        }
    )
    artifacts.save(report, report_path)
    return report, calls
