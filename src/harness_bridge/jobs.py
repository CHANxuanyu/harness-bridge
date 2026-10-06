"""Durable, single-claim background attempts. No queues, automatic retries or model calls.

A reservation and its attempt are committed together before launching a detached local worker.
Only a transaction changing reserved -> claimed authorizes execution. Abandoning an unclaimed
reservation fences even a delayed worker, so recovery can prove non-execution in that window.
After claim, ordinary runner recovery rules apply; a lost worker never means confirmed exit.
"""

from __future__ import annotations

import json
import math
import sqlite3
import subprocess
import time
from threading import Thread
from typing import TYPE_CHECKING, Any, cast

from harness_bridge.adapters.base import InvocationContext, InvocationSpec, TaskPacket
from harness_bridge.config import evaluate_live_gate
from harness_bridge.coordination import check_key
from harness_bridge.errors import BridgeError
from harness_bridge.models import canonical_json, sha256_digest
from harness_bridge.runner import runner_alive, runner_identity
from harness_bridge.state import EXECUTING
from harness_bridge.state import TaskState as S
from harness_bridge.store import new_id

if TYPE_CHECKING:
    from harness_bridge.service import Bridge


class WorkerJobs:
    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge
        self.store = bridge.store

    @staticmethod
    def request(mode: str, allow: bool, binary: str | None) -> dict[str, Any]:
        return {"mode": mode, "allow_model_usage": allow, "executor_binary": binary}

    @staticmethod
    def validate_key(key: str | None) -> None:
        if key is None:
            raise BridgeError("USAGE_ERROR", "--background requires --idempotency-key")
        check_key(key)

    def replay(
        self, cur: sqlite3.Cursor, task_id: str, key: str | None, request: dict[str, Any]
    ) -> str | None:
        row = cur.execute(
            "SELECT job_id,request_digest FROM worker_jobs WHERE task_id=? AND idempotency_key=?",
            (task_id, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_digest"] != sha256_digest(request):
            raise BridgeError("IDEMPOTENCY_CONFLICT", "key already used for another dispatch")
        return str(row["job_id"])

    def reserve(
        self,
        cur: sqlite3.Cursor,
        task_id: str,
        attempt_id: str,
        key: str | None,
        request: dict[str, Any],
        packet: TaskPacket,
        invocation: InvocationSpec,
    ) -> str:
        job_id = new_id("job")
        execution = {"request": request, "packet": packet.to_dict(), "notes": invocation.notes}
        cur.execute(
            "INSERT INTO worker_jobs VALUES (?,?,?,?,?,?,?,'reserved',NULL,?,NULL)",
            (
                job_id,
                task_id,
                attempt_id,
                key,
                sha256_digest(request),
                canonical_json(execution),
                sha256_digest(execution),
                self.store.clock(),
            ),
        )
        self.store.add_event(
            cur, task_id, "worker_reserved", {"job_id": job_id}, attempt_id=attempt_id
        )
        return job_id

    def _row(self, cur: sqlite3.Cursor, job_id: str) -> sqlite3.Row:
        row = cur.execute("SELECT * FROM worker_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise BridgeError("NOT_FOUND", "worker job not found")
        return cast(sqlite3.Row, row)

    def status(
        self, job_id: str, *, replayed: bool | None = None, cur: sqlite3.Cursor | None = None
    ) -> dict[str, Any]:
        if cur is None:
            with self.store.transaction() as reader:
                return self.status(job_id, replayed=replayed, cur=reader)
        row = self._row(cur, job_id)
        task = self.store.get_task(row["task_id"], cur=cur)
        attempt = self.store.get_attempt(row["attempt_id"], cur=cur)
        cursor = cur.execute(
            "SELECT COALESCE(MAX(seq),0) FROM events WHERE task_id=?", (task.task_id,)
        ).fetchone()[0]
        result = {
            "job_id": job_id,
            "task_id": task.task_id,
            "attempt_id": attempt.attempt_id,
            "goal_id": self.bridge.coordination.task_goal(cur, task.task_id),
            "phase": row["phase"],
            "state": task.state.value,
            "runner": attempt.runner,
            "runner_alive": runner_alive(attempt.runner),
            "executor_exit_confirmed": attempt.exit_confirmed,
            "executor_outcome": attempt.outcome,
            "error_code": row["error_code"],
            "event_cursor": cursor,
            "created_at": row["created_at"],
            "ended_at": row["ended_at"],
        }
        if replayed is not None:
            result["replayed"] = replayed
        return result

    def launch(self, job_id: str) -> None:
        # No terminal, pipes or inherited file descriptors tie the worker to the caller.
        # The worker claims in SQLite; a successful Popen is not evidence of that claim.
        try:
            proc = subprocess.Popen(
                [
                    self.bridge.python,
                    "-m",
                    "harness_bridge.worker",
                    "--state-dir",
                    str(self.bridge.state_dir),
                    "--job-id",
                    job_id,
                ],
                cwd=self.bridge.state_dir,
                env=self.bridge.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError:
            with self.store.transaction() as cur:
                row = self._row(cur, job_id)
                if row["phase"] == "reserved":
                    self._abandon(cur, row, "WORKER_SPAWN_FAILED")
            return
        Thread(target=proc.wait, daemon=True).start()

    def _abandon(
        self, cur: sqlite3.Cursor, row: sqlite3.Row, reason: str, *, cancelled: bool = False
    ) -> None:
        """Caller has fenced the unclaimed worker or owns a claim that has not executed."""
        task = self.store.get_task(row["task_id"], cur=cur)
        attempt = self.store.get_attempt(row["attempt_id"], cur=cur)
        assert task.state == S.STARTING and task.current_attempt_id == row["attempt_id"]
        cancelled = cancelled or task.cancel_requested
        cur.execute(
            "UPDATE worker_jobs SET phase='abandoned',error_code=?,ended_at=? WHERE job_id=?",
            (reason, self.store.clock(), row["job_id"]),
        )
        self.store.update_attempt(
            cur,
            row["attempt_id"],
            status="ended",
            outcome="spawn_failed",
            outcome_reason=reason,
            exit_confirmed=1,
            ended_at=self.store.clock(),
        )
        self.store.transition(
            cur,
            task.task_id,
            S.STARTING,
            S.CANCELLED if cancelled else S.BLOCKED,
            reason="worker_cancelled_before_execution" if cancelled else "worker_not_executed",
            details={"job_id": row["job_id"], "error_code": reason, "outcome_known": True},
            event_type="worker_abandoned",
            attempt_id=row["attempt_id"],
            pending_feedback=attempt.feedback,
        )

    def cancel_unclaimed(self, task_id: str) -> bool:
        with self.store.transaction() as cur:
            row = cur.execute(
                "SELECT * FROM worker_jobs WHERE task_id=? AND phase='reserved'", (task_id,)
            ).fetchone()
            if row is None:
                return False
            self._abandon(cur, row, "CANCELLED_BEFORE_CLAIM", cancelled=True)
            return True

    def recover_unclaimed(self, task_id: str) -> dict[str, Any] | None:
        with self.store.transaction() as cur:
            self.bridge.coordination.guard_task(
                cur, task_id, self.bridge.advisor_claim, allow_stopping=True
            )
            row = cur.execute(
                "SELECT * FROM worker_jobs WHERE task_id=? AND phase='reserved'", (task_id,)
            ).fetchone()
            if row is None:
                return None
            attempt = self.store.get_attempt(row["attempt_id"], cur=cur)
            alive = runner_alive(attempt.runner)
            task = self.store.get_task(task_id, cur=cur)
            if alive is False or task.cancel_requested:
                self._abandon(cur, row, "UNCLAIMED_WORKER_RECOVERED")
                action = "unclaimed worker fenced; executor never started; no automatic redispatch"
            else:
                action = "launcher active or liveness unknown; reservation retained"
            return {
                "task_id": task_id,
                "state_before": task.state.value,
                "state_after": self.store.get_task(task_id, cur=cur).state.value,
                "runner_alive": alive,
                "actions": [action],
            }

    def execute(self, job_id: str) -> bool:
        """Internal worker entry. A duplicate/delayed invocation can never claim twice."""
        from harness_bridge.service import _fault_point

        with self.store.transaction() as cur:
            row = self._row(cur, job_id)
            if row["phase"] != "reserved":
                return False
            task = self.store.get_task(row["task_id"], cur=cur)
            attempt = self.store.get_attempt(row["attempt_id"], cur=cur)
            if task.state != S.STARTING or task.current_attempt_id != attempt.attempt_id:
                raise BridgeError("INTEGRITY_ERROR", "worker reservation no longer owns task")
            execution = json.loads(row["execution_json"])
            if sha256_digest(execution) != row["execution_digest"]:
                self._abandon(cur, row, "INTEGRITY_ERROR")
                return False
            if task.cancel_requested:
                self._abandon(cur, row, "CANCELLED_BEFORE_CLAIM", cancelled=True)
                return False
            cur.execute("UPDATE worker_jobs SET phase='claimed' WHERE job_id=?", (job_id,))
            self.store.update_attempt(cur, attempt.attempt_id, runner=runner_identity())
            self.store.add_event(
                cur,
                task.task_id,
                "worker_claimed",
                {"job_id": job_id},
                attempt_id=attempt.attempt_id,
            )
        _fault_point("after_worker_claim")
        b = self.bridge
        try:
            request = execution["request"]
            spec = b._spec(task)
            if attempt.mode == "live":
                gate = evaluate_live_gate(
                    mode=attempt.mode,
                    allow_model_usage=request["allow_model_usage"],
                    config=b.config,
                    env=b.env,
                )
                if not gate.open:
                    raise BridgeError("LIVE_GATE_CLOSED", "worker live gate is closed")
            adapter, binary = b._adapter(spec, attempt.mode, request["executor_binary"])
            packet_data = dict(execution["packet"])
            packet_data.pop("protocol")
            packet = TaskPacket(**packet_data)
            assert task.worktree_path is not None
            invocation = adapter.build_invocation(
                packet,
                InvocationContext(
                    worktree=task.worktree_path,
                    mode=attempt.mode,
                    python_executable=b.python,
                    base_env=b.env,
                    executor_binary=binary,
                    resume_session_id=attempt.invocation.get("resume_session_id"),
                ),
            )
            invocation.notes = execution["notes"]
            if invocation.digest() != attempt.invocation_digest:
                raise BridgeError("INTEGRITY_ERROR", "worker invocation differs from reservation")
            with self.store.transaction() as cur:
                b._child_context(cur, task.task_id)
                if (
                    self.store.get_task(task.task_id, cur=cur).cancel_requested
                    or b.stop_flag.reason
                ):
                    self._abandon(cur, row, "STOPPED_BEFORE_EXECUTION")
                    return False
        except Exception as exc:
            with self.store.transaction() as cur:
                self._abandon(
                    cur,
                    row,
                    exc.code if isinstance(exc, BridgeError) else "WORKER_PREFLIGHT_FAILED",
                )
            return False
        try:
            b._execute_attempt(task, spec, attempt.attempt_id, adapter, invocation)
        except Exception as exc:
            # Execution may already have begun. Keep its reservation and unknown exit intact.
            with self.store.transaction() as cur:
                code = exc.code if isinstance(exc, BridgeError) else "WORKER_ERROR"
                cur.execute("UPDATE worker_jobs SET error_code=? WHERE job_id=?", (code, job_id))
                self.store.add_event(
                    cur, task.task_id, "worker_error", {"job_id": job_id, "code": code}
                )
            return False
        with self.store.transaction() as cur:
            cur.execute(
                "UPDATE worker_jobs SET phase='finished',ended_at=? WHERE job_id=?",
                (self.store.clock(), job_id),
            )
            self.store.add_event(cur, task.task_id, "worker_finished", {"job_id": job_id})
        return True

    def reconcile_recovery(self, task_id: str) -> None:
        """Annotate a dead worker after explicit task recovery; never clear exit uncertainty."""
        with self.store.transaction() as cur:
            task = self.store.get_task(task_id, cur=cur)
            if task.state in EXECUTING:
                return
            rows = cur.execute(
                "SELECT * FROM worker_jobs WHERE task_id=? AND phase='claimed'", (task_id,)
            ).fetchall()
            for row in rows:
                attempt = self.store.get_attempt(row["attempt_id"], cur=cur)
                if runner_alive(attempt.runner) is not False:
                    continue
                cur.execute(
                    "UPDATE worker_jobs SET phase='recovered',ended_at=? WHERE job_id=?",
                    (self.store.clock(), row["job_id"]),
                )
                self.store.add_event(
                    cur,
                    task_id,
                    "worker_recovered",
                    {"job_id": row["job_id"], "executor_exit_confirmed": attempt.exit_confirmed},
                    attempt_id=attempt.attempt_id,
                )

    def events(
        self, task_id: str, *, after: int = 0, limit: int = 100, wait_seconds: float = 0
    ) -> dict[str, Any]:
        if (
            type(after) is not int
            or not 0 <= after < 2**63
            or type(limit) is not int
            or not 1 <= limit <= 500
            or not math.isfinite(wait_seconds)
            or not 0 <= wait_seconds <= 30
        ):
            raise BridgeError(
                "INVALID_INPUT",
                "events requires a nonnegative signed-64-bit cursor, limit=1..500, wait=0..30",
            )
        deadline = time.monotonic() + wait_seconds
        while True:
            with self.store.transaction() as cur:
                task = self.store.get_task(task_id, cur=cur)
                rows = cur.execute(
                    "SELECT seq,event_id,type,attempt_id,from_state,to_state,payload,created_at "
                    "FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (task_id, after, limit + 1),
                ).fetchall()
                events = [{**dict(r), "payload": json.loads(r["payload"])} for r in rows[:limit]]
            # Waiting never holds a DB lock and never changes task/model execution.
            if events or time.monotonic() >= deadline or task.state not in EXECUTING:
                return {
                    "task_id": task_id,
                    "state": task.state.value,
                    "events": events,
                    "next_cursor": events[-1]["seq"] if events else after,
                    "has_more": len(rows) > limit,
                    "wait_timed_out": not events and time.monotonic() >= deadline,
                }
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
