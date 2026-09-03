"""The unblinded conjecture: why the replicas and the paper differ.

When the targeted arm ran, its agent ended its answer with a `## Diagnosis` section
written with the reported values in hand; that section is the diagnosis and costs no
call. Otherwise one strong call reads the focal analysis's match summaries, the focal
contract and the two closest traces. The output is labelled conjecture and grades
nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import artifacts, focal, llm, paths
from ._prompt import fill
from . import blind, match, replicas

PROMPT = "stage1_diagnose_focal"
TRACE_FIELDS = ("open_choices", "model_formula", "filters", "transformations")

HEADER = (
    "# Divergence diagnosis\n\n"
    "*Unblinded conjecture. Written with the paper's reported values in hand; "
    "it grades nothing.*\n\n"
)


def _load_match(paper_id: str) -> artifacts.ComparableResult | None:
    path = paths.run_dir(paper_id, 1) / "match.json"
    if not path.exists():
        return None
    loaded = artifacts.load(artifacts.ComparableResult, path)
    return loaded if isinstance(loaded, artifacts.ComparableResult) else loaded[0]


def _load_targeted(paper_id: str) -> artifacts.TargetedReconstruction | None:
    path = paths.run_dir(paper_id, 1) / "targeted.json"
    if not path.exists():
        return None
    loaded = artifacts.load(artifacts.TargetedReconstruction, path)
    return loaded if isinstance(loaded, artifacts.TargetedReconstruction) else loaded[0]


def _binding(paper_id: str) -> dict | None:
    try:
        return focal.bind_focal_claim(
            paths.manifest(paper_id),
            blind.claims(paper_id),
            blind.contracts(paper_id),
            paper_id=paper_id,
            allow_llm=False,
        )
    except (ValueError, FileNotFoundError):
        return None


def material(paper_id: str, result: artifacts.ComparableResult, binding: dict) -> str:
    """Focal contract, the focal analysis's match summaries, and the two closest traces."""
    analysis_id = binding["analysis_id"]
    contract = next(
        (c for c in blind.contracts(paper_id) if c.analysis_id == analysis_id), None
    )
    claim_ids = {
        c.claim_id
        for c in blind.claims(paper_id)
        if contract and c.claim_id in set(contract.claim_ids or [])
    }
    summaries = [
        s.model_dump(exclude={"meta"}) for s in result.summaries if s.claim_id in claim_ids
    ]
    closest = match.closest_replicas(result, binding["focal_quantity"]["claim_id"], n=2)
    traces = {t.replica_id: t for t in replicas.load_traces(paper_id)}
    trace_payload = [
        {"replica_id": rid, **{f: getattr(traces[rid], f, None) for f in TRACE_FIELDS}}
        for rid in closest
        if rid in traces
    ]
    payload = {
        "focal_claim": binding["focal_quantity"],
        "estimand_contract": contract.model_dump(exclude={"meta"}) if contract else None,
        "match_summaries": summaries,
        "closest_replica_traces": trace_payload,
    }
    return json.dumps(payload, indent=2, default=str)


def key(paper_id: str) -> dict[str, str]:
    s1 = paths.run_dir(paper_id, 1)
    out = {}
    for name, cls in (
        ("match.json", artifacts.ComparableResult),
        ("targeted.json", artifacts.TargetedReconstruction),
    ):
        path = s1 / name
        if path.exists():
            loaded = artifacts.load(cls, path)
            out[name] = artifacts.content_hash(loaded)
    return out


def _write(out_path: Path, meta_path: Path, body: str, ins: dict, calls: list[str]) -> Path:
    out_path.write_text(HEADER + body.strip() + "\n")
    meta_path.write_text(
        json.dumps(
            {
                "inputs": ins,
                "prompt_versions": {PROMPT: artifacts.prompt_version(PROMPT)},
                "model_calls": calls,
            },
            indent=2,
        )
        + "\n"
    )
    return out_path


def run(paper_id: str, force: bool = False) -> Path:
    s1 = paths.run_dir(paper_id, 1)
    out_path, meta_path = s1 / "diagnosis.md", s1 / "diagnosis.meta.json"
    ins = key(paper_id)
    if out_path.exists() and meta_path.exists() and not force:
        meta = json.loads(meta_path.read_text())
        fresh = meta.get("prompt_versions", {}).get(PROMPT) == artifacts.prompt_version(PROMPT)
        if meta.get("inputs") == ins and fresh:
            return out_path

    targeted = _load_targeted(paper_id)
    if targeted and targeted.triggered and targeted.diagnosis:
        return _write(
            out_path, meta_path,
            f"{targeted.diagnosis}\n\n*Source: the targeted reconstruction agent's own "
            "diagnosis section.*",
            ins, list(targeted.meta.model_calls) if targeted.meta else [],
        )

    result = _load_match(paper_id)
    binding = _binding(paper_id)
    if result is None or binding is None:
        return _write(
            out_path, meta_path,
            "No diagnosis: the focal claim could not be bound to a match table."
            if result is not None else "No diagnosis: Stage 1 produced no match table.",
            ins, [],
        )

    r = llm.call(
        "diagnose",
        fill(PROMPT, material=material(paper_id, result, binding)),
        paper_id=paper_id,
        stage="1",
        tier="strong",
        timeout_s=1800,
    )
    body = r.text.strip() if r.ok and r.text.strip() else f"(diagnosis call failed: {r.error})"
    return _write(out_path, meta_path, body, ins, [r.ledger_id] if r.ledger_id else [])
