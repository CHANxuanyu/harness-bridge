"""T2-W: histories created outside RepoBridge, in isolated synthetic native stores.

Not live acceptance. No real account, native CLI, model endpoint or official app is opened.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.workbench.harness import CLAUDE, CODEX
from harness_bridge.workbench.native_history import Pages
from harness_bridge.workbench.server import WorkbenchServer
from tests.integration.test_workbench import WB, wait_for
from tests.integration.test_workbench_conversation import idle
from tests.integration.test_workbench_server import Client, loopback  # noqa: F401


@pytest.fixture
def fx(tmp_path: Path) -> Any:
    f = WB(tmp_path)
    f.env.update(HOME=str(tmp_path / "private-home"), CODEX_HOME=str(tmp_path / "codex-home"))
    yield f
    for wb in f.instances:
        wb.close(timeout=5)


def seed(
    fx: WB, harness: str, *, cwd: Path | None = None, title: str = "Outside", n: int = 3
) -> tuple[str, Path]:
    """Write native-shaped fixture first, never call create_session to make this history."""
    cwd = cwd or fx.repo
    sid = str(uuid.uuid4())
    home = Path(fx.env["WB_STUB_HOME"])
    (home / ("claude" if harness == CLAUDE else "codex")).mkdir(parents=True, exist_ok=True)
    (home / ("claude" if harness == CLAUDE else "codex") / sid).write_text("external\n")
    if harness == CLAUDE:
        p = (
            Path(fx.env["CLAUDE_CONFIG_DIR"])
            / "projects"
            / re.sub(r"[^a-zA-Z0-9]", "-", str(cwd))
            / f"{sid}.jsonl"
        )
        p.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "sessionId": sid,
                "cwd": str(cwd),
                "customTitle": title,
                "type": "user",
                "uuid": f"external-{i}",
                "timestamp": "2026-10-09T00:00:00Z",
                "message": {"role": "user", "content": f"outside {i}"},
            }
            for i in range(n)
        ]
        if not n:
            rows = [{"sessionId": sid, "cwd": str(cwd), "type": "system", "customTitle": title}]
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    else:
        p = home / "codex" / f"{sid}.turns.json"
        p.write_text(
            json.dumps(
                [
                    {
                        "id": f"outside-{i}",
                        "status": "completed",
                        "items": [
                            {
                                "id": f"u-{i}",
                                "type": "userMessage",
                                "content": [{"type": "text", "text": f"outside {i}"}],
                            }
                        ],
                    }
                    for i in range(n)
                ]
            )
        )
        index = home / "external-index.json"
        rows = json.loads(index.read_text()) if index.exists() else []
        rows.append(
            {
                "id": sid,
                "cwd": str(cwd),
                "source": "cli",
                "name": title,
                "updatedAt": 1791504000,
                "ephemeral": False,
            }
        )
        index.write_text(json.dumps(rows))
    return sid, p


def candidate(wb: Any, project: str, harness: str, native: str) -> dict[str, Any]:
    rows = wb.native_history.discover(project, harness)["items"]
    return next(c for c in rows if c["native_session_id"] == native)


def linked(wb: Any, cid: str) -> str:
    return str(wb.link_session(cid)["session"]["session"]["session_id"])


@pytest.mark.parametrize("harness", [CLAUDE, CODEX])
def test_external_discover_preview_link_resume_same_id_and_no_replay(fx: WB, harness: str) -> None:
    native, path = seed(fx, harness)
    before = path.read_bytes()
    # An unrelated project must not be offered, and its transcript must not be read for preview.
    unrelated, _ = seed(fx, harness, cwd=fx.base / "unrelated")
    wb = fx.open()
    project = wb.add_project(str(fx.repo))["project_id"]
    page = wb.native_history.discover(project, harness)
    assert [c["native_session_id"] for c in page["items"]] == [native]
    assert unrelated not in json.dumps(page)
    assert page["completeness"]["state"] == "partial"
    c = page["items"][0]
    preview = wb.native_history.preview(c["candidate_id"], limit=2)
    assert preview["page"]["state"] == "ready" and preview["page"]["has_more"]
    sid = linked(wb, c["candidate_id"])
    assert wb.store.list_runs(sid) == [] and path.read_bytes() == before
    assert wb.store.get_session(sid)["turns_observed"] == 0  # no invented model turns
    with pytest.raises(BridgeError):
        wb.start_run(sid, "new", confirm_external=True)
    with pytest.raises(BridgeError):
        wb.start_run(sid, "resume")
    wb.start_run(sid, "resume", confirm_external=True)
    wait_for(lambda: idle(wb, sid))
    run = WB.run(wb, sid)
    assert run["kind"] == "resume" and wb.store.get_session(sid)["native_session_id"] == native
    assert wb.store.get_session(sid)["turns_observed"] == 0
    assert path.read_bytes() == before
    if harness == CLAUDE:
        assert "--resume" in json.loads(run["argv_json"])
    else:
        calls = [
            json.loads(line)
            for line in (Path(fx.env["WB_STUB_HOME"]) / "codex-rpc.log").read_text().splitlines()
        ]
        assert not any(
            x["method"] in ("thread/start", "turn/start", "thread/name/set") for x in calls
        )
        assert any(
            x["method"] == "thread/resume" and x["params"]["threadId"] == native for x in calls
        )
    with pytest.raises(BridgeError):
        wb.unlink_session(sid)
    wb.stop(sid)
    wait_for(lambda: not WB.view(wb, sid)["active"])


@pytest.mark.parametrize("harness", [CLAUDE, CODEX])
def test_link_concurrency_restart_unlink_relink_and_environment_binding(
    fx: WB, harness: str
) -> None:
    native, path = seed(fx, harness)
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    cid = candidate(wb, pid, harness, native)["candidate_id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: wb.link_session(cid), range(4)))
    assert sum(r["created"] for r in replies) == 1
    sid = replies[0]["session"]["session"]["session_id"]
    assert {r["session"]["session"]["session_id"] for r in replies} == {sid}
    assert len(wb.store.list_sessions()) == 1
    wb.desktop_return(sid)
    wb.unlink_session(sid)
    assert wb.unlink_session(sid)["native_history_preserved"]
    assert path.exists()
    with pytest.raises(BridgeError):
        wb.start_run(sid, "resume", confirm_external=True)
    wb.close()
    fx.instances.remove(wb)
    wb = fx.open()
    cid = candidate(wb, pid, harness, native)["candidate_id"]
    reply = wb.link_session(cid)
    assert reply["relinked"] and not reply["created"]
    assert reply["session"]["session"]["session_id"] == sid
    with pytest.raises(BridgeError):
        wb.start_run(sid, "resume")  # Relinking requires a new external-writer confirmation.
    assert wb.conversation(sid, limit=100)["items"]
    env_key = "CLAUDE_CONFIG_DIR" if harness == CLAUDE else "CODEX_HOME"
    wb.base_env[env_key] = str(fx.base / "other-profile")
    with pytest.raises(BridgeError, match="environment"):
        wb.start_run(sid, "resume", confirm_external=True)


@pytest.mark.parametrize("harness", [CLAUDE, CODEX])
def test_paging_refresh_and_desktop_roundtrip_retains_identity(fx: WB, harness: str) -> None:
    native, path = seed(fx, harness, n=5)
    fx.install_app("Claude", "com.anthropic.claudefordesktop", "claude")
    fx.install_app("Codex", "com.openai.codex", "codex")
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    sid = linked(wb, candidate(wb, pid, harness, native)["candidate_id"])
    wb.desktop_return(sid)
    first = wb.conversation(sid, limit=2)
    ids = [i["id"] for i in first["items"]]
    cursor = first["page"]["next_before"]
    while cursor:
        page = wb.conversation(sid, limit=2, before=cursor)
        ids.extend(i["id"] for i in page["items"])
        cursor = page["page"]["next_before"]
    assert len(ids) == len(set(ids)) == len(wb.conversation(sid)["items"])
    opened = wb.open_in_desktop(sid)
    assert opened["status"] in ("acknowledged", "requested")
    with pytest.raises(BridgeError):
        wb.start_run(sid, "resume")
    # Simulated official desktop app appends to the same external native history, no App send.
    if harness == CLAUDE:
        row = {
            "type": "user",
            "uuid": "desktop-new",
            "sessionId": native,
            "cwd": str(fx.repo),
            "timestamp": "2026-10-09T00:01:00Z",
            "message": {"role": "user", "content": "from desktop"},
        }
        with path.open("a") as f:
            f.write(json.dumps(row) + "\n")
    else:
        rows = json.loads(path.read_text())
        rows.append(
            {
                "id": "desktop-new",
                "status": "completed",
                "items": [
                    {
                        "id": "desktop-new",
                        "type": "userMessage",
                        "content": [{"type": "text", "text": "from desktop"}],
                    }
                ],
            }
        )
        path.write_text(json.dumps(rows))
    wb.desktop_return(sid)
    delta = wb.conversation(sid, limit=100, since=first["page"]["next_since"], refresh=True)
    assert any(i.get("text") == "from desktop" for i in delta["items"])
    assert not any(i["id"] in ids for i in delta["items"])
    wb.start_run(sid, "resume", confirm_external=True)
    wait_for(lambda: idle(wb, sid))
    assert wb.store.get_session(sid)["native_session_id"] == native
    assert wb.store.get_session(sid)["turns_observed"] == 0
    assert wb.conversation(sid, limit=2)["page"]["state"] == "ready"


def test_since_includes_updated_items_and_resets_on_removed_history() -> None:
    pages = Pages()
    result = {
        "items": [{"id": "tool-1", "type": "tool", "output": "pending"}],
        "history": {"source": "codex", "error": None},
    }
    first = pages.history("one", result, 20, None, None)
    result["items"][0]["output"] = "done"
    delta = pages.history("one", result, 20, None, first["page"]["next_since"])
    assert delta["items"][0]["output"] == "done" and not delta["page"]["reset"]
    result["items"] = []
    assert pages.history("one", result, 20, None, delta["page"]["next_since"])["page"]["reset"]


@pytest.mark.parametrize("harness", [CLAUDE, CODEX])
def test_search_cursor_scope_and_missing_directory(fx: WB, harness: str) -> None:
    native, _ = seed(fx, harness, title="Target")
    seed(fx, harness, title="Another")
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    p = wb.native_history.discover(pid, harness, limit=1)
    assert p["next_cursor"]
    p2 = wb.native_history.discover(pid, harness, limit=1, cursor=p["next_cursor"])
    assert p["items"][0]["native_session_id"] != p2["items"][0]["native_session_id"]
    with pytest.raises(BridgeError):
        wb.native_history.discover(pid, harness, limit=1, q="different", cursor=p["next_cursor"])
    assert len(wb.native_history.discover(pid, harness, q="Target")["items"]) == 1
    cid = candidate(wb, pid, harness, native)["candidate_id"]
    fx.repo.rename(fx.base / "moved")
    assert candidate(wb, pid, harness, native)["directory_state"] == "missing"
    sid = linked(wb, cid)
    assert wb.conversation(sid, limit=5)["page"]["state"] == "ready"
    row = wb.snapshot()["projects"][0]["sessions"][0]
    assert not row["can_resume"] and row["native_link"]["resume_reason"] == "directory_missing"
    with pytest.raises(BridgeError):
        wb.start_run(sid, "resume", confirm_external=True)


def test_no_unscoped_fallback_or_empty_on_native_error(fx: WB) -> None:
    seed(fx, CODEX)
    wb = fx.open(WB_STUB_DISCOVERY_UNSUPPORTED="1")
    pid = wb.add_project(str(fx.repo))["project_id"]
    with pytest.raises(BridgeError, match="unsupported"):
        wb.native_history.discover(pid, CODEX)


def test_claude_invalid_metadata_symlink_and_empty_are_distinct(fx: WB) -> None:
    _native, path = seed(fx, CLAUDE, n=0)
    bad = path.with_name(str(uuid.uuid4()) + ".jsonl")
    bad.write_text("broken\n")
    sym = path.with_name(str(uuid.uuid4()) + ".jsonl")
    sym.symlink_to(path)
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    result = wb.native_history.discover(pid, CLAUDE)
    assert (
        len(result["items"]) == 1 and "invalid_native_metadata" in result["completeness"]["reasons"]
    )
    cid = result["items"][0]["candidate_id"]
    assert wb.native_history.preview(cid)["page"]["state"] == "empty"
    path.unlink()
    assert wb.native_history.preview(cid)["page"]["state"] == "unavailable"
    with pytest.raises(BridgeError):
        wb.link_session(cid)


def test_v3_migration_preserves_existing_rows(fx: WB) -> None:
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    s = wb.create_session(pid, CLAUDE, start=False)
    wb.close()
    fx.instances.remove(wb)
    with sqlite3.connect(fx.state / "workbench.sqlite3") as db:
        db.execute("DROP TABLE native_links")
        db.execute("UPDATE meta SET value='3' WHERE key='schema_revision'")
    wb = fx.open()
    assert wb.store.get_session(s["session_id"]) == s
    with sqlite3.connect(fx.state / "workbench.sqlite3") as db:
        assert db.execute("SELECT value FROM meta WHERE key='schema_revision'").fetchone()[0] == "4"
    assert wb.store.list_runs(s["session_id"]) == []


@pytest.mark.usefixtures("loopback")
def test_http_contract_and_cookie_protection(fx: WB) -> None:
    native, _ = seed(fx, CLAUDE)
    wb = fx.open()
    server = WorkbenchServer(wb)
    server.start()
    c = Client(server)
    try:
        assert (
            c.request("GET", "/api/history?project_id=none&harness=claude-code", cookie=False)[0]
            != 200
        )
        c.login()
        pid = c.api("POST", "/api/projects", {"path": str(fx.repo)})["project_id"]
        page = c.api("GET", f"/api/history?project_id={pid}&harness=claude-code&limit=1")
        row = page["items"][0]
        assert row["native_session_id"] == native
        assert c.api("GET", f"/api/history/{row['candidate_id']}?limit=1")["page"]["has_more"]
        result = c.api("POST", "/api/sessions/link", {"candidate_id": row["candidate_id"]})
        sid = result["session"]["session"]["session_id"]
        assert (
            result["created"]
            and not c.api("POST", "/api/sessions/link", {"candidate_id": row["candidate_id"]})[
                "created"
            ]
        )
        assert c.api("GET", f"/api/sessions/{sid}/conversation?limit=2")["page"]["state"] == "ready"
        assert (
            c.request("GET", f"/api/history?project_id={pid}&harness=claude-code&limit=0")[0] == 400
        )
        assert c.request("GET", f"/api/sessions/{sid}/conversation?before=unknown")[0] == 409
        c.api("POST", f"/api/sessions/{sid}/desktop/return", {})
        assert c.api("POST", f"/api/sessions/{sid}/unlink", {})["native_history_preserved"]
    finally:
        server.close()


def test_codex_external_writer_is_reported_and_never_forced(fx: WB) -> None:
    native, _ = seed(fx, CODEX)
    wb = fx.open(WB_STUB_CODEX_WRITER_BUSY="1")
    pid = wb.add_project(str(fx.repo))["project_id"]
    sid = linked(wb, candidate(wb, pid, CODEX, native)["candidate_id"])
    wb.start_run(sid, "resume", confirm_external=True)
    wait_for(lambda: WB.run(wb, sid)["status"] == "failed")
    assert "写入者" in WB.run(wb, sid)["failure"]
    assert wb.store.get_session(sid)["native_session_id"] == native
    assert wb.store.get_session(sid)["turns_observed"] == 0
    assert len(wb.store.list_runs(sid)) == 1


def test_codex_wrong_resume_identity_is_refused_without_turn_or_rebinding(fx: WB) -> None:
    native, path = seed(fx, CODEX)
    original = path.read_bytes()
    wb = fx.open(WB_STUB_CODEX_WRONG_RESUME_ID="1")
    pid = wb.add_project(str(fx.repo))["project_id"]
    sid = linked(wb, candidate(wb, pid, CODEX, native)["candidate_id"])
    wb.start_run(sid, "resume", confirm_external=True)
    wait_for(lambda: WB.run(wb, sid)["status"] == "failed")
    assert "different session ID" in WB.run(wb, sid)["failure"]
    assert wb.store.get_session(sid)["native_session_id"] == native
    assert wb.store.get_session(sid)["turns_observed"] == 0
    assert path.read_bytes() == original


def test_codex_native_pagination_keeps_latest_turns_in_chronological_order(fx: WB) -> None:
    native, _ = seed(fx, CODEX, n=105)
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    cid = candidate(wb, pid, CODEX, native)["candidate_id"]
    page = wb.native_history.preview(cid, limit=4)
    assert [i["text"] for i in page["items"] if i["type"] == "user"] == [
        "outside 103",
        "outside 104",
    ]
    assert page["page"]["has_more"] and page["page"]["completeness"]["state"] == "complete"


def test_same_uuid_in_different_storage_environments_does_not_alias(fx: WB) -> None:
    native, path = seed(fx, CLAUDE)
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    first = linked(wb, candidate(wb, pid, CLAUDE, native)["candidate_id"])
    new_root = fx.base / "other-claude"
    second_path = new_root / "projects" / path.parent.name / path.name
    second_path.parent.mkdir(parents=True)
    second_path.write_bytes(path.read_bytes())
    wb.base_env["CLAUDE_CONFIG_DIR"] = str(new_root)
    c = candidate(wb, pid, CLAUDE, native)
    assert c["already_linked"] is None
    second = linked(wb, c["candidate_id"])
    assert first != second
    assert len(wb.store.list_sessions()) == 2
    with pytest.raises(BridgeError, match="environment"):
        wb.conversation(first)


def test_legacy_app_row_is_reused_without_new_native_or_local_session(fx: WB) -> None:
    native, _ = seed(fx, CLAUDE)
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    old = wb.store.create_session(
        project_id=pid,
        harness=CLAUDE,
        title="Existing App row",
        workdir=str(fx.repo),
        native_session_id=native,
        native_binding="confirmed",
    )
    c = candidate(wb, pid, CLAUDE, native)
    assert c["already_linked"]["session_id"] == old["session_id"]
    r = wb.link_session(c["candidate_id"])
    assert not r["created"] and r["session"]["session"]["session_id"] == old["session_id"]
    assert not wb.store.list_runs(old["session_id"])


def test_partial_history_and_native_id_cwd_mutation_do_not_become_empty_success(fx: WB) -> None:
    native, path = seed(fx, CLAUDE)
    with path.open("a") as f:
        f.write('{"broken":\n')
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    c = candidate(wb, pid, CLAUDE, native)
    p = wb.native_history.preview(c["candidate_id"])
    assert p["items"] and p["page"]["state"] == "partial"
    assert "malformed_native_record" in p["page"]["completeness"]["reasons"]
    path.write_text(json.dumps({"cwd": str(fx.repo), "sessionId": str(uuid.uuid4())}) + "\n")
    assert wb.native_history.preview(c["candidate_id"])["page"]["state"] == "unavailable"
    with pytest.raises(BridgeError):
        wb.link_session(c["candidate_id"])
    assert not wb.store.list_sessions()


def test_cursor_expiry_and_parameter_errors_are_explicit(fx: WB) -> None:
    native, _ = seed(fx, CLAUDE)
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    cid = candidate(wb, pid, CLAUDE, native)["candidate_id"]
    first = wb.native_history.preview(cid, limit=1)
    before = first["page"]["next_before"]
    with pytest.raises(BridgeError):
        wb.native_history.preview(cid, before=before, since=first["page"]["next_since"])
    with pytest.raises(BridgeError):
        wb.native_history.preview(cid, limit="no")
    wb.native_history.pages.entries.clear()
    with pytest.raises(BridgeError) as e:
        wb.native_history.preview(cid, before=before)
    assert e.value.details["reason"] == "cursor_expired"
    refreshed = wb.native_history.preview(cid, since=first["page"]["next_since"])
    assert refreshed["page"]["reset"]


def test_discovery_does_not_open_unrelated_claude_transcripts(
    fx: WB, monkeypatch: pytest.MonkeyPatch
) -> None:
    native, _ = seed(fx, CLAUDE)
    _, unrelated = seed(fx, CLAUDE, cwd=fx.base / "private-unrelated")
    original = Path.open

    def guarded(path: Path, *args: Any, **kwargs: Any) -> Any:
        assert path != unrelated, "unrelated private transcript was read"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    wb = fx.open()
    pid = wb.add_project(str(fx.repo))["project_id"]
    c = candidate(wb, pid, CLAUDE, native)
    wb.native_history.preview(c["candidate_id"])
    linked(wb, c["candidate_id"])
