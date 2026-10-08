"""Model / effort / permission-mode controls, attachments and native forms (T2-W, **stub** CLIs).

The stubs keep their own model, effort and mode state, change it only through the protocol
requests the real CLIs document (Claude Code control requests, Codex thread/turn parameters),
report it back the way the real CLIs do, and log every request. Passing here proves that the
App sends the right native requests and only shows a choice as in force when the host says so.
Real CLIs are T3-W (see docs/WORKBENCH.md).
"""

from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.workbench.harness import CLAUDE, CODEX
from harness_bridge.workbench.service import Workbench
from tests.integration.test_workbench import WB, wait_for
from tests.integration.test_workbench_conversation import (
    conversation_session,
    idle,
    items,
    pending,
    say,
)


@pytest.fixture
def wbx(tmp_path: Path) -> Iterator[WB]:
    fx = WB(tmp_path)
    yield fx
    for wb in fx.instances:
        wb.close(timeout=5)


def png() -> bytes:
    raw = b"\x00\xff\x00\x00"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def settings(wb: Workbench, sid: str) -> dict[str, Any]:
    return dict(WB.view(wb, sid)["settings"])


def field_state(wb: Workbench, sid: str, name: str) -> str | None:
    rec = settings(wb, sid)["fields"].get(name) or {}
    return rec.get("state")


def log(wbx: WB, name: str) -> list[dict[str, Any]]:
    path = wbx.base / "stub-home" / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def replies(wb: Workbench, sid: str) -> list[str]:
    return [a["text"] for a in items(wb, sid, "assistant")]


def test_claude_model_effort_and_mode_are_applied_and_confirmed_by_the_cli(wbx: WB) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CLAUDE)
    # The catalog comes from Claude Code's own initialize response, not a built-in list.
    catalog = wait_for(lambda: wb.catalog(CLAUDE))
    assert catalog["source"] == "initialize"
    ids = [m["id"] for m in catalog["models"]]
    assert ids == ["default", "stub-sonnet", "stub-haiku", "stub-locked"]
    sonnet = next(m for m in catalog["models"] if m["id"] == "stub-sonnet")
    assert sonnet["efforts"] == ["low", "medium", "high"]
    assert [c["name"] for c in catalog["commands"]] == ["compact", "review"]
    # What is in force right now is read back with get_settings.
    actual = wait_for(lambda: settings(wb, sid)["actual"].get("model") and settings(wb, sid))
    assert actual["actual"]["model"] == "claude-stub-opus" and actual["actual"]["live"]

    view = wb.choose_settings(
        sid, {"model": "stub-sonnet", "effort": "high", "mode": "acceptEdits"}
    )
    assert view["chosen"] == {"model": "stub-sonnet", "effort": "high", "mode": "acceptEdits"}
    for name in ("model", "effort", "mode"):
        wait_for(lambda n=name: field_state(wb, sid, n) == "confirmed")
    sent = [
        (e["subtype"], e.get("model") or e.get("settings") or e.get("mode"))
        for e in log(wbx, "claude-controls.log")
        if e.get("subtype") in ("set_model", "apply_flag_settings", "set_permission_mode")
    ]
    assert sent == [
        ("set_model", "stub-sonnet"),
        ("apply_flag_settings", {"effortLevel": "high"}),
        ("set_permission_mode", "acceptEdits"),
    ]
    actual = settings(wb, sid)["actual"]
    assert actual["model"] == "claude-stub-sonnet" and actual["effort"] == "high"
    assert actual["mode"] == "acceptEdits"

    # The next turn really runs with them, and the API's own model is shown for the turn.
    say(wb, sid, "whoami")
    assert replies(wb, sid)[-1] == "model=claude-stub-sonnet effort=high mode=acceptEdits"
    assert items(wb, sid, "turn_end")[-1]["model"] == "claude-stub-sonnet"
    assert settings(wb, sid)["turn_model"] == "claude-stub-sonnet"

    # Invalid combinations are refused from the catalog, before anything is sent.
    with pytest.raises(BridgeError, match="支持的思考强度"):
        wb.choose_settings(sid, {"effort": "max"})
    with pytest.raises(BridgeError, match="不提供"):
        wb.choose_settings(sid, {"mode": "bypassPermissions"})
    with pytest.raises(BridgeError, match="不在当前 CLI"):
        wb.choose_settings(sid, {"model": "made-up"})

    # A model without effort levels: the effort choice is dropped and the user is told.
    view = wb.choose_settings(sid, {"model": "stub-haiku"})
    assert "effort" not in view["chosen"]
    assert any("不支持思考强度" in n["text"] for n in view["notices"])
    wait_for(lambda: field_state(wb, sid, "model") == "confirmed")

    # The CLI refuses a model: the failure is shown and the old model stays in force.
    wb.choose_settings(sid, {"model": "stub-locked"})
    wait_for(lambda: field_state(wb, sid, "model") == "failed")
    rec = settings(wb, sid)["fields"]["model"]
    assert "not available for your organization" in rec["error"]
    assert rec["attempted"] == "stub-locked"
    assert settings(wb, sid)["chosen"]["model"] == "stub-haiku"
    say(wb, sid, "whoami")
    assert replies(wb, sid)[-1].startswith("model=claude-stub-haiku")


