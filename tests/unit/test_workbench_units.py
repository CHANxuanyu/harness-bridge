"""Workbench units: launch argv/env, relay, stream parsers, store admission, handoff notes."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from harness_bridge.workbench import handoff
from harness_bridge.workbench.harness import (
    CLAUDE,
    CLAUDE_HOOK_EVENTS,
    CODEX,
    RELAY,
    WorkbenchConfig,
    build_launch,
    environment_refusal,
    native_argv,
    resolve_binary,
    session_env,
)
from harness_bridge.workbench.pty_host import JsonlTail, OscScanner, strip_ansi_tail
from harness_bridge.workbench.store import WorkbenchStore, WorkdirBusy

FORBIDDEN = {
    "-p",
    "--print",
    "--bare",
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "--dangerously-bypass-approvals-and-sandbox",
}
CONFIG = WorkbenchConfig(binaries={}, discover=False)


def _launch(tmp_path: Path, kind: str, mode: str, **kw: object) -> tuple[list[str], object]:
    spec = build_launch(
        kind,
        "/opt/native/bin/x",
        mode=mode,
        workdir=str(tmp_path),
        title=str(kw.get("title", "T")),
        native_session_id=kw.get("native"),  # type: ignore[arg-type]
        initial_prompt=kw.get("prompt"),  # type: ignore[arg-type]
        run_dir=tmp_path,
        config=CONFIG,
        base_env={"PATH": "/usr/bin", "ANTHROPIC_API_KEY": "secret", "TERM_PROGRAM": "iTerm.app"},
    )
    return native_argv(spec), spec


def test_claude_new_preassigns_id_and_records_hooks(tmp_path: Path) -> None:
    argv, spec = _launch(tmp_path, CLAUDE, "new", title="登录修复")
    assert argv[0] == "/opt/native/bin/x"
    sid = argv[argv.index("--session-id") + 1]
    assert spec.native_session_id == sid and spec.binding == "preassigned"  # type: ignore[attr-defined]
    assert argv[argv.index("-n") + 1] == "登录修复"
    assert not FORBIDDEN & set(argv)
    settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
    assert set(settings["hooks"]) == set(CLAUDE_HOOK_EVENTS)
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert str(RELAY) in command and "claude-hook" in command and "-I" in command
    assert settings["hooks"]["PreToolUse"][0]["matcher"] == "*"


def test_claude_resume_and_initial_prompt(tmp_path: Path) -> None:
    argv, _ = _launch(tmp_path, CLAUDE, "resume", native="abc", prompt="-handoff text")
    assert argv[1:3] == ["--resume", "abc"]
    assert argv[-2:] == ["--", "-handoff text"]
    with pytest.raises(ValueError):
        _launch(tmp_path, CLAUDE, "resume")


def test_codex_overrides_are_per_invocation_and_parse_as_toml(tmp_path: Path) -> None:
    argv, spec = _launch(tmp_path, CODEX, "new")
    assert argv[1:3] == ["-C", str(tmp_path)]
    assert spec.native_session_id is None and spec.binding == "pending"  # type: ignore[attr-defined]
    overrides = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    parsed = {}
    for item in overrides:
        key, _, value = item.partition("=")
        parsed[key] = tomllib.loads("v=" + value)["v"]
    assert parsed["notify"][-2:] == ["codex-notify", str(tmp_path / "events.jsonl")]
    assert parsed["tui.notifications"] is True
    assert parsed["tui.notification_method"] == "osc9"
    assert not FORBIDDEN & set(argv) and "--no-daemon" in argv
    resumed, _ = _launch(tmp_path, CODEX, "resume", native="thread-1")
    assert resumed[1:3] == ["resume", "thread-1"] and "--no-daemon" in resumed


def test_session_env_strips_billing_variables_and_terminal_identity() -> None:
    env, stripped = session_env(
        {
            "PATH": "/usr/bin",
            "ANTHROPIC_API_KEY": "a",
            "OPENAI_API_KEY": "b",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "TERM_PROGRAM": "vscode",
            "TMUX": "/tmp/x",
            "HOME": "/h",
        }
    )
    assert stripped == ["ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "OPENAI_API_KEY"]
    assert not {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "TMUX"} & set(env)
    assert env["TERM"] == "xterm-256color" and env["TERM_PROGRAM"] == "RepoBridge"
    assert env["HOME"] == "/h" and env["PATH"].startswith("/usr/bin")
    assert "a" not in env.values() and "b" not in env.values()


def test_environment_refusal_for_nested_and_cloud() -> None:
    assert environment_refusal({}) is None
    assert "CLAUDECODE" in (environment_refusal({"CLAUDECODE": "1"}) or "")
    assert "cloud" in (environment_refusal({"CLAUDE_CODE_REMOTE": "true"}) or "")


def test_resolve_binary_requires_executable_absolute_path(tmp_path: Path) -> None:
    script = tmp_path / "claude"
    script.write_text("#!/bin/sh\n")
    assert resolve_binary(CLAUDE, WorkbenchConfig(binaries={CLAUDE: str(script)}), {}) is None
    script.chmod(0o755)
    assert resolve_binary(CLAUDE, WorkbenchConfig(binaries={CLAUDE: str(script)}), {}) == str(
        script
    )
    assert resolve_binary(CLAUDE, WorkbenchConfig(binaries={CLAUDE: "claude"}), {}) is None
    assert resolve_binary(CODEX, CONFIG, {"PATH": str(tmp_path)}) is None


def _relay(args: list[str], stdin: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(RELAY), *args],
        input=stdin,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_relay_records_bounded_claude_hook_without_output(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "cwd": "/w",
        "tool_name": "Bash",
        "tool_input": {"command": "echo " + "x" * 5000},
        "tool_use_id": "u1",
    }
    proc = _relay(["claude-hook", str(events)], json.dumps(payload).encode())
    assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b""
    record = json.loads(events.read_text())
    assert record["event"] == "PreToolUse" and record["tool_name"] == "Bash"
    assert record["native_session_id"] == "s1" and len(record["summary"]) <= 300
    prompt = {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "修复登录"}
    assert _relay(["claude-hook", str(events)], json.dumps(prompt).encode()).stdout == b""
    assert json.loads(events.read_text().splitlines()[1])["prompt"] == "修复登录"


def test_relay_never_fails_on_bad_input(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    for args, data in (
        (["claude-hook", str(events)], b"not json"),
        (["codex-notify", str(events), "{bad"], b""),
        (["unknown", str(events)], b""),
        (["claude-hook", str(tmp_path / "missing" / "e.jsonl")], b"{}"),
    ):
        proc = _relay(args, data)
        assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b""
    assert not events.exists()


def test_relay_codex_notify(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    payload = {
        "type": "agent-turn-complete",
        "thread-id": "th-1",
        "turn-id": "t1",
        "cwd": "/w",
        "input-messages": ["first", "second"],
        "last-assistant-message": "done",
    }
    assert _relay(["codex-notify", str(events), json.dumps(payload)]).returncode == 0
    record = json.loads(events.read_text())
    assert record["native_session_id"] == "th-1" and record["prompt"] == "second"
    assert record["message"] == "done" and record["source"] == "codex-notify"


def test_osc_scanner_handles_split_sequences_and_progress() -> None:
    scan = OscScanner()
    assert scan.feed(b"hello \x1b]9;Appro") == []
    assert scan.feed(b"val requested: ls\x07 more") == ["Approval requested: ls"]
    assert scan.feed(b"\x1b]9;4;1;50\x07") == []
    assert scan.feed(b"\x1b]9;turn done\x1b\\") == ["turn done"]
    assert scan.feed(b"\x1b]") == []
    assert scan.feed(b"9;x\x07") == ["x"]


def test_jsonl_tail_waits_for_complete_lines(tmp_path: Path) -> None:
    path = tmp_path / "e.jsonl"
    tail = JsonlTail(path)
    assert tail.poll() == []
    path.write_bytes(b'{"a": 1}\n{"b"')
    assert tail.poll() == [{"a": 1}]
    with path.open("ab") as fh:
        fh.write(b": 2}\nnot-json\n[1]\n")
    assert tail.poll() == [{"b": 2}]


def test_strip_ansi_tail() -> None:
    raw = b"\x1b[31mred\x1b[0m line\r\r\n\x1b]0;title\x07next\rover\r\n\r\n"
    assert strip_ansi_tail(raw) == "red line\nover"


def test_store_single_writer_is_atomic_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "wb.sqlite3"
    a, b = WorkbenchStore(db), WorkbenchStore(db)
    project, _ = a.add_project("p", "/w")
    s1 = a.create_session(
        project_id=project["project_id"],
        harness=CLAUDE,
        title="one",
        workdir="/w",
        native_session_id="x",
        native_binding="preassigned",
    )
    s2 = b.create_session(
        project_id=project["project_id"],
        harness=CODEX,
        title="two",
        workdir="/w",
        native_session_id=None,
        native_binding="pending",
    )
    run = a.begin_run(
        run_id="run_1",
        session_id=s1["session_id"],
        kind="new",
        workdir="/w",
        argv=[],
        stripped_env=[],
    )
    with pytest.raises(WorkdirBusy) as busy:
        b.begin_run(
            run_id="run_2",
            session_id=s2["session_id"],
            kind="new",
            workdir="/w",
            argv=[],
            stripped_env=[],
        )
    assert busy.value.session_id == s1["session_id"]
    other = b.begin_run(
        run_id="run_3",
        session_id=s2["session_id"],
        kind="new",
        workdir="/w2",
        argv=[],
        stripped_env=[],
    )
    assert other["status"] == "starting"
    a.finish_run(run["run_id"], status="stopped", exit_confirmed=True)
    assert (
        b.begin_run(
            run_id="run_4",
            session_id=s2["session_id"],
            kind="new",
            workdir="/w",
            argv=[],
            stripped_env=[],
        )["seq"]
        == 2
    )
    a.close()
    b.close()


def test_handoff_note_is_explicit_about_new_context() -> None:
    note = handoff.draft(
        project={"name": "demo"},
        session={
            "harness": CLAUDE,
            "title": "A",
            "workdir": "/w",
            "native_session_id": "n-1",
        },
        target_harness=CODEX,
        last_run={"status": "stopped", "exit_code": None, "exit_signal": 1},
        events=[
            {"kind": "activity", "payload": {"source": "claude-hook", "prompt": "做登录"}},
            {
                "kind": "activity",
                "payload": {
                    "source": "claude-hook",
                    "event": "PreToolUse",
                    "tool_name": "Edit",
                    "summary": "src/a.py",
                },
            },
        ],
        git_status={
            "git": True,
            "branch": "main",
            "head": "abc",
            "files": [{"kind": "modified", "path": "src/a.py"}],
        },
        diffstat=" src/a.py | 2 +-",
        progress="接口已完成",
    )
    assert "没有上一会话的原生上下文" in note
    assert "Codex" in note and "Claude Code" in note
    assert "接口已完成" in note and "做登录" in note and "Edit: src/a.py" in note
    assert "modified: src/a.py" in note and "src/a.py | 2 +-" in note


def test_prefs_validate_and_persist(tmp_path: Path) -> None:
    from harness_bridge.errors import BridgeError
    from harness_bridge.workbench.prefs import DEFAULTS, Prefs

    path = tmp_path / "prefs.json"
    prefs = Prefs(path)
    assert prefs.get() == DEFAULTS
    prefs.update({"appearance": "light", "collapsed_projects": ["prj_0123456789ab"]})
    for bad in (
        {"appearance": "neon"},
        {"sidebar_width": 9999},
        {"collapsed_projects": ["../x"]},
        {"selected_session": "prj_0123456789ab"},
        {"inspector_open": "yes"},
        {"nope": 1},
    ):
        with pytest.raises(BridgeError):
            prefs.update(bad)
    again = Prefs(path)
    assert again.get()["appearance"] == "light"
    assert again.get()["collapsed_projects"] == ["prj_0123456789ab"]
    path.write_text('{"appearance": "neon", "terminal_font_size": 14}')
    assert Prefs(path).get()["appearance"] == "system", "invalid stored values fall back"
    assert Prefs(path).get()["terminal_font_size"] == 14


def test_quick_branch_reads_head_without_git(tmp_path: Path) -> None:
    from harness_bridge.workbench.changes import quick_branch

    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/feature/login\n")
    assert quick_branch(str(repo)) == "feature/login"
    (repo / ".git" / "HEAD").write_text("a" * 40 + "\n")
    assert quick_branch(str(repo)) == "detached aaaaaaa"
    wt = tmp_path / "wt"
    wt.mkdir()
    (tmp_path / "gitdir").mkdir()
    (tmp_path / "gitdir" / "HEAD").write_text("ref: refs/heads/wt-branch\n")
    (wt / ".git").write_text(f"gitdir: {tmp_path / 'gitdir'}\n")
    assert quick_branch(str(wt)) == "wt-branch"
    assert quick_branch(str(tmp_path / "plain")) is None


def test_single_instance_lock_per_state_dir(tmp_path: Path) -> None:
    from harness_bridge.workbench.app import _single_instance

    first = _single_instance(tmp_path)
    assert first is not None
    assert _single_instance(tmp_path) is None
    assert _single_instance(tmp_path / "other") is not None
    first.close()
    assert _single_instance(tmp_path) is not None
