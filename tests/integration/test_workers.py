"""Detached workers exercised with isolated fake/stub processes, never model calls."""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from harness_bridge.adapters.fake import FakeExecutorAdapter
from harness_bridge.coordination import AdvisorClaim
from harness_bridge.errors import BridgeError
from harness_bridge.jobs import WorkerJobs
from harness_bridge.runner import group_alive
from harness_bridge.service import Bridge
from harness_bridge.store import SCHEMA_REVISION
from tests.conftest import Fixture
from tests.helpers.reviews import review_for
from tests.integration.test_claude_stub_flow import STREAM, argv_log, claude_spec
from tests.integration.test_claude_stub_flow import stub as stub
from tests.integration.test_coordination import setup_goal, takeover
from tests.integration.test_preparation import setup
from tests.integration.test_recovery import fault_env, spawn_cli, wait_for, wait_steady


def args(b: Bridge, task: str, key: str = "dispatch") -> list[str]:
    claim = b.advisor_claim
    return ["run", task, "--background", "--idempotency-key", key] + (
        ["--advisor-binding", claim.binding_id, "--advisor-epoch", str(claim.epoch)]
        if claim
        else []
    )


def finished(b: Bridge, job: str) -> dict[str, Any]:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        status = b.jobs.status(job)
        if status["phase"] in ("finished", "abandoned"):
            return status
        time.sleep(0.05)
    raise AssertionError(b.jobs.status(job))


def no_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WorkerJobs, "launch", lambda self, job: None)


