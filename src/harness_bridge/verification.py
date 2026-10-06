"""Independent verifier: runs the acceptance commands frozen in the TaskSpec at creation time.

Commands come only from the trusted TaskSpec, never from executor output. They run through the
same runner (argv, no shell, own process group, timeout, bounded redacted logs). Running a
command is not sandboxing: only commands the user authorized in the TaskSpec are executed.

Evidence kinds are kept apart: ``external-acceptance`` (a check the executor does not own, e.g.
a script outside the worktree), ``repository-tests`` (tests inside the worktree, which the
executor could have edited) and ``executor-reported`` (claims in executor output, never a pass).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness_bridge.artifacts import store_capture, tail_text
from harness_bridge.models import VerificationCommand
from harness_bridge.runner import ProcessSpec, RunLimits, run_process

# Credentials a verifier never needs. Removed from the inherited environment.
_STRIP_FOR_VERIFIERS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
)


def verifier_env(base_env: dict[str, str]) -> dict[str, str]:
    env = {k: v for k, v in base_env.items() if k not in _STRIP_FOR_VERIFIERS}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


@dataclass
class CheckResult:
    id: str
    trust: str
    required: bool
    argv: list[str]
    cwd: str
    status: str  # passed | failed | timed_out | error | not_run | unconfirmed
    exit_code: int | None = None
    exit_signal: int | None = None
    duration_seconds: float | None = None
    detail: str | None = None
    stdout: dict[str, Any] | None = None
    stderr: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trust": self.trust,
            "required": self.required,
            "argv": self.argv,
            "cwd": self.cwd,
            "status": self.status,
            "exit_code": self.exit_code,
            "exit_signal": self.exit_signal,
            "duration_seconds": self.duration_seconds,
            "detail": self.detail,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def run_checks(
    commands: list[VerificationCommand],
    *,
    worktree: Path,
    log_dir: Path,
    base_env: dict[str, str],
    bytes_per_stream: int,
    kill_grace: float,
    should_stop: Callable[[], str | None] | None = None,
) -> tuple[list[CheckResult], str | None]:
    results: list[CheckResult] = []
    stop_reason: str | None = None
    env = verifier_env(base_env)
    head = max(4096, bytes_per_stream // 4)
    tail = max(4096, bytes_per_stream - head)
    for cmd in commands:
        res = CheckResult(cmd.id, cmd.trust, cmd.required, list(cmd.argv), cmd.cwd, "not_run")
        results.append(res)
        if stop_reason:
            res.detail = f"not run: verification stopped ({stop_reason})"
            continue
        cwd = (worktree / cmd.cwd).resolve()
        root = worktree.resolve()
        if cwd != root and root not in cwd.parents:
            res.status, res.detail = "error", "cwd escapes the worktree"
            continue
        if not cwd.is_dir():
            res.status, res.detail = "error", f"cwd {cmd.cwd!r} does not exist in the worktree"
            continue
        limits = RunLimits(
            wall_timeout=cmd.timeout_seconds,
            kill_grace=kill_grace,
            stdout_head=head,
            stdout_tail=tail,
            stderr_head=head,
            stderr_tail=tail,
        )
        outcome = run_process(
            ProcessSpec(argv=list(cmd.argv), cwd=str(cwd), env=env),
            limits,
            should_stop=should_stop,
        )
        res.duration_seconds = round(outcome.duration, 3)
        res.exit_code = outcome.returncode
        res.exit_signal = outcome.exit_signal
        if outcome.spawn_error:
            res.status, res.detail = "error", f"could not start: {outcome.spawn_error}"
            continue
        res.stdout = store_capture(log_dir / f"{cmd.id}.stdout.log", outcome.stdout)
        res.stderr = store_capture(log_dir / f"{cmd.id}.stderr.log", outcome.stderr)
        if outcome.stop_reason:
            stop_reason = outcome.stop_reason
            res.status, res.detail = "not_run", f"stopped: {outcome.stop_reason}"
        elif not outcome.group_exit_confirmed:
            res.status, res.detail = "unconfirmed", "verifier process exit could not be confirmed"
        elif outcome.timed_out:
            res.status, res.detail = "timed_out", f"exceeded {cmd.timeout_seconds}s"
        elif outcome.returncode == 0:
            res.status = "passed"
        else:
            res.status = "failed"
    return results, stop_reason


def aggregate_status(results: list[CheckResult], fp_before: str, fp_after: str | None) -> str:
    if fp_after is not None and fp_before != fp_after:
        return "invalidated"
    if any(r.required and r.status == "not_run" for r in results):
        return "incomplete"
    if all(r.status == "passed" for r in results if r.required):
        return "passed"
    return "failed"


def failing_tails(
    checks: Sequence[Mapping[str, Any]], log_dir: Path, max_bytes: int = 2000
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in checks:
        if c["status"] in ("passed", "not_run"):
            continue
        out[c["id"]] = {
            "stdout_tail": tail_text(log_dir / f"{c['id']}.stdout.log", max_bytes),
            "stderr_tail": tail_text(log_dir / f"{c['id']}.stderr.log", max_bytes),
        }
    return out


def warnings_for(results: list[CheckResult]) -> list[str]:
    return [
        f"optional check {r.id!r} did not pass ({r.status})"
        for r in results
        if not r.required and r.status != "passed"
    ]


__all__ = [
    "CheckResult",
    "aggregate_status",
    "failing_tails",
    "run_checks",
    "verifier_env",
    "warnings_for",
]
