"""AssertState CLI (DEVELOPMENT.md §8).

P0 commands: `validate` (works now), `run` and `report` (land in later P0 tasks).
Exit codes: 0 ok · 2 invalid/not-found · (run) 1 FAIL · 3 INCONCLUSIVE · 4 ERROR-dominated.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from assertstate import __version__
from assertstate.contract.loader import load_and_validate

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEMO_ADAPTER = "assertstate.adapters.demo_adapter:DemoAdapter"


def _cmd_validate(args: argparse.Namespace) -> int:
    contract, report = load_and_validate(args.contract)
    for w in report.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if report.ok and contract is not None:
        print(
            f"ok: {args.contract} is a valid contract "
            f"({len(contract.expect)} expect, {len(contract.forbid)} forbid, "
            f"{contract.statistics.trials} trials)"
        )
        return 0
    for e in report.errors:
        print(f"error: {e}", file=sys.stderr)
    return 2


def _cmd_run(args: argparse.Namespace) -> int:
    contract, report = load_and_validate(args.contract)
    for e in report.errors:
        print(f"error: {e}", file=sys.stderr)
    if contract is None:
        return 2

    if args.app != "demo":
        print(
            "run: P0 wires only the built-in demo app (`--app demo`). A generic app target "
            "needs config (P0-04) + the Browser Use adapter (P0-14), both pending.",
            file=sys.stderr,
        )
        return 4

    # Built-in demo environment lives under demo-app/ (needs it on sys.path).
    demo_dir = _REPO_ROOT / "demo-app"
    if str(demo_dir) not in sys.path:
        sys.path.insert(0, str(demo_dir))
    from environment import DemoEnvironment  # type: ignore[import-not-found]

    from assertstate.contract.loader import hash_contract
    from assertstate.domain.metadata import RunMetadata
    from assertstate.domain.verdict import RunOutcome
    from assertstate.evidence.bundle import write_run
    from assertstate.orchestrator.runner import run_contract

    env = DemoEnvironment(scenario=args.scenario)
    out = run_contract(contract, env, _DEMO_ADAPTER, trials=args.trials)
    verdict = out.verdict

    metadata = RunMetadata(
        run_id=args.run_id or "demo-run",
        assertstate_version=__version__,
        contract_hash=hash_contract(args.contract),
        scenario_id=args.scenario,
        adapter_name="demo",
        statistics_config={
            "trials": verdict.total_trials,
            "pass_threshold": verdict.pass_threshold,
            "confidence": verdict.confidence,
            "side": verdict.side,
        },
        settlement_config={"mode": "drain"},
    )
    run_dir = write_run(_REPO_ROOT / ".assertstate", metadata.run_id, verdict, metadata)

    summary = {
        "verdict": verdict.verdict.value,
        "trials": verdict.total_trials,
        "valid": verdict.valid_trials,
        "pass": verdict.passed,
        "fail": verdict.failed,
        "error": verdict.errored,
        "skipped": verdict.skipped,
        "wilson_lower": verdict.wilson_lower,
        "reason": verdict.reason,
        "evidence": str(run_dir),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"{verdict.verdict.value}: {verdict.passed}P/{verdict.failed}F/"
            f"{verdict.errored}E/{verdict.skipped}S  ({verdict.reason})"
        )
        print(f"evidence: {run_dir}", file=sys.stderr)

    return {RunOutcome.PASS: 0, RunOutcome.FAIL: 1, RunOutcome.INCONCLUSIVE: 3}[verdict.verdict]


def _cmd_report(args: argparse.Namespace) -> int:
    print("report: the artifact store/reporters are not wired yet (P0-05/P0-19).", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="assertstate", description="Deterministic acceptance harness.")
    p.add_argument("--version", action="version", version=f"assertstate {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="load + validate a contract")
    v.add_argument("contract")
    v.set_defaults(func=_cmd_validate)

    r = sub.add_parser("run", help="run a contract (P0: --app demo)")
    r.add_argument("contract")
    r.add_argument("--adapter", default="browser-use")
    r.add_argument("--app", default=None)
    r.add_argument("--scenario", default="correct", help="demo app behavior (correct|slow_retry)")
    r.add_argument("--run-id", dest="run_id", default=None)
    r.add_argument("--trials", type=int, default=None)
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=_cmd_run)

    rep = sub.add_parser("report", help="format a stored run (P0-05/P0-19)")
    rep.add_argument("run")
    rep.set_defaults(func=_cmd_report)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
