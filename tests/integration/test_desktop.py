"""Desktop handoff contracts with synthetic session rows and a simulated native CLI.

No native harness, authentication, desktop app, network or model is used here.
"""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from harness_bridge import desktop
from harness_bridge.coordination import AdvisorClaim
from harness_bridge.desktop import DesktopSessions
from harness_bridge.errors import BridgeError
from harness_bridge.models import sha256_digest
from harness_bridge.service import Bridge
from tests.conftest import Fixture
from tests.integration.test_claude_stub_flow import claude_spec
from tests.integration.test_coordination import goal_spec, takeover

SID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def synthetic(fx: Fixture, kind: str = "claude-code", goal: bool = False) -> tuple[Bridge, str]:
    b = fx.bridge()
    g = b.coordination.create(goal_spec(fx, allowed_executors=[kind]), "g") if goal else None
    if g:
        b.advisor_claim = AdvisorClaim.model_validate(g["advisor_claim"])
    spec = claude_spec(fx)
    if kind == "codex":
        spec["executor"] = {"kind": "codex", "requested_model": "fixture-model"}
    t = b.create(spec, "t", goal_id=g["goal_id"] if g else None)
    task = b.store.get_task(t["task_id"])
    invocation = {"argv": ["/fixture/native"], "cwd": task.worktree_path}
    binding = {
        "task_id": task.task_id,
        "attempt_id": "att_fixture",
        "executor_kind": kind,
        "repo_identity": task.repo_identity,
        "worktree": task.worktree_path,
        "requested_model": spec["executor"]["requested_model"],
    }
    with b.store.transaction() as cur:
        b.store.insert_attempt(
            cur,
            {
                "attempt_id": "att_fixture",
                "task_id": task.task_id,
                "seq": 1,
                "kind": "initial",
                "executor_kind": kind,
                "mode": "live",
                "invocation": invocation,
                "invocation_digest": sha256_digest(invocation),
                "launch_token": "synthetic-only",
                "status": "ended",
                "exit_confirmed": 1,
                "session_id": SID,
                "session_binding": binding,
                "outcome": "succeeded",
            },
        )
        cur.execute(
            "UPDATE tasks SET state='SUCCEEDED',current_attempt_id='att_fixture',"
            "attempts_used=1 WHERE task_id=?",
            (task.task_id,),
        )
    return b, task.task_id


def native(monkeypatch: pytest.MonkeyPatch, outcome: str = "ack") -> list[list[str]]:
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    original = subprocess.run
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> Any:
        if argv[0] != "/fixture/native":
            return original(argv, **kwargs)
        calls.append(argv)
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert Path(kwargs["cwd"]).is_dir()
        if argv[1:] == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, desktop.CLAUDE_VERSION.encode(), b"")
        assert argv == ["/fixture/native", "--desktop", "--resume", SID]
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, 20, output=b"private-value")
        if outcome == "spawn_error":
            raise OSError("private-value")
        if outcome == "interrupt":
            raise KeyboardInterrupt
        data = f"Opening session {SID} in Claude Desktop" if outcome == "ack" else "private-value"
        return subprocess.CompletedProcess(
            argv, 0 if outcome != "failure" else 1, data.encode(), b""
        )

    monkeypatch.setattr(desktop.subprocess, "run", run)
    return calls


def test_read_only_status_and_cli_never_probe_native(fx: Fixture) -> None:
    b, tid = synthetic(fx)
    before = b.store.list_events(tid)
    result = DesktopSessions(b).status(tid)
    assert result["session_id"] == SID and result["desktop_visibility"] == "unverified"
    assert b.store.list_events(tid) == before
    b.close()
    code, result = fx.cli("desktop", "status", tid)
    assert code == 0 and result["session_id"] == SID
    assert result["last_request"] is None


