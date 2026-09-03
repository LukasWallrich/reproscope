"""Blind materials: the value-free contract, the local leak repair, the scan and the audit.

The redacted methods document itself is written by the combined contracts call
(`contracts.py`); this module never sees the paper text. When the scan finds a
reported value, only the offending sentences go to a cheap model for a rewrite.
"""

from __future__ import annotations

import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
from . import leakcheck

# Everything a replica must not see.
BLIND_DROP = (
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


SCRUB_CHUNK = 120

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

Keep design numbers: scale ranges, item counts, numbers of conditions, thresholds, and the
recruited and analysed sample sizes that define who is in the analysis. Where a fragment
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
    rounds: int = REPAIR_ROUNDS,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Rewrite the leaking passages in place, at most `rounds` times.

    Only the offending passages are sent to the model; the paper text is not in this
    module's reach. Returns the hits that survive and the ledger ids of the calls made.
    """
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    calls: list[str] = []
    hits = leakcheck.scan(files, claims, design)
    for round_no in range(1, rounds + 1):
        if not hits:
            break
        items = repair_items(files, hits)
        if not items:
            break
        payload = [{"id": i["id"], "text": i["text"], "remove": i["forms"]} for i in items]
        r = llm.call(
            f"leak_repair:{round_no}",
            artifacts.load_prompt(
                "stage0_leak_repair", items=json.dumps(payload, indent=1, ensure_ascii=False)
            ),
            paper_id=manifest.paper_id,
            stage="0",
            tier="cheap",
            schema=ScrubOut,
            reasoning_max_tokens=256,
            cwd=manifest.dir,
            timeout_s=900,
            log_path=stage_dir / "logs" / f"leak_repair{round_no}.log",
        )
        calls.append(r.ledger_id or "")
        if r.parsed is None:
            break
        apply_repairs(files, items, {t.id: t.text for t in r.parsed.items})  # type: ignore[attr-defined]
        hits = leakcheck.scan(files, claims, design)
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
        reasoning_max_tokens=256,
        cwd=manifest.dir,
        timeout_s=1800,
        log_path=paths.run_dir(manifest.paper_id, 0) / "logs" / f"scrub{index}.log",
    )
    if r.parsed is None:
        raise llm.LLMError(f"text scrub failed on chunk {index}: {r.error}")
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
    done = {
        i["id"]: cache[i["id"]]["text"]
        for i in items
        if cache.get(i["id"], {}).get("source") == i["text"]
    }
    items = [i for i in items if i["id"] not in done]
    if not items:
        return done, []
    chunks = [items[i : i + SCRUB_CHUNK] for i in range(0, len(items), SCRUB_CHUNK)]
    out: dict[str, str] = {}
    calls: list[str] = []
    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
        futures = [pool.submit(_scrub_chunk, manifest, c, i) for i, c in enumerate(chunks)]
        for f in futures:
            parsed, call_id = f.result()
            calls.append(call_id)
            out.update({t.id: t.text for t in parsed.items})
    missing = [i["id"] for i in items if i["id"] not in out]
    if missing:
        raise llm.LLMError(f"text scrub returned no rewrite for {len(missing)} items: {missing[:5]}")
    cache.update({i["id"]: {"source": i["text"], "text": out[i["id"]]} for i in items})
    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n")
    out.update(done)
    return out, calls


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
    return items


def blind_contracts(
    contract_records: list[artifacts.EstimandContract], scrubbed: dict[str, str]
) -> list[dict[str, Any]]:
    out = []
    for c in contract_records:
        d = {k: v for k, v in c.model_dump(exclude_none=True).items() if k != "meta"}
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
    for name in ("redacted_methods.md", "blind_contract.json"):
        shutil.copy2(stage_dir / name, blind / name)
    return blind


def leak_audit(manifest, blind_dir: Path) -> tuple[dict[str, Any], str]:
    """Ask a model that has not seen the paper what it can infer. Recorded, not load-bearing."""
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
    )
    verdict: dict[str, Any]
    if not r.ok:
        verdict = {"error": r.error, "leak_rating": None}
    else:
        try:
            verdict = json.loads(llm.first_json_object(r.text))
        except json.JSONDecodeError:
            verdict = {"error": "audit reply was not JSON", "raw": r.text[:2000], "leak_rating": None}
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

    if report_path.exists() and blind_path.exists() and not force:
        existing = artifacts.load(artifacts.RedactionReport, report_path)
        if not artifacts.prompt_stale(existing, PROMPTS):  # type: ignore[arg-type]
            return existing, []  # type: ignore[return-value]

    scrubbed, scrub_calls = scrub_texts(manifest, scrub_items(claims, contract_records))
    calls += scrub_calls
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

    hits, repair_calls = repair(manifest, [methods_path, blind_path], claims, design)
    calls += repair_calls

    forbidden, skipped = leakcheck.forbidden_strings(claims, design)
    blind_dir = build_blind_dir(stage_dir)
    audit: dict[str, Any] = {}
    if not hits:
        audit, audit_call = leak_audit(manifest, blind_dir)
        if audit_call:
            calls.append(audit_call)

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
            "scanned_files": [methods_path.name, blind_path.name],
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
