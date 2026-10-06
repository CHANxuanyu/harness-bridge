"""Adapter for the deterministic fake executor (offline / mock mode only)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from harness_bridge.adapters.base import (
    ExecutorResult,
    InvocationContext,
    InvocationSpec,
    ParsedEvent,
    TaskPacket,
    classify_process_level,
    protocol_summary,
)
from harness_bridge.errors import BridgeError
from harness_bridge.models import mock_usage
from harness_bridge.runner import ProcessOutcome
from harness_bridge.state import AttemptOutcome

FAKE_EXECUTOR_SCRIPT = Path(__file__).with_name("fake_executor.py").resolve()
_BLOCKING_CATEGORIES = {"permission_denied", "usage_limit", "rate_limit", "auth_required"}


class FakeExecutorAdapter:
    kind = "fake"

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario

    def describe_capabilities(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "modes": ["mock"],
            "evidence": "offline integration (simulated executor); not a model",
            "makes_model_calls": False,
        }

    def build_invocation(self, packet: TaskPacket, ctx: InvocationContext) -> InvocationSpec:
        if ctx.mode != "mock":
            raise BridgeError("LIVE_GATE_CLOSED", "the fake executor only runs in mock mode")
        keep = ("PATH", "LANG", "LC_ALL", "TMPDIR")
        env: dict[str, str] = {k: ctx.base_env[k] for k in keep if k in ctx.base_env}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return InvocationSpec(
            argv=[
                ctx.python_executable,
                "-I",
                "-B",
                str(FAKE_EXECUTOR_SCRIPT),
                "--scenario",
                self.scenario,
            ],
            cwd=ctx.worktree,
            stdin=packet.to_json_bytes(),
            env=env,
            requested_model=None,
            notes=["simulated executor: no model is invoked"],
        )

    def parse_event(self, raw_line: bytes) -> ParsedEvent:
        try:
            obj = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ParsedEvent("malformed", data={"bytes": len(raw_line)})
        if not isinstance(obj, dict):
            return ParsedEvent("malformed", data={"json_type": type(obj).__name__})
        t = obj.get("type")
        if t == "start":
            return ParsedEvent(
                "session",
                raw_type=t,
                session_id=_str(obj.get("session_id")),
                model=_str(obj.get("model")),
            )
        if t == "progress":
            return ParsedEvent("progress", raw_type=t)
        if t == "child":
            return ParsedEvent("child", raw_type=t, data={"pid": obj.get("pid")})
        if t == "result":
            err = obj.get("error") if isinstance(obj.get("error"), dict) else None
            return ParsedEvent(
                "result",
                raw_type=t,
                data={
                    "status": _str(obj.get("status")),
                    "summary": _str(obj.get("summary"), 4000),
                    "tests_reported": _str(obj.get("tests_reported")),
                    "error": None
                    if err is None
                    else {
                        "category": _str(err.get("category")),
                        "message": _str(err.get("message"), 1000),
                        "reset_at": _str(err.get("reset_at")),
                    },
                },
            )
        return ParsedEvent("unknown", raw_type=_str(t) or "<missing>")

    def classify_completion(
        self, process: ProcessOutcome, events: Sequence[ParsedEvent]
    ) -> ExecutorResult:
        session = next((e for e in events if e.kind == "session"), None)
        results = [e for e in events if e.kind == "result"]
        proto = protocol_summary(events, process)
        base = classify_process_level(process)
        common: dict[str, Any] = {
            "session_id": session.session_id if session else None,
            "observed_model": session.model if session else None,
            "usage": mock_usage(),
            "protocol": proto,
        }
        final = results[-1].data if results else None
        reported = {
            "summary": final.get("summary") if final else None,
            "tests_reported": final.get("tests_reported") if final else None,
            "status": final.get("status") if final else None,
        }
        common["executor_reported"] = reported
        if base is not None:
            base.session_id = common["session_id"]
            base.observed_model = common["observed_model"]
            base.usage = common["usage"]
            base.protocol = proto
            base.executor_reported = reported
            return base
        rc = process.returncode
        if final is None:
            if rc == 0:
                why = (
                    "malformed output and no final result"
                    if proto["malformed_lines"]
                    else ("exited 0 without a final result event")
                )
                return ExecutorResult(AttemptOutcome.PROTOCOL_ERROR, why, **common)
            return ExecutorResult(
                AttemptOutcome.CRASHED,
                f"exited with {_exit_text(process)} and no final result",
                **common,
            )
        if len(results) > 1:
            return ExecutorResult(
                AttemptOutcome.PROTOCOL_ERROR, "more than one final result event", **common
            )
        error = final.get("error")
        if (
            final.get("status") == "error"
            and error
            and error.get("category") in _BLOCKING_CATEGORIES
        ):
            blocked = {
                "category": error["category"],
                "message": error.get("message"),
                "reset_at": error.get("reset_at"),
                "classification": "structured",
            }
            return ExecutorResult(
                AttemptOutcome.BLOCKED,
                f"executor reported {error['category']}",
                blocked=blocked,
                **common,
            )
        if final.get("status") == "success":
            if rc != 0:
                return ExecutorResult(
                    AttemptOutcome.PROTOCOL_ERROR,
                    f"success result but process exited with {_exit_text(process)}",
                    **common,
                )
            return ExecutorResult(AttemptOutcome.SUCCEEDED, "final result: success", **common)
        if final.get("status") == "error":
            return ExecutorResult(AttemptOutcome.FAILED, "executor reported an error", **common)
        return ExecutorResult(
            AttemptOutcome.PROTOCOL_ERROR, "final result has an unknown status", **common
        )


def _str(value: Any, limit: int = 256) -> str | None:
    return value[:limit] if isinstance(value, str) else None


def _exit_text(process: ProcessOutcome) -> str:
    if process.exit_signal:
        return f"signal {process.exit_signal}"
    return f"exit code {process.returncode}"
