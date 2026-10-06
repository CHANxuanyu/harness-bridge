"""Task state machine.

    CREATED -> READY -> STARTING -> RUNNING -> VERIFYING -> AWAITING_REVIEW -> SUCCEEDED
                 ^                                              |
                 +------------- changes_requested --------------+
    any non-terminal -> CANCELLED (only once no owned process can still be running)
    uncertain launch/execution -> INTERRUPTED; external condition -> BLOCKED; budget -> FAILED

Distinctions that must stay visible: executing (STARTING/RUNNING/VERIFYING), waiting for review
(AWAITING_REVIEW, which may show failing verification), blocked by permission/quota/supervisor
(BLOCKED), outcome uncertain (INTERRUPTED), and real success (SUCCEEDED).
"""

from __future__ import annotations

from enum import StrEnum

from harness_bridge.errors import BridgeError


class TaskState(StrEnum):
    CREATED = "CREATED"
    READY = "READY"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"


S = TaskState

TERMINAL: frozenset[TaskState] = frozenset({S.SUCCEEDED, S.FAILED, S.CANCELLED})
EXECUTING: frozenset[TaskState] = frozenset({S.STARTING, S.RUNNING, S.VERIFYING})

TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    S.CREATED: frozenset({S.READY, S.BLOCKED, S.CANCELLED}),
    S.READY: frozenset({S.STARTING, S.FAILED, S.CANCELLED}),
    S.STARTING: frozenset({S.RUNNING, S.BLOCKED, S.INTERRUPTED, S.CANCELLED}),
    S.RUNNING: frozenset({S.VERIFYING, S.BLOCKED, S.INTERRUPTED, S.CANCELLED}),
    S.VERIFYING: frozenset({S.AWAITING_REVIEW, S.INTERRUPTED, S.CANCELLED}),
    S.AWAITING_REVIEW: frozenset(
        {S.SUCCEEDED, S.READY, S.FAILED, S.BLOCKED, S.VERIFYING, S.CANCELLED}
    ),
    S.BLOCKED: frozenset({S.READY, S.FAILED, S.CANCELLED}),
    S.INTERRUPTED: frozenset({S.READY, S.VERIFYING, S.FAILED, S.CANCELLED}),
    S.SUCCEEDED: frozenset(),
    S.FAILED: frozenset(),
    S.CANCELLED: frozenset(),
}


def check_transition(src: TaskState, dst: TaskState, *, task_id: str | None = None) -> None:
    if dst not in TRANSITIONS[src]:
        raise BridgeError(
            "STATE_CONFLICT",
            f"illegal state transition {src} -> {dst}",
            retryable=False,
            task_id=task_id,
        )


class AttemptOutcome(StrEnum):
    """How one executor attempt ended, as classified by the bridge (not the executor)."""

    SUCCEEDED = "succeeded"  # exited cleanly with a complete, successful final result
    FAILED = "failed"  # complete protocol, executor reported failure (implementation failure)
    PROTOCOL_ERROR = "protocol_error"  # exited but output protocol incomplete/malformed
    CRASHED = "crashed"  # non-zero exit / signal without a final result
    TIMED_OUT = "timed_out"  # wall timeout; owned process group terminated and confirmed
    BLOCKED = "blocked"  # trusted permission/quota/auth classification
    CANCELLED = "cancelled"  # cancelled via bridge; exit confirmed
    INTERRUPTED = "interrupted"  # runner interrupted (signal); exit confirmed
    OUTCOME_UNKNOWN = "outcome_unknown"  # exit of owned processes could not be confirmed
    SPAWN_FAILED = "spawn_failed"  # executable could not be started (known not running)


SETTLED_FOR_REVIEW: frozenset[AttemptOutcome] = frozenset(
    {
        AttemptOutcome.SUCCEEDED,
        AttemptOutcome.FAILED,
        AttemptOutcome.PROTOCOL_ERROR,
        AttemptOutcome.CRASHED,
        AttemptOutcome.TIMED_OUT,
    }
)
