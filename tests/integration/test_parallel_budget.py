"""Two real fake workers, atomic ceilings, scopes and compatible historical reservations."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from harness_bridge.adapters.fake import FakeExecutorAdapter
from harness_bridge.coordination import AdvisorClaim, GoalSpec
from harness_bridge.errors import BridgeError
from harness_bridge.models import canonical_json, sha256_digest
from harness_bridge.service import Bridge
from harness_bridge.state import TaskState as S
from tests.conftest import Fixture
from tests.helpers.reviews import review_for
from tests.integration.test_coordination import goal_spec, setup_goal, takeover
from tests.integration.test_dependency_baselines import children
from tests.integration.test_goal_planning import control
from tests.integration.test_preparation import setup_plan
from tests.integration.test_recovery import fault_env, spawn_cli, wait_for, wait_steady
from tests.integration.test_workers import args, finished, no_worker


def parallel(fx: Fixture, slots: int = 2) -> None:
    fx.state_dir.mkdir(parents=True, exist_ok=True)
    (fx.state_dir / "config.toml").write_text(f"[execution]\nmax_parallel_per_project = {slots}\n")


def create(
    b: Bridge,
    fx: Fixture,
    g: dict[str, Any],
    name: str,
    *,
    scenario: str = "hang",
    wall: float = 20,
    turns: int = 4,
    scope: list[str] | None = None,
) -> str:
    spec = fx.spec(
        scenario, wall_timeout_seconds=wall, max_turns_per_attempt=turns, kill_grace_seconds=0.1
    )
    spec["allowed_paths"] = scope or [f"{name}/**"]
    return str(b.create(spec, name, goal_id=g["goal_id"])["task_id"])


def reserve(b: Bridge, task: str, key: str = "dispatch") -> dict[str, Any]:
    return b.run(task, background=True, idempotency_key=key)


def assert_refused(b: Bridge, task: str, reason: str) -> None:
    with pytest.raises(BridgeError) as err:
        reserve(b, task)
    assert err.value.code == "STATE_CONFLICT"
    assert err.value.details["reason"] == reason
    assert not b.store.list_attempts(task)


def test_two_detached_fake_workers_run_together_and_cancel_independently(fx: Fixture) -> None:
    parallel(fx)
    b, g = setup_goal(fx, max_executor_wall_seconds=60, max_executor_turns=12)
    tasks = [create(b, fx, g, key) for key in ("a", "b", "c")]
    jobs: list[str] = []
    try:
        for task in tasks[:2]:
            jobs.append(reserve(b, task)["job_id"])
            record = wait_for(b.store, task, lambda t: t.state == S.RUNNING)
            attempt = b.store.get_attempt(record.current_attempt_id)
            assert attempt.pgid
            wait_steady(attempt.pgid)
        attempts = [b.store.list_attempts(t)[0] for t in tasks[:2]]
        assert attempts[0].pgid != attempts[1].pgid
        assert len({a.invocation["cwd"] for a in attempts}) == 2
        assert all(Path(a.invocation["cwd"]).parent == b.worktrees_dir for a in attempts)
        assert_refused(b, tasks[2], "project_capacity")
        status = b.coordination.status(g["goal_id"])
        assert status["execution"]["occupied_slots"] == 2
        assert status["budget"]["reserved_wall_seconds"] == 40
        assert status["budget"]["reserved_turns"] == 8
        assert b.cancel(tasks[0], wait_seconds=10)["state"] == "CANCELLED"
        assert finished(b, jobs[0])["executor_exit_confirmed"]
        assert b.store.get_task(tasks[1]).state == S.RUNNING
        assert b.coordination.status(g["goal_id"])["execution"]["occupied_slots"] == 1
        jobs.append(reserve(b, tasks[2])["job_id"])
        wait_for(b.store, tasks[2], lambda t: t.state == S.RUNNING)
        assert b.coordination.status(g["goal_id"])["budget"]["reserved_turns"] == 12
    finally:
        for task in tasks:
            if b.store.get_task(task).state not in (S.CANCELLED, S.FAILED, S.SUCCEEDED):
                b.cancel(task, wait_seconds=10)
        for job in jobs:
            finished(b, job)
        b.close()


def test_parallel_configuration_is_explicit_and_reloaded_for_existing_bridge(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    b, g = setup_goal(fx)
    a, c = [create(b, fx, g, key) for key in ("a", "c")]
    reserve(b, a)
    assert_refused(b, c, "project_capacity")
    parallel(fx)
    reserve(b, c)
    parallel(fx, 1)  # does not kill accepted work, but no more reservations are admitted
    assert b.coordination.status(g["goal_id"])["execution"]["occupied_slots"] == 2
    b.cancel(a)
    d = create(b, fx, g, "d")
    assert_refused(b, d, "project_capacity")
    b.cancel(c)
    reserve(b, d)
    b.cancel(d)
    b.close()


@pytest.mark.parametrize(
    "scopes",
    [
        (["src/**"], ["src/x.py"]),
        (["a*"], ["b*"]),
        (["Src/a.py"], ["src/A.py"]),
        (["café/**"], ["cafe\u0301/x.py"]),
    ],
)
def test_overlapping_or_unproven_scopes_refuse_without_spending_budget(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch, scopes: tuple[list[str], list[str]]
) -> None:
    no_worker(monkeypatch)
    parallel(fx)
    b, g = setup_goal(fx)
    a = create(b, fx, g, "a", scope=scopes[0])
    c = create(b, fx, g, "c", scope=scopes[1])
    reserve(b, a)
    before = b.coordination.status(g["goal_id"])["budget"]
    assert_refused(b, c, "write_scopes_may_overlap")
    assert b.coordination.status(g["goal_id"])["budget"] == before
    b.cancel(a)
    reserve(b, c)
    b.cancel(c)
    b.close()


def test_project_capacity_and_scopes_span_different_goals(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    parallel(fx)
    b, g = setup_goal(fx)
    a = create(b, fx, g, "a")
    reserve(b, a)
    h = b.coordination.create(goal_spec(fx), "another-goal")
    peer = Bridge(fx.state_dir, advisor_claim=AdvisorClaim.model_validate(h["advisor_claim"]))
    conflicting = create(peer, fx, h, "same-scope", scope=["a/file"])
    assert_refused(peer, conflicting, "write_scopes_may_overlap")
    c, d = [create(peer, fx, h, key) for key in ("c", "d")]
    reserve(peer, c)
    assert_refused(peer, d, "project_capacity")
    assert peer.coordination.status(h["goal_id"])["budget"]["attempts"] == 1
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 1
    b.cancel(a)
    peer.cancel(c)
    peer.close()
    b.close()


@pytest.mark.parametrize("ceiling", ["wall", "turns", "slots"])
def test_racing_distinct_tasks_cannot_double_reserve_remaining_capacity(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch, ceiling: str
) -> None:
    no_worker(monkeypatch)
    parallel(fx)
    limits = (
        {"max_executor_wall_seconds": 20}
        if ceiling == "wall"
        else ({"max_executor_turns": 4} if ceiling == "turns" else {})
    )
    b, g = setup_goal(fx, max_attempts=4, **limits)
    tasks = [create(b, fx, g, key) for key in ("a", "b", "c")]
    if ceiling == "slots":
        reserve(b, tasks[2])
    barrier = Barrier(2)
    original = FakeExecutorAdapter.build_invocation

    def synchronized(*a: Any, **kw: Any) -> Any:
        inv = original(*a, **kw)
        barrier.wait(timeout=10)
        return inv

    monkeypatch.setattr(FakeExecutorAdapter, "build_invocation", synchronized)

    def start(task: str) -> str:
        peer = Bridge(fx.state_dir, advisor_claim=b.advisor_claim)
        try:
            return reserve(peer, task)["phase"]
        except BridgeError as exc:
            return exc.code
        finally:
            peer.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(start, tasks[:2]))
    assert sorted(results) == sorted(
        ["reserved", "STATE_CONFLICT" if ceiling == "slots" else "BUDGET_EXHAUSTED"]
    )
    assert b.coordination.status(g["goal_id"])["budget"]["reserved_turns"] == (
        8 if ceiling == "slots" else 4
    )
    for task in tasks:
        b.cancel(task)
    b.close()


def test_nonstart_refunds_all_goal_ceilings_but_success_and_repair_keep_them(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    parallel(fx)
    b, g = setup_goal(fx, max_executor_wall_seconds=40, max_executor_turns=8, max_repairs=1)
    task = create(b, fx, g, "a", scenario="bug-then-repair", scope=["tagnorm/**"])
    with monkeypatch.context() as held:
        no_worker(held)
        r = reserve(b, task, "not-started")
    assert b.coordination.status(g["goal_id"])["budget"]["reserved_turns"] == 4
    assert b.jobs.cancel_unclaimed(task)
    assert b.coordination.status(g["goal_id"])["budget"]["reserved_wall_seconds"] == 0
    assert b.jobs.execute(r["job_id"]) is False
    actual = create(b, fx, g, "actual", scenario="bug-then-repair", scope=["tagnorm/**"])
    b.run(actual)  # legacy foreground path uses the same aggregate reservation
    assert b.coordination.status(g["goal_id"])["budget"]["reserved_turns"] == 4
    b.review(actual, review_for(b.artifacts(actual), "changes_requested", "fix"))
    assert finished(b, reserve(b, actual, "repair")["job_id"])["state"] == "AWAITING_REVIEW"
    budget = b.coordination.status(g["goal_id"])["budget"]
    assert budget["repairs"] == 1 and budget["reserved_wall_seconds"] == 40
    assert budget["reserved_turns"] == 8
    b.review(actual, review_for(b.artifacts(actual), "approve", "ok"))
    other = create(b, fx, g, "other")
    with pytest.raises(BridgeError) as err:
        b.run(other)
    assert err.value.code == "BUDGET_EXHAUSTED"
    assert set(err.value.details["exceeded"]) == {"executor_wall_seconds", "executor_turns"}
    assert not b.store.list_attempts(other)
    b.close()


def test_unknown_exit_keeps_a_slot_and_all_ceilings_after_logical_failure(fx: Fixture) -> None:
    parallel(fx)
    b, g = setup_goal(fx, max_executor_wall_seconds=40, max_executor_turns=8)
    a, c, d = [create(b, fx, g, key) for key in ("a", "c", "d")]
    parent = spawn_cli(fx, *args(b, a), env=fault_env("after_worker_claim"))
    stdout, stderr = parent.communicate(timeout=10)
    assert parent.returncode == 0, stderr
    job = json.loads(stdout)["job_id"]
    from tests.integration.test_workers import wait_runner_exit

    wait_for(b.store, a, lambda t: b.jobs.status(job)["phase"] == "claimed")
    wait_runner_exit(b, job)
    assert b.recover(a)["state_after"] == "INTERRUPTED"
    b.recover(a, resolve="fail")
    assert b.coordination.status(g["goal_id"])["budget"]["reserved_turns"] == 4
    r = reserve(b, c)
    try:
        wait_for(b.store, c, lambda t: t.state == S.RUNNING)
        with pytest.raises(BridgeError) as err:
            reserve(b, d)
        assert err.value.code == "BUDGET_EXHAUSTED"
        assert b.coordination.status(g["goal_id"])["execution"]["occupied_slots"] == 2
        control(b, g, "cancel")
        finished(b, r["job_id"])
        assert a in b.coordination.status(g["goal_id"])["pending_stop_tasks"]
    finally:
        if b.store.get_task(c).state != S.CANCELLED:
            b.cancel(c, wait_seconds=10)
        finished(b, r["job_id"])
        b.close()


def test_old_goal_digest_replay_and_history_remain_valid(fx: Fixture) -> None:
    data = goal_spec(fx)
    b = fx.bridge()
    g = b.coordination.create(data, "old")
    b.advisor_claim = AdvisorClaim.model_validate(g["advisor_claim"])
    historical = GoalSpec.model_validate(data).model_dump(
        mode="json", exclude={"max_executor_wall_seconds", "max_executor_turns"}
    )
    with b.store.transaction() as cur:
        row = cur.execute("SELECT * FROM goals WHERE goal_id=?", (g["goal_id"],)).fetchone()
        assert row["spec_json"] == canonical_json(historical)
        assert row["request_digest"] == sha256_digest(historical)
    task = create(b, fx, g, "old-task", scenario="success", scope=["tagnorm/**"])
    b.run(task)
    b.close()
    peer = fx.bridge()
    assert peer.coordination.create(data, "old")["goal_id"] == g["goal_id"]
    budget = peer.coordination.status(g["goal_id"])["budget"]
    assert budget["max_executor_wall_seconds"] is None and budget["max_executor_turns"] is None
    assert budget["reserved_wall_seconds"] == 20 and budget["reserved_turns"] == 4
    assert not (fx.state_dir / "backups").exists()  # no migration or historical rewrite needed
    peer.close()


def test_changed_budget_is_not_an_idempotent_goal_replay(fx: Fixture) -> None:
    b, _ = setup_goal(fx, max_executor_turns=4)
    with pytest.raises(BridgeError) as err:
        b.coordination.create(goal_spec(fx, max_executor_turns=8), "goal")
    assert err.value.code == "IDEMPOTENCY_CONFLICT"
    b.close()


def test_decimal_wall_reservations_do_not_spuriously_exhaust_boundary(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    parallel(fx)
    b, g = setup_goal(fx, max_executor_wall_seconds=0.3)
    a = create(b, fx, g, "a", wall=0.1)
    c = create(b, fx, g, "c", wall=0.2)
    reserve(b, a)
    reserve(b, c)
    assert b.coordination.status(g["goal_id"])["budget"]["reserved_wall_seconds"] == 0.3
    b.cancel(a)
    b.cancel(c)
    b.close()


def test_tampered_prior_task_cannot_shrink_reserved_budget(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    parallel(fx)
    b, g = setup_goal(fx, max_executor_wall_seconds=20)
    a, c = [create(b, fx, g, key) for key in ("a", "c")]
    reserve(b, a)
    original = b.store.get_task(a).spec_json
    changed = json.loads(original)
    changed["limits"]["wall_timeout_seconds"] = 0.001
    with b.store.transaction() as cur:
        cur.execute("UPDATE tasks SET spec_json=? WHERE task_id=?", (canonical_json(changed), a))
    with pytest.raises(BridgeError) as err:
        reserve(b, c)
    assert err.value.code == "INTEGRITY_ERROR"
    assert not b.store.list_attempts(c)
    with b.store.transaction() as cur:
        cur.execute("UPDATE tasks SET spec_json=? WHERE task_id=?", (original, a))
    b.cancel(a)
    b.close()


def test_preparation_and_unresolved_preparation_remain_project_exclusive(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    parallel(fx)
    b, g = setup_goal(fx)
    child = children(b, g, setup_plan(fx))["a"]
    prepared = b.materialize(child)["task_id"]
    other = create(b, fx, g, "other")
    reserve(b, other)
    with pytest.raises(BridgeError) as err:
        b.preparations.prepare(child, "held")
    assert err.value.details["reason"] == "preparation_requires_exclusive_project"
    b.cancel(other)
    from tests.integration.test_preparation import prepare_args

    parent = spawn_cli(fx, *prepare_args(b, child), env=fault_env("after_preparation_reserved"))
    parent.communicate(timeout=10)
    assert parent.returncode == 70
    b.recover(prepared)
    b.recover(prepared, resolve="fail")
    new = create(b, fx, g, "new")
    assert_refused(b, new, "preparation_requires_exclusive_project")
    assert b.coordination.status(g["goal_id"])["execution"]["preparation_exclusive"]
    b.close()


def test_stale_advisor_pause_and_same_key_do_not_bypass_new_limits(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    parallel(fx)
    b, g = setup_goal(fx, max_executor_turns=4)
    a, c = [create(b, fx, g, key) for key in ("a", "c")]
    r = reserve(b, a)
    assert reserve(b, a)["job_id"] == r["job_id"]
    assert b.coordination.status(g["goal_id"])["budget"]["reserved_turns"] == 4
    claim = takeover(b, g)["advisor_claim"]
    with pytest.raises(BridgeError) as err:
        reserve(b, c)
    assert err.value.code == "STALE_ADVISOR"
    b.advisor_claim = AdvisorClaim.model_validate(claim)
    control(b, g, "pause")
    with pytest.raises(BridgeError) as err:
        reserve(b, c)
    assert err.value.code == "STATE_CONFLICT"
    b.cancel(a)
    b.close()


@pytest.mark.parametrize("operation", ["verify", "recover"])
@pytest.mark.parametrize("full", [False, True])
def test_verification_entrypoints_cannot_bypass_slots_or_scopes(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch, operation: str, full: bool
) -> None:
    parallel(fx)
    b, g = setup_goal(fx, max_attempts=4)
    target = create(b, fx, g, "candidate", scenario="success", scope=["tagnorm/**"])
    b.run(target)
    if operation == "recover":
        with b.store.transaction() as cur:
            b.store.transition(cur, target, S.AWAITING_REVIEW, S.VERIFYING, reason="fixture")
            b.store.transition(
                cur,
                target,
                S.VERIFYING,
                S.INTERRUPTED,
                reason="fixture_verifier_interrupt",
                details={"phase": "verification", "outcome_known": True},
            )
    no_worker(monkeypatch)
    first = create(b, fx, g, "first", scope=["other/**"] if full else ["tagnorm/normalize.py"])
    held = [first]
    reserve(b, first)
    if full:
        second = create(b, fx, g, "second", scope=["another/**"])
        reserve(b, second)
        held.append(second)
    before = b.store.get_task(target)
    with pytest.raises(BridgeError) as err:
        getattr(b, operation)(target)
    assert err.value.code == "STATE_CONFLICT"
    assert err.value.details["reason"] == (
        "project_capacity" if full else "write_scopes_may_overlap"
    )
    assert b.store.get_task(target) == before
    assert len(b.store.list_attempts(target)) == 1
    for task in held:
        b.cancel(task)
    assert getattr(b, operation)(target).get("state_after", "AWAITING_REVIEW") == "AWAITING_REVIEW"
    assert b.store.get_task(target).state == S.AWAITING_REVIEW
    b.close()


def test_unknown_attempt_cannot_use_second_slot_on_same_worktree(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    parallel(fx)
    b, g = setup_goal(fx)
    task = create(b, fx, g, "a")
    r = reserve(b, task)
    # Simulate a dead claimed runner before spawn; unlike reserved, this window is unknown.
    with b.store.transaction() as cur:
        cur.execute("UPDATE worker_jobs SET phase='claimed' WHERE job_id=?", (r["job_id"],))
        b.store.update_attempt(cur, r["attempt_id"], runner={"hostname": "lost"})
    b.recover(task, acknowledge_unknown=True)
    b.recover(task, resolve="retry", acknowledge_unknown=True)
    with pytest.raises(BridgeError) as err:
        reserve(b, task, "retry")
    assert err.value.code == "STATE_CONFLICT"
    assert err.value.details["reason"] == "task_already_occupied"
    assert len(b.store.list_attempts(task)) == 1
    b.close()


def test_simulated_host_session_exit_preserves_detached_worker_observation(fx: Fixture) -> None:
    parallel(fx)
    b, g = setup_goal(fx)
    task = create(b, fx, g, "host-exit", wall=30)
    receipt = fx.base / "host-receipt.json"
    script = """
