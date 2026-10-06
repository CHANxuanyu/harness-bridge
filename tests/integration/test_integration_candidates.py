"""P4 frozen integration candidates: local Git/SQLite and simulated executors only."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from harness_bridge.coordination import AdvisorClaim, parse_contract
from harness_bridge.errors import BridgeError
from harness_bridge.integration import IntegrationSpec
from harness_bridge.service import Bridge
from harness_bridge.store import SCHEMA_REVISION
from harness_bridge.workspace import checkout_fingerprint, git
from tests.conftest import Fixture
from tests.helpers.reviews import review_for
from tests.integration.test_coordination import setup_goal, takeover
from tests.integration.test_dependency_baselines import approve, children
from tests.integration.test_goal_planning import control, plan, submit
from tests.integration.test_workers import finished


def request(fx: Fixture, *tasks: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "task_ids": list(tasks),
        "verification": fx.spec()["verification"],
    }


def freeze(b: Bridge, g: dict[str, Any], fx: Fixture, *tasks: str) -> dict[str, Any]:
    return b.integrations.freeze(g["goal_id"], request(fx, *tasks), "integration")


def one(fx: Fixture) -> tuple[Bridge, dict[str, Any], str]:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"))
    return b, g, approve(b, ids["a"])


def materialize(b: Bridge, frozen: dict[str, Any]) -> dict[str, Any]:
    return b.integrations.materialize(frozen["integration_id"])


def test_full_two_child_candidate_uses_retained_inputs_not_current_workspaces(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b"))
    a = approve(b, ids["a"], {"tagnorm/a.txt": "approved-a\n"})
    c = approve(b, ids["b"], {"tagnorm/b.txt": "approved-b\n"})
    before_budget = b.coordination.status(g["goal_id"])["budget"]
    frozen = freeze(b, g, fx, a, c)
    assert frozen["phase"] == "FROZEN" and frozen["workspace"] is None
    assert not (fx.state_dir / "integrations").exists()
    (Path(b.store.get_task(a).worktree_path) / "tagnorm/a.txt").write_text("late child edit")
    git(["gc", "--prune=now"], cwd=fx.repo)
    # Advancing and dirtying the source after registration must not change the frozen base.
    (fx.repo / "new-source.txt").write_text("later source commit")
    git(["add", "--", "new-source.txt"], cwd=fx.repo)
    git(["commit", "-qm", "advance source"], cwd=fx.repo)
    (fx.repo / "keep.txt").write_text("user work")
    source = checkout_fingerprint(str(fx.repo))
    ready = materialize(b, frozen)
    root = Path(ready["workspace"]["path"])
    assert (root / "tagnorm/a.txt").read_text() == "approved-a\n"
    assert (root / "tagnorm/b.txt").read_text() == "approved-b\n"
    assert not (root / "new-source.txt").exists()
    assert ready["base_sha"] == g["base_sha"] != source["head"]
    assert ready["phase"] == "CANDIDATE" and ready["verification_status"] == "not_run"
    assert ready["result"]["applied_task_ids"] == [a, c]
    assert checkout_fingerprint(str(fx.repo)) == source
    assert (fx.repo / "keep.txt").read_text() == "user work"
    status = b.coordination.status(g["goal_id"])
    assert status["state"] == "ACTIVE" and status["delivery"]["status"] == "not_ready"
    assert status["budget"] == before_budget
    assert status["integrations"][0]["integration_id"] == ready["integration_id"]
    assert b.integrations.status(ready["integration_id"])["inputs_status"]["valid"]
    b.close()


def test_candidate_carries_add_delete_binary_rename_and_executable_mode(fx: Fixture) -> None:
    (fx.repo / "tagnorm/remove.txt").write_text("remove me")
    (fx.repo / "tagnorm/old.txt").write_text("rename me")
    git(["add", "--", "tagnorm"], cwd=fx.repo)
    git(["commit", "-qm", "fixture files"], cwd=fx.repo)
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "task", goal_id=g["goal_id"])["task_id"]
    b.run(task)
    root = Path(b.store.get_task(task).worktree_path)
    (root / "tagnorm/remove.txt").unlink()
    (root / "tagnorm/old.txt").rename(root / "tagnorm/new.txt")
    (root / "tagnorm/data.bin").write_bytes(bytes(range(256)))
    (root / "tagnorm/tool.sh").write_text("#!/bin/sh\nexit 0\n")
    (root / "tagnorm/tool.sh").chmod(0o755)
    b.verify(task)
    b.review(task, review_for(b.artifacts(task), "approve", "approve"))
    ready = materialize(b, freeze(b, g, fx, task))
    candidate = Path(ready["workspace"]["path"])
    assert not (candidate / "tagnorm/remove.txt").exists()
    assert not (candidate / "tagnorm/old.txt").exists()
    assert (candidate / "tagnorm/new.txt").read_text() == "rename me"
    assert (candidate / "tagnorm/data.bin").read_bytes() == bytes(range(256))
    assert (candidate / "tagnorm/tool.sh").stat().st_mode & 0o111
    b.close()


def test_conflict_preserves_partial_pin_and_original_approvals_without_workspace(
    fx: Fixture,
) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b"))
    a = approve(b, ids["a"], {"tagnorm/shared.txt": "a\n"})
    c = approve(b, ids["b"], {"tagnorm/shared.txt": "b\n"})
    frozen = freeze(b, g, fx, a, c)
    before = [b.status(t)["approved_snapshot"] for t in (a, c)]
    conflict = materialize(b, frozen)
    assert conflict["phase"] == "CONFLICT" and conflict["workspace"] is None
    assert conflict["result"]["conflict_task_id"] == c
    assert conflict["result"]["applied_task_ids"] == [a]
    content = git(["show", f"{conflict['result']['commit_sha']}:tagnorm/shared.txt"], cwd=fx.repo)
    assert content.stdout == b"a\n"
    assert [b.status(t)["approved_snapshot"] for t in (a, c)] == before
    assert materialize(b, frozen) == {**conflict, "replayed": True}
    assert not (fx.state_dir / "integrations").exists()
    assert b.coordination.status(g["goal_id"])["state"] == "NEEDS_ATTENTION"
    assert (
        len(
            [
                e
                for e in b.coordination.status(g["goal_id"])["recent_events"]
                if e["type"] == "integration_materialized"
            ]
        )
        == 1
    )
    b.close()


def test_dependency_order_preserves_descendant_edits_without_reapplying_parent(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b", "a"))
    a = approve(b, ids["a"], {"tagnorm/value.txt": "old\n"})
    c = approve(b, ids["b"], {"tagnorm/value.txt": "new\n"})
    with pytest.raises(BridgeError, match="dependencies first"):
        freeze(b, g, fx, c, a)
    ready = materialize(b, freeze(b, g, fx, a, c))
    assert (Path(ready["workspace"]["path"]) / "tagnorm/value.txt").read_text() == "new\n"
    b.close()


@pytest.mark.parametrize(
    "reason",
    [
        "unmaterialized",
        "unapproved",
        "omitted",
        "foreign",
        "unknown_attempt",
        "unknown_preparation",
    ],
)
def test_unfinished_missing_foreign_and_unknown_children_refuse_freeze(
    fx: Fixture, reason: str
) -> None:
    b, g, a = one(fx)
    tasks = [a]
    if reason == "unmaterialized":
        submit(b, g, plan(fx, "b"), key="extra")
    elif reason == "unapproved":
        tasks.append(b.create(fx.spec(), "second", goal_id=g["goal_id"])["task_id"])
    elif reason == "omitted":
        ids = submit(b, g, plan(fx, "b"), key="extra")
        approve(b, ids["children"][0]["child_id"])
    elif reason == "foreign":
        tasks.append(b.create(fx.spec(), "standalone")["task_id"])
    elif reason == "unknown_attempt":
        with b.store.transaction() as cur:
            cur.execute("UPDATE attempts SET exit_confirmed=NULL WHERE task_id=?", (a,))
    else:
        with b.store.transaction() as cur:
            cur.execute(
                "INSERT INTO preparation_runs "
                "VALUES (?,?,?,'interrupted',NULL,'{}','unused','now')",
                ("prep_unknown", a, "unknown"),
            )
    with pytest.raises(BridgeError):
        freeze(b, g, fx, *tasks)
    assert not b.coordination.status(g["goal_id"])["integrations"]
    b.close()


def test_new_goal_membership_stales_frozen_inputs_without_silent_replacement(fx: Fixture) -> None:
    b, g, task = one(fx)
    frozen = freeze(b, g, fx, task)
    submit(b, g, plan(fx, "new"), key="new-plan")
    assert not b.integrations.status(frozen["integration_id"])["inputs_status"]["valid"]
    with pytest.raises(BridgeError):
        materialize(b, frozen)
    assert freeze(b, g, fx, task) == {**frozen, "replayed": True}
    assert b.integrations.status(frozen["integration_id"])["phase"] == "FROZEN"
    b.close()


def test_current_advisor_required_for_mutations_but_reads_survive_takeover(fx: Fixture) -> None:
    b, g, task = one(fx)
    frozen = freeze(b, g, fx, task)
    next_claim = takeover(b, g)["advisor_claim"]
    assert b.integrations.status(frozen["integration_id"])["inputs_status"]["valid"]
    with pytest.raises(BridgeError) as err:
        materialize(b, frozen)
    assert err.value.code == "STALE_ADVISOR"
    with pytest.raises(BridgeError):
        freeze(b, g, fx, task)
    b.advisor_claim = AdvisorClaim.model_validate(next_claim)
    assert materialize(b, frozen)["phase"] == "CANDIDATE"
    b.close()


def test_pause_does_not_spend_budget_and_termination_stops_new_materialization(fx: Fixture) -> None:
    b, g, task = one(fx)
    control(b, g, "pause")
    before = b.coordination.status(g["goal_id"])["budget"]
    frozen = freeze(b, g, fx, task)
    assert b.coordination.status(g["goal_id"])["budget"] == before
    control(b, g, "cancel")
    with pytest.raises(BridgeError):
        materialize(b, frozen)
    assert b.integrations.status(frozen["integration_id"])["phase"] == "FROZEN"
    b.close()


@pytest.mark.parametrize("target", ["approval_pin", "candidate_pin", "record", "spec"])
def test_missing_or_changed_evidence_fails_closed(fx: Fixture, target: str) -> None:
    b, g, task = one(fx)
    frozen = freeze(b, g, fx, task)
    ready = materialize(b, frozen)
    if target.endswith("pin"):
        ref = frozen["inputs"][0]["ref"] if target == "approval_pin" else ready["result"]["ref"]
        git(["update-ref", "-d", ref], cwd=fx.repo)
        status = b.integrations.status(frozen["integration_id"])
        assert not status["inputs_status"]["valid"]
    else:
        with b.store.transaction() as cur:
            cur.execute(
                {
                    "record": "UPDATE integrations SET record_json='{}'",
                    "spec": "UPDATE integrations SET spec_json='{}'",
                }[target]
            )
    with pytest.raises(BridgeError) as err:
        materialize(b, frozen)
    assert err.value.code == "INTEGRITY_ERROR"
    b.close()


@pytest.mark.parametrize("dirty", ["none", "visible", "hidden"])
def test_git_workspace_before_db_rollback_is_adopted_only_if_unchanged(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch, dirty: str
) -> None:
    b, g, task = one(fx)
    frozen = freeze(b, g, fx, task)
    event = b.coordination.event

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("crash after Git changes before DB commit")

    monkeypatch.setattr(b.coordination, "event", fail)
    with pytest.raises(RuntimeError):
        materialize(b, frozen)
    root = fx.state_dir / "integrations" / frozen["integration_id"]
    assert root.is_dir()
    assert b.integrations.status(frozen["integration_id"])["phase"] == "FROZEN"
    commit = git(["rev-parse", "HEAD"], cwd=root).stdout
    edited = root / ("tagnorm/normalize.py" if dirty == "hidden" else "keep.txt")
    if dirty == "hidden":
        git(["update-index", "--assume-unchanged", "--", "tagnorm/normalize.py"], cwd=root)
    if dirty != "none":
        edited.write_text("user edit")
    monkeypatch.setattr(b.coordination, "event", event)
    if dirty != "none":
        with pytest.raises(BridgeError, match="refusing adoption"):
            materialize(b, frozen)
        assert edited.read_text() == "user edit"
        assert b.integrations.status(frozen["integration_id"])["phase"] == "FROZEN"
    else:
        assert materialize(b, frozen)["phase"] == "CANDIDATE"
    assert git(["rev-parse", "HEAD"], cwd=root).stdout == commit
    b.close()


@pytest.mark.parametrize("change", ["dirty", "head", "missing", "foreign", "hidden"])
def test_replay_never_overwrites_or_recreates_changed_candidate(fx: Fixture, change: str) -> None:
    b, g, task = one(fx)
    frozen = freeze(b, g, fx, task)
    ready = materialize(b, frozen)
    root = Path(ready["workspace"]["path"])
    if change == "missing":
        git(["worktree", "remove", "--", str(root)], cwd=fx.repo)
    else:
        (root / "keep.txt").write_text("keep")
        if change == "hidden":
            (root / "keep.txt").unlink()
            git(["update-index", "--assume-unchanged", "--", "tagnorm/normalize.py"], cwd=root)
            (root / "tagnorm/normalize.py").write_text("hidden edit")
        if change == "head":
            git(["add", "--", "keep.txt"], cwd=root)
            git(["commit", "-qm", "candidate user commit"], cwd=root)
        if change == "foreign":
            git(["checkout", "-qb", "user-branch"], cwd=root)
    replay = materialize(b, frozen)
    assert replay["replayed"]
    assert (
        replay["workspace_status"]
        == {
            "dirty": "changed",
            "head": "changed",
            "missing": "missing",
            "foreign": "foreign",
            "hidden": "changed",
        }[change]
    )
    if change == "hidden":
        assert (root / "tagnorm/normalize.py").read_text() == "hidden edit"
    elif change != "missing":
        assert (root / "keep.txt").read_text() == "keep"
    else:
        assert not root.exists()
    b.close()


def test_same_key_freeze_and_materialization_races_have_one_receipt(fx: Fixture) -> None:
    b, g, task = one(fx)
    claim = b.advisor_claim

    def race(operation: str) -> list[dict[str, Any]]:
        barrier = Barrier(2)

        def run(_: int) -> dict[str, Any]:
            peer = Bridge(fx.state_dir, advisor_claim=claim)
            barrier.wait(timeout=10)
            try:
                if operation == "freeze":
                    return freeze(peer, g, fx, task)
                return materialize(peer, frozen)
            finally:
                peer.close()

        with ThreadPoolExecutor(2) as pool:
            return list(pool.map(run, [1, 2]))

    results = race("freeze")
    assert results[0]["integration_id"] == results[1]["integration_id"]
    assert sorted(r["replayed"] for r in results) == [False, True]
    frozen = results[0]
    results = race("materialize")
    assert results[0]["result"] == results[1]["result"]
    assert sorted(r["replayed"] for r in results) == [False, True]
    events = b.coordination.status(g["goal_id"])["recent_events"]
    assert len([e for e in events if e["type"] == "integration_frozen"]) == 1
    assert len([e for e in events if e["type"] == "integration_materialized"]) == 1
    b.close()


def test_merge_driver_refused_and_no_verifier_or_model_started(fx: Fixture) -> None:
    b, g, task = one(fx)
    marker = fx.base / "must-not-run"
    data = request(fx, task)
    data["verification"][0]["argv"] = [
        sys.executable,
        "-c",
        f"from pathlib import Path; Path({str(marker)!r}).touch()",
    ]
    before = b.coordination.status(g["goal_id"])["budget"]
    frozen = b.integrations.freeze(g["goal_id"], data, "integration")
    git(["config", "merge.custom.driver", f"touch {marker}"], cwd=fx.repo)
    with pytest.raises(BridgeError) as err:
        materialize(b, frozen)
    assert err.value.code == "PREFLIGHT_FAILED" and not marker.exists()
    git(["config", "--unset", "merge.custom.driver"], cwd=fx.repo)
    assert materialize(b, frozen)["verification_status"] == "not_run"
    assert b.coordination.status(g["goal_id"])["budget"] == before
    assert not marker.exists()
    data["verification"][0]["timeout_seconds"] += 1
    with pytest.raises(BridgeError) as err:
        b.integrations.freeze(g["goal_id"], data, "integration")
    assert err.value.code == "IDEMPOTENCY_CONFLICT"
    b.close()


def test_cli_fresh_process_freeze_read_materialize_and_replay(fx: Fixture) -> None:
    b, g, task = one(fx)
    claim = b.advisor_claim
    assert claim is not None
    file = fx.base / "integration.json"
    file.write_text(json.dumps(request(fx, task)))
    args = ["--advisor-binding", claim.binding_id, "--advisor-epoch", str(claim.epoch)]
    b.close()
    _, result = fx.cli(
        "goal",
        "integrate",
        g["goal_id"],
        "--file",
        str(file),
        "--idempotency-key",
        "candidate",
        *args,
    )
    frozen = result
    _, result = fx.cli("integration", "status", frozen["integration_id"])
    assert result["phase"] == "FROZEN"
    assert not (fx.state_dir / "integrations").exists()
    _, result = fx.cli("integration", "materialize", frozen["integration_id"], *args)
    assert result["phase"] == "CANDIDATE"
    _, result = fx.cli("integration", "materialize", frozen["integration_id"], *args)
    assert result["replayed"]


def test_v6_upgrade_preserves_worker_history_and_goal_budget(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "task", goal_id=g["goal_id"])["task_id"]
    job = b.run(task, background=True, idempotency_key="worker")
    assert finished(b, job["job_id"])["state"] == "AWAITING_REVIEW"
    b.review(task, review_for(b.artifacts(task), "approve", "approved"))
    worker = b.jobs.status(job["job_id"])
    before = b.coordination.status(g["goal_id"])
    attempt = b.store.get_attempt(b.store.get_task(task).current_attempt_id)
    path = b.store.db_path
    b.close()
    with sqlite3.connect(path) as old:
        old.execute("DROP TABLE cleanup_requests")
        old.execute("DROP TABLE deliveries")
        old.execute("DROP TABLE integration_reviews")
        old.execute("DROP TABLE integration_verifications")
        old.execute("DROP TABLE integrations")
        old.execute("UPDATE meta SET value='6' WHERE key='schema_revision'")
    b = Bridge(fx.state_dir)
    assert b.coordination.status(g["goal_id"]) == before
    assert b.store.get_attempt(attempt.attempt_id) == attempt
    assert b.jobs.status(job["job_id"]) == worker
    backup = next((fx.state_dir / "backups").glob(f"pre-v{SCHEMA_REVISION}-*.sqlite3"))
    with sqlite3.connect(backup) as saved:
        assert saved.execute("SELECT value FROM meta").fetchone()[0] == "6"
        assert saved.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1
        assert saved.execute("SELECT count(*) FROM worker_jobs").fetchone()[0] == 1
        assert (
            saved.execute("SELECT name FROM sqlite_master WHERE name='integrations'").fetchone()
            is None
        )
    b.close()


@pytest.mark.parametrize(
    "override",
    [
        {"task_ids": []},
        {"task_ids": ["a", "a"]},
        {"task_ids": [""]},
        {"verification": []},
        {"schema_version": "2.0"},
        {"extra": True},
    ],
)
def test_invalid_integration_contract(override: dict[str, Any]) -> None:
    data = {
        "schema_version": "1.0",
        "task_ids": ["a"],
        "verification": [
            {"id": "accept", "argv": ["true"], "timeout_seconds": 1, "trust": "external-acceptance"}
        ],
        **override,
    }
    with pytest.raises(BridgeError) as err:
        parse_contract(IntegrationSpec, data)
    assert err.value.code == "INVALID_INPUT"


@pytest.mark.parametrize("parent", [False, True])
def test_materialization_does_not_follow_workspace_symlinks(fx: Fixture, parent: bool) -> None:
    b, g, task = one(fx)
    frozen = freeze(b, g, fx, task)
    destination = fx.base / "not-our-workspace"
    destination.mkdir()
    (destination / "keep").write_text("preserve")
    root = fx.state_dir / "integrations"
    if parent:
        root.symlink_to(destination, target_is_directory=True)
    else:
        root.mkdir()
        (root / frozen["integration_id"]).symlink_to(destination, target_is_directory=True)
    with pytest.raises(BridgeError, match="symlink"):
        materialize(b, frozen)
    assert (destination / "keep").read_text() == "preserve"
    assert list(destination.iterdir()) == [destination / "keep"]
    b.close()


def test_existing_branch_is_never_overwritten_to_create_candidate(fx: Fixture) -> None:
    b, g, task = one(fx)
    frozen = freeze(b, g, fx, task)
    branch = f"hbridge/integration/{frozen['integration_id']}"
    git(["branch", branch, g["base_sha"]], cwd=fx.repo)
    with pytest.raises(BridgeError):
        materialize(b, frozen)
    assert git(["rev-parse", branch], cwd=fx.repo).stdout.decode().strip() == g["base_sha"]
    assert b.integrations.status(frozen["integration_id"])["phase"] == "FROZEN"
    b.close()


def test_changed_repo_identity_refuses_even_when_approved_refs_match(fx: Fixture) -> None:
    b, g, task = one(fx)
    frozen = freeze(b, g, fx, task)
    original = fx.base / "moved-repo"
    fx.repo.rename(original)
    git(["clone", "--mirror", "--no-hardlinks", str(original), str(fx.repo / ".git")], cwd=fx.base)
    # The same Git objects/private refs do not establish the original registered identity.
    git(["config", "core.bare", "false"], cwd=fx.repo)
    # A relocated original common dir has the same spelling here; bind a different actual dir.
    alternate = fx.base / "replacement-git"
    (fx.repo / ".git").rename(alternate)
    (fx.repo / ".git").write_text(f"gitdir: {alternate}\n")
    with pytest.raises(BridgeError) as err:
        materialize(b, frozen)
    assert err.value.code == "INTEGRITY_ERROR"
    assert not (fx.state_dir / "integrations").exists()
    b.close()


def test_process_exit_after_git_materialization_rolls_back_db_and_reuses_candidate(
    fx: Fixture,
) -> None:
    b, g, task = one(fx)
    frozen = freeze(b, g, fx, task)
    claim = b.advisor_claim
    assert claim is not None
    b.close()
    code = """
