"""Codex exec JSONL adapter with explicit per-harness budget semantics.

The documented exec stream does not establish an enforceable model-step ceiling or observed
model/auth provenance. A turn.completed event is NOT a count of internal model calls. Never
silently replace an existing task's native turn ceiling with wall-clock limits. New tasks may
explicitly select null turns after accepting the unsupported capability.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
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
from harness_bridge.models import mock_usage
from harness_bridge.policy import redact_text
from harness_bridge.runner import ProcessOutcome
from harness_bridge.state import AttemptOutcome

DOCS = "https://learn.chatgpt.com/docs/non-interactive-mode"
LIVE_GAPS = (
    "enforceable_model_turn_ceiling",
    "subscription_auth_and_provider_provenance",
    "effective_config_permissions_hooks_and_mcp",
    "live_resume_workspace_binding",
)
ITEM_TYPES = frozenset(
    {
        "agent_message",
        "reasoning",
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "web_search",
        "todo_list",
        "error",
    }
)


@dataclass(frozen=True)
class CodexSettings:
    requested_model: str | None = None
    sandbox: str = "workspace-write"


class CodexAdapter:
    kind = "codex"

    def __init__(self, settings: CodexSettings) -> None:
        self.settings = settings
        self._resume_requested: str | None = None

    @staticmethod
    def refuse_live() -> NoReturn:
        raise BridgeError(
            "PREFLIGHT_FAILED",
            "Codex live dispatch is unavailable: required capabilities lack verified enforcement; "
            "a stub or help-text check cannot authorize model usage",
            details={"executor": "codex", "live_dispatch": "unavailable", "gaps": list(LIVE_GAPS)},
        )

    def describe_capabilities(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "modes": ["mock with explicit --stub-binary", "live with null native turn ceiling"],
            "evidence": "docs-derived/synthetic events and offline stub integration only",
            "docs": DOCS,
            "live_dispatch": "gated_wall_time_only",
            "unverified_capabilities": ["native_model_turn_ceiling", "observed_model_identity"],
            "model_observation": "not established by the documented exec JSONL schema",
            "resume": "explicit bound UUID only; never --last, --all, name or fork",
            "turn_ceiling": "unsupported; legacy numeric-turn tasks remain live-refused",
        }

    def build_invocation(self, packet: TaskPacket, ctx: InvocationContext) -> InvocationSpec:
        if ctx.mode != "mock" and packet.max_turns is not None:
            self.refuse_live()
        if not ctx.executor_binary or not os.path.isabs(ctx.executor_binary):
            raise BridgeError("PREFLIGHT_FAILED", "Codex executable must be absolute")
        s = self.settings
        if s.sandbox not in ("read-only", "workspace-write"):
            raise BridgeError("PREFLIGHT_FAILED", "unsupported Codex sandbox policy")
        if s.requested_model is not None and (
            not s.requested_model
            or s.requested_model.startswith("-")
            or any(c.isspace() or c == "\x00" for c in s.requested_model)
        ):
            raise BridgeError("PREFLIGHT_FAILED", "invalid Codex model pin")
        self._resume_requested = ctx.resume_session_id
        if ctx.resume_session_id is not None and _session(ctx.resume_session_id) is None:
            raise BridgeError("PREFLIGHT_FAILED", "Codex resume requires a canonical observed UUID")
        # Parent exec options precede the resume subcommand; prompt is always stdin.
        # Do not discard user config/rules, add writable roots, or bypass sandbox/approvals.
        argv = [
            ctx.executor_binary,
            "exec",
            "--json",
            "--sandbox",
            s.sandbox,
            "--cd",
            ctx.worktree,
            "--config",
            'approval_policy="never"',
        ]
        if s.requested_model:
            argv += ["--model", s.requested_model]
        if ctx.resume_session_id:
            argv += ["resume", ctx.resume_session_id]
        argv.append("-")
        notes = [
            "offline Codex stub" if ctx.mode == "mock" else "Codex native gated execution",
            f"native turn cap not enforced (unsupported); declared max_turns={packet.max_turns}; "
            "null explicitly selects attempts, wall deadline and cancellation only",
            "approval_policy=never denies requests requiring escalation; sandbox remains enabled",
        ]
        if packet.attempt_kind == "repair" and not ctx.resume_session_id:
            notes.append("no verified session to resume; this repair starts a new session")
        return InvocationSpec(
            argv,
            ctx.worktree,
            packet.render_prompt().encode(),
            dict(ctx.base_env),
            s.requested_model,
            ctx.resume_session_id,
            notes,
        )

    def parse_event(self, raw_line: bytes) -> ParsedEvent:
        if not raw_line.strip():
            return ParsedEvent("progress", raw_type="blank")
        try:
            obj = json.loads(raw_line)
        except (UnicodeDecodeError, ValueError, RecursionError):
            return ParsedEvent("malformed", data={"bytes": len(raw_line)})
        if not isinstance(obj, dict) or not isinstance(obj.get("type"), str):
            return ParsedEvent("malformed")
        kind = obj["type"]
        if kind == "thread.started":
            sid = _session(obj.get("thread_id"))
            return ParsedEvent("session" if sid else "malformed", kind, session_id=sid)
        if kind == "turn.started":
            return ParsedEvent("progress", kind)
        if kind == "turn.completed":
            usage = obj.get("usage")
            keys = ("input_tokens", "cached_input_tokens", "output_tokens")
            if not isinstance(usage, dict) or any(not _count(usage.get(k)) for k in keys):
                return ParsedEvent("malformed", kind)
            return ParsedEvent("result", kind, data={"usage": {k: usage[k] for k in keys}})
        if kind in ("turn.failed", "error"):
            error = obj.get("error") if kind == "turn.failed" else obj
            if not isinstance(error, dict) or not isinstance(error.get("message"), str):
                return ParsedEvent("malformed", kind)
            return ParsedEvent("result", kind, data={"error": _text(error["message"])})
        if kind in ("item.started", "item.updated", "item.completed"):
            item = obj.get("item")
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                return ParsedEvent("malformed", kind)
            subtype = item.get("type")
            if not isinstance(subtype, str) or subtype not in ITEM_TYPES:
                return ParsedEvent("unknown", "item:unknown")
            data: dict[str, Any] = {"item_type": subtype}
            if subtype == "agent_message" and kind == "item.completed":
                if not isinstance(item.get("text"), str):
                    return ParsedEvent("malformed", kind)
                data["summary"] = _text(item["text"])
            if subtype == "error":
                if not isinstance(item.get("message"), str):
                    return ParsedEvent("malformed", kind)
                data["error"] = _text(item["message"])
            # Never retain reasoning, shell command/output, MCP arguments/results or file bodies.
            return ParsedEvent(
                "message" if subtype == "agent_message" else "progress", kind, data=data
            )
        return ParsedEvent("unknown", _text(kind, 100))

    def classify_completion(
        self, process: ProcessOutcome, events: Sequence[ParsedEvent]
    ) -> ExecutorResult:
        sessions = [e for e in events if e.kind == "session"]
        sid = sessions[0].session_id if len(sessions) == 1 else None
        completed = [e for e in events if e.raw_type == "turn.completed" and e.kind == "result"]
        reported_usage = completed[0].data["usage"] if len(completed) == 1 else {}
        usage = mock_usage()
        usage.update(
            {
                "mode": "executor_reported",
                "model_calls_made_by_test": None,
                "input_tokens_reported": reported_usage.get("input_tokens"),
                "output_tokens_reported": reported_usage.get("output_tokens"),
                "cache_read_tokens_reported": reported_usage.get("cached_input_tokens"),
                "source": "executor turn.completed event" if completed else "not_observed",
                "aggregation": "one invocation as reported; resumed-history accounting unverified",
            }
        )
        summaries = [e.data["summary"] for e in events if "summary" in e.data]
        common: dict[str, Any] = {
            "session_id": sid,
            "observed_model": None,
            "usage": usage,
            "protocol": protocol_summary(events, process),
            "executor_reported": {
                "status": "turn.completed" if completed else None,
                "summary": summaries[-1] if summaries else None,
                "tests_reported": None,
                "num_turns": None,
                "api_key_source": None,
                "model_pin": "unknown" if self.settings.requested_model else "not_requested",
                "turn_ceiling": "unsupported; no internal model-call count is inferred",
            },
        }
        base = classify_process_level(process)
        if base:
            # Process evidence wins the outcome, but cannot make a wrong resume ID trusted.
            base.session_id = (
                sid if not self._resume_requested or sid == self._resume_requested else None
            )
            base.usage = usage
            base.protocol, base.executor_reported = common["protocol"], common["executor_reported"]
            return base
        if self._resume_requested and sid != self._resume_requested:
            common["session_id"] = None  # Never rebind a refused/mismatched resume.
            return ExecutorResult(
                AttemptOutcome.BLOCKED,
                "requested Codex resume was not confirmed",
                blocked={
                    "category": "resume_failed",
                    "classification": "observed_thread_id",
                    "requested_session_id": self._resume_requested,
                    "observed_session_id": sid,
                    "reset_at": None,
                },
                **common,
            )
        if any(e.kind in ("malformed", "oversized", "unknown") for e in events):
            return ExecutorResult(
                AttemptOutcome.PROTOCOL_ERROR,
                "malformed, truncated or unknown Codex event",
                **common,
            )
        failures = [e.data["error"] for e in events if "error" in e.data]
        if failures:
            hint = _failure_hint(" ".join(failures))
            if hint:
                return ExecutorResult(
                    AttemptOutcome.BLOCKED,
                    "Codex error suggests " + hint,
                    blocked={
                        "category": hint,
                        "classification": "heuristic_error_text",
                        "reset_at": None,
                    },
                    **common,
                )
            return ExecutorResult(AttemptOutcome.FAILED, "Codex reported an error", **common)
        if process.returncode != 0:
            hint = _failure_hint(process.stderr.render().decode("utf-8", "replace")[-4000:])
            if hint:
                return ExecutorResult(
                    AttemptOutcome.BLOCKED,
                    "Codex stderr suggests " + hint,
                    blocked={
                        "category": hint,
                        "classification": "heuristic_stderr",
                        "reset_at": None,
                    },
                    **common,
                )
            return ExecutorResult(
                AttemptOutcome.PROTOCOL_ERROR if completed else AttemptOutcome.CRASHED,
                "Codex exited unsuccessfully",
                **common,
            )
        # Exactly one thread -> one turn -> one completion; exit 0 alone is insufficient.
        phase = "new"
        for event in events:
            if event.raw_type == "blank":
                continue
            if phase == "new" and event.kind == "session":
                phase = "thread"
            elif phase == "thread" and event.raw_type == "turn.started":
                phase = "running"
            elif phase == "running" and event.raw_type in (
                "item.started",
                "item.updated",
                "item.completed",
            ):
                continue
            elif phase == "running" and event.raw_type == "turn.completed":
                phase = "ended"
            else:
                return ExecutorResult(
                    AttemptOutcome.PROTOCOL_ERROR,
                    "unexpected Codex lifecycle event ordering",
                    **common,
                )
        if phase != "ended" or sid is None or len(completed) != 1:
            return ExecutorResult(
                AttemptOutcome.PROTOCOL_ERROR,
                "Codex stream ended without a complete bound turn",
                **common,
            )
        return ExecutorResult(
            AttemptOutcome.SUCCEEDED, "Codex turn completed; checks remain external", **common
        )


def _session(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return value if str(uuid.UUID(value)) == value else None
    except ValueError:
        return None


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _text(value: str, limit: int = 4000) -> str:
    return redact_text(value)[0][:limit]


def _failure_hint(text: str) -> str | None:
    # Only error events / failing stderr, never agent prose. No inferred reset times or retries.
    patterns = (
        (
            "cli_rejected_argument",
            r"unknown (?:option|argument)|unexpected argument|unrecognized (?:option|argument)",
        ),
        ("usage_limit", r"usage limit|quota|rate.?limit|too many requests|\b429\b"),
        ("auth", r"unauthori[sz]ed|not logged in|authentication|\b401\b"),
        ("permission_denied", r"permission denied|approval required|sandbox denied"),
        ("resume_failed", r"session.*not found|thread.*not found|no.*session.*found"),
    )
    return next((name for name, pattern in patterns if re.search(pattern, text, re.I)), None)
