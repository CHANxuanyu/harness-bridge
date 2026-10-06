"""Bounded trusted setup with real local subprocesses, plus explicit fault injections."""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from harness_bridge.coordination import AdvisorClaim
from harness_bridge.errors import BridgeError
from harness_bridge.runner import ProcessOutcome
from harness_bridge.service import Bridge
from harness_bridge.state import TaskState as S
from harness_bridge.workspace import checkout_fingerprint
from tests.conftest import Fixture
from tests.helpers.reviews import review_for
from tests.integration.test_claude_stub_flow import STREAM, argv_log, claude_spec
from tests.integration.test_claude_stub_flow import stub as stub
from tests.integration.test_coordination import goal_spec, setup_goal, takeover
from tests.integration.test_dependency_baselines import children
from tests.integration.test_goal_planning import control, plan, submit
from tests.integration.test_recovery import fault_env, spawn_cli, wait_for

GOOD = (
    "from pathlib import Path; p=Path('__pycache__'); p.mkdir(exist_ok=True); "
    "(p/'ready').write_text('ready')"
)


def setup_plan(fx: Fixture, key: str = "a", code: str = GOOD, **overrides: Any) -> dict[str, Any]:
    p = plan(fx, key)
    p["preparation"] = {
        "steps": [{"id": "install", "argv": [sys.executable, "-c", code], "timeout_seconds": 15}],
        "outputs": [{"path": "__pycache__/ready", "kind": "cache"}],
        **overrides,
    }
    p["environment"] = {"files": ["__pycache__/ready"]}
    return p


def setup(
    fx: Fixture, code: str = GOOD, **overrides: Any
) -> tuple[Bridge, dict[str, Any], str, str]:
    b, g = setup_goal(fx)
    child = children(b, g, setup_plan(fx, code=code, **overrides))["a"]
    return b, g, child, b.materialize(child)["task_id"]


def prepare_args(b: Bridge, child: str, key: str = "prepare") -> list[str]:
    assert b.advisor_claim is not None
    return [
        "child",
        "prepare",
        child,
        "--idempotency-key",
        key,
        "--advisor-binding",
        b.advisor_claim.binding_id,
        "--advisor-epoch",
        str(b.advisor_claim.epoch),
    ]


def test_prepare_is_explicit_durable_idempotent_and_does_not_charge_executor(fx: Fixture) -> None:
    b, g, child, task = setup(fx)
    original = checkout_fingerprint(str(fx.repo))
    assert not b.child_preflight(child)["ready"]
    with pytest.raises(BridgeError) as err:
        b.run(task)
    assert err.value.code == "PREFLIGHT_FAILED"
    _, receipt = fx.cli(*prepare_args(b, child))
    assert receipt["status"] == "passed" and receipt["exit_confirmed"]
    assert receipt["outputs"][0]["kind"] == "cache"
    assert receipt["outputs"][0]["present"]
    assert b.child_preflight(child)["ready"]
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 0
    assert b.store.get_task(task).state == S.READY
    replay = b.preparations.prepare(child, "prepare")
    assert replay["preparation_id"] == receipt["preparation_id"] and replay["replayed"]
    assert len(b.status(task)["preparation"]["steps"]) == 1
    b.run(task)
    assert b.status(task)["state"] == "AWAITING_REVIEW"
    assert checkout_fingerprint(str(fx.repo)) == original
    b.close()


