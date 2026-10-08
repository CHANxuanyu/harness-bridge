"""Units for the conversation model: native-message translation, history, desktop, migration."""

from __future__ import annotations

import json
import plistlib
import sqlite3
from pathlib import Path
from typing import Any

from harness_bridge.workbench import desktop_apps
from harness_bridge.workbench.conversation import (
    ClaudeTranslator,
    CodexTranslator,
    Conversation,
    claude_permission_response,
    claude_transcript_items,
    codex_item,
    codex_permission_response,
    codex_turn_items,
    find_claude_transcript,
)
from harness_bridge.workbench.store import WorkbenchStore
from harness_bridge.workbench.structured import build_structured, claude_argv


def _ev(event: dict[str, Any]) -> dict[str, Any]:
    return {"type": "stream_event", "parent_tool_use_id": None, "event": event}


def test_claude_stream_partials_final_message_and_subagent_noise() -> None:
    ops: list[dict[str, Any]] = []
    conv = Conversation(emit=ops.append)
    t = ClaudeTranslator(conv)
    t.begin_turn("c1", "hi")
    t.feed(_ev({"type": "message_start", "message": {"id": "m1"}}))
    t.feed(_ev({"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}))
    t.feed(
        _ev(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hel"},
            }
        )
    )
    t.feed(
        _ev(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "lo"},
            }
        )
    )
    assert conv.get("a:m1:0")["text"] == "Hello" and conv.get("a:m1:0")["streaming"]
    # Subagent traffic is attributed to the tool that started it, not shown as chat.
    t.feed({"type": "assistant", "parent_tool_use_id": "toolX", "message": {"content": []}})
    t.feed(
        {
            "type": "assistant",
            "parent_tool_use_id": None,
            "message": {"id": "m1", "content": [{"type": "text", "text": "Hello!"}]},
        }
    )
    assert conv.get("a:m1:0") == {**conv.get("a:m1:0"), "text": "Hello!", "streaming": False}
    assert [o["op"] for o in ops].count("delta") == 2
    t.feed(
        {"type": "system", "subtype": "init", "session_id": "s", "permissionMode": "acceptEdits"}
    )
    assert any("自动接受编辑" in i["text"] for i in conv.items() if i["type"] == "notice")
    t.feed({"type": "result", "subtype": "success", "is_error": False, "duration_ms": 5})
    assert conv.turn is None
    assert conv.items()[0] == {**conv.items()[0], "type": "user", "status": "sent"}


def test_claude_permission_request_cancel_and_response_shapes() -> None:
    conv = Conversation()
    t = ClaudeTranslator(conv)
    out = t.feed(
        {
            "type": "control_request",
            "request_id": "r1",
            "request": {
                "subtype": "can_use_tool",
                "tool_name": "Bash",
                "input": {"command": "ls -la", "description": "List"},
                "tool_use_id": "tu1",
                "permission_suggestions": [{"type": "addRules"}],
            },
        }
    )
    assert out is not None and out["permission"]["title"] == "ls -la"
    assert conv.get("tu1")["status"] == "waiting"
    assert "List" in conv.get("perm:r1")["detail"]
    request = {"input": out["input"], "suggestions": out["suggestions"]}
    assert claude_permission_response("deny", request)["behavior"] == "deny"
    allow = claude_permission_response("allow_always", request)
    assert allow["updatedInput"] == {"command": "ls -la", "description": "List"}
    assert allow["updatedPermissions"] == [{"type": "addRules"}]
    assert "updatedPermissions" not in claude_permission_response("allow", request)
    t.feed({"type": "control_cancel_request", "request_id": "r1"})
    assert conv.get("perm:r1")["status"] == "cancelled"
    other = t.feed(
        {"type": "control_request", "request_id": "r2", "request": {"subtype": "hook_callback"}}
    )
    assert other == {"request_id": "r2", "unsupported": "hook_callback"}


def test_claude_transcript_projection(tmp_path: Path) -> None:
    sid = "0b5c3b2e-2d3a-4c39-9c9e-111111111111"
    path = tmp_path / ".claude" / "projects" / "-tmp-x" / f"{sid}.jsonl"
    path.parent.mkdir(parents=True)
    lines = [
        {"type": "summary", "summary": "x"},
        {"type": "user", "uuid": "u0", "isMeta": True, "message": {"content": "meta"}},
        {
            "type": "user",
            "uuid": "u1",
            "message": {"content": "<command-name>/model</command-name>"},
        },
        {"type": "user", "uuid": "u2", "message": {"content": "fix the bug"}},
        {
            "type": "assistant",
            "uuid": "a1",
            "message": {
                "id": "m",
                "content": [
                    {"type": "thinking", "thinking": "hmm"},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Edit",
                        "input": {"file_path": "/r/a.py"},
                    },
                ],
            },
        },
        {"type": "user", "uuid": "u3", "isSidechain": True, "message": {"content": "side"}},
        {
            "type": "user",
            "uuid": "u4",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok", "is_error": True}
                ]
            },
        },
        {
            "type": "assistant",
            "uuid": "a2",
            "message": {"content": [{"type": "text", "text": "Done."}]},
        },
        "not json",
    ]
    path.write_text("\n".join(json.dumps(x) if isinstance(x, dict) else x for x in lines) + "\n")
    env = {"HOME": str(tmp_path)}
    assert find_claude_transcript(env, sid) == path
    assert find_claude_transcript(env, "../etc") is None
    items = claude_transcript_items(path)
    kinds = [(i["type"], i.get("text") or i.get("name")) for i in items]
    assert kinds == [
        ("notice", "执行了命令 /model"),
        ("user", "fix the bug"),
        ("reasoning", "hmm"),
        ("tool", "Edit"),
        ("assistant", "Done."),
    ]
    tool = items[3]
    assert tool["status"] == "failed" and tool["files"] == [{"path": "/r/a.py", "kind": "edit"}]
    assert find_claude_transcript({"CLAUDE_CONFIG_DIR": str(tmp_path / ".claude")}, sid) == path


