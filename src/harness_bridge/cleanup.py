"""Explicit conservative worktree cleanup; all refs, evidence and dirty trees are retained.

Never force-remove, reset, clean, prune, delete a branch, or traverse arbitrary caller paths.
The preview binds repository-owned resource IDs and exact observations, not deletion paths.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, field_validator

from harness_bridge.baselines import approved, read_record, validate_pin
from harness_bridge.coordination import Contract, check_key, parse_contract
from harness_bridge.dispatch import frozen_spec, integration_holds, occupied_tasks
from harness_bridge.errors import BridgeError
from harness_bridge.models import canonical_json, sha256_digest
from harness_bridge.store import new_id
from harness_bridge.workspace import checkout_fingerprint, git, verify_worktree

if TYPE_CHECKING:
    from harness_bridge.service import Bridge


class CleanupResource(Contract):
    resource_id: str = Field(min_length=1, max_length=160)
    fingerprint: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class CleanupRequest(Contract):
    schema_version: Literal["1.0"]
    retention: Literal["clean_worktrees_keep_refs_and_evidence"]
    resources: list[CleanupResource] = Field(min_length=1, max_length=200)

    @field_validator("resources")
    @classmethod
    def unique(cls, values: list[CleanupResource]) -> list[CleanupResource]:
        if len({r.resource_id for r in values}) != len(values):
            raise ValueError("cleanup resources must be unique")
        return values


def exact_files(path: Path, tree: str) -> bool:
    """Compare raw bytes/modes, including ignored/empty extras, without Git filters.

    Git status alone can hide ignored files, index flags, clean filters and user work.
    Submodules and unexpected filesystem entries are retained rather than recursively removed.
    """
    expected = {}
    directories = {"."}
    entries = git(["ls-tree", "-r", "-z", tree], cwd=path).stdout.split(b"\0")
    for entry in entries:
        if not entry:
            continue
        meta, raw_name = entry.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        if kind != "blob":
            return False
        name = raw_name.decode("utf-8", "surrogateescape")
        expected[name] = (mode, oid)
        directories.update(str(p) for p in Path(name).parents)
    observed = set()
    for root, dirs, files in os.walk(path, followlinks=False):
        relative = Path(root).relative_to(path)
        if str(relative) not in directories:
            return False
        for name in [*dirs, *files]:
            item = Path(root) / name
            rel = str(item.relative_to(path))
            if rel == ".git":
                if not item.is_file() or item.is_symlink():
                    return False
                continue
            info = item.lstat()
            if stat.S_ISDIR(info.st_mode):
                if rel not in directories:
                    return False
                continue
            if rel not in expected or not (
                stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            ):
                return False
            mode = (
                "120000" if item.is_symlink() else ("100755" if info.st_mode & 0o111 else "100644")
            )
            content = os.fsencode(os.readlink(item)) if item.is_symlink() else item.read_bytes()
            expected_mode, oid = expected[rel]
            algorithm = "sha1" if len(oid) == 40 else "sha256"
            actual = hashlib.new(
                algorithm, f"blob {len(content)}\0".encode() + content, usedforsecurity=False
            ).hexdigest()
            if actual != oid or mode != expected_mode:
                return False
            observed.add(rel)
    return observed == set(expected)


class Cleanup:
    def __init__(self, bridge: Bridge) -> None:
        self.b = bridge
        self.store = bridge.store

    def guard(self, cur: sqlite3.Cursor, goal: sqlite3.Row) -> None:
        if self.b.deliveries.goal_view(cur, goal)["status"] != "delivered":
            raise BridgeError(
                "STATE_CONFLICT", "cleanup requires a confirmed unchanged local delivery"
            )
        if occupied_tasks(cur, goal["project_id"]) or integration_holds(cur, goal["project_id"]):
            raise BridgeError("STATE_CONFLICT", "active or unknown exits retain all workspaces")
        if cur.execute(
            "SELECT 1 FROM worker_jobs w JOIN goal_tasks gt USING(task_id) "
            "JOIN goals g USING(goal_id) WHERE g.project_id=? "
            "AND w.phase IN ('reserved','claimed')",
            (goal["project_id"],),
        ).fetchone():
            raise BridgeError("STATE_CONFLICT", "unfinished workers retain all workspaces")

    def descriptors(self, cur: sqlite3.Cursor, goal: sqlite3.Row) -> list[dict[str, Any]]:
        out = []
        for row in cur.execute(
            "SELECT t.* FROM tasks t JOIN goal_tasks gt USING(task_id) WHERE gt.goal_id=?",
            (goal["goal_id"],),
        ).fetchall():
            frozen_spec(row)
            snapshot = approved(cur, row["task_id"])
            expected_path = self.b.worktrees_dir / row["task_id"]
            branch = f"hbridge/{row['task_id']}"
            if (
                row["state"] != "SUCCEEDED"
                or snapshot is None
                or row["worktree_path"] != str(expected_path)
                or row["task_branch"] != branch
                or row["repo_identity"] != goal["repo_identity"]
                or row["repo_path"] != goal["repo_path"]
            ):
                raise BridgeError(
                    "INTEGRITY_ERROR", "cleanup task ownership/approval binding changed"
                )
            out.append(
                {
                    "resource_id": row["task_id"],
                    "path": str(expected_path),
                    "branch": branch,
                    "snapshot": snapshot,
                }
            )
        for row in cur.execute(
            "SELECT integration_id FROM integrations WHERE goal_id=?", (goal["goal_id"],)
        ).fetchall():
            record = self.b.integrations.get(cur, row["integration_id"])
            if not record["workspace"]:
                continue
            expected_path = self.b.state_dir / "integrations" / record["integration_id"]
            branch = f"hbridge/integration/{record['integration_id']}"
            if (
                record["workspace"] != {"path": str(expected_path), "branch": branch}
                or record["repo_identity"] != goal["repo_identity"]
                or record["repo_path"] != goal["repo_path"]
            ):
                raise BridgeError(
                    "INTEGRITY_ERROR", "cleanup integration ownership binding changed"
                )
            out.append(
                {
                    "resource_id": record["integration_id"],
                    "path": str(expected_path),
                    "branch": branch,
                    "snapshot": record["result"],
                }
            )
        return out

    def observe(self, goal: sqlite3.Row, item: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._observe(goal, item)
        except OSError:
            return {**item, "eligible": False, "reason": "filesystem_observation_failed"}

    def _observe(self, goal: sqlite3.Row, item: dict[str, Any]) -> dict[str, Any]:
        path = Path(item["path"])
        if not re.fullmatch(r"(?:tsk|integration)_[0-9a-f]{20}", item["resource_id"]):
            raise BridgeError("INTEGRITY_ERROR", "invalid owned cleanup resource ID")
        directory = "worktrees" if item["resource_id"].startswith("tsk_") else "integrations"
        if path != self.b.state_dir / directory / item["resource_id"]:
            raise BridgeError("INTEGRITY_ERROR", "cleanup resource escaped its owned directory")
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink():
                return {**item, "eligible": False, "reason": "symlink"}
            if ancestor == self.b.state_dir:
                break
        if not path.exists():
            return {**item, "eligible": False, "reason": "missing"}
        snapshot = item["snapshot"]
        validate_pin(goal["repo_path"], snapshot)
        if not verify_worktree(path, snapshot["commit_sha"], item["branch"], goal["repo_path"]):
            return {**item, "eligible": False, "reason": "foreign_workspace"}
        top = git(["rev-parse", "--show-toplevel"], cwd=path).stdout.decode().strip()
        if os.path.realpath(top) != str(path.resolve()):
            return {**item, "eligible": False, "reason": "foreign_workspace"}
        # Prove reciprocal Git registration; a copied .git pointer is not an owned checkout.
        gitdir = Path(git(["rev-parse", "--absolute-git-dir"], cwd=path).stdout.decode().strip())
        backlink = gitdir / "gitdir"
        if (
            not backlink.is_file()
            or backlink.is_symlink()
            or os.path.realpath(backlink.read_text().strip()) != str(path / ".git")
        ):
            return {**item, "eligible": False, "reason": "foreign_registration"}
        if (gitdir / "locked").exists():
            return {**item, "eligible": False, "reason": "locked_worktree"}
        extra_metadata = sorted(
            p.name
            for p in gitdir.iterdir()
            if p.name
            not in {
                "HEAD",
                "index",
                "gitdir",
                "commondir",
                "logs",
                "ORIG_HEAD",
                "refs",
                "COMMIT_EDITMSG",
            }
        )
        if extra_metadata:
            return {
                **item,
                "eligible": False,
                "reason": "git_metadata_retained",
                "metadata": extra_metadata,
            }
        observed = checkout_fingerprint(str(path))
        message = gitdir / "COMMIT_EDITMSG"
        if os.path.lexists(message):
            retained_message = git(["cat-file", "commit", observed["head"]], cwd=path).stdout.split(
                b"\n\n", 1
            )[1]
            if (
                not message.is_file()
                or message.is_symlink()
                or message.read_bytes() != retained_message
            ):
                return {**item, "eligible": False, "reason": "commit_message_draft_retained"}
        # Recent Git creates an empty per-worktree refs directory and ORIG_HEAD on add.
        # Keep actual per-worktree refs and any prior commit not reachable from the retained branch.
        refs = gitdir / "refs"
        if refs.is_symlink() or (
            refs.exists()
            and (
                not refs.is_dir() or any(not p.is_dir() or p.is_symlink() for p in refs.rglob("*"))
            )
        ):
            return {**item, "eligible": False, "reason": "worktree_refs_retained"}
        original = gitdir / "ORIG_HEAD"
        if os.path.lexists(original):
            if not original.is_file() or original.is_symlink():
                return {**item, "eligible": False, "reason": "original_head_retained"}
            oid = original.read_text().strip()
            if (
                not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", oid)
                or git(
                    ["merge-base", "--is-ancestor", oid, observed["head"]], cwd=path, check=False
                ).returncode
            ):
                return {**item, "eligible": False, "reason": "original_head_retained"}
        if observed["status"]:
            return {**item, "eligible": False, "reason": "working_changes_retained"}
        if not exact_files(path, snapshot["tree_sha"]):
            return {**item, "eligible": False, "reason": "changed_or_extra_files"}
        result = {**item, "checkout": observed}
        return {**result, "eligible": True, "fingerprint": sha256_digest(result)}

    def inventory(self, cur: sqlite3.Cursor, goal: sqlite3.Row) -> list[dict[str, Any]]:
        unresolved: set[str] = set()
        for row in cur.execute(
            "SELECT * FROM cleanup_requests WHERE goal_id=?", (goal["goal_id"],)
        ):
            record = read_record(row)
            assert record is not None
            unresolved.update(
                r["resource_id"]
                for r in record["resources"]
                if r["outcome"] in ("removing", "unknown")
            )
        items = []
        for descriptor in self.descriptors(cur, goal):
            item = self.observe(goal, descriptor)
            if item["resource_id"] in unresolved and item.get("reason") != "missing":
                item.update(eligible=False, reason="prior_removal_unconfirmed")
            items.append(item)
        return items

    def preview(self, goal_id: str) -> dict[str, Any]:
        with self.store.transaction() as cur:
            goal = self.b.coordination._goal(cur, goal_id)
            blockers = []
            try:
                self.guard(cur, goal)
            except BridgeError as exc:
                blockers.append(exc.to_dict())
            items = self.inventory(cur, goal) if not blockers else []
            resources = [
                {"resource_id": r["resource_id"], "fingerprint": r["fingerprint"]}
                for r in items
                if r["eligible"]
            ]
            return {
                "goal_id": goal_id,
                "requests": [
                    self.get(cur, row[0])
                    for row in cur.execute(
                        "SELECT cleanup_id FROM cleanup_requests WHERE goal_id=? ORDER BY rowid",
                        (goal_id,),
                    ).fetchall()
                ],
                "blockers": blockers,
                "resources": items,
                "retained": ["all_branches", "all_private_refs", "database", "evidence", "caches"],
                "request_template": None
                if blockers or not resources
                else {
                    "schema_version": "1.0",
                    "retention": "clean_worktrees_keep_refs_and_evidence",
                    "resources": resources,
                },
            }

    def get(self, cur: sqlite3.Cursor, cleanup_id: str) -> dict[str, Any]:
        row = cur.execute(
            "SELECT * FROM cleanup_requests WHERE cleanup_id=?", (cleanup_id,)
        ).fetchone()
        if row is None:
            raise BridgeError("NOT_FOUND", "cleanup request does not exist")
        record = read_record(row)
        assert record is not None
        if (
            record["cleanup_id"] != cleanup_id
            or record["goal_id"] != row["goal_id"]
            or sha256_digest(record["request"]) != row["request_digest"]
            or [
                {"resource_id": r["resource_id"], "fingerprint": r["fingerprint"]}
                for r in record["resources"]
            ]
            != record["request"]["resources"]
        ):
            raise BridgeError("INTEGRITY_ERROR", "cleanup request binding changed")
        return record

    def save(self, cur: sqlite3.Cursor, record: dict[str, Any]) -> None:
        cur.execute(
            "UPDATE cleanup_requests SET record_json=?,record_digest=? WHERE cleanup_id=?",
            (canonical_json(record), sha256_digest(record), record["cleanup_id"]),
        )

    def status(self, cleanup_id: str) -> dict[str, Any]:
        with self.store.transaction() as cur:
            return self.get(cur, cleanup_id)

    def apply(self, goal_id: str, data: Any, key: str) -> dict[str, Any]:
        from harness_bridge.service import _fault_point

        check_key(key)
        request = parse_contract(CleanupRequest, data).model_dump(mode="json")
        digest = sha256_digest(request)
        with self.store.transaction() as cur:
            goal = self.b.coordination.guard_goal(
                cur, goal_id, self.b.advisor_claim, allow_delivery=True
            )
            row = cur.execute(
                "SELECT * FROM cleanup_requests WHERE goal_id=? AND idempotency_key=?",
                (goal_id, key),
            ).fetchone()
            if row:
                if row["request_digest"] != digest:
                    raise BridgeError("IDEMPOTENCY_CONFLICT", "cleanup key already used")
                record = self.get(cur, row["cleanup_id"])
                replayed = True
            else:
                self.guard(cur, goal)
                inventory = {r["resource_id"]: r for r in self.inventory(cur, goal)}
                selected = []
                for desired in request["resources"]:
                    item = inventory.get(desired["resource_id"])
                    if (
                        not item
                        or not item["eligible"]
                        or item["fingerprint"] != desired["fingerprint"]
                    ):
                        raise BridgeError(
                            "STATE_CONFLICT", "cleanup preview changed; inspect a fresh preview"
                        )
                    selected.append({**item, "outcome": "pending"})
                record = {
                    "cleanup_id": new_id("cleanup"),
                    "goal_id": goal_id,
                    "request": request,
                    "resources": selected,
                    "status": "pending",
                }
                cur.execute(
                    "INSERT INTO cleanup_requests VALUES (?,?,?,?,?,?,?)",
                    (
                        record["cleanup_id"],
                        goal_id,
                        key,
                        digest,
                        canonical_json(record),
                        sha256_digest(record),
                        self.store.clock(),
                    ),
                )
                self.b.coordination.event(
                    cur,
                    goal_id,
                    goal["advisor_epoch"],
                    "cleanup_reserved",
                    {"cleanup_id": record["cleanup_id"], "request": request},
                )
                replayed = False
        _fault_point("after_cleanup_reserved")
        for number in range(len(record["resources"])):
            with self.store.transaction() as cur:
                record = self.get(cur, record["cleanup_id"])
                item = record["resources"][number]
                if item["outcome"] not in ("pending", "removing"):
                    continue
                goal = self.b.coordination.guard_goal(
                    cur, goal_id, self.b.advisor_claim, allow_delivery=True
                )
                self.guard(cur, goal)
                if item["outcome"] == "removing":
                    # Never launch a second removal after an unconfirmed process lifetime.
                    item["outcome"] = (
                        "missing_after_interruption"
                        if not os.path.lexists(item["path"])
                        else "unknown"
                    )
                    self.save(cur, record)
                    continue
                fresh = {r["resource_id"]: r for r in self.inventory(cur, goal)}.get(
                    item["resource_id"]
                )
                if (
                    not fresh
                    or not fresh["eligible"]
                    or fresh["fingerprint"] != item["fingerprint"]
                ):
                    item.update(outcome="retained", reason="changed_since_preview")
                    self.save(cur, record)
                    continue
                item["outcome"] = "removing"
                self.save(cur, record)
            _fault_point("before_cleanup_remove")
            with self.store.transaction() as cur:
                record = self.get(cur, record["cleanup_id"])
                item = record["resources"][number]
                if item["outcome"] != "removing":
                    continue
                goal = self.b.coordination.guard_goal(
                    cur, goal_id, self.b.advisor_claim, allow_delivery=True
                )
                self.guard(cur, goal)
                fresh = self.observe(
                    goal, {k: item[k] for k in ("resource_id", "path", "branch", "snapshot")}
                )
                if not fresh["eligible"] or fresh["fingerprint"] != item["fingerprint"]:
                    item.update(outcome="retained", reason="changed_before_removal")
                else:
                    result = git(
                        ["worktree", "remove", "--", item["path"]],
                        cwd=goal["repo_path"],
                        check=False,
                    )
                    _fault_point("after_cleanup_remove")
                    item["outcome"] = "removed" if result.returncode == 0 else "retained"
                    if result.returncode:
                        item["reason"] = "git_refused_removal"
                self.save(cur, record)
        with self.store.transaction() as cur:
            record = self.get(cur, record["cleanup_id"])
            status = (
                "needs_attention"
                if any(r["outcome"] == "unknown" for r in record["resources"])
                else "complete"
            )
            if record["status"] != status:
                goal = self.b.coordination.guard_goal(
                    cur, goal_id, self.b.advisor_claim, allow_delivery=True
                )
                record["status"] = status
                self.save(cur, record)
                self.b.coordination.event(
                    cur,
                    goal_id,
                    goal["advisor_epoch"],
                    "cleanup_finished",
                    {"cleanup_id": record["cleanup_id"], "status": status},
                )
        return {**record, "replayed": replayed}
