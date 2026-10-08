"""Conversation view, view switching and official-desktop continuation (T2-W, **stub** CLIs).

The stubs speak the structured protocols the App uses — Claude Code stream-json with the SDK
control protocol, Codex app-server JSON-RPC — and write native-style history, never a model.
Passing here proves the App's side of the contract only; real CLIs/desktop apps are T3-W/T4-W.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.workbench.harness import CLAUDE, CODEX
from harness_bridge.workbench.service import Workbench
from tests.integration.test_workbench import WB, wait_for


@pytest.fixture
def wbx(tmp_path: Path) -> Iterator[WB]:
    fx = WB(tmp_path)
    yield fx
    for wb in fx.instances:
        wb.close(timeout=5)


def items(wb: Workbench, sid: str, kind: str | None = None) -> list[dict[str, Any]]:
    out = wb.conversation(sid)["items"]
    return [i for i in out if kind is None or i["type"] == kind]


def idle(wb: Workbench, sid: str) -> bool:
    c = wb.conversation(sid)
    return c["live"] and c["turn"] is None and WB.view(wb, sid)["phase"] == "waiting"


def turn_ends(wb: Workbench, sid: str) -> list[dict[str, Any]]:
    return items(wb, sid, "turn_end")


def say(wb: Workbench, sid: str, text: str) -> None:
    before = len(turn_ends(wb, sid))
    wb.send_message(sid, text)
    wait_for(lambda: len(turn_ends(wb, sid)) > before and idle(wb, sid))


def pending(wb: Workbench, sid: str) -> dict[str, Any]:
    perms = wait_for(lambda: [i for i in items(wb, sid, "permission") if i["status"] == "pending"])
    return dict(perms[0])


def conversation_session(wb: Workbench, wbx: WB, harness: str) -> str:
    project = wb.add_project(str(wbx.repo))
    session = wb.create_session(project["project_id"], harness, view_mode="conversation")
    sid = str(session["session_id"])
    wait_for(lambda: idle(wb, sid))
    return sid


def test_claude_conversation_streams_reply_and_real_permission_answers(wbx: WB) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CLAUDE)
    run = WB.run(wb, sid)
    assert run["transport"] == "structured"
    argv = json.loads(run["argv_json"])
    assert "-p" in argv and "--permission-prompt-tool" in argv and "--session-id" in argv
    assert "--dangerously-skip-permissions" not in argv and "--bare" not in argv

    say(wb, sid, "hello")
    users = items(wb, sid, "user")
    assert [u["text"] for u in users] == ["hello"] and users[0]["status"] == "sent"
    replies = [a["text"] for a in items(wb, sid, "assistant")]
    assert replies == ["assistant: hello"]
    assert wb.store.get_session(sid)["native_binding"] == "confirmed"
    assert wb.store.get_session(sid)["turns_observed"] == 1

    # A write is asked for, shown as a permission card, and happens only after "allow".
    wb.send_message(sid, "edit made.txt")
    perm = pending(wb, sid)
    assert perm["tool"] == "Write" and perm["title"].endswith("made.txt")
    assert WB.view(wb, sid)["attention"]["kind"] == "permission"
    assert not (wbx.repo / "made.txt").exists()
    wb.answer_permission(sid, perm["request_id"], "allow")
    wait_for(lambda: idle(wb, sid))
    assert (wbx.repo / "made.txt").read_text() == "written by stub stream\n"
    tool = next(i for i in items(wb, sid, "tool") if i["name"] == "Write")
    assert tool["status"] == "ok" and tool["files"][0]["path"].endswith("made.txt")
    assert WB.view(wb, sid)["attention"] is None

    # "Allow and remember" forwards Claude Code's own permission suggestion.
    wb.send_message(sid, "perm")
    perm = pending(wb, sid)
    assert [o["id"] for o in perm["options"]] == ["allow", "allow_always", "deny"]
    wb.answer_permission(sid, perm["request_id"], "allow_always")
    wait_for(lambda: idle(wb, sid))
    assert any("remembered=True" in a["text"] for a in items(wb, sid, "assistant"))

    # Deny is honoured and the tool shows as failed.
    wb.send_message(sid, "edit nope.txt")
    perm = pending(wb, sid)
    wb.answer_permission(sid, perm["request_id"], "deny")
    wait_for(lambda: idle(wb, sid))
    assert not (wbx.repo / "nope.txt").exists()
    with pytest.raises(BridgeError):
        wb.answer_permission(sid, perm["request_id"], "allow")

    # Activity is recorded from the same structured events.
    names = [e["payload"].get("event") for e in wb.activity(sid) if e["kind"] == "activity"]
    assert "PermissionRequest" in names and "PermissionDecision" in names and "Stop" in names


def test_claude_interrupt_auth_failure_retry_and_question(wbx: WB) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CLAUDE)
    wb.send_message(sid, "slow")
    wait_for(lambda: WB.view(wb, sid)["phase"] == "working")
    with pytest.raises(BridgeError, match="上一轮还在进行"):
        wb.send_message(sid, "too soon")
    assert wb.interrupt(sid) == {"interrupted": True}
    wait_for(lambda: idle(wb, sid))
    assert turn_ends(wb, sid)[-1]["status"] == "interrupted"

    say(wb, sid, "authfail")
    end = turn_ends(wb, sid)[-1]
    assert end["status"] == "failed" and "Please run /login" in end["error"]

    say(wb, sid, "retry")
    assert any("正在重试" in n["text"] for n in items(wb, sid, "notice"))

    wb.send_message(sid, "ask")
    perm = pending(wb, sid)
    assert perm["kind"] == "question" and perm["questions"][0]["question"] == "Which color?"
    wb.answer_permission(sid, perm["request_id"], "allow", {"Which color?": "blue"})
    wait_for(lambda: idle(wb, sid))
    assert any('"Which color?": "blue"' in a["text"] for a in items(wb, sid, "assistant"))


def test_codex_conversation_approvals_unsupported_requests_and_history(wbx: WB) -> None:
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CODEX)
    run = WB.run(wb, sid)
    assert json.loads(run["argv_json"])[1:] == ["app-server", "--listen", "stdio://"]
    thread = wait_for(lambda: wb.store.get_session(sid)["native_session_id"])
    assert wb.store.get_session(sid)["native_binding"] == "confirmed"

    say(wb, sid, "hello")
    assert [a["text"] for a in items(wb, sid, "assistant")] == ["codex: hello"]
    assert [u["text"] for u in items(wb, sid, "user")] == ["hello"]

    wb.send_message(sid, "edit c.txt")
    perm = pending(wb, sid)
    assert perm["kind"] == "file" and "c.txt" in perm["detail"]
    wb.answer_permission(sid, perm["request_id"], "allow_session")
    wait_for(lambda: idle(wb, sid))
    assert (wbx.repo / "c.txt").exists()

    wb.send_message(sid, "perm")
    perm = pending(wb, sid)
    assert perm["kind"] == "command" and "rm -rf build" in perm["title"]
    wb.answer_permission(sid, perm["request_id"], "deny")
    wait_for(lambda: idle(wb, sid))
    command = next(i for i in items(wb, sid, "tool") if i["name"] == "命令")
    assert command["status"] == "declined"
    assert any("answer=decline" in a["text"] for a in items(wb, sid, "assistant"))

    # A request RepoBridge cannot answer is refused visibly, not approved silently.
    say(wb, sid, "elicit")
    assert any("MCP" in n["text"] for n in items(wb, sid, "notice"))
    assert any("elicitation=decline" in a["text"] for a in items(wb, sid, "assistant"))

    say(wb, sid, "fail")
    assert turn_ends(wb, sid)[-1]["status"] == "failed"

    wb.stop(sid)
    wait_for(lambda: not WB.view(wb, sid)["active"])
    wb.close(timeout=5)

    # Reopened App: history comes back from the native store via app-server, no turn started.
    wb2 = wbx.open()
    history = wb2.conversation(sid)
    assert history["live"] is False and history["history"]["source"] == "codex"
    texts = [i.get("text") for i in history["items"] if i["type"] in ("user", "assistant")]
    assert texts[:2] == ["hello", "codex: hello"]
    assert WB.view(wb2, sid)["view_mode"] == "conversation"
    say(wb2, sid, "again")
    assert wb2.store.get_session(sid)["native_session_id"] == thread
    assert WB.run(wb2, sid)["kind"] == "resume"
    texts = [i.get("text") for i in items(wb2, sid) if i["type"] in ("user", "assistant")]
    assert texts[0] == "hello" and texts[-1] == "codex: again"


def test_switching_view_reconnects_same_native_session_without_sending(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    session = wb.create_session(project["project_id"], CLAUDE, view_mode="terminal")
    sid = session["session_id"]
    native = session["native_session_id"]
    wait_for(lambda: WB.view(wb, sid)["phase"] == "waiting")
    wbx.send(wb, sid, "hello", "assistant: hello")
    wait_for(lambda: WB.view(wb, sid)["phase"] == "waiting")
    turns = wb.store.get_session(sid)["turns_observed"]

    result = wb.switch_view(sid, "conversation")
    assert result == {"view_mode": "conversation", "reconnected": True, "kind": "resume"}
    runs = wb.store.list_runs(sid)
    assert [r["transport"] for r in runs] == ["pty", "structured"]
    assert runs[0]["status"] == "stopped" and runs[0]["exit_confirmed"] == 1
    assert len([r for r in wb.store.active_runs() if r["workdir"] == str(wbx.repo)]) == 1
    wait_for(lambda: idle(wb, sid))
    # Same native session, its history visible, and nothing was sent by the switch.
    assert wb.store.get_session(sid)["native_session_id"] == native
    assert wb.store.get_session(sid)["turns_observed"] == turns
    history = wb.conversation(sid)
    assert history["history"]["source"] == "claude-transcript"
    assert [i["text"] for i in history["items"] if i["type"] == "user"] == ["hello"]

    # While a turn runs the switch is refused rather than cutting it off.
    wb.send_message(sid, "slow")
    wait_for(lambda: WB.view(wb, sid)["phase"] == "working")
    with pytest.raises(BridgeError) as busy:
        wb.switch_view(sid, "terminal")
    assert busy.value.details == {"idle": "busy"}
    wb.interrupt(sid)
    wait_for(lambda: idle(wb, sid))

    assert wb.switch_view(sid, "terminal")["kind"] == "resume"
    wait_for(lambda: "stub claude ready" in WB.text(wb, sid))
    assert f"session={native}" in WB.text(wb, sid)
    assert [r["transport"] for r in wb.store.list_runs(sid)] == ["pty", "structured", "pty"]


def test_switch_needs_confirmation_when_idle_is_unknown(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    session = wb.create_session(project["project_id"], CODEX, view_mode="terminal")
    sid = session["session_id"]
    wait_for(lambda: "stub codex ready" in WB.text(wb, sid))
    with pytest.raises(BridgeError) as unknown:
        wb.switch_view(sid, "conversation")
    assert unknown.value.details == {"idle": "unknown"}
    assert WB.view(wb, sid)["transport"] == "pty"
    # Confirmed: nothing was said yet, so the conversation view starts a fresh native thread.
    assert wb.switch_view(sid, "conversation", confirm_unknown=True)["kind"] == "new"
    wait_for(lambda: idle(wb, sid))


def test_view_change_without_a_running_process_is_just_a_setting(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    session = wb.create_session(project["project_id"], CLAUDE, start=False)
    sid = session["session_id"]
    assert WB.view(wb, sid)["view_mode"] == "terminal"
    assert wb.switch_view(sid, "conversation") == {
        "view_mode": "conversation",
        "reconnected": False,
    }
    assert wb.store.list_runs(sid) == []
    with pytest.raises(BridgeError, match="终端视图"):
        wb.switch_view(sid, "terminal")
        wb.send_message(sid, "hi")
    # Sending in the conversation view starts the native session on demand.
    sid2 = wb.create_session(project["project_id"], CLAUDE, start=False, view_mode="conversation")[
        "session_id"
    ]
    say(wb, sid2, "first")
    assert WB.run(wb, sid2)["kind"] == "new"


def test_open_in_claude_desktop_releases_first_and_holds_until_return(wbx: WB) -> None:
    wbx.install_app("Claude", "com.anthropic.claudefordesktop", "claude")
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CLAUDE)
    native = wb.store.get_session(sid)["native_session_id"]
    cap = WB.view(wb, sid)["desktop"]
    assert cap["available"] is False and "还没有对话" in cap["reason"]
    say(wb, sid, "hello")
    cap = WB.view(wb, sid)["desktop"]
    assert cap["available"] and cap["command"] == f"claude --desktop --resume {native}"

    with pytest.raises(BridgeError) as running:
        wb.open_in_desktop(sid)
    assert running.value.details == {"needs_release": True}
    result = wb.open_in_desktop(sid, release=True)
    assert result["status"] == "acknowledged" and result["app"] == "Claude Desktop"
    assert WB.run(wb, sid)["status"] == "stopped"
    calls = [json.loads(line) for line in (wbx.base / "stub-home/desktop-calls.log").open()]
    assert calls == [{"argv": ["--desktop", "--resume", native], "tty": True}]
    view = WB.view(wb, sid)
    assert view["external"]["app"] == "Claude Desktop" and not view["active"]

    # RepoBridge does not take the session back silently.
    with pytest.raises(BridgeError) as held:
        wb.send_message(sid, "back")
    assert held.value.details["external"]["app"] == "Claude Desktop"
    wb.close(timeout=5)

    wb2 = wbx.open()
    assert WB.view(wb2, sid)["external"]["status"] == "acknowledged"
    say_confirmed = wb2.send_message(sid, "back", confirm_external=True)
    assert say_confirmed["client_id"]
    wait_for(lambda: idle(wb2, sid) and len(turn_ends(wb2, sid)) >= 1)
    assert WB.view(wb2, sid)["external"] is None
    assert WB.run(wb2, sid)["kind"] == "resume"
    events = [e["kind"] for e in wb2.activity(sid)]
    assert "desktop_open" in events and "desktop_returned" in events


def test_open_in_codex_uses_the_existing_thread_link(wbx: WB) -> None:
    wbx.install_app("ChatGPT", "com.openai.codex", "codex")
    wb = wbx.open()
    sid = conversation_session(wb, wbx, CODEX)
    say(wb, sid, "hello")
    thread = wb.store.get_session(sid)["native_session_id"]
    result = wb.open_in_desktop(sid, release=True)
    assert result["status"] == "requested" and result["app"] == "Codex"
    opened = wbx.opened.read_text().split()
    assert opened == ["-a", str(wbx.apps / "ChatGPT.app"), f"codex://threads/{thread}"]
    assert wb.desktop_return(sid) == {"external": None}
    assert WB.view(wb, sid)["external"] is None


def test_desktop_unavailable_reasons_and_cli_desktop_command(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    session = wb.create_session(project["project_id"], CLAUDE, view_mode="terminal")
    sid = session["session_id"]
    assert "没有在" in WB.view(wb, sid)["desktop"]["reason"]
    with pytest.raises(BridgeError):
        wb.open_in_desktop(sid, release=True)
    # /desktop typed in the native TUI hands the session over; RepoBridge notices and holds.
    wait_for(lambda: WB.view(wb, sid)["phase"] == "waiting")
    wbx.send(wb, sid, "hello", "assistant: hello")
    wb.write_input(sid, b"/desktop\r")
    wait_for(lambda: not WB.view(wb, sid)["active"])
    external = WB.view(wb, sid)["external"]
    assert external["via"] == "cli /desktop"
    with pytest.raises(BridgeError):
        wb.start_run(sid, "resume")
    wb.start_run(sid, "resume", confirm_external=True)
    wait_for(lambda: WB.view(wb, sid)["active"])
