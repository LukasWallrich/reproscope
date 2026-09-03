"""python -m reproscope run|ledger|probe"""

from __future__ import annotations

import argparse
import importlib
import sys

from . import config, ledger, llm

STAGES = ("0", "1", "2", "3", "report")

# Step names = output stems, per stage. `report` has no steps: it is one artifact.
STAGE_STEPS = {
    "0": ("extract", "arbitrate", "contracts", "readiness", "redact"),
    "1": ("replicas", "match", "targeted", "rerun", "diagnose"),
    "2": ("causal_language", "mde", "alignment", "broad"),
    "3": ("focal", "enumerate", "paper_level", "screen", "execute", "rank", "interpret"),
}


def _force_steps(raw: list[str] | None) -> set[str]:
    """Validate `--force-step <step> [<step> ...]` against every stage's step names."""
    steps = set(raw or [])
    known = {name for names in STAGE_STEPS.values() for name in names}
    unknown = steps - known
    if unknown:
        raise SystemExit(f"--force-step: unknown step(s) {sorted(unknown)} (expected one of {sorted(known)})")
    return steps


def cmd_run(args: argparse.Namespace) -> int:
    force_steps = _force_steps(args.force_step)
    for stage in args.stages:
        mod = importlib.import_module("reproscope.report" if stage == "report" else f"reproscope.stage{stage}")
        print(f"== stage {stage} — {args.paper_id}", flush=True)
        # Only the steps that belong to this stage apply; a name for another stage is
        # simply not present here, so mixing --stages 0 1 --force-step match works.
        stage_force_steps = force_steps & set(STAGE_STEPS.get(stage, ()))
        if stage_force_steps:
            mod.run(args.paper_id, force=args.force, force_steps=stage_force_steps)
        else:
            mod.run(args.paper_id, force=args.force)
    print(ledger.format_summary(args.paper_id))
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    print(ledger.format_summary(args.paper_id))
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    print(f"{'label':<20}{'route':<12}{'model':<28}{'ok':<4}{'s':>7}{'cost $':>10}  reply")
    failures = 0
    for label, spec in config.all_specs():
        r = llm.call(
            "probe",
            "Reply with exactly: OK",
            paper_id=args.paper_id,
            stage="probe",
            route=spec.route,
            model=spec.model,
            timeout_s=args.timeout,
        )
        failures += 0 if r.ok else 1
        reply = (r.text or r.error or "")[:60].replace("\n", " ")
        print(
            f"{label:<20}{r.route:<12}{r.model:<28}{str(r.ok):<4}"
            f"{r.duration_s:>7.1f}{r.cost_usd:>10.5f}  {reply}"
        )
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reproscope")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run pipeline stages for one paper")
    run.add_argument("paper_id")
    run.add_argument("--stages", nargs="+", default=list(STAGES), choices=STAGES)
    run.add_argument("--force", action="store_true", help="rerun stages whose done.json matches")
    run.add_argument(
        "--force-step", nargs="+", metavar="STEP",
        help="rerun only the named steps of the listed --stages, e.g. "
             "--stages 1 --force-step match targeted (--force forces every step instead)",
    )
    run.set_defaults(func=cmd_run)

    led = sub.add_parser("ledger", help="print the model-call summary for one paper")
    led.add_argument("paper_id")
    led.set_defaults(func=cmd_ledger)

    probe = sub.add_parser("probe", help="one tiny live call per configured route/model")
    probe.add_argument("--paper-id", default="_probe")
    probe.add_argument("--timeout", type=int, default=300)
    probe.set_defaults(func=cmd_probe)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
