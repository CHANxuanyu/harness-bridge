"""Frozen integration inputs and owned candidate workspaces, without model execution.

Freeze commits before materialization. Git operations run under one SQLite writer lock, but
are not atomic with SQLite: exact private pins and unchanged owned worktrees are adopted on
retry. Conflicts retain the last clean composition, never a fabricated successful candidate.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, field_validator, model_validator

from harness_bridge.baselines import (
    approved,
    commit_tree,
    merge_tree,
    pin,
    read_record,
    validate_pin,
)
from harness_bridge.coordination import Contract, check_key, parse_contract
from harness_bridge.dispatch import frozen_spec
from harness_bridge.errors import BridgeError
from harness_bridge.models import VerificationCommand, canonical_json, sha256_digest
from harness_bridge.store import new_id
from harness_bridge.workspace import (
    create_worktree,
    git,
    source_status,
    take_snapshot,
    verify_worktree,
)

if TYPE_CHECKING:
    from harness_bridge.service import Bridge


class IntegrationSpec(Contract):
    schema_version: Literal["1.0"]
    task_ids: list[str] = Field(min_length=1, max_length=100)
    verification: list[VerificationCommand] = Field(min_length=1, max_length=50)

    @field_validator("task_ids")
    @classmethod
    def unique_tasks(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values) or any(not v or len(v) > 128 for v in values):
            raise ValueError("task IDs must be nonempty and unique")
        return values

    @model_validator(mode="after")
    def checks(self) -> IntegrationSpec:
        ids = [c.id for c in self.verification]
        if len(set(ids)) != len(ids) or not any(c.required for c in self.verification):
            raise ValueError("verification IDs must be unique with at least one required check")
        return self


class Integrations:
    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge
        self.store = bridge.store

    def get(self, cur: sqlite3.Cursor, integration_id: str) -> dict[str, Any]:
        row = cur.execute(
            "SELECT * FROM integrations WHERE integration_id=?", (integration_id,)
        ).fetchone()
        if row is None:
            raise BridgeError("NOT_FOUND", "integration does not exist")
        record = read_record(row)
        assert record is not None
        spec = json.loads(row["spec_json"])
        if (
            sha256_digest(spec) != row["request_digest"]
            or record["integration_id"] != integration_id
            or record["goal_id"] != row["goal_id"]
            or record["request_digest"] != row["request_digest"]
            or [i["task_id"] for i in record["inputs"]] != spec["task_ids"]
            or record["verification"] != spec["verification"]
            or record["verifier_digest"] != sha256_digest(spec["verification"])
        ):
            raise BridgeError("INTEGRITY_ERROR", "integration request/record binding changed")
        return record

    def _inputs(
        self, cur: sqlite3.Cursor, goal: sqlite3.Row, task_ids: list[str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        # V1's first slice treats every planned/linked child as required; no implicit omissions.
        plans = self.bridge.plans.list_in_transaction(cur, goal["goal_id"])
        if any(p["task_id"] is None for p in plans):
            raise BridgeError("STATE_CONFLICT", "all required child plans must be materialized")
        rows = cur.execute(
            "SELECT t.* FROM tasks t JOIN goal_tasks gt USING(task_id) WHERE gt.goal_id=?",
            (goal["goal_id"],),
        ).fetchall()
        tasks = {r["task_id"]: r for r in rows}
        if set(task_ids) != set(tasks):
            raise BridgeError(
                "STATE_CONFLICT", "integration must include every goal task exactly once"
            )
        if any(r["state"] != "SUCCEEDED" for r in rows):
            raise BridgeError("STATE_CONFLICT", "all required tasks must have accepted approval")
        for query in (
            "SELECT 1 FROM attempts r JOIN goal_tasks gt USING(task_id) "
            "WHERE gt.goal_id=? AND COALESCE(r.exit_confirmed,0)<>1 LIMIT 1",
            "SELECT 1 FROM preparation_runs r JOIN goal_tasks gt USING(task_id) "
            "WHERE gt.goal_id=? AND COALESCE(r.exit_confirmed,0)<>1 LIMIT 1",
        ):
            if cur.execute(
                query,
                (goal["goal_id"],),
            ).fetchone():
                raise BridgeError(
                    "STATE_CONFLICT", "integration requires confirmed execution exits"
                )
        positions = {task_id: n for n, task_id in enumerate(task_ids)}
        membership = []
        for plan in plans:
            row = self.bridge.plans.get(cur, plan["child_id"])
            membership.append(
                {
                    "child_id": row["child_id"],
                    "task_id": row["task_id"],
                    "digest": row["spec_digest"],
                }
            )
            if any(
                positions[d["task_id"]] >= positions[row["task_id"]] for d in plan["dependencies"]
            ):
                raise BridgeError(
                    "INVALID_INPUT", "integration order must place dependencies first"
                )
        inputs = []
        for task_id in task_ids:
            frozen_spec(tasks[task_id])
            record = approved(cur, task_id)
            if record is None:
                raise BridgeError("STATE_CONFLICT", "retained approved snapshot required")
            validate_pin(goal["repo_path"], record)
            inputs.append({**record, "spec_digest": tasks[task_id]["spec_digest"]})
        return inputs, membership

    def _validate(self, cur: sqlite3.Cursor, record: dict[str, Any]) -> None:
        goal = self.bridge.coordination._goal(cur, record["goal_id"])
        if (
            goal["request_digest"] != record["goal_digest"]
            or goal["base_sha"] != record["base_sha"]
            or goal["repo_identity"] != record["repo_identity"]
            or goal["repo_path"] != record["repo_path"]
        ):
            raise BridgeError("INTEGRITY_ERROR", "integration goal binding changed")
        actual = (
            git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=goal["repo_path"])
            .stdout.decode()
            .strip()
        )
        if os.path.realpath(actual) != record["repo_identity"]:
            raise BridgeError("INTEGRITY_ERROR", "integration repository identity changed")
        inputs, membership = self._inputs(cur, goal, [i["task_id"] for i in record["inputs"]])
        if inputs != record["inputs"] or membership != record["membership"]:
            raise BridgeError(
                "STATE_CONFLICT", "integration inputs no longer match the frozen goal"
            )
        if record["result"] is not None:
            validate_pin(goal["repo_path"], record["result"])

    def freeze(self, goal_id: str, data: Any, key: str) -> dict[str, Any]:
        check_key(key)
        spec = parse_contract(IntegrationSpec, data).model_dump(mode="json")
        digest = sha256_digest(spec)
        with self.store.transaction() as cur:
            goal = self.bridge.coordination.guard_goal(cur, goal_id, self.bridge.advisor_claim)
            replay = cur.execute(
                "SELECT integration_id,request_digest FROM integrations "
                "WHERE goal_id=? AND idempotency_key=?",
                (goal_id, key),
            ).fetchone()
            if replay:
                if replay["request_digest"] != digest:
                    raise BridgeError("IDEMPOTENCY_CONFLICT", "integration key already used")
                return {**self.get(cur, replay["integration_id"]), "replayed": True}
            inputs, membership = self._inputs(cur, goal, spec["task_ids"])
            record = {
                "integration_id": new_id("integration"),
                "goal_id": goal_id,
                "goal_digest": goal["request_digest"],
                "request_digest": digest,
                "repo_path": goal["repo_path"],
                "repo_identity": goal["repo_identity"],
                "base_sha": goal["base_sha"],
                "inputs": inputs,
                "membership": membership,
                "verification": spec["verification"],
                "verifier_digest": sha256_digest(spec["verification"]),
                "phase": "FROZEN",
                "result": None,
                "workspace": None,
                "verification_status": "not_run",
                "delivery": "not_implemented",
            }
            cur.execute(
                "INSERT INTO integrations VALUES (?,?,?,?,?,?,?,?)",
                (
                    record["integration_id"],
                    goal_id,
                    key,
                    digest,
                    canonical_json(spec),
                    canonical_json(record),
                    sha256_digest(record),
                    self.store.clock(),
                ),
            )
            self.bridge.coordination.event(
                cur,
                goal_id,
                goal["advisor_epoch"],
                "integration_frozen",
                {"integration_id": record["integration_id"], "request_digest": digest},
            )
            return {**record, "replayed": False}

    def _compose(self, record: dict[str, Any]) -> dict[str, Any]:
        repo, integration_id = record["repo_path"], record["integration_id"]
        current = record["base_sha"]
        conflict = None
        completed = []
        for incoming in record["inputs"]:
            tree = merge_tree(repo, current, incoming["commit_sha"])
            if tree is None:
                conflict = incoming["task_id"]
                break
            current = commit_tree(
                repo,
                tree,
                [current, incoming["commit_sha"]],
                f"Harness Bridge integration {integration_id} {incoming['task_id']}",
            )
            completed.append(incoming["task_id"])
        tree = git(["rev-parse", f"{current}^{{tree}}"], cwd=repo).stdout.decode().strip()
        # Bind even identical trees to the complete immutable request and approved inputs.
        current = commit_tree(
            repo, tree, [current], f"Harness Bridge integration {sha256_digest(record)}"
        )
        ref = f"refs/hbridge/integrations/{integration_id}/{'partial' if conflict else 'candidate'}"
        pin(repo, ref, current)
        return {
            "commit_sha": current,
            "tree_sha": tree,
            "ref": ref,
            "applied_task_ids": completed,
            "conflict_task_id": conflict,
        }

    def _workspace_path(self, integration_id: str) -> Path:
        path = self.bridge.state_dir / "integrations" / integration_id
        if path.is_symlink() or path.parent.is_symlink():
            raise BridgeError("WORKSPACE_ERROR", "integration workspace must not be a symlink")
        return path

    def _workspace_check(self, record: dict[str, Any]) -> str:
        path = self._workspace_path(record["integration_id"])
        if not path.exists():
            return "missing"
        workspace, result = record["workspace"], record["result"]
        if workspace != {
            "path": str(path),
            "branch": f"hbridge/integration/{record['integration_id']}",
        }:
            raise BridgeError("INTEGRITY_ERROR", "integration workspace binding changed")
        if not verify_worktree(
            path, result["commit_sha"], workspace["branch"], record["repo_path"]
        ):
            return "foreign"
        top = git(["rev-parse", "--show-toplevel"], cwd=path).stdout.decode().strip()
        if os.path.realpath(top) != str(path.resolve()):
            return "foreign"
        head = git(["rev-parse", "HEAD"], cwd=path).stdout.decode().strip()
        if head != result["commit_sha"] or source_status(str(path)):
            return "changed"
        # An executor/user index can hide changes with assume-unchanged/skip-worktree.
        # The existing snapshotter uses a fresh index; never adopt based on status alone.
        with tempfile.TemporaryDirectory(prefix="hbridge-integration-") as scratch:
            tree = take_snapshot(path, result["commit_sha"], Path(scratch)).tree_sha
        return "unchanged" if tree == result["tree_sha"] else "changed"

    def materialize(self, integration_id: str) -> dict[str, Any]:
        with self.store.transaction() as cur:
            record = self.get(cur, integration_id)
            goal = self.bridge.coordination.guard_goal(
                cur, record["goal_id"], self.bridge.advisor_claim
            )
            self._validate(cur, record)
            if record["phase"] != "FROZEN":
                # An idempotent replay never overwrites or recreates an existing candidate.
                return {
                    **record,
                    "replayed": True,
                    "workspace_status": self._workspace_check(record)
                    if record["workspace"]
                    else None,
                }
            result = self._compose(record)
            record["result"] = result
            if result["conflict_task_id"]:
                record["phase"] = "CONFLICT"
            else:
                path = self._workspace_path(integration_id)
                branch = f"hbridge/integration/{integration_id}"
                record["workspace"] = {"path": str(path), "branch": branch}
                create_worktree(record["repo_path"], path, branch, result["commit_sha"])
                if self._workspace_check(record) != "unchanged":
                    raise BridgeError(
                        "WORKSPACE_ERROR",
                        "existing integration workspace changed; refusing adoption",
                    )
                record["phase"] = "CANDIDATE"
            cur.execute(
                "UPDATE integrations SET record_json=?,record_digest=? WHERE integration_id=?",
                (canonical_json(record), sha256_digest(record), integration_id),
            )
            self.bridge.coordination.event(
                cur,
                record["goal_id"],
                goal["advisor_epoch"],
                "integration_materialized",
                {"integration_id": integration_id, "phase": record["phase"], "result": result},
            )
            return {
                **record,
                "replayed": False,
                "workspace_status": "unchanged" if record["workspace"] else None,
            }

    def status(self, integration_id: str) -> dict[str, Any]:
        with self.store.transaction() as cur:
            record = self.get(cur, integration_id)
            try:
                self._validate(cur, record)
                validity: dict[str, Any] = {"valid": True, "error": None}
            except BridgeError as exc:
                validity = {"valid": False, "error": {"code": exc.code, "message": exc.message}}
            workspace = self._workspace_check(record) if record["workspace"] else None
            return {**record, "inputs_status": validity, "workspace_status": workspace}
