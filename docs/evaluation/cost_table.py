"""Per-paper spend: pilot before the fixes, the post-fix rerun, and a clean v0.1 estimate.

Rows with ts >= runs/logs/rerun_started_at.txt are the post-fix rerun (stages 1-3 +
report on the existing replica outputs). A clean v0.1 run = the 8-replica lineup's
agent runs (taken from the pilot ledger) + the rerun's non-replica stages 1-3 +
stage 0 (not rerun; projected separately).
Writes docs/evaluation/cost_table.json. Usage: .venv/bin/python docs/evaluation/cost_table.py
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
START = (ROOT / "runs/logs/rerun_started_at.txt").read_text().strip()
PAPERS = ["Ohtsubo_EvoHumanBehavior_2014_zlm2", "Hurst_EvoHumanBehavior_2017_yypJ",
          "Axt_JournExpSocPsych_2018_zK2", "Petersen_Cognition_2017_yJwG",
          "Hertel_ClinPsychSci_2018_YabW"]
LINEUP = {"opus_1", "fable_1", "luna_1", "luna_2", "glm_1", "glm_2", "deepseek_1", "deepseek_2"}


def load(paper):
    p = ROOT / "runs" / paper / "ledger.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def sums(rows):
    return {"calls": len(rows), "ok": sum(1 for r in rows if r.get("ok")),
            "tokens": sum(int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0) for r in rows),
            "cash": round(sum(float(r.get("cost_usd") or 0) for r in rows), 4),
            "equiv": round(sum(float(r.get("cost_usd_equiv") or 0) for r in rows), 4)}


out = {"start": START, "papers": {}}
for paper in PAPERS:
    rows = load(paper)
    before = [r for r in rows if r["ts"] < START]
    rerun = [r for r in rows if r["ts"] >= START]
    by_stage = lambda rs: {st: sums([r for r in rs if str(r.get("stage")) == st]) for st in sorted({str(r.get("stage")) for r in rs})}
    replica_rows = [r for r in before if r.get("step") == "replica" and r.get("ok") and r.get("replica_id") in LINEUP]
    # one agent run per lineup replica: keep the last successful row per replica id
    last = {}
    for r in replica_rows:
        last[r["replica_id"]] = r
    lineup_replicas = sums(list(last.values()))
    rerun_nonreplica = sums([r for r in rerun if r.get("step") != "replica"])
    # Single clean pass: the last successful call per step (the rerun repeated the
    # strong steps across retry passes and after trace changes; those repeats are
    # not part of a clean run).
    last_ok = {}
    for r in rerun:
        if r.get("ok") and r.get("step") != "replica":
            last_ok[(r.get("stage"), str(r.get("step")))] = r
    single_pass = sums(list(last_ok.values()))
    out["papers"][paper] = {
        "before": {"total": sums(before), "by_stage": by_stage(before)},
        "rerun": {"total": sums(rerun), "by_stage": by_stage(rerun),
                  "by_step": {k: sums([r for r in rerun if f"{r.get('stage')}:{str(r.get('step')).split(':')[0]}" == k])
                              for k in sorted({f"{r.get('stage')}:{str(r.get('step')).split(':')[0]}" for r in rerun})}},
        "lineup_replica_runs": lineup_replicas,
        "rerun_single_pass": single_pass,
        "clean_v01_stages123": {"cash": round(lineup_replicas["cash"] + single_pass["cash"], 4),
                                "equiv": round(lineup_replicas["equiv"] + single_pass["equiv"], 4)},
    }
(ROOT / "docs/evaluation/cost_table.json").write_text(json.dumps(out, indent=2))
print(f"{'paper':<10}{'before cash':>12}{'before eq':>11}{'1pass cash':>12}{'1pass eq':>10}{'lineup cash':>12}{'lineup eq':>10}{'v01 s1-3 cash':>14}{'v01 s1-3 eq':>12}")
for paper, p in out["papers"].items():
    b, r, l, c = p["before"]["total"], p["rerun_single_pass"], p["lineup_replica_runs"], p["clean_v01_stages123"]
    print(f"{paper[:9]:<10}{b['cash']:>12.3f}{b['equiv']:>11.2f}{r['cash']:>12.3f}{r['equiv']:>10.2f}{l['cash']:>12.3f}{l['equiv']:>10.2f}{c['cash']:>14.3f}{c['equiv']:>12.2f}")
print("\nrerun by step (all papers):")
agg = defaultdict(lambda: defaultdict(float))
for p in out["papers"].values():
    for k, v in p["rerun"]["by_step"].items():
        for f in ("calls", "ok", "cash", "equiv"):
            agg[k][f] += v[f]
for k, v in sorted(agg.items()):
    print(f"  {k:<28} calls={int(v['calls']):<4} ok={int(v['ok']):<4} cash={v['cash']:.3f} equiv={v['equiv']:.2f}")
