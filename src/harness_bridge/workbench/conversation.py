"""Conversation view model, built only from the harnesses' own structured messages.

Live sources are Claude Code's stream-json protocol (``claude -p --input-format stream-json
--output-format stream-json``, the protocol of the official Agent SDK) and the Codex app-server
JSON-RPC protocol. History comes from the native stores through native interfaces: Codex
``thread/turns/list`` and the Claude Code session transcript (the JSONL file ``claude --resume``
itself reads). Terminal output is never parsed into chat.

Everything here is pure bookkeeping (no processes); ``structured.py`` feeds it.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TEXT_CAP = 2 << 20
OUTPUT_CAP = 200 << 10
INPUT_CAP = 20 << 10
HISTORY_FILE_CAP = 64 << 20

Item = dict[str, Any]
Emit = Callable[[dict[str, Any]], None]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clip(text: str, cap: int) -> tuple[str, bool]:
    if len(text) <= cap:
        return text, False
    return text[:cap], True


def pretty(value: Any, cap: int = INPUT_CAP) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            text = repr(value)
    clipped, cut = _clip(text, cap)
    return clipped + ("\n…" if cut else "")


class Conversation:
    """Ordered, thread-safe item list for one session plus the current turn state."""

    def __init__(self, emit: Emit | None = None) -> None:
        self._items: dict[str, Item] = {}
        self._lock = threading.Lock()
        self.emit: Emit = emit or (lambda _op: None)
        self.turn: dict[str, Any] | None = None
        self.history_source: str = "none"
        self.history_error: str | None = None

    # --- reads ---------------------------------------------------------------------------------

    def items(self) -> list[Item]:
        with self._lock:
            return copy.deepcopy(list(self._items.values()))

    def get(self, item_id: str) -> Item | None:
        with self._lock:
            item = self._items.get(item_id)
            return copy.deepcopy(item) if item is not None else None

    def pending_permissions(self) -> list[Item]:
        with self._lock:
            return [
                copy.deepcopy(i)
                for i in self._items.values()
                if i["type"] == "permission" and i.get("status") == "pending"
            ]

    def find(self, predicate: Callable[[Item], bool]) -> Item | None:
        with self._lock:
            for item in self._items.values():
                if predicate(item):
                    return copy.deepcopy(item)
        return None

    # --- writes --------------------------------------------------------------------------------

    def upsert(self, item: Item) -> Item:
        with self._lock:
            current = self._items.get(item["id"])
            if current is None:
                merged = {"time": now(), **item}
                self._items[item["id"]] = merged
            else:
                current.update(item)
                merged = current
            out = copy.deepcopy(merged)
        self.emit({"op": "upsert", "item": out})
        return out

    def append(self, item_id: str, field: str, delta: str, cap: int = TEXT_CAP) -> None:
        if not delta:
            return
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return
            text = item.get(field) or ""
            if item.get(f"{field}_truncated"):
                item[f"{field}_omitted"] = item.get(f"{field}_omitted", 0) + len(delta)
                return
            room = cap - len(text)
            if room <= 0 or len(delta) > room:
                item[field] = text + delta[: max(room, 0)]
                item[f"{field}_truncated"] = True
                item[f"{field}_omitted"] = len(delta) - max(room, 0)
                out: dict[str, Any] = {"op": "upsert", "item": copy.deepcopy(item)}
            else:
                item[field] = text + delta
                out = {"op": "delta", "id": item_id, "field": field, "delta": delta}
        self.emit(out)

    def replace_history(self, items: Iterable[Item], source: str, error: str | None) -> None:
        with self._lock:
            live = [i for i in self._items.values() if not i.get("history")]
            self._items = {}
            for item in items:
                self._items[item["id"]] = {**item, "history": True}
            for item in live:
                self._items.setdefault(item["id"], item)
            self.history_source = source
            self.history_error = error
        self.emit({"op": "reset"})

    def finish_open_items(self, status: str) -> None:
        """At a turn's end nothing can still be running; say so instead of spinning forever."""
        with self._lock:
            touched = []
            for item in self._items.values():
                if item["type"] in ("tool", "assistant", "reasoning") and item.get("status") in (
                    "running",
                    "waiting",
                ):
                    item["status"] = status if item["type"] == "tool" else "done"
                    touched.append(copy.deepcopy(item))
                if item["type"] in ("assistant", "reasoning") and item.get("streaming"):
                    item["streaming"] = False
                    touched.append(copy.deepcopy(item))
                if item["type"] == "permission" and item.get("status") == "pending":
                    item["status"] = "expired"
                    touched.append(copy.deepcopy(item))
        for item in touched:
            self.emit({"op": "upsert", "item": item})

    def set_turn(self, turn: dict[str, Any] | None) -> None:
        with self._lock:
            self.turn = copy.deepcopy(turn)
        self.emit({"op": "turn", "turn": copy.deepcopy(turn)})

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "items": copy.deepcopy(list(self._items.values())),
                "turn": copy.deepcopy(self.turn),
                "history": {"source": self.history_source, "error": self.history_error},
            }


# --- tool presentation ---------------------------------------------------------------------------

_FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def claude_tool_title(name: str, args: Mapping[str, Any]) -> str:
    def s(key: str) -> str:
        value = args.get(key)
        return value if isinstance(value, str) else ""

    if name == "Bash":
        title = s("command").strip().splitlines()[0] if s("command").strip() else ""
    elif name in ("Read", "Write", "Edit", "MultiEdit"):
        title = s("file_path")
    elif name == "NotebookEdit":
        title = s("notebook_path")
    elif name in ("Glob", "Grep"):
        title = s("pattern") + (f"  ({s('path')})" if s("path") else "")
    elif name == "WebFetch":
        title = s("url")
    elif name == "WebSearch":
        title = s("query")
    elif name in ("Task", "Agent"):
        title = s("description") or s("subagent_type")
    elif name == "TodoWrite":
        todos = args.get("todos")
        title = f"更新待办（{len(todos)} 项）" if isinstance(todos, list) else "更新待办"
    elif name == "AskUserQuestion":
        questions = args.get("questions")
        first = questions[0] if isinstance(questions, list) and questions else {}
        title = first.get("question", "") if isinstance(first, dict) else ""
    elif name == "ExitPlanMode":
        title = "提交计划，等待确认"
    else:
        title = next((v for v in args.values() if isinstance(v, str) and v.strip()), "")
    title = " ".join(title.split())
    return title[:600]


def claude_tool_files(name: str, args: Mapping[str, Any]) -> list[dict[str, Any]]:
    if name not in _FILE_TOOLS:
        return []
    path = args.get("file_path") or args.get("notebook_path")
    return [{"path": path, "kind": "write" if name == "Write" else "edit"}] if path else []


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif block.get("type") == "image":
                    parts.append("[图片]")
        return "\n".join(parts)
    return "" if content is None else pretty(content)


def _user_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif block.get("type") == "image":
                parts.append("[图片]")
        return "\n".join(parts)
    return ""


def _command_notice(text: str) -> str | None:
    """Claude Code wraps slash commands and their local output in tags inside user turns."""
    stripped = text.strip()
    if stripped.startswith("<command-name>"):
        name = stripped[len("<command-name>") :].split("</command-name>", 1)[0].strip()
        return f"执行了命令 {name}"
    if stripped.startswith(("<local-command-stdout>", "<local-command-caveat>")):
        return ""
    if stripped.startswith("[Request interrupted by user"):
        return "已中断"
    return None


# --- Claude Code stream-json ---------------------------------------------------------------------


