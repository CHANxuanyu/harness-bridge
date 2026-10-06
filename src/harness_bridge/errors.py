"""Uniform error structure shared by the core and the CLI.

Every error the bridge reports carries a stable ``code``, a human ``message``, whether a retry
could help (``retryable``) and, when applicable, the task/attempt it concerns. The CLI maps the
code to a process exit status so callers can branch without parsing prose.
"""

from __future__ import annotations

from typing import Any

# code -> (exit status, retryable default)
_CODES: dict[str, tuple[int, bool]] = {
    "USAGE_ERROR": (2, False),
    "INVALID_INPUT": (2, False),
    "NOT_FOUND": (5, False),
    "STATE_CONFLICT": (3, True),
    "DELIVERY_CONFLICT": (3, False),
    "IDEMPOTENCY_CONFLICT": (3, False),
    "ADVISOR_REQUIRED": (3, False),
    "STALE_ADVISOR": (3, False),
    "STALE_REVIEW": (3, False),
    "APPROVAL_GATE_FAILED": (3, False),
    "BUDGET_EXHAUSTED": (3, False),
    "LIVE_GATE_CLOSED": (4, False),
    "PREFLIGHT_FAILED": (4, False),
    "SOURCE_REPO_DIRTY": (6, False),
    "REPO_ERROR": (6, False),
    "WORKSPACE_ERROR": (6, False),
    "PATH_POLICY_VIOLATION": (6, False),
    "INTEGRITY_ERROR": (7, False),
    "EXECUTOR_ERROR": (8, True),
    "VERIFICATION_ERROR": (8, True),
    "CANNOT_CONFIRM_EXIT": (9, False),
    "INTERNAL_ERROR": (1, False),
}


class BridgeError(Exception):
    """An expected, reportable failure. Never carries secret values."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool | None = None,
        task_id: str | None = None,
        attempt_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in _CODES:
            raise ValueError(f"unknown error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = _CODES[code][1] if retryable is None else retryable
        self.task_id = task_id
        self.attempt_id = attempt_id
        self.details = details or {}

    @property
    def exit_status(self) -> int:
        return _CODES[self.code][0]

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.task_id is not None:
            out["task_id"] = self.task_id
        if self.attempt_id is not None:
            out["attempt_id"] = self.attempt_id
        if self.details:
            out["details"] = self.details
        return out


def known_codes() -> list[str]:
    return sorted(_CODES)
