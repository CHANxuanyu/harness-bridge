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
  ``size`` prints the tty size (proves SIGWINCH/TIOCSWINSZ reach the process). Anything else
  is echoed as an assistant reply.

``WB_STUB_HOME`` holds the fake native history so resume can succeed or fail realistically.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path
from typing import Any

HOME = Path(os.environ.get("WB_STUB_HOME", "/nonexistent-wb-stub-home"))


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
        if line == "/clear":
            self.session = str(uuid.uuid4())
            self.hook("SessionStart", source="clear")
            out(f"cleared session={self.session}\r\n")
            return None
        self.hook("UserPromptSubmit", prompt=line)
        self.history().parent.mkdir(parents=True, exist_ok=True)
        self.history().write_text("turn\n")
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


def loop(cli: Claude | Codex) -> int:
    while True:
        out("> ")
        line = sys.stdin.readline()
        if not line:
            return 0
        result = cli.turn(line.strip())
        if result is not None:
            return result


def main(argv: list[str]) -> int:
    kind, args = argv[1], argv[2:]
    if "--version" in args:
        print("2.1.291 (Claude Code) [stub]" if kind == "claude" else "codex-cli 0.0.0-stub")
        return 0
    signal.signal(signal.SIGWINCH, on_winch)
    if not os.isatty(0):
        print("stub: stdin is not a tty", file=sys.stderr)
        return 2
    return (Claude(args) if kind == "claude" else Codex(args)).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