def test_refused_model_does_not_drag_dependent_changes_with_it(wbx: WB) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CLAUDE)
    wait_for(lambda: wb.catalog(CLAUDE))
    wb.choose_settings(sid, {"model": "stub-sonnet", "effort": "high"})
    wait_for(lambda: field_state(wb, sid, "effort") == "confirmed")
    # Stub Locked has no effort levels, so choosing it also resets the effort...
    view = wb.choose_settings(sid, {"model": "stub-locked"})
    assert "effort" not in view["chosen"]
    wait_for(lambda: field_state(wb, sid, "model") == "failed")
    # ...but the CLI refused the model, so the effort reset is rolled back, never sent.
    assert settings(wb, sid)["chosen"] == {"model": "stub-sonnet", "effort": "high"}
    assert field_state(wb, sid, "effort") == "confirmed"
    efforts = [
        e["settings"]
        for e in log(wbx, "claude-controls.log")
        if e.get("subtype") == "apply_flag_settings"
    ]
    assert efforts == [{"effortLevel": "high"}]
    say(wb, sid, "whoami")
    assert replies(wb, sid)[-1] == "model=claude-stub-sonnet effort=high mode=default"


def test_claude_choice_during_a_turn_waits_for_the_turn_and_never_touches_it(wbx: WB) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CLAUDE)
    wait_for(lambda: wb.catalog(CLAUDE))
    wb.send_message(sid, "slow")
    wait_for(lambda: wb.conversation(sid)["turn"] is not None)
    wb.choose_settings(sid, {"model": "stub-sonnet"})
    assert field_state(wb, sid, "model") == "selected"
    assert not [e for e in log(wbx, "claude-controls.log") if e.get("subtype") == "set_model"]
    wb.interrupt(sid)
    wait_for(lambda: idle(wb, sid))
    wait_for(lambda: field_state(wb, sid, "model") == "confirmed")
    say(wb, sid, "whoami")
    assert replies(wb, sid)[-1].startswith("model=claude-stub-sonnet")


def test_refused_choice_at_connect_blocks_the_send_instead_of_using_another_model(
    wbx: WB,
) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CLAUDE)
    say(wb, sid, "hello")
    wb.stop(sid)
    wait_for(lambda: not WB.view(wb, sid)["active"])
    # Chosen while disconnected: recorded, applied when the next connection starts.
    wb.choose_settings(sid, {"model": "stub-locked"})
    assert field_state(wb, sid, "model") == "selected"
    with pytest.raises(BridgeError, match="草稿已保留"):
        wb.send_message(sid, "with the locked model")
    assert field_state(wb, sid, "model") == "failed"
    turns = [e for e in log(wbx, "claude-controls.log") if "turn" in e]
    assert [t["turn"] for t in turns] == ["hello"]
    # The user sees the failure; sending again uses the model that is actually in force.
    say(wb, sid, "whoami")
    assert replies(wb, sid)[-1].startswith("model=claude-stub-opus")


