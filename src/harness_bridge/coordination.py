"""Local goal ownership and dispatch guards. No model calls or scheduling.

Advisor bindings fence stale cooperating sessions; they are not authentication against
another process with the same local user's filesystem access. All writes use the store's
writer transaction, including the checks called by legacy task entrypoints.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from harness_bridge import __version__
from harness_bridge.errors import BridgeError
from harness_bridge.models import RepoSpec, canonical_json, sha256_digest
from harness_bridge.state import EXECUTING, TERMINAL, TaskState
from harness_bridge.store import Store, new_id
from harness_bridge.workspace import inspect_source_repo


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AdvisorSession(Contract):
    host: str = Field(min_length=1, max_length=100)
    native_session_ref: str | None = Field(default=None, min_length=1, max_length=500)


class AdvisorClaim(Contract):
    binding_id: str = Field(min_length=1, max_length=100)
    epoch: int = Field(ge=1)


class GoalSpec(Contract):
    schema_version: Literal["1.0"]
    objective: str = Field(min_length=1, max_length=20000)
    repo: RepoSpec
    advisor: AdvisorSession
    constraints: list[str] = Field(default_factory=list, max_length=100)
    acceptance: list[str] = Field(min_length=1, max_length=100)
    max_attempts: int = Field(default=3, ge=1, le=100)
    max_repairs: int = Field(default=1, ge=0, le=100)
    allowed_executors: list[Literal["fake", "claude-code"]] = Field(
        default=["fake"], min_length=1, max_length=2
    )

    @field_validator("acceptance", "constraints")
    @classmethod
    def nonempty_lines(cls, value: list[str]) -> list[str]:
        if any(not line.strip() or len(line) > 10000 for line in value):
            raise ValueError("entries must contain 1-10000 nonblank characters")
        return value


class TakeoverRequest(Contract):
    advisor: AdvisorSession
    expected_epoch: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class GoalControl(Contract):
    action: Literal["pause", "resume", "cancel", "fail"]
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


C = TypeVar("C", bound=Contract)


def parse_contract(cls: type[C], data: Any) -> C:
    try:
        return cls.model_validate(data)
    except ValidationError as exc:
        # Do not echo raw input: it may contain private session/context content.
        problems = [
            {"field": ".".join(map(str, e["loc"])), "type": e["type"]} for e in exc.errors()
        ]
        raise BridgeError(
            "INVALID_INPUT", f"invalid {cls.__name__}", details={"errors": problems}
        ) from None


def check_key(key: str) -> None:
    if not key or len(key) > 200 or not key.isprintable():
        raise BridgeError("INVALID_INPUT", "idempotency key must be 1-200 printable characters")


class Coordinator:
    def __init__(self, store: Store) -> None:
        self.store = store

    def _goal(self, cur: sqlite3.Cursor, goal_id: str) -> sqlite3.Row:
        row = cur.execute(
            "SELECT g.*, p.repo_identity, p.repo_path FROM goals g "
            "JOIN projects p USING(project_id) WHERE goal_id=?",
            (goal_id,),
        ).fetchone()
        if row is None:
            raise BridgeError("NOT_FOUND", "goal does not exist", details={"goal_id": goal_id})
        if sha256_digest(json.loads(row["spec_json"])) != row["request_digest"]:
            raise BridgeError("INTEGRITY_ERROR", "frozen GoalSpec no longer matches its digest")
        return cast(sqlite3.Row, row)

    def event(self, cur: sqlite3.Cursor, goal_id: str, epoch: int, kind: str, payload: Any) -> None:
        cur.execute(
            "INSERT INTO goal_events(goal_id,type,advisor_epoch,payload,created_at) "
            "VALUES (?,?,?,?,?)",
            (goal_id, kind, epoch, canonical_json(payload), self.store.clock()),
        )

    def create(self, data: Any, key: str) -> dict[str, Any]:
        check_key(key)
        spec: GoalSpec = parse_contract(GoalSpec, data)
        normalized = spec.model_dump(mode="json")
        digest = sha256_digest(normalized)
        # Replay does not inspect today's repo or silently issue a newer Advisor binding.
        with self.store.transaction() as cur:
            replay = self._create_replay(cur, key, digest)
            if replay is not None:
                return replay
        src = inspect_source_repo(spec.repo.path, spec.repo.base_ref)
        with self.store.transaction() as cur:
            replay = self._create_replay(cur, key, digest)
            if replay is not None:
                return replay
            project = cur.execute(
                "SELECT project_id FROM projects WHERE repo_identity=?", (src.identity,)
            ).fetchone()
            project_id = project["project_id"] if project else new_id("prj")
            if project is None:
                cur.execute(
                    "INSERT INTO projects VALUES (?,?,?,?)",
                    (
                        project_id,
                        src.identity,
                        str(Path(src.path).resolve()),
                        self.store.clock(),
                    ),
                )
            goal_id, binding_id = new_id("goal"), new_id("adv")
            receipt = {
                "goal_id": goal_id,
                "project_id": project_id,
                "base_sha": src.base_sha,
                "advisor_claim": {"binding_id": binding_id, "epoch": 1},
            }
            cur.execute(
                "INSERT INTO goals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    goal_id,
                    project_id,
                    key,
                    digest,
                    canonical_json(normalized),
                    src.base_sha,
                    binding_id,
                    1,
                    canonical_json(normalized["advisor"]),
                    canonical_json(receipt),
                    self.store.clock(),
                ),
            )
            self.event(
                cur,
                goal_id,
                1,
                "goal_created",
                {"binding_id": binding_id, "base_sha": src.base_sha},
            )
            return {**receipt, "created": True}

    @staticmethod
    def _create_replay(cur: sqlite3.Cursor, key: str, digest: str) -> dict[str, Any] | None:
        row = cur.execute("SELECT * FROM goals WHERE idempotency_key=?", (key,)).fetchone()
        if row is None:
            return None
        if row["request_digest"] != digest:
            raise BridgeError("IDEMPOTENCY_CONFLICT", "key already used for another goal request")
        return {**json.loads(row["create_receipt"]), "created": False}

    def takeover(self, goal_id: str, data: Any, key: str) -> dict[str, Any]:
        check_key(key)
        request: TakeoverRequest = parse_contract(TakeoverRequest, data)
        normalized = request.model_dump(mode="json")
        digest = sha256_digest(normalized)
        with self.store.transaction() as cur:
            goal = self._goal(cur, goal_id)
            replay = cur.execute(
                "SELECT * FROM advisor_takeovers WHERE goal_id=? AND idempotency_key=?",
                (goal_id, key),
            ).fetchone()
            if replay:
                if replay["request_digest"] != digest:
                    raise BridgeError(
                        "IDEMPOTENCY_CONFLICT", "key already used for another takeover"
                    )
                return {**json.loads(replay["receipt_json"]), "replayed": True}
            if goal["advisor_epoch"] != request.expected_epoch:
                raise BridgeError(
                    "STALE_ADVISOR", "Advisor changed; inspect the goal before taking over"
                )
            binding_id, epoch = new_id("adv"), request.expected_epoch + 1
            receipt = {
                "goal_id": goal_id,
                "advisor_claim": {"binding_id": binding_id, "epoch": epoch},
            }
            cur.execute(
                "UPDATE goals SET binding_id=?, advisor_epoch=?, advisor_json=? WHERE goal_id=?",
                (binding_id, epoch, canonical_json(normalized["advisor"]), goal_id),
            )
            cur.execute(
                "INSERT INTO advisor_takeovers VALUES (?,?,?,?)",
                (
                    goal_id,
                    key,
                    digest,
                    canonical_json(receipt),
                ),
            )
            self.event(
                cur,
                goal_id,
                epoch,
                "advisor_taken_over",
                {
                    "previous_binding_id": goal["binding_id"],
                    "binding_id": binding_id,
                    "advisor": normalized["advisor"],
                    "reason": request.reason,
                },
            )
            return {**receipt, "replayed": False}

    def guard_goal(
        self,
        cur: sqlite3.Cursor,
        goal_id: str,
        claim: AdvisorClaim | None,
        *,
        allow_stopping: bool = False,
    ) -> sqlite3.Row:
        goal = self._goal(cur, goal_id)
        if claim is None:
            raise BridgeError(
                "ADVISOR_REQUIRED", "goal mutations require the active Advisor binding and epoch"
            )
        if claim.binding_id != goal["binding_id"] or claim.epoch != goal["advisor_epoch"]:
            raise BridgeError(
                "STALE_ADVISOR", "Advisor binding is stale or belongs to another goal"
            )
        if not allow_stopping and self.controls(cur, goal_id)["termination"]:
            raise BridgeError("STATE_CONFLICT", "goal termination has been requested")
        return goal

    @staticmethod
    def controls(cur: sqlite3.Cursor, goal_id: str) -> dict[str, Any]:
        row = cur.execute("SELECT * FROM goal_controls WHERE goal_id=?", (goal_id,)).fetchone()
        return dict(row) if row else {"paused": 0, "termination": None, "reason": None}

    def control(
        self, goal_id: str, data: Any, key: str, claim: AdvisorClaim | None
    ) -> dict[str, Any]:
        check_key(key)
        request = parse_contract(GoalControl, data)
        digest = sha256_digest(request.model_dump(mode="json"))
        with self.store.transaction() as cur:
            # Emergency goal cancellation must remain available after Advisor loss.
            goal = (
                self._goal(cur, goal_id)
                if request.action == "cancel"
                else self.guard_goal(cur, goal_id, claim, allow_stopping=True)
            )
            replay = cur.execute(
                "SELECT * FROM goal_control_requests WHERE goal_id=? AND idempotency_key=?",
                (goal_id, key),
            ).fetchone()
            if replay:
                if replay["request_digest"] != digest:
                    raise BridgeError(
                        "IDEMPOTENCY_CONFLICT", "key already used for another control request"
                    )
                return {**json.loads(replay["receipt_json"]), "replayed": True}
            before = self.controls(cur, goal_id)
            if before["termination"]:
                raise BridgeError(
                    "STATE_CONFLICT", "goal termination cannot be reversed or replaced"
                )
            termination = request.action if request.action in ("cancel", "fail") else None
            paused = request.action != "resume"
            cur.execute(
                "INSERT INTO goal_controls VALUES (?,?,?,?) ON CONFLICT(goal_id) DO UPDATE SET "
                "paused=excluded.paused, termination=excluded.termination, reason=excluded.reason",
                (goal_id, int(paused), termination, request.reason),
            )
            if termination:
                for row in cur.execute(
                    "SELECT task_id FROM goal_tasks WHERE goal_id=?", (goal_id,)
                ).fetchall():
                    task = self.store.get_task(row["task_id"], cur=cur)
                    if task.state in TERMINAL:
                        continue
                    self.store.update_task(cur, task.task_id, cancel_requested=1)
                    unknown = task.state == TaskState.INTERRUPTED and not (
                        task.state_details or {}
                    ).get("outcome_known")
                    if task.state in EXECUTING or unknown:
                        self.store.add_event(
                            cur, task.task_id, "cancel_requested", {"goal_id": goal_id}
                        )
                    else:
                        self.store.transition(
                            cur,
                            task.task_id,
                            task.state,
                            TaskState.CANCELLED,
                            reason="goal_termination_requested",
                            payload={"goal_id": goal_id},
                        )
            receipt = {
                "goal_id": goal_id,
                "action": request.action,
                "paused": paused,
                "termination_requested": termination,
                "advisor_epoch": goal["advisor_epoch"],
            }
            cur.execute(
                "INSERT INTO goal_control_requests VALUES (?,?,?,?)",
                (goal_id, key, digest, canonical_json(receipt)),
            )
            self.event(
                cur,
                goal_id,
                goal["advisor_epoch"],
                "goal_control_requested",
                {
                    **receipt,
                    "reason": request.reason,
                    "actor": "local_emergency" if request.action == "cancel" else "active_advisor",
                },
            )
            return {**receipt, "replayed": False}

    @staticmethod
    def task_goal(cur: sqlite3.Cursor, task_id: str) -> str | None:
        row = cur.execute("SELECT goal_id FROM goal_tasks WHERE task_id=?", (task_id,)).fetchone()
        return str(row["goal_id"]) if row else None

    def guard_task(
        self,
        cur: sqlite3.Cursor,
        task_id: str,
        claim: AdvisorClaim | None,
        *,
        allow_stopping: bool = False,
    ) -> sqlite3.Row | None:
        goal_id = self.task_goal(cur, task_id)
        return (
            self.guard_goal(cur, goal_id, claim, allow_stopping=allow_stopping) if goal_id else None
        )

    def link_task(
        self,
        cur: sqlite3.Cursor,
        goal_id: str,
        claim: AdvisorClaim | None,
        values: dict[str, Any],
        executor: str,
    ) -> None:
        goal = self.guard_goal(cur, goal_id, claim)
        spec: GoalSpec = parse_contract(GoalSpec, json.loads(goal["spec_json"]))
        if (
            values["repo_identity"] != goal["repo_identity"]
            or values["base_sha"] != goal["base_sha"]
        ):
            raise BridgeError(
                "INVALID_INPUT", "child must use the goal's repository and pinned base SHA"
            )
        if executor not in spec.allowed_executors:
            raise BridgeError("INVALID_INPUT", "executor is outside this goal's allowed set")
        cur.execute("INSERT INTO goal_tasks VALUES (?,?)", (values["task_id"], goal_id))
        self.event(
            cur, goal_id, goal["advisor_epoch"], "child_created", {"task_id": values["task_id"]}
        )

    @staticmethod
    def _budget(cur: sqlite3.Cursor, goal_id: str) -> dict[str, int]:
        row = cur.execute(
            "SELECT COUNT(*) AS attempts, COALESCE(SUM(a.kind='repair'),0) AS repairs "
            "FROM attempts a JOIN goal_tasks gt USING(task_id) WHERE gt.goal_id=? "
            "AND NOT (COALESCE(a.outcome,'')='spawn_failed' AND COALESCE(a.exit_confirmed,0)=1)",
            (goal_id,),
        ).fetchone()
        return {"attempts": row["attempts"], "repairs": row["repairs"]}

    def guard_dispatch(
        self, cur: sqlite3.Cursor, task_id: str, claim: AdvisorClaim | None, kind: str
    ) -> None:
        goal = self.guard_task(cur, task_id, claim)
        if goal is None:
            return
        if self.controls(cur, goal["goal_id"])["paused"]:
            raise BridgeError("STATE_CONFLICT", "goal dispatch is paused", task_id=task_id)
        spec: GoalSpec = parse_contract(GoalSpec, json.loads(goal["spec_json"]))
        budget = self._budget(cur, goal["goal_id"])
        if budget["attempts"] >= spec.max_attempts or (
            kind == "repair" and budget["repairs"] >= spec.max_repairs
        ):
            raise BridgeError(
                "BUDGET_EXHAUSTED", "goal attempt or repair budget exhausted", task_id=task_id
            )
        # Until managed workers/concurrency arrive, serialize across this project's goals.
        # Unknown exits remain occupied even after manual task cancellation/resolution.
        occupied = cur.execute(
            "SELECT DISTINCT t.task_id FROM tasks t JOIN goal_tasks gt USING(task_id) "
            "JOIN goals g USING(goal_id) LEFT JOIN attempts a USING(task_id) "
            "WHERE g.project_id=? AND (t.state IN ('STARTING','RUNNING','VERIFYING') "
            "OR (a.attempt_id IS NOT NULL AND COALESCE(a.exit_confirmed,0)<>1))",
            (goal["project_id"],),
        ).fetchall()
        if occupied:
            raise BridgeError(
                "STATE_CONFLICT",
                "project execution slot is occupied or exit is unknown",
                details={
                    "occupied_tasks": [r["task_id"] for r in occupied],
                },
            )
        self.event(
            cur,
            goal["goal_id"],
            goal["advisor_epoch"],
            "dispatch_reserved",
            {"task_id": task_id, "kind": kind},
        )

    def status(self, goal_id: str) -> dict[str, Any]:
        from harness_bridge.planning import ChildPlans

        with self.store.transaction() as cur:
            goal = self._goal(cur, goal_id)
            spec = json.loads(goal["spec_json"])
            children = [
                dict(r)
                for r in cur.execute(
                    "SELECT t.task_id,t.state,t.state_reason,t.current_attempt_id,t.worktree_path "
                    "FROM tasks t JOIN goal_tasks gt USING(task_id) WHERE gt.goal_id=? "
                    "ORDER BY t.created_at,t.task_id",
                    (goal_id,),
                )
            ]
            attention = any(
                c["state"] in ("AWAITING_REVIEW", "BLOCKED", "INTERRUPTED", "FAILED", "CANCELLED")
                for c in children
            )
            controls = self.controls(cur, goal_id)
            plans = ChildPlans(self).list_in_transaction(cur, goal_id)
            attention = attention or any(p["state"] == "WAITING_BASELINE" for p in plans)
            state = (
                "DRAFT"
                if not children and not plans
                else "NEEDS_ATTENTION"
                if attention
                else "ACTIVE"
            )
            pending_stop = []
            if controls["termination"]:
                pending_stop = [
                    r[0]
                    for r in cur.execute(
                        "SELECT DISTINCT t.task_id FROM tasks t JOIN goal_tasks gt USING(task_id) "
                        "LEFT JOIN attempts a USING(task_id) WHERE gt.goal_id=? AND "
                        "(t.state NOT IN ('SUCCEEDED','FAILED','CANCELLED') OR "
                        "(a.attempt_id IS NOT NULL AND COALESCE(a.exit_confirmed,0)<>1))",
                        (goal_id,),
                    )
                ]
                state = (
                    "NEEDS_ATTENTION"
                    if pending_stop
                    else "CANCELLED"
                    if controls["termination"] == "cancel"
                    else "FAILED"
                )
            events = [
                {**dict(r), "payload": json.loads(r["payload"])}
                for r in cur.execute(
                    "SELECT seq,type,advisor_epoch,payload,created_at FROM goal_events "
                    "WHERE goal_id=? "
                    "ORDER BY seq DESC LIMIT 50",
                    (goal_id,),
                )
            ]
            return {
                "goal_id": goal_id,
                "project_id": goal["project_id"],
                "objective": spec["objective"],
                "state": state,
                "dispatch_paused": bool(controls["paused"]),
                "termination_requested": controls["termination"],
                "pending_stop_tasks": pending_stop,
                "delivery": "not_implemented",
                "base_sha": goal["base_sha"],
                "repo_path": goal["repo_path"],
                "advisor": json.loads(goal["advisor_json"]),
                "advisor_claim": {"binding_id": goal["binding_id"], "epoch": goal["advisor_epoch"]},
                "budget": {
                    **self._budget(cur, goal_id),
                    "max_attempts": spec["max_attempts"],
                    "max_repairs": spec["max_repairs"],
                },
                "children": children,
                "plans": plans,
                "recent_events": list(reversed(events)),
            }

    def projects(self) -> dict[str, Any]:
        with self.store.transaction() as cur:
            projects = [
                dict(r)
                for r in cur.execute("SELECT * FROM projects ORDER BY created_at,project_id")
            ]
            for project in projects:
                project["goal_ids"] = [
                    r[0]
                    for r in cur.execute(
                        "SELECT goal_id FROM goals WHERE project_id=? ORDER BY created_at,goal_id",
                        (project["project_id"],),
                    )
                ]
        return {
            "runtime_version": __version__,
            "state_dir": str(self.store.db_path.parent),
            "projects": projects,
        }