import os, sys
from pathlib import Path
from harness_bridge.service import Bridge
from harness_bridge.coordination import AdvisorClaim
claim = AdvisorClaim(binding_id=sys.argv[3], epoch=int(sys.argv[4]))
b = Bridge(Path(sys.argv[1]), advisor_claim=claim)
def crash(*args, **kwargs):
    os._exit(70)
b.coordination.event = crash
b.integrations.materialize(sys.argv[2])
"""
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(fx.state_dir),
            frozen["integration_id"],
            claim.binding_id,
            str(claim.epoch),
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 70, child.stderr
    b = Bridge(fx.state_dir, advisor_claim=claim)
    assert b.integrations.status(frozen["integration_id"])["phase"] == "FROZEN"
    root = fx.state_dir / "integrations" / frozen["integration_id"]
    commit = git(["rev-parse", "HEAD"], cwd=root).stdout.decode().strip()
    ready = materialize(b, frozen)
    assert ready["phase"] == "CANDIDATE" and ready["result"]["commit_sha"] == commit
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 1
    b.close()


@pytest.mark.parametrize("invalid", ["duplicate", "all_optional"])
def test_frozen_checks_must_have_unique_ids_and_a_required_check(invalid: str) -> None:
    check = {"id": "accept", "argv": ["true"], "timeout_seconds": 1, "trust": "external-acceptance"}
    checks = [check, check] if invalid == "duplicate" else [{**check, "required": False}]
    with pytest.raises(BridgeError):
        parse_contract(
            IntegrationSpec, {"schema_version": "1.0", "task_ids": ["a"], "verification": checks}
        )
