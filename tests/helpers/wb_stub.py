"""Stub native CLIs for workbench tests: ``wb_stub.py claude|codex [native args...]``.

Emulates only what the workbench relies on, never a model:

* ``--version``;
* Claude: ``--session-id`` / ``--resume`` / ``-n`` / ``--settings`` hooks (SessionStart,
  UserPromptSubmit, Pre/PostToolUse, PermissionRequest, Stop, SessionEnd); resume of a session
  without a turn fails like the real CLI ("No conversation found");
* Codex: ``-C`` / ``resume <id>`` / ``-c notify=[...]`` (agent-turn-complete with thread-id) and
  OSC 9 approval notifications;
* a line-oriented "TUI" on the controlling tty. Commands: ``edit <file>`` writes a file,
  ``perm`` asks for approval, ``/clear`` (Claude) starts a new session id, ``exit``, ``crash``,
  ``size`` prints the tty size (proves SIGWINCH/TIOCSWINSZ reach the process), ``spam N``
  prints N numbered lines (long output). Anything else is echoed as an assistant reply.

``WB_STUB_HOME`` holds the fake native history so resume can succeed or fail realistically.

Structured protocols (conversation view), shaped after the official interfaces:

* ``claude -p --input-format stream-json --output-format stream-json ...``: SDK control protocol
  (``initialize``, ``can_use_tool`` permission requests, ``interrupt``), partial ``stream_event``
  deltas, replayed user messages, ``result``. Transcript lines go to
  ``$WB_STUB_HOME/claude-config/projects/<dir>/<id>.jsonl`` like Claude Code's own.
* ``claude --desktop --resume <id>``: prints the official acknowledgement (needs a tty).
* ``codex app-server``: JSON-RPC lines (``initialize``, ``thread/start|resume|name/set``,
  ``thread/turns/list``, ``turn/start|interrupt``; approval server requests; item notifications).

Structured commands: plain text (reply), ``edit <file>`` (asks to write), ``perm`` (asks to run a
command), ``slow`` (waits for an interrupt), ``authfail``, ``retry``, ``ask``, ``elicit``,
``fail``, ``crash``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path
from typing import Any

HOME = Path(os.environ.get("WB_STUB_HOME", "/nonexistent-wb-stub-home"))


def transcript_path(session_id: str) -> Path:
    slug = "".join(c if c.isalnum() else "-" for c in os.getcwd())
    return HOME / "claude-config" / "projects" / slug / f"{session_id}.jsonl"


def transcript_add(session_id: str, entry: dict[str, Any]) -> None:
    path = transcript_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "uuid": str(uuid.uuid4()),
        "sessionId": session_id,
        "timestamp": "2026-10-08T00:00:00Z",
        **entry,
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def codex_turns_path(thread: str) -> Path:
    return HOME / "codex" / f"{thread}.turns.json"


def codex_add_turn(thread: str, turn: dict[str, Any]) -> None:
    path = codex_turns_path(thread)
    path.parent.mkdir(parents=True, exist_ok=True)
    turns = json.loads(path.read_text()) if path.exists() else []
    turns.append(turn)
    path.write_text(json.dumps(turns))
    (HOME / "codex" / thread).write_text("rollout\n")


def out(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def on_winch(_sig: int, _frame: Any) -> None:
    size = shutil.get_terminal_size((0, 0))
    out(f"\r\n[winch {size.columns}x{size.lines}]\r\n")


class Claude:
    def __init__(self, args: list[str]) -> None:
        self.hooks: dict[str, str] = {}
        self.session = None
        self.resume = None
        self.prompt = None
        i = 0
        while i < len(args):
            a = args[i]
            if a == "--session-id":
                self.session = args[i + 1]
                i += 2
            elif a == "--resume":
                self.resume = args[i + 1]
                i += 2
            elif a in ("-n", "--name"):
                i += 2
            elif a == "--settings":
                settings = json.loads(Path(args[i + 1]).read_text())
                for event, entries in settings.get("hooks", {}).items():
                    self.hooks[event] = entries[0]["hooks"][0]["command"]
                i += 2
            elif a == "--":
                self.prompt = " ".join(args[i + 1 :])
                break
            else:
                i += 1

    def hook(self, event: str, **fields: Any) -> None:
        command = self.hooks.get(event)
        if not command:
            return
        payload = {
            "hook_event_name": event,
            "session_id": self.session,
            "cwd": os.getcwd(),
            "transcript_path": str(HOME / "claude" / f"{self.session}.jsonl"),
            **fields,
        }
        subprocess.run(["/bin/sh", "-c", command], input=json.dumps(payload).encode(), check=False)

    def history(self) -> Path:
        return HOME / "claude" / str(self.session)

    def run(self) -> int:
        if self.resume:
            self.session = self.resume
            if not self.history().exists():
                out(f"No conversation found with session ID: {self.resume}\r\n")
                return 1
            self.hook("SessionStart", source="resume")
        else:
            self.session = self.session or str(uuid.uuid4())
            self.hook("SessionStart", source="startup")
        out(f"stub claude ready session={self.session}\r\n")
        if self.prompt:
            self.turn(self.prompt)
        return loop(self)

    def turn(self, line: str) -> int | None:
        if line == "exit":
            self.hook("SessionEnd", reason="prompt_input_exit")
            return 0
        if line == "crash":
            return 3
        if line == "size":
            on_winch(0, None)
            return None
        if line == "/desktop":
            out(f"Opening session {self.session} in Claude Desktop\r\n")
            return 0
        if line == "/clear":
            self.session = str(uuid.uuid4())
            self.hook("SessionStart", source="clear")
            out(f"cleared session={self.session}\r\n")
            return None
        self.hook("UserPromptSubmit", prompt=line)
        self.history().parent.mkdir(parents=True, exist_ok=True)
        self.history().write_text("turn\n")
        transcript_add(
            str(self.session), {"type": "user", "message": {"role": "user", "content": line}}
        )
        transcript_add(
            str(self.session),
            {
                "type": "assistant",
                "message": {
                    "id": f"msg_{uuid.uuid4().hex[:8]}",
                    "role": "assistant",
                    "content": [{"type": "text", "text": f"assistant: {line}"}],
                },
            },
        )
        if line.startswith("edit "):
            name = line.split(" ", 1)[1]
            tool = {"file_path": name, "content": "x"}
            self.hook("PreToolUse", tool_name="Write", tool_input=tool, tool_use_id="t1")
            Path(name).write_text("written by stub\n")
            self.hook("PostToolUse", tool_name="Write", tool_input=tool, tool_use_id="t1")
        elif line == "perm":
            tool = {"command": "rm -rf build"}
            self.hook("PermissionRequest", tool_name="Bash", tool_input=tool, tool_use_id="t2")
            out("Allow Bash(rm -rf build)? [y/n] ")
            answer = sys.stdin.readline().strip()
            out(f"\r\npermission answer={answer}\r\n")
            if answer == "y":
                self.hook("PreToolUse", tool_name="Bash", tool_input=tool, tool_use_id="t2")
                self.hook("PostToolUse", tool_name="Bash", tool_input=tool, tool_use_id="t2")
        else:
            out(f"assistant: {line}\r\n")
        self.hook("Stop", stop_hook_active=False)
        return None


class Codex:
    def __init__(self, args: list[str]) -> None:
        self.notify: list[str] | None = None
        self.thread = None
        self.resume = None
        self.prompt = None
        self.turns = 0
        i = 0
        while i < len(args):
            a = args[i]
            if a == "resume":
                self.resume = args[i + 1]
                i += 2
            elif a == "-c":
                key, _, value = args[i + 1].partition("=")
                if key == "notify":
                    self.notify = tomllib.loads("v=" + value)["v"]
                i += 2
            elif a == "-C":
                i += 2
            elif a == "--":
                self.prompt = " ".join(args[i + 1 :])
                break
            else:
                i += 1

    def history(self) -> Path:
        return HOME / "codex" / str(self.thread)

    def run(self) -> int:
        if self.resume:
            self.thread = self.resume
            if not self.history().exists():
                out(f"Error: no rollout found for thread id {self.resume}\r\n")
                return 1
        else:
            self.thread = str(uuid.uuid4())
        out("stub codex ready\r\n")
        if self.prompt:
            self.turn(self.prompt)
        return loop(self)

    def turn(self, line: str) -> int | None:
        if line == "exit":
            return 0
        if line == "crash":
            return 3
        if line == "size":
            on_winch(0, None)
            return None
        if line == "perm":
            out("\x1b]9;Approval requested: rm -rf build\x07")
            out("Approve command rm -rf build? [y/n] ")
            answer = sys.stdin.readline().strip()
            out(f"\r\napproval answer={answer}\r\n")
        elif line.startswith("edit "):
            Path(line.split(" ", 1)[1]).write_text("written by stub codex\n")
            out("edited\r\n")
        else:
            out(f"codex: {line}\r\n")
        self.turns += 1
        self.history().parent.mkdir(parents=True, exist_ok=True)
        self.history().write_text("rollout\n")
        codex_add_turn(
            str(self.thread),
            {
                "id": f"turn-{self.turns}",
                "status": "completed",
                "items": [
                    {
                        "type": "userMessage",
                        "id": f"u{self.turns}",
                        "content": [{"type": "text", "text": line}],
                    },
                    {"type": "agentMessage", "id": f"a{self.turns}", "text": f"codex: {line}"},
                ],
            },
        )
        if self.notify:
            payload = {
                "type": "agent-turn-complete",
                "thread-id": self.thread,
                "turn-id": f"turn-{self.turns}",
                "cwd": os.getcwd(),
                "input-messages": [line],
                "last-assistant-message": f"done: {line}",
            }
            subprocess.run([*self.notify, json.dumps(payload)], check=False)
        return None


def spam(line: str) -> bool:
    if not line.startswith("spam "):
        return False
    count = int(line.split()[1])
    for i in range(1, count + 1):
        out(f"line {i:05d} " + "lorem ipsum dolor sit amet " * 3 + "\r\n")
    return True


def loop(cli: Claude | Codex) -> int:
    while True:
        out("> ")
        line = sys.stdin.readline()
        if not line:
            return 0
        if spam(line.strip()):
            continue
        result = cli.turn(line.strip())
        if result is not None:
            return result


# --- structured protocols ------------------------------------------------------------------------


def emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def read_json() -> dict[str, Any] | None:
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value


def claude_desktop(args: list[str]) -> int:
    log = HOME / "desktop-calls.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as fh:
        fh.write(json.dumps({"argv": args, "tty": os.isatty(0) and os.isatty(1)}) + "\n")
    if not (os.isatty(0) and os.isatty(1)):
        print("Error: --desktop needs an interactive terminal", file=sys.stderr)
        return 1
    sid = args[args.index("--resume") + 1] if "--resume" in args else ""
    if not (HOME / "claude" / sid).exists():
        print(f"No conversation found with session ID: {sid}")
        return 1
    print(f"Opening session {sid} in Claude Desktop")
    return 0


CLAUDE_MODELS: list[dict[str, Any]] = [
    {
        "value": "default",
        "resolvedModel": "claude-stub-opus",
        "displayName": "Default (recommended)",
        "description": "Stub Opus · most capable",
        "supportsEffort": True,
        "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"],
        "supportsAdaptiveThinking": True,
        "supportsAutoMode": True,
    },
    {
        "value": "stub-sonnet",
        "resolvedModel": "claude-stub-sonnet",
        "displayName": "Stub Sonnet",
        "description": "Stub Sonnet · fast",
        "supportsEffort": True,
        "supportedEffortLevels": ["low", "medium", "high"],
    },
    {
        "value": "stub-haiku",
        "resolvedModel": "claude-stub-haiku",
        "displayName": "Stub Haiku",
        "description": "Stub Haiku · no effort control",
    },
    {
        "value": "stub-locked",
        "resolvedModel": "claude-stub-locked",
        "displayName": "Stub Locked",
        "description": "Listed, but the account cannot use it",
    },
]
CLAUDE_MODES = ("default", "acceptEdits", "plan", "auto", "dontAsk")


def claude_resolve(value: str | None) -> str:
    for m in CLAUDE_MODELS:
        if m["value"] == (value or "default"):
            return str(m["resolvedModel"])
    return str(value)


class ClaudeStream:
    """stream-json emulation of ``claude -p`` with the SDK control protocol."""

    def __init__(self, args: list[str]) -> None:
        self.session = args[args.index("--session-id") + 1] if "--session-id" in args else None
        self.resume = args[args.index("--resume") + 1] if "--resume" in args else None
        self.persist = "--no-session-persistence" not in args
        self.initialized = False
        self.req = 0
        self.inited = False
        self.model = claude_resolve(args[args.index("--model") + 1] if "--model" in args else None)
        self.effort: str | None = args[args.index("--effort") + 1] if "--effort" in args else None
        self.mode = (
            args[args.index("--permission-mode") + 1] if "--permission-mode" in args else "default"
        )

    def log(self, entry: dict[str, Any]) -> None:
        HOME.mkdir(parents=True, exist_ok=True)
        with open(HOME / "claude-controls.log", "a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def run(self) -> int:
        if os.environ.get("WB_STUB_CLAUDE_INIT_FAIL"):
            print("stub: cannot start", file=sys.stderr)
            return 4
        if self.resume:
            self.session = self.resume
            if not (HOME / "claude" / self.resume).exists():
                print(f"No conversation found with session ID: {self.resume}", file=sys.stderr)
                return 1
        self.session = self.session or str(uuid.uuid4())
        while True:
            msg = read_json()
            if msg is None:
                return 0
            if msg.get("type") == "control_request":
                self.control(msg)
            elif msg.get("type") == "user":
                code = self.turn(msg)
                if code is not None:
                    return code

    def control(self, msg: dict[str, Any]) -> None:
        rid = msg.get("request_id")
        request = msg.get("request") or {}
        sub = request.get("subtype")
        self.log({"subtype": sub, **{k: v for k, v in request.items() if k != "subtype"}})
        response: dict[str, Any] = {"subtype": sub}
        error: str | None = None
        if sub == "initialize":
            response = {
                "commands": [
                    {
                        "name": "compact",
                        "description": "Compact the conversation",
                        "argumentHint": "",
                    },
                    {
                        "name": "review",
                        "description": "Review a pull request",
                        "argumentHint": "[pr]",
                    },
                ],
                "models": CLAUDE_MODELS,
                "output_style": "default",
                "available_output_styles": ["default"],
            }
        elif sub == "set_model":
            model = request.get("model") or "default"
            if model == "stub-locked":
                error = "Model stub-locked is not available for your organization"
            elif not any(m["value"] == model for m in CLAUDE_MODELS):
                error = f"Unknown model {model}"
            else:
                self.model = claude_resolve(model)
                entry = next(m for m in CLAUDE_MODELS if m["value"] == model)
                if self.effort and self.effort not in (entry.get("supportedEffortLevels") or []):
                    self.effort = None
            response = {}
        elif sub == "apply_flag_settings":
            settings = request.get("settings") or {}
            if "effortLevel" in settings:
                level = settings["effortLevel"]
                entry = next(m for m in CLAUDE_MODELS if m["resolvedModel"] == self.model)
                if level is not None and level not in (entry.get("supportedEffortLevels") or []):
                    error = f"apply_flag_settings: effort {level} is not available for {self.model}"
                else:
                    self.effort = level
            response = {}
        elif sub == "set_permission_mode":
            mode = request.get("mode")
            if mode not in CLAUDE_MODES:
                error = f"Cannot set permission mode {mode}"
            else:
                self.mode = str(mode)
                response = {"mode": self.mode}
        elif sub == "get_settings":
            response = {
                "effective": {"permissions": {"defaultMode": "default"}},
                "sources": [],
                "applied": {"model": self.model, "effort": self.effort},
            }
        if error is not None:
            emit(
                {
                    "type": "control_response",
                    "response": {"subtype": "error", "request_id": rid, "error": error},
                }
            )
            return
        emit(
            {
                "type": "control_response",
                "response": {"subtype": "success", "request_id": rid, "response": response},
            }
        )

    def ask(
        self, tool: str, tool_id: str, args: dict[str, Any], suggestions: Any = None
    ) -> dict[str, Any]:
        # The permission mode decides first, as in the real CLI: no prompt when it settles it.
        if self.mode == "acceptEdits" and tool in ("Edit", "Write", "MultiEdit"):
            return {"behavior": "allow", "updatedInput": args}
        if self.mode == "dontAsk" and tool != "AskUserQuestion":
            return {"behavior": "deny", "message": "dontAsk mode"}
        self.req += 1
        rid = f"cli_{self.req}"
        emit(
            {
                "type": "control_request",
                "request_id": rid,
                "request": {
                    "subtype": "can_use_tool",
                    "tool_name": tool,
                    "input": args,
                    "tool_use_id": tool_id,
                    "permission_suggestions": suggestions,
                },
            }
        )
        while True:
            msg = read_json()
            if msg is None:
                sys.exit(0)
            if msg.get("type") == "control_response":
                response = msg.get("response") or {}
                if response.get("request_id") == rid:
                    return dict(response.get("response") or {})
            elif msg.get("type") == "control_request":
                self.control(msg)

    def text(self, msg_id: str, index: int, text: str) -> None:
        emit(
            {
                "type": "stream_event",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "event": {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {"type": "text", "text": ""},
                },
            }
        )
        half = len(text) // 2
        for part in (text[:half], text[half:]):
            emit(
                {
                    "type": "stream_event",
                    "parent_tool_use_id": None,
                    "session_id": self.session,
                    "event": {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": part},
                    },
                }
            )
        emit(
            {
                "type": "stream_event",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "event": {"type": "content_block_stop", "index": index},
            }
        )
        emit(
            {
                "type": "assistant",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "message": {
                    "id": msg_id,
                    "role": "assistant",
                    "content": [{"type": "text", "text": text}],
                },
            }
        )

    def tool(self, msg_id: str, index: int, tool_id: str, name: str, args: dict[str, Any]) -> None:
        emit(
            {
                "type": "stream_event",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "event": {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}},
                },
            }
        )
        emit(
            {
                "type": "stream_event",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "event": {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)},
                },
            }
        )
        emit(
            {
                "type": "stream_event",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "event": {"type": "content_block_stop", "index": index},
            }
        )
        emit(
            {
                "type": "assistant",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "message": {
                    "id": msg_id,
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": args}],
                },
            }
        )

    def tool_result(self, tool_id: str, text: str, error: bool = False) -> None:
        emit(
            {
                "type": "user",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": text,
                            "is_error": error,
                        }
                    ],
                },
            }
        )

    def result(self, subtype: str = "success", error: str | None = None) -> None:
        emit(
            {
                "type": "result",
                "subtype": subtype,
                "is_error": error is not None,
                "result": error or "done",
                "session_id": self.session,
                "duration_ms": 12,
                "num_turns": 1,
                "permission_denials": [],
            }
        )

    def turn(self, msg: dict[str, Any]) -> int | None:
        content = (msg.get("message") or {}).get("content")
        line = (
            content
            if isinstance(content, str)
            else "".join(b.get("text", "") for b in content or [] if isinstance(b, dict))
        )
        images = [
            (b.get("source") or {}).get("media_type")
            for b in (content if isinstance(content, list) else [])
            if isinstance(b, dict) and b.get("type") == "image"
        ]
        self.log({"turn": line, "images": images, "model": self.model, "effort": self.effort})
        emit(
            {
                "type": "system",
                "subtype": "init",
                "session_id": self.session,
                "model": self.model,
                "permissionMode": self.mode,
                "apiKeySource": "none",
                "cwd": os.getcwd(),
            }
        )
        emit(
            {
                "type": "user",
                "session_id": self.session,
                "parent_tool_use_id": None,
                "uuid": msg.get("uuid") or str(uuid.uuid4()),
                "message": {"role": "user", "content": content},
            }
        )
        if line == "crash":
            return 3
        assert self.session is not None
        if self.persist:
            (HOME / "claude").mkdir(parents=True, exist_ok=True)
            (HOME / "claude" / self.session).write_text("turn\n")
            transcript_add(
                self.session, {"type": "user", "message": {"role": "user", "content": content}}
            )
        msg_id = f"msg_{uuid.uuid4().hex[:8]}"
        emit(
            {
                "type": "stream_event",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "event": {"type": "message_start", "message": {"id": msg_id, "model": self.model}},
            }
        )
        reply = f"assistant: {line}"
        mentions = re.findall(r'@"([^"]+)"', line)
        if images or mentions:
            seen = [Path(m).read_text().splitlines()[0] for m in mentions if Path(m).is_file()]
            reply = f"images={images} files={seen}"
        elif line == "whoami":
            reply = f"model={self.model} effort={self.effort} mode={self.mode}"
        if line == "authfail":
            self.result("success", "Invalid API key · Please run /login")
            return None
        if line == "retry":
            emit(
                {
                    "type": "system",
                    "subtype": "api_retry",
                    "attempt": 1,
                    "max_retries": 3,
                    "retry_delay_ms": 10,
                    "error_status": 529,
                    "error": "overloaded",
                    "session_id": self.session,
                }
            )
        if line.startswith("edit "):
            path = os.path.abspath(line.split(" ", 1)[1])
            self.text(msg_id, 0, "我来创建这个文件。")
            tid = f"toolu_w{uuid.uuid4().hex[:8]}"
            self.tool(msg_id, 1, tid, "Write", {"file_path": path, "content": "x"})
            answer = self.ask("Write", tid, {"file_path": path, "content": "x"})
            if answer.get("behavior") == "allow":
                Path(path).write_text("written by stub stream\n")
                self.tool_result(tid, f"File created successfully at: {path}")
                reply = "已创建文件。"
            else:
                self.tool_result(tid, f"denied: {answer.get('message')}", error=True)
                reply = "好的，没有写入。"
        elif line == "perm":
            args = {"command": "rm -rf build", "description": "Remove build output"}
            self.tool(msg_id, 0, "toolu_b1", "Bash", args)
            suggestions = [
                {
                    "type": "addRules",
                    "rules": [{"toolName": "Bash", "ruleContent": "rm -rf build"}],
                    "behavior": "allow",
                    "destination": "localSettings",
                }
            ]
            answer = self.ask("Bash", "toolu_b1", args, suggestions)
            granted = answer.get("behavior") == "allow"
            remembered = bool(answer.get("updatedPermissions"))
            self.tool_result("toolu_b1", "removed" if granted else "denied", error=not granted)
            reply = f"permission answer={answer.get('behavior')} remembered={remembered}"
        elif line == "ask":
            args = {
                "questions": [
                    {
                        "question": "Which color?",
                        "header": "Color",
                        "multiSelect": False,
                        "options": [
                            {"label": "red", "description": "warm"},
                            {"label": "blue", "description": "cool"},
                        ],
                    }
                ]
            }
            self.tool(msg_id, 0, "toolu_q1", "AskUserQuestion", args)
            answer = self.ask("AskUserQuestion", "toolu_q1", args)
            answers = (answer.get("updatedInput") or {}).get("answers")
            self.tool_result("toolu_q1", f"answers={json.dumps(answers)}")
            reply = f"you chose {json.dumps(answers)}"
        elif line == "demo" or "精确计算" in line:
            return self.demo(msg_id)
        elif line == "slow":
            self.text(msg_id, 0, "working slowly…")
            while True:
                msg = read_json()
                if msg is None:
                    return 0
                if msg.get("type") == "control_request":
                    self.control(msg)
                    if (msg.get("request") or {}).get("subtype") == "interrupt":
                        emit(
                            {
                                "type": "user",
                                "session_id": self.session,
                                "parent_tool_use_id": None,
                                "message": {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": "[Request interrupted by user]"}
                                    ],
                                },
                            }
                        )
                        self.result("error_during_execution", "interrupted")
                        return None
        self.text(msg_id, 5, reply)
        transcript_add(
            self.session,
            {
                "type": "assistant",
                "message": {
                    "id": msg_id,
                    "role": "assistant",
                    "model": self.model,
                    "content": [{"type": "text", "text": reply}],
                },
            },
        )
        self.result()
        return None

    def demo(self, msg_id: str) -> int | None:
        """Synthetic multi-step turn for screenshots: thinking, read, markdown, guarded edit."""
        path = os.path.abspath("src/ledger.py")
        emit(
            {
                "type": "stream_event",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "event": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "thinking", "thinking": ""},
                },
            }
        )
        emit(
            {
                "type": "stream_event",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "thinking_delta",
                        "thinking": "先读 ledger.py，看金额是怎么累加的。",
                    },
                },
            }
        )
        emit(
            {
                "type": "stream_event",
                "parent_tool_use_id": None,
                "session_id": self.session,
                "event": {"type": "content_block_stop", "index": 0},
            }
        )
        self.text(msg_id, 1, "我先看一下 `src/ledger.py` 里金额是怎么计算的。")
        self.tool(msg_id, 2, "toolu_r1", "Read", {"file_path": path})
        self.tool_result("toolu_r1", Path(path).read_text() if Path(path).exists() else "")
        body = (
            "问题在于用 **浮点数** 累加金额：\n\n"
            "1. `sum()` 对 `float` 会累积舍入误差；\n"
            "2. 对账时 `0.1 + 0.2` 这样的值无法和账单精确相等。\n\n"
            "建议改用 `Decimal`：\n\n"
            "```python\nfrom decimal import Decimal\n\n\ndef total(items):\n"
            '    return sum((Decimal(str(i.amount)) for i in items), Decimal("0"))\n```\n\n'
            "我来修改这个文件。"
        )
        self.text(msg_id, 3, body)
        new = (
            "from decimal import Decimal\n\n\ndef total(items):\n"
            '    return sum((Decimal(str(i.amount)) for i in items), Decimal("0"))\n'
        )
        args = {
            "file_path": path,
            "old_string": "return sum(i.amount for i in items)",
            "new_string": 'return sum((Decimal(str(i.amount)) for i in items), Decimal("0"))',
        }
        self.tool(msg_id, 4, "toolu_e1", "Edit", args)
        answer = self.ask(
            "Edit",
            "toolu_e1",
            args,
            [{"type": "setMode", "mode": "acceptEdits", "destination": "session"}],
        )
        if answer.get("behavior") == "allow":
            Path(path).write_text(new)
            self.tool_result("toolu_e1", f"The file {path} has been updated.")
            reply = (
                "已改为用 `Decimal` 累加：\n\n| 文件 | 变更 |\n|---|---|\n"
                "| `src/ledger.py` | 金额累加改用 `Decimal` |\n\n"
                "建议再补一个 `0.1 + 0.2` 的单元测试。"
            )
        else:
            self.tool_result("toolu_e1", "denied", error=True)
            reply = "好的，没有修改文件。"
        self.text(msg_id, 5, reply)
        transcript_add(
            str(self.session),
            {
                "type": "assistant",
                "message": {
                    "id": msg_id,
                    "role": "assistant",
                    "content": [{"type": "text", "text": reply}],
                },
            },
        )
        self.result()
        return None


CODEX_MODELS: list[dict[str, Any]] = [
    {
        "id": "stub-codex",
        "model": "stub-codex",
        "displayName": "Stub Codex",
        "description": "Stub workhorse",
        "hidden": False,
        "isDefault": True,
        "supportedReasoningEfforts": [
            {"reasoningEffort": "low", "description": "Fast responses"},
            {"reasoningEffort": "medium", "description": "Balanced"},
            {"reasoningEffort": "high", "description": "Deeper reasoning"},
        ],
        "defaultReasoningEffort": "medium",
        "inputModalities": ["text", "image"],
    },
    {
        "id": "stub-codex-mini",
        "model": "stub-codex-mini",
        "displayName": "Stub Codex Mini",
        "description": "Text only",
        "hidden": False,
        "isDefault": False,
        "supportedReasoningEfforts": [
            {"reasoningEffort": "low", "description": "Fast"},
            {"reasoningEffort": "medium", "description": "Balanced"},
        ],
        "defaultReasoningEffort": "low",
        "inputModalities": ["text"],
    },
    {
        "id": "stub-hidden",
        "model": "stub-hidden",
        "displayName": "Hidden",
        "description": "",
        "hidden": True,
        "isDefault": False,
        "supportedReasoningEfforts": [],
        "defaultReasoningEffort": "low",
    },
]


class CodexAppServer:
    """JSON-RPC emulation of ``codex app-server`` (stdio)."""

    def __init__(self) -> None:
        self.thread: str | None = None
        self.turns = 0
        self.next_req = 1000
        self.interrupt: str | None = None
        self.model = "stub-codex"
        self.effort: str | None = "medium"
        self.approval = "on-request"
        self.sandbox: dict[str, Any] = {"type": "workspaceWrite"}

    def log(self, entry: dict[str, Any]) -> None:
        HOME.mkdir(parents=True, exist_ok=True)
        with open(HOME / "codex-rpc.log", "a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def settings(self, params: dict[str, Any]) -> None:
        """thread/start and thread/resume overrides (the sandbox is not persisted, as in 0.162)."""
        if params.get("model"):
            self.model = str(params["model"])
        effort = (params.get("config") or {}).get("model_reasoning_effort")
        if effort:
            self.effort = str(effort)
        if params.get("approvalPolicy"):
            self.approval = str(params["approvalPolicy"])
        sandbox = params.get("sandbox")
        if sandbox:
            self.sandbox = {
                "type": {
                    "read-only": "readOnly",
                    "workspace-write": "workspaceWrite",
                    "danger-full-access": "dangerFullAccess",
                }[sandbox]
            }

    def settings_result(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "reasoningEffort": self.effort,
            "approvalPolicy": self.approval,
            "sandbox": dict(self.sandbox),
            "modelProvider": "openai",
        }

    def respond(self, rid: Any, result: dict[str, Any]) -> None:
        emit({"id": rid, "result": result})

    def error(self, rid: Any, message: str) -> None:
        emit({"id": rid, "error": {"code": -32600, "message": message}})

    def note(self, method: str, params: dict[str, Any]) -> None:
        emit({"method": method, "params": params})

    def thread_obj(self, tid: str) -> dict[str, Any]:
        return {
            "id": tid,
            "source": "vscode",
            "status": {"type": "idle"},
            "turns": [],
            "cwd": os.getcwd(),
            "cliVersion": "0.0.0-stub",
            "preview": "",
            "name": None,
            "model": self.model,
            "reasoningEffort": self.effort,
        }

    def run(self) -> int:
        while True:
            msg = read_json()
            if msg is None:
                return 0
            if "method" in msg and "id" in msg:
                code = self.request(msg)
                if code is not None:
                    return code

    def request(self, msg: dict[str, Any]) -> int | None:
        method, rid, params = msg["method"], msg["id"], msg.get("params") or {}
        self.log({"method": method, "params": params})
        if method == "model/list":
            self.respond(rid, {"data": CODEX_MODELS, "nextCursor": None})
            return None
        if method == "configRequirements/read":
            req = None
            if os.environ.get("WB_STUB_CODEX_READONLY_ONLY"):
                req = {"allowedSandboxModes": ["read-only"]}
            self.respond(rid, {"requirements": req})
            return None
        if method == "thread/read":
            self.respond(rid, {"thread": self.thread_obj(str(params.get("threadId")))})
            return None
        if method == "initialize":
            self.respond(
                rid,
                {
                    "userAgent": "stub",
                    "codexHome": str(HOME),
                    "platformFamily": "unix",
                    "platformOs": "macos",
                },
            )
        elif method == "thread/start":
            self.thread = str(uuid.uuid4())
            self.settings(params)
            self.respond(
                rid,
                {
                    "thread": self.thread_obj(self.thread),
                    "cwd": params.get("cwd"),
                    **self.settings_result(),
                },
            )
            self.note("thread/started", {"thread": self.thread_obj(self.thread)})
        elif method == "thread/resume":
            tid = params.get("threadId")
            if self.thread == tid:
                # Already loaded: report the live settings.
                self.respond(
                    rid, {"thread": self.thread_obj(self.thread), **self.settings_result()}
                )
            elif not (HOME / "codex" / str(tid)).exists():
                self.error(rid, f"no rollout found for thread id {tid}")
            else:
                self.thread = str(tid)
                turns = (
                    json.loads(codex_turns_path(self.thread).read_text())
                    if codex_turns_path(self.thread).exists()
                    else []
                )
                self.turns = len(turns)
                self.settings(params)
                self.respond(
                    rid, {"thread": self.thread_obj(self.thread), **self.settings_result()}
                )
        elif method == "thread/name/set":
            self.respond(rid, {})
            self.note(
                "thread/name/updated",
                {"threadId": params.get("threadId"), "threadName": params.get("name")},
            )
        elif method == "thread/turns/list":
            path = codex_turns_path(str(params.get("threadId")))
            if not path.exists():
                self.error(
                    rid,
                    f"thread {params.get('threadId')} is not materialized yet; "
                    "thread/turns/list is unavailable before first user message",
                )
            else:
                self.respond(rid, {"data": json.loads(path.read_text()), "nextCursor": None})
        elif method == "turn/start":
            return self.turn(rid, params)
        elif method == "turn/interrupt":
            self.interrupt = params.get("turnId")
            self.respond(rid, {})
        else:
            self.error(rid, f"stub does not implement {method}")
        return None

    def ask(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.next_req += 1
        rid = self.next_req
        emit({"id": rid, "method": method, "params": params})
        while True:
            msg = read_json()
            if msg is None:
                sys.exit(0)
            if msg.get("id") == rid and "method" not in msg:
                self.note("serverRequest/resolved", {"threadId": self.thread, "requestId": rid})
                return dict(msg.get("result") or {})
            if "method" in msg and "id" in msg:
                self.request(msg)

    def turn(self, rid: Any, params: dict[str, Any]) -> int | None:
        text = "".join(i.get("text", "") for i in params.get("input") or [] if isinstance(i, dict))
        images = [i.get("path") for i in params.get("input") or [] if i.get("type") == "localImage"]
        if params.get("model"):
            self.model = str(params["model"])
        if params.get("effort"):
            self.effort = str(params["effort"])
        if params.get("approvalPolicy"):
            self.approval = str(params["approvalPolicy"])
        if params.get("sandboxPolicy"):
            self.sandbox = dict(params["sandboxPolicy"])
        self.log({"turn": text, "images": images, "model": self.model, "effort": self.effort})
        self.turns += 1
        tid = f"turn-{self.turns}"
        assert self.thread is not None
        self.respond(rid, {"turn": {"id": tid, "items": [], "status": "inProgress"}})
        self.note(
            "turn/started",
            {"threadId": self.thread, "turn": {"id": tid, "items": [], "status": "inProgress"}},
        )
        user = {
            "type": "userMessage",
            "id": f"u{self.turns}",
            "clientId": params.get("clientUserMessageId"),
            "content": [{"type": "text", "text": text}],
        }
        self.note(
            "item/started", {"threadId": self.thread, "turnId": tid, "item": user, "startedAtMs": 0}
        )
        self.note(
            "item/completed",
            {"threadId": self.thread, "turnId": tid, "item": user, "completedAtMs": 0},
        )
        items: list[dict[str, Any]] = [user]
        if text == "crash":
            return 3
        status, error = "completed", None
        reply = f"codex: {text}"
        if images:
            reply = f"images={len(images)}"
        if text == "whoami":
            reply = (
                f"model={self.model} effort={self.effort} approval={self.approval} "
                f"sandbox={self.sandbox.get('type')}"
            )
        if text == "ask":
            answer = self.ask(
                "item/tool/requestUserInput",
                {
                    "threadId": self.thread,
                    "turnId": tid,
                    "itemId": f"q{self.turns}",
                    "isBlocking": True,
                    "questions": [
                        {
                            "id": "lang",
                            "header": "Language",
                            "question": "Which language?",
                            "options": [
                                {"label": "Python", "description": "scripts"},
                                {"label": "Go", "description": "services"},
                            ],
                            "isOther": True,
                        },
                        {
                            "id": "token",
                            "header": "Token",
                            "question": "Paste it",
                            "isSecret": True,
                        },
                    ],
                },
            )
            reply = f"answers={json.dumps(answer.get('answers'), sort_keys=True)}"
        if text.startswith("edit "):
            path = os.path.abspath(text.split(" ", 1)[1])
            change = {
                "type": "fileChange",
                "id": f"fc{self.turns}",
                "status": "inProgress",
                "changes": [
                    {"path": path, "kind": {"type": "add"}, "diff": "+written by stub codex\n"}
                ],
            }
            self.note(
                "item/started",
                {"threadId": self.thread, "turnId": tid, "item": change, "startedAtMs": 0},
            )
            answer = self.ask(
                "item/fileChange/requestApproval",
                {
                    "threadId": self.thread,
                    "turnId": tid,
                    "itemId": f"fc{self.turns}",
                    "startedAtMs": 0,
                    "reason": "create file",
                },
            )
            if answer.get("decision") in ("accept", "acceptForSession"):
                Path(path).write_text("written by stub codex\n")
                change["status"] = "completed"
            else:
                change["status"] = "declined"
            self.note(
                "item/completed",
                {"threadId": self.thread, "turnId": tid, "item": change, "completedAtMs": 0},
            )
            items.append(change)
            reply = f"edit {change['status']}"
        elif text == "perm":
            cmd = {
                "type": "commandExecution",
                "id": f"c{self.turns}",
                "command": "rm -rf build",
                "cwd": os.getcwd(),
                "status": "inProgress",
                "commandActions": [],
            }
            self.note(
                "item/started",
                {"threadId": self.thread, "turnId": tid, "item": cmd, "startedAtMs": 0},
            )
            answer = self.ask(
                "item/commandExecution/requestApproval",
                {
                    "threadId": self.thread,
                    "turnId": tid,
                    "itemId": f"c{self.turns}",
                    "startedAtMs": 0,
                    "command": "rm -rf build",
                    "cwd": os.getcwd(),
                },
            )
            if answer.get("decision") in ("accept", "acceptForSession"):
                self.note(
                    "item/commandExecution/outputDelta",
                    {
                        "threadId": self.thread,
                        "turnId": tid,
                        "itemId": f"c{self.turns}",
                        "delta": "removed\n",
                    },
                )
                cmd.update({"status": "completed", "exitCode": 0, "aggregatedOutput": "removed\n"})
            else:
                cmd["status"] = "declined"
            self.note(
                "item/completed",
                {"threadId": self.thread, "turnId": tid, "item": cmd, "completedAtMs": 0},
            )
            items.append(cmd)
            reply = f"approval answer={answer.get('decision')}"
        elif text == "elicit":
            answer = self.ask(
                "mcpServer/elicitation/request",
                {
                    "threadId": self.thread,
                    "turnId": tid,
                    "serverName": "stub",
                    "mode": "form",
                    "message": "Deploy settings",
                    "requestedSchema": {
                        "type": "object",
                        "properties": {
                            "env": {"type": "string", "enum": ["staging", "prod"], "title": "Env"},
                            "replicas": {"type": "integer", "title": "Replicas", "minimum": 1},
                            "dry": {"type": "boolean", "title": "Dry run"},
                        },
                        "required": ["env"],
                    },
                },
            )
            reply = (
                f"elicitation={answer.get('action')} "
                f"content={json.dumps(answer.get('content'), sort_keys=True)}"
            )
        elif text == "elicit-array":
            answer = self.ask(
                "mcpServer/elicitation/request",
                {
                    "threadId": self.thread,
                    "turnId": tid,
                    "serverName": "stub",
                    "mode": "form",
                    "message": "Pick many",
                    "requestedSchema": {
                        "type": "object",
                        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
                    },
                },
            )
            reply = f"elicitation={answer.get('action')}"
        elif text == "slow":
            self.note(
                "item/started",
                {
                    "threadId": self.thread,
                    "turnId": tid,
                    "item": {"type": "agentMessage", "id": "a-slow", "text": ""},
                    "startedAtMs": 0,
                },
            )
            self.note(
                "item/agentMessage/delta",
                {"threadId": self.thread, "turnId": tid, "itemId": "a-slow", "delta": "working…"},
            )
            while self.interrupt != tid:
                msg = read_json()
                if msg is None:
                    return 0
                if "method" in msg and "id" in msg:
                    self.request(msg)
            self.note(
                "turn/completed",
                {
                    "threadId": self.thread,
                    "turn": {"id": tid, "items": [], "status": "interrupted"},
                },
            )
            return None
        elif text == "fail":
            status, error = "failed", {"message": "stub failure"}
            self.note(
                "error",
                {"threadId": self.thread, "turnId": tid, "willRetry": False, "error": error},
            )
        agent = {"type": "agentMessage", "id": f"a{self.turns}", "text": ""}
        self.note(
            "item/started",
            {"threadId": self.thread, "turnId": tid, "item": agent, "startedAtMs": 0},
        )
        half = len(reply) // 2
        for part in (reply[:half], reply[half:]):
            self.note(
                "item/agentMessage/delta",
                {"threadId": self.thread, "turnId": tid, "itemId": agent["id"], "delta": part},
            )
        agent["text"] = reply
        self.note(
            "item/completed",
            {"threadId": self.thread, "turnId": tid, "item": agent, "completedAtMs": 0},
        )
        items.append(agent)
        codex_add_turn(self.thread, {"id": tid, "status": status, "error": error, "items": items})
        self.note(
            "turn/completed",
            {
                "threadId": self.thread,
                "turn": {"id": tid, "items": [], "status": status, "error": error},
            },
        )
        return None


def main(argv: list[str]) -> int:
    kind, args = argv[1], argv[2:]
    if "--version" in args:
        print("2.1.291 (Claude Code) [stub]" if kind == "claude" else "codex-cli 0.0.0-stub")
        return 0
    if kind == "claude" and "--desktop" in args:
        return claude_desktop(args)
    if kind == "claude" and "--input-format" in args:
        return ClaudeStream(args).run()
    if kind == "codex" and args[:1] == ["app-server"]:
        return CodexAppServer().run()
    signal.signal(signal.SIGWINCH, on_winch)
    if not os.isatty(0):
        print("stub: stdin is not a tty", file=sys.stderr)
        return 2
    return (Claude(args) if kind == "claude" else Codex(args)).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
