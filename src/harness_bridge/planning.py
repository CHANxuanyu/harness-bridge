"""Immutable child plans, validated DAGs and explicit materialization of independent roots.

Dependency results need preserved, approved baselines (P2); they are never silently mapped
to the original goal HEAD. Planning or querying does not touch a workspace or start a process.
"""

from __future__ import annotations

import json
import sqlite3
from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import Field, field_validator

from harness_bridge.coordination import AdvisorClaim, Contract, check_key, parse_contract
from harness_bridge.errors import BridgeError
from harness_bridge.models import TaskDefinition, canonical_json, sha256_digest
from harness_bridge.store import new_id

if TYPE_CHECKING:
    from harness_bridge.coordination import Coordinator


class ChildPlan(Contract):
    key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    task: TaskDefinition
    depends_on: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("depends_on")
    @classmethod
    def unique_dependencies(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate dependency")
        return value


class PlanBatch(Contract):
    schema_version: Literal["1.0"]
    children: list[ChildPlan] = Field(min_length=1, max_length=100)


class ChildPlans:
    def __init__(self, coordination: Coordinator) -> None:
        self.coordination = coordination
        self.store = coordination.store

    def get(self, cur: sqlite3.Cursor, child_id: str) -> sqlite3.Row:
        row = cur.execute("SELECT * FROM child_plans WHERE child_id=?", (child_id,)).fetchone()
        if row is None:
            raise BridgeError("NOT_FOUND", "child plan does not exist")
        if sha256_digest(json.loads(row["spec_json"])) != row["spec_digest"]:
            raise BridgeError("INTEGRITY_ERROR", "child plan no longer matches its digest")
        return cast(sqlite3.Row, row)

    def submit(
        self, goal_id: str, data: Any, key: str, claim: AdvisorClaim | None
    ) -> dict[str, Any]:
        check_key(key)
        batch = parse_contract(PlanBatch, data)
        digest = sha256_digest(batch.model_dump(mode="json"))
        with self.store.transaction() as cur:
            goal = self.coordination.guard_goal(cur, goal_id, claim)
            replay = cur.execute(
                "SELECT * FROM plan_batches WHERE goal_id=? AND idempotency_key=?", (goal_id, key)
            ).fetchone()
            if replay:
                if replay["request_digest"] != digest:
                    raise BridgeError(
                        "IDEMPOTENCY_CONFLICT", "key already used for another plan batch"
                    )
                return {**json.loads(replay["receipt_json"]), "replayed": True}
            existing = list(cur.execute("SELECT * FROM child_plans WHERE goal_id=?", (goal_id,)))
            ids = {r["child_key"]: r["child_id"] for r in existing}
            graph: dict[str, list[str]] = {
                r["child_key"]: json.loads(self.get(cur, r["child_id"])["spec_json"])["depends_on"]
                for r in existing
            }
            allowed = json.loads(goal["spec_json"])["allowed_executors"]
            for plan in batch.children:
                if plan.key in ids:
                    raise BridgeError("INVALID_INPUT", "child keys must be unique within a goal")
                if plan.task.executor.kind not in allowed:
                    raise BridgeError(
                        "INVALID_INPUT", "executor is outside this goal's allowed set"
                    )
                ids[plan.key] = new_id("child")
                graph[plan.key] = plan.depends_on
            if any(dep not in ids for deps in graph.values() for dep in deps):
                raise BridgeError(
                    "INVALID_INPUT", "every dependency must name a child in the same goal"
                )
            try:
                tuple(TopologicalSorter(graph).static_order())
            except CycleError:
                raise BridgeError(
                    "INVALID_INPUT", "child dependency graph contains a cycle"
                ) from None
            for plan in batch.children:
                normalized = plan.model_dump(mode="json")
                cur.execute(
                    "INSERT INTO child_plans VALUES (?,?,?,?,?,?,?)",
                    (
                        ids[plan.key],
                        goal_id,
                        plan.key,
                        canonical_json(normalized),
                        sha256_digest(normalized),
                        None,
                        self.store.clock(),
                    ),
                )
            for plan in batch.children:
                for dependency in plan.depends_on:
                    cur.execute(
                        "INSERT INTO child_dependencies VALUES (?,?)",
                        (ids[plan.key], ids[dependency]),
                    )
            receipt = {
                "goal_id": goal_id,
                "children": [{"child_id": ids[p.key], "key": p.key} for p in batch.children],
            }
            cur.execute(
                "INSERT INTO plan_batches VALUES (?,?,?,?)",
                (goal_id, key, digest, canonical_json(receipt)),
            )
            self.coordination.event(
                cur, goal_id, goal["advisor_epoch"], "children_planned", receipt
            )
            return {**receipt, "replayed": False}

    def view(self, cur: sqlite3.Cursor, child_id: str) -> dict[str, Any]:
        row = self.get(cur, child_id)
        spec = json.loads(row["spec_json"])
        dependencies = [
            dict(r)
            for r in cur.execute(
                "SELECT p.child_id,p.child_key AS key,p.task_id,t.state AS task_state "
                "FROM child_dependencies d JOIN child_plans p ON p.child_id=d.dependency_id "
                "LEFT JOIN tasks t ON t.task_id=p.task_id WHERE d.child_id=? ORDER BY p.child_key",
                (child_id,),
            )
        ]
        if {d["key"] for d in dependencies} != set(spec["depends_on"]):
            raise BridgeError("INTEGRITY_ERROR", "dependency links do not match the child plan")
        reasons: list[str] = []
        if row["task_id"]:
            state = self.store.get_task(row["task_id"], cur=cur).state.value
        elif self.coordination.controls(cur, row["goal_id"])["termination"]:
            state = "CANCELLED"
            reasons = ["goal_termination_requested"]
        elif any(d["task_state"] != "SUCCEEDED" for d in dependencies):
            state = "WAITING_DEPENDENCIES"
            reasons = ["dependencies_not_approved"]
        elif dependencies:
            state = "WAITING_BASELINE"
            reasons = ["approved_dependency_baseline_not_implemented"]
        else:
            state = "READY_TO_MATERIALIZE"
        return {
            "child_id": child_id,
            "goal_id": row["goal_id"],
            "key": row["child_key"],
            "task_id": row["task_id"],
            "state": state,
            "blocking_reasons": reasons,
            "dependencies": dependencies,
            "plan_digest": row["spec_digest"],
        }

    def list_in_transaction(self, cur: sqlite3.Cursor, goal_id: str) -> list[dict[str, Any]]:
        rows = cur.execute(
            "SELECT child_id FROM child_plans WHERE goal_id=? ORDER BY created_at,child_id",
            (goal_id,),
        ).fetchall()
        return [self.view(cur, row["child_id"]) for row in rows]

    def status(self, child_id: str) -> dict[str, Any]:
        with self.store.transaction() as cur:
            return self.view(cur, child_id)

    def materialization_spec(
        self, cur: sqlite3.Cursor, child_id: str, claim: AdvisorClaim | None
    ) -> dict[str, Any]:
        row = self.get(cur, child_id)
        goal = self.coordination.guard_goal(cur, row["goal_id"], claim)
        view = self.view(cur, child_id)
        if row["task_id"] is None and view["state"] != "READY_TO_MATERIALIZE":
            raise BridgeError(
                "STATE_CONFLICT",
                "child dependencies require a fixed approved baseline",
                details=view,
            )
        task = json.loads(row["spec_json"])["task"]
        repo = {**json.loads(goal["spec_json"])["repo"], "base_ref": goal["base_sha"]}
        return {**task, "schema_version": "1.0", "repo": repo}

    def attach(
        self,
        cur: sqlite3.Cursor,
        child_id: str,
        claim: AdvisorClaim | None,
        task_id: str,
        spec: dict[str, Any],
    ) -> None:
        expected = self.materialization_spec(cur, child_id, claim)
        if expected != spec:
            raise BridgeError(
                "INTEGRITY_ERROR", "materialized TaskSpec differs from the child plan"
            )
        cur.execute(
            "UPDATE child_plans SET task_id=? WHERE child_id=? AND task_id IS NULL",
            (task_id, child_id),
        )
        if cur.rowcount != 1:
            raise BridgeError("STATE_CONFLICT", "child is already materialized")
        goal_id = self.get(cur, child_id)["goal_id"]
        goal = self.coordination.guard_goal(cur, goal_id, claim)
        self.coordination.event(
            cur,
            goal_id,
            goal["advisor_epoch"],
            "child_materialized",
            {"child_id": child_id, "task_id": task_id},
        )
