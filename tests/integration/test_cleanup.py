"""Conservative retention and replay with isolated local Git, never user worktrees."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.baselines import commit_tree
from harness_bridge.coordination import AdvisorClaim
from harness_bridge.errors import BridgeError
from harness_bridge.service import Bridge
from harness_bridge.store import SCHEMA_REVISION
from harness_bridge.workspace import checkout_fingerprint, git
from tests.conftest import Fixture
from tests.integration.test_coordination import takeover
from tests.integration.test_delivery import approved, deliver
from tests.integration.test_integration_checks import candidate, claim_args


def delivered(fx: Fixture) -> tuple[Bridge, dict[str, Any], str, Path]:
    b, g, ident = approved(fx)
    deliver(b, g, ident)
    return b, g, ident, Path(b.integrations.status(ident)["workspace"]["path"])


def test_preview_apply_cli_reopen_and_replay_retain_all_evidence_and_branches(fx: Fixture) -> None:
    b, g, _, path = delivered(fx)
    (fx.repo / "keep.txt").write_text("source user work")
    before = checkout_fingerprint(str(fx.repo))
    evidence = {
        str(p): p.read_bytes()
        for p in fx.state_dir.rglob("*")
        if p.is_file() and ("artifacts" in p.parts or "integration-checks" in p.parts)
    }
    refs = git(["show-ref"], cwd=fx.repo).stdout
    _, preview = fx.cli("goal", "cleanup", g["goal_id"])
    assert preview["blockers"] == [] and path.exists()
    assert any(r.get("reason") == "working_changes_retained" for r in preview["resources"]), [
        (r.get("reason"), r.get("metadata")) for r in preview["resources"]
    ]
    file = fx.base / "cleanup.json"
    file.write_text(json.dumps(preview["request_template"]))
    args = (
        "goal",
        "cleanup",
        g["goal_id"],
        "--file",
        str(file),
        "--idempotency-key",
        "cleanup",
        *claim_args(b),
    )
    _, receipt = fx.cli(*args)
    assert receipt["status"] == "complete"
    assert [r["outcome"] for r in receipt["resources"]] == ["removed"]
    assert not path.exists()
    assert refs == git(["show-ref"], cwd=fx.repo).stdout
    assert all(Path(p).read_bytes() == content for p, content in evidence.items())
    assert checkout_fingerprint(str(fx.repo)) == before
    assert b.coordination.status(g["goal_id"])["state"] == "DELIVERED"
    # A later user-created directory at the old path is never re-deleted by replay.
    path.mkdir()
    (path / "user.txt").write_text("keep on replay")
    _, replay = fx.cli(*args)
    assert replay == {**receipt, "replayed": True}
    assert (path / "user.txt").read_text() == "keep on replay"
    _, status = fx.cli("cleanup", receipt["cleanup_id"])
    assert status == {k: v for k, v in receipt.items() if k != "replayed"}
    b.close()


@pytest.mark.parametrize(
    "case",
    [
        "dirty",
        "ignored",
        "empty_dir",
        "skip_worktree",
        "locked",
        "symlink",
        "foreign_branch",
        "staged",
        "git_operation",
        "worktree_ref",
        "unreachable_original",
        "commit_draft",
    ],
)
def test_user_changes_and_unowned_resources_are_retained(fx: Fixture, case: str) -> None:
    b, g, ident, path = delivered(fx)
    before = checkout_fingerprint(str(fx.repo))
    file = path / "tagnorm/normalize.py"
    if case in ("dirty", "skip_worktree", "staged"):
        if case == "skip_worktree":
            git(["update-index", "--skip-worktree", "--", "tagnorm/normalize.py"], cwd=path)
        file.write_text("# user changed this after delivery\n")
        if case == "staged":
            git(["add", "--", "tagnorm/normalize.py"], cwd=path)
    elif case == "ignored":
        (path / "__pycache__").mkdir(exist_ok=True)
        (path / "__pycache__/private.pyc").write_bytes(b"user cache")
    elif case == "empty_dir":
        (path / "user-empty-folder").mkdir()
    elif case == "locked":
        git(["worktree", "lock", "--", str(path)], cwd=fx.repo)
    elif case == "symlink":
        moved = path.with_name(path.name + "-user")
        path.rename(moved)
        path.symlink_to(moved, target_is_directory=True)
    elif case in ("git_operation", "commit_draft"):
        gitdir = Path(git(["rev-parse", "--absolute-git-dir"], cwd=path).stdout.decode().strip())
        (gitdir / ("MERGE_HEAD" if case == "git_operation" else "COMMIT_EDITMSG")).write_text(
            g["base_sha"] + "\n" if case == "git_operation" else "unsaved user commit draft\n"
        )
    elif case in ("worktree_ref", "unreachable_original"):
        gitdir = Path(git(["rev-parse", "--absolute-git-dir"], cwd=path).stdout.decode().strip())
        if case == "worktree_ref":
            ref = gitdir / "refs/worktree/keep"
            ref.parent.mkdir(parents=True, exist_ok=True)
            ref.write_text(g["base_sha"] + "\n")
        else:
            tree = git(["rev-parse", "HEAD^{tree}"], cwd=path).stdout.decode().strip()
            orphan = commit_tree(str(fx.repo), tree, [], "user's otherwise unreachable work")
            (gitdir / "ORIG_HEAD").write_text(orphan + "\n")
    else:
        git(["checkout", "-qb", "user-branch"], cwd=path)
    preview = b.cleanup.preview(g["goal_id"])
    resource = next(r for r in preview["resources"] if r["resource_id"] == ident)
    assert not resource["eligible"] and preview["request_template"] is None
    assert path.exists()
    assert checkout_fingerprint(str(fx.repo)) == before
    b.close()


def test_changed_preview_foreign_path_and_stale_advisor_cannot_remove(fx: Fixture) -> None:
    b, g, _, path = delivered(fx)
    request = b.cleanup.preview(g["goal_id"])["request_template"]
    (path / "user.txt").write_text("new data")
    with pytest.raises(BridgeError):
        b.cleanup.apply(g["goal_id"], request, "changed")
    (path / "user.txt").unlink()
    foreign = json.loads(json.dumps(request))
    foreign["resources"][0]["resource_id"] = str(fx.repo)
    with pytest.raises(BridgeError):
        b.cleanup.apply(g["goal_id"], foreign, "foreign")
    new = takeover(b, g)["advisor_claim"]
    with pytest.raises(BridgeError) as error:
        b.cleanup.apply(g["goal_id"], request, "stale")
    assert error.value.code == "STALE_ADVISOR" and path.exists()
    b.advisor_claim = AdvisorClaim.model_validate(new)
    assert b.cleanup.apply(g["goal_id"], request, "current")["status"] == "complete"
    b.close()


@pytest.mark.parametrize(
    "case", ["not_delivered", "unknown_attempt", "unknown_check", "delivery_changed"]
)
def test_undelivered_or_unknown_execution_never_cleans(fx: Fixture, case: str) -> None:
    if case == "not_delivered":
        b, g, ident = candidate(fx)
        path = Path(b.integrations.status(ident)["workspace"]["path"])
        request = {
            "schema_version": "1.0",
            "retention": "clean_worktrees_keep_refs_and_evidence",
            "resources": [{"resource_id": ident, "fingerprint": "sha256:" + "0" * 64}],
        }
    else:
        b, g, ident, path = delivered(fx)
        request = b.cleanup.preview(g["goal_id"])["request_template"]
        if case == "delivery_changed":
            git(["update-ref", "refs/heads/delivered/result", g["base_sha"]], cwd=fx.repo)
        else:
            with b.store.transaction() as cur:
                if case == "unknown_attempt":
                    cur.execute("UPDATE attempts SET exit_confirmed=NULL")
                else:
                    cur.execute("UPDATE integration_verifications SET exit_confirmed=NULL")
    with pytest.raises(BridgeError):
        b.cleanup.apply(g["goal_id"], request, "blocked")
    assert path.exists()
    b.close()


@pytest.mark.parametrize(
    "point,expected",
    [
        ("after_cleanup_reserved", "removed"),
        ("before_cleanup_remove", "unknown"),
        ("after_cleanup_remove", "missing_after_interruption"),
    ],
)
def test_crash_replay_never_reissues_unconfirmed_removal(
    fx: Fixture, point: str, expected: str
) -> None:
    b, g, _, path = delivered(fx)
    request = b.cleanup.preview(g["goal_id"])["request_template"]
    file = fx.base / "cleanup.json"
    file.write_text(json.dumps(request))
    args = (
        "goal",
        "cleanup",
        g["goal_id"],
        "--file",
        str(file),
        "--idempotency-key",
        "cleanup",
        *claim_args(b),
    )
    code, output = fx.cli(*args, check_ok=None, env={**os.environ, "HBRIDGE_TEST_FAULT": point})
    assert code == 70, output
    receipt = b.cleanup.apply(g["goal_id"], request, "cleanup")
    assert receipt["resources"][0]["outcome"] == expected
    assert path.exists() == (expected == "unknown")
    if expected == "unknown":
        assert b.cleanup.preview(g["goal_id"])["request_template"] is None
        with pytest.raises(BridgeError):
            b.cleanup.apply(g["goal_id"], request, "new-key")
    assert b.cleanup.apply(g["goal_id"], request, "cleanup") == receipt
    b.close()


def test_changed_after_reservation_is_retained_and_same_key_cannot_expand(fx: Fixture) -> None:
    b, g, _, path = delivered(fx)
    request = b.cleanup.preview(g["goal_id"])["request_template"]
    file = fx.base / "cleanup.json"
    file.write_text(json.dumps(request))
    code, _ = fx.cli(
        "goal",
        "cleanup",
        g["goal_id"],
        "--file",
        str(file),
        "--idempotency-key",
        "cleanup",
        *claim_args(b),
        check_ok=None,
        env={**os.environ, "HBRIDGE_TEST_FAULT": "after_cleanup_reserved"},
    )
    assert code == 70
    (path / "later.txt").write_text("retain this")
    receipt = b.cleanup.apply(g["goal_id"], request, "cleanup")
    assert receipt["resources"][0]["outcome"] == "retained"
    assert (path / "later.txt").read_text() == "retain this"
    request["resources"][0]["fingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(BridgeError) as error:
        b.cleanup.apply(g["goal_id"], request, "cleanup")
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    b.close()


def test_revision9_migration_preserves_delivered_binding_and_backups(fx: Fixture) -> None:
    b, g, _, _ = delivered(fx)
    before = b.coordination.status(g["goal_id"])
    path = b.store.db_path
    b.close()

    old = sqlite3.connect(path)
    old.execute("DROP TABLE cleanup_requests")
    old.execute("UPDATE meta SET value='9' WHERE key='schema_revision'")
    old.commit()
    old.close()
    b = fx.bridge()
    assert b.coordination.status(g["goal_id"]) == before
    assert b.cleanup.preview(g["goal_id"])["request_template"]
    backups = list((fx.state_dir / "backups").glob(f"pre-v{SCHEMA_REVISION}-*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("SELECT value FROM meta").fetchone()[0] == "9"
        assert backup.execute("SELECT status FROM deliveries").fetchone()[0] == "delivered"
    b.close()


def test_clean_committed_child_workspace_can_be_removed_without_losing_commit(fx: Fixture) -> None:
    b, g, _, _ = delivered(fx)
    task = b.store.list_tasks()[0]
    path = Path(task.worktree_path)
    git(["add", "--", "."], cwd=path)
    git(["commit", "-qm", "preserved executor commit"], cwd=path)
    head = git(["rev-parse", "HEAD"], cwd=path).stdout
    preview = b.cleanup.preview(g["goal_id"])
    assert len(preview["request_template"]["resources"]) == 2
    receipt = b.cleanup.apply(g["goal_id"], preview["request_template"], "cleanup")
    assert all(r["outcome"] == "removed" for r in receipt["resources"])
    assert not path.exists()
    assert git(["rev-parse", f"refs/heads/{task.task_branch}"], cwd=fx.repo).stdout == head
    assert b.coordination.status(g["goal_id"])["state"] == "DELIVERED"
    b.close()