@pytest.mark.parametrize("case", ["failure", "timeout", "spawn", "cwd", "output", "candidate"])
def test_failed_preparation_blocks_run_and_never_executes_later_steps(
    fx: Fixture, case: str
) -> None:
    b, g = setup_goal(fx)
    code = "raise SystemExit(2)" if case == "failure" else GOOD
    if case == "timeout":
        code = "import time; time.sleep(20)"
    if case == "output":
        code = "print('no output created')"
    if case == "candidate":
        code = GOOD + "; Path('README.md').write_text('unapproved source change')"
    p = setup_plan(fx, code=code)
    p["preparation"]["steps"].append(
        {
            "id": "never",
            "argv": [sys.executable, "-c", "raise SystemExit(99)"],
            "timeout_seconds": 5,
        }
    )
    if case == "timeout":
        p["preparation"]["wall_timeout_seconds"] = 0.2
    if case == "spawn":
        p["preparation"]["steps"][0]["argv"] = ["/nonexistent/hbridge-setup"]
    if case == "cwd":
        p["preparation"]["steps"][0]["cwd"] = "absent-dir"
    # Outputs/candidate are checked after setup steps; remove the later-step fixture there.
    if case in {"output", "candidate"}:
        p["preparation"]["steps"].pop()
    child = children(b, g, p)["a"]
    task = b.materialize(child)["task_id"]
    receipt = b.preparations.prepare(child, "p")
    expected = {
        "failure": "failed",
        "timeout": "timed_out",
        "spawn": "spawn_failed",
        "cwd": "invalid_cwd",
        "output": "requirements_missing",
        "candidate": "candidate_changed",
    }
    assert receipt["status"] == expected[case] and receipt["exit_confirmed"]
    assert all(s["id"] != "never" for s in receipt["steps"])
    assert b.store.get_task(task).state == S.BLOCKED
    assert b.store.list_attempts(task) == []
    with pytest.raises(BridgeError):
        b.run(task)
    assert b.preparations.prepare(child, "p")["replayed"]
    b.close()


def test_known_failure_can_be_explicitly_retried_with_new_key_and_finite_limit(fx: Fixture) -> None:
    code = (
        "from pathlib import Path; p=Path('__pycache__'); p.mkdir(exist_ok=True); "
        "marker=p/'first'; existed=marker.exists(); marker.touch(); "
        "(p/'ready').write_text('ok') if existed else None; raise SystemExit(0 if existed else 2)"
    )
    b, g, child, task = setup(fx, code=code, max_runs=2)
    first = b.preparations.prepare(child, "first")
    assert first["status"] == "failed"
    b.recover(task, resolve="retry")
    assert b.preparations.prepare(child, "first")["status"] == "failed"
    assert not b.child_preflight(child)["ready"]
    assert b.preparations.prepare(child, "second")["status"] == "passed"
    with pytest.raises(BridgeError) as err:
        b.preparations.prepare(child, "third")
    assert err.value.code == "BUDGET_EXHAUSTED"
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 0
    b.close()


def test_candidate_changes_and_missing_outputs_invalidate_setup_evidence(fx: Fixture) -> None:
    b, _, child, task = setup(fx)
    b.preparations.prepare(child, "first")
    root = Path(b.store.get_task(task).worktree_path)
    (root / "__pycache__/ready").unlink()
    assert not b.child_preflight(child)["ready"]
    b.preparations.prepare(child, "second")
    (root / "tagnorm/new.py").write_text("# changed\n")
    assert not b.child_preflight(child)["ready"]
    with pytest.raises(BridgeError) as err:
        b.run(task)
    assert err.value.code == "PREFLIGHT_FAILED"
    b.preparations.prepare(child, "third")
    assert b.child_preflight(child)["ready"]
    b.close()