def test_native_handoff_replays_across_processes_without_budget_or_state_change(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b, tid = synthetic(fx)
    calls = native(monkeypatch)
    before = b.store.get_task(tid)
    attempts = b.store.list_attempts(tid)
    result = DesktopSessions(b).open(tid, "open")
    assert result["status"] == "native_open_requested"
    assert result["desktop_visibility"] == "unverified" and not result["model_call_requested"]
    assert b.store.get_task(tid) == before and b.store.list_attempts(tid) == attempts
    assert len(calls) == 2
    b.close()
    code, replay = fx.cli("desktop", "open", tid, "--idempotency-key", "another-key")
    assert code == 0 and replay == {**result, "replayed": True, "ok": True}


@pytest.mark.parametrize("outcome", ["no_ack", "failure", "timeout", "spawn_error", "interrupt"])
def test_uncertain_or_failed_open_is_durable_and_never_blindly_retried(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    b, tid = synthetic(fx)
    calls = native(monkeypatch, outcome)
    d = DesktopSessions(b)
    if outcome == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            d.open(tid, "open")
    else:
        result = d.open(tid, "open")
        assert result["status"] != "native_open_requested"
    result = d.open(tid, "different-key")
    assert result["replayed"] and len(calls) == 2
    assert "private-value" not in json.dumps(b.store.list_events(tid))


@pytest.mark.parametrize("state", ["READY", "RUNNING", "AWAITING_REVIEW", "INTERRUPTED"])
def test_open_refuses_active_and_repairable_tasks_before_any_native_call(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    b, tid = synthetic(fx)
    calls = native(monkeypatch)
    with b.store.transaction() as cur:
        cur.execute("UPDATE tasks SET state=? WHERE task_id=?", (state, tid))
    with pytest.raises(BridgeError):
        DesktopSessions(b).open(tid, "open")
    assert calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", None),
        ("session_id", "--new-session"),
        ("mode", "mock"),
        ("exit_confirmed", None),
        ("exit_confirmed", 0),
        ("session_binding", {}),
        ("invocation_digest", "tampered"),
    ],
)
def test_invalid_native_binding_never_opens(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
) -> None:
    b, tid = synthetic(fx)
    calls = native(monkeypatch)
    with b.store.transaction() as cur:
        b.store.update_attempt(cur, "att_fixture", **{field: value})
    with pytest.raises(BridgeError):
        DesktopSessions(b).open(tid, "open")
    assert calls == []


def test_codex_is_not_reported_as_synced(fx: Fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    b, tid = synthetic(fx, "codex")
    calls = native(monkeypatch)
    d = DesktopSessions(b)
    assert d.status(tid)["capability"] == "native_history_only"
    with pytest.raises(BridgeError):
        d.open(tid, "open")
    assert calls == []


def test_missing_worktree_and_platform_do_not_open(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b, tid = synthetic(fx)
    calls = native(monkeypatch)
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    path = Path(b.store.get_task(tid).worktree_path or "")
    path.rename(path.with_name("retained"))
    d = DesktopSessions(b)
    assert set(d.status(tid)["blockers"]) >= {
        "desktop_platform_unverified",
        "original_worktree_unavailable",
    }
    with pytest.raises(BridgeError):
        d.open(tid, "open")
    assert calls == []


def test_goal_requires_delivery_and_current_advisor(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b, tid = synthetic(fx, goal=True)
    calls = native(monkeypatch)
    gid = b._goal_id(tid)
    assert gid
    d = DesktopSessions(b)
    assert "goal_not_delivered" in d.status(tid)["blockers"]
    with pytest.raises(BridgeError):
        d.open(tid, "open")
    takeover(b, {"goal_id": gid})
    with pytest.raises(BridgeError, match="stale"):
        d.open(tid, "open")
    b.advisor_claim = None
    with pytest.raises(BridgeError) as err:
        d.open(tid, "open")
    assert err.value.code == "ADVISOR_REQUIRED" and calls == []


def test_provider_environment_is_reported_by_name_only(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b, tid = synthetic(fx)
    calls = native(monkeypatch)
    b.env["ANTHROPIC_API_KEY"] = "private-value"
    with pytest.raises(BridgeError) as err:
        DesktopSessions(b).open(tid, "open")
    assert "private-value" not in json.dumps(err.value.to_dict()) and calls == []


def test_unvalidated_version_refuses_before_handoff(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b, tid = synthetic(fx)
    calls = native(monkeypatch)
    original = desktop.subprocess.run

    def old_version(argv: list[str], **kwargs: Any) -> Any:
        result = original(argv, **kwargs)
        if argv[0] == "/fixture/native":
            result.stdout = b"2.1.1 (Claude Code)"
        return result

    monkeypatch.setattr(desktop.subprocess, "run", old_version)
    with pytest.raises(BridgeError):
        DesktopSessions(b).open(tid, "open")
    assert len(calls) == 1 and DesktopSessions(b).status(tid)["last_request"] is None


def test_concurrent_open_records_one_native_handoff(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b, tid = synthetic(fx)
    b.close()
    calls = native(monkeypatch)
    original = desktop.subprocess.run
    barrier = Barrier(2)

    def probe(argv: list[str], **kwargs: Any) -> Any:
        result = original(argv, **kwargs)
        if argv == ["/fixture/native", "--version"]:
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(desktop.subprocess, "run", probe)

    def open_one(key: str) -> dict[str, Any]:
        local = fx.bridge()
        try:
            return DesktopSessions(local).open(tid, key)
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(open_one, ["first", "second"]))
    assert sum(not r["replayed"] for r in results) == 1
    assert sum("--desktop" in c for c in calls) == 1
    b = fx.bridge()
    status = DesktopSessions(b).status(tid)
    assert status["request_replay_only"] and not status["can_request_open"]
    b.close()


def test_delivered_goal_handoff_is_fenced_after_native_probe(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b, tid = synthetic(fx, goal=True)
    gid = b._goal_id(tid)
    assert gid
    # Simulates only the delivery projection; ownership checks and requests are real SQLite.
    monkeypatch.setattr(b.coordination, "status", lambda _: {"state": "DELIVERED"})
    calls = native(monkeypatch)
    original = desktop.subprocess.run

    def probe(argv: list[str], **kwargs: Any) -> Any:
        result = original(argv, **kwargs)
        if argv == ["/fixture/native", "--version"]:
            takeover(b, {"goal_id": gid})
        return result

    monkeypatch.setattr(desktop.subprocess, "run", probe)
    with pytest.raises(BridgeError, match="stale"):
        DesktopSessions(b).open(tid, "open")
    assert len(calls) == 1
    assert DesktopSessions(b).status(tid)["last_request"] is None


def test_delivered_goal_can_request_without_changing_delivery_or_budget(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b, tid = synthetic(fx, goal=True)
    monkeypatch.setattr(b.coordination, "status", lambda _: {"state": "DELIVERED"})
    calls = native(monkeypatch)
    before = b.store.get_task(tid)
    assert DesktopSessions(b).open(tid, "open")["status"] == "native_open_requested"
    assert b.store.get_task(tid) == before and len(calls) == 2