import subprocess, sys, time
from pathlib import Path
result = subprocess.run(
    [sys.executable, '-m', 'harness_bridge', '--state-dir', sys.argv[1], '--json', *sys.argv[3:]],
    capture_output=True, text=True, check=True, timeout=15)
Path(sys.argv[2]).write_text(result.stdout)
while True:
    time.sleep(1)
"""
    host = subprocess.Popen(
        [sys.executable, "-c", script, str(fx.state_dir), str(receipt), *args(b, task)],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    job = None
    try:
        deadline = time.monotonic() + 15
        while not receipt.exists() and host.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert receipt.exists()
        r = json.loads(receipt.read_text())
        job = r["job_id"]
        record = wait_for(b.store, task, lambda t: t.state == S.RUNNING)
        attempt = b.store.get_attempt(record.current_attempt_id)
        assert attempt.runner and attempt.pgid
        wait_steady(attempt.pgid)
        assert os.getpgid(attempt.runner["pid"]) != host.pid
        os.killpg(host.pid, signal.SIGTERM)
        host.communicate(timeout=5)
        code, observed = fx.cli("job", job)
        assert code == 0 and observed["runner_alive"] is True and observed["state"] == "RUNNING"
        cursor = b.jobs.events(task)["next_cursor"]
        assert b.jobs.events(task, after=cursor, wait_seconds=0.1)["wait_timed_out"]
        assert b.run(task, background=True, idempotency_key="dispatch")["job_id"] == job
        assert len(b.store.list_attempts(task)) == 1
    finally:
        if host.poll() is None:
            os.killpg(host.pid, signal.SIGKILL)
        host.communicate(timeout=5)
        if b.store.get_task(task).state not in (S.CANCELLED, S.FAILED, S.SUCCEEDED):
            b.cancel(task, wait_seconds=10)
        if job:
            assert finished(b, job)["executor_exit_confirmed"] is True
        b.close()


def test_multiple_unknown_historical_attempts_do_not_collapse_into_one_slot(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    parallel(fx)
    b, g = setup_goal(fx)
    task = create(b, fx, g, "legacy-unknown")
    r = reserve(b, task)
    # Synthetic historical ledger: no process is started by this fixture. New dispatch rules
    # already prohibit making another attempt on an unresolved worktree.
    with b.store.transaction() as cur:
        previous = dict(
            cur.execute("SELECT * FROM attempts WHERE attempt_id=?", (r["attempt_id"],)).fetchone()
        )
        b.store.insert_attempt(
            cur,
            {
                **previous,
                "attempt_id": "att_historical_unknown",
                "seq": 2,
                "launch_token": "historic-token",
            },
        )
        cur.execute("UPDATE worker_jobs SET phase='claimed' WHERE job_id=?", (r["job_id"],))
        b.store.transition(
            cur,
            task,
            S.STARTING,
            S.INTERRUPTED,
            reason="fixture_history",
            details={"outcome_known": False},
            attempts_used=2,
        )
    b.recover(task, resolve="fail")
    report = b.coordination.status(g["goal_id"])
    assert report["execution"]["occupied_slots"] == 2
    assert report["execution"]["slots_by_task"][task] == 2
    assert report["budget"]["attempts"] == 2 and report["budget"]["reserved_wall_seconds"] == 40
    other = create(b, fx, g, "other")
    assert_refused(b, other, "project_capacity")
    b.close()
