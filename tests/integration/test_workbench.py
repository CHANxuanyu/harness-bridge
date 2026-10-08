"""Workbench offline integration (T2-W): real PTY, subprocesses, git and SQLite, **stub** CLIs.

The stubs (tests/helpers/wb_stub.py) emulate only the native interfaces the App relies on —
interactive tty, Claude hooks via ``--settings``, Codex ``-c notify`` and OSC 9 — never a model.
"""

from __future__ import annotations

import base64
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.workbench.harness import CLAUDE, CODEX, WorkbenchConfig
from harness_bridge.workbench.pty_host import process_birth
from harness_bridge.workbench.service import Workbench

STUB = Path(__file__).resolve().parents[1] / "helpers" / "wb_stub.py"


def wait_for(predicate: Callable[[], Any], timeout: float = 15.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not reached in time")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


class WB:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.repo = base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / "README.md").write_text("demo\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init")
        self.binaries: dict[str, str] = {}
        for kind, name in ((CLAUDE, "claude"), (CODEX, "codex")):
            wrapper = base / f"stub-{name}"
            wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{STUB}" {name} "$@"\n')
            wrapper.chmod(0o755)
            self.binaries[kind] = str(wrapper)
        self.env = {**os.environ, "WB_STUB_HOME": str(base / "stub-home")}
        self.state = base / "state"
        self.instances: list[Workbench] = []

    def open(self, **env_extra: str) -> Workbench:
        wb = Workbench(
            self.state,
            config=WorkbenchConfig(binaries=self.binaries, discover=False),
            base_env={**self.env, **env_extra},
            stop_grace=1.0,
        )
        self.instances.append(wb)
        return wb

    @staticmethod
    def text(wb: Workbench, sid: str) -> str:
        return base64.b64decode(wb.output(sid)["data"]).decode("utf-8", "replace")

    @staticmethod
    def run(wb: Workbench, sid: str) -> dict[str, Any]:
        return wb.store.list_runs(sid)[-1]

    @staticmethod
    def view(wb: Workbench, sid: str) -> dict[str, Any]:
        for project in wb.snapshot()["projects"]:
            for session in project["sessions"]:
                if session["session_id"] == sid:
                    return dict(session)
        raise AssertionError(sid)

    def send(self, wb: Workbench, sid: str, line: str, expect: str) -> None:
        wb.write_input(sid, (line + "\r").encode())
        wait_for(lambda: expect in self.text(wb, sid))


@pytest.fixture
def wbx(tmp_path: Path) -> Iterator[WB]:
    fx = WB(tmp_path)
    yield fx
    for wb in fx.instances:
        wb.close(timeout=5)