def test_repair_requires_fresh_preparation_and_preserves_feedback_and_session(
    fx: Fixture, stub: Path, tmp_path: Path
) -> None:
    # The fake executor deliberately starts new synthetic sessions. Exercise the Claude
    # adapter with its offline stub to verify actual --resume binding across preparation.
    b, g = setup_goal(fx, allowed_executors=["claude-code"])
    log = tmp_path / "stub-argv.jsonl"
    b.env.update(
        {
            "HBRIDGE_STUB_FIXTURE": str(STREAM / "success.jsonl"),
            "HBRIDGE_STUB_ARGV_LOG": str(log),
            "HBRIDGE_STUB_EDIT": "buggy",
        }
    )
    p = setup_plan(fx)
    p["task"]["executor"] = claude_spec(fx)["executor"]
    child = children(b, g, p)["a"]
    task = b.materialize(child)["task_id"]
    first_setup = b.preparations.prepare(child, "initial-setup")
    assert b.run(task, executor_binary=str(stub))["verification_status"] == "failed"
    first_attempt = b.store.list_attempts(task)[0]
    b.review(task, review_for(b.artifacts(task), "changes_requested", "fix"))
    with pytest.raises(BridgeError) as err:
        b.run(task, executor_binary=str(stub))
    assert err.value.code == "PREFLIGHT_FAILED"
    assert b.store.get_task(task).attempts_used == 1
    next_setup = b.preparations.prepare(child, "repair-setup")
    assert next_setup["preparation_id"] != first_setup["preparation_id"]
    b.env["HBRIDGE_STUB_EDIT"] = "correct"
    second = b.run(task, executor_binary=str(stub))
    assert second["attempt_kind"] == "repair" and second["verification_status"] == "passed"
    second_attempt = b.store.list_attempts(task)[1]
    assert second_attempt.feedback[0]["explanation"] == "fix it"
    assert second_attempt.session_id == first_attempt.session_id
    calls = argv_log(log)
    assert len(calls) == 2 and calls[1]["argv"][-2:] == ["--resume", first_attempt.session_id]
    assert "fix it" in calls[1]["stdin_text"] and child in calls[1]["stdin_text"]
    b.review(task, review_for(b.artifacts(task), "approve", "done"))
    assert b.store.get_task(task).state == S.SUCCEEDED
    b.close()


def test_preparation_scrubs_environment_and_keeps_logs_bounded_and_redacted(fx: Fixture) -> None:
    code = GOOD + (
        "; import os; assert 'ANTHROPIC_API_KEY' not in os.environ; "
        "assert 'HBRIDGE_TEST_FAULT' not in os.environ; "
        "assert str(Path.home()).endswith('/home'); "
        "print('sk-ant-' + 'a'*60); print('x'*50000)"
    )
    b, _, child, _ = setup(fx, code=code, max_log_bytes=8192)
    b.env["ANTHROPIC_API_KEY"] = "test-environment-only"
    b.env["HBRIDGE_TEST_FAULT"] = "not inherited"
    receipt = b.preparations.prepare(child, "p")
    assert receipt["status"] == "passed"
    step = receipt["steps"][0]
    assert step["stdout"]["truncated"] and step["stdout"]["redactions"]
    assert step["stdout"]["stored_bytes"] < 8192
    b.close()


@pytest.mark.parametrize(
    "case", ["harness", "escape", "secret-output", "duplicate-step", "duplicate-resource"]
)
def test_invalid_preparation_plan_is_rejected(fx: Fixture, case: str) -> None:
    b, g = setup_goal(fx)
    p = setup_plan(fx)
    cfg = p["preparation"]
    if case == "harness":
        cfg["steps"][0]["argv"] = ["claude", "-p", "test"]
    elif case == "escape":
        cfg["steps"][0]["cwd"] = "../outside"
    elif case == "secret-output":
        cfg["outputs"][0]["path"] = ".env"
    elif case == "duplicate-step":
        cfg["steps"].append(cfg["steps"][0])
    else:
        cfg["resources"] = ["cache", "cache"]
    with pytest.raises(BridgeError) as err:
        submit(b, g, p)
    assert err.value.code == "INVALID_INPUT"
    assert not b.store.list_tasks()
    b.close()


