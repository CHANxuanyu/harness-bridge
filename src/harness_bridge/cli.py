"""``hbridge`` command line interface.

JSON receipts go to stdout (``--json``: one object with ``"ok": true|false``); diagnostics go to
stderr. Exit status is derived from the error code (see :mod:`harness_bridge.errors`).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

from harness_bridge import __version__
from harness_bridge.config import default_state_dir
from harness_bridge.errors import BridgeError


def _read_json_file(path: str) -> Any:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise BridgeError("INVALID_INPUT", f"cannot read {path}: {exc.strerror}") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise BridgeError("INVALID_INPUT", f"{path} is not valid JSON: {exc}") from None


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state-dir", default=argparse.SUPPRESS, help="state root directory")
    common.add_argument("--advisor-binding", default=argparse.SUPPRESS)
    common.add_argument("--advisor-epoch", type=int, default=argparse.SUPPRESS)
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="machine-readable JSON on stdout",
    )

    parser = argparse.ArgumentParser(
        prog="hbridge",
        description="Harness Bridge: supervised task handoff across coding harnesses "
        "(experimental prototype; default mode is mock, no model calls).",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"hbridge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    from harness_bridge.workbench.app import add_arguments as add_app_arguments

    p = sub.add_parser(
        "app",
        parents=[common],
        help="RepoBridge desktop workbench for native Codex / Claude Code sessions",
    )
    add_app_arguments(p, state_dir=False)

    p = sub.add_parser("doctor", parents=[common], help="non-inference environment diagnostics")
    p.add_argument("--offline", action="store_true", help="do not execute any external binary")

    p = sub.add_parser("create", parents=[common], help="create a task from a TaskSpec file")
    p.add_argument("--task", required=True, help="TaskSpec JSON file ('-' for stdin)")
    p.add_argument("--idempotency-key", required=True)
    p.add_argument("--goal", default=None, help="parent goal (requires current Advisor claim)")

    sub.add_parser("projects", parents=[common], help="discover projects/goals in this state root")
    p = sub.add_parser("goal", parents=[common], help="coordinate a goal and its Advisor session")
    goal_sub = p.add_subparsers(dest="goal_command", required=True)
    p = goal_sub.add_parser("create", parents=[common])
    p.add_argument("--file", required=True, help="GoalSpec JSON")
    p.add_argument("--idempotency-key", required=True)
    p = goal_sub.add_parser("status", parents=[common])
    p.add_argument("goal_id")
    p = goal_sub.add_parser("takeover", parents=[common])
    p.add_argument("goal_id")
    p.add_argument("--file", required=True, help="TakeoverRequest JSON")
    p.add_argument("--idempotency-key", required=True)

    p = goal_sub.add_parser("control", parents=[common])
    p.add_argument("goal_id")
    p.add_argument("--file", required=True, help="GoalControl JSON: pause/resume/cancel/fail")
    p.add_argument("--idempotency-key", required=True)
    p = goal_sub.add_parser("plan", parents=[common])
    p.add_argument("goal_id")
    p.add_argument("--file", required=True, help="immutable child plan batch JSON")
    p.add_argument("--idempotency-key", required=True)
    p = goal_sub.add_parser(
        "integrate", parents=[common], help="freeze approved integration inputs"
    )
    p.add_argument("goal_id")
    p.add_argument("--file", required=True, help="IntegrationSpec JSON")
    p.add_argument("--idempotency-key", required=True)
    p = goal_sub.add_parser("deliver", parents=[common])
    p.add_argument("goal_id")
    p.add_argument("--integration", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--idempotency-key", required=True)
    p = goal_sub.add_parser(
        "cleanup", parents=[common], help="preview or apply conservative worktree cleanup"
    )
    p.add_argument("goal_id")
    p.add_argument("--file", help="apply a reviewed CleanupRequest; omitted means preview only")
    p.add_argument("--idempotency-key")
    p = sub.add_parser("cleanup", parents=[common], help="inspect a cleanup receipt")
    p.add_argument("cleanup_id")
    p = sub.add_parser("delivery", parents=[common], help="inspect or abort a local delivery")
    delivery_sub = p.add_subparsers(dest="delivery_command", required=True)
    for operation in ("status", "abort"):
        p = delivery_sub.add_parser(operation, parents=[common])
        p.add_argument("delivery_id")
        if operation == "abort":
            p.add_argument("--reason", required=True)
    p = sub.add_parser(
        "integration", parents=[common], help="inspect or materialize an integration"
    )
    integration_sub = p.add_subparsers(dest="integration_command", required=True)
    for operation in ("status", "materialize", "cancel", "recover"):
        p = integration_sub.add_parser(operation, parents=[common])
        p.add_argument("integration_id")
    p = integration_sub.add_parser("verify", parents=[common])
    p.add_argument("integration_id")
    p.add_argument("--idempotency-key", required=True)
    p = integration_sub.add_parser("review", parents=[common])
    p.add_argument("integration_id")
    p.add_argument("--file", required=True, help="IntegrationReview JSON")
    p = sub.add_parser("child", parents=[common], help="inspect or materialize a planned child")
    child_sub = p.add_subparsers(dest="child_command", required=True)
    for operation in ("status", "materialize", "preflight"):
        p = child_sub.add_parser(operation, parents=[common])
        p.add_argument("child_id")
    p = child_sub.add_parser("prepare", parents=[common], help="run frozen workspace preparation")
    p.add_argument("child_id")
    p.add_argument("--idempotency-key", required=True)

    p = sub.add_parser("retain-approved", parents=[common], help="pin an unchanged older approval")
    p.add_argument("task_id")

    p = sub.add_parser("run", parents=[common], help="run one executor attempt")
    p.add_argument("task_id")
    p.add_argument("--mode", choices=["mock", "live"], default="mock")
    p.add_argument("--background", action="store_true", help="return a durable worker handle")
    p.add_argument("--idempotency-key", help="required for background dispatch")
    p.add_argument(
        "--allow-model-usage",
        action="store_true",
        help="required (with local config opt-in) for live mode",
    )
    p.add_argument(
        "--stub-binary",
        default=None,
        help="mock mode only: absolute path of a non-model stand-in executable for "
        "the claude-code or codex adapter (contract testing)",
    )

    p = sub.add_parser("job", parents=[common], help="read a background worker handle")
    p.add_argument("job_id")
    p = sub.add_parser("events", parents=[common], help="read incremental task events")
    p.add_argument("task_id")
    p.add_argument("--after", type=int, default=0)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--wait", type=float, default=0, help="bounded read-only wait, 0..30 seconds")

    p = sub.add_parser("status", parents=[common], help="show task state")
    p.add_argument("task_id")

    p = sub.add_parser(
        "desktop", parents=[common], help="inspect or open an existing native session"
    )
    desktop_sub = p.add_subparsers(dest="desktop_command", required=True)
    p = desktop_sub.add_parser("status", parents=[common])
    p.add_argument("task_id")
    p = desktop_sub.add_parser("open", parents=[common])
    p.add_argument("task_id")
    p.add_argument("--idempotency-key", required=True)
    p.add_argument(
        "--retry-legacy-pipe",
        action="store_true",
        help="explicitly retry a confirmed 2.1.291 legacy non-terminal refusal once",
    )

    p = sub.add_parser("list", parents=[common], help="list recent tasks")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("artifacts", parents=[common], help="evidence summary or one artifact")
    p.add_argument("task_id")
    p.add_argument("--attempt", type=int, default=None, help="attempt sequence number")
    p.add_argument(
        "--show", default=None, help="manifest | diff | stdout | stderr | check:<id>:stdout|stderr"
    )

    p = sub.add_parser("review", parents=[common], help="submit a ReviewDecision file")
    p.add_argument("task_id")
    p.add_argument("--file", required=True, help="ReviewDecision JSON file ('-' for stdin)")

    p = sub.add_parser("verify", parents=[common], help="re-run frozen verifiers (no executor)")
    p.add_argument("task_id")

    p = sub.add_parser("recover", parents=[common], help="inspect/repair state after a crash")
    p.add_argument("task_id")
    p.add_argument(
        "--resolve",
        choices=["retry", "fail"],
        default=None,
        help="explicit decision for a BLOCKED or INTERRUPTED task",
    )
    p.add_argument(
        "--acknowledge-unknown",
        action="store_true",
        help="accept that a previous executor's exit could not be confirmed",
    )

    p = sub.add_parser("cancel", parents=[common], help="cancel a task")
    p.add_argument("task_id")
    p.add_argument(
        "--wait",
        type=float,
        default=10.0,
        help="seconds to wait for a live runner to confirm (default 10)",
    )
    p.add_argument(
        "--acknowledge-unknown",
        action="store_true",
        help="cancel an INTERRUPTED task whose executor exit is unknown",
    )

    p = sub.add_parser("demo", parents=[common], help="offline demo with the fake executor")
    p.add_argument("--scenario", choices=["success", "bug-then-repair"], required=True)
    p.add_argument("--workdir", default=None, help="directory for the demo (default: temp dir)")
    p.add_argument("--cleanup", action="store_true", help="delete the demo directory afterwards")

    sub.add_parser(
        "env",
        parents=[common],
        help="runtime environment (dev/test/prod), isolation verdict, version and code SHA",
    )
    p = sub.add_parser("diag", parents=[common], help="local diagnostics and product events")
    diag_sub = p.add_subparsers(dest="diag_command", required=True)
    for operation in ("summary", "export"):
        p = diag_sub.add_parser(operation, parents=[common])
        p.add_argument("--since", default=None, help="ISO time lower bound (UTC, ...Z)")
        p.add_argument("--until", default=None, help="ISO time upper bound (UTC, ...Z)")
        p.add_argument(
            "--env",
            action="append",
            choices=["prod", "dev", "test", "all"],
            default=None,
            help="records of these environments (default: the current HBRIDGE_ENV profile)",
        )
        if operation == "summary":
            p.add_argument("--format", choices=["json", "csv"], default="json")
        else:
            p.add_argument("--out", default=None, help="new .zip path (default: state dir)")
    p = diag_sub.add_parser("trace", parents=[common], help="records of one operation/alias")
    for flag in ("--op", "--session", "--run", "--msg"):
        p.add_argument(flag, default=None)
    p = diag_sub.add_parser("config", parents=[common], help="show or change local settings")
    p.add_argument("--diagnostics", choices=["on", "off"], default=None)
    p.add_argument("--product-events", choices=["on", "off"], default=None)
    diag_sub.add_parser("events", parents=[common], help="the event dictionary")
    return parser


def _install_signal_handlers(flag: Any) -> None:
    def handler(signum: int, _frame: Any) -> None:
        if flag.reason is None:
            flag.reason = "interrupted"
            sys.stderr.write(f"hbridge: received signal {signum}; stopping owned processes\n")
        else:
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    from harness_bridge.coordination import AdvisorClaim, parse_contract
    from harness_bridge.service import Bridge, StopFlag

    if args.command in ("env", "diag"):
        return _observability(args)
    state_dir = Path(getattr(args, "state_dir", None) or default_state_dir())
    cmd = args.command

    if cmd == "demo":
        from harness_bridge.demo import run_demo

        report = run_demo(
            args.scenario,
            workdir=Path(args.workdir) if args.workdir else None,
            cleanup=args.cleanup,
        )
        if not report.get("demo_passed"):
            raise BridgeError("INTERNAL_ERROR", "demo did not pass", details={"report": report})
        return report

    if cmd == "doctor":
        from harness_bridge.doctor import run_doctor

        return run_doctor(state_dir, offline=args.offline)

    flag = StopFlag()
    binding, epoch = getattr(args, "advisor_binding", None), getattr(args, "advisor_epoch", None)
    claim = None
    if binding is not None or epoch is not None:
        claim = parse_contract(AdvisorClaim, {"binding_id": binding, "epoch": epoch})
    bridge = Bridge(state_dir, stop_flag=flag, advisor_claim=claim)
    try:
        if cmd == "projects":
            return bridge.coordination.projects()
        if cmd == "cleanup":
            return bridge.cleanup.status(args.cleanup_id)
        if cmd == "goal" and args.goal_command == "cleanup":
            if bool(args.file) != bool(args.idempotency_key):
                raise BridgeError(
                    "INVALID_INPUT", "cleanup apply requires both --file and --idempotency-key"
                )
            return (
                bridge.cleanup.apply(args.goal_id, _read_json_file(args.file), args.idempotency_key)
                if args.file
                else bridge.cleanup.preview(args.goal_id)
            )
        if cmd == "delivery":
            if args.delivery_command == "abort":
                return bridge.deliveries.abort(args.delivery_id, args.reason)
            return bridge.deliveries.status(args.delivery_id)
        if cmd == "goal" and args.goal_command == "deliver":
            return bridge.deliveries.deliver(
                args.goal_id,
                {"integration_id": args.integration, "branch": args.branch},
                args.idempotency_key,
            )
        if cmd == "integration":
            if args.integration_command == "verify":
                _install_signal_handlers(flag)
                return bridge.integration_checks.verify(args.integration_id, args.idempotency_key)
            if args.integration_command == "review":
                return bridge.integration_checks.review(
                    args.integration_id, _read_json_file(args.file)
                )
            if args.integration_command == "cancel":
                return bridge.integration_checks.cancel(args.integration_id)
            if args.integration_command == "recover":
                return bridge.integration_checks.recover(args.integration_id)
            if args.integration_command == "materialize":
                return bridge.integrations.materialize(args.integration_id)
            return bridge.integrations.status(args.integration_id)
        if cmd == "child":
            if args.child_command == "prepare":
                _install_signal_handlers(flag)
                return bridge.preparations.prepare(args.child_id, args.idempotency_key)
            if args.child_command == "materialize":
                return bridge.materialize(args.child_id)
            if args.child_command == "preflight":
                return bridge.child_preflight(args.child_id)
            return bridge.plans.status(args.child_id)
        if cmd == "retain-approved":
            return bridge.retain_approved(args.task_id)
        if cmd == "goal":
            if args.goal_command == "integrate":
                return bridge.integrations.freeze(
                    args.goal_id, _read_json_file(args.file), args.idempotency_key
                )
            if args.goal_command == "plan":
                return bridge.plans.submit(
                    args.goal_id, _read_json_file(args.file), args.idempotency_key, claim
                )
            if args.goal_command == "control":
                receipt = bridge.coordination.control(
                    args.goal_id, _read_json_file(args.file), args.idempotency_key, claim
                )
                return {
                    "request_receipt": receipt,
                    "goal": bridge.coordination.status(args.goal_id),
                }
            if args.goal_command == "create":
                return bridge.coordination.create(_read_json_file(args.file), args.idempotency_key)
            if args.goal_command == "takeover":
                return bridge.coordination.takeover(
                    args.goal_id, _read_json_file(args.file), args.idempotency_key
                )
            return bridge.coordination.status(args.goal_id)
        if cmd == "create":
            return bridge.create(
                _read_json_file(args.task), args.idempotency_key, goal_id=args.goal
            )
        if cmd == "run":
            _install_signal_handlers(flag)
            return bridge.run(
                args.task_id,
                mode=args.mode,
                allow_model_usage=args.allow_model_usage,
                executor_binary=args.stub_binary,
                background=args.background,
                idempotency_key=args.idempotency_key,
            )
        if cmd == "job":
            return bridge.jobs.status(args.job_id)
        if cmd == "events":
            return bridge.jobs.events(
                args.task_id, after=args.after, limit=args.limit, wait_seconds=args.wait
            )
        if cmd == "status":
            return bridge.status(args.task_id)
        if cmd == "desktop":
            from harness_bridge.desktop import DesktopSessions

            desktop = DesktopSessions(bridge)
            if args.desktop_command == "open":
                return desktop.open(
                    args.task_id, args.idempotency_key, retry_legacy_pipe=args.retry_legacy_pipe
                )
            return desktop.status(args.task_id)
        if cmd == "list":
            return {
                "tasks": [
                    {"task_id": t.task_id, "state": t.state.value, "updated_at": t.updated_at}
                    for t in bridge.store.list_tasks(args.limit)
                ]
            }
        if cmd == "artifacts":
            return bridge.artifacts(args.task_id, attempt_seq=args.attempt, show=args.show)
        if cmd == "review":
            return bridge.review(args.task_id, _read_json_file(args.file))
        if cmd == "verify":
            _install_signal_handlers(flag)
            return bridge.verify(args.task_id)
        if cmd == "recover":
            _install_signal_handlers(flag)
            return bridge.recover(
                args.task_id,
                resolve=args.resolve,
                acknowledge_unknown=args.acknowledge_unknown,
            )
        if cmd == "cancel":
            return bridge.cancel(
                args.task_id,
                wait_seconds=args.wait,
                acknowledge_unknown=args.acknowledge_unknown,
            )
        raise BridgeError("USAGE_ERROR", f"unknown command {cmd!r}")
    finally:
        bridge.close()


def _observability(args: argparse.Namespace) -> dict[str, Any]:
    """Read-only except ``diag config`` (settings) and ``diag export`` (one new local zip)."""
    from harness_bridge import runtime_env
    from harness_bridge.observability import report, schema
    from harness_bridge.observability.recorder import load_settings, save_settings

    explicit = getattr(args, "state_dir", None)
    state_dir = Path(explicit).expanduser() if explicit else None
    if args.command == "env":
        return runtime_env.describe(state_dir)
    target = state_dir or default_state_dir()
    try:
        profile = runtime_env.resolve(target, dict(os.environ))
    except BridgeError:
        if args.diag_command not in ("events",):
            raise
        profile = None
    command = args.diag_command
    if command == "events":
        return {"schema_version": schema.SCHEMA_VERSION, "events": schema.describe_events()}
    if command == "config":
        changes = {
            key: value == "on"
            for key, value in (
                ("diagnostics", args.diagnostics),
                ("product_events", args.product_events),
            )
            if value is not None
        }
        if changes:
            save_settings(target, **changes)
        return {"settings": load_settings(target, dict(os.environ)), "changed": sorted(changes)}
    if command == "trace":
        try:
            return report.trace(
                target, op=args.op, session=args.session, run=args.run, msg=args.msg
            )
        except ValueError as exc:
            raise BridgeError("USAGE_ERROR", str(exc)) from None
    assert profile is not None
    selected = args.env or [profile.name]
    envs = None if "all" in selected else set(selected)
    if command == "summary":
        summary = report.summarize(
            target, envs=envs, since=args.since, until=args.until, env=dict(os.environ)
        )
        return {"content": report.to_csv(summary)} if args.format == "csv" else summary
    try:
        return report.export_bundle(
            target,
            Path(args.out) if args.out else None,
            envs=envs,
            profile=profile.describe(),
            since=args.since,
            until=args.until,
        )
    except FileExistsError as exc:
        raise BridgeError("USAGE_ERROR", str(exc)) from None


def _render_human(result: dict[str, Any]) -> str:
    lines = []
    for key, value in result.items():
        if key == "content" and isinstance(value, str):
            lines.append(value)
        elif isinstance(value, dict | list):
            lines.append(f"{key}: {json.dumps(value, indent=2, ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if args.command == "app":
        from harness_bridge.workbench.app import run as run_app

        return run_app(args)
    as_json = bool(getattr(args, "json", False))
    try:
        result = _dispatch(args)
    except BridgeError as err:
        if as_json:
            print(json.dumps({"ok": False, "error": err.to_dict()}, ensure_ascii=False))
        else:
            report = err.details.get("report") if err.details else None
            if report:
                print(_render_human(report))
        print(f"hbridge: error [{err.code}]: {err.message}", file=sys.stderr)
        return err.exit_status
    except KeyboardInterrupt:
        print("hbridge: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        if os.environ.get("HBRIDGE_DEBUG"):
            raise
        internal = BridgeError("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")
        if as_json:
            print(json.dumps({"ok": False, "error": internal.to_dict()}, ensure_ascii=False))
        print(f"hbridge: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return internal.exit_status
    if as_json:
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    else:
        print(_render_human(result))
    return 0