class ClaudeTranslator:
    """Translate Claude Code stream-json output lines into conversation items.

    Returns permission requests that need a host answer; everything else only updates ``conv``.
    """

    def __init__(self, conv: Conversation) -> None:
        self.conv = conv
        self.info: dict[str, Any] = {}
        self._msg_id = ""
        self._blocks: dict[int, tuple[str, str]] = {}
        self._partial: dict[int, str] = {}
        self._streamed: dict[str, dict[str, list[str]]] = {}
        self._used: dict[str, dict[str, int]] = {}
        self._turn_seq = 0
        self.interrupt_requested = False
        self.tool_names: dict[str, str] = {}
        self.turn_started_at: float | None = None
        # Tools whose permission the user denied: their error result means "declined".
        self.denied: set[str] = set()

    # A turn starts when the host sends a user message.
    def begin_turn(self, client_id: str, text: str) -> str:
        self._turn_seq += 1
        turn_id = f"t{self._turn_seq}:{client_id}"
        self.interrupt_requested = False
        self.conv.upsert(
            {"id": f"user:{client_id}", "type": "user", "text": text, "status": "sending"}
        )
        self.conv.set_turn({"id": turn_id, "status": "running", "started_at": now()})
        return turn_id

    def feed(self, msg: Mapping[str, Any]) -> dict[str, Any] | None:
        kind = msg.get("type")
        if kind == "stream_event":
            if msg.get("parent_tool_use_id") is None:
                self._stream_event(msg.get("event") or {})
        elif kind == "assistant":
            self._assistant(msg)
        elif kind == "user":
            self._user(msg)
        elif kind == "result":
            self._result(msg)
        elif kind == "system":
            self._system(msg)
        elif kind == "control_request":
            return self._control_request(msg)
        elif kind == "control_cancel_request":
            rid = str(msg.get("request_id") or "")
            item = self.conv.get(f"perm:{rid}")
            if item and item.get("status") == "pending":
                self.conv.upsert({"id": item["id"], "status": "cancelled"})
        return None

    # --- message kinds --------------------------------------------------------------------------

    def _stream_event(self, event: Mapping[str, Any]) -> None:
        etype = event.get("type")
        if etype == "message_start":
            message = event.get("message") or {}
            self._msg_id = str(message.get("id") or f"m{len(self._streamed)}")
            self._blocks = {}
            self._partial = {}
        elif etype == "content_block_start":
            index = int(event.get("index") or 0)
            block = event.get("content_block") or {}
            btype = block.get("type")
            if btype == "text":
                item_id = f"a:{self._msg_id}:{index}"
                self._remember(item_id, "text")
                self.conv.upsert(
                    {
                        "id": item_id,
                        "type": "assistant",
                        "text": block.get("text") or "",
                        "streaming": True,
                    }
                )
                self._blocks[index] = ("text", item_id)
            elif btype == "thinking":
                item_id = f"r:{self._msg_id}:{index}"
                self._remember(item_id, "thinking")
                self.conv.upsert(
                    {
                        "id": item_id,
                        "type": "reasoning",
                        "text": block.get("thinking") or "",
                        "streaming": True,
                    }
                )
                self._blocks[index] = ("thinking", item_id)
            elif btype in ("tool_use", "server_tool_use", "mcp_tool_use"):
                tool_id = str(block.get("id") or f"tool:{self._msg_id}:{index}")
                name = str(block.get("name") or "工具")
                self.tool_names[tool_id] = name
                self.conv.upsert(
                    {
                        "id": tool_id,
                        "type": "tool",
                        "name": name,
                        "title": "",
                        "status": "running",
                    }
                )
                self._blocks[index] = ("tool", tool_id)
                self._partial[index] = ""
        elif etype == "content_block_delta":
            index = int(event.get("index") or 0)
            delta = event.get("delta") or {}
            kind_id = self._blocks.get(index)
            if kind_id is None:
                return
            dtype = delta.get("type")
            if dtype == "text_delta":
                self.conv.append(kind_id[1], "text", str(delta.get("text") or ""))
            elif dtype == "thinking_delta":
                self.conv.append(kind_id[1], "text", str(delta.get("thinking") or ""))
            elif dtype == "input_json_delta":
                self._partial[index] = self._partial.get(index, "") + str(
                    delta.get("partial_json") or ""
                )
        elif etype == "content_block_stop":
            index = int(event.get("index") or 0)
            kind_id = self._blocks.get(index)
            if kind_id is None:
                return
            if kind_id[0] == "tool":
                raw = self._partial.pop(index, "")
                try:
                    args = json.loads(raw) if raw else {}
                except ValueError:
                    args = {}
                if isinstance(args, dict) and args:
                    self._tool_input(kind_id[1], args)
            else:
                self.conv.upsert({"id": kind_id[1], "streaming": False})

    def _remember(self, item_id: str, kind: str) -> None:
        self._streamed.setdefault(self._msg_id, {}).setdefault(kind, []).append(item_id)

    def _next_streamed(self, msg_id: str, kind: str) -> str | None:
        ids = self._streamed.get(msg_id, {}).get(kind, [])
        used = self._used.setdefault(msg_id, {})
        n = used.get(kind, 0)
        if n < len(ids):
            used[kind] = n + 1
            return ids[n]
        return None

    def _tool_input(self, tool_id: str, args: Mapping[str, Any]) -> None:
        name = self.tool_names.get(tool_id, "工具")
        self.conv.upsert(
            {
                "id": tool_id,
                "title": claude_tool_title(name, args),
                "input": pretty(dict(args)),
                "files": claude_tool_files(name, args),
                "raw_input": dict(args) if name in ("AskUserQuestion", "ExitPlanMode") else None,
            }
        )

    def _assistant(self, msg: Mapping[str, Any]) -> None:
        parent = msg.get("parent_tool_use_id")
        message = msg.get("message") or {}
        content = message.get("content") or []
        if parent is not None:
            # Subagent work is shown as activity of the tool that started it.
            item = self.conv.get(str(parent))
            if item is not None:
                self.conv.upsert(
                    {"id": item["id"], "subagent_steps": item.get("subagent_steps", 0) + 1}
                )
            return
        msg_id = str(message.get("id") or "")
        if message.get("error") or msg.get("error"):
            pass
        for n, block in enumerate(content if isinstance(content, list) else []):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                item_id = self._next_streamed(msg_id, "text") or f"a:{msg_id}:x{n}"
                self.conv.upsert(
                    {
                        "id": item_id,
                        "type": "assistant",
                        "text": str(block.get("text") or ""),
                        "streaming": False,
                    }
                )
            elif btype == "thinking":
                item_id = self._next_streamed(msg_id, "thinking") or f"r:{msg_id}:x{n}"
                existing = self.conv.get(item_id)
                text = str(block.get("thinking") or "") or (existing or {}).get("text", "")
                self.conv.upsert(
                    {"id": item_id, "type": "reasoning", "text": text, "streaming": False}
                )
            elif btype in ("tool_use", "server_tool_use", "mcp_tool_use"):
                tool_id = str(block.get("id") or f"tool:{msg_id}:{n}")
                name = str(block.get("name") or "工具")
                self.tool_names[tool_id] = name
                existing = self.conv.get(tool_id)
                self.conv.upsert(
                    {
                        "id": tool_id,
                        "type": "tool",
                        "name": name,
                        "status": (existing or {}).get("status", "running"),
                    }
                )
                args = block.get("input")
                if isinstance(args, dict):
                    self._tool_input(tool_id, args)

    def _user(self, msg: Mapping[str, Any]) -> None:
        if msg.get("parent_tool_use_id") is not None:
            return
        message = msg.get("message") or {}
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        ):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tool_id = str(block.get("tool_use_id") or "")
                if not tool_id:
                    continue
                failed = bool(block.get("is_error"))
                text = _result_text(block.get("content"))
                clipped, cut = _clip(text, OUTPUT_CAP)
                status = "ok"
                if failed:
                    status = "declined" if tool_id in self.denied else "failed"
                self.conv.upsert(
                    {
                        "id": tool_id,
                        "type": "tool",
                        "name": self.tool_names.get(tool_id, "工具"),
                        "status": status,
                        "output": clipped,
                        "output_truncated": cut,
                    }
                )
            return
        text = _user_text(content)
        if not text:
            return
        # --replay-user-messages: the CLI acknowledges a message it accepted.
        pending = self.conv.find(
            lambda i: i["type"] == "user" and i.get("status") == "sending" and i["text"] == text
        )
        if pending is not None:
            self.conv.upsert({"id": pending["id"], "status": "sent"})
            return
        notice = _command_notice(text)
        if notice is not None:
            if notice:
                self.conv.upsert(
                    {"id": f"n:{msg.get('uuid') or now()}", "type": "notice", "text": notice}
                )
            return
        self.conv.upsert(
            {
                "id": f"user:{msg.get('uuid') or now()}",
                "type": "user",
                "text": text,
                "status": "sent",
            }
        )

    def _result(self, msg: Mapping[str, Any]) -> None:
        failed = bool(msg.get("is_error")) or str(msg.get("subtype") or "success") != "success"
        status = (
            "interrupted" if self.interrupt_requested else ("failed" if failed else "completed")
        )
        error = None
        if failed and not self.interrupt_requested:
            result = msg.get("result")
            errors = msg.get("errors")
            if isinstance(result, str) and result.strip():
                error = result.strip()
            elif isinstance(errors, list) and errors:
                error = "；".join(str(e) for e in errors[:3])
            else:
                error = f"Claude Code 报告这一轮未成功（{msg.get('subtype') or 'error'}）"
        turn = self.conv.turn or {"id": f"t{self._turn_seq}"}
        self.conv.finish_open_items("interrupted" if status != "completed" else "ok")
        for pending in self.conv.pending_permissions():
            self.conv.upsert({"id": pending["id"], "status": "expired"})
        self.conv.upsert(
            {
                "id": f"end:{turn['id']}",
                "type": "turn_end",
                "status": status,
                "error": error,
                "duration_ms": msg.get("duration_ms"),
                "denials": len(msg.get("permission_denials") or []),
            }
        )
        # A message the CLI never echoed back was still part of this finished turn.
        for item in self.conv.items():
            if item["type"] == "user" and item.get("status") == "sending":
                self.conv.upsert({"id": item["id"], "status": "sent"})
        self.conv.set_turn(None)
        self.interrupt_requested = False

    def _system(self, msg: Mapping[str, Any]) -> None:
        sub = msg.get("subtype")
        if sub == "init":
            keep = ("session_id", "model", "permissionMode", "apiKeySource", "cwd")
            self.info.update({k: msg.get(k) for k in keep if k in msg})
            version = msg.get("claude_code_version") or msg.get("version")
            if version:
                self.info["version"] = version
            mode = msg.get("permissionMode")
            if mode and mode != "default" and not self.info.get("mode_noticed"):
                self.info["mode_noticed"] = True
                self.conv.upsert(
                    {
                        "id": "n:permission-mode",
                        "type": "notice",
                        "text": f"Claude Code 当前权限模式：{_PERMISSION_MODES.get(mode, mode)}"
                        "（来自 Claude Code 自己的设置）。",
                    }
                )
        elif sub == "api_retry":
            turn = (self.conv.turn or {}).get("id", "")
            self.conv.upsert(
                {
                    "id": f"retry:{turn}",
                    "type": "notice",
                    "level": "warn",
                    "text": (
                        f"请求失败，Claude Code 正在重试（第 {msg.get('attempt')}"
                        f"/{msg.get('max_retries')} 次，原因：{msg.get('error') or '未知'}）"
                    ),
                }
            )
        elif sub == "compact_boundary":
            self.conv.upsert(
                {"id": f"n:{msg.get('uuid') or now()}", "type": "notice", "text": "上下文已压缩"}
            )
        elif sub == "permission_denied":
            self.conv.upsert(
                {
                    "id": f"n:{msg.get('uuid') or now()}",
                    "type": "notice",
                    "level": "warn",
                    "text": f"权限被拒绝：{msg.get('tool_name') or ''}",
                }
            )

    def _control_request(self, msg: Mapping[str, Any]) -> dict[str, Any] | None:
        request = msg.get("request") or {}
        rid = str(msg.get("request_id") or "")
        if request.get("subtype") != "can_use_tool":
            return {"request_id": rid, "unsupported": str(request.get("subtype"))}
        name = str(request.get("tool_name") or "工具")
        args = _dict(request.get("input"))
        tool_id = str(request.get("tool_use_id") or "")
        if tool_id:
            self.conv.upsert({"id": tool_id, "type": "tool", "name": name, "status": "waiting"})
            self.tool_names.setdefault(tool_id, name)
            self._tool_input(tool_id, args)
        suggestions = request.get("permission_suggestions")
        kind = "tool"
        options = [{"id": "allow", "label": "允许"}]
        if isinstance(suggestions, list) and suggestions:
            options.append({"id": "allow_always", "label": suggestion_label(suggestions)})
        options.append({"id": "deny", "label": "拒绝"})
        detail = pretty(args)
        diff = edit_diff(name, args)
        questions = None
        if name == "AskUserQuestion":
            kind = "question"
            questions = args.get("questions") if isinstance(args.get("questions"), list) else []
            options = [{"id": "deny", "label": "不回答"}]
        elif name == "ExitPlanMode":
            kind = "plan"
            detail = str(args.get("plan") or detail)
            options = [{"id": "allow", "label": "批准计划"}, {"id": "deny", "label": "继续计划"}]
        elif name == "Bash":
            detail = str(args.get("command") or detail)
            if args.get("description"):
                detail = f"{args['description']}\n\n$ {detail}"
        item = self.conv.upsert(
            {
                "id": f"perm:{rid}",
                "type": "permission",
                "kind": kind,
                "request_id": rid,
                "tool_id": tool_id or None,
                "tool": name,
                "title": claude_tool_title(name, args) or name,
                "detail": detail,
                "reason": request.get("decision_reason") or request.get("blocked_path"),
                "options": options,
                "questions": questions,
                "diff": diff,
                "status": "pending",
            }
        )
        return {"permission": item, "input": args, "suggestions": suggestions}


