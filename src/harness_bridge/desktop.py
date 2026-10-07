"""Open an existing, finished native session without a prompt or an Executor attempt.

Native acknowledgement is distinct from observed desktop-list visibility. This module
never edits vendor history, creates a replacement conversation, or starts/resumes a turn.
"""

from __future__ import annotations

import json
import subprocess
import sys
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
            capability = "native_history_only"
            blockers.append("codex_desktop_list_sync_unverified")
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
            "model_call_requested": False,
        }

    def open(self, task_id: str, key: str) -> dict[str, Any]:
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
            # At most one handoff per task. An interrupted/unknown request is not retried
            # with another key: it may already have opened the original session.
            if prior:
                return {**json.loads(prior[0]["payload"]), "replayed": True}
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
        if version.stdout.decode(errors="replace").strip() != CLAUDE_VERSION:
            raise BridgeError("PREFLIGHT_FAILED", "native desktop version has not been validated")
        receipt = {
            "task_id": task_id,
            "session_id": plan["session_id"],
            "worktree": plan["worktree"],
            "idempotency_key": key,
            "status": "request_outcome_unknown",
            "desktop_visibility": "unverified",
            "model_call_requested": False,
        }
        with b.store.transaction() as cur:
            if goal_id:
                b.coordination.guard_goal(cur, goal_id, b.advisor_claim, allow_delivery=True)
            inserted = b.store.add_event(
                cur,
                task_id,
                "desktop_open_requested",
                receipt,
                attempt_id=attempt.attempt_id,
                dedupe_key="desktop-open:" + task_id,
            )
        if not inserted:
            return self.open(task_id, key)
        # --desktop --resume performs the official CLI-to-desktop handoff and exits.
        # No positional prompt, stdin, --print, model flags, or permission overrides.
        try:
            result = subprocess.run(
                [binary, "--desktop", "--resume", plan["session_id"]],
                cwd=plan["worktree"],
                env=b.env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=20,
                check=False,
            )
            ack = f"Opening session {plan['session_id']} in Claude Desktop"
            text = (result.stdout + result.stderr).decode(errors="replace")
            if result.returncode == 0 and ack in text:
                receipt["status"] = "native_open_requested"
            receipt["native_exit_code"] = result.returncode
        except OSError:
            receipt["status"] = "native_launch_failed"
        except subprocess.TimeoutExpired:
            pass
        # Never persist raw native output (it can contain private paths/auth diagnostics).
        with b.store.transaction() as cur:
            b.store.add_event(
                cur,
                task_id,
                "desktop_open_result",
                receipt,
                attempt_id=attempt.attempt_id,
                dedupe_key="desktop-open-result:" + task_id,
            )
        return {**receipt, "replayed": False}
