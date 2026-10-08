"""Structured native connections for the conversation view.

* Claude Code: ``claude -p --input-format stream-json --output-format stream-json`` with
  ``--permission-prompt-tool stdio`` — the control protocol the official Agent SDK uses. The CLI
  keeps its own login, settings, tools, permission rules and transcript.
* Codex: ``codex app-server`` (JSON-RPC over stdio), the protocol of the official IDE extension
  and desktop app.

Both run as App-owned child processes (own process group, pipes, no tty). Only the user's actions
send messages; answers to permission requests come only from the user. Nothing reads login state.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from harness_bridge.workbench.controls import CODEX_MODE_BY_ID
from harness_bridge.workbench.conversation import (
    ClaudeTranslator,
    CodexTranslator,
    Conversation,
    claude_permission_response,
    claude_transcript_items,
    codex_permission_response,
    codex_turn_items,
    find_claude_transcript,
)
from harness_bridge.workbench.harness import CLAUDE, CODEX, session_env
from harness_bridge.workbench.pty_host import ExitInfo, group_members

MAX_LINE = 64 << 20
CLIENT_VERSION = "0.2"


@dataclass(frozen=True)
class StructuredSpec:
    argv: list[str]
    env: dict[str, str]
    cwd: str
    native_session_id: str | None
    binding: str
    stripped_env: list[str]
    mode: str
    title: str


def claude_argv(binary: str, *, mode: str, session_id: str, title: str) -> list[str]:
    argv = [
        binary,
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--replay-user-messages",
        "--permission-prompt-tool",
        "stdio",
    ]
    if mode == "new":
        return [*argv, "--session-id", session_id, "-n", title]
    return [*argv, "--resume", session_id]


def codex_argv(binary: str) -> list[str]:
    return [binary, "app-server", "--listen", "stdio://"]


def build_structured(
    kind: str,
    binary: str,
    *,
    mode: str,
    workdir: str,
    title: str,
    native_session_id: str | None,
    base_env: Mapping[str, str],
) -> StructuredSpec:
    if mode not in ("new", "resume"):
        raise ValueError(mode)
    if mode == "resume" and not native_session_id:
        raise ValueError("resume requires a native session id")
    env, stripped = session_env(base_env)
    sid: str | None
    if kind == CLAUDE:
        sid = native_session_id or str(uuid.uuid4())
        argv = claude_argv(binary, mode=mode, session_id=sid, title=title)
        binding = "preassigned" if mode == "new" else "resume_requested"
    elif kind == CODEX:
        sid = native_session_id if mode == "resume" else None
        argv = codex_argv(binary)
        binding = "pending" if mode == "new" else "resume_requested"
    else:
        raise ValueError(f"unknown harness {kind!r}")
    return StructuredSpec(argv, env, workdir, sid, binding, stripped, mode, title)


class PipeProcess:
    """A child with JSON-lines stdin/stdout in its own process group; stderr goes to a file."""

    def __init__(
        self,
        spec: StructuredSpec,
        stderr_path: Path,
        *,
        on_line: Callable[[dict[str, Any]], None],
        on_exit: Callable[[ExitInfo], None],
    ) -> None:
        self.spec = spec
        self.stderr_path = stderr_path
        self._on_line = on_line
        self._on_exit = on_exit
        self.proc: subprocess.Popen[bytes] | None = None
        self._write_lock = threading.Lock()
        self._exited = threading.Event()
        self._stop_lock = threading.Lock()
        self.exit_info: ExitInfo | None = None
        self._stderr: IO[bytes] | None = None

    @property
    def pid(self) -> int:
        assert self.proc is not None
        return self.proc.pid

    def start(self) -> None:
        self._stderr = open(self.stderr_path, "ab")  # noqa: SIM115 - closed when the reader ends
        try:
            self.proc = subprocess.Popen(
                self.spec.argv,
                cwd=self.spec.cwd,
                env=self.spec.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                start_new_session=True,
                close_fds=True,
            )
        except BaseException:
            self._stderr.close()
            raise
        threading.Thread(target=self._read, name=f"json-{self.pid}", daemon=True).start()

    def write(self, message: Mapping[str, Any]) -> None:
        if self._exited.is_set() or self.proc is None or self.proc.stdin is None:
            raise OSError("session process has exited")
        line = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            self.proc.stdin.write(line)
            self.proc.stdin.flush()

    def close_input(self) -> None:
        if self.proc is not None and self.proc.stdin is not None:
            with self._write_lock, contextlib.suppress(OSError):
                self.proc.stdin.close()

    def wait(self, timeout: float | None = None) -> bool:
        return self._exited.wait(timeout)

    @property
    def exited(self) -> bool:
        return self._exited.is_set()

    def terminate(self, grace: float = 3.0) -> ExitInfo | None:
        """End input first (the CLI cancels open prompts and exits), then escalate."""
        with self._stop_lock:
            self.close_input()
            if self._exited.wait(grace) and not group_members(self.pid):
                return self.exit_info
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(self.pid, sig)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    break
                if self._exited.wait(grace) and not group_members(self.pid):
                    break
            self._exited.wait(grace)
            return self.exit_info

    def _read(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        stdout = self.proc.stdout
        try:
            while True:
                raw = stdout.readline(MAX_LINE)
                if not raw:
                    break
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    try:
                        self._on_line(message)
                    except Exception:  # noqa: S112 - one bad message must not kill the reader
                        continue
        finally:
            code = self.proc.wait()
            pgid = self.proc.pid
            remaining = group_members(pgid)
            if remaining:
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(pgid, sig)
                    except (ProcessLookupError, PermissionError):
                        break
                    if _wait_empty(pgid, 2.0):
                        break
                remaining = group_members(pgid)
            if self._stderr is not None:
                self._stderr.close()
            self.exit_info = ExitInfo(
                exit_code=code if code >= 0 else None,
                exit_signal=-code if code < 0 else None,
                confirmed=remaining == [],
                remaining_group=remaining or [],
            )
            self._exited.set()
            self._on_exit(self.exit_info)


def _wait_empty(pgid: int, timeout: float) -> bool:
    end = threading.Event()
    waited = 0.0
    while waited < timeout:
        if group_members(pgid) == []:
            return True
        end.wait(0.1)
        waited += 0.1
    return group_members(pgid) == []


class StructuredError(Exception):
    pass


@dataclass
class SessionCallbacks:
    on_native_id: Callable[[str, str], None]
    on_turn_started: Callable[[], None]
    on_turn_finished: Callable[[], None]
    on_ready: Callable[[], None]
    on_activity: Callable[[dict[str, Any]], None]
    on_exit: Callable[[ExitInfo], None]
    on_fatal: Callable[[str], None] = field(default=lambda _m: None)
    # Host-reported settings ({"model"?, "effort"?, "mode"?, "source"}) and the harness catalog.
    on_settings: Callable[[dict[str, Any]], None] = field(default=lambda _s: None)
    on_catalog: Callable[[dict[str, Any]], None] = field(default=lambda _c: None)


class StructuredSession:
    """Common surface the service uses for either harness."""

    harness = ""

    def __init__(self, spec: StructuredSpec, run_dir: Path, conv: Conversation) -> None:
        self.spec = spec
        self.run_dir = run_dir
        self.conv = conv
        self.ready = threading.Event()
        self.process: PipeProcess | None = None
        self.info: dict[str, Any] = {}
        self.queue: list[Any] = []
        self._lock = threading.RLock()
        self.permission_requests: dict[str, dict[str, Any]] = {}

    @property
    def pid(self) -> int:
        assert self.process is not None
        return self.process.pid

    @property
    def busy(self) -> bool:
        return self.conv.turn is not None

    def terminate(self, grace: float = 3.0) -> ExitInfo | None:
        assert self.process is not None
        return self.process.terminate(grace)

    def wait(self, timeout: float | None = None) -> bool:
        return self.process.wait(timeout) if self.process else True

    # implemented per harness
    def start(self) -> None:
        raise NotImplementedError

    def send(self, text: str, client_id: str) -> None:
        raise NotImplementedError

    def interrupt(self) -> bool:
        raise NotImplementedError

    def answer(
        self, request_id: str, decision: str, answers: Mapping[str, Any] | None = None
    ) -> None:
        raise NotImplementedError

    def apply_settings(self, chosen: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """Ask the harness to use these settings; per field {"ok", "error"?, "pending"?}."""
        raise NotImplementedError


# --- Claude Code ---------------------------------------------------------------------------------


class ClaudeStreamSession(StructuredSession):
    harness = CLAUDE

    def __init__(
        self, spec: StructuredSpec, run_dir: Path, conv: Conversation, cb: SessionCallbacks
    ) -> None:
        super().__init__(spec, run_dir, conv)
        self.cb = cb
        self.translator = ClaudeTranslator(conv)
        self._req = 0
        self._control_waiters: dict[str, tuple[threading.Event, dict[str, Any]]] = {}
        self._init_rid: str | None = None
        self.initialized = threading.Event()

    def start(self) -> None:
        self.process = PipeProcess(
            self.spec,
            self.run_dir / "stderr.log",
            on_line=self._on_line,
            on_exit=self._exit,
        )
        self.process.start()
        # The SDK handshake: the CLI answers with its commands and model catalog; hooks stay the
        # user's own.
        self._init_rid = self._control({"subtype": "initialize", "hooks": None})
        self.ready.set()
        self.cb.on_ready()

    def _exit(self, info: ExitInfo) -> None:
        for event, box in list(self._control_waiters.values()):
            box["error"] = "Claude Code 进程已退出"
            event.set()
        self.initialized.set()
        self.cb.on_exit(info)

    def _control(self, request: dict[str, Any], *, waiter: bool = False) -> str:
        self._req += 1
        rid = f"rb_{self._req}_{uuid.uuid4().hex[:8]}"
        if waiter:
            self._control_waiters[rid] = (threading.Event(), {})
        assert self.process is not None
        try:
            self.process.write({"type": "control_request", "request_id": rid, "request": request})
        except OSError:
            self._control_waiters.pop(rid, None)
            raise
        return rid

    def control_wait(self, request: dict[str, Any], timeout: float = 20) -> dict[str, Any]:
        """Send a control request and wait for the CLI's answer (raises with its error text)."""
        try:
            rid = self._control(request, waiter=True)
        except OSError as exc:
            raise StructuredError(f"Claude Code 连接已断开：{exc}") from None
        event, box = self._control_waiters[rid]
        try:
            if not event.wait(timeout):
                raise StructuredError(
                    f"Claude Code 没有在 {int(timeout)} 秒内回应 {request['subtype']}"
                )
        finally:
            self._control_waiters.pop(rid, None)
        if "error" in box:
            raise StructuredError(str(box["error"]) or f"{request['subtype']} 失败")
        response = box.get("response")
        return response if isinstance(response, dict) else {}

    def wait_initialized(self, timeout: float = 30) -> bool:
        return self.initialized.wait(timeout)

    def send(
        self,
        text: str,
        client_id: str,
        blocks: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        display: str | None = None,
    ) -> None:
        with self._lock:
            if self.busy:
                raise StructuredError("上一轮还在进行；可以先停止它")
            native_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"repobridge:{client_id}"))
            self.translator.begin_turn(
                client_id,
                text if display is None else display,
                attachments,
                native_uuid,
                echo_text=text,
            )
            content: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
            content.extend(blocks or [])
            assert self.process is not None
            self.process.write(
                {
                    "type": "user",
                    "message": {"role": "user", "content": content},
                    "parent_tool_use_id": None,
                    "session_id": self.spec.native_session_id or "",
                    "uuid": native_uuid,
                }
            )
        self.cb.on_turn_started()
        self.cb.on_activity({"event": "UserPromptSubmit", "prompt": text[:2000]})

    def interrupt(self) -> bool:
        with self._lock:
            if not self.busy:
                return False
            self.translator.interrupt_requested = True
            for pending in self.conv.pending_permissions():
                self._respond_permission(pending["request_id"], "deny", None)
            self._control({"subtype": "interrupt"})
        return True

    def apply_settings(self, chosen: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """Apply each chosen field with its own control request (read back separately)."""
        results: dict[str, dict[str, Any]] = {}
        requests: dict[str, Callable[[Any], dict[str, Any]]] = {
            "model": lambda v: {"subtype": "set_model", "model": v or "default"},
            "effort": lambda v: {"subtype": "apply_flag_settings", "settings": {"effortLevel": v}},
            "mode": lambda v: {"subtype": "set_permission_mode", "mode": v or "default"},
        }
        report: dict[str, Any] = {"source": "control_response"}
        for key, build in requests.items():
            if key not in chosen:
                continue
            try:
                response = self.control_wait(build(chosen[key]))
            except StructuredError as exc:
                results[key] = {"ok": False, "error": str(exc)}
                continue
            results[key] = {"ok": True}
            if key == "mode" and isinstance(response.get("mode"), str):
                report["mode"] = response["mode"]
                self.info["mode"] = response["mode"]
        if "mode" in report:
            self.cb.on_settings(dict(report))
        return results

    def read_settings(self) -> dict[str, Any] | None:
        """``get_settings``: the model and effort Claude Code has actually applied."""
        try:
            response = self.control_wait({"subtype": "get_settings"})
        except StructuredError as exc:
            self.info["settings_error"] = str(exc)
            return None
        applied = _obj(response.get("applied"))
        effective = _obj(response.get("effective"))
        report: dict[str, Any] = {"source": "get_settings"}
        if isinstance(applied.get("model"), str):
            report["model"] = applied["model"]
        if "effort" in applied:
            report["effort"] = applied.get("effort")
        permissions = effective.get("permissions")
        if "mode" not in self.info and isinstance(permissions, dict):
            default_mode = permissions.get("defaultMode")
            if isinstance(default_mode, str):
                report["mode"] = "default" if default_mode == "manual" else default_mode
        self.cb.on_settings(report)
        return report

    def answer(
        self, request_id: str, decision: str, answers: Mapping[str, Any] | None = None
    ) -> None:
        with self._lock:
            self._respond_permission(request_id, decision, answers)

    def _respond_permission(
        self, request_id: str, decision: str, answers: Mapping[str, Any] | None
    ) -> None:
        request = self.permission_requests.pop(request_id, None)
        if request is None:
            raise StructuredError("这个权限请求已经结束")
        if decision not in ("allow", "allow_always", "deny"):
            raise StructuredError(f"unknown decision {decision!r}")
        response = claude_permission_response(decision, request, answers)
        if decision == "deny" and request.get("tool_id"):
            self.translator.denied.add(str(request["tool_id"]))
        assert self.process is not None
        self.process.write(
            {
                "type": "control_response",
                "response": {"subtype": "success", "request_id": request_id, "response": response},
            }
        )
        label = {"allow": "allowed", "allow_always": "allowed", "deny": "denied"}[decision]
        self.conv.upsert({"id": f"perm:{request_id}", "status": label, "decision": decision})
        self.cb.on_activity(
            {"event": "PermissionDecision", "decision": decision, "tool_name": request.get("tool")}
        )

    def _control_response(self, msg: dict[str, Any]) -> None:
        response = _obj(msg.get("response"))
        rid = str(response.get("request_id") or "")
        ok = response.get("subtype") == "success"
        payload = _obj(response.get("response"))
        if rid and rid == self._init_rid:
            if ok:
                self.cb.on_catalog(dict(payload))
            else:
                self.info["init_error"] = str(response.get("error") or "initialize failed")
            self.initialized.set()
        waiter = self._control_waiters.get(rid)
        if waiter is not None:
            event, box = waiter
            if ok:
                box["response"] = payload
            else:
                box["error"] = str(response.get("error") or "")
            event.set()

    def _on_line(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "control_response":
            self._control_response(msg)
            return
        sid = msg.get("session_id")
        if isinstance(sid, str) and sid and kind == "system" and msg.get("subtype") == "init":
            self.cb.on_native_id(
                sid, "confirmed" if sid == self.spec.native_session_id else "observed"
            )
            report: dict[str, Any] = {"source": "system/init"}
            if isinstance(msg.get("model"), str):
                report["model"] = msg["model"]
            if isinstance(msg.get("permissionMode"), str):
                report["mode"] = msg["permissionMode"]
                self.info["mode"] = msg["permissionMode"]
            self.cb.on_settings(report)
        if kind == "stream_event" and msg.get("parent_tool_use_id") is None:
            event = msg.get("event") or {}
            if event.get("type") == "message_start":
                model = (event.get("message") or {}).get("model")
                if isinstance(model, str) and model:
                    # The model that actually answered this turn, from the API response itself.
                    self.cb.on_settings({"source": "message_start", "turn_model": model})
        out = self.translator.feed(msg)
        self.info.update({k: v for k, v in self.translator.info.items() if k != "mode"})
        if out and "unsupported" in out:
            assert self.process is not None
            self.process.write(
                {
                    "type": "control_response",
                    "response": {
                        "subtype": "error",
                        "request_id": out["request_id"],
                        "error": f"RepoBridge does not handle {out['unsupported']}",
                    },
                }
            )
        elif out and "permission" in out:
            item = out["permission"]
            self.permission_requests[item["request_id"]] = {
                "input": out["input"],
                "suggestions": out["suggestions"],
                "tool": item["tool"],
                "tool_id": item.get("tool_id"),
            }
            self.cb.on_activity(
                {
                    "event": "PermissionRequest",
                    "tool_name": item["tool"],
                    "summary": item["title"],
                }
            )
        if kind == "assistant" and msg.get("parent_tool_use_id") is None:
            for block in (msg.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    self.cb.on_activity(
                        {
                            "event": "PreToolUse",
                            "tool_name": block.get("name"),
                            "tool_use_id": block.get("id"),
                            "summary": (self.conv.get(str(block.get("id"))) or {}).get("title"),
                        }
                    )
        elif kind == "user" and msg.get("parent_tool_use_id") is None:
            content = (msg.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool = self.conv.get(str(block.get("tool_use_id"))) or {}
                    self.cb.on_activity(
                        {
                            "event": "PostToolUseFailure"
                            if block.get("is_error")
                            else "PostToolUse",
                            "tool_name": tool.get("name"),
                            "tool_use_id": block.get("tool_use_id"),
                            "declined": tool.get("status") == "declined",
                        }
                    )
        elif kind == "result":
            self.cb.on_activity({"event": "Stop", "status": msg.get("subtype")})
            self.cb.on_turn_finished()


# --- Codex ---------------------------------------------------------------------------------------


class CodexAppServerSession(StructuredSession):
    harness = CODEX

    def __init__(
        self, spec: StructuredSpec, run_dir: Path, conv: Conversation, cb: SessionCallbacks
    ) -> None:
        super().__init__(spec, run_dir, conv)
        self.cb = cb
        self.translator = CodexTranslator(conv)
        self._next_id = 0
        self._waiters: dict[int, tuple[threading.Event, dict[str, Any]]] = {}
        self._server_requests: dict[str, tuple[Any, str, dict[str, Any]]] = {}
        self.thread_id: str | None = spec.native_session_id
        self.failure: str | None = None
        # Settings to pass when the thread is started or resumed (set by the service).
        self.connect_settings: dict[str, Any] = {}
        self._confirm_after_turn = False

    def start(self) -> None:
        self.process = PipeProcess(
            self.spec,
            self.run_dir / "stderr.log",
            on_line=self._on_line,
            on_exit=self._exit,
        )
        self.process.start()
        threading.Thread(target=self._handshake, name="codex-handshake", daemon=True).start()

    def _exit(self, info: ExitInfo) -> None:
        for event, box in list(self._waiters.values()):
            box["error"] = {"message": "app-server exited"}
            event.set()
        self.cb.on_exit(info)

    def _handshake(self) -> None:
        try:
            self.call(
                "initialize",
                {
                    "clientInfo": {
                        "name": "repobridge",
                        "title": "RepoBridge",
                        "version": CLIENT_VERSION,
                    }
                },
            )
            self._notify("initialized", None)
            self._load_catalog()
            params: dict[str, Any] = {
                "cwd": self.spec.cwd,
                **codex_thread_settings(self.connect_settings),
            }
            if self.spec.mode == "resume" and self.thread_id:
                result = self.call(
                    "thread/resume",
                    {"threadId": self.thread_id, "excludeTurns": True, **params},
                )
            else:
                result = self.call("thread/start", params)
            thread = result.get("thread") or {}
            self.thread_id = str(thread.get("id") or self.thread_id or "")
            self.translator.thread_id = self.thread_id
            self.info.update(
                {
                    "thread_source": thread.get("source"),
                    "model": result.get("model") or thread.get("model"),
                    "approval_policy": result.get("approvalPolicy"),
                    "sandbox": (result.get("sandbox") or {}).get("type")
                    if isinstance(result.get("sandbox"), dict)
                    else result.get("sandbox"),
                    "cli_version": thread.get("cliVersion"),
                }
            )
            self.cb.on_settings(
                {
                    "source": "thread/resume" if self.spec.mode == "resume" else "thread/start",
                    "model": result.get("model") or thread.get("model"),
                    "effort": result.get("reasoningEffort", thread.get("reasoningEffort")),
                    "approval": result.get("approvalPolicy"),
                    "sandbox": result.get("sandbox"),
                }
            )
            if self.spec.mode == "new":
                self.call("thread/name/set", {"threadId": self.thread_id, "name": self.spec.title})
                self.cb.on_native_id(self.thread_id, "confirmed")
            else:
                self.cb.on_native_id(self.thread_id, "confirmed")
                self.load_history()
        except StructuredError as exc:
            self.failure = str(exc)
            self.cb.on_fatal(f"Codex app-server 未能就绪：{exc}")
            return
        self.ready.set()
        self.cb.on_ready()
        with self._lock:
            queued, self.queue = self.queue, []
        for turn in queued:
            self._start_turn(turn)

    def _load_catalog(self) -> None:
        """``model/list`` and ``configRequirements/read``: what the selectors may offer."""
        models: list[dict[str, Any]] = []
        cursor: str | None = None
        try:
            for _ in range(10):
                page = self.call("model/list", {"cursor": cursor} if cursor else {})
                models.extend(m for m in page.get("data") or [] if isinstance(m, dict))
                cursor = page.get("nextCursor")
                if not cursor:
                    break
        except StructuredError as exc:
            self.cb.on_catalog({"error": f"model/list 失败：{exc}"})
            return
        requirements: dict[str, Any] | None = None
        try:
            raw = self.call("configRequirements/read", {}).get("requirements")
            requirements = raw if isinstance(raw, dict) else None
        except StructuredError:
            requirements = None
        self.cb.on_catalog({"models": models, "requirements": requirements})

    def read_settings(self, with_mode: bool) -> None:
        """Read back what the thread now uses: ``thread/read`` (model, effort) and, after a
        turn, ``thread/resume`` on the loaded thread (approval policy and sandbox)."""
        if not self.thread_id:
            return
        try:
            thread = self.call("thread/read", {"threadId": self.thread_id}).get("thread") or {}
            self.cb.on_settings(
                {
                    "source": "thread/read",
                    "model": thread.get("model"),
                    "effort": thread.get("reasoningEffort"),
                }
            )
            if with_mode:
                result = self.call(
                    "thread/resume",
                    {"threadId": self.thread_id, "cwd": self.spec.cwd, "excludeTurns": True},
                )
                self.cb.on_settings(
                    {
                        "source": "thread/resume",
                        "approval": result.get("approvalPolicy"),
                        "sandbox": result.get("sandbox"),
                    }
                )
        except StructuredError as exc:
            self.info["settings_error"] = str(exc)

    def apply_settings(self, chosen: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        # Codex has no per-thread "set" request: overrides travel with the next turn/start.
        return {key: {"ok": True, "pending": True} for key in chosen}

    def load_history(self) -> None:
        if not self.thread_id:
            return
        try:
            turns = codex_read_turns(self.call, self.thread_id)
        except StructuredError as exc:
            self.conv.replace_history([], "codex", f"无法读取 Codex 历史：{exc}")
            return
        self.conv.replace_history(codex_turn_items(turns), "codex", None)

    # --- JSON-RPC ---------------------------------------------------------------------------

    def call(
        self, method: str, params: Mapping[str, Any] | None, timeout: float = 30
    ) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            rid = self._next_id
            event = threading.Event()
            box: dict[str, Any] = {}
            self._waiters[rid] = (event, box)
        assert self.process is not None
        try:
            self.process.write({"id": rid, "method": method, "params": dict(params or {})})
        except OSError as exc:
            self._waiters.pop(rid, None)
            raise StructuredError(f"{method}: {exc}") from None
        if not event.wait(timeout):
            self._waiters.pop(rid, None)
            raise StructuredError(f"{method} 超时")
        self._waiters.pop(rid, None)
        if "error" in box:
            err = box["error"]
            raise StructuredError(str(err.get("message") if isinstance(err, dict) else err))
        result = box.get("result")
        return result if isinstance(result, dict) else {}

    def _notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        assert self.process is not None
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = dict(params)
        self.process.write(message)

    def _respond(
        self, rid: Any, result: Mapping[str, Any] | None = None, error: str | None = None
    ) -> None:
        assert self.process is not None
        if error is not None:
            self.process.write({"id": rid, "error": {"code": -32000, "message": error}})
        else:
            self.process.write({"id": rid, "result": dict(result or {})})

    def _on_line(self, msg: dict[str, Any]) -> None:
        if "method" in msg and "id" in msg:
            self._server_request(msg["id"], str(msg["method"]), msg.get("params") or {})
        elif "method" in msg:
            method = str(msg["method"])
            params = msg.get("params") or {}
            self.translator.notification(method, params)
            if method == "turn/started":
                self.cb.on_turn_started()
                if self._confirm_after_turn:
                    threading.Thread(target=self.read_settings, args=(False,), daemon=True).start()
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                self.cb.on_activity({"event": "Stop", "status": turn.get("status")})
                self.cb.on_turn_finished()
                if self._confirm_after_turn:
                    self._confirm_after_turn = False
                    threading.Thread(target=self.read_settings, args=(True,), daemon=True).start()
            elif method == "model/rerouted":
                self.cb.on_settings(
                    {"source": "model/rerouted", "model": params.get("toModel"), "rerouted": True}
                )
            elif method == "item/started":
                item = params.get("item") or {}
                if item.get("type") in (
                    "commandExecution",
                    "fileChange",
                    "mcpToolCall",
                    "webSearch",
                ):
                    shown = self.conv.get(str(item.get("id"))) or {}
                    self.cb.on_activity(
                        {
                            "event": "PreToolUse",
                            "tool_name": shown.get("name"),
                            "tool_use_id": item.get("id"),
                            "summary": shown.get("title"),
                        }
                    )
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") in (
                    "commandExecution",
                    "fileChange",
                    "mcpToolCall",
                    "webSearch",
                ):
                    shown = self.conv.get(str(item.get("id"))) or {}
                    self.cb.on_activity(
                        {
                            "event": "PostToolUseFailure"
                            if shown.get("status") in ("failed", "declined")
                            else "PostToolUse",
                            "tool_name": shown.get("name"),
                            "tool_use_id": item.get("id"),
                            "declined": shown.get("status") == "declined",
                        }
                    )
            elif method == "turn/diff/updated":
                self.cb.on_activity({"event": "DiffUpdated"})
        elif "id" in msg:
            waiter = self._waiters.get(msg["id"]) if isinstance(msg["id"], int) else None
            if waiter is not None:
                event, box = waiter
                if "error" in msg:
                    box["error"] = msg["error"]
                else:
                    box["result"] = msg.get("result")
                event.set()

    def _server_request(self, rid: Any, method: str, params: dict[str, Any]) -> None:
        key = str(rid)
        item = self.translator.server_request(key, method, params)
        if item is not None:
            self._server_requests[key] = (rid, method, params)
            self.cb.on_activity(
                {"event": "PermissionRequest", "tool_name": item["tool"], "summary": item["title"]}
            )
            return
        # Requests RepoBridge cannot answer are refused visibly, never silently approved.
        notice = {
            "mcpServer/elicitation/request": "MCP 服务器请求的表单格式 RepoBridge 无法显示；已拒绝",
            "item/tool/requestUserInput": "Codex 发来的提问没有可显示的问题；已回复空答案",
            "execCommandApproval": "收到旧版命令审批请求；已拒绝",
            "applyPatchApproval": "收到旧版补丁审批请求；已拒绝",
        }.get(method, f"收到不支持的请求 {method}；已拒绝")
        self.conv.upsert({"id": f"n:req:{key}", "type": "notice", "level": "warn", "text": notice})
        if method == "mcpServer/elicitation/request":
            self._respond(rid, {"action": "decline"})
        elif method == "item/tool/requestUserInput":
            self._respond(rid, {"answers": {}})
        elif method in ("execCommandApproval", "applyPatchApproval"):
            self._respond(rid, {"decision": "denied"})
        elif method == "item/tool/call":
            self._respond(rid, {"contentItems": [], "success": False})
        else:
            # Includes auth-token refresh: RepoBridge never supplies credentials.
            self._respond(rid, error=f"RepoBridge does not handle {method}")

    # --- user actions -----------------------------------------------------------------------

    def send(
        self,
        text: str,
        client_id: str,
        inputs: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        overrides: Mapping[str, Any] | None = None,
        display: str | None = None,
    ) -> None:
        turn = _CodexTurn(text, client_id, list(inputs or []), dict(overrides or {}))
        with self._lock:
            if self.busy:
                raise StructuredError("上一轮还在进行；可以先停止它")
            self.translator.begin_turn(client_id, text if display is None else display, attachments)
            if not self.ready.is_set():
                self.queue.append(turn)
                return
        self._start_turn(turn)

    def _start_turn(self, turn: _CodexTurn) -> None:
        text, client_id = turn.text, turn.client_id
        self.cb.on_activity({"event": "UserPromptSubmit", "prompt": text[:2000]})
        params: dict[str, Any] = {
            "threadId": self.thread_id,
            "input": ([{"type": "text", "text": text}] if text else []) + turn.inputs,
            "clientUserMessageId": client_id,
            **codex_turn_settings(turn.overrides),
        }
        if turn.overrides:
            self._confirm_after_turn = True

        def run() -> None:
            try:
                result = self.call("turn/start", params)
            except StructuredError as exc:
                if turn.overrides:
                    self.cb.on_settings({"source": "turn/start", "error": str(exc)})
                self.conv.upsert({"id": f"user:{client_id}", "status": "failed"})
                self.conv.upsert(
                    {
                        "id": f"n:send:{client_id}",
                        "type": "notice",
                        "level": "error",
                        "text": f"消息没有发送成功：{exc}",
                    }
                )
                self.conv.set_turn(None)
                self.cb.on_turn_finished()
                return
            started = result.get("turn") or {}
            if started.get("id") and not self.translator.turn_id:
                self.translator.turn_id = str(started["id"])

        threading.Thread(target=run, name="codex-turn", daemon=True).start()

    def interrupt(self) -> bool:
        with self._lock:
            turn_id = self.translator.turn_id
            if not self.busy or not turn_id:
                return False
            self.translator.interrupt_requested = True
        for pending in self.conv.pending_permissions():
            with contextlib.suppress(StructuredError):
                self.answer(pending["request_id"], "deny")
        threading.Thread(
            target=lambda: _quiet(
                lambda: self.call("turn/interrupt", {"threadId": self.thread_id, "turnId": turn_id})
            ),
            daemon=True,
        ).start()
        return True

    def answer(
        self, request_id: str, decision: str, answers: Mapping[str, str] | None = None
    ) -> None:
        with self._lock:
            entry = self._server_requests.pop(request_id, None)
        if entry is None:
            raise StructuredError("这个权限请求已经结束")
        rid, method, params = entry
        allowed = {
            "item/tool/requestUserInput": ("answer", "deny"),
            "mcpServer/elicitation/request": ("accept", "decline", "cancel"),
        }.get(method, ("allow", "allow_session", "deny"))
        if decision not in allowed:
            with self._lock:
                self._server_requests[request_id] = entry
            raise StructuredError(f"unknown decision {decision!r}")
        try:
            response = codex_permission_response(method, decision, params, answers)
        except ValueError as exc:
            with self._lock:
                self._server_requests[request_id] = entry
            raise StructuredError(str(exc)) from None
        self._respond(rid, response)
        label = "denied" if decision in ("deny", "decline", "cancel") else "allowed"
        self.conv.upsert({"id": f"perm:{request_id}", "status": label, "decision": decision})
        self.cb.on_activity({"event": "PermissionDecision", "decision": decision})


@dataclass
class _CodexTurn:
    text: str
    client_id: str
    inputs: list[dict[str, Any]]
    overrides: dict[str, Any]


def codex_thread_settings(chosen: Mapping[str, Any]) -> dict[str, Any]:
    """``thread/start`` / ``thread/resume`` parameters for the chosen settings."""
    out: dict[str, Any] = {}
    if chosen.get("model"):
        out["model"] = chosen["model"]
    if chosen.get("effort"):
        out["config"] = {"model_reasoning_effort": chosen["effort"]}
    mode = CODEX_MODE_BY_ID.get(str(chosen.get("mode") or ""))
    if mode is not None:
        out["approvalPolicy"] = mode["approval"]
        out["sandbox"] = mode["sandbox_mode"]
    return out


def codex_turn_settings(chosen: Mapping[str, Any]) -> dict[str, Any]:
    """``turn/start`` overrides (they apply to this turn and the ones after it)."""
    out: dict[str, Any] = {}
    if chosen.get("model"):
        out["model"] = chosen["model"]
    if chosen.get("effort"):
        out["effort"] = chosen["effort"]
    mode = CODEX_MODE_BY_ID.get(str(chosen.get("mode") or ""))
    if mode is not None:
        out["approvalPolicy"] = mode["approval"]
        out["sandboxPolicy"] = dict(mode["sandbox"])
    return out


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _quiet(fn: Callable[[], Any]) -> None:
    with contextlib.suppress(StructuredError, OSError):
        fn()


def codex_read_turns(
    call: Callable[..., dict[str, Any]], thread_id: str, max_pages: int = 20
) -> list[dict[str, Any]]:
    """Read a thread's turns through the app-server (paginated store first, legacy fallback)."""
    turns: list[dict[str, Any]] = []
    cursor: str | None = None
    try:
        for _ in range(max_pages):
            params: dict[str, Any] = {
                "threadId": thread_id,
                "itemsView": "full",
                "sortDirection": "asc",
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor
            page = call("thread/turns/list", params)
            turns.extend(t for t in page.get("data") or [] if isinstance(t, dict))
            cursor = page.get("nextCursor")
            if not cursor:
                return turns
        return turns
    except StructuredError as first:
        if "not materialized" in str(first):
            return []
        try:
            thread = (
                call("thread/read", {"threadId": thread_id, "includeTurns": True}).get("thread")
                or {}
            )
        except StructuredError:
            raise first from None
        return [t for t in thread.get("turns") or [] if isinstance(t, dict)]


def read_codex_history(
    binary: str, env: Mapping[str, str], cwd: str, thread_id: str, run_dir: Path
) -> list[dict[str, Any]]:
    """Read history with a short-lived app-server: no thread is resumed, no turn is started."""
    spec = StructuredSpec(
        argv=codex_argv(binary),
        env=dict(env),
        cwd=cwd,
        native_session_id=thread_id,
        binding="confirmed",
        stripped_env=[],
        mode="read",
        title="",
    )
    conv = Conversation()
    done = threading.Event()
    reader = CodexAppServerSession(
        spec,
        run_dir,
        conv,
        SessionCallbacks(
            on_native_id=lambda *_: None,
            on_turn_started=lambda: None,
            on_turn_finished=lambda: None,
            on_ready=lambda: None,
            on_activity=lambda _r: None,
            on_exit=lambda _i: done.set(),
        ),
    )
    reader.process = PipeProcess(
        spec, run_dir / "history-stderr.log", on_line=reader._on_line, on_exit=reader._exit
    )
    reader.process.start()
    try:
        reader.call(
            "initialize",
            {
                "clientInfo": {
                    "name": "repobridge",
                    "title": "RepoBridge",
                    "version": CLIENT_VERSION,
                }
            },
            timeout=20,
        )
        reader._notify("initialized", None)
        return codex_turn_items(codex_read_turns(reader.call, thread_id))
    finally:
        reader.process.terminate(1.0)


def probe_catalog(
    kind: str, binary: str, cwd: str, base_env: Mapping[str, str], run_dir: Path
) -> dict[str, Any]:
    """Ask a short-lived CLI process for its model catalog: no session, no turn, no model call.

    Claude Code: ``initialize`` on a ``-p`` stream-json process with ``--no-session-persistence``
    (nothing is written to its session store). Codex: ``model/list`` and
    ``configRequirements/read`` on an app-server that starts no thread.
    """
    env, stripped = session_env(base_env)
    captured: dict[str, Any] = {}
    done = threading.Event()

    def on_catalog(payload: dict[str, Any]) -> None:
        captured.update(payload)
        done.set()

    callbacks = SessionCallbacks(
        on_native_id=lambda *_: None,
        on_turn_started=lambda: None,
        on_turn_finished=lambda: None,
        on_ready=lambda: None,
        on_activity=lambda _r: None,
        on_exit=lambda _i: done.set(),
        on_catalog=on_catalog,
    )
    if kind == CLAUDE:
        argv = [
            binary,
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
        ]
        spec = StructuredSpec(argv, env, cwd, None, "none", stripped, "probe", "")
        claude = ClaudeStreamSession(spec, run_dir, Conversation(), callbacks)
        claude.start()
        try:
            if not claude.wait_initialized(40):
                raise StructuredError("Claude Code 没有回应 initialize")
            if claude.info.get("init_error"):
                raise StructuredError(str(claude.info["init_error"]))
        finally:
            claude.terminate(2.0)
        return captured
    spec = StructuredSpec(codex_argv(binary), env, cwd, None, "none", stripped, "probe", "")
    codex = CodexAppServerSession(spec, run_dir, Conversation(), callbacks)
    codex.process = PipeProcess(
        spec, run_dir / "catalog-stderr.log", on_line=codex._on_line, on_exit=codex._exit
    )
    codex.process.start()
    try:
        client = {"name": "repobridge", "title": "RepoBridge", "version": CLIENT_VERSION}
        codex.call("initialize", {"clientInfo": client}, timeout=20)
        codex._notify("initialized", None)
        codex._load_catalog()
    finally:
        codex.process.terminate(1.0)
    if captured.get("error"):
        raise StructuredError(str(captured["error"]))
    return captured


def read_claude_history(
    env: Mapping[str, str], session_id: str
) -> tuple[list[dict[str, Any]], str | None]:
    path = find_claude_transcript(env, session_id)
    if path is None:
        return [], None
    return claude_transcript_items(path), str(path)