def suggestion_label(suggestions: list[Any]) -> str:
    """Say what "remember" would actually change, from Claude Code's own suggestion."""
    for entry in suggestions:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "setMode" and entry.get("mode") == "acceptEdits":
            return "允许，本会话内自动接受编辑"
        if entry.get("type") == "addRules":
            rules = [r for r in entry.get("rules") or [] if isinstance(r, dict)]
            if rules:
                rule = rules[0]
                text = str(rule.get("toolName") or "")
                if rule.get("ruleContent"):
                    text += f"({rule['ruleContent']})"
                where = {
                    "session": "本会话",
                    "localSettings": "本地设置",
                    "projectSettings": "项目设置",
                    "userSettings": "用户设置",
                }.get(str(entry.get("destination")), "")
                return f"允许，并始终允许 {text[:60]}" + (f"（{where}）" if where else "")
        if entry.get("type") == "addDirectories":
            return "允许，并允许访问该目录"
    return "允许，并记住"


def edit_diff(name: str, args: Mapping[str, Any]) -> str | None:
    """A readable -/+ view of what an edit tool asks to change."""

    def lines(prefix: str, text: Any) -> list[str]:
        return [prefix + line for line in str(text or "").splitlines()] if text else []

    if name == "Edit" and ("old_string" in args or "new_string" in args):
        out = ["@@ " + str(args.get("file_path") or "")]
        out += lines("-", args.get("old_string")) + lines("+", args.get("new_string"))
        return pretty("\n".join(out), OUTPUT_CAP)
    if name == "MultiEdit" and isinstance(args.get("edits"), list):
        out = []
        for edit in args["edits"]:
            if isinstance(edit, dict):
                out.append("@@ " + str(args.get("file_path") or ""))
                out += lines("-", edit.get("old_string")) + lines("+", edit.get("new_string"))
        return pretty("\n".join(out), OUTPUT_CAP)
    if name == "Write" and "content" in args:
        body = lines("+", args.get("content"))
        head = ["@@ 新内容 " + str(args.get("file_path") or "")]
        return pretty(
            "\n".join(head + body[:400] + (["+…"] if len(body) > 400 else [])), OUTPUT_CAP
        )
    return None