def test_claude_session_lifecycle_binding_activity_changes_stop_resume(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    session = wb.create_session(project["project_id"], CLAUDE, title="登录修复")
    sid = session["session_id"]
    preassigned = session["native_session_id"]
    wait_for(lambda: "stub claude ready" in wbx.text(wb, sid))
    assert f"session={preassigned}" in wbx.text(wb, sid)
    wait_for(lambda: wb.store.get_session(sid)["native_binding"] == "confirmed")

    wbx.send(wb, sid, "hello", "assistant: hello")
    wbx.send(wb, sid, "edit feature.txt", "edit feature.txt")
    wait_for(lambda: (wbx.repo / "feature.txt").exists())
    wait_for(lambda: wb.store.get_session(sid)["turns_observed"] == 2)
    events = wait_for(
        lambda: (
            [e for e in wb.activity(sid) if e["payload"].get("event") == "PostToolUse"]
            and wb.activity(sid)
        )
    )
    names = [e["payload"].get("event") for e in events if e["kind"] == "activity"]
    assert names[:3] == ["SessionStart", "UserPromptSubmit", "Stop"]
    assert "PreToolUse" in names and "PostToolUse" in names
    changes = wb.changes(sid)
    assert changes["git"] and [(f["kind"], f["path"]) for f in changes["files"]] == [
        ("untracked", "feature.txt")
    ]
    assert "written by stub" in wb.diff(sid, "feature.txt")["diff"]

    view = wbx.view(wb, sid)
    assert view["status"] == "running" and view["attached"] and not view["can_resume"]
    assert wb.stop(sid) == {"stopping": True}
    wait_for(lambda: wbx.run(wb, sid)["status"] == "stopped")
    run = wbx.run(wb, sid)
    assert run["exit_confirmed"] == 1 and run["exit_signal"] == signal.SIGHUP
    view = wbx.view(wb, sid)
    assert view["can_resume"] and not view["active"]

    wb.start_run(sid, "resume")
    wait_for(lambda: "session=" + preassigned in wbx.text(wb, sid))
    run = wbx.run(wb, sid)
    assert run["kind"] == "resume" and run["seq"] == 2
    assert run["argv_json"].count(preassigned) == 1 and "--resume" in run["argv_json"]
    wbx.send(wb, sid, "exit", "exit")
    wait_for(lambda: wbx.run(wb, sid)["status"] == "exited")
    assert wbx.run(wb, sid)["exit_code"] == 0
    assert wb.store.get_session(sid)["native_session_id"] == preassigned


def test_session_phase_follows_native_signals(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    claude = wb.create_session(project["project_id"], CLAUDE)["session_id"]
    wait_for(lambda: wbx.view(wb, claude)["phase"] == "waiting")  # SessionStart hook
    wbx.send(wb, claude, "hello", "assistant: hello")
    wait_for(lambda: wbx.view(wb, claude)["phase"] == "waiting")  # Stop hook after the turn
    kinds = [e["payload"].get("event") for e in wb.activity(claude) if e["kind"] == "activity"]
    assert kinds[-1] == "Stop"
    wbx.send(wb, claude, "exit", "exit")
    wait_for(lambda: wbx.view(wb, claude)["phase"] is None)
    other = wbx.base / "other"
    other.mkdir()
    codex_project = wb.add_project(str(other))
    codex = wb.create_session(codex_project["project_id"], CODEX)["session_id"]
    wait_for(lambda: wbx.view(wb, codex)["phase"] == "running")  # output seen, no turn yet
    wbx.send(wb, codex, "hi", "codex: hi")
    wait_for(lambda: wbx.view(wb, codex)["phase"] == "waiting")  # notify after the turn
    wb.write_input(codex, b"again\r")
    assert wbx.view(wb, codex)["phase"] == "running"


def test_resize_reaches_native_process_through_controlling_tty(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    sid = wb.create_session(project["project_id"], CLAUDE)["session_id"]
    wait_for(lambda: "stub claude ready" in wbx.text(wb, sid))
    wb.resize(sid, 101, 33)
    wait_for(lambda: "[winch 101x33]" in wbx.text(wb, sid))
    wb.write_input(sid, b"size\r")
    wait_for(lambda: wbx.text(wb, sid).count("[winch 101x33]") >= 2)


def test_codex_thread_id_is_observed_only_after_a_turn(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    session = wb.create_session(project["project_id"], CODEX)
    sid = session["session_id"]
    assert session["native_session_id"] is None and session["native_binding"] == "pending"
    wait_for(lambda: "stub codex ready" in wbx.text(wb, sid))
    assert wb.store.get_session(sid)["native_session_id"] is None
    wbx.send(wb, sid, "hi", "codex: hi")
    observed = wait_for(lambda: wb.store.get_session(sid)["native_session_id"])
    assert wb.store.get_session(sid)["native_binding"] == "observed"
    wbx.send(wb, sid, "exit", "exit")
    wait_for(lambda: wbx.run(wb, sid)["status"] == "exited")
    assert wbx.view(wb, sid)["can_resume"]
    wb.start_run(sid, "resume")
    wbx.send(wb, sid, "again", "codex: again")
    assert wb.store.get_session(sid)["native_session_id"] == observed
    kinds = [e["kind"] for e in wb.activity(sid)]
    assert kinds.count("native_session_observed") == 1 and "native_session_changed" not in kinds


def test_single_writer_per_workdir(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    first = wb.create_session(project["project_id"], CLAUDE)["session_id"]
    wait_for(lambda: "stub claude ready" in wbx.text(wb, first))
    with pytest.raises(BridgeError) as err:
        wb.create_session(project["project_id"], CODEX)
    assert err.value.code == "STATE_CONFLICT"
    assert err.value.details["busy_session_id"] == first
    assert len(wb.store.list_sessions(project["project_id"])) == 1
    # A second App instance on the same state is refused too.
    other = wbx.open()
    idle = other.create_session(project["project_id"], CODEX, start=False)["session_id"]
    with pytest.raises(BridgeError) as err2:
        other.start_run(idle, "new")
    assert err2.value.code == "STATE_CONFLICT"
    assert not other.store.list_runs(idle)


def test_nested_or_cloud_environment_refuses_without_spawning(wbx: WB) -> None:
    wb = wbx.open(CLAUDECODE="1")
    project = wb.add_project(str(wbx.repo))
    with pytest.raises(BridgeError) as err:
        wb.create_session(project["project_id"], CLAUDE)
    assert err.value.code == "PREFLIGHT_FAILED" and "CLAUDECODE" in err.value.message
    assert wb.store.list_sessions() == []
    assert wb.snapshot()["environment"]["refusal"]


def test_missing_binary_is_reported_not_guessed(wbx: WB) -> None:
    wbx.binaries[CODEX] = str(wbx.base / "no-such-codex")
    wb = wbx.open()
    harness = wb.harnesses()[CODEX]
    assert not harness.available and "not an executable" in (harness.problem or "")
    project = wb.add_project(str(wbx.repo))
    with pytest.raises(BridgeError) as err:
        wb.create_session(project["project_id"], CODEX)
    assert err.value.code == "PREFLIGHT_FAILED"


def test_failure_reason_and_output_tail_are_kept(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    sid = wb.create_session(project["project_id"], CLAUDE)["session_id"]
    wait_for(lambda: "stub claude ready" in wbx.text(wb, sid))
    wb.write_input(sid, b"crash\r")
    wait_for(lambda: wbx.run(wb, sid)["status"] == "failed")
    run = wbx.run(wb, sid)
    assert run["exit_code"] == 3 and "退出码 3" in run["failure"]
    assert "stub claude ready" in run["output_tail"]
    # No turn was observed: the slot can start a fresh native session, but not "resume".
    view = wbx.view(wb, sid)
    assert view["can_start_fresh"] and not view["can_resume"]
    with pytest.raises(BridgeError):
        wb.start_run(sid, "resume")
    old = wb.store.get_session(sid)["native_session_id"]
    wb.start_run(sid, "new")
    wait_for(lambda: wb.store.get_session(sid)["native_binding"] == "confirmed")
    assert wb.store.get_session(sid)["native_session_id"] != old


def test_clear_inside_tui_rebinds_to_latest_native_session(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    sid = wb.create_session(project["project_id"], CLAUDE)["session_id"]
    wait_for(lambda: "stub claude ready" in wbx.text(wb, sid))
    first = wb.store.get_session(sid)["native_session_id"]
    wbx.send(wb, sid, "/clear", "cleared session=")
    wait_for(lambda: wb.store.get_session(sid)["native_session_id"] != first)
    changed = [e for e in wb.activity(sid) if e["kind"] == "native_session_changed"]
    assert changed and changed[0]["payload"]["from"] == first


def test_permission_request_is_visible_and_answered_in_terminal(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    sid = wb.create_session(project["project_id"], CLAUDE)["session_id"]
    wait_for(lambda: "stub claude ready" in wbx.text(wb, sid))
    wb.write_input(sid, b"perm\r")
    attention = wait_for(lambda: wbx.view(wb, sid)["attention"])
    assert attention["kind"] == "permission" and "rm -rf build" in attention["message"]
    wbx.send(wb, sid, "y", "permission answer=y")
    assert wbx.view(wb, sid)["attention"] is None


def test_codex_osc9_approval_becomes_attention(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    sid = wb.create_session(project["project_id"], CODEX)["session_id"]
    wait_for(lambda: "stub codex ready" in wbx.text(wb, sid))
    wb.write_input(sid, b"perm\r")
    attention = wait_for(lambda: wbx.view(wb, sid)["attention"])
    assert attention["message"] == "Approval requested: rm -rf build"
    wbx.send(wb, sid, "n", "approval answer=n")
    wait_for(lambda: wbx.view(wb, sid)["attention"] is None)


def test_handoff_creates_new_session_in_same_project_and_keeps_source(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    src = wb.create_session(project["project_id"], CLAUDE, title="A")["session_id"]
    wait_for(lambda: "stub claude ready" in wbx.text(wb, src))
    wb.write_input(src, b"edit api.py\r")
    wait_for(lambda: any(e["payload"].get("event") == "Stop" for e in wb.activity(src)))
    with pytest.raises(BridgeError) as err:
        wb.create_handoff(src, CODEX, "note", send_as_prompt=False)
    assert err.value.code == "STATE_CONFLICT"
    wb.stop(src)
    wait_for(lambda: wbx.run(wb, src)["status"] == "stopped")

    draft = wb.handoff_draft(src, CODEX, progress="API 写好了，测试未跑")
    assert "API 写好了" in draft["note"] and "untracked: api.py" in draft["note"]
    result = wb.create_handoff(src, CODEX, draft["note"], send_as_prompt=True)
    new = result["session"]
    assert new["harness"] == CODEX and new["project_id"] == project["project_id"]
    assert new["handoff_from"] == src and new["native_session_id"] is None
    dst = new["session_id"]
    wait_for(lambda: wb.store.get_session(dst)["native_session_id"])
    prompts = [e["payload"].get("prompt") or "" for e in wb.activity(dst)]
    assert any(p.startswith("# 会话交接说明") for p in prompts)
    note_path = Path(result["handoff"]["note_path"])
    assert note_path.is_relative_to(wbx.state) and note_path.read_text().startswith("# 会话交接")
    assert sorted(p.name for p in wbx.repo.iterdir() if p.name != ".git") == [
        "README.md",
        "api.py",
    ]
    # Source keeps its own native identity and remains resumable once the writer slot is free.
    assert wb.store.get_session(src)["native_session_id"] is not None
    with pytest.raises(BridgeError):
        wb.start_run(src, "resume")
    wbx.send(wb, dst, "exit", "exit")
    wait_for(lambda: wbx.run(wb, dst)["status"] == "exited")
    wb.start_run(src, "resume")
    wait_for(lambda: wbx.run(wb, src)["status"] == "running")
    links = wb.snapshot()["projects"][0]["handoffs"]
    assert [(h["from_session_id"], h["to_session_id"]) for h in links] == [(src, dst)]


def test_restart_marks_dead_runs_interrupted_and_keeps_live_orphans(wbx: WB) -> None:
    wb = wbx.open()
    project = wb.add_project(str(wbx.repo))
    sid = wb.create_session(project["project_id"], CLAUDE)["session_id"]
    wait_for(lambda: "stub claude ready" in wbx.text(wb, sid))
    wbx.send(wb, sid, "hello", "assistant: hello")
    run = wbx.run(wb, sid)
    # Simulate an App crash: the PTY owner disappears without recording an exit.
    wb._on_exit = lambda live, info: None  # type: ignore[method-assign]
    wb._on_tick = lambda live: None  # type: ignore[method-assign]
    wb._on_output = lambda live, data: None  # type: ignore[method-assign]
    wb._live.clear()
    os.killpg(run["pgid"], signal.SIGKILL)
    wait_for(lambda: process_birth(run["pid"]) is None)
    wb.store.close()

    reopened = wbx.open()
    run = wbx.run(reopened, sid)
    assert run["status"] == "interrupted" and run["exit_confirmed"] == 1
    assert "hello" in run["output_tail"]
    view = wbx.view(reopened, sid)
    assert view["can_resume"] and "assistant: hello" in wbx.text(reopened, sid)
    reopened.start_run(sid, "resume")
    wait_for(lambda: wbx.run(reopened, sid)["status"] == "running")
    reopened.stop(sid)
    wait_for(lambda: wbx.run(reopened, sid)["status"] == "stopped")

    # A still-running process recorded by an earlier instance keeps the writer slot.
    orphan = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        other = reopened.create_session(project["project_id"], CODEX, start=False)
        oid = other["session_id"]
        reopened.store.begin_run(
            run_id="run_orphan00001",
            session_id=oid,
            kind="new",
            workdir=other["workdir"],
            argv=[],
            stripped_env=[],
        )
        birth = process_birth(orphan.pid)
        reopened.store.mark_running("run_orphan00001", pid=orphan.pid, pgid=orphan.pid, birth=birth)
        third = wbx.open()
        assert wbx.run(third, oid)["status"] == "running"
        assert "之前的 App" in wbx.run(third, oid)["failure"]
        assert wbx.view(third, oid)["active"] and not wbx.view(third, oid)["attached"]
        with pytest.raises(BridgeError):
            third.start_run(sid, "resume")
        assert third.stop(oid) == {"stopping": False, "confirmed": True}
        assert orphan.wait(timeout=5) is not None
        assert wbx.run(third, oid)["status"] == "stopped"
    finally:
        if orphan.poll() is None:
            orphan.kill()
            orphan.wait()


def test_project_and_diff_path_validation(wbx: WB) -> None:
    wb = wbx.open()
    with pytest.raises(BridgeError):
        wb.add_project("relative/path")
    with pytest.raises(BridgeError):
        wb.add_project(str(wbx.base / "missing"))
    sub = wbx.repo / "src"
    sub.mkdir()
    with pytest.raises(BridgeError) as err:
        wb.add_project(str(sub))
    assert "仓库顶层" in err.value.message
    project = wb.add_project(str(wbx.repo))
    again = wb.add_project(str(wbx.repo) + "/")
    assert again["project_id"] == project["project_id"] and not again["created"]
    sid = wb.create_session(project["project_id"], CLAUDE, start=False)["session_id"]
    for bad in ("/etc/passwd", "../outside.txt", "src/../../x"):
        with pytest.raises(BridgeError):
            wb.diff(sid, bad)
    plain = wbx.base / "plain"
    plain.mkdir()
    other = wb.add_project(str(plain))
    psid = wb.create_session(other["project_id"], CODEX, start=False)["session_id"]
    assert wb.changes(psid) == {"git": False, "error": None, "files": []}
