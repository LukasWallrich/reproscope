"""Steps 6-8: the redacted methods document, the blind contract, the scan and the audit."""

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


def analysis_labels(contract_records: list[artifacts.EstimandContract]) -> str:
    lines = []
    for c in contract_records:
        label = getattr(c, "analysis_label", None) or c.model_type or c.analysis_id
        lines.append(f"- {c.analysis_id}: {label}")
    return "\n".join(lines) or "- (no contracts)"


def _write_methods(
    manifest, paper_text: str, contract_records, extra_instruction: str, attempt: int
) -> tuple[str, str]:
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    prompt = artifacts.load_prompt(
        "stage0_redact",
        paper_text=paper_text,
        analysis_labels=analysis_labels(contract_records),
    ) + extra_instruction
    r = llm.call(
        "redact" if attempt == 1 else "redact:retry",
        prompt,
        paper_id=manifest.paper_id,
        stage="0",
        tier="strong",
        cwd=manifest.dir,
        timeout_s=3600,
        log_path=stage_dir / "logs" / f"redact{attempt}.log",
    )
    if not r.ok or not r.text.strip():
        raise llm.LLMError(f"redaction failed: {r.error}")
    return r.text.strip(), (r.ledger_id or "")


def _scrub_chunk(manifest, items: list[dict[str, str]], index: int):
    r = llm.call(
        f"scrub:{index}",
        SCRUB_PROMPT.format(items=json.dumps(items, indent=1, ensure_ascii=False)),
        paper_id=manifest.paper_id,
        stage="0",
        tier="strong",
        schema=ScrubOut,
        cwd=manifest.dir,
        timeout_s=3600,
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


def leak_audit(manifest, blind_dir: Path, force: bool = False) -> tuple[dict[str, Any], str]:
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    out_path = stage_dir / "leak_audit.json"
    if out_path.exists() and not force:
        return json.loads(out_path.read_text()), ""
    material = "\n\n".join(
        f"--- {p.name} ---\n{p.read_text()}" for p in sorted(blind_dir.iterdir())
    )
    r = llm.call(
        "leak_audit",
        artifacts.load_prompt("stage0_leak_audit", blind_material=material),
        paper_id=manifest.paper_id,
        stage="0",
        tier="strong_alt",
        cwd=blind_dir,
        timeout_s=1800,
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


def run(
    manifest,
    claims: list[artifacts.ClaimRecord],
    contract_records: list[artifacts.EstimandContract],
    paper_text: str,
    inputs: dict[str, str] | None = None,
    force: bool = False,
) -> tuple[artifacts.RedactionReport, list[str]]:
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    methods_path = stage_dir / "redacted_methods.md"
    blind_path = stage_dir / "blind_contract.json"
    report_path = stage_dir / "redaction_report.json"
    design = leakcheck.design_numbers_from_manifest(manifest)
    calls: list[str] = []

    # A leaking file is never reused: the resume check is the scan itself, so a rerun
    # after a failure rewrites the offending file instead of failing on it again. The
    # two outputs are checked separately, so one does not force the other's rewrite.
    def stale(path: Path) -> bool:
        return force or not path.exists() or bool(leakcheck.scan([path], claims, design))

    if stale(blind_path):
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

    if stale(methods_path):
        extra = ""
        hits: list[dict[str, Any]] = []
        for attempt in (1, 2):
            text, call_id = _write_methods(
                manifest, paper_text, contract_records, extra, attempt
            )
            calls.append(call_id)
            methods_path.write_text(text + "\n")
            hits = leakcheck.scan([methods_path], claims, design)
            if not hits:
                break
            extra = (
                "\n\nA previous draft of this document still contained these reported "
                "values. Remove every one of them and any sentence that carries a "
                "result:\n" + json.dumps(hits, indent=1)[:4000]
            )
    hits = leakcheck.scan([methods_path, blind_path], claims, design)

    forbidden, skipped = leakcheck.forbidden_strings(claims, design)
    blind_dir = build_blind_dir(stage_dir)
    audit, audit_call = ({}, "")
    if not hits:
        audit, audit_call = leak_audit(manifest, blind_dir, force=force)
        if audit_call:
            calls.append(audit_call)

    report = artifacts.RedactionReport.model_validate(
        {
            "meta": artifacts.ArtifactMeta(
                artifact="RedactionReport",
                stage="0",
                inputs=inputs or {},
                prompt_versions={
                    "stage0_redact": artifacts.prompt_version("stage0_redact"),
                    "stage0_leak_audit": artifacts.prompt_version("stage0_leak_audit"),
                },
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
    if hits:
        raise RuntimeError(
            "redaction leaks reported values:\n" + json.dumps(hits, indent=2)
        )
    return report, calls
