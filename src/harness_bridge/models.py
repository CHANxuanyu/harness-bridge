"""Versioned external data contracts: TaskSpec and ReviewDecision.

All external input passes through these models. Unknown fields are rejected (``extra="forbid"``),
limits are bounded, and an unsupported ``schema_version`` is reported explicitly instead of being
interpreted silently.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from harness_bridge import SCHEMA_VERSION
from harness_bridge.errors import BridgeError
from harness_bridge.policy import compile_glob

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_FORBIDDEN_PATHS = (".github/**", ".env", ".env.*", "**/.env", "**/.env.*")

FAKE_SCENARIOS = (
    "success",
    "bug-then-repair",
    "hang",
    "crash",
    "malformed-output",
    "permission-denied",
    "budget-exhausted",
    "scope-violation",
    "false-success-report",
    "noisy",
    "tamper-tests",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_UNRESTRICTED_BASH = re.compile(r"^Bash(\(\s*(\*|:\*|\*:\*)?\s*\))?$")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_digest(obj: Any) -> str:
    data = obj if isinstance(obj, bytes) else canonical_json(obj).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


def _no_nul(value: str, what: str) -> str:
    if "\x00" in value:
        raise ValueError(f"{what} must not contain NUL bytes")
    return value


class RepoSpec(_Strict):
    path: str = Field(min_length=1, max_length=4096)
    base_ref: str = Field(default="HEAD", min_length=1, max_length=256)

    @field_validator("path")
    @classmethod
    def _abs_path(cls, v: str) -> str:
        _no_nul(v, "repo.path")
        if not os.path.isabs(v):
            raise ValueError("repo.path must be an absolute path")
        return v

    @field_validator("base_ref")
    @classmethod
    def _ref(cls, v: str) -> str:
        _no_nul(v, "repo.base_ref")
        if v.startswith("-") or any(c.isspace() for c in v):
            raise ValueError("repo.base_ref must not start with '-' or contain whitespace")
        return v


class VerificationCommand(_Strict):
    id: str
    argv: list[str] = Field(min_length=1, max_length=256)
    cwd: str = "."
    timeout_seconds: float = Field(gt=0, le=3600)
    required: bool = True
    trust: Literal["external-acceptance", "repository-tests"]

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError("verification id must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
        return v

    @field_validator("argv")
    @classmethod
    def _argv(cls, v: list[str]) -> list[str]:
        for item in v:
            _no_nul(item, "verification argv")
        if not v[0]:
            raise ValueError("verification argv[0] must be non-empty")
        return v

    @field_validator("cwd")
    @classmethod
    def _cwd(cls, v: str) -> str:
        _no_nul(v, "verification cwd")
        if os.path.isabs(v) or "\\" in v:
            raise ValueError("verification cwd must be relative to the task worktree (POSIX '/')")
        parts = [p for p in v.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise ValueError("verification cwd must not contain '..'")
        return v


class Limits(_Strict):
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_repair_cycles: int = Field(default=2, ge=0, le=9)
    wall_timeout_seconds: float = Field(default=900, gt=0, le=86400)
    max_turns_per_attempt: int = Field(default=20, ge=1, le=500)
    max_artifact_bytes: int = Field(default=10 * 1024 * 1024, ge=64 * 1024, le=1024**3)
    kill_grace_seconds: float = Field(default=5.0, ge=0, le=120)

    @model_validator(mode="after")
    def _consistent(self) -> Limits:
        if self.max_repair_cycles > self.max_attempts - 1:
            raise ValueError("max_repair_cycles must be <= max_attempts - 1")
        return self


class ExecutorSpec(_Strict):
    kind: Literal["fake", "claude-code"]
    requested_model: str | None = Field(default=DEFAULT_MODEL, max_length=128)
    scenario: str | None = None
    permission_mode: Literal["acceptEdits", "manual", "dontAsk", "plan"] = "acceptEdits"
    allowed_tools: list[str] = Field(default_factory=list, max_length=64)
    resume_on_repair: bool = True
    strict_mcp_config: bool = True

    @model_validator(mode="after")
    def _kind_rules(self) -> ExecutorSpec:
        if self.kind == "fake":
            if self.scenario not in FAKE_SCENARIOS:
                raise ValueError(
                    f"executor.scenario for kind 'fake' must be one of {FAKE_SCENARIOS}"
                )
        elif self.scenario is not None:
            raise ValueError("executor.scenario is only valid for kind 'fake'")
        for tool in self.allowed_tools:
            _no_nul(tool, "allowed_tools entry")
            if _UNRESTRICTED_BASH.match(tool.strip()):
                raise ValueError(
                    "unrestricted Bash auto-approval is not allowed; use a scoped pattern "
                    "such as 'Bash(python -m pytest:*)'"
                )
        return self


class TaskDefinition(_Strict):
    """Task requirements without a repository/base; shared by plans and execution specs."""

    goal: str = Field(min_length=1, max_length=20000)
    requirements: list[str] = Field(default_factory=list, max_length=200)
    allowed_paths: list[str] = Field(min_length=1, max_length=200)
    forbidden_paths: list[str] = Field(default_factory=lambda: list(DEFAULT_FORBIDDEN_PATHS))
    verification: list[VerificationCommand] = Field(min_length=1, max_length=50)
    limits: Limits = Field(default_factory=Limits)
    executor: ExecutorSpec

    @field_validator("allowed_paths", "forbidden_paths")
    @classmethod
    def _globs(cls, v: list[str]) -> list[str]:
        for pattern in v:
            compile_glob(pattern)  # raises ValueError with a precise message
        return v

    @model_validator(mode="after")
    def _verification_rules(self) -> TaskDefinition:
        ids = [c.id for c in self.verification]
        if len(ids) != len(set(ids)):
            raise ValueError("verification ids must be unique")
        if not any(c.required for c in self.verification):
            raise ValueError("at least one verification command must be required")
        return self


class TaskSpec(TaskDefinition):
    schema_version: Literal["1.0"]
    repo: RepoSpec


class Finding(_Strict):
    severity: Literal["blocking", "major", "minor", "info"]
    location: str | None = Field(default=None, max_length=1024)
    requirement: str | None = Field(default=None, max_length=4000)
    explanation: str = Field(min_length=1, max_length=8000)
    requested_change: str | None = Field(default=None, max_length=8000)


class ReviewDecision(_Strict):
    schema_version: Literal["1.0"]
    task_id: str = Field(min_length=1, max_length=128)
    attempt_id: str = Field(min_length=1, max_length=128)
    task_version: int = Field(ge=1)
    snapshot_digest: str = Field(min_length=1, max_length=256)
    verdict: Literal["approve", "changes_requested", "blocked"]
    findings: list[Finding] = Field(default_factory=list, max_length=100)
    reviewer_label: str = Field(default="external-supervisor", max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _findings_required(self) -> ReviewDecision:
        if self.verdict in ("changes_requested", "blocked") and not self.findings:
            raise ValueError(f"verdict '{self.verdict}' requires at least one finding")
        return self


def _check_schema_version(data: Any, what: str) -> None:
    if not isinstance(data, dict):
        raise BridgeError("INVALID_INPUT", f"{what} must be a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise BridgeError(
            "INVALID_INPUT",
            f"unsupported {what} schema_version {version!r}; this bridge understands "
            f"{SCHEMA_VERSION!r} only",
        )


def _validation_error(what: str, exc: ValidationError) -> BridgeError:
    problems = []
    for err in exc.errors()[:20]:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        problems.append(f"{loc or '<root>'}: {err.get('msg')}")
    return BridgeError(
        "INVALID_INPUT", f"invalid {what}: " + "; ".join(problems), details={"errors": problems}
    )


def parse_task_spec(data: Any) -> TaskSpec:
    _check_schema_version(data, "TaskSpec")
    try:
        return TaskSpec.model_validate(data)
    except ValidationError as exc:
        raise _validation_error("TaskSpec", exc) from None


def parse_review(data: Any) -> ReviewDecision:
    _check_schema_version(data, "ReviewDecision")
    try:
        return ReviewDecision.model_validate(data)
    except ValidationError as exc:
        raise _validation_error("ReviewDecision", exc) from None


def mock_usage() -> dict[str, Any]:
    """Usage record for a simulated attempt: no model call was made by the bridge or the test."""
    return {
        "mode": "mock",
        "model_calls_made_by_test": 0,
        "input_tokens_reported": None,
        "output_tokens_reported": None,
        "cache_read_tokens_reported": None,
        "cost_estimate_usd_reported": None,
        "subscription_remaining": None,
        "source": "not_observed",
    }
