"""Open an existing, finished native session without a prompt or an Executor attempt.

Native acknowledgement is distinct from observed desktop-list visibility. This module
never edits vendor history, creates a replacement conversation, or starts/resumes a turn.
"""

from __future__ import annotations

import errno
import json
import os
import plistlib
import select
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from harness_bridge.config import API_PROVIDER_ENV, CLOUD_ENV_MARKERS, NESTED_ENV_MARKERS
from harness_bridge.coordination import check_key
from harness_bridge.errors import BridgeError
from harness_bridge.models import sha256_digest
from harness_bridge.state import TERMINAL

if TYPE_CHECKING:
    from harness_bridge.service import Bridge

CLAUDE_VERSION = "2.1.291 (Claude Code)"
CODEX_VERSION = "codex-cli 0.160.0"
CODEX_APP = Path("/Applications/ChatGPT.app")
CODEX_APP_VERSION = "26.930.31730"


def codex_app() -> Path:
    try:
        info = plistlib.loads((CODEX_APP / "Contents/Info.plist").read_bytes())
        schemes = [
            s for row in info.get("CFBundleURLTypes", []) for s in row.get("CFBundleURLSchemes", [])
        ]
        valid = (
            not CODEX_APP.is_symlink()
            and info.get("CFBundleIdentifier") == "com.openai.codex"
            and info.get("CFBundleShortVersionString") == CODEX_APP_VERSION
            and "codex" in schemes
        )
    except (OSError, ValueError, TypeError, AttributeError, plistlib.InvalidFileException):
        valid = False
    if not valid:
        raise BridgeError("PREFLIGHT_FAILED", "Codex desktop app has not been validated")
    return CODEX_APP


def run_handoff(
    argv: list[str], *, cwd: str, env: dict[str, str], timeout: float = 20
) -> subprocess.CompletedProcess[bytes]:
    """Give the desktop-only native launcher a terminal, never write input to it.

    Claude 2.1.291 refuses redirected stdin/stdout before session lookup. A PTY is
    required even though this command opens the desktop and exits without a turn.
    """
    import pty  # POSIX only; status/version guards reject other platforms before this call.

    master, slave = pty.openpty()
    proc: subprocess.Popen[bytes] | None = None
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
        )
        os.close(slave)
        slave = -1
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            ready, _, _ = select.select([master], [], [], min(remaining, 0.1))
            if ready:
                try:
                    data = os.read(master, 8192)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    data = b""
                if not data:
                    break
                output.extend(data)
                if len(output) > 65536:
                    raise OSError("desktop launcher output limit exceeded")
            elif proc.poll() is not None:
                break
        return subprocess.CompletedProcess(
            argv, proc.wait(timeout=max(0.001, deadline - time.monotonic())), bytes(output), b""
        )
    except OSError:
        if proc is not None:
            raise subprocess.SubprocessError("desktop launcher observation failed") from None
        raise
    finally:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)
        os.close(master)
        if slave >= 0:
            os.close(slave)


def legacy_pipe_refusal(receipt: dict[str, Any]) -> bool:
    # Legacy requests only used DEVNULL + captured output and pinned 2.1.291,
    # whose desktop launcher unconditionally rejects this transport before opening.
    # Exit/ack-unknown, interrupted, successful and all newer PTY requests are excluded.
    return (
        "transport" not in receipt
        and receipt.get("status") == "request_outcome_unknown"
        and receipt.get("native_exit_code") == 1
    )


