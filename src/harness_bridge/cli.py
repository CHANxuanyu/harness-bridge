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

    p = sub.add_parser("doctor", parents=[common], help="non-inference environment diagnostics")
    p.add_argument("--offline", action="store_true", help="do not execute any external binary")

    p = sub.add_parser("create", parents=[common], help="create a task from a TaskSpec file")
    p.add_argument("--task", required=True, help="TaskSpec JSON file ('-' for stdin)")
    p.add_argument("--idempotency-key", required=True)

    p = sub.add_parser("run", parents=[common], help="run one executor attempt (foreground)")
    p.add_argument("task_id")
    p.add_argument("--mode", choices=["mock", "live"], default="mock")
    p.add_argument(
        "--allow-model-usage",
        action="store_true",
        help="required (with local config opt-in) for live mode",
    )
    p.add_argument(
        "--stub-binary",
        default=None,
        help="mock mode only: absolute path of a non-model stand-in executable for "
        "the claude-code adapter (contract testing)",
    )

    p = sub.add_parser("status", parents=[common], help="show task state")
    p.add_argument("task_id")

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

    p = sub.add_parser("demo", parents=[common], help="offline demo with the fake executor")
    p.add_argument("--scenario", choices=["success", "bug-then-repair"], required=True)
    p.add_argument("--workdir", default=None, help="directory for the demo (default: temp dir)")
    p.add_argument("--cleanup", action="store_true", help="delete the demo directory afterwards")
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
    from harness_bridge.service import Bridge, StopFlag

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
    bridge = Bridge(state_dir, stop_flag=flag)
    try:
        if cmd == "create":
            return bridge.create(_read_json_file(args.task), args.idempotency_key)
        if cmd == "run":
            _install_signal_handlers(flag)
            return bridge.run(
                args.task_id,
                mode=args.mode,
                allow_model_usage=args.allow_model_usage,
                executor_binary=args.stub_binary,
            )
        if cmd == "status":
            return bridge.status(args.task_id)
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
        raise BridgeError("USAGE_ERROR", f"unknown command {cmd!r}")
    finally:
        bridge.close()


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
