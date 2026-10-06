"""Retain approved trees and compose immutable dependency baselines, without checkouts.

Private Git refs keep objects alive; SQLite records bind them to accepted reviews/plans.
Git and SQLite cannot commit atomically. A crash may leave an unclaimed private ref; retries
only accept the exact deterministic object. No ref is overwritten or automatically removed.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from harness_bridge.errors import BridgeError
from harness_bridge.models import canonical_json, sha256_digest
from harness_bridge.store import TaskRecord
from harness_bridge.workspace import Snapshot, git

_IDENTITY = {
    "GIT_AUTHOR_NAME": "Harness Bridge",
    "GIT_AUTHOR_EMAIL": "bridge@hbridge.invalid",
    "GIT_COMMITTER_NAME": "Harness Bridge",
    "GIT_COMMITTER_EMAIL": "bridge@hbridge.invalid",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
}


def object_id(value: str) -> str:
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise BridgeError("INTEGRITY_ERROR", "invalid retained Git object ID")
    return value


def commit_tree(repo: str, tree: str, parents: list[str], message: str) -> str:
    args = ["-c", "commit.gpgSign=false", "commit-tree", object_id(tree)]
    for parent in dict.fromkeys(parents):
        args += ["-p", object_id(parent)]
    return object_id(
        git(args, cwd=repo, env_extra=_IDENTITY, input_bytes=(message + "\n").encode())
        .stdout.decode()
        .strip()
    )


def pin(repo: str, ref: str, commit: str) -> None:
    current = git(["rev-parse", "--verify", "--quiet", ref], cwd=repo, check=False)
    if current.returncode == 0:
        if current.stdout.decode().strip() == commit:
            return
        raise BridgeError("INTEGRITY_ERROR", "retained Git reference changed; refusing overwrite")
    result = git(["update-ref", ref, commit, "0" * len(commit)], cwd=repo, check=False)
    if result.returncode:
        raise BridgeError("INTEGRITY_ERROR", "could not reserve retained Git reference")


def validate_pin(repo: str, record: dict[str, Any]) -> None:
    ref = record["ref"]
    if not isinstance(ref, str) or not ref.startswith("refs/hbridge/"):
        raise BridgeError("INTEGRITY_ERROR", "invalid retained Git reference")
    commit = object_id(record["commit_sha"])
    actual = git(["rev-parse", "--verify", "--quiet", ref], cwd=repo, check=False)
    tree = git(["rev-parse", "--verify", f"{commit}^{{tree}}"], cwd=repo, check=False)
    if (
        actual.returncode
        or actual.stdout.decode().strip() != commit
        or tree.returncode
        or tree.stdout.decode().strip() != record["tree_sha"]
    ):
        raise BridgeError("INTEGRITY_ERROR", "retained Git snapshot is missing or changed")


def read_record(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data: dict[str, Any] = json.loads(row["record_json"])
    if sha256_digest(data) != row["record_digest"]:
        raise BridgeError("INTEGRITY_ERROR", "retained snapshot record no longer matches digest")
    return data


def approved(cur: sqlite3.Cursor, task_id: str) -> dict[str, Any] | None:
    row = cur.execute("SELECT * FROM approved_snapshots WHERE task_id=?", (task_id,)).fetchone()
    record = read_record(row)
    if record is not None:
        review = cur.execute(
            "SELECT * FROM reviews WHERE review_id=?", (row["review_id"],)
        ).fetchone()
        if (
            record["task_id"] != task_id
            or record["review_id"] != row["review_id"]
            or review is None
            or review["task_id"] != task_id
            or review["attempt_id"] != record["attempt_id"]
            or review["status"] != "accepted"
            or review["verdict"] != "approve"
            or json.loads(review["receipt_json"])["snapshot_digest"] != record["fingerprint"]
        ):
            raise BridgeError("INTEGRITY_ERROR", "snapshot is not bound to an accepted approval")
    return record


def retain_approval(
    cur: sqlite3.Cursor, task: TaskRecord, manifest: dict[str, Any], review_id: str
) -> dict[str, Any]:
    tree = object_id(manifest["tree_sha"])
    expected = Snapshot(task.base_sha, tree, []).fingerprint(
        task_version=task.task_version, verifier_digest=task.verifier_digest
    )
    if expected != manifest["fingerprint"] or manifest["base_sha"] != task.base_sha:
        raise BridgeError("INTEGRITY_ERROR", "approval tree does not match verified fingerprint")
    # Deliberately exclude review ID/time: retry after a rolled-back transaction uses the
    # same task/attempt/fingerprint and recovers the existing pin, even with a new review ID.
    commit = commit_tree(
        task.repo_path,
        tree,
        [task.base_sha],
        f"Harness Bridge approval {task.task_id} {manifest['attempt_id']} {expected}",
    )
    ref = f"refs/hbridge/approved/{task.task_id}/{manifest['attempt_id']}"
    pin(task.repo_path, ref, commit)
    record = {
        "task_id": task.task_id,
        "attempt_id": manifest["attempt_id"],
        "review_id": review_id,
        "fingerprint": expected,
        "base_sha": task.base_sha,
        "tree_sha": tree,
        "commit_sha": commit,
        "ref": ref,
    }
    cur.execute(
        "INSERT INTO approved_snapshots VALUES (?,?,?,?)",
        (
            task.task_id,
            review_id,
            canonical_json(record),
            sha256_digest(record),
        ),
    )
    return record


def merge_tree(repo: str, current: str, incoming: str) -> str | None:
    """Return the merged tree or a conflict; external merge drivers are never executed."""
    current, incoming = object_id(current), object_id(incoming)
    # merge-tree honors custom drivers from shared configuration. Refuse those
    # configurations instead of executing a repo/user-provided shell command.
    configured = git(
        ["config", "--null", "--name-only", "--get-regexp", r"^merge\..*\.driver$"],
        cwd=repo,
        check=False,
    )
    if configured.returncode not in (0, 1) or configured.stdout:
        raise BridgeError("PREFLIGHT_FAILED", "custom Git merge drivers require explicit handling")
    result = git(
        [
            "-c",
            "merge.renormalize=false",
            "merge-tree",
            "--write-tree",
            "-z",
            current,
            incoming,
        ],
        cwd=repo,
        check=False,
    )
    if result.returncode == 1:
        return None
    if result.returncode:
        raise BridgeError("PREFLIGHT_FAILED", "Git could not compose dependency baseline")
    return object_id(result.stdout.split(b"\0", 1)[0].decode().strip())


def compose(repo: str, child_id: str, base: str, inputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge approved commits in stable child-key order; never run external merge drivers."""
    current = object_id(base)
    for dependency in inputs:
        validate_pin(repo, dependency)
        incoming = object_id(dependency["commit_sha"])
        tree = merge_tree(repo, current, incoming)
        if tree is None:
            return {"status": "conflict", "dependency_child_id": dependency["child_id"]}
        current = commit_tree(
            repo,
            tree,
            [current, incoming],
            f"Harness Bridge baseline {child_id} {dependency['child_id']}",
        )
    tree = object_id(git(["rev-parse", f"{current}^{{tree}}"], cwd=repo).stdout.decode().strip())
    ref = f"refs/hbridge/baselines/{child_id}"
    pin(repo, ref, current)
    return {"status": "ready", "commit_sha": current, "tree_sha": tree, "ref": ref}
