"""Bridge core: task lifecycle orchestration on top of store, workspace, runner and adapters.

Every public method returns a JSON-serializable receipt or raises :class:`BridgeError`. The
foreground ``run`` owns the executor process group for the duration of the attempt; other CLI
processes communicate with it only through the SQLite store (e.g. ``cancel_requested``).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness_bridge import SCHEMA_VERSION, __version__
from harness_bridge.adapters.base import (
    ExecutorAdapter,
    ExecutorResult,
    InvocationContext,
    ParsedEvent,
    TaskPacket,
)
from harness_bridge.adapters.claude_code import (
    ClaudeCodeAdapter,
    ClaudeSettings,
    help_flags,
    preflight,
)
from harness_bridge.adapters.fake import FakeExecutorAdapter
from harness_bridge.artifacts import (
    atomic_write_json,
    fit_summary,
    store_bounded_file,
    store_capture,
)
from harness_bridge.baselines import approved, retain_approval, validate_pin
from harness_bridge.config import BridgeConfig, evaluate_live_gate, load_config
from harness_bridge.coordination import AdvisorClaim, Coordinator
from harness_bridge.errors import BridgeError
from harness_bridge.models import (
    TaskSpec,
    canonical_json,
    parse_review,
    parse_task_spec,
    sha256_digest,
)
from harness_bridge.planning import ChildPlans
from harness_bridge.policy import (
    PathPolicy,
    Violation,
    is_secret_path,
    redact_text,
    symlink_escapes,
)
from harness_bridge.preparation import Preparations
from harness_bridge.readiness import EnvironmentRequirements, inspect_readiness
from harness_bridge.runner import ProcessSpec, RunLimits, run_process, runner_identity
from harness_bridge.runner import group_alive as _group_alive
from harness_bridge.runner import runner_alive as _runner_alive
from harness_bridge.state import AttemptOutcome, TaskState
from harness_bridge.store import AttemptRecord, Store, TaskRecord, new_id, utc_now
from harness_bridge.verification import (
    aggregate_status,
    failing_tails,
    run_checks,
    warnings_for,
)
from harness_bridge.workspace import (
    Snapshot,
    create_worktree,
    inspect_source_repo,
    snapshot_summary,
    take_snapshot,
    write_diff,
)

S = TaskState
MAX_KEPT_EVENTS = 500
FAULT_ENV = "HBRIDGE_TEST_FAULT"


def _fault_point(name: str) -> None:
    """Test-only crash injection (``HBRIDGE_TEST_FAULT=<name>``): simulates a runner crash."""
    if os.environ.get(FAULT_ENV) == name:
        sys.stderr.write(f"hbridge: injected fault {name}\n")
        sys.stderr.flush()
        os._exit(70)


@dataclass
class StopFlag:
    """Set by the CLI's signal handlers; polled by the runner loop."""

    reason: str | None = None


