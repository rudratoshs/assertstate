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
from typing import Any

from assertstate import __version__
from assertstate.contract.loader import load_and_validate

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEMO_ADAPTER = "assertstate.adapters.demo_adapter:DemoAdapter"
_ADAPTERS = {
    "browser-use": "assertstate.adapters.browser_use_adapter:BrowserUseAdapter",
    "http": "assertstate.adapters.http_demo_adapter:HttpDemoAdapter",
    "noop": "assertstate.adapters.noop_adapter:NoopAdapter",
    "demo": _DEMO_ADAPTER,
}


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


def _print_verdict(verdict: Any, run_dir: object, as_json: bool) -> None:
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
    if as_json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"{verdict.verdict.value}: {verdict.passed}P/{verdict.failed}F/"
            f"{verdict.errored}E/{verdict.skipped}S  ({verdict.reason})"
        )
        print(f"evidence: {run_dir}", file=sys.stderr)


def _cmd_run(args: argparse.Namespace) -> int:
    contract, report = load_and_validate(args.contract)
    for e in report.errors:
        print(f"error: {e}", file=sys.stderr)
    if contract is None:
        return 2

    # Config-driven run against a real app described by assertstate.yaml.
    if args.config:
        from assertstate.config.environment import ConfiguredEnvironment
        from assertstate.config.loader import ConfigError, load_config
        from assertstate.contract.loader import hash_contract
        from assertstate.domain.metadata import RunMetadata
        from assertstate.domain.verdict import RunOutcome
        from assertstate.evidence.bundle import write_run
        from assertstate.orchestrator.runner import run_contract

        if args.adapter not in _ADAPTERS:
            print(f"run: unknown --adapter {args.adapter!r} ({sorted(_ADAPTERS)})", file=sys.stderr)
            return 2
        try:
            cfg = load_config(args.config)
            app_cfg = cfg.app(args.app or "")
        except (ConfigError, KeyError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        cenv: object = ConfiguredEnvironment(app_cfg)
        cout = run_contract(contract, cenv, _ADAPTERS[args.adapter], trials=args.trials)  # type: ignore[arg-type]
        cmeta = RunMetadata(
            run_id=args.run_id or f"{args.app}-run",
            assertstate_version=__version__,
            contract_hash=hash_contract(args.contract),
            scenario_id=args.scenario,
            adapter_name=args.adapter,
        )
        cdir = write_run(_REPO_ROOT / ".assertstate", cmeta.run_id, cout.verdict, cmeta)
        _print_verdict(cout.verdict, cdir, args.json)
        return {RunOutcome.PASS: 0, RunOutcome.FAIL: 1, RunOutcome.INCONCLUSIVE: 3}[
            cout.verdict.verdict
        ]

    if args.app not in ("demo", "bounded-demo"):
        print(
            "run: built-in `--app demo` (drain) / `--app bounded-demo` (bounded), or "
            "`--config assertstate.yaml --app <name>` for a real app.",
            file=sys.stderr,
        )
        return 4

    # Built-in demo environments live under demo-app/ (needs it on sys.path).
    demo_dir = _REPO_ROOT / "demo-app"
    if str(demo_dir) not in sys.path:
        sys.path.insert(0, str(demo_dir))

    from assertstate.contract.loader import hash_contract
    from assertstate.domain.metadata import RunMetadata
    from assertstate.domain.verdict import RunOutcome
    from assertstate.evidence.bundle import write_run
    from assertstate.orchestrator.runner import run_contract

    if args.app == "bounded-demo":
        from bounded_environment import BoundedDemoEnvironment  # type: ignore[import-not-found]

        env: object = BoundedDemoEnvironment(buggy=(args.scenario in ("slow_retry", "buggy")))
        adapter_spec = "assertstate.adapters.http_demo_adapter:HttpDemoAdapter"
        settle_mode = "bounded"
    else:
        from environment import DemoEnvironment  # type: ignore[import-not-found]

        env = DemoEnvironment(scenario=args.scenario)
        adapter_spec = _DEMO_ADAPTER
        settle_mode = "drain"

    out = run_contract(contract, env, adapter_spec, trials=args.trials)  # type: ignore[arg-type]
    verdict = out.verdict

    metadata = RunMetadata(
        run_id=args.run_id or f"{args.app}-run",
        assertstate_version=__version__,
        contract_hash=hash_contract(args.contract),
        scenario_id=args.scenario,
        adapter_name=args.app,
        statistics_config={
            "trials": verdict.total_trials,
            "pass_threshold": verdict.pass_threshold,
            "confidence": verdict.confidence,
            "side": verdict.side,
        },
        settlement_config={"mode": settle_mode},
    )
    run_dir = write_run(_REPO_ROOT / ".assertstate", metadata.run_id, verdict, metadata)
    _print_verdict(verdict, run_dir, args.json)
    return {RunOutcome.PASS: 0, RunOutcome.FAIL: 1, RunOutcome.INCONCLUSIVE: 3}[verdict.verdict]


def _cmd_report(args: argparse.Namespace) -> int:
    # Resolve <run-id | path-to-run-dir | path-to-run.json> to a run.json.
    target = Path(args.run)
    if target.is_dir():
        run_json = target / "run.json"
    elif target.suffix == ".json":
        run_json = target
    else:
        run_json = _REPO_ROOT / ".assertstate" / "runs" / args.run / "run.json"
    if not run_json.exists():
        print(f"report: no stored run at {run_json}", file=sys.stderr)
        return 2

    data = json.loads(run_json.read_text(encoding="utf-8"))
    verdict = data.get("verdict", {})
    run_id = data.get("run_id", args.run)
    if args.format == "junit":
        from assertstate.reporters.junit import to_junit

        print(to_junit(verdict, run_id), end="")
    elif args.format == "html":
        from assertstate.reporters.html import to_html

        print(to_html(verdict, run_id), end="")
    else:
        print(json.dumps(data, indent=2))
    return 0


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
    r.add_argument("--config", default=None, help="assertstate.yaml for a real app target")
    r.add_argument("--scenario", default="correct", help="demo app behavior (correct|slow_retry)")
    r.add_argument("--run-id", dest="run_id", default=None)
    r.add_argument("--trials", type=int, default=None)
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=_cmd_run)

    rep = sub.add_parser("report", help="format a stored run (run-id, dir, or run.json)")
    rep.add_argument("run")
    rep.add_argument("--format", choices=("json", "junit", "html"), default="json")
    rep.set_defaults(func=_cmd_report)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
