"""Real Bridge/worktree/worker/verifier; simulated bidirectional ZCode peer only."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.runner import group_alive
from harness_bridge.service import Bridge
from tests.conftest import Fixture
from tests.contracts.test_zcode_adapter import settings
from tests.helpers.reviews import review_for
from tests.integration.test_coordination import setup_goal
from tests.integration.test_goal_planning import plan, submit
from tests.integration.test_recovery import wait_for
from tests.integration.test_workers import finished


@pytest.fixture
def peer(tmp_path: Path) -> Path:
    exe = tmp_path / "zc-stand-in"
    helper = Path(__file__).parents[1] / "helpers/zc_peer.py"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{helper}" "$@"\n')
    exe.chmod(0o755)
    return exe


def zc_spec(fx: Fixture, **limits: Any) -> dict[str, Any]:
    data = fx.spec(**limits)
    data["limits"]["max_turns_per_attempt"] = None
    data["executor"] = settings().model_dump()
    return data


def bridge(fx: Fixture, **env: str) -> Bridge:
    return Bridge(fx.state_dir, env={**os.environ, **env})


def test_initial_repair_same_session_external_verification(fx: Fixture, peer: Path) -> None:
    log = fx.base / "rpc.jsonl"
    b = bridge(fx, HBRIDGE_ZC_LOG=str(log), HBRIDGE_ZC_EDIT="buggy", HBRIDGE_ZC_TRICKLE="1")
    tid = b.create(zc_spec(fx), "create")["task_id"]
    first = b.run(tid, executor_binary=str(peer))
    assert first["executor_outcome"] == "succeeded" and first["verification_status"] == "failed"
    a = b.store.list_attempts(tid)[0]
    assert a.session_id.startswith("sess_") and a.observed_model == "GLM-5.3-Flash"
    b.review(tid, review_for(b.artifacts(tid), "changes_requested", "fix"))
    b.env["HBRIDGE_ZC_EDIT"] = "correct"
    second = b.run(tid, executor_binary=str(peer))
    assert second["verification_status"] == "passed"
    calls = [json.loads(x) for x in log.read_text().splitlines()]
    resumed = [x for x in calls if x["method"] == "session/resume"]
    assert len(resumed) == 1 and resumed[0]["params"]["sessionId"] == a.session_id
    sent = [x for x in calls if x["method"] == "session/send"]
    assert len(sent) == 2 and "fix it" in sent[-1]["params"]["content"]
    assert sent[0]["cwd"] == sent[1]["cwd"] != str(fx.repo)
    assert not any(x["method"] in ("session/setModel", "session/close") for x in calls)
    b.review(tid, review_for(b.artifacts(tid), "approve", "done"))
    assert b.status(tid)["state"] == "SUCCEEDED"
    assert b.store.get_task(tid).repair_cycles_used == 1
    assert "PRIVATE_NATIVE_HISTORY" not in json.dumps(b.artifacts(tid))
    b.close()


@pytest.mark.parametrize(
    "mode",
    [
        "model",
        "workspace",
        "permission",
        "busy",
        "wrong-id",
        "bad-runtime",
        "bad-projection",
        "missing-preferences",
        "bad-preference-session",
        "bad-preference-scope",
        "duplicate-preferences",
        "preference-binding-mismatch",
    ],
)
def test_identity_and_permissions_refuse_before_prompt(fx: Fixture, peer: Path, mode: str) -> None:
    log = fx.base / "rpc.jsonl"
    b = bridge(fx, HBRIDGE_ZC_LOG=str(log), HBRIDGE_ZC_MODE=mode)
    tid = b.create(zc_spec(fx), "k")["task_id"]
    result = b.run(tid, executor_binary=str(peer))
    assert result["executor_outcome"] != "succeeded"
    assert not any(json.loads(x)["method"] == "session/send" for x in log.read_text().splitlines())
    assert b.store.list_attempts(tid)[0].session_binding is None
    b.close()


@pytest.mark.parametrize(
    "mode",
    [
        "truncated",
        "malformed",
        "oversized",
        "failed",
        "rpc-error",
        "duplicate",
        "after-final",
        "final-model",
        "request-permission",
        "stale-final",
        "final-busy",
        "wrong-turn",
        "wrong-turn-workspace",
        "missing-start",
        "exit-error",
    ],
)
def test_failures_cannot_be_approved(fx: Fixture, peer: Path, mode: str) -> None:
    b = bridge(fx, HBRIDGE_ZC_MODE=mode)
    tid = b.create(zc_spec(fx), "k")["task_id"]
    result = b.run(tid, executor_binary=str(peer))
    assert result["executor_outcome"] != "succeeded"
    artifacts = b.artifacts(tid)
    assert not artifacts["approval_gate"]["approvable"]
    logs = "".join(
        p.read_text() for p in b.attempt_dir(tid, result["attempt_id"]).glob("executor.*.log")
    )
    assert "PRIVATE_" not in logs
    if result["executor_outcome"] == "blocked":
        assert "review_template" not in artifacts
    else:
        # Verification may still inspect the changed files; passing checks do not erase
        # protocol failure. Exercise the actual approval gate, not only its summary.
        with pytest.raises(BridgeError):
            b.review(tid, review_for(artifacts, "approve", "must-refuse"))
    assert len(b.store.list_attempts(tid)) == 1
    b.close()


def test_resume_mismatch_does_not_rebind(fx: Fixture, peer: Path) -> None:
    b = bridge(fx)
    tid = b.create(zc_spec(fx), "k")["task_id"]
    b.run(tid, executor_binary=str(peer))
    b.review(tid, review_for(b.artifacts(tid), "changes_requested", "fix"))
    b.env["HBRIDGE_ZC_MODE"] = "resume-mismatch"
    assert b.run(tid, executor_binary=str(peer))["state"] == "BLOCKED"
    assert b.store.list_attempts(tid)[-1].session_binding is None
    b.close()


@pytest.mark.parametrize("background", [False, True])
def test_live_refused_before_reservation_even_with_opt_in(fx: Fixture, background: bool) -> None:
    fx.state_dir.mkdir()
    (fx.state_dir / "config.toml").write_text(
        "[live]\nenabled=true\nhooks_and_permissions_reviewed=true\n"
    )
    b = bridge(fx)
    tid = b.create(zc_spec(fx), "k")["task_id"]
    with pytest.raises(BridgeError) as exc:
        b.run(
            tid,
            mode="live",
            allow_model_usage=True,
            background=background,
            idempotency_key="d" if background else None,
        )
    assert exc.value.details["executor"] == "zcode"
    assert not b.store.list_attempts(tid)
    b.close()


def test_mock_refuses_native_name_and_symlink(fx: Fixture, peer: Path) -> None:
    b = bridge(fx)
    tid = b.create(zc_spec(fx), "k")["task_id"]
    native = peer.with_name("zcode-native")
    native.write_text(peer.read_text())
    native.chmod(0o755)
    link = peer.with_name("alias")
    link.symlink_to(native)
    for binary in (None, "relative", str(native), str(link)):
        with pytest.raises(BridgeError):
            b.run(tid, executor_binary=binary)
    assert not b.store.list_attempts(tid)
    b.close()


def test_timeout_stops_protocol_child_and_retains_outcome(fx: Fixture, peer: Path) -> None:
    b = bridge(fx, HBRIDGE_ZC_MODE="sleep")
    tid = b.create(zc_spec(fx, wall_timeout_seconds=1.5, kill_grace_seconds=0.2), "k")["task_id"]
    result = b.run(tid, executor_binary=str(peer))
    assert result["executor_outcome"] == "timed_out"
    assert b.store.list_attempts(tid)[0].exit_confirmed
    b.close()


def test_goal_worker_replay_and_null_budget(fx: Fixture, peer: Path) -> None:
    b, g = setup_goal(fx, allowed_executors=["zcode"], max_attempts=1, max_repairs=0)
    child = plan(fx, "flash")
    child["task"]["limits"].update(max_attempts=1, max_repair_cycles=0)
    child["task"]["executor"] = settings().model_dump()
    child["task"]["limits"]["max_turns_per_attempt"] = None
    batch = submit(b, g, child)
    tid = b.materialize(batch["children"][0]["child_id"])["task_id"]
    job = b.run(tid, executor_binary=str(peer), background=True, idempotency_key="dispatch")
    replay = b.run(tid, executor_binary=str(peer), background=True, idempotency_key="dispatch")
    assert replay["job_id"] == job["job_id"] and replay["replayed"]
    assert finished(b, job["job_id"])["phase"] == "finished"
    assert b.status(tid)["state"] == "AWAITING_REVIEW"
    assert len(b.store.list_attempts(tid)) == 1
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 1
    b.close()


def test_cancel_stops_both_transport_and_peer(fx: Fixture, peer: Path) -> None:
    log = fx.base / "rpc.jsonl"
    b = bridge(fx, HBRIDGE_ZC_MODE="sleep", HBRIDGE_ZC_LOG=str(log))
    tid = b.create(zc_spec(fx, wall_timeout_seconds=30, kill_grace_seconds=0.2), "k")["task_id"]
    job = b.run(tid, executor_binary=str(peer), background=True, idempotency_key="dispatch")
    try:
        wait_for(b.store, tid, lambda t: t.state == "RUNNING")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if log.exists() and '"session/send"' in log.read_text():
                break
            time.sleep(0.05)
        else:
            pytest.fail("protocol peer did not receive the synthetic turn")
        pid = json.loads(log.read_text().splitlines()[-1])["pid"]
        attempt = b.store.list_attempts(tid)[0]
        assert attempt.pid != pid and attempt.pgid == os.getpgid(pid)
        assert b.cancel(tid, wait_seconds=10)["state"] == "CANCELLED"
        assert finished(b, job["job_id"])["executor_exit_confirmed"]
        assert not group_alive(attempt.pgid)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert len(b.store.list_attempts(tid)) == 1
    finally:
        if b.status(tid)["state"] not in ("CANCELLED", "FAILED", "SUCCEEDED"):
            b.cancel(tid, wait_seconds=10)
        b.close()


def test_numeric_goal_turn_budget_cannot_be_bypassed(fx: Fixture, peer: Path) -> None:
    b, g = setup_goal(fx, allowed_executors=["zcode"], max_executor_turns=10)
    tid = b.create(zc_spec(fx), "k", goal_id=g["goal_id"])["task_id"]
    with pytest.raises(BridgeError) as error:
        b.run(tid, executor_binary=str(peer))
    assert error.value.code == "BUDGET_EXHAUSTED"
    assert not b.store.list_attempts(tid)
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 0
    b.close()


@pytest.mark.parametrize("provider", ["account:bigmodel-start-plan", "account:zai-start-plan"])
def test_start_plan_is_explicit_and_observed_without_coding_plan_fallback(
    fx: Fixture, peer: Path, provider: str
) -> None:
    log = fx.base / "rpc.jsonl"
    b = bridge(fx, HBRIDGE_ZC_PROVIDER=provider, HBRIDGE_ZC_LOG=str(log))
    spec = zc_spec(fx)
    spec["executor"]["provider_id"] = provider
    tid = b.create(spec, "k")["task_id"]
    result = b.run(tid, executor_binary=str(peer))
    assert result["executor_outcome"] == "succeeded"
    assert result["verification_status"] == "passed"
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    create = next(x for x in calls if x["method"] == "session/create")
    send = next(x for x in calls if x["method"] == "session/send")
    assert create["params"]["model"]["providerId"] == provider
    assert send["params"]["modelSelection"]["providerId"] == provider
    assert b.store.list_attempts(tid)[0].session_binding
    b.close()
