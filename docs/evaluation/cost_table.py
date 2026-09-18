"""Observed costs for the explicit evaluation cohort, including all failed attempts."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from reproscope import cohort


def sums(rows):
    return {"calls": len(rows), "ok": sum(bool(r.get("ok")) for r in rows),
            "cash": round(sum(float(r.get("cost_usd") or 0) for r in rows), 6),
            "equiv": round(sum(float(r.get("cost_usd_equiv") or 0) for r in rows), 6)}


def build(manifest):
    cohort.validate_runs(manifest, ROOT / "runs")
    out = {"cohort_fingerprint": manifest["fingerprint"], "papers": {},
           "cost_policy": "All ledger attempts in each selected run, including failures and reruns."}
    for entry in manifest["papers"]:
        pid = entry["run_id"]
        ledger = ROOT / "runs" / pid / "ledger.jsonl"
        rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()] if ledger.exists() else []
        by_stage = defaultdict(list)
        for row in rows:
            by_stage[str(row.get("stage"))].append(row)
        out["papers"][pid] = {"total": sums(rows), "by_stage": {k: sums(v) for k, v in by_stage.items()},
                               "ledger_present": ledger.exists()}
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", type=Path)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "docs/evaluation")
    args = parser.parse_args(argv)
    result = build(cohort.load(args.cohort))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    target = args.out_dir / "cost_table.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(target)


if __name__ == "__main__":
    main()