def test_resource_claim_is_exclusive_until_terminal_confirmed_stop(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    ids = children(
        b,
        g,
        setup_plan(fx, "a", resources=["shared-cache"]),
        setup_plan(fx, "b", resources=["shared-cache"]),
    )
    a = b.materialize(ids["a"])["task_id"]
    c = b.materialize(ids["b"])["task_id"]
    b.preparations.prepare(ids["a"], "p")
    with pytest.raises(BridgeError) as err:
        b.preparations.prepare(ids["b"], "p")
    assert err.value.details["owner_task_id"] == a
    with b.store.transaction() as cur:
        assert b.preparations.latest(cur, c) is None
    b.run(a)
    b.review(a, review_for(b.artifacts(a), "approve", "approve"))
    assert b.preparations.prepare(ids["b"], "p")["status"] == "passed"
    b.close()


def test_parallel_prepare_calls_reserve_one_run(fx: Fixture) -> None:
    b, _, child, task = setup(fx)
    barrier = Barrier(2)
    claim = b.advisor_claim

    def prepare(_: int) -> dict[str, Any]:
        peer = Bridge(fx.state_dir, advisor_claim=claim)
        barrier.wait(timeout=10)
        try:
            return peer.preparations.prepare(child, "same")
        finally:
            peer.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(prepare, [1, 2]))
    assert results[0]["preparation_id"] == results[1]["preparation_id"]
    assert b.status(task)["preparation"]["status"] == "passed"
    with b.store.transaction() as cur:
        assert cur.execute("SELECT count(*) FROM preparation_runs").fetchone()[0] == 1
    b.close()


@pytest.mark.parametrize("unknown", [False, True])
def test_resource_claim_spans_projects_and_unknown_owner_is_never_released(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch, unknown: bool
) -> None:
    b, _, child, task = setup(fx, resources=["port:fixture"])
    if unknown:
        monkeypatch.setattr(
            "harness_bridge.preparation.run_process", lambda *a, **kw: ProcessOutcome()
        )
    b.preparations.prepare(child, "p")
    if unknown:
        b.recover(task, resolve="fail")
    other_fixture = Fixture(fx.base / "second-project")
    g = b.coordination.create(goal_spec(other_fixture), "second-project")
    b.advisor_claim = AdvisorClaim.model_validate(g["advisor_claim"])
    next_child = children(b, g, setup_plan(other_fixture, resources=["port:fixture"]))["a"]
    next_task = b.materialize(next_child)["task_id"]
    with pytest.raises(BridgeError) as err:
        b.preparations.prepare(next_child, "p")
    assert err.value.details["resource"] == "port:fixture"
    assert err.value.details["owner_task_id"] == task
    with b.store.transaction() as cur:
        assert b.preparations.latest(cur, next_task) is None
    b.close()


@pytest.mark.parametrize("cancel_kind", ["task", "goal", "signal"])
def test_active_preparation_cancels_owned_process_before_releasing_slot(
    fx: Fixture, cancel_kind: str
) -> None:
    b, g, child, task = setup(fx, code="import time; time.sleep(60)")
    proc = spawn_cli(fx, *prepare_args(b, child))
    try:
        wait_for(
            b.store,
            task,
            lambda t: (
                t.state == S.PREPARING
                and bool((b.status(task)["preparation"]["active_process"] or {}).get("pid"))
            ),
        )
        if cancel_kind == "goal":
            control(b, g, "cancel")
        elif cancel_kind == "task":
            b.cancel(task)
        else:
            proc.send_signal(signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=20)
        assert proc.returncode == 0, stderr
        receipt = json.loads(stdout)
        assert receipt["exit_confirmed"]
        assert receipt["status"] == ("interrupted" if cancel_kind == "signal" else "cancelled")
        assert b.store.get_task(task).state == (
            S.INTERRUPTED if cancel_kind == "signal" else S.CANCELLED
        )
        assert b.store.list_attempts(task) == []
        if cancel_kind == "signal":
            b.recover(task, resolve="retry")
            assert b.store.get_task(task).state == S.READY
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.communicate(timeout=20)
        b.close()


