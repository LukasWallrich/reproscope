"""python -m reproscope run|ledger|probe"""

from __future__ import annotations

import argparse
import importlib
import sys

from . import config, ledger, llm

STAGES = ("0", "1", "2", "3")


def cmd_run(args: argparse.Namespace) -> int:
    for stage in args.stages:
        mod = importlib.import_module(f"reproscope.stage{stage}")
        print(f"== stage {stage} — {args.paper_id}", flush=True)
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