def test_choices_survive_view_switch_and_restart_and_reach_the_terminal_as_flags(
    wbx: WB,
) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CLAUDE)
    wait_for(lambda: wb.catalog(CLAUDE))
    wb.choose_settings(sid, {"model": "stub-sonnet", "effort": "low", "mode": "plan"})
    wait_for(lambda: field_state(wb, sid, "mode") == "confirmed")
    say(wb, sid, "hello")

    wb.switch_view(sid, "terminal")
    argv = json.loads(WB.run(wb, sid)["argv_json"])
    tail = argv[argv.index("--resume") :]
    assert tail[tail.index("--model") : tail.index("--model") + 2] == ["--model", "stub-sonnet"]
    assert "--effort" in tail and tail[tail.index("--effort") + 1] == "low"
    assert tail[tail.index("--permission-mode") + 1] == "plan"
    # A terminal cannot report back: the choices are shown as passed, not as confirmed.
    assert settings(wb, sid)["fields"]["model"]["state"] == "launched"
    assert settings(wb, sid)["actual"]["live"] is False

    wait_for(lambda: WB.view(wb, sid)["phase"] == "waiting")
    wb.switch_view(sid, "conversation")
    wait_for(lambda: field_state(wb, sid, "model") == "confirmed")
    wait_for(lambda: field_state(wb, sid, "mode") == "confirmed")
    say(wb, sid, "whoami")
    assert replies(wb, sid)[-1] == "model=claude-stub-sonnet effort=low mode=plan"
    wb.stop(sid)
    wait_for(lambda: not WB.view(wb, sid)["active"])
    wb.close(timeout=5)

    wb2 = wbx.open()
    assert settings(wb2, sid)["chosen"] == {"model": "stub-sonnet", "effort": "low", "mode": "plan"}
    say(wb2, sid, "whoami")
    assert replies(wb2, sid)[-1] == "model=claude-stub-sonnet effort=low mode=plan"
    assert field_state(wb2, sid, "effort") == "confirmed"


def test_codex_choices_travel_with_the_next_turn_and_are_read_back(wbx: WB) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CODEX)
    catalog = wait_for(lambda: wb.catalog(CODEX))
    assert catalog["source"] == "model/list"
    assert [m["id"] for m in catalog["models"]] == ["stub-codex", "stub-codex-mini"]
    assert catalog["default_model"] == "stub-codex"
    mini = next(m for m in catalog["models"] if m["id"] == "stub-codex-mini")
    assert mini["images"] is False and mini["efforts"] == ["low", "medium"]
    actual = wait_for(lambda: settings(wb, sid)["actual"].get("mode") and settings(wb, sid))
    assert actual["actual"]["model"] == "stub-codex" and actual["actual"]["mode"] == "workspace"
    # Who answers approvals is Codex's own setting; it is shown, never changed.
    assert actual["actual"]["reviewer"] == "user"

    wb.choose_settings(sid, {"model": "stub-codex-mini", "effort": "low", "mode": "read-only"})
    # Codex has no "set" request: the choice waits for the next turn, it is not claimed yet.
    assert field_state(wb, sid, "model") == "selected"
    assert not [e for e in log(wbx, "codex-rpc.log") if e.get("method") == "turn/start"]

    say(wb, sid, "whoami")
    assert replies(wb, sid)[-1] == (
        "model=stub-codex-mini effort=low approval=on-request sandbox=readOnly"
    )
    start = [e for e in log(wbx, "codex-rpc.log") if e.get("method") == "turn/start"][-1]
    assert start["params"]["model"] == "stub-codex-mini" and start["params"]["effort"] == "low"
    assert start["params"]["sandboxPolicy"] == {"type": "readOnly"}
    for name in ("model", "effort", "mode"):
        wait_for(lambda n=name: field_state(wb, sid, n) == "confirmed")
    sources = settings(wb, sid)["actual"]["sources"]
    assert sources["model"] == "thread/read" and sources["mode"] == "thread/resume"

    # Images are refused for a model whose catalog entry has no image input.
    att = wb.add_attachment(sid, name="shot.png", data=png())
    with pytest.raises(BridgeError, match="不接受图片"):
        wb.send_message(sid, "look", attachments=[att["id"]])

    # Reconnecting passes the choices as thread/resume parameters (the sandbox does not
    # persist in Codex's own store) and confirms them from the resume result.
    wb.stop(sid)
    wait_for(lambda: not WB.view(wb, sid)["active"])
    say(wb, sid, "whoami")
    resume = [
        e
        for e in log(wbx, "codex-rpc.log")
        if e.get("method") == "thread/resume" and "model" in e["params"]
    ][-1]
    assert resume["params"]["sandbox"] == "read-only"
    assert resume["params"]["model"] == "stub-codex-mini"
    assert resume["params"]["config"] == {"model_reasoning_effort": "low"}
    assert field_state(wb, sid, "mode") == "confirmed"