_PERMISSION_MODES = {
    "default": "默认（需要时询问）",
    "acceptEdits": "自动接受编辑",
    "plan": "计划模式",
    "auto": "自动审查",
    "dontAsk": "不询问（直接拒绝需要确认的操作）",
    "bypassPermissions": "跳过权限检查",
    "manual": "手动",
}


def claude_permission_response(
    decision: str,
    request: Mapping[str, Any],
    answers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The ``can_use_tool`` answer for the SDK control protocol."""
    args = dict(request.get("input") or {})
    if decision == "deny":
        return {"behavior": "deny", "message": "用户在 RepoBridge 中拒绝了这个操作"}
    if answers is not None:
        args["answers"] = dict(answers)
    response: dict[str, Any] = {"behavior": "allow", "updatedInput": args}
    if decision == "allow_always" and request.get("suggestions"):
        response["updatedPermissions"] = request["suggestions"]
    return response


# --- Claude Code transcript (history) ------------------------------------------------------------


def claude_config_dir(env: Mapping[str, str]) -> Path:
    configured = env.get("CLAUDE_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(env.get("HOME") or os.path.expanduser("~")) / ".claude"


def find_claude_transcript(env: Mapping[str, str], session_id: str) -> Path | None:
    """The transcript of exactly this session id (a UUID), wherever Claude Code filed it."""
    if not session_id or "/" in session_id or session_id.startswith("."):
        return None
    projects = claude_config_dir(env) / "projects"
    try:
        dirs = [d for d in projects.iterdir() if d.is_dir()]
    except OSError:
        return None
    for directory in dirs:
        candidate = directory / f"{session_id}.jsonl"
        if candidate.is_file():
            return candidate
    return None


def claude_transcript_items(path: Path) -> list[Item]:
    items: dict[str, Item] = {}
    names: dict[str, str] = {}
    with open(path, "rb") as fh:
        data = fh.read(HISTORY_FILE_CAP + 1)
    truncated = len(data) > HISTORY_FILE_CAP
    for n, raw in enumerate(data[:HISTORY_FILE_CAP].splitlines()):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain"):
            continue
        kind = entry.get("type")
        stamp = entry.get("timestamp") or now()
        uid = str(entry.get("uuid") or n)
        message = _dict(entry.get("message"))
        content = message.get("content")
        if kind == "user":
            if entry.get("isMeta"):
                continue
            if entry.get("isCompactSummary"):
                items[f"n:{uid}"] = {"id": f"n:{uid}", "type": "notice", "text": "上下文已压缩"}
                continue
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    tid = str(block.get("tool_use_id") or "")
                    tool = items.get(tid)
                    if tool is None:
                        continue
                    clipped, cut = _clip(_result_text(block.get("content")), OUTPUT_CAP)
                    tool.update(
                        {
                            "status": "failed" if block.get("is_error") else "ok",
                            "output": clipped,
                            "output_truncated": cut,
                        }
                    )
                continue
            text = _user_text(content)
            if not text:
                continue
            notice = _command_notice(text)
            if notice is not None:
                if notice:
                    items[f"n:{uid}"] = {"id": f"n:{uid}", "type": "notice", "text": notice}
                continue
            items[f"user:{uid}"] = {
                "id": f"user:{uid}",
                "type": "user",
                "text": text,
                "status": "sent",
                "time": stamp,
            }
        elif kind == "assistant":
            if entry.get("isApiErrorMessage"):
                items[f"n:{uid}"] = {
                    "id": f"n:{uid}",
                    "type": "notice",
                    "level": "error",
                    "text": _user_text(content) or "API 错误",
                    "time": stamp,
                }
                continue
            for i, block in enumerate(content if isinstance(content, list) else []):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text" and str(block.get("text") or "").strip():
                    items[f"a:{uid}:{i}"] = {
                        "id": f"a:{uid}:{i}",
                        "type": "assistant",
                        "text": str(block["text"]),
                        "time": stamp,
                    }
                elif btype == "thinking" and str(block.get("thinking") or "").strip():
                    items[f"r:{uid}:{i}"] = {
                        "id": f"r:{uid}:{i}",
                        "type": "reasoning",
                        "text": str(block["thinking"]),
                        "time": stamp,
                    }
                elif btype in ("tool_use", "server_tool_use", "mcp_tool_use"):
                    tid = str(block.get("id") or f"tool:{uid}:{i}")
                    name = str(block.get("name") or "工具")
                    names[tid] = name
                    args = _dict(block.get("input"))
                    items[tid] = {
                        "id": tid,
                        "type": "tool",
                        "name": name,
                        "title": claude_tool_title(name, args),
                        "input": pretty(args),
                        "files": claude_tool_files(name, args),
                        "status": "unknown",
                        "time": stamp,
                    }
        elif kind == "system" and entry.get("subtype") == "compact_boundary":
            items[f"n:{uid}"] = {"id": f"n:{uid}", "type": "notice", "text": "上下文已压缩"}
    out = list(items.values())
    if truncated:
        out.insert(
            0,
            {
                "id": "n:history-truncated",
                "type": "notice",
                "level": "warn",
                "text": "会话记录很长，这里只显示了开头的 64 MB；完整历史仍在原生会话中。",
            },
        )
    return out


# --- Codex app-server ----------------------------------------------------------------------------

_CODEX_STATUS = {
    "inProgress": "running",
    "completed": "ok",
    "failed": "failed",
    "declined": "declined",
}


def _user_inputs(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    parts = []
    for entry in content:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "text":
            parts.append(str(entry.get("text") or ""))
        elif entry.get("type") in ("image", "localImage"):
            parts.append("[图片]")
        elif entry.get("type") in ("mention", "skill"):
            parts.append(f"@{entry.get('name')}")
    return "\n".join(p for p in parts if p)


def codex_item(item: Mapping[str, Any], *, client_ids: Mapping[str, str] | None = None) -> Item:
    """Map one app-server ThreadItem to a conversation item (unknown kinds stay visible)."""
    kind = item.get("type")
    iid = str(item.get("id") or "")
    status = _CODEX_STATUS.get(str(item.get("status") or ""), "ok")
    if kind == "userMessage":
        client = item.get("clientId")
        if client and client_ids is not None and client in client_ids:
            iid = client_ids[str(client)]
        else:
            iid = f"user:{iid}"
        return {
            "id": iid,
            "type": "user",
            "text": _user_inputs(item.get("content")),
            "status": "sent",
        }
    if kind == "agentMessage":
        return {"id": iid, "type": "assistant", "text": str(item.get("text") or "")}
    if kind == "reasoning":
        summary = item.get("summary") or []
        content = item.get("content") or []
        parts = summary if summary else content
        text = "\n\n".join(str(p) for p in parts if p) if isinstance(parts, list) else ""
        return {"id": iid, "type": "reasoning", "text": text}
    if kind == "plan":
        return {
            "id": iid,
            "type": "reasoning",
            "label": "计划",
            "text": str(item.get("text") or ""),
        }
    if kind == "commandExecution":
        code = item.get("exitCode")
        if status == "ok" and isinstance(code, int) and code != 0:
            status = "failed"
        output, cut = _clip(str(item.get("aggregatedOutput") or ""), OUTPUT_CAP)
        return {
            "id": iid,
            "type": "tool",
            "name": "命令",
            "title": " ".join(str(item.get("command") or "").split())[:200],
            "input": f"$ {item.get('command') or ''}\n（目录 {item.get('cwd') or ''}）",
            "output": output,
            "output_truncated": cut,
            "exit_code": code,
            "duration_ms": item.get("durationMs"),
            "status": status,
        }
    if kind == "fileChange":
        changes = item.get("changes") or []
        files = []
        for change in changes if isinstance(changes, list) else []:
            if not isinstance(change, dict):
                continue
            ckind = (
                (change.get("kind") or {}).get("type")
                if isinstance(change.get("kind"), dict)
                else None
            )
            diff, _ = _clip(str(change.get("diff") or ""), OUTPUT_CAP)
            files.append({"path": change.get("path"), "kind": ckind or "update", "diff": diff})
        title = ", ".join(str(f["path"]) for f in files[:3]) + (" …" if len(files) > 3 else "")
        return {
            "id": iid,
            "type": "tool",
            "name": "编辑文件",
            "title": title,
            "files": files,
            "status": status,
        }
    if kind == "mcpToolCall":
        error = item.get("error")
        result = item.get("result")
        return {
            "id": iid,
            "type": "tool",
            "name": f"{item.get('server')}.{item.get('tool')}",
            "title": "",
            "input": pretty(item.get("arguments")),
            "output": pretty(result, OUTPUT_CAP) if result is not None else "",
            "error": pretty(error) if error else None,
            "status": "failed" if error else status,
        }
    if kind == "dynamicToolCall":
        return {
            "id": iid,
            "type": "tool",
            "name": str(item.get("tool") or "工具"),
            "title": "",
            "input": pretty(item.get("arguments")),
            "output": pretty(item.get("contentItems"), OUTPUT_CAP),
            "status": "failed" if item.get("success") is False else status,
        }
    if kind == "webSearch":
        return {
            "id": iid,
            "type": "tool",
            "name": "网页搜索",
            "title": str(item.get("query") or ""),
            "status": status,
        }
    if kind == "imageView":
        return {
            "id": iid,
            "type": "tool",
            "name": "查看图片",
            "title": str(item.get("path") or ""),
            "status": "ok",
        }
    if kind in ("collabAgentToolCall", "subAgentActivity"):
        return {
            "id": iid,
            "type": "tool",
            "name": "子代理",
            "title": str(item.get("prompt") or item.get("agentPath") or ""),
            "status": status,
        }
    if kind == "contextCompaction":
        return {"id": iid, "type": "notice", "text": "上下文已压缩"}
    if kind in ("enteredReviewMode", "exitedReviewMode"):
        text = "进入审查模式" if kind == "enteredReviewMode" else "退出审查模式"
        return {"id": iid, "type": "notice", "text": text}
    if kind in ("functionCallOutput", "sleep", "hookPrompt"):
        return {"id": iid, "type": "skip"}
    return {"id": iid, "type": "notice", "text": f"（RepoBridge 暂不显示这类条目：{kind}）"}


def codex_turn_items(turns: Iterable[Mapping[str, Any]]) -> list[Item]:
    out: list[Item] = []
    for turn in turns:
        tid = str(turn.get("id") or len(out))
        for raw in turn.get("items") or []:
            if isinstance(raw, dict):
                item = codex_item(raw)
                if item["type"] != "skip":
                    if item["type"] == "assistant":
                        item["streaming"] = False
                    out.append(item)
        status = str(turn.get("status") or "completed")
        error = turn.get("error")
        out.append(
            {
                "id": f"end:{tid}",
                "type": "turn_end",
                "status": "completed" if status == "inProgress" else status,
                "error": (error or {}).get("message") if isinstance(error, dict) else None,
                "duration_ms": turn.get("durationMs"),
            }
        )
    return out


class CodexTranslator:
    """Translate app-server notifications and server requests into conversation items."""

    def __init__(self, conv: Conversation) -> None:
        self.conv = conv
        self.client_ids: dict[str, str] = {}
        self.thread_id: str | None = None
        self.turn_id: str | None = None
        self.interrupt_requested = False

    def begin_turn(self, client_id: str, text: str) -> None:
        self.client_ids[client_id] = f"user:{client_id}"
        self.interrupt_requested = False
        self.conv.upsert(
            {"id": f"user:{client_id}", "type": "user", "text": text, "status": "sending"}
        )
        self.conv.set_turn({"id": None, "status": "starting", "started_at": now()})

    def notification(self, method: str, params: Mapping[str, Any]) -> None:
        if method == "turn/started":
            turn = params.get("turn") or {}
            self.turn_id = str(turn.get("id") or "")
            self.conv.set_turn({"id": self.turn_id, "status": "running", "started_at": now()})
            for item in self.conv.items():
                if item["type"] == "user" and item.get("status") == "sending":
                    self.conv.upsert({"id": item["id"], "status": "sent"})
        elif method in ("item/started", "item/completed"):
            raw = params.get("item")
            if isinstance(raw, dict):
                item = codex_item(raw, client_ids=self.client_ids)
                if item["type"] == "skip":
                    return
                if item["type"] == "user" and self.conv.get(item["id"]) is not None:
                    self.conv.upsert({"id": item["id"], "status": "sent"})
                    return
                if method == "item/started":
                    existing = self.conv.get(item["id"])
                    if item["type"] == "assistant":
                        item["streaming"] = True
                        if existing and existing.get("text"):
                            item.pop("text", None)
                    if item["type"] == "tool" and existing and existing.get("output"):
                        item.pop("output", None)
                elif item["type"] in ("assistant", "reasoning"):
                    item["streaming"] = False
                self.conv.upsert(item)
        elif method == "item/agentMessage/delta":
            self.conv.append(str(params.get("itemId")), "text", str(params.get("delta") or ""))
        elif method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
            iid = str(params.get("itemId"))
            if self.conv.get(iid) is None:
                self.conv.upsert({"id": iid, "type": "reasoning", "text": "", "streaming": True})
            self.conv.append(iid, "text", str(params.get("delta") or ""))
        elif method in ("item/commandExecution/outputDelta", "item/fileChange/outputDelta"):
            self.conv.append(
                str(params.get("itemId")), "output", str(params.get("delta") or ""), OUTPUT_CAP
            )
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            status = str(turn.get("status") or "completed")
            error = turn.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            self.conv.finish_open_items("ok" if status == "completed" else "interrupted")
            self.conv.upsert(
                {
                    "id": f"end:{turn.get('id') or self.turn_id}",
                    "type": "turn_end",
                    "status": status,
                    "error": message,
                    "duration_ms": turn.get("durationMs"),
                }
            )
            self.turn_id = None
            self.interrupt_requested = False
            self.conv.set_turn(None)
        elif method == "error":
            error = params.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            retry = bool(params.get("willRetry"))
            self.conv.upsert(
                {
                    "id": f"err:{params.get('turnId') or ''}",
                    "type": "notice",
                    "level": "warn" if retry else "error",
                    "text": (
                        f"出错，Codex 正在重试：{message}"
                        if retry
                        else f"Codex 报告错误：{message}"
                    ),
                }
            )
        elif method == "serverRequest/resolved":
            rid = str(params.get("requestId"))
            resolved = self.conv.get(f"perm:{rid}")
            if resolved and resolved.get("status") == "pending":
                self.conv.upsert({"id": resolved["id"], "status": "cancelled"})
        elif method in ("warning", "configWarning", "guardianWarning"):
            text = params.get("message") or params.get("summary") or ""
            if text:
                self.conv.upsert(
                    {"id": f"w:{now()}", "type": "notice", "level": "warn", "text": str(text)[:600]}
                )
        elif method == "model/rerouted":
            self.conv.upsert(
                {
                    "id": f"n:{now()}",
                    "type": "notice",
                    "text": "Codex 改用了模型 "
                    + str(params.get("toModel") or params.get("model") or ""),
                }
            )

    def server_request(self, rid: str, method: str, params: Mapping[str, Any]) -> Item | None:
        """Return the permission item to show, or None for a request the host must refuse."""
        item_id = params.get("itemId")
        related = self.conv.get(str(item_id)) if item_id else None
        if related is not None and related["type"] == "tool":
            self.conv.upsert({"id": related["id"], "status": "waiting"})
        base: Item = {
            "id": f"perm:{rid}",
            "type": "permission",
            "request_id": rid,
            "method": method,
            "tool_id": related["id"] if related else None,
            "status": "pending",
            "reason": params.get("reason"),
        }
        session_opt = {"id": "allow_session", "label": "本会话内都允许"}
        if method == "item/commandExecution/requestApproval":
            network = params.get("networkApprovalContext")
            command = str(params.get("command") or (related or {}).get("title") or "")
            if isinstance(network, dict):
                title = f"访问网络 {network.get('host')}（{network.get('protocol')}）"
            else:
                title = " ".join(command.split())[:200]
            return self.conv.upsert(
                {
                    **base,
                    "kind": "command",
                    "tool": "命令",
                    "title": title or "运行命令",
                    "detail": f"$ {command}\n（目录 {params.get('cwd') or ''}）" if command else "",
                    "options": [
                        {"id": "allow", "label": "允许"},
                        session_opt,
                        {"id": "deny", "label": "拒绝"},
                    ],
                }
            )
        if method == "item/fileChange/requestApproval":
            files = (related or {}).get("files") or []
            detail = "\n\n".join(f"{f.get('path')}\n{f.get('diff') or ''}".strip() for f in files)
            return self.conv.upsert(
                {
                    **base,
                    "kind": "file",
                    "tool": "编辑文件",
                    "title": (related or {}).get("title") or "修改文件",
                    "detail": pretty(detail) if detail else "",
                    "grant_root": params.get("grantRoot"),
                    "options": [
                        {"id": "allow", "label": "允许"},
                        session_opt,
                        {"id": "deny", "label": "拒绝"},
                    ],
                }
            )
        if method == "item/permissions/requestApproval":
            return self.conv.upsert(
                {
                    **base,
                    "kind": "permissions",
                    "tool": "额外权限",
                    "title": "Codex 请求额外的权限",
                    "detail": pretty(params.get("permissions")),
                    "options": [
                        {"id": "allow", "label": "本轮允许"},
                        session_opt,
                        {"id": "deny", "label": "拒绝"},
                    ],
                }
            )
        return None


def codex_permission_response(
    method: str, decision: str, params: Mapping[str, Any]
) -> dict[str, Any]:
    if method == "item/permissions/requestApproval":
        if decision == "deny":
            return {"permissions": {}}
        response: dict[str, Any] = {"permissions": params.get("permissions") or {}}
        if decision == "allow_session":
            response["scope"] = "session"
        return response
    native = {"allow": "accept", "allow_session": "acceptForSession", "deny": "decline"}
    return {"decision": native[decision]}