def test_codex_items_turns_and_permission_responses() -> None:
    cmd = codex_item(
        {
            "type": "commandExecution",
            "id": "c",
            "command": "pytest -q",
            "cwd": "/r",
            "status": "completed",
            "exitCode": 1,
            "commandActions": [],
        }
    )
    assert cmd["status"] == "failed" and cmd["exit_code"] == 1 and cmd["title"] == "pytest -q"
    fc = codex_item(
        {
            "type": "fileChange",
            "id": "f",
            "status": "declined",
            "changes": [{"path": "a.txt", "kind": {"type": "add"}, "diff": "+x"}],
        }
    )
    assert fc["status"] == "declined" and fc["files"][0] == {
        "path": "a.txt",
        "kind": "add",
        "diff": "+x",
    }
    assert codex_item({"type": "somethingNew", "id": "z"})["type"] == "notice"
    user = codex_item(
        {
            "type": "userMessage",
            "id": "u",
            "clientId": "c9",
            "content": [{"type": "text", "text": "hi"}],
        },
        client_ids={"c9": "user:c9"},
    )
    assert user["id"] == "user:c9"
    items = codex_turn_items(
        [
            {
                "id": "t1",
                "status": "failed",
                "error": {"message": "boom"},
                "items": [{"type": "agentMessage", "id": "a", "text": "x"}],
            }
        ]
    )
    assert items[-1] == {
        "id": "end:t1",
        "type": "turn_end",
        "status": "failed",
        "error": "boom",
        "duration_ms": None,
    }
    assert codex_permission_response(
        "item/commandExecution/requestApproval", "allow_session", {}
    ) == {"decision": "acceptForSession"}
    assert codex_permission_response("item/fileChange/requestApproval", "deny", {}) == {
        "decision": "decline"
    }
    granted = codex_permission_response(
        "item/permissions/requestApproval", "allow_session", {"permissions": {"network": {}}}
    )
    assert granted == {"permissions": {"network": {}}, "scope": "session"}
    assert codex_permission_response(
        "item/permissions/requestApproval", "deny", {"permissions": {"network": {}}}
    ) == {"permissions": {}}


def test_codex_translator_streams_and_dedupes_echoed_user_message() -> None:
    conv = Conversation()
    t = CodexTranslator(conv)
    t.begin_turn("k1", "hello")
    t.notification("turn/started", {"turn": {"id": "T"}})
    t.notification(
        "item/started",
        {"item": {"type": "userMessage", "id": "srv", "clientId": "k1", "content": []}},
    )
    t.notification("item/started", {"item": {"type": "agentMessage", "id": "a", "text": ""}})
    t.notification("item/agentMessage/delta", {"itemId": "a", "delta": "par"})
    t.notification("item/agentMessage/delta", {"itemId": "a", "delta": "tial"})
    t.notification(
        "item/started",
        {
            "item": {
                "type": "commandExecution",
                "id": "c",
                "command": "ls",
                "cwd": "/",
                "status": "inProgress",
                "commandActions": [],
            }
        },
    )
    t.notification("item/commandExecution/outputDelta", {"itemId": "c", "delta": "a\nb\n"})
    perm = t.server_request(
        "7", "item/commandExecution/requestApproval", {"itemId": "c", "command": "ls"}
    )
    assert perm is not None and conv.get("c")["status"] == "waiting"
    t.notification("serverRequest/resolved", {"requestId": 7})
    assert conv.get("perm:7")["status"] == "cancelled"
    assert t.server_request("8", "item/tool/requestUserInput", {}) is None
    t.notification("turn/completed", {"turn": {"id": "T", "status": "interrupted"}})
    users = [i for i in conv.items() if i["type"] == "user"]
    assert [u["id"] for u in users] == ["user:k1"] and users[0]["status"] == "sent"
    assert conv.get("a")["text"] == "partial"
    assert conv.get("c")["status"] == "interrupted" and conv.get("c")["output"] == "a\nb\n"
    assert conv.turn is None


