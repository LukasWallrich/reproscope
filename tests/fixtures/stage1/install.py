"""Install the synthetic fixture paper as corpus/_fixture and runs/_fixture/stage0.

Stage 1 reads a paper from the corpus and stage 0's outputs from the run
directory. The fixture supplies both so the whole stage can run end to end without
stage 0. `blind_contract.json` is derived here rather than stored, so it cannot
drift out of step with claims.json.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent
PAPER_ID = "_fixture"
BLIND_FIELDS = {"value", "precision", "uncertainty"}


def blind_contract(claims: list[dict], contracts: list[dict]) -> dict:
    """The replica's CONTRACT.json: contracts plus claims with their values removed."""
    stripped = [{k: v for k, v in c.items() if k not in BLIND_FIELDS} for c in claims]
    return {"contracts": contracts, "claims": stripped}


def install(root: Path) -> tuple[Path, Path]:
    root = Path(root)
    corpus = root / "corpus" / PAPER_ID
    stage0 = root / "runs" / PAPER_ID / "stage0"
    (corpus / "data").mkdir(parents=True, exist_ok=True)
    stage0.mkdir(parents=True, exist_ok=True)

    shutil.copy2(FIXTURE / "manifest.json", corpus / "manifest.json")
    shutil.copy2(FIXTURE / "paper.txt", corpus / "paper.txt")
    for f in sorted((FIXTURE / "data").iterdir()):
        shutil.copy2(f, corpus / "data" / f.name)

    claims = json.loads((FIXTURE / "claims.json").read_text())
    contracts = json.loads((FIXTURE / "contracts.json").read_text())
    shutil.copy2(FIXTURE / "claims.json", stage0 / "claims.json")
    shutil.copy2(FIXTURE / "contracts.json", stage0 / "contracts.json")
    shutil.copy2(FIXTURE / "redacted_methods.md", stage0 / "redacted_methods.md")
    (stage0 / "blind_contract.json").write_text(
        json.dumps(blind_contract(claims, contracts), indent=2) + "\n"
    )
    (stage0 / "redaction_report.json").write_text(
        json.dumps(
            {"removed_spans": [{"kind": "results_sentence", "location": "Results"}],
             "scan_hits": [], "scan_clean": True,
             "leakage_audit_verdict": "clean", "state": "complete"},
            indent=2,
        )
        + "\n"
    )
    (stage0 / "readiness.json").write_text(
        json.dumps(
            {"files": [{"path": "data/study1.csv", "format": "csv", "rows": 60, "cols": 4}],
             "unit_of_observation": "participant", "keys": ["pid"],
             "missing_sentinels": [], "variable_bindings": [],
             "per_analysis_state": {"a1": "complete"}, "state": "complete"},
            indent=2,
        )
        + "\n"
    )
    return corpus, stage0


if __name__ == "__main__":
    print(install(FIXTURE.parents[2]))