@pytest.mark.parametrize("point", ["after_preparation_reserved", "after_preparation_spawn"])
def test_crash_recovery_never_restarts_or_releases_unknown_reservation(
    fx: Fixture, point: str
) -> None:
    b, g, child, task = setup(fx, code="import time; time.sleep(60)", resources=["db:fixture"])
    proc = spawn_cli(fx, *prepare_args(b, child), env=fault_env(point))
    pgid = None
    try:
        proc.communicate(timeout=20)
        assert proc.returncode == 70
        latest = b.status(task)["preparation"]
        pgid = (latest["active_process"] or {}).get("pgid")
        recovered = b.recover(task)
        assert recovered["state_after"] == "INTERRUPTED"
        with pytest.raises(BridgeError) as err:
            b.recover(task, resolve="retry", acknowledge_unknown=True)
        assert err.value.code == "CANNOT_CONFIRM_EXIT"
        b.recover(task, resolve="fail")
        control(b, g, "cancel")
        assert b.coordination.status(g["goal_id"])["state"] == "NEEDS_ATTENTION"
        assert b.coordination.status(g["goal_id"])["pending_stop_tasks"] == [task]
        assert b.store.list_attempts(task) == []
        with b.store.transaction() as cur:
            assert cur.execute("SELECT count(*) FROM preparation_resources").fetchone()[0] == 1
    finally:
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=20)
        b.close()


def test_unconfirmed_process_fixture_blocks_other_goal_even_after_failed_resolution(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, _, child, task = setup(fx)
    monkeypatch.setattr("harness_bridge.preparation.run_process", lambda *a, **kw: ProcessOutcome())
    assert b.preparations.prepare(child, "p")["status"] == "unknown"
    b.recover(task, resolve="fail")
    other = b.coordination.create(goal_spec(fx, objective="Other"), "other")
    b.advisor_claim = AdvisorClaim.model_validate(other["advisor_claim"])
    t = b.create(fx.spec(), "other-task", goal_id=other["goal_id"])["task_id"]
    with pytest.raises(BridgeError) as err:
        b.run(t)
    assert err.value.code == "STATE_CONFLICT"
    b.close()


def test_takeover_allows_accepted_preparation_completion_but_fences_new_steps(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, g, child, task = setup(fx)
    original = b.preparations.inventory
    new_claim = None

    def change(*args: Any) -> Any:
        nonlocal new_claim
        peer = fx.bridge()
        new_claim = takeover(peer, g)["advisor_claim"]
        peer.close()
        return original(*args)

    monkeypatch.setattr(b.preparations, "inventory", change)
    assert b.preparations.prepare(child, "p")["status"] == "passed"
    assert b.store.get_task(task).state == S.READY
    with pytest.raises(BridgeError) as err:
        b.preparations.prepare(child, "again")
    assert err.value.code == "STALE_ADVISOR"
    assert new_claim is not None
    b.close()


def test_cancel_after_postchecks_does_not_revive_preparing_task(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, _, child, task = setup(fx)
    original = b._child_context_for_preparation
    # Model a cancellation arriving after the last runner poll: only the final
    # transactional cancel_requested read can observe it.
    monkeypatch.setattr(b, "_should_stop_factory", lambda _: lambda: None)

    def cancel(task_id: str) -> dict[str, Any]:
        result = original(task_id)
        b.cancel(task_id)
        return result

    monkeypatch.setattr(b, "_child_context_for_preparation", cancel)
    assert b.preparations.prepare(child, "p")["status"] == "cancelled"
    assert b.store.get_task(task).state == S.CANCELLED
    b.close()


def test_v4_upgrade_preserves_old_environment_plan_digest(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    p = plan(fx, "old")
    p["environment"] = {"files": ["README.md"]}
    batch = submit(b, g, p)
    child = batch["children"][0]["child_id"]
    task = b.materialize(child)["task_id"]
    before = b.plans.status(child)
    path, claim = b.store.db_path, b.advisor_claim
    b.close()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE preparation_resources")
        conn.execute("DROP TABLE preparation_runs")
        conn.execute("UPDATE meta SET value='4' WHERE key='schema_revision'")
    b = Bridge(fx.state_dir, advisor_claim=claim)
    assert submit(b, g, p)["replayed"]
    assert b.plans.status(child) == before
    assert b.materialize(child)["task_id"] == task
    b.run(task)
    assert b.store.get_task(task).state == S.AWAITING_REVIEW
    b.close()
