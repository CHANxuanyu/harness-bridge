"""Minimal executor adapter contract.

The core depends only on :class:`ExecutorAdapter`. Process lifecycle, timeouts, output limits and
signals belong to :mod:`harness_bridge.runner`; adapters only describe how to launch (pure,
side-effect free so it can be dry-run and contract-tested), how to parse one output line, and how
to classify a finished process from the bridge's observations.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from harness_bridge.models import sha256_digest
from harness_bridge.policy import redact_text
from harness_bridge.runner import ProcessOutcome
from harness_bridge.state import AttemptOutcome


@dataclass(frozen=True)
class TaskPacket:
    """Everything an executor is told about one attempt. Serialized to stdin, never to argv."""

    task_id: str
    attempt_id: str
    attempt_seq: int
    attempt_kind: str  # initial | repair | retry
    goal: str
    requirements: list[str]
    allowed_paths: list[str]
    forbidden_paths: list[str]
    verification: list[dict[str, Any]]
    max_turns: int | None
    feedback: list[dict[str, Any]] | None = None
    context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"protocol": "hbridge-task-packet/1", **asdict(self)}

    def to_json_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")

    def render_prompt(self) -> str:
        lines = [
            "You are the executor for a Harness Bridge task. Work only inside the current",
            "working directory (a git worktree created for this task).",
            "",
            "## Goal",
            self.goal,
        ]
        if self.requirements:
            lines += ["", "## Requirements", *[f"- {r}" for r in self.requirements]]
        if self.context:
            lines += [
                "",
                "## Parent goal and fixed execution context",
                json.dumps(self.context, ensure_ascii=False, sort_keys=True),
            ]
        lines += [
            "",
            "## Path policy",
            "Only change files matching: " + ", ".join(self.allowed_paths),
            "Never create or change files matching: " + ", ".join(self.forbidden_paths),
            "",
            "## Acceptance",
            "The bridge will independently run these checks after you finish; your own claims",
            "about test results are recorded but do not count as verification:",
        ]
        for check in self.verification:
            req = "required" if check.get("required") else "optional"
            lines.append(f"- {check['id']} ({req}, {check['trust']}): {' '.join(check['argv'])}")
        if self.feedback:
            lines += ["", "## Review feedback to address (from the supervisor)"]
            for f in self.feedback:
                loc = f" [{f['location']}]" if f.get("location") else ""
                lines.append(f"- ({f['severity']}){loc} {f['explanation']}")
                if f.get("requested_change"):
                    lines.append(f"  Requested change: {f['requested_change']}")
        lines += [
            "",
            "When done, reply with a short summary of what you changed and what you ran.",
            f"(task {self.task_id}, attempt {self.attempt_seq}: {self.attempt_kind})",
        ]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class InvocationContext:
    worktree: str
    mode: str  # mock | live
    python_executable: str
    base_env: dict[str, str]
    executor_binary: str | None = None
    resume_session_id: str | None = None


@dataclass
class InvocationSpec:
    argv: list[str]
    cwd: str
    stdin: bytes
    env: dict[str, str]
    requested_model: str | None
    resume_session_id: str | None = None
    notes: list[str] = field(default_factory=list)

    def describe(self) -> dict[str, Any]:
        """Loggable description: argv (redacted), cwd, stdin digest, env *names* only."""
        return {
            "argv": [redact_text(a)[0] for a in self.argv],
            "cwd": self.cwd,
            "stdin_sha256": sha256_digest(self.stdin),
            "stdin_bytes": len(self.stdin),
            "env_names": sorted(self.env),
            "requested_model": self.requested_model,
            "resume_session_id": self.resume_session_id,
            "notes": list(self.notes),
        }

    def digest(self) -> str:
        return sha256_digest(self.describe())


@dataclass
class ParsedEvent:
    kind: str  # session | message | progress | child | result | unknown | malformed | oversized
    raw_type: str | None = None
    session_id: str | None = None
    model: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutorResult:
    outcome: AttemptOutcome
    reason: str
    session_id: str | None = None
    observed_model: str | None = None
    executor_reported: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    blocked: dict[str, Any] | None = None
    protocol: dict[str, Any] = field(default_factory=dict)


class ExecutorAdapter(Protocol):
    kind: str

    def describe_capabilities(self) -> dict[str, Any]: ...

    def build_invocation(self, packet: TaskPacket, ctx: InvocationContext) -> InvocationSpec: ...

    def parse_event(self, raw_line: bytes) -> ParsedEvent: ...

    def classify_completion(
        self, process: ProcessOutcome, events: Sequence[ParsedEvent]
    ) -> ExecutorResult: ...


def classify_process_level(process: ProcessOutcome) -> ExecutorResult | None:
    """Outcomes decided by the runner's observations alone, before any protocol parsing.

    Order matters: an unconfirmed exit dominates everything, because nothing else can be
    trusted while an owned process might still be running.
    """
    if process.spawn_error:
        return ExecutorResult(AttemptOutcome.SPAWN_FAILED, process.spawn_error)
    if not process.group_exit_confirmed:
        why = (
            "pipes held open by an unobservable process"
            if process.pipes_held_open
            else ("owned process group did not exit after TERM/KILL")
        )
        return ExecutorResult(AttemptOutcome.OUTCOME_UNKNOWN, why)
    if process.stop_reason == "cancelled":
        return ExecutorResult(AttemptOutcome.CANCELLED, "cancelled via hbridge cancel")
    if process.stop_reason == "interrupted":
        return ExecutorResult(AttemptOutcome.INTERRUPTED, "runner received a stop signal")
    if process.timed_out:
        return ExecutorResult(AttemptOutcome.TIMED_OUT, "wall timeout; process group terminated")
    return None


def protocol_summary(events: Sequence[ParsedEvent], process: ProcessOutcome) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    unknown_types: set[str] = set()
    for e in events:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
        if e.kind == "unknown" and e.raw_type:
            unknown_types.add(e.raw_type[:64])
    return {
        "lines": process.lines,
        "events_by_kind": dict(sorted(kinds.items())),
        "unknown_types": sorted(unknown_types)[:20],
        "result_seen": kinds.get("result", 0) > 0,
        "malformed_lines": kinds.get("malformed", 0),
        "oversized_lines": process.oversized_lines,
    }