def test_detached_cli_returns_handle_and_finishes_through_existing_review(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    parent = spawn_cli(fx, *args(b, task))
    stdout, stderr = parent.communicate(timeout=10)
    assert parent.returncode == 0, stderr
    receipt = json.loads(stdout)
    done = finished(b, receipt["job_id"])
    assert done["phase"] == "finished" and done["state"] == "AWAITING_REVIEW"
    assert done["runner"]["pid"] != parent.pid
    assert done["executor_exit_confirmed"] is True
    assert b.artifacts(task)["verification"]["status"] == "passed"
    b.review(task, review_for(b.artifacts(task), "approve", "ok"))
    code, read = fx.cli("job", receipt["job_id"])
    assert code == 0 and read["state"] == "SUCCEEDED"
    assert b.run(task, background=True, idempotency_key="dispatch")["replayed"]
    assert len(b.store.list_attempts(task)) == 1
    b.close()


def test_lost_launch_receipt_can_be_replayed_without_another_worker(fx: Fixture) -> None:
    b = fx.bridge()
    task = b.create(fx.spec(), "a")["task_id"]
    parent = spawn_cli(fx, *args(b, task), env=fault_env("after_worker_launch"))
    parent.communicate(timeout=10)
    assert parent.returncode == 70
    receipt = b.run(task, background=True, idempotency_key="dispatch")
    assert receipt["replayed"]
    assert finished(b, receipt["job_id"])["state"] == "AWAITING_REVIEW"
    assert len(b.store.list_attempts(task)) == 1
    assert [e["type"] for e in b.store.list_events(task)].count("worker_claimed") == 1
    b.close()


def test_cancel_detached_worker_stops_owned_executor_group(fx: Fixture) -> None:
    b = fx.bridge()
    task = b.create(fx.spec("hang", wall_timeout_seconds=30, kill_grace_seconds=0.1), "a")[
        "task_id"
    ]
    code, receipt = fx.cli(*args(b, task))
    assert code == 0
    wait_for(b.store, task, lambda t: t.state == "RUNNING")
    attempt = b.store.get_attempt(receipt["attempt_id"])
    assert attempt.runner and attempt.pgid
    try:
        wait_steady(attempt.pgid)
        assert os.getpgid(attempt.runner["pid"]) == attempt.runner["pid"]
        assert b.cancel(task, wait_seconds=10)["state"] == "CANCELLED"
        done = finished(b, receipt["job_id"])
        assert done["executor_exit_confirmed"] is True
        assert not group_alive(attempt.pgid)
    finally:
        if group_alive(attempt.pgid):
            os.killpg(attempt.pgid, signal.SIGKILL)
    b.close()


def test_wall_timeout_remains_executor_timeout_not_wait_timeout(fx: Fixture) -> None:
    b = fx.bridge()
    task = b.create(fx.spec("hang", wall_timeout_seconds=0.8, kill_grace_seconds=0.1), "a")[
        "task_id"
    ]
    receipt = b.run(task, background=True, idempotency_key="k")
    done = finished(b, receipt["job_id"])
    assert done["executor_outcome"] == "timed_out" and done["executor_exit_confirmed"]
    assert done["state"] == "AWAITING_REVIEW"
    b.close()


@pytest.mark.parametrize("recover", [False, True])
def test_unclaimed_crash_is_fenced_before_delayed_worker_can_execute(
    fx: Fixture, recover: bool
) -> None:
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    parent = spawn_cli(fx, *args(b, task), env=fault_env("after_starting_commit"))
    parent.communicate(timeout=10)
    assert parent.returncode == 70
    job = b.run(task, background=True, idempotency_key="dispatch")["job_id"]
    if recover:
        assert b.recover(task)["state_after"] == "BLOCKED"
    else:
        assert b.cancel(task)["state"] == "CANCELLED"
    assert b.jobs.status(job)["phase"] == "abandoned"
    assert b.jobs.execute(job) is False
    assert b.store.list_attempts(task)[0].pid is None
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 0
    assert b.run(task, background=True, idempotency_key="dispatch")["job_id"] == job
    b.close()


def test_unknown_launcher_liveness_does_not_release_reservation(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    b = fx.bridge()
    task = b.create(fx.spec(), "a")["task_id"]
    r = b.run(task, background=True, idempotency_key="k")
    with b.store.transaction() as cur:
        b.store.update_attempt(cur, r["attempt_id"], runner=None)
    assert b.recover(task, acknowledge_unknown=True)["state_after"] == "STARTING"
    assert b.jobs.status(r["job_id"])["phase"] == "reserved"
    b.cancel(task)
    b.close()


def test_worker_crash_after_claim_retains_unknown_exit_and_goal_budget(fx: Fixture) -> None:
    b, g = setup_goal(fx, max_attempts=2)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    parent = spawn_cli(fx, *args(b, task), env=fault_env("after_worker_claim"))
    stdout, stderr = parent.communicate(timeout=10)
    assert parent.returncode == 0, stderr
    job = json.loads(stdout)["job_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        r = b.jobs.status(job)
        if r["phase"] == "claimed" and r["runner_alive"] is False:
            break
        time.sleep(0.05)
    assert r["phase"] == "claimed" and r["runner_alive"] is False
    assert b.recover(task)["state_after"] == "INTERRUPTED"
    assert b.store.list_attempts(task)[0].exit_confirmed is None
    assert b.jobs.execute(job) is False
    b.recover(task, resolve="fail")
    other = b.create(fx.spec(), "b", goal_id=g["goal_id"])["task_id"]
    with pytest.raises(BridgeError) as err:
        b.run(other, background=True, idempotency_key="new")
    assert err.value.code == "STATE_CONFLICT"
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 1
    b.close()


def test_takeover_fences_new_dispatch_but_accepted_worker_finishes(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    r = b.run(task, background=True, idempotency_key="k")
    claim = takeover(b, g)["advisor_claim"]
    with pytest.raises(BridgeError) as err:
        b.run(task, background=True, idempotency_key="k")
    assert err.value.code == "STALE_ADVISOR"
    worker = fx.bridge()  # no Advisor claim: may execute only the already reserved job
    assert worker.jobs.execute(r["job_id"])
    b.advisor_claim = AdvisorClaim.model_validate(claim)
    assert b.run(task, background=True, idempotency_key="k")["replayed"]
    assert b.jobs.execute(r["job_id"]) is False
    worker.close()
    b.close()


def test_spawn_failure_is_durable_and_replay_never_relaunches(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, g = setup_goal(fx)
    task = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    b.python = "/missing-hbridge-python"
    r = b.run(task, background=True, idempotency_key="k")
    assert r["phase"] == "abandoned" and r["error_code"] == "WORKER_SPAWN_FAILED"
    assert r["executor_exit_confirmed"] is True
    b.python = sys.executable
    assert b.run(task, background=True, idempotency_key="k")["phase"] == "abandoned"
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 0
    assert b.store.list_attempts(task)[0].pid is None
    b.close()


@pytest.mark.parametrize("same_task", [False, True])
def test_concurrent_dispatch_reserves_one_attempt(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch, same_task: bool
) -> None:
    no_worker(monkeypatch)
    b, g = setup_goal(fx, max_attempts=1)
    first = b.create(fx.spec(), "a", goal_id=g["goal_id"])["task_id"]
    tasks = [
        first,
        first if same_task else b.create(fx.spec(), "b", goal_id=g["goal_id"])["task_id"],
    ]
    original = FakeExecutorAdapter.build_invocation
    barrier = Barrier(2)

    def synchronize(*a: Any, **kw: Any) -> Any:
        result = original(*a, **kw)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(FakeExecutorAdapter, "build_invocation", synchronize)

    def dispatch(task: str) -> str:
        peer = Bridge(fx.state_dir, advisor_claim=b.advisor_claim)
        try:
            return str(peer.run(task, background=True, idempotency_key="k")["job_id"])
        except BridgeError as exc:
            return exc.code
        finally:
            peer.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(dispatch, tasks))
    if same_task:
        assert results[0] == results[1] and results[0].startswith("job_")
    else:
        assert results.count("BUDGET_EXHAUSTED") == 1
    assert sum(len(b.store.list_attempts(t)) for t in set(tasks)) == 1
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 1
    for t in set(tasks):
        b.cancel(t)
    b.close()


def test_background_cannot_bypass_key_live_gate_or_preparation(fx: Fixture) -> None:
    b, _, child, task = setup(fx)
    with pytest.raises(BridgeError) as err:
        b.run(task, background=True)
    assert err.value.code == "USAGE_ERROR"
    with pytest.raises(BridgeError) as err:
        b.run(task, background=True, idempotency_key="live", mode="live", allow_model_usage=True)
    assert err.value.code == "LIVE_GATE_CLOSED"
    with pytest.raises(BridgeError) as err:
        b.run(task, background=True, idempotency_key="prepare")
    assert err.value.code == "PREFLIGHT_FAILED"
    assert b.store.list_attempts(task) == []
    b.preparations.prepare(child, "setup")
    r = b.run(task, background=True, idempotency_key="prepared")
    assert finished(b, r["job_id"])["state"] == "AWAITING_REVIEW"
    with pytest.raises(BridgeError) as err:
        b.run(task, background=True, idempotency_key="prepared", allow_model_usage=True)
    assert err.value.code == "IDEMPOTENCY_CONFLICT"
    b.close()


def test_worker_rechecks_preparation_after_reservation(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    b, g, child, task = setup(fx)
    b.preparations.prepare(child, "setup")
    r = b.run(task, background=True, idempotency_key="k")
    wt = Path(b.store.get_task(task).worktree_path or "")
    (wt / "__pycache__" / "ready").unlink()
    assert b.jobs.execute(r["job_id"]) is False
    assert b.jobs.status(r["job_id"])["error_code"] == "PREFLIGHT_FAILED"
    assert b.store.list_attempts(task)[0].pid is None
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 0
    b.close()


@pytest.mark.parametrize("aborted_repair", [False, True])
def test_background_claude_stub_repair_preserves_bound_session(
    fx: Fixture, stub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aborted_repair: bool
) -> None:
    log = tmp_path / "calls.jsonl"
    b = Bridge(
        fx.state_dir,
        env={
            **os.environ,
            "HBRIDGE_STUB_FIXTURE": str(STREAM / "success.jsonl"),
            "HBRIDGE_STUB_ARGV_LOG": str(log),
            "HBRIDGE_STUB_EDIT": "buggy",
        },
    )
    task = b.create(claude_spec(fx), "a")["task_id"]
    r = b.run(task, background=True, idempotency_key="first", executor_binary=str(stub))
    assert finished(b, r["job_id"])["state"] == "AWAITING_REVIEW"
    first = b.store.list_attempts(task)[0]
    b.review(task, review_for(b.artifacts(task), "changes_requested", "fix"))
    if aborted_repair:
        with monkeypatch.context() as held:
            no_worker(held)
            aborted = b.run(
                task, background=True, idempotency_key="not-started", executor_binary=str(stub)
            )
        b.env["HBRIDGE_STUB_ADDED_AFTER_RESERVATION"] = "1"
        assert b.jobs.execute(aborted["job_id"]) is False
        del b.env["HBRIDGE_STUB_ADDED_AFTER_RESERVATION"]
        assert b.jobs.status(aborted["job_id"])["error_code"] == "INTEGRITY_ERROR"
        assert len(argv_log(log)) == 1
        b.recover(task, resolve="retry")
    b.env["HBRIDGE_STUB_EDIT"] = "correct"
    r = b.run(task, background=True, idempotency_key="repair", executor_binary=str(stub))
    assert finished(b, r["job_id"])["state"] == "AWAITING_REVIEW"
    calls = argv_log(log)
    assert calls[1]["argv"][-2:] == ["--resume", first.session_id]
    assert "fix it" in calls[1]["stdin_text"]
    b.review(task, review_for(b.artifacts(task), "approve", "ok"))
    assert b.store.get_task(task).state == "SUCCEEDED"
    b.close()


def test_incremental_events_paginate_without_duplicates_or_mutation(fx: Fixture) -> None:
    b = fx.bridge()
    task = b.create(fx.spec(), "a")["task_id"]
    r = b.run(task, background=True, idempotency_key="k")
    finished(b, r["job_id"])
    seen: list[int] = []
    cursor = 0
    while True:
        code, page = fx.cli("events", task, "--after", str(cursor), "--limit", "2")
        assert code == 0
        seen.extend(e["seq"] for e in page["events"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    before = b.store.get_task(task)
    empty = b.jobs.events(task, after=cursor, wait_seconds=0.2)
    assert empty["events"] == [] and empty["next_cursor"] == cursor
    assert seen == [e["seq"] for e in b.store.list_events(task)]
    assert len(set(seen)) == len(seen)
    assert b.store.get_task(task) == before
    b.close()


def test_wait_timeout_is_read_only_and_new_event_wakes_wait(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    b = fx.bridge()
    task = b.create(fx.spec(), "a")["task_id"]
    r = b.run(task, background=True, idempotency_key="k")
    assert b.jobs.events(task, after=r["event_cursor"], wait_seconds=0.1)["wait_timed_out"]
    assert b.store.get_task(task).state == "STARTING"

    def wait() -> dict[str, Any]:
        peer = fx.bridge()
        try:
            return peer.jobs.events(task, after=r["event_cursor"], wait_seconds=3)
        finally:
            peer.close()

    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(wait)
        b.cancel(task)
        result = pending.result(timeout=5)
    assert result["events"] and not result["wait_timed_out"]
    assert result["state"] == "CANCELLED"
    b.close()


@pytest.mark.parametrize(
    "options",
    [
        {"after": -1},
        {"after": 2**63},
        {"limit": 0},
        {"limit": 501},
        {"wait_seconds": 31},
        {"wait_seconds": float("nan")},
    ],
)
def test_event_query_rejects_unbounded_or_invalid_requests(
    fx: Fixture, options: dict[str, Any]
) -> None:
    b = fx.bridge()
    task = b.create(fx.spec(), "a")["task_id"]
    with pytest.raises(BridgeError) as err:
        b.jobs.events(task, **options)
    assert err.value.code == "INVALID_INPUT"
    b.close()


def test_v5_migration_preserves_prepared_task_and_current_advisor(fx: Fixture) -> None:
    b, g, child, task = setup(fx)
    b.preparations.prepare(child, "setup")
    before = b.status(task)
    claim = b.advisor_claim
    path = b.store.db_path
    b.close()
    with sqlite3.connect(path) as old:
        old.execute("DROP TABLE worker_jobs")
        old.execute("UPDATE meta SET value='5' WHERE key='schema_revision'")
    b = Bridge(fx.state_dir, advisor_claim=claim)
    assert b.status(task) == before
    r = b.run(task, background=True, idempotency_key="migrated")
    assert finished(b, r["job_id"])["state"] == "AWAITING_REVIEW"
    backup = next((fx.state_dir / "backups").glob(f"pre-v{SCHEMA_REVISION}-*.sqlite3"))
    with sqlite3.connect(backup) as saved:
        assert saved.execute("SELECT value FROM meta").fetchone()[0] == "5"
        assert saved.execute("SELECT count(*) FROM preparation_runs").fetchone()[0] == 1
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 1
    b.close()


def test_killed_worker_leaves_executor_unknown_and_never_signals_on_recovery(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    task = b.create(
        fx.spec("hang", wall_timeout_seconds=30, kill_grace_seconds=0.1), "a", goal_id=g["goal_id"]
    )["task_id"]
    r = b.run(task, background=True, idempotency_key="k")
    wait_for(b.store, task, lambda t: t.state == "RUNNING")
    attempt = b.store.get_attempt(r["attempt_id"])
    assert attempt.runner and attempt.pgid
    try:
        wait_steady(attempt.pgid)
        os.kill(attempt.runner["pid"], signal.SIGKILL)
        wait_runner_exit(b, r["job_id"])
        assert b.recover(task)["state_after"] == "INTERRUPTED"
        assert group_alive(attempt.pgid)
        status = b.jobs.status(r["job_id"])
        assert status["phase"] == "recovered" and not status["executor_exit_confirmed"]
        assert b.jobs.execute(r["job_id"]) is False
        b.cancel(task, acknowledge_unknown=True)
        other = b.create(fx.spec(), "b", goal_id=g["goal_id"])["task_id"]
        with pytest.raises(BridgeError) as err:
            b.run(other, background=True, idempotency_key="other")
        assert err.value.code == "STATE_CONFLICT"
    finally:
        if group_alive(attempt.pgid):
            os.killpg(attempt.pgid, signal.SIGKILL)
    b.close()


def wait_runner_exit(b: Bridge, job: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if b.jobs.status(job)["runner_alive"] is False:
            return
        time.sleep(0.05)
    raise AssertionError(b.jobs.status(job))


def test_worker_verification_crash_recovers_checks_without_another_executor(fx: Fixture) -> None:
    b = fx.bridge()
    task = b.create(fx.spec(), "a")["task_id"]
    parent = spawn_cli(fx, *args(b, task), env=fault_env("after_verifying_commit"))
    stdout, stderr = parent.communicate(timeout=10)
    assert parent.returncode == 0, stderr
    r = json.loads(stdout)
    wait_for(b.store, task, lambda t: t.state == "VERIFYING")
    wait_runner_exit(b, r["job_id"])
    assert b.recover(task)["state_after"] == "AWAITING_REVIEW"
    assert b.jobs.status(r["job_id"])["phase"] == "recovered"
    assert len(b.store.list_attempts(task)) == 1
    assert b.jobs.execute(r["job_id"]) is False
    b.review(task, review_for(b.artifacts(task), "approve", "ok"))
    b.close()


def test_two_worker_processes_cannot_claim_one_reservation_twice(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    b = fx.bridge()
    task = b.create(fx.spec(), "a")["task_id"]
    r = b.run(task, background=True, idempotency_key="k")
    argv = [
        sys.executable,
        "-m",
        "harness_bridge.worker",
        "--state-dir",
        str(fx.state_dir),
        "--job-id",
        r["job_id"],
    ]
    workers = [
        subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)
    ]
    for worker in workers:
        worker.communicate(timeout=15)
    assert sorted(w.returncode for w in workers) == [0, 1]
    assert finished(b, r["job_id"])["state"] == "AWAITING_REVIEW"
    assert [e["type"] for e in b.store.list_events(task)].count("executor_spawned") == 1
    b.close()


@pytest.mark.parametrize("closed", [False, True])
def test_background_live_route_with_stub_rechecks_gate_before_execution(
    fx: Fixture, stub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, closed: bool
) -> None:
    # Configured binary is an offline stub. Neither branch ever invokes a real Claude binary.
    from tests.integration.test_claude_stub_flow import HELP, _live_config

    no_worker(monkeypatch)
    _live_config(fx, stub, 'allow_unlisted_flags = ["--max-turns"]\n')
    log = tmp_path / "calls.jsonl"
    env = {
        **os.environ,
        "HBRIDGE_STUB_HELP": str(HELP),
        "HBRIDGE_STUB_FIXTURE": str(STREAM / "success.jsonl"),
        "HBRIDGE_STUB_ARGV_LOG": str(log),
        "HBRIDGE_STUB_EDIT": "correct",
    }
    b = Bridge(fx.state_dir, env=env)
    task = b.create(claude_spec(fx), "a")["task_id"]
    r = b.run(task, background=True, idempotency_key="k", mode="live", allow_model_usage=True)
    if closed:
        (fx.state_dir / "config.toml").write_text("[live]\nenabled = false\n")
    worker = Bridge(fx.state_dir, env=env)
    assert worker.jobs.execute(r["job_id"]) is (not closed)
    if closed:
        assert b.jobs.status(r["job_id"])["error_code"] == "LIVE_GATE_CLOSED"
        assert not log.exists()
        assert b.store.list_attempts(task)[0].pid is None
    else:
        assert len(argv_log(log)) == 1
        assert b.store.get_task(task).state == "AWAITING_REVIEW"
    worker.close()
    b.close()


def test_unclaimed_record_tamper_never_spawns(fx: Fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    no_worker(monkeypatch)
    b = fx.bridge()
    task = b.create(fx.spec(), "a")["task_id"]
    r = b.run(task, background=True, idempotency_key="k")
    with b.store.transaction() as cur:
        cur.execute("UPDATE worker_jobs SET execution_json='{}'")
    assert b.jobs.execute(r["job_id"]) is False
    assert b.jobs.status(r["job_id"])["error_code"] == "INTEGRITY_ERROR"
    assert b.store.list_attempts(task)[0].pid is None
    b.close()


def test_resolve_is_not_silently_applied_as_unclaimed_recovery(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_worker(monkeypatch)
    b = fx.bridge()
    task = b.create(fx.spec(), "a")["task_id"]
    r = b.run(task, background=True, idempotency_key="k")
    with pytest.raises(BridgeError) as err:
        b.recover(task, resolve="retry")
    assert err.value.code == "STATE_CONFLICT"
    assert b.jobs.status(r["job_id"])["phase"] == "reserved"
    b.cancel(task)
    b.close()
