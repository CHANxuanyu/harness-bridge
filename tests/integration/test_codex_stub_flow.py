"""Codex-shaped stub through actual worktrees, worker, verifier and review. Never live evidence."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.coordination import AdvisorClaim
from harness_bridge.errors import BridgeError
from harness_bridge.service import Bridge
from tests.conftest import Fixture
from tests.helpers.reviews import review_for
from tests.integration.test_coordination import setup_goal, takeover
from tests.integration.test_goal_planning import plan, submit
from tests.integration.test_recovery import wait_for
from tests.integration.test_workers import finished


@pytest.fixture
def cx_stub(tmp_path: Path) -> Path:
    exe = tmp_path / "cx-stand-in"
    helper = Path(__file__).parents[1] / "helpers/cx_stub.py"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{helper}" "$@"\n')
    exe.chmod(0o755)
    return exe


def cx_spec(fx: Fixture, **limits: Any) -> dict[str, Any]:
    data = fx.spec(**limits)
    data["executor"] = {"kind": "codex", "requested_model": "synthetic-pin"}
    return data


def bridge(fx: Fixture, **env: str) -> Bridge:
    return Bridge(fx.state_dir, env={**os.environ, **env})


def test_initial_repair_exact_resume_and_external_review(fx: Fixture, cx_stub: Path) -> None:
    log = fx.base / "calls.jsonl"
    b = bridge(fx, HBRIDGE_CX_LOG=str(log), HBRIDGE_CX_EDIT="buggy", HBRIDGE_CX_TRICKLE="1")
    task = b.create(cx_spec(fx), "create")["task_id"]
    first = b.run(task, executor_binary=str(cx_stub))
    assert first["executor_outcome"] == "succeeded" and first["verification_status"] == "failed"
    assert first["evidence_level"] == "offline-stub-binary"
    attempt = b.store.list_attempts(task)[0]
    assert attempt.session_id and attempt.observed_model is None
    assert attempt.session_binding["executor_kind"] == "codex"
    b.review(task, review_for(b.artifacts(task), "changes_requested", "repair"))
    b.env["HBRIDGE_CX_EDIT"] = "correct"
    second = b.run(task, executor_binary=str(cx_stub))
    assert second["verification_status"] == "passed"
    calls = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(calls) == 2 and "resume" not in calls[0]["argv"]
    assert calls[1]["argv"][-3:] == ["resume", attempt.session_id, "-"]
    assert "fix it" in calls[1]["stdin"] and calls[0]["cwd"] == calls[1]["cwd"]
    assert calls[0]["cwd"] != str(fx.repo)
    b.review(task, review_for(b.artifacts(task), "approve", "approve"))
    assert b.status(task)["state"] == "SUCCEEDED"
    assert b.store.get_task(task).repair_cycles_used == 1
    b.close()


def test_resume_mismatch_blocks_without_rebinding_or_retry(fx: Fixture, cx_stub: Path) -> None:
    b = bridge(fx)
    task = b.create(cx_spec(fx), "k")["task_id"]
    b.run(task, executor_binary=str(cx_stub))
    b.review(task, review_for(b.artifacts(task), "changes_requested", "repair"))
    b.env["HBRIDGE_CX_MODE"] = "mismatch"
    result = b.run(task, executor_binary=str(cx_stub))
    assert result["state"] == "BLOCKED"
    assert b.status(task)["state_details"]["category"] == "resume_failed"
    attempt = b.store.list_attempts(task)[-1]
    assert attempt.session_binding is None and attempt.session_id is None
    with pytest.raises(BridgeError):
        b.run(task, executor_binary=str(cx_stub))
    assert len(b.store.list_attempts(task)) == 2
    b.close()


@pytest.mark.parametrize(
    "mode, outcome",
    [
        ("truncated", "protocol_error"),
        ("malformed", "protocol_error"),
        ("quota", "blocked"),
        ("flood", "protocol_error"),
    ],
)
def test_failure_receipts_never_become_approvable(
    fx: Fixture, cx_stub: Path, monkeypatch: pytest.MonkeyPatch, mode: str, outcome: str
) -> None:
    if mode == "flood":
        monkeypatch.setattr("harness_bridge.service.MAX_KEPT_EVENTS", 10)
    b = bridge(fx, HBRIDGE_CX_MODE=mode)
    task = b.create(cx_spec(fx), "k")["task_id"]
    result = b.run(task, executor_binary=str(cx_stub))
    assert result["executor_outcome"] == outcome
    assert b.status(task)["state"] != "SUCCEEDED"
    artifacts = b.artifacts(task)
    if outcome == "blocked":
        assert "review_template" not in artifacts
        assert artifacts["state"] == "BLOCKED"
    else:
        with pytest.raises(BridgeError):
            b.review(task, review_for(artifacts, "approve", "bad"))
    assert len(b.store.list_attempts(task)) == 1
    b.close()


def test_mock_refuses_real_binary_names_missing_stub_and_symlinks(
    fx: Fixture, cx_stub: Path
) -> None:
    b = bridge(fx)
    task = b.create(cx_spec(fx), "k")["task_id"]
    named = cx_stub.with_name("codex-wrapper")
    named.write_text(cx_stub.read_text())
    named.chmod(0o755)
    link = cx_stub.with_name("ordinary-name")
    link.symlink_to(named)
    sentinel = Path(b.env["PATH"].split(os.pathsep)[0]) / "codex"
    for path in (None, "relative", str(named), str(link), str(sentinel)):
        with pytest.raises(BridgeError):
            b.run(task, executor_binary=path)
    assert b.store.list_attempts(task) == []
    b.close()


@pytest.mark.parametrize("background", [False, True])
def test_even_fully_opted_in_live_is_refused_before_budget_or_binary(
    fx: Fixture, background: bool
) -> None:
    fx.state_dir.mkdir()
    (fx.state_dir / "config.toml").write_text(
        "[live]\nenabled=true\nhooks_and_permissions_reviewed=true\n"
        'allow_unlisted_flags=["--max-turns"]\n'
    )
    b = bridge(fx)
    task = b.create(cx_spec(fx), "k")["task_id"]
    with pytest.raises(BridgeError) as exc:
        b.run(
            task,
            mode="live",
            allow_model_usage=True,
            background=background,
            idempotency_key="run" if background else None,
        )
    assert exc.value.code == "PREFLIGHT_FAILED"
    assert "enforceable_model_turn_ceiling" in exc.value.details["gaps"]
    assert b.store.list_attempts(task) == [] and b.status(task)["state"] == "READY"
    b.close()


def test_goal_plan_worker_takeover_replay_and_shared_budget(fx: Fixture, cx_stub: Path) -> None:
    b, g = setup_goal(
        fx, allowed_executors=["codex"], max_attempts=1, max_repairs=0, max_executor_turns=20
    )
    p = plan(fx, "codex-child")
    p["task"]["executor"] = cx_spec(fx)["executor"]
    batch = submit(b, g, p)
    task = b.materialize(batch["children"][0]["child_id"])["task_id"]
    receipt = b.run(task, executor_binary=str(cx_stub), background=True, idempotency_key="run")
    assert finished(b, receipt["job_id"])["executor_outcome"] == "succeeded"
    assert b.run(task, executor_binary=str(cx_stub), background=True, idempotency_key="run")[
        "replayed"
    ]
    claim = takeover(b, g)["advisor_claim"]
    with pytest.raises(BridgeError) as exc:
        b.run(task, executor_binary=str(cx_stub), background=True, idempotency_key="run")
    assert exc.value.code == "STALE_ADVISOR"
    b.advisor_claim = AdvisorClaim.model_validate(claim)
    b.review(task, review_for(b.artifacts(task), "changes_requested", "repair"))
    with pytest.raises(BridgeError):
        b.run(task, executor_binary=str(cx_stub))
    assert len(b.store.list_attempts(task)) == 1
    budget = b.coordination.status(g["goal_id"])["budget"]
    assert budget["attempts"] == 1
    b.close()


def test_wall_timeout_is_still_enforced_by_bridge(fx: Fixture, cx_stub: Path) -> None:
    b = bridge(fx, HBRIDGE_CX_DELAY="10")
    task = b.create(cx_spec(fx, wall_timeout_seconds=0.3, kill_grace_seconds=0.1), "k")["task_id"]
    result = b.run(task, executor_binary=str(cx_stub))
    assert result["executor_outcome"] == "timed_out"
    assert b.store.list_attempts(task)[0].exit_confirmed
    b.close()


def test_background_cancel_stops_owned_codex_stub(fx: Fixture, cx_stub: Path) -> None:
    b = bridge(fx, HBRIDGE_CX_DELAY="15")
    task = b.create(cx_spec(fx, wall_timeout_seconds=25, kill_grace_seconds=0.1), "k")["task_id"]
    receipt = b.run(task, executor_binary=str(cx_stub), background=True, idempotency_key="run")
    wait_for(b.store, task, lambda t: t.state == "RUNNING")
    assert b.cancel(task, wait_seconds=10)["state"] == "CANCELLED"
    assert finished(b, receipt["job_id"])["executor_exit_confirmed"]
    b.close()


def test_offline_doctor_exposes_codex_gaps(fx: Fixture) -> None:
    _, report = fx.cli("doctor", "--offline")
    cap = next(x for x in report["capabilities"] if x["name"] == "codex_executor_adapter")
    assert cap["status"] == "offline_only"
    assert cap["evidence"]["live_dispatch"] == "unavailable"


@pytest.mark.parametrize(
    "key, wrong",
    [
        ("executor_kind", "claude-code"),
        ("repo_identity", "different"),
        ("worktree", "/other/worktree"),
        ("requested_model", "other-model"),
        ("task_id", "other-task"),
    ],
)
def test_incompatible_recorded_session_is_not_selected(
    fx: Fixture, cx_stub: Path, key: str, wrong: str
) -> None:
    b = bridge(fx)
    task = b.create(cx_spec(fx), "k")["task_id"]
    b.run(task, executor_binary=str(cx_stub))
    attempt = b.store.list_attempts(task)[0]
    with b.store.transaction() as cur:
        b.store.update_attempt(
            cur, attempt.attempt_id, session_binding={**attempt.session_binding, key: wrong}
        )
    current = b.store.get_task(task)
    assert b._resume_session(current, b._spec(current)) is None
    b.close()


def test_background_repair_reconstructs_bound_session_and_feedback(
    fx: Fixture, cx_stub: Path
) -> None:
    log = fx.base / "calls.jsonl"
    b = bridge(fx, HBRIDGE_CX_LOG=str(log), HBRIDGE_CX_EDIT="buggy")
    task = b.create(cx_spec(fx), "k")["task_id"]
    first = b.run(task, executor_binary=str(cx_stub), background=True, idempotency_key="initial")
    assert finished(b, first["job_id"])["executor_outcome"] == "succeeded"
    assert b.artifacts(task)["verification"]["status"] == "failed"
    sid = b.store.list_attempts(task)[0].session_id
    b.review(task, review_for(b.artifacts(task), "changes_requested", "repair"))
    b.env["HBRIDGE_CX_EDIT"] = "correct"
    second = b.run(task, executor_binary=str(cx_stub), background=True, idempotency_key="repair")
    assert finished(b, second["job_id"])["executor_outcome"] == "succeeded"
    assert b.artifacts(task)["verification"]["status"] == "passed"
    calls = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(calls) == 2 and calls[1]["argv"][-3:] == ["resume", sid, "-"]
    assert "fix it" in calls[1]["stdin"]
    b.close()


def test_resume_opt_out_remains_explicit(fx: Fixture, cx_stub: Path) -> None:
    log = fx.base / "calls.jsonl"
    b = bridge(fx, HBRIDGE_CX_LOG=str(log))
    spec = cx_spec(fx)
    spec["executor"]["resume_on_repair"] = False
    task = b.create(spec, "k")["task_id"]
    b.run(task, executor_binary=str(cx_stub))
    b.review(task, review_for(b.artifacts(task), "changes_requested", "repair"))
    b.run(task, executor_binary=str(cx_stub))
    calls = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(calls) == 2 and all("resume" not in c["argv"] for c in calls)
    b.close()
