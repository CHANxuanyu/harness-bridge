"""Repair loop, idempotency, crash windows, races, cancellation and recovery (M2).

Crashes are real: the CLI runner process is killed (injected ``os._exit`` at a named point, or
SIGTERM/SIGKILL from the test), and recovery runs in a fresh process.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.adapters import fake_executor
from harness_bridge.errors import BridgeError
from harness_bridge.runner import _linux_group_members, _ps_group_members, group_alive
from harness_bridge.store import Store
from tests.conftest import Fixture
from tests.helpers.reviews import review_for
from tests.unit.test_runner import alive


def write(path: Path, obj: object) -> str:
    path.write_text(json.dumps(obj))
    return str(path)


def spawn_cli(fx: Fixture, *args: str, env: dict[str, str] | None = None) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "harness_bridge", "--state-dir", str(fx.state_dir), "--json", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def wait_for(store: Store, task_id: str, pred: Any, timeout: float = 30.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        task = store.get_task(task_id)
        if pred(task):
            return task
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting; state={store.get_task(task_id).state}")


def created_task(fx: Fixture, tmp_path: Path, scenario: str, **limits: Any) -> str:
    _, created = fx.cli(
        "create",
        "--task",
        write(tmp_path / "task.json", fx.spec(scenario, **limits)),
        "--idempotency-key",
        f"k-{scenario}",
    )
    return str(created["task_id"])


def live_members(pgid: int) -> list[int]:
    members = _linux_group_members(pgid)
    if members is None:
        members = _ps_group_members(pgid) or []
    return [pid for pid, state in members if not state.startswith("Z")]


def wait_steady(pgid: int) -> None:
    """Wait until the fake 'hang' executor has started its helper child (2 live members)."""
    end = time.monotonic() + 30
    while len(live_members(pgid)) < 2 and time.monotonic() < end:
        time.sleep(0.05)
    assert len(live_members(pgid)) >= 2


def fault_env(name: str) -> dict[str, str]:
    return dict(os.environ, HBRIDGE_TEST_FAULT=name)


# --- repair loop -------------------------------------------------------------------------------


def test_c02_bug_then_repair(fx: Fixture) -> None:
    b = fx.bridge()
    task_id = b.create(fx.spec("bug-then-repair"), "k")["task_id"]
    first = b.run(task_id)
    assert first["verification_status"] == "failed"
    summary = b.artifacts(task_id)
    receipt = b.review(task_id, review_for(summary, "changes_requested", "r1"))
    assert receipt["resulting_state"] == "READY"
    second = b.run(task_id)
    assert second["attempt_kind"] == "repair" and second["verification_status"] == "passed"
    attempts = b.store.list_attempts(task_id)
    assert attempts[1].feedback and attempts[1].feedback[0]["explanation"] == "fix it"
    b.review(task_id, review_for(b.artifacts(task_id), "approve", "r2"))
    status = b.status(task_id)
    assert status["state"] == "SUCCEEDED"
    assert status["attempts_used"] == 2 and status["repair_cycles_used"] == 1


def test_r03_repair_budget_is_enforced(fx: Fixture) -> None:
    b = fx.bridge()
    task_id = b.create(fx.spec("false-success-report"), "k")["task_id"]
    states = []
    for i in range(3):
        b.run(task_id)
        receipt = b.review(task_id, review_for(b.artifacts(task_id), "changes_requested", f"r{i}"))
        states.append(receipt["resulting_state"])
    assert states == ["READY", "READY", "FAILED"]
    assert b.status(task_id)["state_reason"] == "repair_budget_exhausted"
    with pytest.raises(BridgeError) as exc:
        b.run(task_id)
    assert exc.value.code == "STATE_CONFLICT"
    assert len(b.store.list_attempts(task_id)) == 3


def test_r04_duplicate_review_does_not_advance_twice(fx: Fixture) -> None:
    b = fx.bridge()
    task_id = b.create(fx.spec("bug-then-repair"), "k")["task_id"]
    b.run(task_id)
    body = review_for(b.artifacts(task_id), "changes_requested", "same-key")
    first = b.review(task_id, body)
    again = b.review(task_id, body)
    assert again["review_id"] == first["review_id"] and again["duplicate"] is True
    task = b.store.get_task(task_id)
    assert task.state.value == "READY" and task.attempts_used == 1
    accepted = [e for e in b.store.list_events(task_id) if e["type"] == "review_accepted"]
    assert len(accepted) == 1
    with pytest.raises(BridgeError) as exc:
        b.review(task_id, {**body, "findings": [{"severity": "minor", "explanation": "other"}]})
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"


def test_rejected_approve_is_replayed_as_the_same_rejection(fx: Fixture) -> None:
    b = fx.bridge()
    task_id = b.create(fx.spec("false-success-report"), "k")["task_id"]
    b.run(task_id)
    body = review_for(b.artifacts(task_id), "approve", "probe")
    with pytest.raises(BridgeError) as first:
        b.review(task_id, body)
    with pytest.raises(BridgeError) as second:
        b.review(task_id, body)
    assert first.value.code == second.value.code == "APPROVAL_GATE_FAILED"
    assert second.value.details["receipt"]["duplicate"] is True


def test_supervisor_blocked_verdict(fx: Fixture) -> None:
    b = fx.bridge()
    task_id = b.create(fx.spec("success"), "k")["task_id"]
    b.run(task_id)
    receipt = b.review(task_id, review_for(b.artifacts(task_id), "blocked", "r1"))
    assert receipt["resulting_state"] == "BLOCKED"
    assert b.status(task_id)["state_reason"] == "supervisor_blocked"


# --- verify ------------------------------------------------------------------------------------


def test_verify_rebinds_evidence_after_candidate_change(fx: Fixture) -> None:
    b = fx.bridge()
    task_id = b.create(fx.spec("bug-then-repair"), "k")["task_id"]
    b.run(task_id)
    old = b.artifacts(task_id)
    assert old["verification"]["status"] == "failed"
    # e.g. the supervisor fixes the candidate by hand in the task worktree
    worktree = Path(b.status(task_id)["worktree"])
    (worktree / "tagnorm/normalize.py").write_text(fake_executor.CORRECT_IMPL)
    with pytest.raises(BridgeError) as exc:
        b.review(task_id, review_for(old, "approve", "stale"))
    assert exc.value.code == "STALE_REVIEW"
    receipt = b.verify(task_id)
    assert receipt["verification_status"] == "passed"
    assert receipt["snapshot_digest"] != old["snapshot_digest"]
    new = b.artifacts(task_id)
    # the old approve is stale; a fresh approve must bind to the new snapshot
    assert new["approval_gate"]["approvable"]
    b.review(task_id, review_for(new, "approve", "fresh"))
    assert b.status(task_id)["state"] == "SUCCEEDED"
    assert len(b.store.list_attempts(task_id)) == 1


def test_verify_requires_awaiting_review(fx: Fixture) -> None:
    b = fx.bridge()
    task_id = b.create(fx.spec(), "k")["task_id"]
    with pytest.raises(BridgeError) as exc:
        b.verify(task_id)
    assert exc.value.code == "STATE_CONFLICT"


# --- crash windows -----------------------------------------------------------------------------


def test_r02_crash_after_dispatch_record_is_not_redispatched(fx: Fixture, tmp_path: Path) -> None:
    task_id = created_task(fx, tmp_path, "success")
    code, payload = fx.cli("run", task_id, check_ok=None, env=fault_env("after_starting_commit"))
    assert code == 70
    store = Store(fx.state_dir / "bridge.sqlite3")
    assert store.get_task(task_id).state.value == "STARTING"
    code, payload = fx.cli("run", task_id, check_ok=False)
    assert payload["error"]["code"] == "STATE_CONFLICT"
    _, report = fx.cli("recover", task_id)
    assert report["state_after"] == "INTERRUPTED"
    details = store.get_task(task_id).state_details
    assert details is not None
    assert details["outcome_known"] is False and details["phase"] == "launch"
    assert details["signalled"] is False
    attempts = store.list_attempts(task_id)
    assert len(attempts) == 1 and attempts[0].pid is None
    # retry needs an explicit acknowledgement because the launch outcome is unknown
    _, err = fx.cli("recover", task_id, "--resolve", "retry", check_ok=False)
    assert err["error"]["code"] == "CANNOT_CONFIRM_EXIT"
    _, resolved = fx.cli("recover", task_id, "--resolve", "retry", "--acknowledge-unknown")
    assert resolved["state_after"] == "READY"
    _, run = fx.cli("run", task_id)
    assert run["attempt_seq"] == 2 and run["attempt_kind"] == "retry"
    assert run["state"] == "AWAITING_REVIEW"


def test_r02_crash_after_spawn_before_record(fx: Fixture, tmp_path: Path) -> None:
    task_id = created_task(fx, tmp_path, "success")
    code, _ = fx.cli("run", task_id, check_ok=None, env=fault_env("after_spawn_before_record"))
    assert code == 70
    store = Store(fx.state_dir / "bridge.sqlite3")
    assert store.get_task(task_id).state.value == "STARTING"
    _, report = fx.cli("recover", task_id)
    assert report["state_after"] == "INTERRUPTED"
    assert store.list_attempts(task_id)[0].pgid is None  # nothing we could prove we own


def test_crash_during_verification_resumes_without_rerunning_executor(
    fx: Fixture, tmp_path: Path
) -> None:
    task_id = created_task(fx, tmp_path, "success")
    code, _ = fx.cli("run", task_id, check_ok=None, env=fault_env("after_verifying_commit"))
    assert code == 70
    store = Store(fx.state_dir / "bridge.sqlite3")
    assert store.get_task(task_id).state.value == "VERIFYING"
    _, report = fx.cli("recover", task_id)
    assert report["state_after"] == "AWAITING_REVIEW"
    assert "verification re-run" in report["actions"][0]
    assert len(store.list_attempts(task_id)) == 1


# --- races and cancellation -------------------------------------------------------------------


def test_r05_two_runners_race_for_one_task(fx: Fixture, tmp_path: Path) -> None:
    task_id = created_task(fx, tmp_path, "success")
    procs = [spawn_cli(fx, "run", task_id) for _ in range(2)]
    results = [json.loads(p.communicate(timeout=120)[0]) for p in procs]
    oks = [r for r in results if r["ok"]]
    conflicts = [r for r in results if not r["ok"]]
    assert len(oks) == 1 and len(conflicts) == 1
    assert conflicts[0]["error"]["code"] == "STATE_CONFLICT"
    assert len(Store(fx.state_dir / "bridge.sqlite3").list_attempts(task_id)) == 1


def test_r06_cancel_stops_owned_process_group(fx: Fixture, tmp_path: Path) -> None:
    task_id = created_task(fx, tmp_path, "hang", wall_timeout_seconds=120)
    runner = spawn_cli(fx, "run", task_id)
    store = Store(fx.state_dir / "bridge.sqlite3")
    try:
        wait_for(store, task_id, lambda t: t.state.value == "RUNNING")
        executor_pid = store.list_attempts(task_id)[0].pid
        assert executor_pid and alive(executor_pid)
        wait_steady(executor_pid)
        _, result = fx.cli("cancel", task_id, "--wait", "30")
        assert result["status"] == "cancelled"
        runner.communicate(timeout=60)
    finally:
        if runner.poll() is None:
            runner.kill()
    assert store.get_task(task_id).state.value == "CANCELLED"
    assert not alive(executor_pid)
    attempt = store.list_attempts(task_id)[0]
    log = fx.state_dir / "artifacts" / task_id / attempt.attempt_id / "executor.stdout.log"
    child = next(json.loads(x) for x in log.read_text().splitlines() if '"child"' in x)
    assert not alive(child["pid"])
    assert attempt.outcome == "cancelled" and attempt.exit_confirmed


def test_sigterm_to_runner_interrupts_with_known_outcome(fx: Fixture, tmp_path: Path) -> None:
    task_id = created_task(fx, tmp_path, "hang", wall_timeout_seconds=120)
    runner = spawn_cli(fx, "run", task_id)
    store = Store(fx.state_dir / "bridge.sqlite3")
    wait_for(store, task_id, lambda t: t.state.value == "RUNNING")
    executor_pid = store.list_attempts(task_id)[0].pid
    assert executor_pid
    wait_steady(executor_pid)
    runner.send_signal(signal.SIGTERM)
    runner.communicate(timeout=60)
    task = store.get_task(task_id)
    assert task.state.value == "INTERRUPTED"
    assert task.state_details and task.state_details["outcome_known"] is True
    assert not alive(executor_pid)
    _, resolved = fx.cli("recover", task_id, "--resolve", "retry")
    assert resolved["state_after"] == "READY"


def test_hard_killed_runner_never_signals_unproven_processes(fx: Fixture, tmp_path: Path) -> None:
    task_id = created_task(fx, tmp_path, "hang", wall_timeout_seconds=120)
    runner = spawn_cli(fx, "run", task_id)
    store = Store(fx.state_dir / "bridge.sqlite3")
    wait_for(store, task_id, lambda t: t.state.value == "RUNNING")
    attempt = store.list_attempts(task_id)[0]
    assert attempt.pgid
    # Wait until the fake has started its helper child (steady "hanging" state); killing the
    # runner earlier can make the fake die of a broken stdout pipe, which is also legitimate
    # but would not exercise the "possibly alive, not ours to signal" path.
    wait_steady(attempt.pgid)
    runner.kill()
    runner.wait(timeout=30)
    try:
        _, report = fx.cli("recover", task_id)
        assert report["runner_alive"] is False
        assert report["state_after"] == "INTERRUPTED"
        details = store.get_task(task_id).state_details
        assert details is not None
        assert details["outcome_known"] is False
        assert details["process_group_possibly_alive"] is True
        assert details["signalled"] is False
        # The orphaned executor is still running: the bridge did not kill what it cannot prove.
        assert group_alive(attempt.pgid)
        _, err = fx.cli("cancel", task_id, check_ok=False)
        assert err["error"]["code"] == "CANNOT_CONFIRM_EXIT"
        _, err = fx.cli(
            "recover", task_id, "--resolve", "retry", "--acknowledge-unknown", check_ok=False
        )
        assert err["error"]["code"] == "CANNOT_CONFIRM_EXIT"  # group still alive
    finally:
        try:
            os.killpg(attempt.pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    end = time.monotonic() + 10
    while group_alive(attempt.pgid) and time.monotonic() < end:
        time.sleep(0.05)
    _, resolved = fx.cli("recover", task_id, "--resolve", "retry", "--acknowledge-unknown")
    assert resolved["state_after"] == "READY"


def test_cancel_without_process(fx: Fixture) -> None:
    b = fx.bridge()
    t1 = b.create(fx.spec(), "k1")["task_id"]
    assert b.cancel(t1)["status"] == "cancelled"
    with pytest.raises(BridgeError) as exc:
        b.cancel(t1)
    assert exc.value.code == "STATE_CONFLICT"
    t2 = b.create(fx.spec("success"), "k2")["task_id"]
    b.run(t2)
    assert b.cancel(t2)["state"] == "CANCELLED"


def test_blocked_task_retry_and_budget(fx: Fixture) -> None:
    b = fx.bridge()
    task_id = b.create(fx.spec("permission-denied", max_attempts=2, max_repair_cycles=1), "k")[
        "task_id"
    ]
    assert b.run(task_id)["state"] == "BLOCKED"
    assert b.recover(task_id)["actions"] == ["no automatic action for this state"]
    assert b.recover(task_id, resolve="retry")["state_after"] == "READY"
    second = b.run(task_id)
    assert second["attempt_kind"] == "retry" and second["state"] == "BLOCKED"
    final = b.recover(task_id, resolve="retry")
    assert final["state_after"] == "FAILED" and final["state_reason"] == "attempt_budget_exhausted"
    assert len(b.store.list_attempts(task_id)) == 2