def test_codex_org_requirements_limit_the_modes(wbx: WB) -> None:
    wb = wbx.open(WB_STUB_CODEX_READONLY_ONLY="1")
    sid = conversation_session(wb, wbx, CODEX)
    catalog = wait_for(lambda: wb.catalog(CODEX))
    modes = {m["id"]: m for m in catalog["modes"]}
    assert modes["read-only"]["available"] and not modes["workspace"]["available"]
    with pytest.raises(BridgeError, match="组织策略"):
        wb.choose_settings(sid, {"mode": "workspace"})


def test_codex_questions_and_mcp_forms_are_answered_in_the_conversation(wbx: WB) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CODEX)
    wb.send_message(sid, "ask")
    card = pending(wb, sid)
    assert card["kind"] == "question" and card["answer_key"] == "id"
    lang, token = card["questions"]
    assert [o["label"] for o in lang["options"]] == ["Python", "Go"] and lang["other"]
    assert token["secret"] and token["options"] == []
    with pytest.raises(BridgeError, match="至少回答"):
        wb.answer_permission(sid, card["request_id"], "answer", {})
    wb.answer_permission(sid, card["request_id"], "answer", {"lang": "Go", "token": "s3cret"})
    wait_for(lambda: idle(wb, sid))
    assert replies(wb, sid)[-1] == (
        'answers={"lang": {"answers": ["Go"]}, "token": {"answers": ["s3cret"]}}'
    )
    answered = next(i for i in items(wb, sid, "permission") if i["id"] == card["id"])
    assert answered["status"] == "allowed" and "s3cret" not in json.dumps(answered)

    wb.send_message(sid, "elicit")
    form = pending(wb, sid)
    assert form["kind"] == "form" and form["form"]["mode"] == "form"
    names = [f["name"] for f in form["form"]["fields"]]
    assert names == ["env", "replicas", "dry"]
    with pytest.raises(BridgeError, match="必填"):
        wb.answer_permission(sid, form["request_id"], "accept", {"replicas": "2"})
    with pytest.raises(BridgeError, match="选项无效"):
        wb.answer_permission(sid, form["request_id"], "accept", {"env": "moon"})
    wb.answer_permission(
        sid, form["request_id"], "accept", {"env": "prod", "replicas": "3", "dry": True}
    )
    wait_for(lambda: idle(wb, sid))
    assert replies(wb, sid)[-1] == (
        'elicitation=accept content={"dry": true, "env": "prod", "replicas": 3}'
    )
    wb.send_message(sid, "elicit")
    form = pending(wb, sid)
    wb.answer_permission(sid, form["request_id"], "decline")
    wait_for(lambda: idle(wb, sid))
    assert replies(wb, sid)[-1].startswith("elicitation=decline")