class DesktopSessions:
    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge

    def status(self, task_id: str) -> dict[str, Any]:
        b = self.bridge
        task = b.store.get_task(task_id)
        spec = b._spec(task)
        attempts = b.store.list_attempts(task_id)
        attempt = next(
            (
                a
                for a in reversed(attempts)
                if not (a.outcome == "spawn_failed" and a.exit_confirmed)
            ),
            None,
        )
        blockers: list[str] = []
        if task.state not in TERMINAL:
            blockers.append("task_not_terminal")
        if not attempts or any(a.exit_confirmed is not True for a in attempts):
            blockers.append("executor_exit_not_confirmed")
        goal_id = b._goal_id(task_id)
        if goal_id and b.coordination.status(goal_id)["state"] != "DELIVERED":
            blockers.append("goal_not_delivered")
        binding = (attempt.session_binding or {}) if attempt else {}
        expected = {
            "task_id": task_id,
            "attempt_id": attempt.attempt_id if attempt else None,
            "executor_kind": spec.executor.kind,
            "repo_identity": task.repo_identity,
            "worktree": task.worktree_path,
            "requested_model": spec.executor.requested_model,
        }
        session_id = attempt.session_id if attempt else None
        try:
            valid_id = isinstance(session_id, str) and str(uuid.UUID(session_id)) == session_id
        except ValueError:
            valid_id = False
        if (
            not attempt
            or attempt.mode != "live"
            or attempt.executor_kind != spec.executor.kind
            or not valid_id
            or any(binding.get(k) != v for k, v in expected.items())
            or attempt.invocation_digest != sha256_digest(attempt.invocation)
            or attempt.invocation.get("cwd") != task.worktree_path
        ):
            blockers.append("native_session_binding_unverified")
        if (
            not task.worktree_path
            or not Path(task.worktree_path).is_dir()
            or str(Path(task.worktree_path).resolve()) != task.worktree_path
        ):
            blockers.append("original_worktree_unavailable")
        if spec.executor.kind == "codex":
            capability = "existing_thread_deep_link"
            if sys.platform != "darwin":
                blockers.append("desktop_platform_unverified")
            else:
                try:
                    codex_app()
                except BridgeError:
                    blockers.append("codex_desktop_app_unverified")
        elif spec.executor.kind == "claude-code":
            capability = "existing_session_handoff"
            if sys.platform != "darwin":
                blockers.append("desktop_platform_unverified")
        else:
            capability = "unsupported"
            blockers.append("unsupported_executor")
        with b.store.transaction() as cur:
            rows = cur.execute(
                "SELECT type,payload FROM events WHERE task_id=? "
                "AND type IN ('desktop_open_requested','desktop_open_result') ORDER BY seq DESC",
                (task_id,),
            ).fetchall()
        receipt = json.loads(rows[0]["payload"]) if rows else None
        return {
            "task_id": task_id,
            "goal_id": goal_id,
            "executor": spec.executor.kind,
            "session_id": session_id,
            "attempt_id": attempt.attempt_id if attempt else None,
            "worktree": task.worktree_path,
            "capability": capability,
            "can_request_open": not blockers and receipt is None,
            "request_replay_only": receipt is not None,
            "blockers": blockers,
            "desktop_visibility": "unverified",
            "last_request": receipt,
            "legacy_pipe_retry_available": not blockers
            and bool(receipt and legacy_pipe_refusal(receipt)),
            "model_call_requested": False,
            "deep_link": f"codex://threads/{session_id}"
            if spec.executor.kind == "codex" and valid_id
            else None,
        }

    def open(self, task_id: str, key: str, *, retry_legacy_pipe: bool = False) -> dict[str, Any]:
        check_key(key)
        b = self.bridge
        # The transaction serializes callers through the durable request, not the external
        # handoff. Terminal tasks / delivered goals cannot admit a competing repair.
        with b.store.transaction() as cur:
            goal_id = b.coordination.task_goal(cur, task_id)
            if goal_id:
                b.coordination.guard_goal(
                    cur, goal_id, b.advisor_claim, allow_delivery=True, allow_stopping=True
                )
            prior = cur.execute(
                "SELECT payload FROM events WHERE task_id=? "
                "AND type IN ('desktop_open_requested','desktop_open_result') ORDER BY seq DESC",
                (task_id,),
            ).fetchall()
            # Normally one handoff per task; only the proven pre-open legacy pipe refusal
            # permits explicit recovery. Other unknown outcomes may already have opened.
            previous = json.loads(prior[0]["payload"]) if prior else None
            if previous:
                if not retry_legacy_pipe or previous["idempotency_key"] == key:
                    return {**previous, "replayed": True}
                if not legacy_pipe_refusal(previous):
                    return {**previous, "replayed": True}
            elif retry_legacy_pipe:
                raise BridgeError("STATE_CONFLICT", "no legacy pipe refusal to retry")
        plan = self.status(task_id)
        if plan["blockers"]:
            raise BridgeError(
                "STATE_CONFLICT", "desktop handoff is unavailable", details=plan, task_id=task_id
            )
        names = [
            n for n in (*API_PROVIDER_ENV, *CLOUD_ENV_MARKERS, *NESTED_ENV_MARKERS) if n in b.env
        ]
        if names:
            raise BridgeError(
                "PREFLIGHT_FAILED",
                "desktop handoff requires a local native context",
                details={"environment_names": names},
            )
        attempt = b.store.get_attempt(plan["attempt_id"])
        argv = attempt.invocation.get("argv", [])
        if not argv or not isinstance(argv[0], str) or not Path(argv[0]).is_absolute():
            raise BridgeError("INTEGRITY_ERROR", "original native executable is unavailable")
        binary = argv[0]
        try:
            version = subprocess.run(
                [binary, "--version"],
                cwd=plan["worktree"],
                env=b.env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            raise BridgeError("PREFLIGHT_FAILED", "native desktop version probe failed") from None
        is_codex = plan["executor"] == "codex"
        if previous and is_codex:
            raise BridgeError("STATE_CONFLICT", "legacy pipe recovery applies only to Claude")
        expected_version = CODEX_VERSION if is_codex else CLAUDE_VERSION
        if version.stdout.decode(errors="replace").strip() != expected_version:
            raise BridgeError("PREFLIGHT_FAILED", "native desktop version has not been validated")
        app = codex_app() if is_codex else None
        if app and not Path(binary).resolve().is_relative_to(app.resolve()):
            raise BridgeError("PREFLIGHT_FAILED", "Codex executable is not from the validated app")
        receipt = {
            "task_id": task_id,
            "session_id": plan["session_id"],
            "worktree": plan["worktree"],
            "idempotency_key": key,
            "status": "request_outcome_unknown",
            "desktop_visibility": "unverified",
            "model_call_requested": False,
            "transport": "native_url" if is_codex else "pty",
        }
        if previous:
            receipt["supersedes_key"] = previous["idempotency_key"]
            receipt["retry_reason"] = "validated_2_1_291_legacy_pipe_refusal"
        with b.store.transaction() as cur:
            if goal_id:
                b.coordination.guard_goal(cur, goal_id, b.advisor_claim, allow_delivery=True)
            inserted = b.store.add_event(
                cur,
                task_id,
                "desktop_open_requested",
                receipt,
                attempt_id=attempt.attempt_id,
                dedupe_key=("desktop-open-pty-retry:" if previous else "desktop-open:") + task_id,
            )
        if not inserted:
            return self.open(task_id, key)
        # --desktop --resume performs the official CLI-to-desktop handoff and exits.
        # No positional prompt, stdin, --print, model flags, or permission overrides.
        try:
            if app:
                # The documented existing-thread URL contains no prompt/new-thread route.
                result = subprocess.run(
                    ["/usr/bin/open", "-a", str(app), plan["deep_link"]],
                    cwd=plan["worktree"],
                    env=b.env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=20,
                    check=False,
                )
                acknowledged = result.returncode == 0
            else:
                result = run_handoff(
                    [binary, "--desktop", "--resume", plan["session_id"]],
                    cwd=plan["worktree"],
                    env=b.env,
                    timeout=20,
                )
                ack = f"Opening session {plan['session_id']} in Claude Desktop"
                acknowledged = result.returncode == 0 and ack in (
                    result.stdout + result.stderr
                ).decode(errors="replace")
            if acknowledged:
                receipt["status"] = "native_open_requested"
            receipt["native_exit_code"] = result.returncode
        except OSError:
            receipt["status"] = "native_launch_failed"
        except subprocess.SubprocessError:
            pass
        # Never persist raw native output (it can contain private paths/auth diagnostics).
        with b.store.transaction() as cur:
            b.store.add_event(
                cur,
                task_id,
                "desktop_open_result",
                receipt,
                attempt_id=attempt.attempt_id,
                dedupe_key=(
                    "desktop-open-pty-retry-result:" if previous else "desktop-open-result:"
                )
                + task_id,
            )
        return {**receipt, "replayed": False}
