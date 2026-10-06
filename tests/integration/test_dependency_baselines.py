"""Real local Git/worktrees with simulated executors; no model calls or user state."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from harness_bridge.adapters.base import InvocationContext, TaskPacket
from harness_bridge.adapters.fake import FakeExecutorAdapter
from harness_bridge.baselines import approved
from harness_bridge.coordination import AdvisorClaim
from harness_bridge.errors import BridgeError
from harness_bridge.service import Bridge
from harness_bridge.workspace import checkout_fingerprint, git
from tests.conftest import Fixture
from tests.helpers.reviews import review_for
from tests.integration.test_coordination import setup_goal, takeover
from tests.integration.test_goal_planning import plan, submit


def children(b: Bridge, g: dict[str, Any], *plans: dict[str, Any]) -> dict[str, str]:
    return {p["key"]: p["child_id"] for p in submit(b, g, *plans)["children"]}


def approve(b: Bridge, child: str, files: dict[str, str] | None = None) -> str:
    task = b.materialize(child)["task_id"]
    b.run(task)
    if files:
        root = Path(b.store.get_task(task).worktree_path)
        for path, value in files.items():
            (root / path).write_text(value)
        b.verify(task)
    b.review(task, review_for(b.artifacts(task), "approve", "approval"))
    return task


def test_dependency_uses_retained_tree_after_parent_workspace_changes_and_gc(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    source = checkout_fingerprint(str(fx.repo))
    ids = children(b, g, plan(fx, "a"), plan(fx, "b", "a"))
    a = approve(b, ids["a"])
    root = Path(b.store.get_task(a).worktree_path)
    content = (root / "tagnorm/normalize.py").read_bytes()
    (root / "tagnorm/normalize.py").write_text("# changed after approval\n")
    git(["gc", "--prune=now"], cwd=fx.repo)
    child = b.materialize(ids["b"])
    assert (Path(child["worktree"]) / "tagnorm/normalize.py").read_bytes() == content
    with b.store.transaction() as cur:
        record = approved(cur, a)
    baseline = b.plans.status(ids["b"])["baseline"]
    assert baseline["inputs"][0]["fingerprint"] == record["fingerprint"]
    assert baseline["inputs"][0]["review_id"] == record["review_id"]
    assert child["base_sha"] != g["base_sha"]
    assert checkout_fingerprint(str(fx.repo)) == source
    b.close()


def test_diamond_dependencies_preserve_descendant_edits_and_disjoint_changes(fx: Fixture) -> None:
    b, g = setup_goal(fx, max_attempts=5)
    ids = children(
        b, g, plan(fx, "a"), plan(fx, "b", "a"), plan(fx, "c", "a"), plan(fx, "d", "a", "b", "c")
    )
    approve(b, ids["a"], {"tagnorm/a.txt": "first\n"})
    approve(b, ids["b"], {"tagnorm/a.txt": "updated\n", "tagnorm/b.txt": "b\n"})
    approve(b, ids["c"], {"tagnorm/c.txt": "c\n"})
    d = b.materialize(ids["d"])
    root = Path(d["worktree"])
    assert (root / "tagnorm/a.txt").read_text() == "updated\n"
    assert (root / "tagnorm/b.txt").read_text() == "b\n"
    assert (root / "tagnorm/c.txt").read_text() == "c\n"
    claim = b.advisor_claim
    b.close()
    b = Bridge(fx.state_dir, advisor_claim=claim)
    assert b.materialize(ids["d"])["task_id"] == d["task_id"]
    assert b.materialize(ids["d"])["base_sha"] == d["base_sha"]
    goal = b.coordination.status(g["goal_id"])
    assert goal["delivery"]["status"] == "not_ready" and goal["state"] == "ACTIVE"
    b.close()


def test_conflicting_approvals_are_persisted_without_task_or_workspace(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b"), plan(fx, "c", "a", "b"))
    approve(b, ids["a"], {"tagnorm/shared.txt": "a\n"})
    approve(b, ids["b"], {"tagnorm/shared.txt": "b\n"})
    for _ in range(2):
        with pytest.raises(BridgeError) as err:
            b.materialize(ids["c"])
        assert err.value.code == "STATE_CONFLICT"
        assert b.plans.status(ids["c"])["state"] == "BASELINE_CONFLICT"
    assert b.coordination.status(g["goal_id"])["state"] == "NEEDS_ATTENTION"
    assert len(b.store.list_tasks()) == len(list(b.worktrees_dir.iterdir())) == 2
    assert (
        len(
            [
                e
                for e in b.coordination.status(g["goal_id"])["recent_events"]
                if e["type"] == "child_baseline_frozen" and e["payload"]["child_id"] == ids["c"]
            ]
        )
        == 1
    )
    b.close()


def test_custom_merge_driver_is_never_executed(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b", "a"))
    approve(b, ids["a"])
    marker = fx.base / "driver-ran"
    git(["config", "merge.custom.driver", f"touch {marker}"], cwd=fx.repo)
    with pytest.raises(BridgeError) as err:
        b.materialize(ids["b"])
    assert err.value.code == "PREFLIGHT_FAILED"
    assert not marker.exists() and len(b.store.list_tasks()) == 1
    b.close()


@pytest.mark.parametrize("target", ["approval", "baseline"])
def test_missing_git_pins_fail_closed(fx: Fixture, target: str) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b", "a"))
    a = approve(b, ids["a"])
    if target == "approval":
        with b.store.transaction() as cur:
            record = approved(cur, a)
    else:
        b.materialize(ids["b"])
        record = b.plans.status(ids["b"])["baseline"]
    git(["update-ref", "-d", record["ref"]], cwd=fx.repo)
    with pytest.raises(BridgeError) as err:
        b.materialize(ids["b"])
    assert err.value.code == "INTEGRITY_ERROR"
    b.close()


def test_concurrent_dependency_materialization_has_one_baseline_and_task(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b", "a"))
    approve(b, ids["a"])
    claim = b.advisor_claim
    barrier = Barrier(2)

    def materialize(_: int) -> dict[str, Any]:
        peer = Bridge(fx.state_dir, advisor_claim=claim)
        barrier.wait(timeout=10)
        try:
            return peer.materialize(ids["b"])
        finally:
            peer.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(materialize, [1, 2]))
    assert results[0]["task_id"] == results[1]["task_id"]
    assert results[0]["base_sha"] == results[1]["base_sha"]
    assert len(b.store.list_tasks()) == 2
    b.close()


def test_pin_created_before_db_failure_is_reused_without_false_approval(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"))
    task = b.materialize(ids["a"])["task_id"]
    b.run(task)
    review = review_for(b.artifacts(task), "approve", "approval")
    transition = b.store.transition

    def fail(*args: Any, **kw: Any) -> Any:
        raise RuntimeError("crash after Git pin, before database commit")

    monkeypatch.setattr(b.store, "transition", fail)
    with pytest.raises(RuntimeError):
        b.review(task, review)
    assert b.status(task)["state"] == "AWAITING_REVIEW"
    with b.store.transaction() as cur:
        assert approved(cur, task) is None
    refs = git(
        ["for-each-ref", "--format=%(objectname)", "refs/hbridge/approved"], cwd=fx.repo
    ).stdout
    assert refs
    monkeypatch.setattr(b.store, "transition", transition)
    b.review(task, review)
    assert b.status(task)["state"] == "SUCCEEDED"
    assert (
        git(["for-each-ref", "--format=%(objectname)", "refs/hbridge/approved"], cwd=fx.repo).stdout
        == refs
    )
    b.close()


@pytest.mark.parametrize("changed", [False, True])
def test_legacy_approval_requires_explicit_retention_and_unchanged_candidate(
    fx: Fixture, changed: bool
) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b", "a"))
    a = approve(b, ids["a"])
    with b.store.transaction() as cur:
        cur.execute("DELETE FROM approved_snapshots WHERE task_id=?", (a,))
    assert b.plans.status(ids["b"])["state"] == "WAITING_BASELINE"
    with pytest.raises(BridgeError):
        b.materialize(ids["b"])
    if changed:
        (Path(b.store.get_task(a).worktree_path) / "tagnorm/normalize.py").write_text("changed\n")
        with pytest.raises(BridgeError) as err:
            b.retain_approved(a)
        assert err.value.code == "STALE_REVIEW"
    else:
        _, receipt = fx.cli(
            "retain-approved",
            a,
            "--advisor-binding",
            b.advisor_claim.binding_id,
            "--advisor-epoch",
            str(b.advisor_claim.epoch),
        )
        record = {k: v for k, v in receipt.items() if k != "ok"}
        assert b.retain_approved(a) == record
        assert b.status(a)["approved_snapshot"] == record
        assert b.materialize(ids["b"])["base_sha"] != g["base_sha"]
    b.close()


@pytest.mark.parametrize("target", ["approved_snapshots", "child_baselines"])
def test_retained_record_tampering_is_detected(fx: Fixture, target: str) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b", "a"))
    approve(b, ids["a"])
    if target == "child_baselines":
        b.materialize(ids["b"])
    with b.store.transaction() as cur:
        cur.execute(
            {
                "approved_snapshots": "UPDATE approved_snapshots SET record_json='{}'",
                "child_baselines": "UPDATE child_baselines SET record_json='{}'",
            }[target]
        )
    with pytest.raises(BridgeError) as err:
        b.materialize(ids["b"])
    assert err.value.code == "INTEGRITY_ERROR"
    b.close()


def test_context_reaches_executor_and_old_create_cannot_choose_dependency_base(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b", "a"))
    a = approve(b, ids["a"])
    child = b.materialize(ids["b"])
    spec = fx.spec()
    spec["repo"]["base_ref"] = child["base_sha"]
    with pytest.raises(BridgeError):
        b.create(spec, "bypass", goal_id=g["goal_id"])
    packets = []
    build = FakeExecutorAdapter.build_invocation

    def capture(self: FakeExecutorAdapter, packet: TaskPacket, ctx: InvocationContext) -> Any:
        packets.append(packet)
        assert ctx.worktree == child["worktree"]
        return build(self, packet, ctx)

    monkeypatch.setattr(FakeExecutorAdapter, "build_invocation", capture)
    b.run(child["task_id"])
    context = packets[0].context
    assert context["goal_id"] == g["goal_id"] and context["child_id"] == ids["b"]
    assert context["base_sha"] == child["base_sha"]
    assert context["dependencies"][0]["task_id"] == a
    assert a in packets[0].render_prompt()  # Claude uses this rendered text, not JSON stdin.
    assert json.loads(packets[0].to_json_bytes())["context"] == context
    b.close()


def test_upgrade_v3_preserves_materialized_plan_and_batch_replay(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    p = plan(fx, "a")
    batch = submit(b, g, p)
    child = batch["children"][0]["child_id"]
    task = b.materialize(child)["task_id"]
    claim = b.advisor_claim
    path = b.store.db_path
    b.close()
    with sqlite3.connect(path) as old:
        old.execute("DROP TABLE deliveries")
        old.execute("DROP TABLE integration_reviews")
        old.execute("DROP TABLE integration_verifications")
        old.execute("DROP TABLE integrations")
        old.execute("DROP TABLE worker_jobs")
        old.execute("DROP TABLE preparation_resources")
        old.execute("DROP TABLE preparation_runs")
        old.execute("DROP TABLE approved_snapshots")
        old.execute("DROP TABLE child_baselines")
        old.execute("UPDATE meta SET value='3' WHERE key='schema_revision'")
    b = Bridge(fx.state_dir, advisor_claim=claim)
    assert submit(b, g, p) == {**batch, "replayed": True}
    assert b.child_preflight(child)["ready"]
    assert b.materialize(child)["task_id"] == task
    assert list((fx.state_dir / "backups").glob("pre-v*-*.sqlite3"))
    b.close()


def test_stale_advisor_cannot_retain_or_materialize(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b", "a"))
    a = approve(b, ids["a"])
    new = takeover(b, g)
    with pytest.raises(BridgeError):
        b.retain_approved(a)
    with pytest.raises(BridgeError):
        b.materialize(ids["b"])
    assert b.plans.status(ids["b"])["baseline"] is None
    b.advisor_claim = AdvisorClaim.model_validate(new["advisor_claim"])
    assert b.materialize(ids["b"])["task_id"]
    b.close()
