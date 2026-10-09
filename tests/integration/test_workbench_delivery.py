"""Isolated native protocol failure/receipt tests; no real harness or model calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.workbench.harness import CLAUDE, CODEX
from harness_bridge.workbench.server import WorkbenchServer
from harness_bridge.workbench.structured import CodexAppServerSession
from tests.integration.test_existing_sessions import candidate, linked, seed
from tests.integration.test_workbench import WB, wait_for
from tests.integration.test_workbench_conversation import idle
from tests.integration.test_workbench_server import Client, loopback  # noqa: F401


@pytest.fixture
def fx(tmp_path: Path) -> Any:
    fixture = WB(tmp_path)
    fixture.env.update(HOME=str(tmp_path / "home"), CODEX_HOME=str(tmp_path / "codex-home"))
    yield fixture
    for wb in fixture.instances:
        wb.close(timeout=5)


def setup(fx: WB, **env: str) -> tuple[Any, str]:
    native, _ = seed(fx, CODEX)
    wb = fx.open(**env)
    pid = wb.add_project(str(fx.repo))["project_id"]
    return wb, linked(wb, candidate(wb, pid, CODEX, native)["candidate_id"])


def calls(fx: WB, method: str) -> list[dict[str, Any]]:
    path = Path(fx.env["WB_STUB_HOME"]) / "codex-rpc.log"
    return [
        r
        for line in path.read_text().splitlines()
        if (r := json.loads(line)).get("method") == method
    ]


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("busy", "native_writer_busy"),
        ("timeout", "native_timeout"),
        ("exit", "native_process_exited"),
    ],
)
def test_queued_failure_is_durable_recoverable_and_never_resent(
    fx: WB, monkeypatch: pytest.MonkeyPatch, fault: str, reason: str
) -> None:
    env = {"WB_STUB_RESUME_DELAY": "0.3"}
    if fault == "busy":
        env["WB_STUB_CODEX_WRITER_BUSY"] = "1"
    elif fault == "timeout":
        monkeypatch.setattr(CodexAppServerSession, "rpc_timeout", 0.1)
    else:
        env["WB_STUB_RESUME_EXIT"] = "1"
    wb, sid = setup(fx, **env)
    attachment = wb.add_attachment(sid, name="notes.txt", data=b"synthetic attachment")
    ack = wb.send_message(
        sid,
        "keep this draft",
        client_id="queue-test",
        attachments=[attachment["id"]],
        confirm_external=True,
    )
    assert ack["client_id"] == "queue-test"
    wait_for(lambda: WB.run(wb, sid)["status"] == "failed")
    receipt = wb.message_delivery(sid, "queue-test")
    assert receipt["delivery"]["state"] == "not_sent"
    assert receipt["delivery"]["reason"] == reason
    assert (
        receipt["text"] == "keep this draft" and receipt["attachments"][0]["id"] == attachment["id"]
    )
    assert not calls(fx, "turn/start")
    assert any(
        i["id"] == "user:queue-test" and i["status"] == "failed"
        for i in wb.conversation(sid)["items"]
    )
    wb.close()
    fx.instances.remove(wb)
    wb = fx.open()
    retry = wb.send_message(
        sid, "keep this draft", client_id="queue-test", attachments=[attachment["id"]]
    )
    assert retry["reused"] and retry["delivery"]["state"] == "not_sent"
    assert len(wb.store.list_runs(sid)) == 1 and not calls(fx, "turn/start")


@pytest.mark.parametrize(
    "fault,state", [("exit", "unknown"), ("reject", "not_sent"), ("delay", "unknown")]
)
def test_native_submit_outcomes_and_late_ack_are_distinct(
    fx: WB, monkeypatch: pytest.MonkeyPatch, fault: str, state: str
) -> None:
    wb, sid = setup(fx, WB_STUB_TURN_DELIVERY=fault)
    wb.start_run(sid, "resume", confirm_external=True)
    wait_for(lambda: idle(wb, sid))
    monkeypatch.setattr(CodexAppServerSession, "rpc_timeout", 0.1)
    wb.send_message(sid, "submitted once", client_id="submit-test")
    wait_for(lambda: wb.message_delivery(sid, "submit-test")["delivery"]["state"] == state)
    if state == "unknown":
        with pytest.raises(BridgeError) as e:
            wb.send_message(sid, "submitted once", client_id="another-id")
        assert e.value.details["reason"] == "delivery_unknown"
    assert wb.send_message(sid, "submitted once", client_id="submit-test")["reused"]
    with pytest.raises(BridgeError) as e:
        wb.send_message(sid, "changed", client_id="submit-test")
    assert e.value.details["reason"] == "client_id_conflict"
    assert len(calls(fx, "turn/start")) == 1
    if fault == "delay":
        wait_for(lambda: wb.message_delivery(sid, "submit-test")["delivery"]["state"] == "sent")
        wait_for(lambda: idle(wb, sid))
        wb.stop(sid)
        wait_for(lambda: not WB.view(wb, sid)["active"])
        assert wb.message_delivery(sid, "submit-test")["delivery"]["state"] == "sent"


def test_handshake_failure_before_send_rejects_without_accepting(fx: WB) -> None:
    wb, sid = setup(fx, WB_STUB_CODEX_WRITER_BUSY="1")
    wb.start_run(sid, "resume", confirm_external=True)
    wait_for(lambda: WB.run(wb, sid)["status"] == "failed")
    assert not wb.store.message_deliveries(sid)
    assert not calls(fx, "turn/start")


@pytest.mark.usefixtures("loopback")
def test_unlink_external_local_and_confirmation_contract_over_http(fx: WB) -> None:
    native, history = seed(fx, CLAUDE)
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    sid = linked(wb, candidate(wb, pid, CLAUDE, native)["candidate_id"])
    before = history.read_bytes()
    server = WorkbenchServer(wb)
    server.start()
    client = Client(server)
    try:
        client.login()
        status, _, raw = client.request("POST", f"/api/sessions/{sid}/unlink", {})
        data = json.loads(raw)
        assert status == 409
        details = data["error"]["details"]
        assert details["external"]["via"] == "native-link"
        assert (
            details["reason"] == "external_confirmation_required"
            and "busy_session_id" not in details
        )
        wb._history_cache[f"{sid}:{native}"] = (0, {})
        assert client.api("POST", f"/api/sessions/{sid}/desktop/return", {}) == {"external": None}
        assert not wb.store.list_runs(sid) and history.read_bytes() == before
        assert f"{sid}:{native}" not in wb._history_cache
        event = wb.store.list_events(sid)[-1]
        assert event["payload"] == {"source": "user_confirmation", "process_exit_observed": False}
        wb.start_run(sid, "resume")
        wait_for(lambda: idle(wb, sid))
        status, _, raw = client.request("POST", f"/api/sessions/{sid}/unlink", {})
        data = json.loads(raw)
        assert status == 409 and data["error"]["details"]["reason"] == "local_writer_busy"
        assert (
            data["error"]["details"]["busy_session_id"] == sid
            and "external" not in data["error"]["details"]
        )
    finally:
        server.close()


@pytest.mark.parametrize(
    "env,reason,unsupported",
    [
        ("WB_STUB_DISCOVERY_UNSUPPORTED", "native_capability_unsupported", True),
        ("WB_STUB_DISCOVERY_FAILED", "native_read_failed", False),
    ],
)
def test_discovery_failure_reason_is_not_inferred_from_text(
    fx: WB, env: str, reason: str, unsupported: bool
) -> None:
    seed(fx, CODEX)
    wb = fx.open(**{env: "1"})
    pid = wb.add_project(str(fx.repo))["project_id"]
    with pytest.raises(BridgeError) as e:
        wb.native_history.discover(pid, CODEX)
    assert e.value.details == {"reason": reason, "capability_unsupported": unsupported}


def test_history_failure_keeps_string_and_adds_machine_reason(fx: WB) -> None:
    native, path = seed(fx, CLAUDE)
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    cid = candidate(wb, pid, CLAUDE, native)["candidate_id"]
    path.unlink()
    preview = wb.native_history.preview(cid)
    assert preview["page"]["state"] == "unavailable"
    assert isinstance(preview["history"]["error"], str)
    assert preview["history"]["reason"] == "native_history_missing"
    assert preview["history"]["capability_unsupported"] is False


@pytest.mark.usefixtures("loopback")
def test_unknown_survives_restart_and_only_exact_native_receipt_settles_it(fx: WB) -> None:
    wb, sid = setup(fx, WB_STUB_TURN_DELIVERY="exit")
    wb.start_run(sid, "resume", confirm_external=True)
    wait_for(lambda: idle(wb, sid))
    wb.send_message(sid, "one ambiguous message", client_id="unknown-restart")
    wait_for(lambda: not WB.view(wb, sid)["active"])
    original = wb.message_delivery(sid, "unknown-restart")
    assert original["delivery"]["state"] == "unknown"
    native = wb.store.get_session(sid)["native_session_id"]
    wb.close()
    fx.instances.remove(wb)
    wb = fx.open()
    server = WorkbenchServer(wb)
    server.start()
    client = Client(server)
    try:
        client.login()
        receipt = client.api("GET", f"/api/sessions/{sid}/delivery?client_id=unknown-restart")
        assert (
            receipt["delivery"]["state"] == "unknown" and receipt["text"] == "one ambiguous message"
        )
        assert wb.conversation(sid, refresh=True)["items"][-1]["status"] == "unknown"
        # Simulate late native persistence: no App send; require the exact native client ID.
        path = Path(fx.env["WB_STUB_HOME"]) / "codex" / f"{native}.turns.json"
        rows = json.loads(path.read_text())
        rows.append(
            {
                "id": "late",
                "status": "completed",
                "items": [
                    {
                        "type": "userMessage",
                        "id": "late",
                        "clientId": "unknown-restart",
                        "content": [{"type": "text", "text": "one ambiguous message"}],
                    }
                ],
            }
        )
        path.write_text(json.dumps(rows))
        visible = wb.conversation(sid, refresh=True)["items"]
        assert sum(i["id"] == "user:unknown-restart" for i in visible) == 1
        assert wb.message_delivery(sid, "unknown-restart")["delivery"]["state"] == "sent"
        # A racing old exit/timeout record cannot turn confirmed delivery back into unknown.
        wb.store.record_delivery(sid, original["run_id"], original)
        assert wb.message_delivery(sid, "unknown-restart")["delivery"]["state"] == "sent"
        assert len(calls(fx, "turn/start")) == 1
    finally:
        server.close()


@pytest.mark.parametrize("native_diagnostic", ["", "synthetic CLI diagnostic"])
def test_run_failure_does_not_freeze_delivery_uncertainty(fx: WB, native_diagnostic: str) -> None:
    wb, sid = setup(fx, WB_STUB_TURN_DELIVERY="exit")
    wb.start_run(sid, "resume", confirm_external=True)
    wait_for(lambda: idle(wb, sid))
    live = wb._live[sid]
    assert live.conv is not None
    # Historical application notice remains diagnostic evidence, not a process-exit summary.
    notice = "这条消息可能已被 Codex 接收，但结果无法确认。"
    live.conv.upsert({"id": "n:old-delivery", "type": "notice", "level": "error", "text": notice})
    if native_diagnostic:
        with (live.run_dir / "stderr.log").open("a") as log:
            log.write(native_diagnostic + "\n")
    wb.send_message(sid, "late proof", client_id="banner-proof")
    wait_for(lambda: not WB.view(wb, sid)["active"])
    run = WB.run(wb, sid)
    assert run["status"] == "failed" and run["exit_code"] == 3 and run["exit_confirmed"]
    assert "退出码 3" in run["failure"] and "无法确认" not in run["failure"]
    assert notice in run["output_tail"]
    if native_diagnostic:
        assert native_diagnostic in run["failure"] and native_diagnostic in run["output_tail"]
    assert wb.message_delivery(sid, "banner-proof")["delivery"]["state"] == "unknown"
    native = wb.store.get_session(sid)["native_session_id"]
    path = Path(fx.env["WB_STUB_HOME"]) / "codex" / f"{native}.turns.json"
    rows = json.loads(path.read_text())
    rows.append(
        {
            "id": "late-proof",
            "status": "completed",
            "items": [
                {
                    "type": "userMessage",
                    "id": "late-proof-user",
                    "clientId": "banner-proof",
                    "content": [{"type": "text", "text": "late proof"}],
                }
            ],
        }
    )
    path.write_text(json.dumps(rows))
    wb.conversation(sid, refresh=True)
    assert wb.message_delivery(sid, "banner-proof")["delivery"]["state"] == "sent"
    assert WB.run(wb, sid) == run
    wb.close()
    fx.instances.remove(wb)
    wb = fx.open()
    wb.conversation(sid, refresh=True)
    assert WB.run(wb, sid) == run
    assert wb.message_delivery(sid, "banner-proof")["delivery"]["state"] == "sent"
    assert len(wb.store.list_runs(sid)) == 1 and len(calls(fx, "turn/start")) == 1
