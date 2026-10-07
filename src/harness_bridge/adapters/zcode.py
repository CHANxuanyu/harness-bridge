"""Offline ZCode protocol adapter. Native dispatch stays unavailable pending qualification."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Sequence
from typing import Any, NoReturn

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
from harness_bridge.models import ZCodeExecutorSpec, mock_usage
from harness_bridge.runner import ProcessOutcome
from harness_bridge.state import AttemptOutcome

LIVE_GAPS = (
    "account_subscription_provenance",
    "effective_permissions_hooks_mcp",
    "native_model_and_resume_binding",
    "native_stop_and_desktop_history",
)


def session_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("sess_"):
        return None
    try:
        return value if str(uuid.UUID(value[5:])) == value[5:] else None
    except ValueError:
        return None


class ZCodeAdapter:
    kind = "zcode"

    def __init__(self, settings: ZCodeExecutorSpec) -> None:
        self.settings = settings
        self.resume: str | None = None
        self.worktree: str | None = None

    @staticmethod
    def refuse_live() -> NoReturn:
        raise BridgeError(
            "PREFLIGHT_FAILED",
            "ZCode live execution is not qualified; protocol discovery is not model authorization",
            details={"executor": "zcode", "live_dispatch": "unavailable", "gaps": list(LIVE_GAPS)},
        )

    def describe_capabilities(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "modes": ["mock with explicit protocol stand-in"],
            "live_dispatch": "unavailable",
            "evidence": "installed protocol symbols and offline simulated execution",
            "transport": "bounded bidirectional stdio through a managed child process",
            "resume": "exact sess_UUID and workspace/model/permission checks",
            "turn_ceiling": "unsupported; requires explicit null",
            "gaps": list(LIVE_GAPS),
        }

    def build_invocation(self, packet: TaskPacket, ctx: InvocationContext) -> InvocationSpec:
        if ctx.mode != "mock":
            self.refuse_live()
        if packet.max_turns is not None:
            raise BridgeError("PREFLIGHT_FAILED", "ZCode has no verified internal turn ceiling")
        if not ctx.executor_binary or not os.path.isabs(ctx.executor_binary):
            raise BridgeError(
                "PREFLIGHT_FAILED", "ZCode mock requires an absolute protocol stand-in"
            )
        if ctx.resume_session_id is not None and session_id(ctx.resume_session_id) is None:
            raise BridgeError("PREFLIGHT_FAILED", "ZCode resume requires an exact sess_UUID")
        self.resume, self.worktree = ctx.resume_session_id, ctx.worktree
        payload = {
            "version": 1,
            "mode": "mock",
            "stub": ctx.executor_binary,
            "workspace": ctx.worktree,
            "settings": self.settings.model_dump(),
            "resume": self.resume,
            "input_id": packet.attempt_id,
            "prompt": packet.render_prompt(),
        }
        return InvocationSpec(
            argv=[ctx.python_executable, "-m", "harness_bridge.zcode_transport"],
            cwd=ctx.worktree,
            stdin=json.dumps(payload, sort_keys=True).encode(),
            env=dict(ctx.base_env),
            requested_model=self.settings.requested_model,
            resume_session_id=self.resume,
            notes=["offline protocol stand-in only", "no native model-turn ceiling"],
        )

    def parse_event(self, raw_line: bytes) -> ParsedEvent:
        try:
            obj = json.loads(raw_line)
        except (ValueError, UnicodeError):
            return ParsedEvent("malformed")
        if not isinstance(obj, dict):
            return ParsedEvent("malformed")
        kind = obj.get("type")
        if kind == "zcode.error":
            category = obj.get("category")
            allowed = {
                "protocol_error",
                "native_error",
                "model_mismatch",
                "workspace_mismatch",
                "permission_denied",
                "resume_failed",
                "session_busy",
            }
            if (
                set(obj) != {"type", "category"}
                or not isinstance(category, str)
                or category not in allowed
            ):
                return ParsedEvent("malformed")
            return ParsedEvent("result", kind, data={"error": category})
        if kind in ("zcode.session", "zcode.started", "zcode.completed"):
            sid = session_id(obj.get("session_id"))
            expected = {"type", "session_id"}
            if kind == "zcode.session":
                expected |= {"model", "provider", "workspace", "permission_mode"}
            if sid is None or set(obj) != expected:
                return ParsedEvent("malformed")
            if kind == "zcode.session":
                if not all(isinstance(obj[k], str) for k in expected):
                    return ParsedEvent("malformed")
                return ParsedEvent("session", kind, sid, obj["model"], obj)
            return ParsedEvent("progress" if kind == "zcode.started" else "result", kind, sid)
        return ParsedEvent("unknown", "unrecognized_zcode_envelope")

    def classify_completion(
        self, process: ProcessOutcome, events: Sequence[ParsedEvent]
    ) -> ExecutorResult:
        sessions = [e for e in events if e.kind == "session"]
        session = sessions[0] if len(sessions) == 1 else None
        sid = session.session_id if session else None
        bound = bool(
            session
            and sid
            and (not self.resume or sid == self.resume)
            and session.model == self.settings.requested_model
            and session.data.get("provider") == self.settings.provider_id
            and session.data.get("workspace") == self.worktree
            and session.data.get("permission_mode") == self.settings.permission_mode
        )
        protocol = protocol_summary(events, process)
        common: dict[str, Any] = {
            "session_id": sid if bound else None,
            "observed_model": session.model if bound and session else None,
            "usage": mock_usage(),
            "protocol": protocol,
            "executor_reported": {
                "model_pin": "satisfied" if bound else "unknown",
                "source": "offline simulated ZCode protocol; not account or model inference proof",
                "num_turns": None,
                "tests_reported": None,
            },
        }
        base = classify_process_level(process)
        if base:
            base.session_id = common["session_id"]
            base.protocol = protocol
            base.usage = common["usage"]
            return base
        if any(e.kind in ("unknown", "malformed", "oversized") for e in events):
            return ExecutorResult(AttemptOutcome.PROTOCOL_ERROR, "invalid ZCode envelope", **common)
        errors = [e.data["error"] for e in events if "error" in e.data]
        if errors:
            category = errors[0]
            if category == "protocol_error":
                return ExecutorResult(AttemptOutcome.PROTOCOL_ERROR, category, **common)
            # Do not make a previous binding reusable after reported identity uncertainty.
            if category in ("model_mismatch", "workspace_mismatch", "resume_failed"):
                common["session_id"] = None
                common["observed_model"] = None
            return ExecutorResult(
                AttemptOutcome.BLOCKED,
                "ZCode protocol refused execution",
                blocked={
                    "category": category,
                    "classification": "protocol_guard",
                    "reset_at": None,
                },
                **common,
            )
        order = [e.raw_type for e in events]
        if (
            process.returncode != 0
            or not bound
            or order != ["zcode.session", "zcode.started", "zcode.completed"]
            or any(e.session_id != sid for e in events)
        ):
            return ExecutorResult(
                AttemptOutcome.PROTOCOL_ERROR, "incomplete bound ZCode turn", **common
            )
        return ExecutorResult(
            AttemptOutcome.SUCCEEDED, "ZCode completed; checks remain external", **common
        )
