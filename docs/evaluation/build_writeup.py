"""Render a self-contained evaluation from one cohort's metrics and observed costs."""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from reproscope import cohort


def pct(value):
    return "n/a" if value is None else f"{value:.1%}"


def table(headers, rows):
    esc = lambda x: html.escape(str(x))
    return '<table><thead><tr>' + ''.join(f'<th>{esc(x)}</th>' for x in headers) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{esc(x)}</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table>'


def render(evaluation, costs, manifest):
    if (evaluation.get("cohort") or {}).get("fingerprint") != manifest["fingerprint"]:
        raise ValueError("evaluation does not match the selected cohort; regenerate it")
    if costs.get("cohort_fingerprint") != manifest["fingerprint"]:
        raise ValueError("cost table does not match the selected cohort; regenerate it")
    expected = {p["run_id"] for p in manifest["papers"]}
    if set(evaluation["papers"]) != expected or set(costs["papers"]) != expected:
        raise ValueError("metrics and cost tables must contain exactly the cohort runs")
    body = [f'<h1>Pipeline evaluation: {html.escape(manifest["name"])}</h1>',
            f'<p>{html.escape(manifest.get("purpose", ""))}</p>',
            f'<p>{html.escape(evaluation.get("validation_status", "Validation status not established"))}.</p>',
            '<p>Coverage is the proportion of eligible planned requests with accepted numeric outputs. '
            'Conditional agreement is A+B among those outputs. End-to-end success is A+B across '
            'all eligible planned requests, including failed and incomplete attempts. These are '
            'development measures; claim rows within an analysis are not independent observations.</p>']
    preflight = evaluation.get("preflight", {})
    if not preflight.get("all_runs_release_ready", False):
        body.append('<p><strong>Semantic finalisation has not passed. These scores describe development outputs and must not be interpreted as validated reproduction evidence.</strong></p>')
    for pid, status in preflight.get("runs", {}).items():
        for reason in status.get("semantic_blockers", []):
            body.append('<p>' + html.escape(pid + ': ' + reason) + '</p>')
    rows = []
    for family in evaluation["families"]:
        m = family["match"]["all"]
        rows.append([family["label"], family["launched"], family["ran"], m["n"],
                     pct(m["coverage"]), pct(m["share_ab"]), pct(m["end_to_end_ab"]),
                     pct(family.get("paper_macro_end_to_end")), pct(family.get("analysis_macro_end_to_end")), pct(m.get("exact_precision_share"))])
    body.append(table(["Family", "Planned", "Ran", "Requests", "Coverage", "Conditional A+B",
                       "End-to-end A+B", "Mean across papers", "Mean across bound analyses", "Exact at reported precision (checked outputs)"], rows))
    rows = []
    for entry in manifest["papers"]:
        pid = entry["run_id"]
        total = costs["papers"][pid]["total"]
        rows.append([pid, entry["split"], len(entry["replicas"]), total["calls"],
                     f'${total["cash"]:.3f}', f'${total["equiv"]:.3f}'])
    body.append('<p>Observed costs include every ledger attempt in the selected run. '
                'Subscription list-price equivalents are estimates, not metered charges.</p>')
    body.append(table(["Run", "Split", "Planned replicas", "Calls", "Metered", "Subscription equivalent"], rows))
    if manifest.get("exclusions"):
        body.append(table(["Excluded paper", "Reason"], [[x["paper_id"], x["reason"]] for x in manifest["exclusions"]]))
    body.append('<p>Run-level limitations, unresolved audits, and data coverage are recorded in the per-paper artifacts. '
                'This aggregate does not establish that every requested analysis was identified or implemented correctly.</p>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Pipeline evaluation</title><style>body{max-width:1100px;margin:3rem auto;padding:0 1rem;font:17px/1.6 system-ui;color:#202830}table{border-collapse:collapse;width:100%;font-size:14px;margin:2rem 0}th,td{text-align:left;border-bottom:1px solid #ccd3d8;padding:8px}th{background:#eef1f3}h1{line-height:1.2}</style><main>''' + '\n'.join(body) + '</main></html>\n'


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", type=Path)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "docs/evaluation")
    args = parser.parse_args(argv)
    ev = json.loads((args.out_dir / "pilot_eval.json").read_text())
    cost = json.loads((args.out_dir / "cost_table.json").read_text())
    target = args.out_dir / "PILOT_EVALUATION.html"
    target.write_text(render(ev, cost, cohort.load(args.cohort)))
    print(target)


if __name__ == "__main__":
    main()