def test_output_is_capped_with_an_explicit_marker() -> None:
    conv = Conversation()
    conv.upsert({"id": "x", "type": "tool", "output": ""})
    conv.append("x", "output", "a" * 50, cap=40)
    conv.append("x", "output", "b" * 10, cap=40)
    item = conv.get("x")
    assert item["output"] == "a" * 40 and item["output_truncated"] and item["output_omitted"] == 20


def test_structured_argv_never_bypasses_permissions_or_login() -> None:
    argv = claude_argv("/bin/claude", mode="resume", session_id="s", title="t")
    assert argv[:2] == ["/bin/claude", "-p"] and argv[-2:] == ["--resume", "s"]
    for forbidden in ("--bare", "--dangerously-skip-permissions", "--permission-mode"):
        assert forbidden not in argv
    spec = build_structured(
        "codex",
        "/bin/codex",
        mode="new",
        workdir="/r",
        title="t",
        native_session_id=None,
        base_env={"PATH": "/bin", "OPENAI_API_KEY": "sk-x", "ANTHROPIC_API_KEY": "a"},
    )
    assert "OPENAI_API_KEY" not in spec.env and "ANTHROPIC_API_KEY" not in spec.env
    assert spec.stripped_env == ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]


def test_desktop_app_discovery_and_capability(tmp_path: Path) -> None:
    for name, bundle, scheme in (
        ("Claude", "com.anthropic.claudefordesktop", "claude"),
        ("ChatGPT", "com.openai.codex", "codex"),
        ("Fake", "com.example.fake", "codex"),
    ):
        contents = tmp_path / f"{name}.app" / "Contents"
        contents.mkdir(parents=True)
        info = {
            "CFBundleIdentifier": bundle,
            "CFBundleShortVersionString": "9",
            "CFBundleURLTypes": [{"CFBundleURLSchemes": [scheme]}],
        }
        (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    apps = desktop_apps.find_apps([str(tmp_path)])
    assert {k: Path(a.path).name for k, a in apps.items()} == {
        "claude-code": "Claude.app",
        "codex": "ChatGPT.app",
    }
    session = {
        "harness": "claude-code",
        "native_session_id": "0b5c3b2e-2d3a-4c39-9c9e-111111111111",
        "turns_observed": 2,
    }
    cap = desktop_apps.capability(
        session, apps=apps, cli_version="2.1.291 (Claude Code)", platform="darwin"
    )
    assert cap["available"] and cap["command"].startswith("claude --desktop --resume")
    old = desktop_apps.capability(session, apps=apps, cli_version="2.1.200", platform="darwin")
    assert not old["available"] and "2.1.285" in old["reason"]
    assert (
        "macOS"
        in desktop_apps.capability(session, apps=apps, cli_version="2.1.291", platform="linux")[
            "reason"
        ]
    )
    codex = desktop_apps.capability(
        {**session, "harness": "codex"}, apps=apps, cli_version=None, platform="darwin"
    )
    assert codex["available"] and codex["link"] == f"codex://threads/{session['native_session_id']}"


def test_store_migrates_revision_1_without_losing_sessions(tmp_path: Path) -> None:
    path = tmp_path / "workbench.sqlite3"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta VALUES ('schema_revision', '1');
        CREATE TABLE projects (project_id TEXT PRIMARY KEY, name TEXT NOT NULL,
            root_path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE sessions (session_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            harness TEXT NOT NULL, title TEXT NOT NULL, workdir TEXT NOT NULL,
            native_session_id TEXT, native_binding TEXT NOT NULL,
            handoff_from TEXT, turns_observed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE runs (run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, seq INTEGER NOT NULL,
            kind TEXT NOT NULL, workdir TEXT NOT NULL, status TEXT NOT NULL,
            argv_json TEXT NOT NULL,
            stripped_env_json TEXT NOT NULL, pid INTEGER, pgid INTEGER, birth TEXT,
            exit_code INTEGER, exit_signal INTEGER, exit_confirmed INTEGER,
            stop_requested INTEGER NOT NULL DEFAULT 0,
            failure TEXT, output_tail TEXT, started_at TEXT NOT NULL, ended_at TEXT);
        INSERT INTO projects VALUES ('prj_000000000001', 'p', '/r', 't', 0);
        INSERT INTO sessions VALUES ('ses_000000000001', 'prj_000000000001', 'codex', 'old', '/r',
            'th', 'observed', NULL, 3, 't', 't', 0);
        INSERT INTO runs VALUES ('run_1', 'ses_000000000001', 1, 'new', '/r', 'exited', '[]', '[]',
            NULL, NULL, NULL, 0, NULL, 1, 0, NULL, NULL, 't', 't');
        """
    )
    db.commit()
    db.close()
    store = WorkbenchStore(path)
    session = store.get_session("ses_000000000001")
    assert (
        session is not None
        and session["view_mode"] == "terminal"
        and session["turns_observed"] == 3
    )
    assert store.list_runs("ses_000000000001")[0]["transport"] == "pty"
    store.set_view_mode("ses_000000000001", "conversation")
    store.close()
    again = WorkbenchStore(path)
    assert again.get_session("ses_000000000001")["view_mode"] == "conversation"
    again.close()
