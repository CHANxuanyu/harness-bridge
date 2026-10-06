"""Bind budgeted repair children to immutable integration provenance.

The original approvals remain required inputs. An approved repair explicitly resolves a
prefix of those inputs; composition never re-merges that conflicting prefix over the fix.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from harness_bridge.baselines import pin, validate_pin
from harness_bridge.coordination import GoalSpec, parse_contract
from harness_bridge.dispatch import budget_usage, integration_holds, occupied_tasks
from harness_bridge.errors import BridgeError
from harness_bridge.models import sha256_digest
from harness_bridge.planning import ChildPlan

if TYPE_CHECKING:
    from harness_bridge.service import Bridge


def provenance(record: dict[str, Any]) -> dict[str, Any]:
    return {
        k: record[k]
        for k in (
            "integration_id",
            "goal_id",
            "goal_digest",
            "request_digest",
            "repo_path",
            "repo_identity",
            "base_sha",
            "inputs",
            "membership",
            "result",
            "verification",
            "verifier_digest",
        )
    }


class IntegrationRepairs:
    def __init__(self, bridge: Bridge) -> None:
        self.b = bridge

    def baseline(
        self, cur: sqlite3.Cursor, goal: sqlite3.Row, child_id: str, plan: ChildPlan
    ) -> dict[str, Any]:
        assert plan.integration_repair is not None
        request = plan.integration_repair.model_dump(mode="json")
        original = self.b.integrations.get(cur, request["integration_id"])
        latest = cur.execute(
            "SELECT integration_id FROM integrations WHERE goal_id=? ORDER BY rowid DESC LIMIT 1",
            (goal["goal_id"],),
        ).fetchone()
        if (
            original["goal_id"] != goal["goal_id"]
            or not latest
            or latest[0] != request["integration_id"]
        ):
            raise BridgeError(
                "STATE_CONFLICT", "repair must bind the latest integration of this goal"
            )
        self.b.integrations._validate(cur, original)
        if occupied_tasks(cur, goal["project_id"]) or integration_holds(cur, goal["project_id"]):
            raise BridgeError(
                "STATE_CONFLICT", "repair planning requires an idle project with known exits"
            )
        run = self.b.integration_checks.latest(cur, original["integration_id"])
        if original["result"] is None or not (
            original["phase"] in ("CONFLICT", "CHANGES_REQUESTED", "BLOCKED")
            or (run and run["status"] not in ("running", "passed") and run["exit_confirmed"])
        ):
            raise BridgeError(
                "STATE_CONFLICT", "repair requires a conflict, failed check or requested changes"
            )
        spec = parse_contract(GoalSpec, json.loads(goal["spec_json"]))
        usage = budget_usage(cur, goal["goal_id"])
        limits = plan.task.limits
        if (
            usage.attempts >= spec.max_attempts
            or usage.repairs >= spec.max_repairs
            or (
                spec.max_executor_wall_seconds is not None
                and usage.wall_seconds + Decimal(str(limits.wall_timeout_seconds))
                > Decimal(str(spec.max_executor_wall_seconds))
            )
            or (
                spec.max_executor_turns is not None
                and usage.turns + limits.max_turns_per_attempt > spec.max_executor_turns
            )
        ):
            raise BridgeError(
                "BUDGET_EXHAUSTED", "integration repair exceeds the remaining goal budget"
            )
        result = original["result"]
        ref = f"refs/hbridge/baselines/{child_id}"
        pin(goal["repo_path"], ref, result["commit_sha"])
        return {
            "child_id": child_id,
            "goal_id": goal["goal_id"],
            "plan_digest": sha256_digest(plan.normalized()),
            "goal_base_sha": goal["base_sha"],
            "inputs": original["inputs"],
            "status": "ready",
            "ref": ref,
            "commit_sha": result["commit_sha"],
            "tree_sha": result["tree_sha"],
            "integration_repair": {
                "request": request,
                "source": provenance(original),
                "pending_inputs": [
                    i for i in original["inputs"] if i["task_id"] not in result["applied_task_ids"]
                ],
                "verification_run": run,
                "review": self.b.integration_checks.summary(cur, original)["review"],
            },
        }

    def context(self, cur: sqlite3.Cursor, child_id: str) -> dict[str, Any] | None:
        row = self.b.plans.get(cur, child_id)
        request = json.loads(row["spec_json"]).get("integration_repair")
        if not request:
            return None
        baseline = self.b.plans.baseline(cur, child_id)
        assert baseline is not None
        binding = baseline["integration_repair"]
        source = self.b.integrations.get(cur, request["integration_id"])
        if (
            provenance(source) != binding["source"]
            or source["goal_id"] != row["goal_id"]
            or baseline["inputs"] != source["inputs"]
            or baseline["commit_sha"] != source["result"]["commit_sha"]
            or baseline["tree_sha"] != source["result"]["tree_sha"]
        ):
            raise BridgeError("INTEGRITY_ERROR", "integration repair provenance changed")
        validate_pin(source["repo_path"], baseline)
        validate_pin(source["repo_path"], source["result"])
        for item in source["inputs"]:
            validate_pin(source["repo_path"], item)
        return dict(binding)

    def resolution(
        self,
        cur: sqlite3.Cursor,
        goal: sqlite3.Row,
        child_id: str | None,
        inputs: list[dict[str, Any]],
        membership: list[dict[str, Any]],
        verification: list[Any],
    ) -> dict[str, Any] | None:
        repair_members = [
            m
            for m in membership
            if json.loads(self.b.plans.get(cur, m["child_id"])["spec_json"]).get(
                "integration_repair"
            )
        ]
        if child_id is None:
            if repair_members:
                raise BridgeError(
                    "INVALID_INPUT", "select repair_child_id to retain the explicit resolution"
                )
            return None
        child = self.b.plans.get(cur, child_id)
        binding = self.context(cur, child_id)
        if child["goal_id"] != goal["goal_id"] or binding is None or child["task_id"] is None:
            raise BridgeError(
                "INVALID_INPUT", "resolution must name an approved repair child in this goal"
            )
        position = next((n for n, i in enumerate(inputs) if i["task_id"] == child["task_id"]), -1)
        source = binding["source"]
        expected_members = [
            m for m in membership if m["task_id"] in {i["task_id"] for i in source["inputs"]}
        ]
        if (
            position < 0
            or inputs[:position] != source["inputs"]
            or expected_members != source["membership"]
            or verification != source["verification"]
            or any(
                m["task_id"] not in {i["task_id"] for i in inputs[: position + 1]}
                for m in repair_members
            )
        ):
            raise BridgeError(
                "STATE_CONFLICT",
                "repair must resolve its exact input prefix and preserve total checks",
            )
        return {
            "child_id": child_id,
            "task_id": child["task_id"],
            "position": position,
            "source_integration_id": source["integration_id"],
            "binding_digest": sha256_digest(binding),
        }
