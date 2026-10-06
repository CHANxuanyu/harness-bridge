"""Transactional dispatch accounting and conservative proof of disjoint write scopes.

Attempts are the durable reservation ledger; their immutable TaskSpecs supply the requested
ceilings. We do not refund unused time/turns from self-reported usage or turn counts. Only a
confirmed non-start is excluded, using the same rule as the existing attempt/repair budgets.
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from harness_bridge.baselines import read_record
from harness_bridge.errors import BridgeError
from harness_bridge.models import TaskSpec, parse_task_spec, sha256_digest


def frozen_spec(row: sqlite3.Row) -> TaskSpec:
    data = json.loads(row["spec_json"])
    if sha256_digest(data) != row["spec_digest"]:
        raise BridgeError("INTEGRITY_ERROR", "reserved task spec no longer matches its digest")
    return parse_task_spec(data)


@dataclass(frozen=True)
class BudgetUsage:
    attempts: int = 0
    repairs: int = 0
    wall_seconds: Decimal = Decimal(0)
    turns: int = 0

    def to_dict(self) -> dict[str, int | float]:
        return {
            "attempts": self.attempts,
            "repairs": self.repairs,
            "reserved_wall_seconds": float(self.wall_seconds),
            "reserved_turns": self.turns,
        }


def budget_usage(cur: sqlite3.Cursor, goal_id: str) -> BudgetUsage:
    rows = cur.execute(
        "SELECT a.kind,t.task_id,t.spec_json,t.spec_digest FROM attempts a "
        "JOIN tasks t USING(task_id) JOIN goal_tasks gt USING(task_id) WHERE gt.goal_id=? "
        "AND NOT (COALESCE(a.outcome,'')='spawn_failed' AND COALESCE(a.exit_confirmed,0)=1)",
        (goal_id,),
    ).fetchall()
    specs: dict[str, TaskSpec] = {}
    wall = Decimal(0)
    turns = repairs = 0
    for row in rows:
        if row["task_id"] not in specs:
            specs[row["task_id"]] = frozen_spec(row)
        limits = specs[row["task_id"]].limits
        wall += Decimal(str(limits.wall_timeout_seconds))
        turns += limits.max_turns_per_attempt
        repairs += row["kind"] == "repair"
    return BudgetUsage(len(rows), repairs, wall, turns)


def literal_root(pattern: str) -> tuple[str, ...]:
    # Ignore exclusions: proving a set difference empty requires stronger glob analysis.
    # Stop before the first wildcard component. Empty prefix conservatively covers the repo.
    root = []
    for segment in pattern.split("/"):
        if "*" in segment or "?" in segment:
            break
        # Treat case/Unicode spelling aliases as overlapping, including on macOS volumes.
        root.append(unicodedata.normalize("NFC", segment).casefold())
    return tuple(root)


def scopes_overlap(left: list[str], right: list[str]) -> bool:
    a_roots = {literal_root(pattern) for pattern in left}
    b_roots = {literal_root(pattern) for pattern in right}
    return any(a[: len(b)] == b or b[: len(a)] == a for a in a_roots for b in b_roots)


def occupied_tasks(cur: sqlite3.Cursor, project_id: str) -> list[sqlite3.Row]:
    # Avoid join multiplication while retaining *every* unresolved historical execution.
    # A task cannot use a spare slot to retry on its own unresolved worktree.
    return cur.execute(
        "SELECT t.*, MAX(1,(SELECT COUNT(*) FROM attempts a WHERE a.task_id=t.task_id "
        "AND COALESCE(a.exit_confirmed,0)<>1) + (SELECT COUNT(*) FROM preparation_runs p "
        "WHERE p.task_id=t.task_id AND COALESCE(p.exit_confirmed,0)<>1)) AS slots_held, "
        "(t.state='PREPARING' OR EXISTS (SELECT 1 FROM preparation_runs p "
        "WHERE p.task_id=t.task_id AND COALESCE(p.exit_confirmed,0)<>1)) AS preparation_held "
        "FROM tasks t JOIN goal_tasks gt USING(task_id) JOIN goals g USING(goal_id) "
        "WHERE g.project_id=? AND (t.state IN ('PREPARING','STARTING','RUNNING','VERIFYING') "
        "OR EXISTS (SELECT 1 FROM attempts a WHERE a.task_id=t.task_id "
        "AND COALESCE(a.exit_confirmed,0)<>1) OR EXISTS (SELECT 1 FROM preparation_runs p "
        "WHERE p.task_id=t.task_id AND COALESCE(p.exit_confirmed,0)<>1)) "
        "ORDER BY t.created_at,t.task_id",
        (project_id,),
    ).fetchall()


def integration_holds(cur: sqlite3.Cursor, project_id: str) -> list[dict[str, Any]]:
    rows = cur.execute(
        "SELECT v.* FROM integration_verifications v JOIN integrations i USING(integration_id) "
        "JOIN goals g USING(goal_id) WHERE g.project_id=? "
        "AND (v.status='running' OR COALESCE(v.exit_confirmed,0)<>1)",
        (project_id,),
    ).fetchall()
    holds = []
    for row in rows:
        record = read_record(row)
        if (
            record is None
            or record["status"] != row["status"]
            or record["exit_confirmed"] != row["exit_confirmed"]
        ):
            raise BridgeError("INTEGRITY_ERROR", "integration process reservation changed")
        holds.append(record)
    return holds


def guard_integration_hold(cur: sqlite3.Cursor, project_id: str) -> None:
    holds = integration_holds(cur, project_id)
    if holds:
        raise BridgeError(
            "STATE_CONFLICT",
            "integration verification holds the project exclusively",
            details={
                "reason": "integration_verification_exclusive",
                "run_ids": [r["run_id"] for r in holds],
            },
        )


def guard_slot(
    cur: sqlite3.Cursor,
    project_id: str,
    task_id: str,
    max_parallel: int,
    *,
    preparation: bool = False,
) -> None:
    guard_integration_hold(cur, project_id)
    active = occupied_tasks(cur, project_id)
    reason = None
    conflicts: list[str] = []
    if any(r["task_id"] == task_id for r in active):
        reason = "task_already_occupied"
    elif sum(r["slots_held"] for r in active) >= max_parallel:
        reason = "project_capacity"
    elif active and (preparation or any(r["preparation_held"] for r in active)):
        # Setup may run arbitrary trusted commands; its effect scope is not allowed_paths.
        reason = "preparation_requires_exclusive_project"
    elif active:
        candidate = cur.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        assert candidate is not None
        scope = frozen_spec(candidate).allowed_paths
        conflicts = [
            r["task_id"] for r in active if scopes_overlap(scope, frozen_spec(r).allowed_paths)
        ]
        if conflicts:
            reason = "write_scopes_may_overlap"
    if reason:
        raise BridgeError(
            "STATE_CONFLICT",
            "project execution reservation refused",
            task_id=task_id,
            details={
                "reason": reason,
                "max_parallel": max_parallel,
                "occupied_tasks": [r["task_id"] for r in active],
                "occupied_slots": sum(r["slots_held"] for r in active),
                "conflicting_tasks": conflicts,
            },
        )


def slot_status(cur: sqlite3.Cursor, project_id: str, max_parallel: int) -> dict[str, Any]:
    holds = integration_holds(cur, project_id)
    active = occupied_tasks(cur, project_id)
    return {
        "max_parallel": max_parallel,
        "occupied_tasks": [r["task_id"] for r in active],
        "occupied_slots": sum(r["slots_held"] for r in active) + len(holds),
        "integration_runs": [r["run_id"] for r in holds],
        "integration_exclusive": bool(holds),
        "slots_by_task": {r["task_id"]: r["slots_held"] for r in active},
        "preparation_exclusive": any(r["preparation_held"] for r in active),
        "scope_policy": "disjoint_literal_roots",
    }
