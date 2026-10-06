"""Goal coordination using isolated repositories and real fake-executor subprocesses."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest

from harness_bridge.adapters.fake import FakeExecutorAdapter
from harness_bridge.coordination import AdvisorClaim
from harness_bridge.errors import BridgeError
from harness_bridge.service import Bridge
from tests.conftest import Fixture
from tests.helpers.reviews import review_for


def goal_spec(fx: Fixture, **overrides: Any) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "objective": "Implement normalization",
        "repo": fx.spec()["repo"],
        "advisor": {"host": "codex", "native_session_ref": "chat-a"},
        "acceptance": ["The final integrated candidate must pass the external normalization suite"],
        **overrides,
    }


def setup_goal(fx: Fixture, **overrides: Any) -> tuple[Bridge, dict[str, Any]]:
    b = fx.bridge()
    goal = b.coordination.create(goal_spec(fx, **overrides), "goal")
    b.advisor_claim = AdvisorClaim.model_validate(goal["advisor_claim"])
    return b, goal


def takeover(
    b: Bridge, goal: dict[str, Any], epoch: int = 1, key: str = "takeover"
) -> dict[str, Any]:
    return b.coordination.takeover(
        goal["goal_id"],
        {
            "advisor": {"host": "zcode", "native_session_ref": "chat-b"},
            "expected_epoch": epoch,
            "reason": "Continue in another existing agent session",
        },
        key,
    )


def test_goal_two_children_and_takeover_preserve_workspaces(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    assert b.coordination.status(g["goal_id"])["state"] == "DRAFT"
    a = b.create(fx.spec(), "a", goal_id=g["goal_id"])
    c = b.create(fx.spec(), "c", goal_id=g["goal_id"])
    assert a["goal_id"] == c["goal_id"] == g["goal_id"]
    assert a["worktree"] != c["worktree"]
    assert a["base_sha"] == c["base_sha"] == g["base_sha"]
    assert b.coordination.status(g["goal_id"])["state"] == "ACTIVE"
    b.run(a["task_id"])
    assert b.coordination.status(g["goal_id"])["state"] == "NEEDS_ATTENTION"
    claim = takeover(b, g)["advisor_claim"]
    b.close()
    new = Bridge(fx.state_dir, advisor_claim=AdvisorClaim.model_validate(claim))
    new.review(a["task_id"], review_for(new.artifacts(a["task_id"]), "approve", "a-ok"))
    assert new.run(c["task_id"])["verification_status"] == "passed"
    new.review(c["task_id"], review_for(new.artifacts(c["task_id"]), "approve", "c-ok"))
    status = new.coordination.status(g["goal_id"])
    assert status["state"] == "ACTIVE"  # child approvals do not imply integrated delivery
    assert status["delivery"] == "not_implemented"
    assert status["budget"]["attempts"] == 2
    assert [t["worktree_path"] for t in status["children"]] == [a["worktree"], c["worktree"]]
    assert new.coordination.projects()["projects"][0]["goal_ids"] == [g["goal_id"]]
    new.close()


@pytest.mark.parametrize("action", ["create", "run", "review", "verify", "recover"])
@pytest.mark.parametrize("missing_claim", [False, True])
def test_legacy_entrypoints_cannot_bypass_advisor(
    fx: Fixture, action: str, missing_claim: bool
) -> None:
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    takeover(b, g)
    if missing_claim:
        b.advisor_claim = None
    before = b.store.get_task(task)
    events_before = b.coordination.status(g["goal_id"])["recent_events"]
    with pytest.raises(BridgeError) as err:
        if action == "create":
            b.create(fx.spec(), "b", goal_id=g["goal_id"])
        elif action == "review":
            b.review(task, {})  # rejected before parsing untrusted review
        else:
            getattr(b, action)(task)
    assert err.value.code == ("ADVISOR_REQUIRED" if missing_claim else "STALE_ADVISOR")
    assert b.store.get_task(task) == before
    assert len(b.store.list_tasks()) == 1
    assert b.coordination.status(g["goal_id"])["recent_events"] == events_before
    assert b.status(task)["state"] == "READY"  # read and emergency cancel remain available
    assert b.cancel(task)["state"] == "CANCELLED"
    b.close()


def test_idempotency_does_not_reassign_task_or_refresh_old_binding(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])
    with pytest.raises(BridgeError, match="different goal"):
        b.create(fx.spec(), "a")
    second = b.coordination.create(goal_spec(fx), "second")
    b.advisor_claim = AdvisorClaim.model_validate(second["advisor_claim"])
    with pytest.raises(BridgeError) as err:
        b.create(fx.spec(), "a", goal_id=second["goal_id"])
    assert err.value.code == "STALE_ADVISOR"
    taken = takeover(b, g)
    assert takeover(b, g) == {**taken, "replayed": True}
    replay = b.coordination.create(goal_spec(fx), "goal")
    assert replay["advisor_claim"] == g["advisor_claim"]
    b.advisor_claim = AdvisorClaim.model_validate(taken["advisor_claim"])
    assert b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"] == task["task_id"]
    takeover(b, g, epoch=2, key="later")
    assert takeover(b, g)["advisor_claim"] == taken["advisor_claim"]
    assert b.coordination.status(g["goal_id"])["advisor_claim"]["epoch"] == 3
    b.close()


def test_takeover_race_has_one_winner(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    barrier = Barrier(2)

    def compete(key: str) -> str:
        peer = fx.bridge()
        try:
            barrier.wait(timeout=10)
            takeover(peer, g, key=key)
            return "accepted"
        except BridgeError as exc:
            return exc.code
        finally:
            peer.close()

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(compete, ["x", "y"])) == ["STALE_ADVISOR", "accepted"]
    events = b.coordination.status(g["goal_id"])["recent_events"]
    assert sum(e["type"] == "advisor_taken_over" for e in events) == 1
    b.close()


def test_takeover_during_dispatch_preparation_prevents_spawn(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    original = FakeExecutorAdapter.build_invocation

    def intercept(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        other = fx.bridge()
        takeover(other, g)
        other.close()
        return result

    monkeypatch.setattr(FakeExecutorAdapter, "build_invocation", intercept)
    with pytest.raises(BridgeError) as err:
        b.run(task)
    assert err.value.code == "STALE_ADVISOR"
    assert b.store.list_attempts(task) == []
    assert b.status(task)["state"] == "READY"
    b.close()


def test_takeover_during_review_snapshot_prevents_approval(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    b.run(task)
    review = review_for(b.artifacts(task), "approve", "review")
    original = b.current_fingerprint

    def intercept(*args: Any) -> str:
        result = original(*args)
        peer = fx.bridge()
        takeover(peer, g)
        peer.close()
        return result

    monkeypatch.setattr(b, "current_fingerprint", intercept)
    with pytest.raises(BridgeError) as err:
        b.review(task, review)
    assert err.value.code == "STALE_ADVISOR"
    assert b.store.list_reviews(task) == []
    assert b.store.get_task(task).state == "AWAITING_REVIEW"
    b.close()


def test_goal_budget_race_reserves_once(fx: Fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    b, g = setup_goal(fx, max_attempts=1)
    tasks = [b.create(fx.spec(), k, goal_id=g["goal_id"])["task_id"] for k in ("a", "b")]
    original = FakeExecutorAdapter.build_invocation
    barrier = Barrier(2)

    def synchronize(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(FakeExecutorAdapter, "build_invocation", synchronize)

    def dispatch(task: str) -> str:
        peer = Bridge(fx.state_dir, advisor_claim=b.advisor_claim)
        try:
            return str(peer.run(task)["state"])
        except BridgeError as exc:
            return exc.code
        finally:
            peer.close()

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(dispatch, tasks)) == ["AWAITING_REVIEW", "BUDGET_EXHAUSTED"]
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 1
    assert sum(len(b.store.list_attempts(t)) for t in tasks) == 1
    b.close()


def test_aggregate_repair_budget_and_legacy_task_compatibility(fx: Fixture) -> None:
    b, g = setup_goal(fx, max_repairs=0)
    task = b.create(fx.spec("bug-then-repair"), "a", goal_id=g["goal_id"])["task_id"]
    b.run(task)
    b.review(task, review_for(b.artifacts(task), "changes_requested", "fix"))
    with pytest.raises(BridgeError) as err:
        b.run(task)
    assert err.value.code == "BUDGET_EXHAUSTED"
    assert len(b.store.list_attempts(task)) == 1
    b.advisor_claim = None
    legacy = b.create(fx.spec(), "legacy")
    assert legacy["goal_id"] is None
    assert b.run(legacy["task_id"])["verification_status"] == "passed"
    b.close()


def test_cli_goal_claim_and_project_discovery(fx: Fixture) -> None:
    goal_file = fx.base / "goal.json"
    goal_file.write_text(json.dumps(goal_spec(fx)))
    _, g = fx.cli("goal", "create", "--file", str(goal_file), "--idempotency-key", "g")
    task_file = fx.base / "task.json"
    task_file.write_text(json.dumps(fx.spec()))
    claim = g["advisor_claim"]
    _, task = fx.cli(
        "create",
        "--task",
        str(task_file),
        "--idempotency-key",
        "a",
        "--goal",
        g["goal_id"],
        "--advisor-binding",
        claim["binding_id"],
        "--advisor-epoch",
        str(claim["epoch"]),
    )
    code, err = fx.cli("run", task["task_id"], check_ok=False)
    assert code == 3 and err["error"]["code"] == "ADVISOR_REQUIRED"
    _, projects = fx.cli("projects")
    assert projects["state_dir"] == str(fx.state_dir)
    assert projects["projects"][0]["goal_ids"] == [g["goal_id"]]
    _, status = fx.cli("goal", "status", g["goal_id"])
    assert status["children"][0]["task_id"] == task["task_id"]


@pytest.mark.parametrize("change", ["repo", "executor", "base"])
def test_child_must_match_goal_context(fx: Fixture, change: str) -> None:
    b, g = setup_goal(fx)
    spec = fx.spec()
    if change == "repo":
        other = Fixture(fx.base / "other")
        spec = other.spec()
    elif change == "executor":
        spec["executor"] = {"kind": "claude-code"}
    else:
        from harness_bridge.workspace import git

        git(
            [
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "advance",
            ],
            cwd=fx.repo,
        )
    with pytest.raises(BridgeError) as err:
        b.create(spec, "bad", goal_id=g["goal_id"])
    assert err.value.code == "INVALID_INPUT"
    assert b.store.list_tasks() == []
    assert b.coordination.status(g["goal_id"])["children"] == []
    b.close()


def test_unknown_exit_keeps_project_slot_after_cancel(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    assert b.advisor_claim is not None
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
    assert b.recover(task)["state_after"] == "INTERRUPTED"
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 1
    b.cancel(task, acknowledge_unknown=True)
    # Even a different goal in the same project must not assume the old process exited.
    second = b.coordination.create(goal_spec(fx), "other-goal")
    b.advisor_claim = AdvisorClaim.model_validate(second["advisor_claim"])
    other = b.create(fx.spec(), "b", goal_id=second["goal_id"])["task_id"]
    with pytest.raises(BridgeError) as err:
        b.run(other)
    assert err.value.code == "STATE_CONFLICT"
    assert err.value.details["occupied_tasks"] == [task]
    assert b.store.list_attempts(other) == []
    b.close()


def test_accepted_attempt_can_finish_after_takeover(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness_bridge.service as service

    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    original = service._fault_point

    def after_reservation(name: str) -> None:
        if name == "after_starting_commit":
            peer = fx.bridge()
            takeover(peer, g)
            peer.close()
        original(name)

    monkeypatch.setattr(service, "_fault_point", after_reservation)
    assert b.run(task)["verification_status"] == "passed"
    assert b.coordination.status(g["goal_id"])["advisor_claim"]["epoch"] == 2
    with pytest.raises(BridgeError) as err:
        b.review(task, review_for(b.artifacts(task), "approve", "stale"))
    assert err.value.code == "STALE_ADVISOR"
    assert len(b.store.list_attempts(task)) == 1
    b.close()


def test_confirmed_spawn_failure_refunds_goal_budget(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    b, g = setup_goal(fx, max_attempts=1)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    original = FakeExecutorAdapter.build_invocation

    def missing_binary(*args: Any, **kwargs: Any) -> Any:
        invocation = original(*args, **kwargs)
        return replace(invocation, argv=[str(fx.base / "nonexistent-executor")])

    monkeypatch.setattr(FakeExecutorAdapter, "build_invocation", missing_binary)
    assert b.run(task)["executor_outcome"] == "spawn_failed"
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 0
    monkeypatch.setattr(FakeExecutorAdapter, "build_invocation", original)
    other = b.create(fx.spec(), "b", goal_id=g["goal_id"])["task_id"]
    assert b.run(other)["verification_status"] == "passed"
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 1
    b.close()
