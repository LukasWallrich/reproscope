"""The unblinded conjecture: why the replicas and the paper differ.

One strong non-agentic call over everything Stage 1 produced, plus the paper.
The output is labelled as conjecture and is never used to grade anything.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import artifacts, llm, paths
from ._prompt import fill
from . import blind, replicas

MAX_PAPER = 60_000
MAX_SCRIPT = 12_000


def _section(title: str, body: str) -> str:
    return f"\n\n## {title}\n\n{body.strip()}\n"


def material(paper_id: str) -> str:
    parts = [_section("Paper", blind.paper_text(paper_id)[:MAX_PAPER])]
    s1 = paths.run_dir(paper_id, 1)

    contracts = [c.model_dump(exclude={"meta"}) for c in blind.contracts(paper_id)]
    claims = [c.model_dump(exclude={"meta"}) for c in blind.claims(paper_id)]
    parts.append(_section("Estimand contracts", json.dumps(contracts, indent=2, default=str)))
    parts.append(_section("Reported claims", json.dumps(claims, indent=2, default=str)))

    for trace in replicas.load_traces(paper_id):
        out_dir = blind.replica_dir(paper_id, trace.replica_id) / "work" / "out"
        script = replicas.find_script(out_dir)
        body = trace.model_dump_json(indent=2, exclude={"meta"})
        parts.append(_section(f"Replica {trace.replica_id} — trace", body))
        if script:
            parts.append(
                _section(
                    f"Replica {trace.replica_id} — {script.name}",
                    f"```\n{script.read_text()[:MAX_SCRIPT]}\n```",
                )
            )
        results = out_dir / "results.json"
        if results.exists():
            parts.append(
                _section(f"Replica {trace.replica_id} — results", results.read_text()[:8_000])
            )

    for name in ("match.json", "targeted.json", "rerun.json"):
        p = s1 / name
        if p.exists():
            parts.append(_section(name, p.read_text()[:40_000]))
    return "".join(parts)


def inputs(paper_id: str) -> dict[str, str]:
    s1 = paths.run_dir(paper_id, 1)
    return {
        name: artifacts.sha256_file(s1 / name)
        for name in ("match.json", "targeted.json", "rerun.json")
        if (s1 / name).exists()
    }


def run(paper_id: str, force: bool = False) -> Path:
    s1 = paths.run_dir(paper_id, 1)
    out_path, meta_path = s1 / "diagnosis.md", s1 / "diagnosis.meta.json"
    key = inputs(paper_id)
    if out_path.exists() and meta_path.exists() and not force:
        if json.loads(meta_path.read_text()).get("inputs") == key:
            return out_path
    r = llm.call(
        "diagnose",
        fill("stage1_diagnose", material=material(paper_id)),
        paper_id=paper_id,
        stage="1",
        tier="strong",
        timeout_s=1800,
    )
    text = r.text.strip() if r.ok and r.text.strip() else f"(diagnosis call failed: {r.error})"
    out_path.write_text(
        f"<!-- prompt stage1_diagnose@{artifacts.prompt_version('stage1_diagnose')}"
        f" call {r.ledger_id} -->\n\n{text}\n"
    )
    meta_path.write_text(
        json.dumps({"inputs": key, "model_calls": [r.ledger_id]}, indent=2) + "\n"
    )
    return out_path
