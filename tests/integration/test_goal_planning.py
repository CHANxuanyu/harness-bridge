"""Planning/control contracts: no implicit execution, premature workspaces or false stops."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from harness_bridge.adapters.fake import FakeExecutorAdapter
from harness_bridge.errors import BridgeError
from harness_bridge.service import Bridge
from tests.conftest import Fixture
from tests.helpers.reviews import review_for
from tests.integration.test_coordination import goal_spec, setup_goal, takeover
from tests.integration.test_recovery import spawn_cli, wait_for, wait_steady


def plan(fx: Fixture, key: str, *deps: str) -> dict[str, Any]:
    return {
        "key": key,
        "depends_on": list(deps),
        "task": {k: v for k, v in fx.spec().items() if k not in ("schema_version", "repo")},
    }


def submit(
    b: Bridge, g: dict[str, Any], *plans: dict[str, Any], key: str = "plan"
) -> dict[str, Any]:
    return b.plans.submit(
        g["goal_id"], {"schema_version": "1.0", "children": list(plans)}, key, b.advisor_claim
    )


def control(b: Bridge, g: dict[str, Any], action: str, key: str | None = None) -> dict[str, Any]:
    return b.coordination.control(
        g["goal_id"],
        {"action": action, "reason": "explicit test decision"},
        key or action,
        b.advisor_claim,
    )


def test_plan_is_durable_without_workspace_and_dependencies_never_use_old_head(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    batch = submit(b, g, plan(fx, "b", "a"), plan(fx, "a"))
    ids = {p["key"]: p["child_id"] for p in batch["children"]}
    assert b.store.list_tasks() == [] and not b.worktrees_dir.exists()
    assert submit(b, g, plan(fx, "b", "a"), plan(fx, "a"))["replayed"]
    assert len(b.coordination.status(g["goal_id"])["plans"]) == 2
    assert b.coordination.status(g["goal_id"])["state"] == "ACTIVE"
    assert b.plans.status(ids["b"])["state"] == "WAITING_DEPENDENCIES"
    with pytest.raises(BridgeError):
        b.materialize(ids["b"])
    assert not b.worktrees_dir.exists()
    root = b.materialize(ids["a"])
    assert root["base_sha"] == g["base_sha"]
    claim = b.advisor_claim
    b.close()
    b = Bridge(fx.state_dir, advisor_claim=claim)
    assert b.materialize(ids["a"])["task_id"] == root["task_id"]
    b.run(root["task_id"])
    b.review(root["task_id"], review_for(b.artifacts(root["task_id"]), "approve", "ok"))
    assert b.plans.status(ids["b"])["state"] == "READY_TO_MATERIALIZE"
    successor = b.materialize(ids["b"])
    assert successor["base_sha"] != g["base_sha"]
    a = Path(b.store.get_task(root["task_id"]).worktree_path)
    c = Path(b.store.get_task(successor["task_id"]).worktree_path)
    assert (a / "tagnorm/normalize.py").read_bytes() == (c / "tagnorm/normalize.py").read_bytes()
    assert len(b.store.list_tasks()) == len(list(b.worktrees_dir.iterdir())) == 2
    b.close()


@pytest.mark.parametrize(
    "case", ["self-cycle", "cycle", "missing", "duplicate", "duplicate-dep", "repo-in-template"]
)
def test_invalid_graph_rolls_back_whole_batch(fx: Fixture, case: str) -> None:
    b, g = setup_goal(fx)
    plans = [plan(fx, "a"), plan(fx, "b", "a")]
    if case == "self-cycle":
        plans[0]["depends_on"] = ["a"]
    elif case == "cycle":
        plans[0]["depends_on"] = ["b"]
    elif case == "missing":
        plans[0]["depends_on"] = ["another-goal-child"]
    elif case == "duplicate":
        plans[1]["key"] = "a"
    elif case == "duplicate-dep":
        plans[1]["depends_on"] = ["a", "a"]
    else:
        plans[0]["task"]["repo"] = fx.spec()["repo"]
    before = b.coordination.status(g["goal_id"])["recent_events"]
    with pytest.raises(BridgeError) as err:
        submit(b, g, *plans)
    assert err.value.code == "INVALID_INPUT"
    status = b.coordination.status(g["goal_id"])
    assert status["plans"] == [] and status["recent_events"] == before
    assert not b.worktrees_dir.exists()
    b.close()


def test_batches_extend_dag_but_cannot_rewrite_or_reuse_keys(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    submit(b, g, plan(fx, "a"))
    second = submit(b, g, plan(fx, "b", "a"), key="next")
    assert b.plans.status(second["children"][0]["child_id"])["dependencies"][0]["key"] == "a"
    with pytest.raises(BridgeError) as err:
        submit(b, g, plan(fx, "c"))
    assert err.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(BridgeError):
        submit(b, g, plan(fx, "a"), key="rewrite")
    other = b.coordination.create(goal_spec(fx), "other")
    from harness_bridge.coordination import AdvisorClaim

    b.advisor_claim = AdvisorClaim.model_validate(other["advisor_claim"])
    with pytest.raises(BridgeError):
        submit(b, other, plan(fx, "foreign", "a"))
    b.close()


@pytest.mark.parametrize("action", ["plan", "materialize", "pause", "resume", "fail"])
def test_new_mutations_require_active_advisor(fx: Fixture, action: str) -> None:
    b, g = setup_goal(fx)
    child = submit(b, g, plan(fx, "a"))["children"][0]["child_id"]
    takeover(b, g)
    with pytest.raises(BridgeError) as err:
        if action == "plan":
            submit(b, g, plan(fx, "b"), key="later")
        elif action == "materialize":
            b.materialize(child)
        else:
            control(b, g, action)
    assert err.value.code == "STALE_ADVISOR"
    assert b.plans.status(child)["task_id"] is None
    # Emergency stop is still possible from a disconnected/stale local session.
    control(b, g, "cancel")
    assert b.coordination.status(g["goal_id"])["state"] == "CANCELLED"
    b.close()


def test_pause_only_blocks_dispatch_and_replay_does_not_repause(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    child = submit(b, g, plan(fx, "a"))["children"][0]["child_id"]
    control(b, g, "pause")
    task = b.materialize(child)["task_id"]
    with pytest.raises(BridgeError, match="paused"):
        b.run(task)
    assert b.store.list_attempts(task) == []
    control(b, g, "resume")
    assert control(b, g, "pause")["replayed"]
    assert not b.coordination.status(g["goal_id"])["dispatch_paused"]
    b.run(task)
    control(b, g, "pause", key="again")
    b.review(task, review_for(b.artifacts(task), "approve", "ok"))
    assert b.store.get_task(task).state == "SUCCEEDED"
    b.close()


def test_pause_racing_dispatch_is_checked_before_reservation(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "t", goal_id=g["goal_id"])["task_id"]
    original = FakeExecutorAdapter.build_invocation

    def intercepted(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        control(b, g, "pause")
        return result

    monkeypatch.setattr(FakeExecutorAdapter, "build_invocation", intercepted)
    with pytest.raises(BridgeError, match="paused"):
        b.run(task)
    assert b.store.list_attempts(task) == []
    b.close()


@pytest.mark.parametrize("action,expected", [("cancel", "CANCELLED"), ("fail", "FAILED")])
def test_goal_termination_is_irreversible_and_cancels_unstarted_work(
    fx: Fixture, action: str, expected: str
) -> None:
    b, g = setup_goal(fx)
    child = submit(b, g, plan(fx, "a"))["children"][0]["child_id"]
    task = b.create(fx.spec(), "t", goal_id=g["goal_id"])["task_id"]
    receipt = control(b, g, action)
    assert control(b, g, action) == {**receipt, "replayed": True}
    assert b.coordination.status(g["goal_id"])["state"] == expected
    assert b.store.get_task(task).state == b.plans.status(child)["state"] == "CANCELLED"
    for operation in [
        lambda: control(b, g, "resume"),
        lambda: b.run(task),
        lambda: b.materialize(child),
        lambda: submit(b, g, plan(fx, "b"), key="b"),
        lambda: b.create(fx.spec(), "new", goal_id=g["goal_id"]),
    ]:
        with pytest.raises(BridgeError, match="termination"):
            operation()
    b.close()


def test_unknown_exit_prevents_goal_cancelled_even_after_task_resolution(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "t", goal_id=g["goal_id"])["task_id"]
    assert b.advisor_claim
    code, _ = fx.cli(
        "run",
        task,
        "--advisor-binding",
        b.advisor_claim.binding_id,
        "--advisor-epoch",
        "1",
        env=dict(os.environ, HBRIDGE_TEST_FAULT="after_starting_commit"),
        check_ok=None,
    )
    assert code == 70
    control(b, g, "cancel")
    assert b.coordination.status(g["goal_id"])["state"] == "NEEDS_ATTENTION"
    assert b.recover(task)["state_after"] == "INTERRUPTED"
    with pytest.raises(BridgeError):
        b.recover(task, resolve="retry", acknowledge_unknown=True)
    assert b.recover(task, resolve="fail")["state_after"] == "FAILED"
    status = b.coordination.status(g["goal_id"])
    assert status["state"] == "NEEDS_ATTENTION" and status["pending_stop_tasks"] == [task]
    b.close()


def test_goal_cancel_stops_running_fake_process_before_reporting_stopped(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    task = b.create(
        fx.spec("hang", wall_timeout_seconds=30, kill_grace_seconds=0.3), "t", goal_id=g["goal_id"]
    )["task_id"]
    assert b.advisor_claim
    proc = spawn_cli(
        fx, "run", task, "--advisor-binding", b.advisor_claim.binding_id, "--advisor-epoch", "1"
    )
    try:
        running = wait_for(b.store, task, lambda t: t.state == "RUNNING")
        attempt = b.store.get_attempt(running.current_attempt_id)
        wait_steady(attempt.pgid)
        control(b, g, "pause")
        assert b.store.get_task(task).cancel_requested is False
        b.advisor_claim = None
        control(b, g, "cancel")
        stdout, stderr = proc.communicate(timeout=15)
        assert proc.returncode == 0, stderr
        assert json.loads(stdout)["executor_outcome"] == "cancelled"
        status = b.coordination.status(g["goal_id"])
        assert status["state"] == "CANCELLED" and status["pending_stop_tasks"] == []
        assert b.store.get_attempt(attempt.attempt_id).exit_confirmed
    finally:
        if proc.poll() is None:
            b.cancel(task)
            proc.communicate(timeout=15)
        b.close()


def test_concurrent_materialization_creates_one_task_and_workspace(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness_bridge.service as service

    b, g = setup_goal(fx)
    child = submit(b, g, plan(fx, "a"))["children"][0]["child_id"]
    barrier = Barrier(2)
    original = service.inspect_source_repo

    def synchronized(*args: Any) -> Any:
        value = original(*args)
        barrier.wait(timeout=10)
        return value

    monkeypatch.setattr(service, "inspect_source_repo", synchronized)

    def materialize(_: int) -> dict[str, Any]:
        peer = Bridge(fx.state_dir, advisor_claim=b.advisor_claim)
        try:
            return peer.materialize(child)
        finally:
            peer.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(materialize, [1, 2]))
    assert results[0]["task_id"] == results[1]["task_id"]
    assert sum(r["created"] for r in results) == 1
    assert len(b.store.list_tasks()) == len(list(b.worktrees_dir.iterdir())) == 1
    b.close()


def test_cancel_during_workspace_preparation_retains_workspace_ownership(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness_bridge.service as service

    b, g = setup_goal(fx)
    child = submit(b, g, plan(fx, "a"))["children"][0]["child_id"]
    original = service.create_worktree

    def intercepted(*args: Any) -> None:
        control(b, g, "cancel")
        original(*args)

    monkeypatch.setattr(service, "create_worktree", intercepted)
    task = b.materialize(child)
    assert task["state"] == "CANCELLED" and task["worktree"] is not None
    assert b.coordination.status(g["goal_id"])["state"] == "CANCELLED"
    assert b.plans.status(child)["task_id"] == task["task_id"]
    assert len(list(b.worktrees_dir.iterdir())) == 1
    b.close()


def test_cli_plan_materialize_and_emergency_cancel(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    assert b.advisor_claim
    args = ["--advisor-binding", b.advisor_claim.binding_id, "--advisor-epoch", "1"]
    batch = fx.base / "plan.json"
    batch.write_text(json.dumps({"schema_version": "1.0", "children": [plan(fx, "a")]}))
    _, receipt = fx.cli(
        "goal", "plan", g["goal_id"], "--file", str(batch), "--idempotency-key", "p", *args
    )
    child = receipt["children"][0]["child_id"]
    _, status = fx.cli("child", "status", child)
    assert status["state"] == "READY_TO_MATERIALIZE"
    _, task = fx.cli("child", "materialize", child, *args)
    stop = fx.base / "cancel.json"
    stop.write_text(json.dumps({"action": "cancel", "reason": "stop this goal"}))
    _, result = fx.cli(
        "goal", "control", g["goal_id"], "--file", str(stop), "--idempotency-key", "stop"
    )
    assert result["goal"]["state"] == "CANCELLED"
    assert b.store.get_task(task["task_id"]).state == "CANCELLED"
    b.close()


def test_interrupted_materialization_reuses_task_and_explicit_recovery(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, g = setup_goal(fx)
    child = submit(b, g, plan(fx, "a"))["children"][0]["child_id"]
    original = b._prepare_workspace

    def interrupt(_: str) -> None:
        raise RuntimeError("interrupted after task and child association commit")

    monkeypatch.setattr(b, "_prepare_workspace", interrupt)
    with pytest.raises(RuntimeError):
        b.materialize(child)
    status = b.plans.status(child)
    assert status["state"] == "CREATED" and status["task_id"]
    replay = b.materialize(child)
    assert replay["task_id"] == status["task_id"] and not replay["created"]
    assert not b.worktrees_dir.exists()
    monkeypatch.setattr(b, "_prepare_workspace", original)
    assert b.recover(status["task_id"])["state_after"] == "READY"
    assert len(b.store.list_tasks()) == len(list(b.worktrees_dir.iterdir())) == 1
    b.close()