def test_attachments_reach_both_clis_natively(wbx: WB) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CLAUDE)
    image = wb.add_attachment(sid, name="screen.png", data=png())
    note = wb.add_attachment(sid, name="notes.txt", data=b"first line of notes\nmore\n")
    fake = wb.add_attachment(sid, name="fake.png", data=b"not really an image")
    assert image["kind"] == "image" and image["mime"] == "image/png"
    assert note["kind"] == "file" and fake["kind"] == "file"
    assert "path" not in image
    say_with = [image["id"], note["id"]]
    before = len(items(wb, sid, "turn_end"))
    wb.send_message(sid, "what is in these?", attachments=say_with)
    wait_for(lambda: len(items(wb, sid, "turn_end")) > before and idle(wb, sid))
    assert replies(wb, sid)[-1] == "images=['image/png'] files=['first line of notes']"
    user = items(wb, sid, "user")[-1]
    assert user["text"] == "what is in these?" and user["status"] == "sent"
    assert [(a["kind"], a["name"]) for a in user["attachments"]] == [
        ("image", "screen.png"),
        ("file", "notes.txt"),
    ]
    with pytest.raises(BridgeError, match="太大"):
        wb.add_attachment(sid, name="big.png", data=png()[:8] + b"\0" * (6 << 20))
    with pytest.raises(BridgeError, match="附件 ID"):
        wb.send_message(sid, "x", attachments=["../etc"])

    wb.stop(sid)
    wait_for(lambda: not WB.view(wb, sid)["active"])
    cid = conversation_session(wb, wbx, CODEX)
    att = wb.add_attachment(cid, name="screen.png", data=png())
    before = len(items(wb, cid, "turn_end"))
    wb.send_message(cid, "", attachments=[att["id"]])
    wait_for(lambda: len(items(wb, cid, "turn_end")) > before and idle(wb, cid))
    assert replies(wb, cid)[-1] == "images=1"
    turn = [e for e in log(wbx, "codex-rpc.log") if "turn" in e][-1]
    assert len(turn["images"]) == 1 and Path(turn["images"][0]).read_bytes() == png()


def test_catalog_probe_starts_no_session_and_file_search(wbx: WB) -> None:
    wb = wbx.open()
    assert wb.snapshot()["catalogs"][CLAUDE]["status"] == "missing"
    wb.refresh_catalog(CLAUDE)
    wait_for(lambda: wb.snapshot()["catalogs"][CLAUDE]["status"] == "ok")
    wb.refresh_catalog(CODEX)
    wait_for(lambda: wb.snapshot()["catalogs"][CODEX]["status"] == "ok")
    assert not (wbx.base / "stub-home" / "claude").exists()
    methods = [e["method"] for e in log(wbx, "codex-rpc.log")]
    assert "model/list" in methods and "thread/start" not in methods
    assert not [e for e in log(wbx, "claude-controls.log") if "turn" in e]

    # Terminal launches pass explicit choices as the CLIs' own flags.
    project = wb.add_project(str(wbx.repo))
    session = wb.create_session(project["project_id"], CODEX, start=False, view_mode="terminal")
    sid = session["session_id"]
    wb.choose_settings(sid, {"model": "stub-codex-mini", "effort": "low", "mode": "read-only"})
    wb.start_run(sid, "new")
    argv = json.loads(WB.run(wb, sid)["argv_json"])
    assert argv[argv.index("-m") + 1] == "stub-codex-mini"
    assert 'model_reasoning_effort="low"' in argv
    assert argv[argv.index("-a") + 1] == "on-request" and argv[argv.index("-s") + 1] == "read-only"
    wb.stop(sid)
    wait_for(lambda: not WB.view(wb, sid)["active"])

    (wbx.repo / "src").mkdir()
    (wbx.repo / "src" / "ledger.py").write_text("x\n")
    found = [f["path"] for f in wb.search_files(sid, "ledg")]
    assert found[0] == "src/ledger.py"
    assert [f["path"] for f in wb.search_files(sid, "rdme")] == ["README.md"]


def test_codex_single_writer_lock_is_reported_as_an_actionable_failure(wbx: WB) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CODEX)
    say(wb, sid, "hello")
    wb.stop(sid)
    wait_for(lambda: not WB.view(wb, sid)["active"])
    wb.close(timeout=5)
    # The thread is now held by another writer (the Codex app): RepoBridge must not force it.
    wb2 = wbx.open(WB_STUB_CODEX_WRITER_BUSY="1")
    try:
        wb2.send_message(sid, "again")
    except BridgeError:
        pass
    wait_for(lambda: WB.run(wb2, sid)["status"] == "failed")
    failure = WB.run(wb2, sid)["failure"]
    assert "already has an active writer" in failure and "Codex App" in failure
    assert not [e for e in log(wbx, "codex-rpc.log") if e.get("turn") == "again"]