class Bridge:
    def __init__(
        self,
        state_dir: Path,
        *,
        env: dict[str, str] | None = None,
        python_executable: str | None = None,
        stop_flag: StopFlag | None = None,
        advisor_claim: AdvisorClaim | None = None,
    ) -> None:
        self.state_dir = state_dir.expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.env = dict(os.environ) if env is None else dict(env)
        self.config: BridgeConfig = load_config(self.state_dir)
        self.store = Store(self.state_dir / "bridge.sqlite3")
        self.coordination = Coordinator(self.store)
        self.plans = ChildPlans(self.coordination)
        self.preparations = Preparations(self)
        self.advisor_claim = advisor_claim
        self.python = python_executable or sys.executable
        self.stop_flag = stop_flag or StopFlag()

    def close(self) -> None:
        self.store.close()

    @contextmanager
    def _advisor_transaction(
        self, task_id: str, *, allow_stopping: bool = False
    ) -> Iterator[sqlite3.Cursor]:
        with self.store.transaction() as cur:
            goal = self.coordination.guard_task(
                cur, task_id, self.advisor_claim, allow_stopping=allow_stopping
            )
            yield cur
            if goal is not None:
                self.coordination.event(
                    cur,
                    goal["goal_id"],
                    goal["advisor_epoch"],
                    "child_mutation",
                    {"task_id": task_id},
                )

    def _check_advisor(self, task_id: str, *, allow_stopping: bool = False) -> None:
        with self.store.transaction() as cur:
            self.coordination.guard_task(
                cur, task_id, self.advisor_claim, allow_stopping=allow_stopping
            )

    # --- paths -------------------------------------------------------------------------------

    @property
    def worktrees_dir(self) -> Path:
        return self.state_dir / "worktrees"

    @property
    def artifacts_root(self) -> Path:
        return self.state_dir / "artifacts"

    @property
    def scratch_dir(self) -> Path:
        return self.state_dir / "tmp"

    def attempt_dir(self, task_id: str, attempt_id: str) -> Path:
        return self.artifacts_root / task_id / attempt_id

    # --- spec integrity ----------------------------------------------------------------------

    def _spec(self, task: TaskRecord) -> TaskSpec:
        """Load the frozen TaskSpec, refusing it if its digests no longer match (S03)."""
        actual = "sha256:" + _sha256(task.spec_json.encode("utf-8"))
        data = json.loads(task.spec_json)
        verifier = sha256_digest(data.get("verification"))
        if actual != task.spec_digest or verifier != task.verifier_digest:
            raise BridgeError(
                "INTEGRITY_ERROR",
                "frozen TaskSpec/verifier configuration does not match its recorded digest; "
                "acceptance criteria may have been altered after creation",
                task_id=task.task_id,
            )
        return parse_task_spec(data)

    # --- create --------------------------------------------------------------------------

    def create(
        self,
        spec_data: Any,
        idempotency_key: str,
        *,
        goal_id: str | None = None,
        _child_id: str | None = None,
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 200 or not idempotency_key.isprintable():
            raise BridgeError("INVALID_INPUT", "idempotency key must be 1-200 printable characters")
        if goal_id is not None:
            with self.store.transaction() as cur:
                self.coordination.guard_goal(cur, goal_id, self.advisor_claim)
        spec = parse_task_spec(spec_data)
        normalized = spec.model_dump(mode="json")
        request_digest = sha256_digest(normalized)
        existing = self.store.find_task_by_key(idempotency_key)
        if existing is not None:
            return self._create_replay(existing, request_digest, goal_id, _child_id)

        src = inspect_source_repo(spec.repo.path, spec.repo.base_ref)
        task_id = new_id("tsk")
        spec_json = canonical_json(normalized)
        values = {
            "task_id": task_id,
            "idempotency_key": idempotency_key,
            "request_digest": request_digest,
            "spec_json": spec_json,
            "spec_digest": "sha256:" + _sha256(spec_json.encode("utf-8")),
            "verifier_digest": sha256_digest(normalized["verification"]),
            "task_version": 1,
            "repo_path": spec.repo.path,
            "repo_identity": src.identity,
            "base_ref": spec.repo.base_ref,
            "base_sha": src.base_sha,
        }
        try:
            with self.store.transaction() as cur:
                self.store.insert_task(cur, values)
                if goal_id is not None:
                    self.coordination.link_task(
                        cur, goal_id, self.advisor_claim, values, spec.executor.kind, _child_id
                    )
                if _child_id is not None:
                    if self.plans.get(cur, _child_id)["goal_id"] != goal_id:
                        raise BridgeError("INVALID_INPUT", "child plan belongs to another goal")
                    self.plans.attach(cur, _child_id, self.advisor_claim, task_id, normalized)
                self.store.add_event(
                    cur,
                    task_id,
                    "task_created",
                    {"base_sha": src.base_sha, "request_digest": request_digest},
                    to_state=S.CREATED.value,
                )
        except sqlite3.IntegrityError:
            raced = self.store.find_task_by_key(idempotency_key)
            if raced is None:
                raise
            return self._create_replay(raced, request_digest, goal_id, _child_id)
        self._prepare_workspace(task_id)
        return self._task_receipt(self.store.get_task(task_id), created=True)

    def _create_replay(
        self,
        existing: TaskRecord,
        request_digest: str,
        goal_id: str | None,
        child_id: str | None = None,
    ) -> dict[str, Any]:
        with self.store.transaction() as cur:
            self.coordination.guard_task(cur, existing.task_id, self.advisor_claim)
            if (
                child_id is not None
                and self.plans.get(cur, child_id)["task_id"] != existing.task_id
            ):
                raise BridgeError(
                    "IDEMPOTENCY_CONFLICT", "existing task does not belong to this child plan"
                )
            if self.coordination.task_goal(cur, existing.task_id) != goal_id:
                raise BridgeError(
                    "IDEMPOTENCY_CONFLICT", "existing task belongs to a different goal"
                )
        if existing.request_digest != request_digest:
            raise BridgeError(
                "IDEMPOTENCY_CONFLICT",
                "idempotency key already used for a different task request",
                task_id=existing.task_id,
            )
        return self._task_receipt(existing, created=False)

    def materialize(self, child_id: str) -> dict[str, Any]:
        # Persist conflicts as well as successful fixed baselines before attempting a task.
        with self.store.transaction() as cur:
            self.plans.freeze_baseline(cur, child_id, self.advisor_claim)
        with self.store.transaction() as cur:
            data = self.plans.materialization_spec(cur, child_id, self.advisor_claim)
            row = self.plans.get(cur, child_id)
            goal_id = row["goal_id"]
        receipt = self.create(data, f"materialize:{child_id}", goal_id=goal_id, _child_id=child_id)
        return {**receipt, "child_id": child_id}

    def child_preflight(self, child_id: str) -> dict[str, Any]:
        with self.store.transaction() as cur:
            row = self.plans.get(cur, child_id)
            if not row["task_id"]:
                raise BridgeError(
                    "STATE_CONFLICT", "materialize the child before workspace preflight"
                )
            context = self._child_context(cur, row["task_id"], require_ready=False)
            assert context is not None
            return dict(context["readiness"])

    def _child_context(
        self,
        cur: sqlite3.Cursor,
        task_id: str,
        *,
        require_ready: bool = True,
        check_preparation: bool = True,
    ) -> dict[str, Any] | None:
        row = cur.execute("SELECT child_id FROM child_plans WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            return None
        child = self.plans.get(cur, row["child_id"])
        task = self.store.get_task(task_id, cur=cur)
        goal = self.coordination._goal(cur, child["goal_id"])
        baseline = self.plans.baseline(cur, row["child_id"])
        # Pre-v4 independent roots may already be materialized; their original pinned
        # goal base remains valid without inventing a new dependency result.
        if baseline is not None:
            if baseline["status"] != "ready" or baseline["commit_sha"] != task.base_sha:
                raise BridgeError("INTEGRITY_ERROR", "task differs from frozen child baseline")
            validate_pin(task.repo_path, baseline)
        elif json.loads(child["spec_json"])["depends_on"] or task.base_sha != goal["base_sha"]:
            raise BridgeError("INTEGRITY_ERROR", "task is missing its dependency baseline")
        data = json.loads(child["spec_json"]).get("environment") or {}
        requirements = EnvironmentRequirements.model_validate(data)
        readiness = inspect_readiness(task, self._spec(task), requirements, self.env)
        setup = json.loads(child["spec_json"]).get("preparation")
        if setup and check_preparation:
            prepared = self.preparations.readiness(cur, task_id, setup)
            readiness["preparation"] = prepared
            readiness["ready"] = readiness["ready"] and prepared["ready"]
        if require_ready and not readiness["ready"]:
            raise BridgeError(
                "PREFLIGHT_FAILED",
                "child workspace requirements or preparation evidence are missing/stale",
                task_id=task_id,
                details=readiness,
            )
        return {
            "goal_id": goal["goal_id"],
            "objective": json.loads(goal["spec_json"])["objective"],
            "child_id": child["child_id"],
            "child_key": child["child_key"],
            "base_sha": task.base_sha,
            "worktree": task.worktree_path,
            "dependencies": baseline["inputs"] if baseline else [],
            "environment": data,
            "preparation_id": readiness.get("preparation", {})
            .get("latest", {})
            .get("preparation_id")
            if readiness.get("preparation", {}).get("latest")
            else None,
            "readiness": readiness,
        }

    def _child_context_for_preparation(self, task_id: str) -> dict[str, Any]:
        with self.store.transaction() as cur:
            context = self._child_context(
                cur, task_id, require_ready=False, check_preparation=False
            )
            assert context is not None
            return dict(context["readiness"])

    def retain_approved(self, task_id: str) -> dict[str, Any]:
        """Explicitly retain an older approval only if its candidate/evidence still match."""
        self._check_advisor(task_id)
        task = self.store.get_task(task_id)
        self._spec(task)
        with self._advisor_transaction(task_id) as cur:
            existing = approved(cur, task_id)
            if existing:
                validate_pin(task.repo_path, existing)
                return existing
            task = self.store.get_task(task_id, cur=cur)
            if task.state != S.SUCCEEDED or task.current_attempt_id is None:
                raise BridgeError("STATE_CONFLICT", "retention requires an approved task")
            attempt = self.store.get_attempt(task.current_attempt_id, cur=cur)
            manifest = self._load_manifest(attempt)
            review = cur.execute(
                "SELECT * FROM reviews WHERE task_id=? AND attempt_id=? AND status='accepted' "
                "AND verdict='approve'",
                (task_id, attempt.attempt_id),
            ).fetchone()
            if (
                review is None
                or manifest is None
                or self.current_fingerprint(task) != attempt.fingerprint
                or json.loads(review["receipt_json"])["snapshot_digest"] != attempt.fingerprint
            ):
                raise BridgeError(
                    "STALE_REVIEW", "older approved candidate/evidence no longer match"
                )
            record = retain_approval(cur, task, manifest, review["review_id"])
            self.store.add_event(cur, task_id, "approved_snapshot_retained", record)
            return record

    def _prepare_workspace(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        worktree = self.worktrees_dir / task_id
        branch = f"hbridge/{task_id}"
        try:
            create_worktree(task.repo_path, worktree, branch, task.base_sha)
        except BridgeError as exc:
            with self.store.transaction() as cur:
                if self.store.get_task(task_id, cur=cur).state == S.CANCELLED:
                    self.store.add_event(
                        cur, task_id, "workspace_error_after_cancel", {"message": exc.message}
                    )
                    return
                self.store.transition(
                    cur,
                    task_id,
                    S.CREATED,
                    S.BLOCKED,
                    reason="workspace_error",
                    details={"message": exc.message},
                )
            raise BridgeError("WORKSPACE_ERROR", exc.message, task_id=task_id) from None
        with self.store.transaction() as cur:
            if self.store.get_task(task_id, cur=cur).state == S.CANCELLED:
                self.store.update_task(
                    cur, task_id, worktree_path=str(worktree), task_branch=branch
                )
                self.store.add_event(
                    cur,
                    task_id,
                    "workspace_ready_after_cancel",
                    {"worktree": str(worktree), "branch": branch},
                )
                return
            self.store.transition(
                cur,
                task_id,
                S.CREATED,
                S.READY,
                reason="workspace_ready",
                event_type="workspace_ready",
                payload={"worktree": str(worktree), "branch": branch},
                worktree_path=str(worktree),
                task_branch=branch,
            )

    def _goal_id(self, task_id: str) -> str | None:
        with self.store.transaction() as cur:
            return self.coordination.task_goal(cur, task_id)

    def _task_receipt(self, task: TaskRecord, **extra: Any) -> dict[str, Any]:
        out = {
            "goal_id": self._goal_id(task.task_id),
            "task_id": task.task_id,
            "state": task.state.value,
            "task_version": task.task_version,
            "base_sha": task.base_sha,
            "worktree": task.worktree_path,
            "branch": task.task_branch,
            "spec_digest": task.spec_digest,
        }
        out.update(extra)
        return out

    # --- run -----------------------------------------------------------------------------

    def _adapter(
        self, spec: TaskSpec, mode: str, executor_binary: str | None
    ) -> tuple[ExecutorAdapter, str | None]:
        """Pick the adapter and the executable it will launch (never a real binary in mock)."""
        if spec.executor.kind == "fake":
            if mode != "mock":
                raise BridgeError("INVALID_INPUT", "the fake executor only runs in mock mode")
            if executor_binary:
                raise BridgeError("INVALID_INPUT", "--stub-binary applies to claude-code only")
            assert spec.executor.scenario is not None
            return FakeExecutorAdapter(spec.executor.scenario), None
        adapter = ClaudeCodeAdapter(
            ClaudeSettings(
                requested_model=spec.executor.requested_model,
                max_turns=spec.limits.max_turns_per_attempt,
                permission_mode=spec.executor.permission_mode,
                allowed_tools=tuple(spec.executor.allowed_tools),
                strict_mcp_config=spec.executor.strict_mcp_config,
            )
        )
        real = self.config.claude_binary or shutil.which("claude", path=self.env.get("PATH"))
        if mode == "mock":
            if not executor_binary:
                raise BridgeError(
                    "PREFLIGHT_FAILED",
                    "claude-code in mock mode needs --stub-binary (a non-model stand-in for "
                    "contract tests); a real run requires --mode live and the live gate",
                )
            stub = os.path.realpath(executor_binary)
            looks_real = os.path.basename(stub).lower().startswith("claude") or (
                real is not None and os.path.realpath(real) == stub
            )
            if not os.path.isabs(executor_binary) or looks_real:
                raise BridgeError(
                    "PREFLIGHT_FAILED",
                    "--stub-binary must be an absolute path to a stand-in that is not the real "
                    "claude executable (and not named 'claude*')",
                )
            if not os.access(stub, os.X_OK):
                raise BridgeError("PREFLIGHT_FAILED", f"stub binary {stub} is not executable")
            return adapter, stub
        if executor_binary:
            raise BridgeError("INVALID_INPUT", "--stub-binary is only allowed in mock mode")
        if real is None:
            raise BridgeError(
                "PREFLIGHT_FAILED",
                "claude executable not found (set [live] claude_binary in config.toml)",
            )
        return adapter, real

    def _should_stop_factory(self, task_id: str) -> Callable[[], str | None]:
        def should_stop() -> str | None:
            if self.stop_flag.reason:
                return "interrupted"
            try:
                if self.store.get_task(task_id).cancel_requested:
                    return "cancelled"
            except BridgeError:
                return None
            return None

        return should_stop

    def run(
        self,
        task_id: str,
        *,
        mode: str = "mock",
        allow_model_usage: bool = False,
        executor_binary: str | None = None,
    ) -> dict[str, Any]:
        self._check_advisor(task_id)
        if mode not in ("mock", "live"):
            raise BridgeError("USAGE_ERROR", "mode must be 'mock' or 'live'")
        task = self.store.get_task(task_id)
        spec = self._spec(task)
        if mode == "live":
            gate = evaluate_live_gate(
                mode=mode, allow_model_usage=allow_model_usage, config=self.config, env=self.env
            )
            if not gate.open:
                raise BridgeError(
                    "LIVE_GATE_CLOSED",
                    "live dispatch refused: " + "; ".join(gate.reasons),
                    task_id=task_id,
                    details=gate.to_dict(),
                )
        adapter, binary = self._adapter(spec, mode, executor_binary)
        if task.state != S.READY:
            raise BridgeError(
                "STATE_CONFLICT",
                f"run requires state READY, task is {task.state}",
                task_id=task_id,
                details={"actual_state": task.state.value},
            )
        if task.attempts_used >= spec.limits.max_attempts:
            with self._advisor_transaction(task_id) as cur:
                self.store.transition(
                    cur, task_id, S.READY, S.FAILED, reason="attempt_budget_exhausted"
                )
            raise BridgeError(
                "BUDGET_EXHAUSTED",
                f"all {spec.limits.max_attempts} attempts used",
                task_id=task_id,
            )
        assert task.worktree_path is not None
        with self.store.transaction() as cur:
            context = self._child_context(cur, task_id)
        seq = task.attempts_used + 1
        feedback = task.pending_feedback
        kind = "initial" if seq == 1 else ("repair" if feedback else "retry")
        packet = TaskPacket(
            task_id=task_id,
            attempt_id=new_id("att"),
            attempt_seq=seq,
            attempt_kind=kind,
            goal=spec.goal,
            requirements=list(spec.requirements),
            allowed_paths=list(spec.allowed_paths),
            forbidden_paths=list(spec.forbidden_paths),
            verification=[
                {"id": c.id, "argv": list(c.argv), "required": c.required, "trust": c.trust}
                for c in spec.verification
            ],
            max_turns=spec.limits.max_turns_per_attempt,
            feedback=feedback,
            context=context,
        )
        attempt_id = packet.attempt_id
        resume = self._resume_session(task, spec) if kind == "repair" else None
        ctx = InvocationContext(
            worktree=task.worktree_path,
            mode=mode,
            python_executable=self.python,
            base_env=self.env,
            executor_binary=binary,
            resume_session_id=resume,
        )
        invocation = adapter.build_invocation(packet, ctx)
        if mode == "live":
            assert isinstance(adapter, ClaudeCodeAdapter) and binary is not None
            listed, version = help_flags(binary, self.env)
            checked = preflight(
                adapter,
                invocation.argv,
                listed_flags=listed,
                allow_unlisted=self.config.allow_unlisted_flags,
            )
            invocation.notes.append(f"claude --version: {version}")
            invocation.notes.append(
                "flag evidence: "
                + ", ".join(f"{f}={e['status']}" for f, e in checked["flag_evidence"].items())
            )
        launch_token = uuid.uuid4().hex
        evidence = _evidence_level(spec.executor.kind, mode)
        with self._advisor_transaction(task_id) as cur:
            self.coordination.guard_dispatch(cur, task_id, self.advisor_claim, kind)
            # Check again after invocation construction: a late filesystem/ownership
            # change must not slip through the legacy run entrypoint.
            self._child_context(cur, task_id)
            self.store.transition(
                cur,
                task_id,
                S.READY,
                S.STARTING,
                reason="dispatch",
                event_type="attempt_starting",
                attempt_id=attempt_id,
                payload={
                    "seq": seq,
                    "kind": kind,
                    "launch_token": launch_token,
                    "invocation_digest": invocation.digest(),
                },
                current_attempt_id=attempt_id,
                attempts_used=seq,
                repair_cycles_used=task.repair_cycles_used + (1 if kind == "repair" else 0),
                pending_feedback=None,
                cancel_requested=0,
            )
            self.store.insert_attempt(
                cur,
                {
                    "attempt_id": attempt_id,
                    "task_id": task_id,
                    "seq": seq,
                    "kind": kind,
                    "executor_kind": spec.executor.kind,
                    "mode": mode,
                    "requested_model": invocation.requested_model,
                    "invocation_digest": invocation.digest(),
                    "invocation": invocation.describe(),
                    "feedback": feedback,
                    "launch_token": launch_token,
                    "runner": runner_identity(),
                    "status": "starting",
                    "evidence_level": evidence,
                },
            )
        _fault_point("after_starting_commit")

        events: list[ParsedEvent] = []
        dropped = 0
        session_recorded = False

        def on_spawn(pid: int, pgid: int) -> None:
            _fault_point("after_spawn_before_record")
            with self.store.transaction() as cur:
                self.store.transition(
                    cur,
                    task_id,
                    S.STARTING,
                    S.RUNNING,
                    reason="spawned",
                    event_type="executor_spawned",
                    attempt_id=attempt_id,
                    payload={"pid": pid, "pgid": pgid},
                )
                self.store.update_attempt(cur, attempt_id, status="running", pid=pid, pgid=pgid)

        def on_line(line: bytes, truncated: bool) -> None:
            nonlocal dropped, session_recorded
            event = ParsedEvent("oversized") if truncated else adapter.parse_event(line)
            if len(events) < MAX_KEPT_EVENTS or event.kind in ("result", "session"):
                events.append(event)
            else:
                dropped += 1
            if event.kind == "session" and event.session_id and not session_recorded:
                session_recorded = True
                with self.store.transaction() as cur:
                    self.store.update_attempt(cur, attempt_id, session_id=event.session_id)
                    self.store.add_event(
                        cur,
                        task_id,
                        "executor_session",
                        {"session_id": event.session_id, "model": event.model},
                        attempt_id=attempt_id,
                    )

        budget = spec.limits.max_artifact_bytes
        limits = RunLimits(
            wall_timeout=spec.limits.wall_timeout_seconds,
            kill_grace=spec.limits.kill_grace_seconds,
            stdout_head=budget // 16,
            stdout_tail=budget * 3 // 16,
            stderr_head=budget // 32,
            stderr_tail=budget * 3 // 32,
        )
        outcome = run_process(
            ProcessSpec(
                argv=invocation.argv,
                cwd=invocation.cwd,
                env=invocation.env,
                stdin=invocation.stdin,
            ),
            limits,
            on_spawn=on_spawn,
            on_line=on_line,
            should_stop=self._should_stop_factory(task_id),
        )
        result = adapter.classify_completion(outcome, events)
        result.protocol["events_dropped"] = dropped
        adir = self.attempt_dir(task_id, attempt_id)
        process = outcome.to_dict()
        process["stdout"] = store_capture(adir / "executor.stdout.log", outcome.stdout)
        process["stderr"] = store_capture(adir / "executor.stderr.log", outcome.stderr)
        self._record_attempt_end(task, spec, attempt_id, result, process)
        return self._after_executor(task_id, attempt_id, result)

    def _record_attempt_end(
        self,
        task: TaskRecord,
        spec: TaskSpec,
        attempt_id: str,
        result: ExecutorResult,
        process: dict[str, Any],
    ) -> None:
        reported = dict(result.executor_reported)
        if isinstance(reported.get("summary"), str):
            reported["summary"] = redact_text(reported["summary"])[0]
        binding = None
        if result.session_id:
            binding = {
                "executor_kind": spec.executor.kind,
                "task_id": task.task_id,
                "attempt_id": attempt_id,
                "repo_identity": task.repo_identity,
                "worktree": task.worktree_path,
                "requested_model": spec.executor.requested_model,
                "observed_model": result.observed_model,
                "source": "executor output (adapter-parsed)",
            }
        with self.store.transaction() as cur:
            self.store.update_attempt(
                cur,
                attempt_id,
                status="ended",
                outcome=result.outcome.value,
                outcome_reason=result.reason,
                exit_code=process.get("returncode"),
                exit_signal=process.get("exit_signal"),
                exit_confirmed=1 if process.get("group_exit_confirmed") else 0,
                session_id=result.session_id,
                session_binding=binding,
                observed_model=result.observed_model,
                executor_reported={**reported, "protocol": result.protocol},
                process=process,
                usage=result.usage,
                ended_at=utc_now(),
            )
            self.store.add_event(
                cur,
                task.task_id,
                "executor_finished",
                {"outcome": result.outcome.value, "reason": result.reason},
                attempt_id=attempt_id,
                dedupe_key=f"{attempt_id}:executor_finished",
            )

    def _after_executor(
        self, task_id: str, attempt_id: str, result: ExecutorResult
    ) -> dict[str, Any]:
        o = result.outcome
        task = self.store.get_task(task_id)
        src = task.state  # STARTING (spawn failed) or RUNNING
        with self.store.transaction() as cur:
            if o is AttemptOutcome.SPAWN_FAILED:
                self.store.transition(
                    cur,
                    task_id,
                    src,
                    S.BLOCKED,
                    reason="executor_unavailable",
                    details={"message": result.reason},
                    attempt_id=attempt_id,
                )
            elif o is AttemptOutcome.OUTCOME_UNKNOWN:
                self.store.transition(
                    cur,
                    task_id,
                    src,
                    S.INTERRUPTED,
                    reason="outcome_unknown",
                    details={"outcome_known": False, "phase": "executor", "why": result.reason},
                    attempt_id=attempt_id,
                )
            elif o is AttemptOutcome.CANCELLED:
                self.store.transition(
                    cur, task_id, src, S.CANCELLED, reason="cancelled", attempt_id=attempt_id
                )
            elif o is AttemptOutcome.INTERRUPTED:
                self.store.transition(
                    cur,
                    task_id,
                    src,
                    S.INTERRUPTED,
                    reason="runner_interrupted",
                    details={"outcome_known": True, "phase": "executor"},
                    attempt_id=attempt_id,
                )
            elif o is AttemptOutcome.BLOCKED:
                self.store.transition(
                    cur,
                    task_id,
                    src,
                    S.BLOCKED,
                    reason="executor_blocked",
                    details=result.blocked,
                    attempt_id=attempt_id,
                )
            else:
                self.store.transition(
                    cur,
                    task_id,
                    src,
                    S.VERIFYING,
                    reason="executor_exited",
                    details={"runner": runner_identity(), "executor_exit_confirmed": True},
                    attempt_id=attempt_id,
                    payload={"outcome": o.value},
                )
        if self.store.get_task(task_id).state == S.VERIFYING:
            _fault_point("after_verifying_commit")
            self._verify_and_finalize(task_id, attempt_id, origin="run")
        return self._run_receipt(task_id, attempt_id)

    # --- verify / recover / cancel -----------------------------------------------------------

    def verify(self, task_id: str) -> dict[str, Any]:
        """Re-snapshot and re-run the frozen verifiers for the current attempt (no executor)."""
        self._check_advisor(task_id)
        task = self.store.get_task(task_id)
        self._spec(task)
        if task.state != S.AWAITING_REVIEW:
            raise BridgeError(
                "STATE_CONFLICT",
                f"verify requires state AWAITING_REVIEW, task is {task.state}",
                task_id=task_id,
                details={"actual_state": task.state.value},
            )
        assert task.current_attempt_id is not None
        with self._advisor_transaction(task_id) as cur:
            self.store.transition(
                cur,
                task_id,
                S.AWAITING_REVIEW,
                S.VERIFYING,
                reason="reverify_requested",
                details={"runner": runner_identity(), "executor_exit_confirmed": True},
                event_type="verification_requested",
                attempt_id=task.current_attempt_id,
            )
        self._verify_and_finalize(task_id, task.current_attempt_id, origin="verify")
        return self._run_receipt(task_id, task.current_attempt_id)

    def recover(
        self, task_id: str, *, resolve: str | None = None, acknowledge_unknown: bool = False
    ) -> dict[str, Any]:
        """Inspect a task after a crash/interruption and apply only model-free safe actions.

        Never re-dispatches an executor by itself. ``resolve='retry'|'fail'`` records an explicit
        human decision for BLOCKED / INTERRUPTED tasks.
        """
        self._check_advisor(task_id, allow_stopping=True)
        task = self.store.get_task(task_id)
        spec = self._spec(task)
        attempt = (
            self.store.get_attempt(task.current_attempt_id) if task.current_attempt_id else None
        )
        details = task.state_details or {}
        report: dict[str, Any] = {"task_id": task_id, "state_before": task.state.value}
        actions: list[str] = []
        with self.store.transaction() as cur:
            goal = self.coordination.guard_task(
                cur, task_id, self.advisor_claim, allow_stopping=True
            )
            stopping = goal is not None and bool(
                self.coordination.controls(cur, goal["goal_id"])["termination"]
            )
        if stopping and resolve == "retry":
            raise BridgeError("STATE_CONFLICT", "cannot retry after goal termination is requested")
        if stopping and resolve is None and task.state not in (S.PREPARING, S.STARTING, S.RUNNING):
            return {
                **report,
                "state_after": task.state.value,
                "actions": ["goal is stopping; no workspace or verification work resumed"],
            }

        if resolve is not None:
            if resolve not in ("retry", "fail"):
                raise BridgeError("USAGE_ERROR", "--resolve must be 'retry' or 'fail'")
            if task.state not in (S.BLOCKED, S.INTERRUPTED):
                raise BridgeError(
                    "STATE_CONFLICT",
                    f"--resolve applies to BLOCKED or INTERRUPTED tasks, task is {task.state}",
                    task_id=task_id,
                )
            unknown = task.state == S.INTERRUPTED and not details.get("outcome_known", False)
            with self.store.transaction() as cur:
                if resolve == "retry" and self.preparations.unresolved(cur, task_id):
                    raise BridgeError(
                        "CANNOT_CONFIRM_EXIT", "preparation exit remains unknown; retry is held"
                    )
            if resolve == "retry" and unknown:
                pg = attempt.pgid if attempt else None
                if pg is not None and _group_alive(pg):
                    raise BridgeError(
                        "CANNOT_CONFIRM_EXIT",
                        f"process group {pg} of the interrupted attempt still has live members; "
                        "stop it yourself before retrying (the bridge does not signal processes "
                        "it cannot prove it owns)",
                        task_id=task_id,
                    )
                if not acknowledge_unknown:
                    raise BridgeError(
                        "CANNOT_CONFIRM_EXIT",
                        "the previous attempt's outcome is unknown; a retry could run two "
                        "executors on one worktree. Check that no executor is still running, then "
                        "repeat with --acknowledge-unknown",
                        task_id=task_id,
                    )
            exhausted = task.attempts_used >= spec.limits.max_attempts
            target = S.FAILED if resolve == "fail" or exhausted else S.READY
            reason = (
                "resolved_fail"
                if resolve == "fail"
                else ("attempt_budget_exhausted" if exhausted else "resolved_retry")
            )
            with self._advisor_transaction(task_id, allow_stopping=resolve == "fail") as cur:
                self.store.transition(
                    cur,
                    task_id,
                    task.state,
                    target,
                    reason=reason,
                    event_type="recovery_resolved",
                    payload={"resolve": resolve, "acknowledged_unknown": acknowledge_unknown},
                    details={"previous_state": task.state.value, "previous_details": details},
                )
            actions.append(f"{task.state.value} -> {target.value} ({reason})")
        elif task.state == S.CREATED:
            with self._advisor_transaction(task_id) as cur:
                self.store.add_event(cur, task_id, "workspace_recovery_requested", {})
            self._prepare_workspace(task_id)
            actions.append("workspace prepared (no model involved): CREATED -> READY")
        elif task.state in (S.PREPARING, S.STARTING, S.RUNNING, S.VERIFYING):
            runner = details.get("runner") if task.state in (S.PREPARING, S.VERIFYING) else None
            runner = runner or (attempt.runner if attempt else None)
            alive = _runner_alive(runner)
            report["runner_alive"] = alive
            if alive is True:
                actions.append("runner is still active; nothing to recover")
            elif alive is None and not acknowledge_unknown:
                actions.append(
                    "runner liveness cannot be determined; no change (fail closed). Re-run with "
                    "--acknowledge-unknown after checking that no hbridge run is active"
                )
            elif task.state == S.PREPARING:
                with self._advisor_transaction(task_id, allow_stopping=True) as cur:
                    record = self.preparations.latest(cur, task_id)
                    assert record is not None
                    record.update(status="unknown", exit_confirmed=False, ended_at=utc_now())
                    self.preparations.save(cur, record)
                    self.store.transition(
                        cur,
                        task_id,
                        S.PREPARING,
                        S.INTERRUPTED,
                        reason="preparation_outcome_unknown",
                        details={
                            "phase": "preparation",
                            "outcome_known": False,
                            "preparation_id": record["preparation_id"],
                            "signalled": False,
                        },
                    )
                actions.append(
                    "preparation runner gone; outcome unknown; no signals or automatic restart"
                )
            elif task.state == S.VERIFYING:
                self._claim_verification(task, "recover")
                assert attempt is not None
                self._verify_and_finalize(task_id, attempt.attempt_id, origin="recover")
                actions.append("executor exit was already confirmed; verification re-run")
            else:
                pg = attempt.pgid if attempt else None
                group = None if pg is None else _group_alive(pg)
                phase = "launch" if task.state == S.STARTING else "executor"
                with self._advisor_transaction(task_id, allow_stopping=True) as cur:
                    self.store.transition(
                        cur,
                        task_id,
                        task.state,
                        S.INTERRUPTED,
                        reason="outcome_unknown",
                        details={
                            "outcome_known": False,
                            "phase": phase,
                            "why": "runner is gone; executor outcome cannot be confirmed",
                            "recorded_pgid": pg,
                            "process_group_possibly_alive": group,
                            "signalled": False,
                        },
                        event_type="recovery_interrupted",
                        attempt_id=attempt.attempt_id if attempt else None,
                    )
                actions.append(
                    f"{task.state.value} -> INTERRUPTED (outcome unknown; no automatic "
                    "re-dispatch, no signals sent)"
                )
        elif (
            task.state == S.INTERRUPTED
            and details.get("outcome_known")
            and details.get("phase") == "verification"
            and attempt is not None
        ):
            with self._advisor_transaction(task_id) as cur:
                self.store.transition(
                    cur,
                    task_id,
                    S.INTERRUPTED,
                    S.VERIFYING,
                    reason="resume_verification",
                    details={"runner": runner_identity(), "executor_exit_confirmed": True},
                    event_type="verification_requested",
                    attempt_id=attempt.attempt_id,
                )
            self._verify_and_finalize(task_id, attempt.attempt_id, origin="recover")
            actions.append("interrupted verification re-run (executor not re-run)")
        else:
            actions.append("no automatic action for this state")
        after = self.store.get_task(task_id)
        report.update(
            {
                "state_after": after.state.value,
                "state_reason": after.state_reason,
                "actions": actions,
                "attempts_used": after.attempts_used,
                "max_attempts": spec.limits.max_attempts,
                "options": _next_actions(after.state),
            }
        )
        return report

    def _claim_verification(self, task: TaskRecord, origin: str) -> None:
        """Take over a VERIFYING task whose runner died (CAS on revision)."""
        with self._advisor_transaction(task.task_id) as cur:
            details = dict(task.state_details or {})
            details["runner"] = runner_identity()
            details["claimed_by"] = origin
            cur.execute(
                "UPDATE tasks SET state_details=?, revision=revision+1 "
                "WHERE task_id=? AND state=? AND revision=?",
                (
                    json.dumps(details, sort_keys=True),
                    task.task_id,
                    S.VERIFYING.value,
                    task.revision,
                ),
            )
            if cur.rowcount != 1:
                raise BridgeError(
                    "STATE_CONFLICT",
                    "task changed while claiming verification",
                    task_id=task.task_id,
                )
            self.store.add_event(cur, task.task_id, "verification_claimed", {"origin": origin})

    def cancel(
        self, task_id: str, *, wait_seconds: float = 0.0, acknowledge_unknown: bool = False
    ) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        details = task.state_details or {}
        if task.state in (S.SUCCEEDED, S.FAILED, S.CANCELLED):
            raise BridgeError("STATE_CONFLICT", f"task is already {task.state}", task_id=task_id)
        unknown = task.state == S.INTERRUPTED and not details.get("outcome_known", False)
        if unknown and not acknowledge_unknown:
            raise BridgeError(
                "CANNOT_CONFIRM_EXIT",
                "the interrupted attempt's process exit is unknown, so cancellation cannot be "
                "confirmed. Check for leftover executor processes, then repeat with "
                "--acknowledge-unknown (or use recover --resolve fail)",
                task_id=task_id,
            )
        if task.state in (S.PREPARING, S.STARTING, S.RUNNING, S.VERIFYING):
            with self.store.transaction() as cur:
                self.store.update_task(cur, task_id, cancel_requested=1)
                self.store.add_event(cur, task_id, "cancel_requested", {})
            runner = details.get("runner") if task.state in (S.PREPARING, S.VERIFYING) else None
            attempt = (
                self.store.get_attempt(task.current_attempt_id) if task.current_attempt_id else None
            )
            runner = runner or (attempt.runner if attempt else None)
            alive = _runner_alive(runner)
            deadline = time.monotonic() + max(0.0, wait_seconds)
            while alive is True and time.monotonic() < deadline:
                if self.store.get_task(task_id).state not in (
                    S.PREPARING,
                    S.STARTING,
                    S.RUNNING,
                    S.VERIFYING,
                ):
                    break
                time.sleep(0.1)
            now = self.store.get_task(task_id)
            if now.state == S.CANCELLED:
                return {"task_id": task_id, "status": "cancelled", "state": now.state.value}
            return {
                "task_id": task_id,
                "status": "cancellation_pending",
                "state": now.state.value,
                "runner_alive": alive,
                "note": (
                    "the foreground runner will stop its own process group and record CANCELLED"
                    if alive
                    else "runner is not alive; nothing was signalled. Run `hbridge recover`."
                ),
            }
        with self.store.transaction() as cur:
            self.store.transition(
                cur,
                task_id,
                task.state,
                S.CANCELLED,
                reason="cancelled",
                details={
                    "previous_state": task.state.value,
                    "residual_process_risk": task.state == S.INTERRUPTED
                    and not details.get("outcome_known", False),
                },
            )
        return {"task_id": task_id, "status": "cancelled", "state": S.CANCELLED.value}

    def _run_receipt(self, task_id: str, attempt_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        attempt = self.store.get_attempt(attempt_id)
        vr = (
            self.store.get_verification_run(attempt.verification_run_id)
            if attempt.verification_run_id
            else None
        )
        return {
            "goal_id": self._goal_id(task_id),
            "task_id": task_id,
            "state": task.state.value,
            "state_reason": task.state_reason,
            "attempt_id": attempt_id,
            "attempt_seq": attempt.seq,
            "attempt_kind": attempt.kind,
            "executor_outcome": attempt.outcome,
            "executor_outcome_reason": attempt.outcome_reason,
            "evidence_level": attempt.evidence_level,
            "verification_status": vr["status"] if vr else None,
            "snapshot_digest": attempt.fingerprint,
        }

    def _resume_session(self, task: TaskRecord, spec: TaskSpec) -> str | None:
        """A session id is reused only if this task's previous attempt observed it for the same
        executor kind, repository and worktree. Otherwise the repair starts a new session."""
        if spec.executor.kind != "claude-code" or not spec.executor.resume_on_repair:
            return None
        attempts = self.store.list_attempts(task.task_id)
        if not attempts:
            return None
        prev = attempts[-1]
        binding = prev.session_binding or {}
        if (
            prev.session_id
            and prev.exit_confirmed
            and binding.get("executor_kind") == "claude-code"
            and binding.get("task_id") == task.task_id
            and binding.get("repo_identity") == task.repo_identity
            and binding.get("worktree") == task.worktree_path
        ):
            return prev.session_id
        return None

    # --- verification and manifest -----------------------------------------------------------

    def _verify_and_finalize(self, task_id: str, attempt_id: str, *, origin: str) -> None:
        task = self.store.get_task(task_id)
        spec = self._spec(task)
        attempt = self.store.get_attempt(attempt_id)
        assert task.worktree_path is not None
        worktree = Path(task.worktree_path)
        adir = self.attempt_dir(task_id, attempt_id)
        snap = take_snapshot(worktree, task.base_sha, self.scratch_dir)
        fp_before = snap.fingerprint(
            task_version=task.task_version, verifier_digest=task.verifier_digest
        )
        run_id = new_id("vr")
        log_dir = adir / "verification" / run_id
        budget = spec.limits.max_artifact_bytes
        per_stream = max(8192, (budget * 3 // 10) // max(1, 2 * len(spec.verification)))
        started = utc_now()
        results, stop = run_checks(
            list(spec.verification),
            worktree=worktree,
            log_dir=log_dir,
            base_env=self.env,
            bytes_per_stream=per_stream,
            kill_grace=spec.limits.kill_grace_seconds,
            should_stop=self._should_stop_factory(task_id),
        )
        if stop:
            with self.store.transaction() as cur:
                if stop == "cancelled":
                    self.store.transition(
                        cur,
                        task_id,
                        S.VERIFYING,
                        S.CANCELLED,
                        reason="cancelled",
                        attempt_id=attempt_id,
                    )
                else:
                    self.store.transition(
                        cur,
                        task_id,
                        S.VERIFYING,
                        S.INTERRUPTED,
                        reason="runner_interrupted",
                        details={"outcome_known": True, "phase": "verification"},
                        attempt_id=attempt_id,
                    )
            return
        snap_after = take_snapshot(worktree, task.base_sha, self.scratch_dir)
        fp_after = snap_after.fingerprint(
            task_version=task.task_version, verifier_digest=task.verifier_digest
        )
        status = aggregate_status(results, fp_before, fp_after)
        violations = self._scope_violations(spec, snap)
        diff_meta = self._store_diff(worktree, snap, adir, budget * 3 // 10)
        verification = {
            "run_id": run_id,
            "status": status,
            "origin": origin,
            "fingerprint_before": fp_before,
            "fingerprint_after": fp_after,
            "checks": [r.to_dict() for r in results],
            "warnings": warnings_for(results),
            "log_dir": str(log_dir.relative_to(adir)),
        }
        manifest = self._build_manifest(task, attempt, snap, fp_before, violations, diff_meta)
        manifest["bridge_observed"]["verification"] = verification
        manifest_path = adir / "manifest.json"
        data = atomic_write_json(manifest_path, manifest)
        atomic_write_json(adir / f"manifest-{run_id}.json", manifest)
        manifest_digest = "sha256:" + _sha256(data)
        with self.store.transaction() as cur:
            self.store.insert_verification_run(
                cur,
                {
                    "run_id": run_id,
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "fingerprint_before": fp_before,
                    "fingerprint_after": fp_after,
                    "verifier_digest": task.verifier_digest,
                    "status": status,
                    "results": [r.to_dict() for r in results],
                    "started_at": started,
                    "ended_at": utc_now(),
                },
            )
            self.store.update_attempt(
                cur,
                attempt_id,
                fingerprint=fp_before,
                manifest_path=str(manifest_path),
                manifest_digest=manifest_digest,
                verification_run_id=run_id,
            )
            self.store.transition(
                cur,
                task_id,
                S.VERIFYING,
                S.AWAITING_REVIEW,
                reason="evidence_ready",
                event_type="verification_completed",
                attempt_id=attempt_id,
                payload={"run_id": run_id, "status": status, "snapshot_digest": fp_before},
            )

    def _scope_violations(self, spec: TaskSpec, snap: Snapshot) -> list[dict[str, str]]:
        policy = PathPolicy(spec.allowed_paths, spec.forbidden_paths)
        found: list[Violation] = []
        for change in snap.changes:
            found.extend(policy.check_paths(change.touched_paths()))
            escapes = change.symlink_target is None or symlink_escapes(
                change.path, change.symlink_target
            )
            if change.entry_type == "symlink" and change.status != "D" and escapes:
                found.append(
                    Violation(change.path, "symlink_escape", "symlink points outside the repo")
                )
            if change.entry_type == "gitlink":
                found.append(
                    Violation(change.path, "nested_repository", "gitlink/nested repository entry")
                )
        unique = {(v.path, v.rule): v for v in found}
        return [v.to_dict() for v in unique.values()]

    def _store_diff(self, worktree: Path, snap: Snapshot, adir: Path, limit: int) -> dict[str, Any]:
        paths: list[str] = []
        withheld: list[str] = []
        for change in snap.changes:
            for p in change.touched_paths():
                (withheld if is_secret_path(p) else paths).append(p)
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        raw = self.scratch_dir / f"diff-{uuid.uuid4().hex}.patch"
        try:
            write_diff(worktree, snap.base_sha, snap.tree_sha, sorted(set(paths)), raw)
            meta = store_bounded_file(raw, adir / "diff.patch", max(4096, limit))
        finally:
            raw.unlink(missing_ok=True)
        meta["content_withheld_paths"] = sorted(set(withheld))
        return meta

    def _build_manifest(
        self,
        task: TaskRecord,
        attempt: AttemptRecord,
        snap: Snapshot,
        fingerprint: str,
        violations: list[dict[str, str]],
        diff_meta: dict[str, Any],
    ) -> dict[str, Any]:
        changes = []
        for c in snap.changes:
            entry = c.to_dict()
            entry["secret_path"] = any(is_secret_path(p) for p in c.touched_paths())
            entry["content_withheld"] = entry["secret_path"] or c.binary
            if c.symlink_target is not None:
                entry["symlink_target"] = c.symlink_target[:512]
            changes.append(entry)
        reported = attempt.executor_reported or {}
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "hbridge.artifact_manifest",
            "bridge_version": __version__,
            "generated_at": utc_now(),
            "goal_id": self._goal_id(task.task_id),
            "task_id": task.task_id,
            "attempt_id": attempt.attempt_id,
            "attempt_seq": attempt.seq,
            "task_version": task.task_version,
            "base_sha": task.base_sha,
            "tree_sha": snap.tree_sha,
            "fingerprint": fingerprint,
            "verifier_digest": task.verifier_digest,
            "spec_digest": task.spec_digest,
            "evidence_level": attempt.evidence_level,
            "observation_scope": (
                "git-visible worktree content relative to base: committed, staged, unstaged and "
                "untracked non-ignored files. Ignored files, files outside the worktree and "
                "external side effects are NOT observed."
            ),
            "change_list_complete": True,
            "changes": changes,
            "change_summary": snapshot_summary(snap),
            "scope_violations": violations,
            "diff": diff_meta,
            "bridge_observed": {
                "executor_outcome": attempt.outcome,
                "executor_outcome_reason": attempt.outcome_reason,
                "exit_code": attempt.exit_code,
                "exit_signal": attempt.exit_signal,
                "exit_confirmed": attempt.exit_confirmed,
                "process": attempt.process,
            },
            "executor_reported": {
                "note": "claims made by the executor; never counted as verification",
                **{k: v for k, v in reported.items() if k != "protocol"},
                "session_id": attempt.session_id,
                "observed_model": attempt.observed_model,
            },
            "protocol": reported.get("protocol"),
            "usage": attempt.usage,
        }

    # --- evidence views ----------------------------------------------------------------------

    def _load_manifest(self, attempt: AttemptRecord) -> dict[str, Any] | None:
        if not attempt.manifest_path:
            return None
        path = Path(attempt.manifest_path)
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if "sha256:" + _sha256(data) != attempt.manifest_digest:
            raise BridgeError(
                "INTEGRITY_ERROR",
                "manifest file does not match its recorded digest",
                task_id=attempt.task_id,
                attempt_id=attempt.attempt_id,
            )
        manifest: dict[str, Any] = json.loads(data)
        return manifest

    def current_fingerprint(self, task: TaskRecord) -> str:
        assert task.worktree_path is not None
        snap = take_snapshot(Path(task.worktree_path), task.base_sha, self.scratch_dir)
        return snap.fingerprint(
            task_version=task.task_version, verifier_digest=task.verifier_digest
        )

    def gate_blockers(
        self,
        task: TaskRecord,
        attempt: AttemptRecord | None,
        manifest: dict[str, Any] | None,
        current_fp: str | None,
    ) -> list[str]:
        """Everything that prevents SUCCEEDED right now. Empty list == approvable."""
        blockers: list[str] = []
        if task.state != S.AWAITING_REVIEW:
            blockers.append(f"task state is {task.state}, not AWAITING_REVIEW")
        if attempt is None:
            return [*blockers, "no attempt"]
        if attempt.outcome != AttemptOutcome.SUCCEEDED.value:
            blockers.append(f"executor outcome is {attempt.outcome} ({attempt.outcome_reason})")
        if not attempt.exit_confirmed:
            blockers.append("executor process exit was not confirmed")
        if manifest is None:
            return [*blockers, "no evidence manifest"]
        if not manifest.get("change_list_complete"):
            blockers.append("change list incomplete")
        if manifest.get("scope_violations"):
            blockers.append(f"{len(manifest['scope_violations'])} unresolved scope violation(s)")
        verification = manifest.get("bridge_observed", {}).get("verification") or {}
        if verification.get("status") != "passed":
            blockers.append(f"verification status is {verification.get('status')}")
        for check in verification.get("checks", []):
            if check.get("required") and check.get("status") != "passed":
                blockers.append(f"required check {check['id']!r} is {check['status']}")
        if manifest.get("verifier_digest") != task.verifier_digest:
            blockers.append("manifest was produced with a different verifier configuration")
        if manifest.get("fingerprint") != attempt.fingerprint:
            blockers.append("manifest does not belong to the attempt's recorded snapshot")
        if current_fp is not None and current_fp != manifest.get("fingerprint"):
            blockers.append("candidate changed after evidence was produced; run `hbridge verify`")
        return blockers

    def status(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        spec = self._spec(task)
        with self.store.transaction() as cur:
            retained = approved(cur, task_id)
            preparation = self.preparations.latest(cur, task_id)
        attempts = self.store.list_attempts(task_id)
        current = next((a for a in attempts if a.attempt_id == task.current_attempt_id), None)
        gate: dict[str, Any] | None = None
        if task.state == S.AWAITING_REVIEW and current is not None:
            manifest = self._load_manifest(current)
            blockers = self.gate_blockers(task, current, manifest, self.current_fingerprint(task))
            gate = {"approvable": not blockers, "blockers": blockers}
        return {
            "goal_id": self._goal_id(task.task_id),
            "task_id": task.task_id,
            "state": task.state.value,
            "state_reason": task.state_reason,
            "state_details": task.state_details,
            "goal": spec.goal[:500],
            "executor_kind": spec.executor.kind,
            "task_version": task.task_version,
            "base_sha": task.base_sha,
            "worktree": task.worktree_path,
            "attempts_used": task.attempts_used,
            "max_attempts": spec.limits.max_attempts,
            "repair_cycles_used": task.repair_cycles_used,
            "max_repair_cycles": spec.limits.max_repair_cycles,
            "cancel_requested": task.cancel_requested,
            "current_attempt_id": task.current_attempt_id,
            "attempts": [_attempt_brief(a) for a in attempts],
            "approval_gate": gate,
            "approved_snapshot": retained,
            "preparation": preparation,
            "reviews": self.store.list_reviews(task_id),
            "recent_events": [
                {k: e[k] for k in ("seq", "type", "from_state", "to_state", "created_at")}
                for e in self.store.list_events(task_id, limit=12)
            ],
            "next_actions": _next_actions(task.state),
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    def artifacts(
        self, task_id: str, *, attempt_seq: int | None = None, show: str | None = None
    ) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        attempts = self.store.list_attempts(task_id)
        if not attempts:
            raise BridgeError("NOT_FOUND", "task has no attempts yet", task_id=task_id)
        if attempt_seq is None:
            attempt = next(a for a in attempts if a.attempt_id == task.current_attempt_id)
        else:
            match = [a for a in attempts if a.seq == attempt_seq]
            if not match:
                raise BridgeError("NOT_FOUND", f"attempt #{attempt_seq} not found", task_id=task_id)
            attempt = match[0]
        if show is not None:
            return self._show_artifact(task, attempt, show)
        return self._summary(task, attempt)

    def _summary(self, task: TaskRecord, attempt: AttemptRecord) -> dict[str, Any]:
        spec = self._spec(task)
        manifest = self._load_manifest(attempt)
        is_current = attempt.attempt_id == task.current_attempt_id
        current_fp = (
            self.current_fingerprint(task)
            if is_current and task.state == S.AWAITING_REVIEW
            else None
        )
        blockers = (
            self.gate_blockers(task, attempt, manifest, current_fp)
            if is_current
            else ["not the current attempt"]
        )
        adir = self.attempt_dir(task.task_id, attempt.attempt_id)
        out: dict[str, Any] = {
            "goal_id": self._goal_id(task.task_id),
            "task_id": task.task_id,
            "state": task.state.value,
            "goal": spec.goal[:2000],
            "task_version": task.task_version,
            "attempt": _attempt_brief(attempt),
            "snapshot_digest": attempt.fingerprint,
            "approval_gate": {"approvable": not blockers, "blockers": blockers},
        }
        if manifest is None:
            out["evidence"] = "no manifest for this attempt (executor did not reach verification)"
            out["executor_reported"] = attempt.executor_reported
            return fit_summary(out)
        verification = manifest["bridge_observed"]["verification"]
        tails = failing_tails(verification["checks"], adir / verification["log_dir"])
        checks = []
        for c in verification["checks"]:
            view = {k: c[k] for k in ("id", "trust", "required", "status", "exit_code")}
            view["duration_seconds"] = c.get("duration_seconds")
            if c["id"] in tails:
                view.update(tails[c["id"]])
            checks.append(view)
        risks = []
        if manifest["scope_violations"]:
            risks.append("scope violations present")
        if attempt.outcome != AttemptOutcome.SUCCEEDED.value:
            risks.append(f"executor outcome {attempt.outcome}")
        reported = manifest["executor_reported"]
        if reported.get("tests_reported") == "passed" and verification["status"] != "passed":
            risks.append("executor claimed tests passed but bridge verification did not pass")
        if manifest["diff"].get("truncated"):
            risks.append("stored diff is truncated; inspect the worktree for full content")
        pin = reported.get("model_pin")
        if pin == "mismatch":
            risks.append("observed model differs from the requested model pin")
        elif pin == "unknown":
            risks.append("requested model pin was not confirmed by executor output")
        if reported.get("permission_denials"):
            risks.append(f"executor hit {reported['permission_denials']} permission denial(s)")
        out.update(
            {
                "changes": {
                    **manifest["change_summary"],
                    "paths": [
                        {
                            k: ch.get(k)
                            for k in (
                                "path",
                                "old_path",
                                "status",
                                "entry_type",
                                "lines_added",
                                "lines_deleted",
                                "binary",
                                "secret_path",
                            )
                        }
                        for ch in manifest["changes"]
                    ],
                },
                "scope_violations": manifest["scope_violations"],
                "verification": {
                    "run_id": verification["run_id"],
                    "status": verification["status"],
                    "checks": checks,
                    "warnings": verification.get("warnings", []),
                },
                "executor_reported": reported,
                "risks": risks,
                "usage": manifest.get("usage"),
                "review_template": {
                    "schema_version": SCHEMA_VERSION,
                    "task_id": task.task_id,
                    "attempt_id": attempt.attempt_id,
                    "task_version": task.task_version,
                    "snapshot_digest": attempt.fingerprint,
                },
                "artifact_names": _artifact_names(manifest, verification),
                "artifact_dir": str(adir),
            }
        )
        return fit_summary(out)

    def _show_artifact(self, task: TaskRecord, attempt: AttemptRecord, name: str) -> dict[str, Any]:
        adir = self.attempt_dir(task.task_id, attempt.attempt_id)
        manifest = self._load_manifest(attempt)
        allowed: dict[str, Path] = {
            "stdout": adir / "executor.stdout.log",
            "stderr": adir / "executor.stderr.log",
        }
        if manifest is not None:
            allowed["manifest"] = adir / "manifest.json"
            allowed["diff"] = adir / "diff.patch"
            verification = manifest["bridge_observed"]["verification"]
            for c in verification["checks"]:
                for stream in ("stdout", "stderr"):
                    allowed[f"check:{c['id']}:{stream}"] = (
                        adir / verification["log_dir"] / f"{c['id']}.{stream}.log"
                    )
        if name not in allowed:
            raise BridgeError(
                "INVALID_INPUT",
                f"unknown artifact {name!r}; available: {sorted(allowed)}",
                task_id=task.task_id,
            )
        path = allowed[name]
        try:
            data = path.read_bytes()
        except OSError:
            raise BridgeError("NOT_FOUND", f"artifact {name!r} is missing") from None
        limit = 1024 * 1024
        return {
            "task_id": task.task_id,
            "attempt_id": attempt.attempt_id,
            "name": name,
            "path": str(path),
            "bytes": len(data),
            "truncated_in_output": len(data) > limit,
            "content": data[:limit].decode("utf-8", "replace"),
        }

    # --- review --------------------------------------------------------------------------------

    def review(self, task_id: str, data: Any) -> dict[str, Any]:
        self._check_advisor(task_id)
        decision = parse_review(data)
        if decision.task_id != task_id:
            raise BridgeError(
                "INVALID_INPUT", "review.task_id does not match the task argument", task_id=task_id
            )
        content_digest = sha256_digest(decision.model_dump(mode="json"))
        replay = self._review_replay(task_id, decision.idempotency_key, content_digest)
        if replay is not None:
            return replay
        task = self.store.get_task(task_id)
        spec = self._spec(task)
        if task.state != S.AWAITING_REVIEW:
            raise BridgeError(
                "STATE_CONFLICT",
                f"review requires state AWAITING_REVIEW, task is {task.state}",
                task_id=task_id,
                details={"actual_state": task.state.value},
            )
        assert task.current_attempt_id is not None
        attempt = self.store.get_attempt(task.current_attempt_id)
        stale = []
        if decision.attempt_id != attempt.attempt_id:
            stale.append(f"attempt_id {decision.attempt_id} is not the current attempt")
        if decision.task_version != task.task_version:
            stale.append(f"task_version {decision.task_version} != {task.task_version}")
        if decision.snapshot_digest != attempt.fingerprint:
            stale.append("snapshot_digest does not match the current evidence snapshot")
        if stale:
            raise BridgeError(
                "STALE_REVIEW",
                "review does not bind to the current attempt/snapshot: " + "; ".join(stale),
                task_id=task_id,
                attempt_id=attempt.attempt_id,
                details={
                    "current_attempt_id": attempt.attempt_id,
                    "current_snapshot_digest": attempt.fingerprint,
                },
            )
        manifest = self._load_manifest(attempt)
        current_fp = self.current_fingerprint(task)
        if current_fp != attempt.fingerprint:
            raise BridgeError(
                "STALE_REVIEW",
                "candidate changed after evidence was produced; earlier verification and "
                "reviews no longer apply. Run `hbridge verify` and review the new snapshot.",
                task_id=task_id,
                attempt_id=attempt.attempt_id,
            )
        review_id = new_id("rev")
        receipt: dict[str, Any] = {
            "review_id": review_id,
            "task_id": task_id,
            "attempt_id": attempt.attempt_id,
            "verdict": decision.verdict,
            "snapshot_digest": attempt.fingerprint,
            "reviewer_label": decision.reviewer_label,
            "reviewer_label_note": "declarative metadata, not authenticated",
        }
        findings = [f.model_dump(mode="json") for f in decision.findings]
        row = {
            "review_id": review_id,
            "task_id": task_id,
            "idempotency_key": decision.idempotency_key,
            "content_digest": content_digest,
            "attempt_id": attempt.attempt_id,
            "verdict": decision.verdict,
        }
        try:
            if decision.verdict == "approve":
                blockers = self.gate_blockers(task, attempt, manifest, current_fp)
                if blockers:
                    receipt.update(
                        {
                            "status": "rejected",
                            "blockers": blockers,
                            "resulting_state": task.state.value,
                        }
                    )
                    with self._advisor_transaction(task_id) as cur:
                        self.store.insert_review(
                            cur, {**row, "status": "rejected", "receipt": receipt}
                        )
                        self.store.add_event(
                            cur,
                            task_id,
                            "review_rejected",
                            {"review_id": review_id, "blockers": blockers},
                            attempt_id=attempt.attempt_id,
                        )
                    raise self._gate_error(receipt)
                receipt.update({"status": "accepted", "resulting_state": S.SUCCEEDED.value})
                with self._advisor_transaction(task_id) as cur:
                    self.store.insert_review(cur, {**row, "status": "accepted", "receipt": receipt})
                    assert manifest is not None
                    retain_approval(cur, task, manifest, review_id)
                    self.store.transition(
                        cur,
                        task_id,
                        S.AWAITING_REVIEW,
                        S.SUCCEEDED,
                        reason="approved",
                        event_type="review_accepted",
                        attempt_id=attempt.attempt_id,
                        payload={"review_id": review_id},
                    )
            elif decision.verdict == "changes_requested":
                exhausted = (
                    task.repair_cycles_used >= spec.limits.max_repair_cycles
                    or task.attempts_used >= spec.limits.max_attempts
                )
                new_state = S.FAILED if exhausted else S.READY
                receipt.update({"status": "accepted", "resulting_state": new_state.value})
                if exhausted:
                    receipt["note"] = "repair budget exhausted; no further attempt will be made"
                with self._advisor_transaction(task_id) as cur:
                    self.store.insert_review(cur, {**row, "status": "accepted", "receipt": receipt})
                    self.store.transition(
                        cur,
                        task_id,
                        S.AWAITING_REVIEW,
                        new_state,
                        reason="repair_budget_exhausted" if exhausted else "changes_requested",
                        event_type="review_accepted",
                        attempt_id=attempt.attempt_id,
                        payload={"review_id": review_id, "findings": len(findings)},
                        pending_feedback=None if exhausted else findings,
                    )
            else:
                receipt.update({"status": "accepted", "resulting_state": S.BLOCKED.value})
                with self._advisor_transaction(task_id) as cur:
                    self.store.insert_review(cur, {**row, "status": "accepted", "receipt": receipt})
                    self.store.transition(
                        cur,
                        task_id,
                        S.AWAITING_REVIEW,
                        S.BLOCKED,
                        reason="supervisor_blocked",
                        details={"findings": findings},
                        event_type="review_accepted",
                        attempt_id=attempt.attempt_id,
                        payload={"review_id": review_id},
                    )
        except sqlite3.IntegrityError:
            raced = self._review_replay(task_id, decision.idempotency_key, content_digest)
            if raced is None:
                raise
            return raced
        return receipt

    def _review_replay(self, task_id: str, key: str, digest: str) -> dict[str, Any] | None:
        existing = self.store.find_review(task_id, key)
        if existing is None:
            return None
        if existing["content_digest"] != digest:
            raise BridgeError(
                "IDEMPOTENCY_CONFLICT",
                "review idempotency key already used with different content",
                task_id=task_id,
            )
        receipt = dict(existing["receipt"])
        receipt["duplicate"] = True
        if existing["status"] == "rejected":
            raise self._gate_error(receipt)
        return receipt

    @staticmethod
    def _gate_error(receipt: dict[str, Any]) -> BridgeError:
        return BridgeError(
            "APPROVAL_GATE_FAILED",
            "approve rejected: " + "; ".join(receipt.get("blockers", [])),
            task_id=receipt["task_id"],
            attempt_id=receipt["attempt_id"],
            details={"receipt": receipt},
        )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _evidence_level(kind: str, mode: str) -> str:
    if kind == "fake":
        return "offline-simulated"
    if mode == "mock":
        return "offline-stub-binary"
    return "live-executor"


def _attempt_brief(a: AttemptRecord) -> dict[str, Any]:
    process = a.process or {}
    return {
        "attempt_id": a.attempt_id,
        "seq": a.seq,
        "kind": a.kind,
        "executor_kind": a.executor_kind,
        "mode": a.mode,
        "evidence_level": a.evidence_level,
        "status": a.status,
        "outcome": a.outcome,
        "outcome_reason": a.outcome_reason,
        "exit_code": a.exit_code,
        "exit_confirmed": a.exit_confirmed,
        "duration_seconds": process.get("duration_seconds"),
        "requested_model": a.requested_model,
        "observed_model": a.observed_model,
        "session_id": a.session_id,
        "snapshot_digest": a.fingerprint,
        "usage": a.usage,
        "started_at": a.started_at,
        "ended_at": a.ended_at,
    }


def _artifact_names(manifest: dict[str, Any], verification: dict[str, Any]) -> list[str]:
    names = ["manifest", "diff", "stdout", "stderr"]
    for c in verification["checks"]:
        if c.get("stdout"):
            names += [f"check:{c['id']}:stdout", f"check:{c['id']}:stderr"]
    return names


def _next_actions(state: TaskState) -> list[str]:
    return {
        S.CREATED: ["hbridge recover TASK_ID  (prepares the workspace)"],
        S.READY: ["hbridge run TASK_ID --mode mock"],
        S.PREPARING: ["wait; hbridge cancel TASK_ID to stop; recover if preparation runner died"],
        S.STARTING: ["wait; if the runner died: hbridge recover TASK_ID"],
        S.RUNNING: ["wait; hbridge cancel TASK_ID to stop", "if the runner died: hbridge recover"],
        S.VERIFYING: ["wait; if the runner died: hbridge recover TASK_ID"],
        S.AWAITING_REVIEW: [
            "hbridge artifacts TASK_ID",
            "hbridge review TASK_ID --file review.json",
        ],
        S.BLOCKED: ["inspect state_details", "hbridge recover TASK_ID --resolve retry|fail"],
        S.INTERRUPTED: ["hbridge recover TASK_ID", "hbridge recover TASK_ID --resolve retry|fail"],
    }.get(state, [])
