"""Record-only side-channel relay for native CLIs (stdlib only; run as ``python -I -S -B``).

Usage::

    relay.py claude-hook  EVENTS_FILE   < hook JSON on stdin
    relay.py codex-notify EVENTS_FILE   NOTIFY_JSON

It appends one bounded JSON line to EVENTS_FILE and always exits 0 without writing to stdout or
stderr: Claude Code adds SessionStart/UserPromptSubmit hook stdout to the conversation context,
and a failing hook must never change what the native CLI decides.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

MAX_INPUT = 4 * 1024 * 1024
TEXT = 400


def _clip(value: Any, limit: int = TEXT) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tool_summary(name: Any, tool_input: Any) -> str | None:
    if not isinstance(tool_input, dict):
        return _clip(tool_input, 200)
    for key in ("command", "file_path", "notebook_path", "path", "pattern", "url", "query"):
        if isinstance(tool_input.get(key), str):
            return _clip(tool_input[key], 300)
    if name == "Task" and isinstance(tool_input.get("description"), str):
        return _clip(tool_input["description"], 200)
    return _clip(tool_input, 200)


def claude_record(payload: dict[str, Any]) -> dict[str, Any]:
    event = payload.get("hook_event_name")
    record: dict[str, Any] = {
        "source": "claude-hook",
        "event": event if isinstance(event, str) else None,
        "native_session_id": payload.get("session_id"),
        "cwd": payload.get("cwd"),
    }
    if event == "SessionStart":
        record["start_source"] = payload.get("source")
        record["transcript_path"] = payload.get("transcript_path")
    elif event == "UserPromptSubmit":
        record["prompt"] = _clip(payload.get("prompt"))
    elif event in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"):
        record["tool_name"] = payload.get("tool_name")
        record["tool_use_id"] = payload.get("tool_use_id")
        record["summary"] = _tool_summary(payload.get("tool_name"), payload.get("tool_input"))
        if event == "PostToolUseFailure":
            record["error"] = _clip(payload.get("error"), 300)
    elif event == "Notification":
        record["message"] = _clip(payload.get("message"))
        record["notification_type"] = payload.get("notification_type")
    elif event == "SessionEnd":
        record["reason"] = payload.get("reason")
    return record


def codex_record(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = payload.get("input-messages")
    last_input = inputs[-1] if isinstance(inputs, list) and inputs else None
    return {
        "source": "codex-notify",
        "event": payload.get("type"),
        "native_session_id": payload.get("thread-id"),
        "turn_id": payload.get("turn-id"),
        "cwd": payload.get("cwd"),
        "prompt": _clip(last_input),
        "message": _clip(payload.get("last-assistant-message")),
    }


def main(argv: list[str]) -> int:
    try:
        mode, path = argv[1], argv[2]
        if mode == "claude-hook":
            raw = sys.stdin.buffer.read(MAX_INPUT)
            record = claude_record(json.loads(raw.decode("utf-8", "replace")))
        elif mode == "codex-notify":
            record = codex_record(json.loads(argv[3]))
        else:
            return 0
        record["ts"] = time.time()
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:  # noqa: S110 - a side channel must never affect the native CLI
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
