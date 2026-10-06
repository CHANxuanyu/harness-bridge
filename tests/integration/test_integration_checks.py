"""Offline integration acceptance and Advisor decisions; no model subprocesses."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from harness_bridge.coordination import AdvisorClaim
from harness_bridge.errors import BridgeError
from harness_bridge.service import Bridge
from harness_bridge.store import SCHEMA_REVISION
from harness_bridge.workspace import checkout_fingerprint
from tests.conftest import Fixture
from tests.integration.test_coordination import goal_spec, takeover
from tests.integration.test_goal_planning import control, plan, submit
from tests.integration.test_integration_candidates import materialize, one, request


def command(code: str = "print('accepted')", **options: Any) -> dict[str, Any]:
    return {
        "id": "acceptance",
        "argv": [sys.executable, "-c", code],
        "cwd": ".",
        "timeout_seconds": 5,
        "required": True,
        "trust": "external-acceptance",
        **options,
    }


def candidate(
    fx: Fixture, checks: list[dict[str, Any]] | None = None
) -> tuple[Bridge, dict[str, Any], str]:
    b, g, task = one(fx)
    spec = request(fx, task)
    if checks is not None:
        spec["verification"] = checks
    ready = materialize(b, b.integrations.freeze(g["goal_id"], spec, "integration"))
    return b, g, ready["integration_id"]


def decision(b: Bridge, ident: str, key: str = "approve", **extra: Any) -> dict[str, Any]:
    return {
        **b.integrations.status(ident)["review_template"],
        "idempotency_key": key,
        **extra,
    }


def claim_args(b: Bridge) -> list[str]:
    assert b.advisor_claim is not None
    return [
        "--advisor-binding",
        b.advisor_claim.binding_id,
        "--advisor-epoch",
        str(b.advisor_claim.epoch),
    ]


def test_complete_acceptance_review_replay_keeps_source_and_executor_budget(fx: Fixture) -> None:
    b, g, ident = candidate(fx)
    budget = b.coordination.status(g["goal_id"])["budget"]
    source = checkout_fingerprint(str(fx.repo))
    run = b.integration_checks.verify(ident, "verify")
    assert run["status"] == "passed" and run["exit_confirmed"]
    assert run["fingerprint_before"] == run["fingerprint_after"]
    assert b.integrations.status(ident)["phase"] == "AWAITING_REVIEW"
    assert b.coordination.status(g["goal_id"])["state"] == "NEEDS_ATTENTION"
    data = decision(b, ident)
    accepted = b.integration_checks.review(ident, data)
    assert accepted["status"] == "accepted"
    assert b.integration_checks.review(ident, data) == {**accepted, "replayed": True}
    assert b.integration_checks.verify(ident, "verify") == {**run, "replayed": True}
    status = b.integrations.status(ident)
    assert status["phase"] == "APPROVED" and status["approval_current"]
    assert checkout_fingerprint(str(fx.repo)) == source
    goal = b.coordination.status(g["goal_id"])
    assert goal["budget"] == budget
    assert goal["delivery"] == "not_implemented" and goal["state"] == "ACTIVE"
    b.close()


@pytest.mark.parametrize("failure", ["failed", "timeout", "missing", "cwd", "mutation"])
def test_bad_checks_cannot_be_approved_and_rejections_are_durable(
    fx: Fixture, failure: str
) -> None:
    checks = {
        "failed": command("raise SystemExit(1)"),
        "timeout": command("import time; time.sleep(10)", timeout_seconds=0.1),
        "missing": command(argv=["hbridge-nonexistent-test-executable"]),
        "cwd": command(cwd="does-not-exist"),
        "mutation": command("from pathlib import Path; Path('tagnorm/mutated').touch()"),
    }
    b, g, ident = candidate(fx, [checks[failure]])
    run = b.integration_checks.verify(ident, "verify")
    assert run["exit_confirmed"] and run["status"] in ("failed", "invalidated")
    data = decision(b, ident)
    with pytest.raises(BridgeError) as rejected:
        b.integration_checks.review(ident, data)
    assert rejected.value.code == "APPROVAL_GATE_FAILED"
    with pytest.raises(BridgeError) as replay:
        b.integration_checks.review(ident, data)
    assert replay.value.details["replayed"]
    assert replay.value.details["receipt"] == rejected.value.details["receipt"]
    assert not b.integrations.status(ident)["approval_current"]
    before = b.coordination.status(g["goal_id"])["budget"]
    fix = decision(
        b,
        ident,
        "fix",
        verdict="changes_requested",
        findings=[{"severity": "major", "explanation": "Integrated acceptance is not satisfied"}],
    )
    b.integration_checks.review(ident, fix)
    assert b.integrations.status(ident)["phase"] == "CHANGES_REQUESTED"
    assert b.coordination.status(g["goal_id"])["budget"] == before
    b.close()


def test_optional_failure_is_warning_but_not_an_executor_call(fx: Fixture) -> None:
    b, _, ident = candidate(
        fx, [command(), command("raise SystemExit(1)", id="optional", required=False)]
    )
    run = b.integration_checks.verify(ident, "verify")
    assert run["status"] == "passed" and run["warnings"]
    b.integration_checks.review(ident, decision(b, ident))
    assert b.integrations.status(ident)["approval_current"]
    b.close()


@pytest.mark.parametrize("change", ["log", "manifest", "workspace", "membership"])
def test_approval_rechecks_evidence_and_invalidates_current_approval(
    fx: Fixture, change: str
) -> None:
    b, g, ident = candidate(fx, [command()])
    run = b.integration_checks.verify(ident, "verify")
    data = decision(b, ident)
    b.integration_checks.review(ident, data)
    if change in ("log", "manifest"):
        name = "acceptance.stdout.log" if change == "log" else "manifest.json"
        (b.integration_checks.directory(run) / name).write_text("changed evidence")
    elif change == "workspace":
        root = Path(b.integrations.status(ident)["workspace"]["path"])
        (root / "tagnorm/late.txt").write_text("late edit")
    else:
        submit(b, g, plan(fx, "extra"), key="extra")
    status = b.integrations.status(ident)
    assert not status["approval_current"] and status["approval_blockers"]
    with pytest.raises(BridgeError):
        b.integration_checks.review(ident, {**data, "idempotency_key": "again"})
    # A historical receipt remains historical; replay never refreshes approval.
    assert b.integration_checks.review(ident, data)["replayed"]
    assert not b.integrations.status(ident)["approval_current"]
    b.close()


def test_new_run_and_takeover_invalidate_old_review_without_automatic_reexecution(
    fx: Fixture,
) -> None:
    b, g, ident = candidate(fx, [command()])
    b.integration_checks.verify(ident, "first")
    old = decision(b, ident)
    b.integration_checks.review(ident, old)
    b.integration_checks.verify(ident, "second")
    assert not b.integrations.status(ident)["approval_current"]
    assert b.integration_checks.review(ident, old)["replayed"]
    with pytest.raises(BridgeError) as stale:
        b.integration_checks.review(ident, {**old, "idempotency_key": "stale"})
    assert stale.value.code == "STALE_REVIEW"
    current = decision(b, ident, "current")
    b.integration_checks.review(ident, current)
    new_claim = takeover(b, g)["advisor_claim"]
    assert not b.integrations.status(ident)["approval_current"]
    for action in (
        lambda: b.integration_checks.verify(ident, "second"),
        lambda: b.integration_checks.review(ident, current),
        lambda: b.integration_checks.recover(ident),
    ):
        with pytest.raises(BridgeError) as stale:
            action()
        assert stale.value.code == "STALE_ADVISOR"
    b.advisor_claim = AdvisorClaim.model_validate(new_claim)
    b.integration_checks.review(ident, {**current, "idempotency_key": "new-advisor"})
    assert b.integrations.status(ident)["approval_current"]
    b.close()


def test_same_key_races_execute_once_and_review_once(fx: Fixture) -> None:
    marker = fx.base / "executions"
    code = (
        f"from pathlib import Path; p=Path({str(marker)!r}); "
        "p.write_text(p.read_text()+'x' if p.exists() else 'x')"
    )
    b, _, ident = candidate(fx, [command(code)])
    claim = b.advisor_claim

    def race(review: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        barrier = Barrier(2)

        def run(_: int) -> dict[str, Any]:
            peer = Bridge(fx.state_dir, advisor_claim=claim)
            try:
                barrier.wait(timeout=10)
                if review:
                    return peer.integration_checks.review(ident, review)
                return peer.integration_checks.verify(ident, "same-key")
            finally:
                peer.close()

        with ThreadPoolExecutor(2) as pool:
            return list(pool.map(run, [0, 1]))

    runs = race()
    assert runs[0]["run_id"] == runs[1]["run_id"]
    assert sorted(r["replayed"] for r in runs) == [False, True]
    assert marker.read_text() == "x"
    reviews = race(decision(b, ident))
    assert reviews[0]["review_id"] == reviews[1]["review_id"]
    assert sorted(r["replayed"] for r in reviews) == [False, True]
    with pytest.raises(BridgeError) as conflict:
        b.integration_checks.review(ident, decision(b, ident, reviewer_label="changed"))
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    b.close()


@pytest.mark.parametrize(
    "point,confirmed",
    [
        ("after_integration_verification_reserved", True),
        ("before_integration_check_spawn", False),
        ("after_integration_check_recorded", True),
    ],
)
def test_process_crash_recovery_never_reexecutes_and_unknown_keeps_hold(
    fx: Fixture, point: str, confirmed: bool
) -> None:
    marker = fx.base / "executed"
    b, g, ident = candidate(
        fx, [command(f"from pathlib import Path; Path({str(marker)!r}).touch()")]
    )
    code, _ = fx.cli(
        "integration",
        "verify",
        ident,
        "--idempotency-key",
        "crash",
        *claim_args(b),
        check_ok=None,
        env={**os.environ, "HBRIDGE_TEST_FAULT": point},
    )
    assert code == 70
    before = marker.exists()
    recovered = b.integration_checks.recover(ident)
    assert recovered["action"] == "recorded_without_execution"
    assert recovered["verification"]["exit_confirmed"] is confirmed
    assert marker.exists() == before
    assert b.integration_checks.verify(ident, "crash")["replayed"]
    assert marker.exists() == before
    if confirmed:
        assert b.integration_checks.verify(ident, "explicit-new")["status"] == "passed"
    else:
        with pytest.raises(BridgeError):
            b.integration_checks.verify(ident, "explicit-new")
        control(b, g, "cancel")
        status = b.coordination.status(g["goal_id"])
        assert status["state"] == "NEEDS_ATTENTION" and status["pending_stop_integrations"]
        assert b.integration_checks.cancel(ident)["status"] == "cancellation_pending"
        assert b.integration_checks.recover(ident)["action"] == "none"
    b.close()


def wait_started(b: Bridge, ident: str, proc: subprocess.Popen[str]) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        # Observe the durable launch checkpoint without repeatedly taking the writer
        # lock for Git snapshot/status work while the checker is trying to reserve.
        with b.store.transaction() as cur:
            run = b.integration_checks.latest(cur, ident)
        if run and run["active_process"] and run["active_process"].get("pid"):
            return run
        assert proc.poll() is None, proc.communicate()
        time.sleep(0.02)
    raise AssertionError("verification did not start")


@pytest.mark.parametrize("cancel_goal", [False, True])
def test_running_checks_exclude_child_verification_and_cancel_confirmed(
    fx: Fixture, cancel_goal: bool
) -> None:
    b, g, ident = candidate(fx, [command("import time; time.sleep(60)", timeout_seconds=60)])
    original_claim = b.advisor_claim
    other = b.coordination.create(goal_spec(fx), "other-goal")
    b.advisor_claim = AdvisorClaim.model_validate(other["advisor_claim"])
    task = b.create(fx.spec(), "other-task", goal_id=other["goal_id"])["task_id"]
    b.run(task)
    peer = Bridge(fx.state_dir, advisor_claim=b.advisor_claim)
    b.advisor_claim = original_claim
    args = [
        sys.executable,
        "-m",
        "harness_bridge",
        "--state-dir",
        str(fx.state_dir),
        "--json",
        "integration",
        "verify",
        ident,
        "--idempotency-key",
        "run",
        *claim_args(b),
    ]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        running = wait_started(b, ident, proc)
        with pytest.raises(BridgeError) as held:
            peer.verify(task)
        assert held.value.details["reason"] == "integration_verification_exclusive"
        assert b.integration_checks.recover(ident)["action"] == "owner_running"
        with pytest.raises(BridgeError):
            b.integration_checks.verify(ident, "other")
        if cancel_goal:
            control(b, g, "cancel")
            pending = b.coordination.status(g["goal_id"])["pending_stop_integrations"]
            assert pending == [running["run_id"]]
        else:
            b.integration_checks.cancel(ident)
        out, err = proc.communicate(timeout=15)
        assert proc.returncode == 0, err
        stopped = json.loads(out)
        assert stopped["status"] == "cancelled" and stopped["exit_confirmed"]
        assert stopped["active_process"] is None
        assert not b.coordination.status(g["goal_id"])["pending_stop_integrations"]
        if cancel_goal:
            assert b.coordination.status(g["goal_id"])["state"] == "CANCELLED"
        else:
            # Child verification becomes possible only after the owned checker exits.
            assert peer.verify(task)["verification_status"] == "passed"
    finally:
        if proc.poll() is None:
            try:
                b.integration_checks.cancel(ident)
            except BridgeError:
                proc.terminate()  # this test owns the CLI, including a pre-reservation failure
            proc.communicate(timeout=15)
        peer.close()
        b.close()


def test_v7_migration_preserves_frozen_candidate_and_cli_can_verify_review(fx: Fixture) -> None:
    b, _, ident = candidate(fx, [command()])
    args = claim_args(b)
    before = b.integrations.status(ident)
    db = b.store.db_path
    b.close()
    with sqlite3.connect(db) as old:
        old.execute("DROP TABLE integration_reviews")
        old.execute("DROP TABLE integration_verifications")
        old.execute("UPDATE meta SET value='7' WHERE key='schema_revision'")
    b = fx.bridge()
    assert b.integrations.status(ident) == before
    with b.store.transaction() as cur:
        assert (
            int(cur.execute("SELECT value FROM meta WHERE key='schema_revision'").fetchone()[0])
            == SCHEMA_REVISION
        )
    b.close()
    _, run = fx.cli("integration", "verify", ident, "--idempotency-key", "verify", *args)
    assert run["status"] == "passed"
    _, status = fx.cli("integration", "status", ident)
    file = fx.base / "review.json"
    file.write_text(json.dumps({**status["review_template"], "idempotency_key": "approval"}))
    _, reviewed = fx.cli("integration", "review", ident, "--file", str(file), *args)
    assert reviewed["status"] == "accepted"
    _, status = fx.cli("integration", "status", ident)
    assert status["approval_current"]


def test_manifest_write_failure_releases_proven_exit_without_false_success(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, _, ident = candidate(fx, [command()])

    def fail(*args: Any) -> None:
        raise OSError("simulated evidence disk error")

    monkeypatch.setattr("harness_bridge.integration_checks.atomic_write_json", fail)
    run = b.integration_checks.verify(ident, "verify")
    assert run["status"] == "observation_failed" and run["exit_confirmed"]
    with pytest.raises(BridgeError):
        b.integration_checks.review(ident, decision(b, ident))
    assert b.integration_checks.recover(ident)["action"] == "none"
    b.close()


def test_check_environment_is_isolated_and_no_direct_harness_is_dispatched(fx: Fixture) -> None:
    b, g, task = one(fx)
    code = (
        "import os; from pathlib import Path; assert 'OPENAI_API_KEY' not in os.environ; "
        "assert not (Path.home()/'.claude').exists(); print('x'*100000)"
    )
    spec = request(fx, task)
    spec["verification"] = [command(code)]
    ident = materialize(b, b.integrations.freeze(g["goal_id"], spec, "normal"))["integration_id"]
    b.env["OPENAI_API_KEY"] = "test-placeholder-never-logged"
    run = b.integration_checks.verify(ident, "verify")
    assert run["status"] == "passed"
    assert (b.integration_checks.directory(run) / "acceptance.stdout.log").stat().st_size < 70000
    spec["verification"] = [command(argv=["claude", "--version"])]
    with pytest.raises(BridgeError) as denied:
        b.integrations.freeze(g["goal_id"], spec, "bad")
    assert denied.value.code == "INVALID_INPUT"
    assert len(b.coordination.status(g["goal_id"])["integrations"]) == 1
    b.close()


def test_individually_approved_children_can_fail_total_goal_contract(fx: Fixture) -> None:
    from tests.integration.test_coordination import setup_goal
    from tests.integration.test_dependency_baselines import approve, children

    b, g = setup_goal(fx)
    ids = children(b, g, plan(fx, "producer"), plan(fx, "consumer"))
    producer = approve(b, ids["producer"], {"tagnorm/produces.txt": "v1"})
    consumer = approve(b, ids["consumer"], {"tagnorm/expects.txt": "v2"})
    spec = request(fx, producer, consumer)
    spec["verification"] = [
        command(
            "from pathlib import Path; "
            "assert Path('tagnorm/produces.txt').read_text() == "
            "Path('tagnorm/expects.txt').read_text()"
        )
    ]
    ident = materialize(b, b.integrations.freeze(g["goal_id"], spec, "integration"))[
        "integration_id"
    ]
    assert b.integration_checks.verify(ident, "verify")["status"] == "failed"
    with pytest.raises(BridgeError):
        b.integration_checks.review(ident, decision(b, ident))
    assert b.coordination.status(g["goal_id"])["state"] == "NEEDS_ATTENTION"
    b.close()


def test_unknown_optional_check_retains_hold_and_cannot_be_approved(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness_bridge.verification import CheckResult

    b, _, ident = candidate(fx, [command(), command(id="optional", required=False)])
    from harness_bridge.integration_checks import run_checks

    def unknown(commands: Any, **kwargs: Any) -> Any:
        cmd = commands[0]
        if cmd.id != "optional":
            return run_checks(commands, **kwargs)
        return [
            CheckResult(
                cmd.id,
                cmd.trust,
                cmd.required,
                cmd.argv,
                cmd.cwd,
                "unconfirmed",
                exit_confirmed=False,
            )
        ], None

    monkeypatch.setattr("harness_bridge.integration_checks.run_checks", unknown)
    run = b.integration_checks.verify(ident, "verify")
    assert run["status"] == "unknown" and not run["exit_confirmed"]
    with pytest.raises(BridgeError):
        b.integration_checks.review(ident, decision(b, ident))
    with pytest.raises(BridgeError):
        b.integration_checks.verify(ident, "retry")
    b.close()


def test_crash_after_spawn_keeps_uncertain_hold_even_when_checker_later_exits(fx: Fixture) -> None:
    from harness_bridge.runner import group_alive

    b, _, ident = candidate(fx, [command("pass")])
    code, _ = fx.cli(
        "integration",
        "verify",
        ident,
        "--idempotency-key",
        "crash",
        *claim_args(b),
        check_ok=None,
        env={**os.environ, "HBRIDGE_TEST_FAULT": "after_integration_check_spawn"},
    )
    assert code == 70
    with b.store.transaction() as cur:
        run = b.integration_checks.latest(cur, ident)
    assert run and run["active_process"]["pid"]
    pgid = run["active_process"]["pgid"]
    deadline = time.monotonic() + 5
    while group_alive(pgid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not group_alive(pgid)
    result = b.integration_checks.recover(ident)
    assert result["verification"]["status"] == "unknown"
    assert result["verification"]["active_process"]["pgid"] == pgid
    with pytest.raises(BridgeError):
        b.integration_checks.verify(ident, "retry")
    b.close()


def test_explicit_local_check_limit_is_separate_from_executor_budget(fx: Fixture) -> None:
    from harness_bridge.integration_checks import MAX_RUNS

    b, g, ident = candidate(fx, [command()])
    budget = b.coordination.status(g["goal_id"])["budget"]
    for n in range(MAX_RUNS):
        assert b.integration_checks.verify(ident, f"check-{n}")["status"] == "passed"
    with pytest.raises(BridgeError) as exhausted:
        b.integration_checks.verify(ident, "over-limit")
    assert exhausted.value.code == "BUDGET_EXHAUSTED"
    assert b.integration_checks.verify(ident, "check-0")["replayed"]
    assert b.coordination.status(g["goal_id"])["budget"] == budget
    b.close()
