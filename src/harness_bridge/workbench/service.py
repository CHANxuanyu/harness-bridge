"""Workbench service: projects, native sessions, runs, side-channel events, handoffs.

Thread model: HTTP handler threads call into this object; each live run has one reader thread
(PTY or JSON lines); a notifier thread coalesces state snapshots for subscribers. SQLite is the
authority for projects/sessions/runs/events; live processes exist only for runs this App spawned.

A session has one harness for life. Its *view* (terminal or conversation) only chooses how the
App connects to that same native session: the interactive CLI on a PTY, or the harness's own
structured protocol. Changing the view releases one connection at a safe point and reconnects with
the native resume; it never sends a message, never forks, and never runs two writers.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from harness_bridge import runtime_env
from harness_bridge.errors import BridgeError
from harness_bridge.observability import Observability
from harness_bridge.observability.recorder import error_fields
from harness_bridge.workbench import changes, controls, desktop_apps, handoff
from harness_bridge.workbench.conversation import Conversation
from harness_bridge.workbench.harness import (
    CLAUDE,
    CODEX,
    HARNESSES,
    LABELS,
    HarnessInfo,
    WorkbenchConfig,
    build_launch,
    environment_refusal,
    native_argv,
    probe,
    session_env,
    stripped_billing_env,
)
from harness_bridge.workbench.native_history import NativeHistory, page_limit
from harness_bridge.workbench.prefs import Prefs
from harness_bridge.workbench.pty_host import (
    ExitInfo,
    JsonlTail,
    OscScanner,
    OutputBuffer,
    PtyProcess,
    alive_with_birth,
    group_members,
    process_birth,
    read_log_tail,
    strip_ansi_tail,
)
from harness_bridge.workbench.store import (
    SCHEMA_REVISION,
    ExternalHeld,
    WorkbenchStore,
    WorkdirBusy,
)
from harness_bridge.workbench.store import now as _now
from harness_bridge.workbench.structured import (
    ClaudeStreamSession,
    CodexAppServerSession,
    SessionCallbacks,
    StructuredError,
    StructuredSession,
    build_structured,
    probe_catalog,
    read_claude_history,
    read_codex_history,
)

_PERMISSION_WORDS = ("permission", "approval", "approve", "权限", "批准")
_CLEARS_ATTENTION = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop", "UserPromptSubmit"}
VIEWS = ("terminal", "conversation")
MAX_MESSAGE = 100_000
MAX_ATTACHMENTS = 10
IMAGE_LIMIT = {CLAUDE: 5 << 20, CODEX: 20 << 20}
FILE_LIMIT = 10 << 20
_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
FIELD_LABEL = {"model": "模型", "effort": "思考强度", "mode": "权限模式"}
# Which host reports may overrule a choice (a mismatch there means the choice did not apply).
AUTHORITATIVE = {
    CLAUDE: {
        "model": ("get_settings", "system/init"),
        "effort": ("get_settings",),
        "mode": ("control_response", "system/init"),
    },
    CODEX: {
        "model": ("thread/start", "thread/resume", "thread/read"),
        "effort": ("thread/start", "thread/resume", "thread/read"),
        "mode": ("thread/start", "thread/resume"),
    },
}

# Diagnostic step for a refused connect/resume, by stable reason.
_CONNECT_STEPS = {
    "directory_missing": "directory",
    "external_confirmation_required": "external_confirmation",
    "local_writer_busy": "admission",
    "unlinked": "link_check",
    "environment_changed": "link_check",
    "unsupported_source": "link_check",
    "native_identity_changed": "link_check",
    "project_archived": "link_check",
}


@dataclass
class LiveRun:
    run_id: str
    session_id: str
    harness: str
    run_dir: Path
    buffer: OutputBuffer
    tail: JsonlTail
    osc: OscScanner = field(default_factory=OscScanner)
    process: PtyProcess | None = None
    stop_requested: bool = False
    attention: dict[str, Any] | None = None
    # starting → running (output seen) → working (turn) / waiting (ready for input)
    phase: str = "starting"
    transport: str = "pty"
    structured: StructuredSession | None = None
    conv: Conversation | None = None
    release_reason: str | None = None
    # Set once the settings chosen for this session were sent and read back after connecting.
    settings_ready: threading.Event = field(default_factory=threading.Event)
    apply_lock: threading.Lock = field(default_factory=threading.Lock)
    turn_model: str | None = None
    # Choices the harness refused while connecting; the next send reports them instead of
    # going out with the previous value.
    connect_failures: list[str] = field(default_factory=list)
    applying: bool = False

    def terminate(self, grace: float) -> None:
        if self.structured is not None:
            if self.structured.busy:
                # End the turn first so the native session records it as interrupted.
                with contextlib.suppress(StructuredError, OSError):
                    self.structured.interrupt()
                deadline = time.monotonic() + grace
                while self.structured.busy and time.monotonic() < deadline:
                    time.sleep(0.05)
            self.structured.terminate(grace)
        elif self.process is not None:
            self.process.terminate(grace)

    @property
    def pid(self) -> int:
        if self.structured is not None:
            return self.structured.pid
        assert self.process is not None
        return self.process.pid


class Subscriber:
    def __init__(self) -> None:
        self.queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=4000)
        self.overflowed = False


class Workbench:
    def __init__(
        self,
        state_dir: Path,
        *,
        config: WorkbenchConfig | None = None,
        base_env: Mapping[str, str] | None = None,
        stop_grace: float = 3.0,
    ) -> None:
        self.state_dir = state_dir
        self.base_env = dict(os.environ if base_env is None else base_env)
        # Environment boundary first: a refused dev/test start creates and opens nothing.
        self.profile, self.config = runtime_env.workbench_profile(
            state_dir, config or WorkbenchConfig(), self.base_env
        )
        root = self.profile.test_root
        self._root_lock = runtime_env.TestRootLock(root) if root is not None else None
        try:
            self.root = state_dir / "workbench"
            (self.root / "runs").mkdir(parents=True, exist_ok=True)
            (self.root / "handoffs").mkdir(parents=True, exist_ok=True)
            (self.root / "history").mkdir(parents=True, exist_ok=True)
            (self.root / "attachments").mkdir(parents=True, exist_ok=True)
            self.store = WorkbenchStore(state_dir / "workbench.sqlite3")
        except BaseException:
            if self._root_lock is not None:
                self._root_lock.release()
            raise
        try:
            self.obs = Observability(state_dir, env_name=self.profile.name, env=self.base_env)
        except Exception:  # diagnostics must never stop the App from starting
            off = {"HBRIDGE_DIAGNOSTICS": "0", "HBRIDGE_PRODUCT_EVENTS": "0"}
            self.obs = Observability(state_dir, env_name=self.profile.name, env=off)
        self.prefs = Prefs(self.root / "prefs.json")
        # Native window hooks (title, appearance, folder picker), set by ``hbridge app`` when a
        # pywebview window exists. Called from request threads; never from page JavaScript eval.
        self.native: dict[str, Callable[..., Any]] = {}
        # Development-only window snapshot/reload (``hbridge app --dev-snapshot-dir``).
        self.dev_snapshot: Callable[[str], dict[str, Any]] | None = None
        self.dev_reload: Callable[[str], None] | None = None
        self.dev_resize: Callable[[int, int], None] | None = None
        self.stop_grace = stop_grace
        self._lock = threading.RLock()
        self._live: dict[str, LiveRun] = {}
        self._subs: set[Subscriber] = set()
        self._harnesses: dict[str, HarnessInfo] = {}
        self._apps: dict[str, desktop_apps.DesktopApp] | None = None
        self._history_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.native_history = NativeHistory(self)
        self._session_locks: dict[str, threading.RLock] = {}
        self._settings_lock = threading.RLock()
        self._catalogs: dict[str, dict[str, Any]] = {}
        self._catalog_probes: set[str] = set()
        self._file_index: dict[str, tuple[float, list[str]]] = {}
        self._dirty = threading.Event()
        self._closing = threading.Event()
        self.reconcile()
        build = self.obs.build
        self.obs.record(
            "app.start",
            env_source=self.profile.source,
            native_env=self.profile.native_env,
            code_source=build["code_source"],
            code_dirty=build["code_dirty"],
            schema=self.store.schema_revision(),
            schema_expected=SCHEMA_REVISION,
            python=build["python"],
            os=build["os"],
            diagnostics=self.obs.diagnostics_enabled,
            product_events=self.obs.product_enabled,
            alias_stable=self.obs.alias_stable,
        )
        self._notifier = threading.Thread(target=self._notify_loop, name="wb-notify", daemon=True)
        self._notifier.start()

    # --- subscriptions --------------------------------------------------------------------------

    def subscribe(self) -> Subscriber:
        sub = Subscriber()
        with self._lock:
            self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subs.discard(sub)

    def _publish(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            try:
                sub.queue.put_nowait((kind, data))
            except queue.Full:
                sub.overflowed = True
                self.unsubscribe(sub)

    def _changed(self) -> None:
        self._dirty.set()

    def _notify_loop(self) -> None:
        while not self._closing.is_set():
            if not self._dirty.wait(0.5):
                continue
            self._closing.wait(0.08)
            self._dirty.clear()
            try:
                snap = self.snapshot()
            except Exception:  # noqa: S112 - a failed snapshot is retried on the next change
                continue
            self._publish("state", snap)

    # --- harnesses ------------------------------------------------------------------------------

    def harnesses(self, refresh: bool = False) -> dict[str, HarnessInfo]:
        with self._lock:
            if refresh or not self._harnesses:
                self._harnesses = {k: probe(k, self.config, self.base_env) for k in HARNESSES}
                self._apps = None
            return dict(self._harnesses)

    def desktop_apps(self) -> dict[str, desktop_apps.DesktopApp]:
        with self._lock:
            if self._apps is None:
                self._apps = desktop_apps.find_apps(self.config.app_dirs)
            return dict(self._apps)

    # --- snapshot -------------------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        latest = self.store.latest_runs()
        with self._lock:
            live = dict(self._live)
        projects = []
        for project in self.store.list_projects():
            sessions = [
                self._session_view(s, latest.get(s["session_id"]), live.get(s["session_id"]))
                for s in self.store.list_sessions(project["project_id"], include_archived=True)
            ]
            projects.append(
                {
                    **project,
                    "branch": changes.quick_branch(project["root_path"]),
                    "exists": os.path.isdir(project["root_path"]),
                    "sessions": sessions,
                    "handoffs": self.store.list_handoffs(project["project_id"]),
                }
            )
        return {
            "projects": projects,
            "prefs": self.prefs.get(),
            "home": self.base_env.get("HOME") or os.path.expanduser("~"),
            "native": sorted(self.native),
            "dev": self.dev_snapshot is not None,
            "harnesses": [h.to_dict() for h in self.harnesses().values()],
            "desktop_apps": {
                k: {"label": a.label, "version": a.version} for k, a in self.desktop_apps().items()
            },
            "catalogs": {h: self._catalog_summary(h) for h in HARNESSES},
            "environment": {
                "refusal": environment_refusal(self.base_env),
                "stripped_env": stripped_billing_env(self.base_env),
            },
        }

    def _session_view(
        self,
        session: dict[str, Any],
        run: dict[str, Any] | None,
        live: LiveRun | None,
    ) -> dict[str, Any]:
        status = "new" if run is None else run["status"]
        active = status in ("starting", "running")
        resumable = self._can_resume(session)
        native_link = self._native_link_view(session)
        raw_external = session.get("external_json")
        external = _loads(raw_external) if isinstance(raw_external, str) else None
        view = {
            **{k: v for k, v in session.items() if k not in ("external_json", "settings_json")},
            "harness_label": LABELS.get(session["harness"], session["harness"]),
            "status": status,
            "active": active,
            "attached": live is not None,
            "stopping": live.stop_requested if live else False,
            "attention": live.attention if live else None,
            "phase": live.phase if live else None,
            "transport": live.transport if live else (run or {}).get("transport"),
            "turn": live.conv.turn if live and live.conv is not None else None,
            "conn_info": _conn_info(live),
            "can_resume": (not active)
            and resumable
            and (native_link is None or native_link["resumable"]),
            "can_start_fresh": (not active)
            and session["turns_observed"] == 0
            and not self._has_submitted_delivery(session)
            and self.store.native_link(session["session_id"]) is None,
            "native_link": native_link,
            "external": external,
            "desktop": self._desktop_capability(session),
            "settings": self._settings_view(session, live),
            "run": None,
        }
        if run is not None:
            view["run"] = {
                k: run.get(k)
                for k in (
                    "run_id",
                    "seq",
                    "kind",
                    "status",
                    "pid",
                    "exit_code",
                    "exit_signal",
                    "exit_confirmed",
                    "failure",
                    "output_tail",
                    "started_at",
                    "ended_at",
                    "transport",
                )
            }
        return view

    def _desktop_capability(self, session: Mapping[str, Any]) -> dict[str, Any]:
        info = self.harnesses().get(session["harness"])
        return desktop_apps.capability(
            session,
            apps=self.desktop_apps(),
            cli_version=info.version if info else None,
            native_linked=bool(
                self.store.native_link(session["session_id"]) and self._can_resume(session)
            ),
        )

    def session_detail(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        runs = self.store.list_runs(session_id)
        with self._lock:
            live = self._live.get(session_id)
        info = dict(live.structured.info) if live and live.structured else {}
        return {
            "session": {
                k: v for k, v in session.items() if k not in ("external_json", "settings_json")
            },
            "structured_info": {k: v for k, v in info.items() if k != "mode_noticed"},
            "runs": [
                {k: v for k, v in r.items() if k not in ("argv_json", "stripped_env_json")}
                | {"stripped_env": _loads(r["stripped_env_json"]), "argv": _loads(r["argv_json"])}
                for r in runs
            ],
            "handoffs_in": [
                h for h in self.store.list_handoffs() if h["to_session_id"] == session_id
            ],
            "handoffs_out": [
                h for h in self.store.list_handoffs() if h["from_session_id"] == session_id
            ],
        }

    # --- projects -------------------------------------------------------------------------------

    def add_project(self, path: str, name: str | None = None) -> dict[str, Any]:
        raw = os.path.expanduser(path.strip())
        if not raw or not os.path.isabs(raw):
            raise BridgeError("INVALID_INPUT", "项目路径必须是绝对路径")
        real = os.path.realpath(raw)
        if not os.path.isdir(real):
            raise BridgeError("INVALID_INPUT", f"目录不存在：{raw}")
        try:
            info = changes.repo_info(real)
        except BridgeError:
            info = None
        if info is not None and os.path.realpath(info["toplevel"]) != real:
            raise BridgeError(
                "INVALID_INPUT",
                f"该目录位于 Git 仓库 {info['toplevel']} 之内；请添加仓库顶层目录",
            )
        project, created = self.store.add_project(
            (name or "").strip() or os.path.basename(real) or real, real
        )
        self._changed()
        return {**project, "created": created}

    def archive_project(self, project_id: str) -> None:
        self._project(project_id)
        if any(
            r["status"] in ("starting", "running")
            for s in self.store.list_sessions(project_id)
            for r in self.store.list_runs(s["session_id"])[-1:]
        ):
            raise BridgeError("STATE_CONFLICT", "项目中仍有运行中的会话；请先停止")
        self.store.archive_project(project_id)
        self._changed()

    # --- sessions -------------------------------------------------------------------------------

    def create_session(
        self,
        project_id: str,
        harness: str,
        *,
        title: str | None = None,
        start: bool = True,
        handoff_from: str | None = None,
        view_mode: str | None = None,
    ) -> dict[str, Any]:
        project = self._project(project_id)
        if harness not in HARNESSES:
            raise BridgeError("INVALID_INPUT", f"unknown harness {harness!r}")
        view = view_mode or self.prefs.get().get("default_view", "terminal")
        if view not in VIEWS:
            raise BridgeError("INVALID_INPUT", f"unknown view {view!r}")
        workdir = project["root_path"]
        if start:
            self._preflight(harness)
            self._ensure_workdir_free(workdir)
        count = sum(1 for s in self.store.list_sessions(project_id) if s["harness"] == harness)
        session = self.store.create_session(
            project_id=project_id,
            harness=harness,
            title=(title or "").strip()[:120] or f"{LABELS[harness]} {count + 1}",
            workdir=workdir,
            native_session_id=str(uuid.uuid4()) if harness == CLAUDE else None,
            native_binding="preassigned" if harness == CLAUDE else "pending",
            handoff_from=handoff_from,
            view_mode=view,
        )
        self.store.add_event(
            session["session_id"], None, "session_created", {"harness": harness, "view": view}
        )
        self._changed()
        if start:
            self.start_run(session["session_id"], "new")
        return self._session(session["session_id"])

    def _native_link_view(self, session: Mapping[str, Any]) -> dict[str, Any] | None:
        link = self.store.native_link(session["session_id"])
        if link is None:
            return None
        meta = json.loads(link["metadata_json"])
        directory = "available" if Path(session["workdir"]).is_dir() else "missing"
        reason = meta["resume_reason"]
        if not link["linked"]:
            reason = "unlinked"
        elif meta["environment"] != self.native_history.environment(session["harness"]):
            reason = "environment_changed"
        elif directory == "missing":
            reason = "directory_missing"
        return {
            "linked": bool(link["linked"]),
            "environment": meta["environment"],
            "source": meta["source"],
            "resumable": bool(meta["resumable"] and not reason),
            "resume_reason": reason,
            "directory_state": directory,
        }

    def link_session(self, candidate_id: str, view_mode: str = "conversation") -> dict[str, Any]:
        try:
            result = self._link_session(candidate_id, view_mode)
        except BridgeError as err:
            self.obs.record("session.link", outcome="refused", **error_fields(err))
            raise
        detail = result["session"]["session"]
        self.obs.record(
            "session.link",
            project=detail.get("project_id"),
            session=detail.get("session_id"),
            outcome="created"
            if result["created"]
            else ("relinked" if result["relinked"] else "duplicate"),
            harness=detail.get("harness"),
        )
        return result

    def _link_session(self, candidate_id: str, view_mode: str) -> dict[str, Any]:
        if view_mode not in VIEWS:
            raise BridgeError("INVALID_INPUT", "Invalid view mode")
        meta = self.native_history.candidate(candidate_id)
        result = self.native_history.history(meta)
        if result["history"]["error"]:
            raise BridgeError(
                "PREFLIGHT_FAILED",
                result["history"]["error"],
                details={
                    "reason": result["history"].get("reason", "native_read_failed"),
                    "capability_unsupported": result["history"].get(
                        "capability_unsupported", False
                    ),
                },
            )
        try:
            sid, created, relinked = self.store.link_native(meta["_project_id"], meta, view_mode)
        except ValueError as exc:
            raise BridgeError("STATE_CONFLICT", str(exc)) from None
        if created or relinked:
            self.store.add_event(sid, None, "native_linked", {"relinked": relinked})
            self._changed()
        return {"session": self.session_detail(sid), "created": created, "relinked": relinked}

    def unlink_session(self, session_id: str) -> dict[str, Any]:
        try:
            result = self._unlink_session(session_id)
        except BridgeError as err:
            self.obs.record(
                "session.unlink",
                session=session_id,
                outcome="refused",
                harness=self._harness_of(session_id),
                **error_fields(err),
            )
            raise
        self.obs.record(
            "session.unlink", session=session_id, outcome="ok", harness=self._harness_of(session_id)
        )
        return result

    def _harness_of(self, session_id: str) -> str | None:
        try:
            session = self.store.get_session(session_id)
        except Exception:
            return None
        return session["harness"] if session else None

    def _unlink_session(self, session_id: str) -> dict[str, Any]:
        self._session(session_id)
        link = self.store.native_link(session_id)
        if link is None:
            raise BridgeError(
                "STATE_CONFLICT", "This session is not an existing-session association"
            )
        if link["linked"]:
            with self._session_lock(session_id):
                try:
                    self.store.unlink_native(session_id)
                except WorkdirBusy as busy:
                    raise self._busy_error(busy) from None
                except ExternalHeld as held:
                    raise BridgeError(
                        "STATE_CONFLICT",
                        "请先确认外部使用已结束，再移除这个关联。",
                        details={
                            "reason": "external_confirmation_required",
                            "external": held.external,
                        },
                    ) from None
                self.store.add_event(session_id, None, "native_unlinked", {})
                self._changed()
        return {"session_id": session_id, "unlinked": True, "native_history_preserved": True}

    def _check_link(self, session: Mapping[str, Any], *, resume: bool = False) -> None:
        link = self.store.native_link(session["session_id"])
        if not link:
            return
        if not link["linked"]:
            raise BridgeError(
                "STATE_CONFLICT", "关联已移除，请重新添加后再使用。", details={"reason": "unlinked"}
            )
        meta = json.loads(link["metadata_json"])
        if meta["environment"] != self.native_history.environment(session["harness"]):
            raise BridgeError(
                "STATE_CONFLICT",
                "原生存储位置已变化，请切回原来的存储环境。",
                details={"reason": "environment_changed"},
            )
        if session["native_session_id"] != link["native_session_id"]:
            raise BridgeError(
                "STATE_CONFLICT",
                "原生会话 ID 与关联记录不一致。",
                details={"reason": "native_identity_changed"},
            )
        if resume and not meta["resumable"]:
            raise BridgeError(
                "PREFLIGHT_FAILED",
                "这个来源只支持查看，不能在本机恢复。",
                details={"reason": "unsupported_source", "capability_unsupported": True},
            )

    def rename_session(self, session_id: str, title: str) -> None:
        self._session(session_id)
        title = title.strip()[:120]
        if not title:
            raise BridgeError("INVALID_INPUT", "标题不能为空")
        self.store.rename_session(session_id, title)
        self._changed()

    def archive_session(self, session_id: str) -> None:
        self._session(session_id)
        try:
            self.store.archive_session(session_id)
        except ValueError as exc:
            raise BridgeError("STATE_CONFLICT", "会话仍在运行；请先停止") from exc
        self._changed()

    def unarchive_session(self, session_id: str) -> None:
        self._session(session_id)
        self.store.unarchive_session(session_id)
        self._changed()

    def set_prefs(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        values = self.prefs.update(changes)
        self._changed()
        return values

    def native_call(self, name: str, *args: Any) -> Any:
        hook = self.native.get(name)
        if hook is None:
            raise BridgeError("NOT_FOUND", "no native window is attached")
        return hook(*args)

    def reveal_project(self, project_id: str) -> None:
        """Open the project folder in Finder (or the desktop's file manager) on user request."""
        root = self._project(project_id)["root_path"]
        if not os.path.isdir(root):
            raise BridgeError("NOT_FOUND", f"目录不存在：{root}")
        opener = ["open", "--", root] if sys.platform == "darwin" else ["xdg-open", root]
        try:
            subprocess.run(opener, check=False, timeout=10, capture_output=True)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BridgeError("EXECUTOR_ERROR", f"无法打开文件夹：{type(exc).__name__}") from None

    def start_run(
        self, session_id: str, kind: str, *, confirm_external: bool = False
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            with self._session_lock(session_id):
                run = self._start_run_locked(session_id, kind, confirm_external=confirm_external)
        except BridgeError as err:
            self._observe_connect(session_id, kind, started, error=err)
            raise
        self._observe_connect(session_id, kind, started, run=run)
        return run

    def _observe_connect(
        self,
        session_id: str,
        kind: str,
        started: float,
        *,
        run: Mapping[str, Any] | None = None,
        error: BridgeError | None = None,
    ) -> None:
        """Diagnostics only; never changes the start result."""
        try:
            session = self.store.get_session(session_id) or {}
            fields: dict[str, Any] = {}
            if error is not None:
                fields = error_fields(error)
                step = _CONNECT_STEPS.get(str(fields.get("reason")))
                if step is None:
                    step = {"PREFLIGHT_FAILED": "preflight", "EXECUTOR_ERROR": "spawn"}.get(
                        error.code, "request"
                    )
                fields["step"] = step
            self.obs.record(
                "connect.start",
                session=session_id,
                run=(run or {}).get("run_id"),
                outcome="refused" if error is not None else "spawned",
                duration_ms=(time.monotonic() - started) * 1000,
                harness=session.get("harness"),
                kind=kind,
                transport=(run or {}).get("transport")
                or ("structured" if session.get("view_mode") == "conversation" else "pty"),
                linked=bool(self.store.native_link(session_id)) if session else None,
                **fields,
            )
        except Exception:
            self.obs.invalid += 1

    def _observe_ready(self, live: LiveRun) -> None:
        try:
            if not self.obs.first_ready(live.run_id):
                return
            run = self.store.get_run(live.run_id) or {}
            self.obs.record(
                "connect.ready",
                session=live.session_id,
                run=live.run_id,
                duration_ms=self.obs.run_elapsed(live.run_id),
                harness=live.harness,
                kind=run.get("kind"),
                transport=live.transport,
            )
        except Exception:
            self.obs.invalid += 1

    def _start_run_locked(
        self, session_id: str, kind: str, *, confirm_external: bool = False
    ) -> dict[str, Any]:
        session = self._session(session_id)
        self._check_link(session, resume=True)
        if kind == "new" and self.store.native_link(session_id):
            raise BridgeError(
                "STATE_CONFLICT",
                "已关联会话只能恢复原会话，不能重新创建。",
                details={"reason": "resume_required"},
            )
        self._check_external(session, confirm_external)
        harness = session["harness"]
        info = self._preflight(harness)
        assert info.binary is not None
        runs = self.store.list_runs(session_id)
        initial_prompt = None
        if kind == "resume":
            if not session["native_session_id"]:
                raise BridgeError("STATE_CONFLICT", "尚未观察到原生会话 ID，无法恢复")
            if not self._can_resume(session):
                raise BridgeError(
                    "STATE_CONFLICT",
                    f"这个 {LABELS[harness]} 会话还没有对话，原生 CLI 中没有可恢复的内容",
                )
        elif kind == "new":
            if session["turns_observed"] > 0 or self._has_submitted_delivery(session):
                raise BridgeError(
                    "STATE_CONFLICT",
                    "该会话已有原生对话或待确认的投递；请核对历史后使用恢复，或在项目中新建会话",
                    details={"reason": "resume_required"},
                )
            if not runs:
                initial_prompt = self._handoff_prompt(session_id)
        else:
            raise BridgeError("INVALID_INPUT", f"unknown run kind {kind!r}")
        workdir = session["workdir"]
        if not os.path.isdir(workdir):
            raise BridgeError(
                "PREFLIGHT_FAILED",
                f"工作目录不存在：{workdir}",
                details={"reason": "directory_missing", "capability_unsupported": False},
            )
        run_id = "run_" + uuid.uuid4().hex[:12]
        self.obs.note_run(run_id)
        run_dir = self.root / "runs" / run_id
        run_dir.mkdir(parents=True, mode=0o700)
        native_id = session["native_session_id"]
        if kind == "new" and runs:
            # Nothing was said in the earlier run(s): start a fresh native session for this slot.
            native_id = str(uuid.uuid4()) if harness == CLAUDE else None
            self.store.set_native(
                session_id, native_id, "preassigned" if harness == CLAUDE else "pending"
            )
        if session["view_mode"] == "conversation":
            return self._start_structured(
                session, kind, run_id, run_dir, info.binary, native_id, initial_prompt
            )
        spec = build_launch(
            harness,
            info.binary,
            mode=kind,
            workdir=workdir,
            title=session["title"],
            native_session_id=native_id,
            initial_prompt=initial_prompt,
            run_dir=run_dir,
            config=self.config,
            base_env=self.base_env,
            settings=self._settings_of(session)["chosen"],
        )
        self._admit(
            run_id, session_id, kind, workdir, native_argv(spec), spec.stripped_env, run_dir
        )
        live = LiveRun(
            run_id=run_id,
            session_id=session_id,
            harness=harness,
            run_dir=run_dir,
            buffer=OutputBuffer(run_dir / "output.log"),
            tail=JsonlTail(run_dir / "events.jsonl"),
        )
        process = PtyProcess(
            spec,
            on_output=lambda data: self._on_output(live, data),
            on_tick=lambda: self._on_tick(live),
            on_exit=lambda info: self._on_exit(live, info),
        )
        live.process = process
        with self._lock:
            self._live[session_id] = live
        try:
            process.start()
        except OSError as exc:
            self._launch_failed(live, exc)
        self.store.mark_running(
            run_id, pid=process.pid, pgid=process.pid, birth=process_birth(process.pid)
        )
        self.store.add_event(
            session_id,
            run_id,
            "run_started",
            {
                "kind": kind,
                "transport": "pty",
                "argv": native_argv(spec),
                "stripped_env": spec.stripped_env,
                "native_session_id": spec.native_session_id,
                "handoff_prompt": initial_prompt is not None,
            },
        )
        self._settings_disconnected(session_id, launched=True)
        self._changed()
        return self.store.get_run(run_id) or {}

    def _admit(
        self,
        run_id: str,
        session_id: str,
        kind: str,
        workdir: str,
        argv: list[str],
        stripped: list[str],
        run_dir: Path,
        transport: str = "pty",
    ) -> None:
        try:
            self.store.begin_run(
                run_id=run_id,
                session_id=session_id,
                kind=kind,
                workdir=workdir,
                argv=argv,
                stripped_env=stripped,
                transport=transport,
            )
        except WorkdirBusy as busy:
            shutil.rmtree(run_dir, ignore_errors=True)
            self.store.add_event(
                session_id, None, "writer_refused", {"busy_session_id": busy.session_id}
            )
            raise self._busy_error(busy) from None
        except ValueError as exc:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise BridgeError("STATE_CONFLICT", str(exc)) from None

    def _launch_failed(self, live: LiveRun, exc: OSError) -> NoReturn:
        with self._lock:
            self._live.pop(live.session_id, None)
        live.buffer.close()
        failure = f"无法启动 {LABELS[live.harness]}：{exc.strerror or type(exc).__name__}"
        self.store.finish_run(live.run_id, status="failed", failure=failure)
        self.store.add_event(live.session_id, live.run_id, "run_failed", {"failure": failure})
        self._changed()
        raise BridgeError("EXECUTOR_ERROR", failure) from None

    def _start_structured(
        self,
        session: dict[str, Any],
        kind: str,
        run_id: str,
        run_dir: Path,
        binary: str,
        native_id: str | None,
        initial_prompt: str | None,
    ) -> dict[str, Any]:
        sid = session["session_id"]
        harness = session["harness"]
        spec = build_structured(
            harness,
            binary,
            mode=kind,
            workdir=session["workdir"],
            title=session["title"],
            native_session_id=native_id,
            base_env=self.base_env,
        )
        self._admit(
            run_id,
            sid,
            kind,
            session["workdir"],
            spec.argv,
            spec.stripped_env,
            run_dir,
            "structured",
        )
        live = LiveRun(
            run_id=run_id,
            session_id=sid,
            harness=harness,
            run_dir=run_dir,
            buffer=OutputBuffer(run_dir / "output.log"),
            tail=JsonlTail(run_dir / "events.jsonl"),
            transport="structured",
        )
        conv = Conversation(
            emit=lambda op: self._publish("conv", {"session_id": sid, "run_id": run_id, **op})
        )
        live.conv = conv
        callbacks = SessionCallbacks(
            on_native_id=lambda native, binding: self._structured_native(live, native, binding),
            on_turn_started=lambda: self._structured_turn(live, True),
            on_turn_finished=lambda: self._structured_turn(live, False),
            on_ready=lambda: self._structured_ready(live),
            on_activity=lambda record: self._record(live, {"source": "structured", **record}),
            on_exit=lambda info: self._on_exit(live, info),
            on_fatal=lambda message: self._structured_fatal(live, message),
            on_settings=lambda report: self._on_settings(live, report),
            on_catalog=lambda payload: self._store_catalog(harness, payload),
            on_delivery=lambda record: self._record_delivery(live, record),
        )
        chosen = dict(self._settings_of(session)["chosen"])
        structured: StructuredSession
        if harness == CLAUDE:
            structured = ClaudeStreamSession(spec, run_dir, conv, callbacks)
        else:
            structured = CodexAppServerSession(spec, run_dir, conv, callbacks)
            # Codex takes the choices as thread/start or thread/resume parameters.
            structured.connect_settings = chosen
            if chosen:
                self._mark_fields(sid, list(chosen), "applying")
            live.settings_ready.set()
        live.structured = structured
        # History first (the native store), so the view shows the same session immediately.
        if kind == "resume" and harness == CLAUDE and native_id:
            if self.store.native_link(sid):
                history = self._history(session, True)
                items, path = (
                    history["items"],
                    "linked" if not history["history"]["error"] else None,
                )
            else:
                items, path = read_claude_history(self._history_env(), native_id)
            conv.replace_history(
                items,
                "claude-transcript",
                None if path else "没有找到 Claude Code 的会话记录文件；只显示本次运行的内容",
            )
        with self._lock:
            self._live[sid] = live
        try:
            structured.start()
        except OSError as exc:
            self._launch_failed(live, exc)
        if harness == CLAUDE:
            threading.Thread(
                target=self._connect_settings, args=(live,), name="settings", daemon=True
            ).start()
        self.store.mark_running(
            run_id, pid=structured.pid, pgid=structured.pid, birth=process_birth(structured.pid)
        )
        self.store.add_event(
            sid,
            run_id,
            "run_started",
            {
                "kind": kind,
                "transport": "structured",
                "argv": spec.argv,
                "stripped_env": spec.stripped_env,
                "native_session_id": spec.native_session_id,
                "handoff_prompt": initial_prompt is not None,
            },
        )
        self._changed()
        if initial_prompt:
            # The user ticked "send the note as the first message" when creating the handoff.
            with contextlib.suppress(StructuredError, OSError):
                structured.send(initial_prompt, "handoff")
        return self.store.get_run(run_id) or {}

    def _history_env(self) -> dict[str, str]:
        env, _ = session_env(self.base_env)
        return env

    # --- structured callbacks -------------------------------------------------------------------

    def _structured_native(self, live: LiveRun, native: str, binding: str) -> None:
        session = self.store.get_session(live.session_id)
        if session is None:
            return
        current = session["native_session_id"]
        if native != current and self.store.native_link(live.session_id):
            self._structured_fatal(
                live,
                "Native resume returned a different session ID; association retained",
                "native_identity_changed",
            )
            return
        if native != current:
            self.store.set_native(live.session_id, native, binding)
            self.store.add_event(
                live.session_id,
                live.run_id,
                "native_session_changed" if current else "native_session_observed",
                {"from": current, "to": native, "via": "structured"},
            )
        elif session["native_binding"] != "confirmed":
            self.store.set_native(live.session_id, native, "confirmed")
        self._changed()

    def _structured_ready(self, live: LiveRun) -> None:
        if live.phase == "starting":
            live.phase = "waiting"
        self._observe_ready(live)
        self._changed()

    def _structured_turn(self, live: LiveRun, started: bool) -> None:
        if started:
            live.phase = "working"
            self.store.count_turn(live.session_id)
        else:
            live.phase = "waiting"
            live.attention = None
            self.obs.record(
                "turn.end", session=live.session_id, run=live.run_id, harness=live.harness
            )
            if live.conv is not None and live.turn_model:
                ends = [i for i in live.conv.items() if i["type"] == "turn_end"]
                if ends and not ends[-1].get("model"):
                    live.conv.upsert({"id": ends[-1]["id"], "model": live.turn_model})
            live.turn_model = None
            self._save_conversation(live)
            if live.harness == CLAUDE and self._pending_fields(live.session_id):
                # Choices made during the turn take effect now, before the next message.
                threading.Thread(target=self._apply_pending, args=(live,), daemon=True).start()
        self._changed()

    def _structured_fatal(
        self, live: LiveRun, message: str, cause: str = "native_protocol"
    ) -> None:
        self.obs.record(
            "connect.fatal",
            session=live.session_id,
            run=live.run_id,
            harness=live.harness,
            cause=cause,
            ready=self.obs.was_ready(live.run_id),
        )
        if live.conv is not None:
            live.conv.upsert({"id": "n:fatal", "type": "notice", "level": "error", "text": message})
        self.store.note_failure(live.run_id, message)
        live.stop_requested = False
        threading.Thread(target=live.terminate, args=(self.stop_grace,), daemon=True).start()

    def _save_conversation(self, live: LiveRun) -> None:
        if live.conv is None:
            return
        items = [i for i in live.conv.items() if not i.get("history")]
        path = live.run_dir / "conversation.json"
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass

    def _store_delivery(
        self,
        session_id: str,
        run_id: str,
        record: dict[str, Any],
        *,
        evidence: str,
        ended_only: bool = False,
    ) -> dict[str, Any]:
        """Persist a receipt exactly as before; observe a real state change afterwards."""
        before = self._delivery_state(session_id, record.get("client_id"))
        event = self.store.record_delivery(session_id, run_id, record, ended_only=ended_only)
        try:
            after = event["payload"]["delivery"]["state"]
            if after != before:
                self.obs.record(
                    "delivery.state",
                    level="warning" if after == "unknown" else "info",
                    session=session_id,
                    run=run_id,
                    msg=record.get("client_id"),
                    reason=event["payload"]["delivery"].get("reason"),
                    harness=self._harness_of(session_id),
                    from_state=before,
                    to_state=after,
                    evidence=evidence,
                    latency_ms=self.obs.message_latency(str(record.get("client_id"))),
                )
        except Exception:
            self.obs.invalid += 1
        return event

    def _delivery_state(self, session_id: str, client_id: Any) -> str | None:
        if not self.obs.sinks or not isinstance(client_id, str):
            return None
        try:
            record = self.store.message_deliveries(session_id).get(client_id)
            return record["delivery"]["state"] if record else None
        except Exception:
            return None

    def _record_delivery(self, live: LiveRun, record: dict[str, Any]) -> dict[str, Any]:
        event = self._store_delivery(
            live.session_id, live.run_id, record, evidence="native_protocol"
        )
        self._publish("activity", event)
        return dict(event["payload"])

    def _deliveries(self, session_id: str) -> dict[str, dict[str, Any]]:
        records = self.store.message_deliveries(session_id)
        for cid, record in records.items():
            state = record["delivery"]["state"]
            run = self.store.get_run(record["run_id"]) or {}
            if state in ("queued", "sending") and run.get("status") not in ("starting", "running"):
                state = "not_sent" if state == "queued" else "unknown"
                record.update(
                    status="failed" if state == "not_sent" else "unknown",
                    delivery={
                        "state": state,
                        "reason": "connection_ended",
                        "message": "连接已结束；文字和附件已保留。"
                        if state == "not_sent"
                        else "连接已结束，是否送达无法确认；请核对原生历史，不要重复发送。",
                    },
                )
                event = self._store_delivery(
                    session_id,
                    record["run_id"],
                    record,
                    ended_only=True,
                    evidence="connection_ended",
                )
                records[cid] = {**event["payload"], "run_id": record["run_id"]}
        return records

    def message_delivery(self, session_id: str, client_id: str) -> dict[str, Any]:
        self._session(session_id)
        record = self._deliveries(session_id).get(client_id)
        if record is None:
            raise BridgeError(
                "NOT_FOUND", "没有找到这条消息的接收记录。", details={"reason": "message_not_found"}
            )
        return record

    def _merge_deliveries(self, session_id: str, result: dict[str, Any]) -> dict[str, Any]:
        records = self._deliveries(session_id)
        merged = {item["id"]: item for item in result["items"]}
        for key, item in list(merged.items()):
            cid = item.get("client_id")
            if cid in records and item.get("status") == "sent":
                record = records[cid]
                if record["delivery"]["state"] != "sent":
                    record = {
                        **record,
                        "status": "sent",
                        "delivery": {
                            "state": "sent",
                            "reason": None,
                            "message": "原生历史已确认这条消息。",
                        },
                    }
                    self._store_delivery(
                        session_id,
                        record["run_id"],
                        record,
                        evidence="native_history_client_id",
                    )
                    records[cid] = record
                # Preserve one item with the API client identity, not a duplicate native echo.
                del merged[key]
                merged[record["id"]] = {**item, **record}
        for record in records.values():
            if record["delivery"]["state"] != "sent":
                merged[record["id"]] = record
        ordered = []
        for item in result["items"]:
            cid = item.get("client_id")
            key = records[cid]["id"] if cid in records else item["id"]
            if key in merged:
                ordered.append(merged.pop(key))
        return {**result, "items": ordered + list(merged.values())}

    # --- model catalogs -------------------------------------------------------------------------

    def _catalog_path(self, harness: str) -> Path:
        return self.root / f"catalog-{harness}.json"

    def catalog(self, harness: str) -> dict[str, Any] | None:
        """The harness's own model/effort/mode catalog (last one it reported, cached on disk)."""
        with self._lock:
            cached = self._catalogs.get(harness)
        if cached is None:
            try:
                loaded = json.loads(self._catalog_path(harness).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                loaded = None
            if isinstance(loaded, dict) and loaded.get("harness") == harness:
                cached = loaded
                with self._lock:
                    self._catalogs[harness] = loaded
        return cached

    def _catalog_summary(self, harness: str) -> dict[str, Any]:
        catalog = self.catalog(harness)
        info = self._harnesses.get(harness)
        probing = harness in self._catalog_probes
        if catalog is None:
            return {"status": "probing" if probing else "missing", "harness": harness}
        stale = bool(
            info is not None
            and info.version
            and catalog.get("cli_version")
            and catalog["cli_version"] != info.version
        )
        status = "probing" if probing else ("error" if catalog.get("error") else "ok")
        return {**catalog, "status": status, "stale": stale}

    def _store_catalog(self, harness: str, payload: Mapping[str, Any]) -> None:
        info = self._harnesses.get(harness)
        version = info.version if info else None
        if payload.get("error"):
            previous = self.catalog(harness) or {"harness": harness, "models": [], "modes": []}
            catalog = {**previous, "error": str(payload["error"])}
        elif harness == CLAUDE:
            catalog = controls.claude_catalog(payload, cli_version=version)
        else:
            catalog = controls.codex_catalog(
                list(payload.get("models") or []),
                payload.get("requirements"),
                cli_version=version,
            )
        if not payload.get("error"):
            catalog["fetched_at"] = _now()
        path = self._catalog_path(harness)
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass
        with self._lock:
            self._catalogs[harness] = catalog
        self._changed()

    def refresh_catalog(self, harness: str, session_id: str | None = None) -> dict[str, Any]:
        """Ask the CLI for its catalog with a short-lived process: no session, no turn."""
        if harness not in HARNESSES:
            raise BridgeError("INVALID_INPUT", f"unknown harness {harness!r}")
        workdir = self.base_env.get("HOME") or os.path.expanduser("~")
        if session_id:
            workdir = self._session(session_id)["workdir"]
        with self._lock:
            if harness in self._catalog_probes:
                return {"probing": True}
            self._catalog_probes.add(harness)
        self._changed()
        threading.Thread(
            target=self._probe_catalog, args=(harness, workdir), name="catalog", daemon=True
        ).start()
        return {"probing": True}

    def _probe_catalog(self, harness: str, workdir: str) -> None:
        scratch = self.root / "history" / ("catalog-" + uuid.uuid4().hex[:8])
        try:
            info = self._preflight(harness)
            assert info.binary is not None
            scratch.mkdir(parents=True, exist_ok=True)
            payload = probe_catalog(harness, info.binary, workdir, self.base_env, scratch)
            self._store_catalog(harness, payload)
        except (BridgeError, StructuredError, OSError) as exc:
            message = exc.message if isinstance(exc, BridgeError) else str(exc)
            self._store_catalog(harness, {"error": f"无法取得模型目录：{message}"})
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
            with self._lock:
                self._catalog_probes.discard(harness)
            self._changed()

    # --- model / effort / permission settings ---------------------------------------------------

    @staticmethod
    def _settings_of(session: Mapping[str, Any]) -> dict[str, Any]:
        raw = session.get("settings_json")
        try:
            loaded = json.loads(raw) if isinstance(raw, str) and raw else None
        except ValueError:
            loaded = None
        return controls.normalise(loaded)

    def _settings_view(self, session: Mapping[str, Any], live: LiveRun | None) -> dict[str, Any]:
        st = self._settings_of(session)
        actual = dict(st["actual"])
        actual["live"] = bool(
            live is not None and live.structured is not None and actual.get("live")
        )
        return {
            "chosen": st["chosen"],
            "fields": st["fields"],
            "actual": actual,
            "turn_model": st.get("turn_model"),
            "notices": st["notices"][-3:],
        }

    def _update_settings(
        self, session_id: str, fn: Callable[[dict[str, Any], dict[str, Any]], None]
    ) -> dict[str, Any] | None:
        """Read-modify-write a session's settings under one lock."""
        with self._settings_lock:
            session = self.store.get_session(session_id)
            if session is None:
                return None
            st = self._settings_of(session)
            fn(st, session)
            self.store.set_settings(session_id, st)
        self._changed()
        return st

    def choose_settings(self, session_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        """Record the user's choice; apply it now when that is safe, else on the next turn."""
        if not changes or any(k not in controls.FIELDS for k in changes):
            raise BridgeError("INVALID_INPUT", "settings: model, effort and/or mode")
        session = self._session(session_id)
        harness = session["harness"]
        catalog = self.catalog(harness)
        with self._settings_lock:
            st = self._settings_of(self._session(session_id))
            try:
                chosen, notices = controls.validate_choice(catalog, st, changes, harness=harness)
            except controls.ChoiceError as exc:
                raise BridgeError("INVALID_INPUT", str(exc)) from None
            previous = dict(st["chosen"])
            changed = [f for f in controls.FIELDS if chosen.get(f) != previous.get(f)]

            def record(st: dict[str, Any], _s: dict[str, Any]) -> None:
                for f in changed:
                    rec = {
                        "state": "selected",
                        "value": chosen.get(f),
                        "previous": previous.get(f),
                        "at": _now(),
                        "error": None,
                    }
                    if f not in changes and "model" in changes:
                        # Adjusted only because of the new model: it stands or falls with it.
                        rec["depends_on"] = "model"
                        rec["prior"] = st["fields"].get(f)
                    st["fields"][f] = rec
                st["chosen"] = chosen
                st["notices"] = (st["notices"] + [{"text": n, "at": _now()} for n in notices])[-5:]

            self._update_settings(session_id, record)
        if changed:
            self.store.add_event(
                session_id, None, "settings_chosen", {f: chosen.get(f) for f in changed}
            )
        with self._lock:
            live = self._live.get(session_id)
        if (
            changed
            and live is not None
            and live.structured is not None
            and live.harness == CLAUDE
            and not live.structured.busy
            and live.settings_ready.is_set()
        ):
            threading.Thread(target=self._apply_pending, args=(live,), daemon=True).start()
        self._changed()
        return self._settings_view(self._session(session_id), live)

    def _pending_fields(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        st = self._settings_of(session)
        return {
            f: rec.get("value")
            for f, rec in st["fields"].items()
            if isinstance(rec, dict) and rec.get("state") == "selected"
        }

    def _apply_pending(self, live: LiveRun) -> list[str]:
        """Claude Code: send the selected fields as control requests; return failure texts."""
        if live.structured is None:
            return []
        with live.apply_lock:
            pending = self._pending_fields(live.session_id)
            if not pending:
                return []
            failures = self._apply_now(live, pending) + live.connect_failures
            live.connect_failures = []
            return failures

    def _apply_now(self, live: LiveRun, fields: Mapping[str, Any]) -> list[str]:
        """Send, record refusals with the harness's own words, then read the result back."""
        structured = live.structured
        assert structured is not None
        self._mark_fields(live.session_id, list(fields), "applying")
        live.applying = True
        try:
            rest = dict(fields)
            failures: list[str] = []
            if "model" in rest:
                # The model first: changes made only because of it must not apply without it.
                failures = self._settle(
                    live, structured.apply_settings({"model": rest.pop("model")})
                )
                if failures:
                    rest = {f: v for f, v in rest.items() if f not in self._revert_dependents(live)}
            if rest:
                failures += self._settle(live, structured.apply_settings(rest))
            if isinstance(structured, ClaudeStreamSession):
                structured.read_settings()
            return failures
        finally:
            live.applying = False

    def _revert_dependents(self, live: LiveRun) -> set[str]:
        reverted: set[str] = set()

        def revert(st: dict[str, Any], _s: dict[str, Any]) -> None:
            for f, rec in list(st["fields"].items()):
                if isinstance(rec, dict) and rec.get("depends_on") == "model":
                    if rec.get("previous") is None:
                        st["chosen"].pop(f, None)
                    else:
                        st["chosen"][f] = rec["previous"]
                    prior = rec.get("prior")
                    if isinstance(prior, dict):
                        st["fields"][f] = prior
                    else:
                        st["fields"].pop(f, None)
                    st["notices"] = (
                        st["notices"]
                        + [{"text": f"模型没有切换，{FIELD_LABEL[f]}保持原样", "at": _now()}]
                    )[-5:]
                    reverted.add(f)

        self._update_settings(live.session_id, revert)
        return reverted

    def _settle(self, live: LiveRun, results: Mapping[str, Mapping[str, Any]]) -> list[str]:
        failures: list[str] = []

        def settle(st: dict[str, Any], _s: dict[str, Any]) -> None:
            for f, res in results.items():
                rec = st["fields"].get(f)
                if not isinstance(rec, dict) or rec.get("state") != "applying":
                    continue
                if not res.get("ok"):
                    text = (
                        f"{LABELS[live.harness]} 没有接受{FIELD_LABEL[f]}设置：{res.get('error')}"
                    )
                    self._fail_field(st, f, text)
                    failures.append(text)
                elif res.get("pending"):
                    rec["note"] = "下一轮发送时生效"
                    rec["state"] = "selected"
                else:
                    rec["note"] = "CLI 已接受，等待它报告生效值"

        self._update_settings(live.session_id, settle)
        return failures

    def _mark_fields(self, session_id: str, fields: list[str], state: str) -> None:
        def mark(st: dict[str, Any], _s: dict[str, Any]) -> None:
            for f in fields:
                rec = st["fields"].setdefault(f, {"value": st["chosen"].get(f)})
                rec.update(state=state, at=_now(), error=None, note=None)

        self._update_settings(session_id, mark)

    @staticmethod
    def _fail_field(st: dict[str, Any], f: str, error: str) -> None:
        rec = st["fields"].setdefault(f, {})
        rec.update(state="failed", error=error, attempted=rec.get("value"), at=_now())
        previous = rec.get("previous")
        # The harness keeps the old value; never pretend the new one is in force.
        if previous is None:
            st["chosen"].pop(f, None)
        else:
            st["chosen"][f] = previous
        rec["value"] = previous

    def _on_settings(self, live: LiveRun, report: Mapping[str, Any]) -> None:
        """A host report of what is actually in effect; confirms or fails pending choices."""
        source = str(report.get("source") or "")
        harness = live.harness
        catalog = self.catalog(harness)
        derived: dict[str, Any] = {}
        if isinstance(report.get("model"), str) and report["model"]:
            derived["model"] = report["model"]
        if "effort" in report:
            derived["effort"] = report.get("effort")
        if harness == CLAUDE and isinstance(report.get("mode"), str):
            derived["mode"] = "default" if report["mode"] == "manual" else report["mode"]
        if harness == CODEX and report.get("approval") is not None:
            derived["mode"] = (
                controls.codex_mode_of(report.get("approval"), report.get("sandbox")) or "other"
            )
        if report.get("turn_model"):
            live.turn_model = str(report["turn_model"])
        error = report.get("error")

        def apply(st: dict[str, Any], _s: dict[str, Any]) -> None:
            actual = st["actual"]
            sources = actual.setdefault("sources", {})
            for key, value in derived.items():
                actual[key] = value
                sources[key] = source
            if harness == CODEX and "mode" in derived:
                actual["mode_label"] = controls.describe_codex_mode(
                    report.get("approval"), report.get("sandbox")
                )
            if harness == CODEX and isinstance(report.get("reviewer"), str):
                # Who answers approval requests is Codex's own setting (user / auto review).
                actual["reviewer"] = report["reviewer"]
            if report.get("turn_model"):
                st["turn_model"] = report["turn_model"]
            actual["at"] = _now()
            actual["live"] = True
            for f, rec in st["fields"].items():
                if not isinstance(rec, dict) or rec.get("state") != "applying":
                    continue
                if error:
                    # The turn never started, so nothing was applied (or refused): retry later.
                    rec.update(
                        state="selected", note=f"这一轮没有开始（{error}）；下次发送时再应用"
                    )
                    continue
                if f not in derived:
                    continue
                want, got = rec.get("value"), derived[f]
                if self._setting_matches(harness, catalog, f, want, got):
                    rec.update(state="confirmed", source=source, at=_now(), note=None)
                elif source in AUTHORITATIVE[harness].get(f, ()):
                    text = (
                        f"{LABELS[harness]} 报告当前{FIELD_LABEL[f]}为 {got or '默认'}，"
                        f"不是所选的 {want or '默认'}"
                    )
                    self._fail_field(st, f, text)
                    if live.applying:
                        live.connect_failures.append(text)

        self._update_settings(live.session_id, apply)

    @staticmethod
    def _setting_matches(
        harness: str, catalog: Mapping[str, Any] | None, f: str, want: Any, got: Any
    ) -> bool:
        if f == "model":
            return want is None or controls.model_matches(catalog, str(want), got)
        if f == "effort":
            return want is None or want == got
        if want is None:
            return harness == CODEX or got == "default"
        return bool(want == got)

    def _connect_settings(self, live: LiveRun) -> None:
        """Claude Code: after the handshake, apply this session's choices and read them back."""
        structured = live.structured
        if not isinstance(structured, ClaudeStreamSession):
            live.settings_ready.set()
            return
        try:
            structured.wait_initialized(30)
            chosen = dict(self._settings_of(self._session(live.session_id))["chosen"])
            if chosen:
                with live.apply_lock:
                    live.connect_failures += self._apply_now(live, chosen)
            else:
                structured.read_settings()
        except (BridgeError, StructuredError, OSError):
            pass
        finally:
            live.settings_ready.set()
            self._changed()

    def _settings_disconnected(self, session_id: str, *, launched: bool = False) -> None:
        """The connection ended (or a terminal launch took the choices as flags)."""

        def mark(st: dict[str, Any], _s: dict[str, Any]) -> None:
            st["actual"]["live"] = False
            for f, rec in st["fields"].items():
                if not isinstance(rec, dict):
                    continue
                if launched and f in st["chosen"]:
                    rec.update(
                        state="launched", note="已作为启动参数传给终端；以终端中 CLI 的显示为准"
                    )
                elif rec.get("state") == "applying":
                    rec.update(state="selected", note="连接已结束；下次连接时再应用")

        self._update_settings(session_id, mark)

    # --- attachments and file references --------------------------------------------------------

    def add_attachment(
        self,
        session_id: str,
        *,
        name: str,
        data: bytes | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Keep a copy of a pasted, dropped or picked file for this session's next message."""
        session = self._session(session_id)
        if (data is None) == (path is None):
            raise BridgeError("INVALID_INPUT", "需要文件内容或文件路径（二选一）")
        if path is not None:
            if not os.path.isabs(path) or not os.path.isfile(path):
                raise BridgeError("INVALID_INPUT", f"不是文件：{path}")
            size = os.path.getsize(path)
            if size > max(FILE_LIMIT, IMAGE_LIMIT[CODEX]):
                raise BridgeError("INVALID_INPUT", f"文件太大（{size >> 20} MB）")
            with open(path, "rb") as fh:
                data = fh.read()
            name = name or os.path.basename(path)
        assert data is not None
        safe = _safe_name(name)
        mime = _image_mime(data)
        kind = "image" if mime else "file"
        limit = IMAGE_LIMIT[session["harness"]] if kind == "image" else FILE_LIMIT
        if len(data) > limit:
            what = "图片" if kind == "image" else "文件"
            raise BridgeError(
                "INVALID_INPUT",
                f"{what}太大：{len(data) / (1 << 20):.1f} MB，上限 {limit >> 20} MB",
            )
        if not data:
            raise BridgeError("INVALID_INPUT", "文件是空的")
        att_id = "att_" + uuid.uuid4().hex[:12]
        folder = self.root / "attachments" / session_id / att_id
        folder.mkdir(parents=True, mode=0o700)
        target = folder / safe
        target.write_bytes(data)
        meta = {
            "id": att_id,
            "name": safe,
            "kind": kind,
            "mime": mime or (mimetypes.guess_type(safe)[0] or "application/octet-stream"),
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "path": str(target),
            "added_at": _now(),
        }
        (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return {k: v for k, v in meta.items() if k != "path"}

    def _attachments(self, session_id: str, ids: list[str]) -> list[dict[str, Any]]:
        if len(ids) > MAX_ATTACHMENTS:
            raise BridgeError("INVALID_INPUT", f"一条消息最多 {MAX_ATTACHMENTS} 个附件")
        out = []
        for att_id in ids:
            if not re.fullmatch(r"att_[0-9a-f]{12}", att_id):
                raise BridgeError("INVALID_INPUT", "附件 ID 无效")
            folder = self.root / "attachments" / session_id / att_id
            try:
                meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise BridgeError("NOT_FOUND", "附件已不存在；请重新添加") from None
            out.append(meta)
        return out

    def search_files(self, session_id: str, query: str, limit: int = 40) -> list[dict[str, Any]]:
        """Project files for ``@`` references (git's view when it is a repository)."""
        workdir = self._session(session_id)["workdir"]
        files = self._project_files(workdir)
        q = query.strip().lower()
        scored = []
        for rel in files:
            score = _fuzzy(q, rel.lower())
            if score is not None:
                scored.append((score, rel))
        scored.sort(key=lambda x: (x[0], len(x[1]), x[1]))
        return [{"path": rel, "name": os.path.basename(rel)} for _, rel in scored[:limit]]

    def _project_files(self, workdir: str) -> list[str]:
        cached = self._file_index.get(workdir)
        if cached and time.monotonic() - cached[0] < 15:
            return cached[1]
        files: list[str] = []
        try:
            proc = subprocess.run(
                [
                    "git",
                    "-C",
                    workdir,
                    "ls-files",
                    "-z",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                ],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0:
                files = [f for f in proc.stdout.decode("utf-8", "replace").split("\0") if f]
        except (OSError, subprocess.TimeoutExpired):
            files = []
        if not files:
            skip = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
            for root, dirs, names in os.walk(workdir):
                dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
                for n in names:
                    files.append(os.path.relpath(os.path.join(root, n), workdir))
                if len(files) > 20000:
                    break
        files = files[:20000]
        self._file_index[workdir] = (time.monotonic(), files)
        return files

    # --- conversation actions -------------------------------------------------------------------

    def send_message(
        self,
        session_id: str,
        text: str,
        *,
        client_id: str | None = None,
        confirm_external: bool = False,
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        client_id = client_id or uuid.uuid4().hex[:16]
        self.obs.note_message(client_id)
        started = time.monotonic()
        observed: dict[str, Any] = {
            "session": session_id,
            "msg": client_id,
            "harness": self._harness_of(session_id),
            "attachments": len(attachments or []),
        }
        try:
            result = self._send_message(
                session_id,
                text,
                client_id=client_id,
                confirm_external=confirm_external,
                attachments=attachments,
            )
        except BridgeError as err:
            self.obs.record(
                "message.submit",
                outcome="refused",
                duration_ms=(time.monotonic() - started) * 1000,
                **observed,
                **error_fields(err),
            )
            raise
        self.obs.record(
            "message.submit",
            outcome="reused" if result.get("reused") else "accepted",
            duration_ms=(time.monotonic() - started) * 1000,
            linked=bool(self.store.native_link(session_id)),
            **observed,
        )
        return result

    def _send_message(
        self,
        session_id: str,
        text: str,
        *,
        client_id: str | None = None,
        confirm_external: bool = False,
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        files = self._attachments(session_id, list(attachments or []))
        if not text.strip() and not files:
            raise BridgeError("INVALID_INPUT", "消息不能为空")
        if len(text.encode("utf-8")) > MAX_MESSAGE:
            raise BridgeError("INVALID_INPUT", "消息过长（上限 100 KB）")
        client_id = client_id or uuid.uuid4().hex[:16]
        if not client_id.replace("-", "").isalnum() or len(client_id) > 64:
            raise BridgeError("INVALID_INPUT", "client_id 无效")
        with self._session_lock(session_id):
            session = self._session(session_id)
            if session["harness"] == CODEX:
                records = self._deliveries(session_id)
                previous = records.get(client_id)
                if previous:
                    if previous["text"] != text or [
                        a["id"] for a in previous.get("attachments", [])
                    ] != list(attachments or []):
                        raise BridgeError(
                            "STATE_CONFLICT",
                            "这个消息编号已用于其他内容。",
                            details={"reason": "client_id_conflict", "client_id": client_id},
                        )
                    return {
                        "client_id": client_id,
                        "delivery": previous["delivery"],
                        "reused": True,
                    }
                unknown = next(
                    (r for r in records.values() if r["delivery"]["state"] == "unknown"), None
                )
                if unknown:
                    raise BridgeError(
                        "STATE_CONFLICT",
                        "上一条消息是否送达不明；请先刷新并核对原生历史，不要重复发送。",
                        details={
                            "reason": "delivery_unknown",
                            "client_id": unknown["client_id"],
                            "delivery": unknown["delivery"],
                        },
                    )
            if session["view_mode"] != "conversation":
                raise BridgeError(
                    "STATE_CONFLICT", "这个会话使用终端视图；请在终端中输入，或先切换到对话视图"
                )
            with self._lock:
                live = self._live.get(session_id)
            if live is None:
                self._check_external(session, confirm_external)
                kind = "resume" if self._can_resume(session) else "new"
                self.start_run(session_id, kind, confirm_external=confirm_external)
                with self._lock:
                    live = self._live.get(session_id)
            if live is None or live.structured is None:
                raise BridgeError("STATE_CONFLICT", "会话没有以对话方式连接")
            if live.structured.busy:
                raise BridgeError("STATE_CONFLICT", "上一轮还在进行；可以先停止它")
            chips = [
                {"id": f["id"], "kind": f["kind"], "name": f["name"], "size": f["size"]}
                for f in files
            ]
            try:
                if isinstance(live.structured, ClaudeStreamSession):
                    if not live.settings_ready.wait(40):
                        raise BridgeError(
                            "STATE_CONFLICT", "Claude Code 还没有完成连接；请稍后再发"
                        )
                    failures = live.connect_failures + self._apply_pending(live)
                    live.connect_failures = []
                    if failures:
                        # The chosen setting did not apply: do not send with another one silently.
                        raise BridgeError(
                            "STATE_CONFLICT", "；".join(failures) + "。消息没有发送，草稿已保留。"
                        )
                    body, blocks = _claude_content(text, files)
                    live.structured.send(body, client_id, blocks, chips, display=text)
                else:
                    assert isinstance(live.structured, CodexAppServerSession)
                    model = controls.find_model(
                        self.catalog(CODEX),
                        self._settings_of(self._session(session_id))["chosen"].get("model")
                        or self._settings_of(self._session(session_id))["actual"].get("model"),
                    )
                    if any(f["kind"] == "image" for f in files) and model and not model["images"]:
                        raise BridgeError(
                            "INVALID_INPUT", f"{model['label']} 不接受图片输入；请换模型或去掉图片"
                        )
                    chosen = dict(self._settings_of(self._session(session_id))["chosen"])
                    pending = list(self._pending_fields(session_id))
                    if pending:
                        self._mark_fields(session_id, pending, "applying")
                    body, inputs = _codex_content(text, files)
                    codex = live.structured
                    codex.send(body, client_id, inputs, chips, chosen, display=text)
            except (StructuredError, OSError) as exc:
                if isinstance(live.structured, CodexAppServerSession):
                    raise BridgeError(
                        "STATE_CONFLICT",
                        str(exc) or "消息未被接收，内容仍需保留。",
                        details={
                            "reason": getattr(exc, "reason", "native_transport_error"),
                            "client_id": client_id,
                            "delivery": {"state": "not_sent"},
                        },
                    ) from None
                if live.structured.process is not None and live.structured.process.exited:
                    # The connection ended before the message went out: say why, keep the draft.
                    reason = self._ended_reason(live)
                    label = LABELS[live.harness]
                    raise BridgeError(
                        "STATE_CONFLICT",
                        f"{label} 的连接已结束：{reason}。消息没有发送，草稿已保留。",
                    ) from None
                raise BridgeError("STATE_CONFLICT", str(exc) or "消息没有发送成功") from None
        record = self._deliveries(session_id).get(client_id)
        return {"client_id": client_id, **({"delivery": record["delivery"]} if record else {})}

    def _ended_reason(self, live: LiveRun) -> str:
        deadline = time.monotonic() + 5
        run: dict[str, Any] = {}
        while time.monotonic() < deadline:
            run = self.store.get_run(live.run_id) or {}
            if run.get("status") not in ("starting", "running"):
                break
            time.sleep(0.05)
        return str(run.get("failure") or "进程已退出")

    def interrupt(self, session_id: str) -> dict[str, Any]:
        self._session(session_id)
        with self._lock:
            live = self._live.get(session_id)
        if live is None or live.structured is None:
            raise BridgeError("STATE_CONFLICT", "没有正在进行的对话")
        try:
            interrupted = live.structured.interrupt()
        except (StructuredError, OSError) as exc:
            raise BridgeError("STATE_CONFLICT", str(exc)) from None
        if interrupted:
            self.store.add_event(session_id, live.run_id, "turn_interrupt_requested", {})
        return {"interrupted": interrupted}

    def answer_permission(
        self,
        session_id: str,
        request_id: str,
        decision: str,
        answers: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._session(session_id)
        with self._lock:
            live = self._live.get(session_id)
        if live is None or live.structured is None:
            raise BridgeError("STATE_CONFLICT", "这个权限请求已经结束（会话没有在运行）")
        try:
            live.structured.answer(request_id, decision, answers)
        except (StructuredError, OSError) as exc:
            raise BridgeError("STATE_CONFLICT", str(exc)) from None
        if live.conv is not None and not live.conv.pending_permissions():
            live.attention = None
        self._changed()
        return {"answered": True}

    def conversation(
        self,
        session_id: str,
        *,
        refresh: bool = False,
        limit: Any = None,
        before: str | None = None,
        since: str | None = None,
    ) -> dict[str, Any]:
        session = self._session(session_id)
        self._check_link(session)
        if limit is not None or before or since:
            size = page_limit(limit)
            result = {} if before else self.conversation(session_id, refresh=refresh or bool(since))
            if not before:
                result.setdefault("history", {"source": "live-structured", "error": None})
            return self.native_history.pages.history(session_id, result, size, before, since)
        with self._lock:
            live = self._live.get(session_id)
        if live is not None and live.conv is not None:
            snap = live.conv.snapshot()
            info = live.structured.info if live.structured else {}
            return {**snap, "live": True, "run_id": live.run_id, "info": dict(info)}
        result = {**self._history(session, refresh), "live": False, "run_id": None, "turn": None}
        return self._merge_deliveries(session_id, result) if session["harness"] == CODEX else result

    def _history(self, session: dict[str, Any], refresh: bool) -> dict[str, Any]:
        sid = session["session_id"]
        native = session["native_session_id"]
        link = self.store.native_link(sid)
        if link:
            self._check_link(session)
            return self.native_history.history(json.loads(link["metadata_json"]))
        if not native or (
            session["turns_observed"] == 0 and not self._has_submitted_delivery(session)
        ):
            return {"items": [], "history": {"source": "none", "error": None}}
        key = f"{sid}:{native}"
        cached = self._history_cache.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < 30:
            return cached[1]
        error: str | None = None
        items: list[dict[str, Any]] = []
        source = "none"
        if session["harness"] == CLAUDE:
            try:
                items, path = read_claude_history(self._history_env(), native)
                source = "claude-transcript" if path else "none"
                if path is None:
                    error = "没有找到这个会话的 Claude Code 会话记录文件"
            except OSError as exc:
                error = f"无法读取 Claude Code 会话记录：{exc.strerror or exc}"
        else:
            info = self.harnesses().get(CODEX)
            if info is None or not info.available or info.binary is None:
                error = "找不到 Codex，无法读取历史"
            else:
                scratch = self.root / "history" / uuid.uuid4().hex[:8]
                scratch.mkdir(parents=True, exist_ok=True)
                try:
                    items = read_codex_history(
                        info.binary, self._history_env(), session["workdir"], native, scratch
                    )
                    source = "codex"
                except (StructuredError, OSError) as exc:
                    error = f"无法通过 Codex app-server 读取历史：{exc}"
                finally:
                    shutil.rmtree(scratch, ignore_errors=True)
        if not items:
            cache = self._cached_conversation(sid)
            if cache:
                items = cache
                source = "cache"
                error = (error or "原生历史为空") + "；下面是 RepoBridge 上次显示的内容"
        result = {
            "items": [{**i, "history": True} for i in items],
            "history": {"source": source, "error": error},
        }
        self._history_cache[key] = (time.monotonic(), result)
        return result

    def _cached_conversation(self, session_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for run in self.store.list_runs(session_id):
            path = self.root / "runs" / run["run_id"] / "conversation.json"
            try:
                items = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(items, list):
                out.extend(i for i in items if isinstance(i, dict) and "id" in i)
        return out

    # --- view switching -------------------------------------------------------------------------

    def switch_view(
        self, session_id: str, mode: str, *, confirm_unknown: bool = False
    ) -> dict[str, Any]:
        if mode not in VIEWS:
            raise BridgeError("INVALID_INPUT", f"unknown view {mode!r}")
        with self._session_lock(session_id):
            session = self._session(session_id)
            if session["view_mode"] == mode:
                return {"view_mode": mode, "reconnected": False}
            with self._lock:
                live = self._live.get(session_id)
            runs = self.store.list_runs(session_id)
            if live is None and self._is_active(runs):
                raise BridgeError(
                    "STATE_CONFLICT",
                    "上次运行遗留的进程仍在，当前窗口无法安全切换；请先结束它",
                )
            if live is None:
                self.store.set_view_mode(session_id, mode)
                self.store.add_event(session_id, None, "view_changed", {"to": mode})
                self._history_cache.pop(f"{session_id}:{session['native_session_id']}", None)
                self._changed()
                return {"view_mode": mode, "reconnected": False}
            self._require_idle(live, confirm_unknown, "切换视图")
            self._release(live, "view")
            self.store.set_view_mode(session_id, mode)
            self.store.add_event(session_id, None, "view_changed", {"to": mode, "released": True})
            session = self._session(session_id)
            kind = "resume" if self._can_resume(session) else "new"
            try:
                self.start_run(session_id, kind, confirm_external=True)
            except BridgeError as exc:
                raise BridgeError(
                    exc.code,
                    f"已结束原来的连接，但没能用新视图接续：{exc.message}。原生会话已保存，可以稍后恢复。",
                ) from None
            return {"view_mode": mode, "reconnected": True, "kind": kind}

    def _require_idle(self, live: LiveRun, confirm_unknown: bool, action: str) -> None:
        state = self._idle_state(live)
        if state == "busy":
            raise BridgeError(
                "STATE_CONFLICT",
                f"{LABELS[live.harness]} 还在处理当前这一轮（或在等你确认权限）；"
                f"请等它结束或先停止这一轮，再{action}",
                details={"idle": "busy"},
            )
        if state == "unknown" and not confirm_unknown:
            raise BridgeError(
                "STATE_CONFLICT",
                f"无法确认 {LABELS[live.harness]} 当前是否空闲；{action}会结束它的进程，"
                "如果它正在执行，这一轮会被中断",
                details={"idle": "unknown"},
            )

    @staticmethod
    def _idle_state(live: LiveRun) -> str:
        if live.attention is not None:
            return "busy"
        if live.structured is not None:
            return "busy" if live.structured.busy else "idle"
        if live.phase == "waiting":
            return "idle"
        if live.phase == "working":
            return "busy"
        return "unknown"

    def _release(self, live: LiveRun, reason: str, timeout: float = 20.0) -> None:
        """End this App's connection and wait until its exit is confirmed (one writer only)."""
        live.stop_requested = True
        live.release_reason = reason
        self.store.mark_stop_requested(live.run_id)
        self.store.add_event(live.session_id, live.run_id, "released", {"reason": reason})
        self._changed()
        live.terminate(self.stop_grace)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._live.get(live.session_id) is not live:
                    break
            time.sleep(0.05)
        run = self.store.get_run(live.run_id) or {}
        if run.get("status") in ("starting", "running") or not run.get("exit_confirmed"):
            raise BridgeError(
                "STATE_CONFLICT",
                "原来的连接还没有确认退出；为避免两个写入者，没有启动新的连接",
            )

    # --- official desktop clients ---------------------------------------------------------------

    def open_in_desktop(
        self, session_id: str, *, release: bool = False, confirm_unknown: bool = False
    ) -> dict[str, Any]:
        harness = self._harness_of(session_id)
        try:
            result = self._open_in_desktop(
                session_id, release=release, confirm_unknown=confirm_unknown
            )
        except BridgeError as err:
            self.obs.record(
                "desktop.open",
                session=session_id,
                outcome="refused",
                harness=harness,
                released=False,
                **error_fields(err),
            )
            raise
        self.obs.record(
            "desktop.open",
            session=session_id,
            outcome=result.get("status"),
            harness=harness,
            released=release,
        )
        return result

    def _open_in_desktop(
        self, session_id: str, *, release: bool = False, confirm_unknown: bool = False
    ) -> dict[str, Any]:
        with self._session_lock(session_id):
            session = self._session(session_id)
            harness = session["harness"]
            self._check_link(session, resume=True)
            cap = self._desktop_capability(session)
            if not cap["available"]:
                raise BridgeError("PREFLIGHT_FAILED", cap["reason"] or "无法在桌面客户端中打开")
            refusal = environment_refusal(self.base_env)
            if refusal:
                raise BridgeError("PREFLIGHT_FAILED", refusal)
            with self._lock:
                live = self._live.get(session_id)
            if live is not None:
                if not release:
                    raise BridgeError(
                        "STATE_CONFLICT",
                        f"会话正在 RepoBridge 中运行；在 {cap['app']} 中继续之前"
                        "需要先结束这里的连接",
                        details={"needs_release": True},
                    )
                self._require_idle(live, confirm_unknown, f"在 {cap['app']} 中打开")
                self._release(live, "desktop")
            elif self._is_active(self.store.list_runs(session_id)):
                raise BridgeError(
                    "STATE_CONFLICT", "上次运行遗留的进程仍在；请先结束它，再在桌面客户端中打开"
                )
            native = str(session["native_session_id"])
            env = self._history_env()
            if harness == CLAUDE:
                info = self._preflight(CLAUDE)
                assert info.binary is not None
                result = desktop_apps.open_claude(
                    info.binary, native, cwd=session["workdir"], env=env
                )
            else:
                app = self.desktop_apps()[CODEX]
                result = desktop_apps.open_codex(app, native, opener=self.config.opener, env=env)
            external = {
                "app": cap["app"],
                "harness": harness,
                "opened_at": _now(),
                "status": result["status"],
                "via": "repobridge",
            }
            self.store.add_event(
                session_id,
                None,
                "desktop_open",
                {k: v for k, v in result.items() if k != "message"} | {"app": cap["app"]},
            )
            if result["status"] in ("acknowledged", "requested"):
                self.store.set_external(session_id, external)
            self._changed()
            return {**result, "app": cap["app"], "external": external}

    def desktop_return(self, session_id: str) -> dict[str, Any]:
        with self._session_lock(session_id):
            session = self._session(session_id)
            self.obs.record(
                "desktop.return",
                session=session_id,
                harness=session["harness"],
                had_hold=bool(session.get("external_json")),
            )
            if session.get("external_json"):
                self.store.set_external(session_id, None)
                self.store.add_event(
                    session_id,
                    None,
                    "desktop_returned",
                    {"source": "user_confirmation", "process_exit_observed": False},
                )
            self._history_cache.pop(f"{session_id}:{session['native_session_id']}", None)
            self._changed()
        return {"external": None}

    def _check_external(self, session: Mapping[str, Any], confirm: bool) -> None:
        raw = session.get("external_json")
        if not raw:
            return
        external = _loads(raw)
        if not confirm:
            location = (
                "这个原生会话可能仍在外部客户端使用。"
                if external.get("via") == "native-link"
                else f"这个会话已在 {external.get('app')} 中打开。"
            )
            raise BridgeError(
                "STATE_CONFLICT",
                location + "RepoBridge 看不到那边是否还在执行；"
                "请先在那边结束当前这一轮，再回到这里继续",
                details={"reason": "external_confirmation_required", "external": external},
            )
        self.store.set_external(str(session["session_id"]), None)
        self.store.add_event(str(session["session_id"]), None, "desktop_returned", {})

    # --- runs -----------------------------------------------------------------------------------

    def stop(self, session_id: str) -> dict[str, Any]:
        self._session(session_id)
        with self._lock:
            live = self._live.get(session_id)
        if live is not None:
            live.stop_requested = True
            self.store.mark_stop_requested(live.run_id)
            self.store.add_event(session_id, live.run_id, "stop_requested", {})
            self._changed()
            threading.Thread(target=live.terminate, args=(self.stop_grace,), daemon=True).start()
            return {"stopping": True}
        runs = self.store.list_runs(session_id)
        run = runs[-1] if runs else None
        if run is None or run["status"] not in ("starting", "running"):
            return {"stopping": False}
        return self._stop_orphan(run)

    def _stop_orphan(self, run: dict[str, Any]) -> dict[str, Any]:
        """A run recorded as active by an earlier App instance (no process attached here)."""
        pid, pgid = run["pid"], run["pgid"]
        if pid is None:
            self.store.finish_run(
                run["run_id"], status="interrupted", failure="App 在启动过程中退出"
            )
            self._changed()
            return {"stopping": False}
        alive = alive_with_birth(pid, run["birth"])
        if alive:
            for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGKILL):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pgid, sig)
                if _wait_until(lambda: group_members(pgid) == [], self.stop_grace):
                    break
        members = group_members(pgid)
        if members == []:
            self.store.finish_run(
                run["run_id"],
                status="stopped",
                exit_confirmed=True,
                failure="由之前的 App 进程启动；已结束其进程组",
            )
            self.store.add_event(run["session_id"], run["run_id"], "orphan_stopped", {})
        else:
            self.store.note_failure(run["run_id"], f"退出不明：进程组成员 {members}")
        self._changed()
        return {"stopping": False, "confirmed": members == []}

    def write_input(self, session_id: str, data: bytes) -> None:
        with self._lock:
            live = self._live.get(session_id)
        if live is None or live.process is None:
            raise BridgeError("STATE_CONFLICT", "会话没有在本窗口的终端中运行")
        if live.attention is not None:
            live.attention = None
            self._changed()
        if live.harness == CODEX and live.phase == "waiting" and b"\r" in data:
            live.phase = "running"
            self._changed()
        try:
            live.process.write(data)
        except OSError as exc:
            raise BridgeError("STATE_CONFLICT", f"会话进程已退出：{exc.strerror}") from None

    def resize(self, session_id: str, cols: int, rows: int) -> None:
        with self._lock:
            live = self._live.get(session_id)
        if live is not None and live.process is not None:
            live.process.resize(max(2, min(cols, 1000)), max(2, min(rows, 500)))

    def output(self, session_id: str, limit: int = 256 << 10) -> dict[str, Any]:
        self._session(session_id)
        with self._lock:
            live = self._live.get(session_id)
        if live is not None and live.transport == "pty":
            offset, data = live.buffer.tail(limit)
            return {"run_id": live.run_id, "live": True, "offset": offset, "data": _b64(data)}
        runs = [r for r in self.store.list_runs(session_id) if r.get("transport", "pty") == "pty"]
        if not runs:
            return {"run_id": None, "live": False, "offset": 0, "data": ""}
        run = runs[-1]
        data = read_log_tail(self.root / "runs" / run["run_id"] / "output.log", limit)
        return {"run_id": run["run_id"], "live": False, "offset": 0, "data": _b64(data)}

    def live_tails(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = [sid for sid, lr in self._live.items() if lr.transport == "pty"]
        return [{"session_id": sid, **self.output(sid)} for sid in sessions]

    def activity(self, session_id: str, after: int = 0) -> list[dict[str, Any]]:
        self._session(session_id)
        return self.store.list_events(session_id, after=after)

    def changes(self, session_id: str) -> dict[str, Any]:
        return changes.status(self._session(session_id)["workdir"])

    def diff(self, session_id: str, path: str) -> dict[str, Any]:
        workdir = self._session(session_id)["workdir"]
        if path and os.path.isabs(path):
            # Native tools report absolute paths; show them when they are inside the project.
            real = os.path.realpath(path)
            root = os.path.realpath(workdir).rstrip(os.sep) + os.sep
            if real.startswith(root):
                path = real[len(root) :]
        if not path or os.path.isabs(path) or "\0" in path:
            raise BridgeError("INVALID_INPUT", "path must be relative to the working directory")
        target = os.path.realpath(os.path.join(workdir, path))
        if not (target + os.sep).startswith(workdir.rstrip(os.sep) + os.sep):
            raise BridgeError("INVALID_INPUT", "path is outside the working directory")
        return {**changes.diff(workdir, path), "path": path}

    # --- handoff --------------------------------------------------------------------------------

    def handoff_draft(self, session_id: str, target: str, progress: str = "") -> dict[str, Any]:
        session = self._session(session_id)
        if target not in HARNESSES:
            raise BridgeError("INVALID_INPUT", f"unknown harness {target!r}")
        runs = self.store.list_runs(session_id)
        note = handoff.draft(
            project=self._project(session["project_id"]),
            session=session,
            target_harness=target,
            last_run=runs[-1] if runs else None,
            events=self.store.list_events(session_id, limit=2000),
            git_status=changes.status(session["workdir"]),
            diffstat=changes.diffstat(session["workdir"]),
            progress=progress,
        )
        return {"note": note, "target": target, "source_active": self._is_active(runs)}

    def create_handoff(
        self,
        session_id: str,
        target: str,
        note: str,
        *,
        send_as_prompt: bool,
        title: str | None = None,
    ) -> dict[str, Any]:
        source = self._session(session_id)
        if target not in HARNESSES:
            raise BridgeError("INVALID_INPUT", f"unknown harness {target!r}")
        note = note.strip()
        if not note:
            raise BridgeError("INVALID_INPUT", "交接说明不能为空")
        if len(note.encode("utf-8")) > 100_000:
            raise BridgeError("INVALID_INPUT", "交接说明过长（上限 100 KB）")
        if self._is_active(self.store.list_runs(session_id)):
            raise BridgeError(
                "STATE_CONFLICT",
                "原会话仍在运行；同一工作目录只允许一个写入会话，请先停止原会话再交接",
            )
        self._preflight(target)
        self._ensure_workdir_free(source["workdir"])
        new = self.create_session(
            source["project_id"],
            target,
            title=title or f"{LABELS[target]} ← {source['title']}"[:120],
            start=False,
            handoff_from=session_id,
            view_mode=source["view_mode"],
        )
        note_path = self.root / "handoffs" / f"{new['session_id']}.md"
        note_path.write_text(note + "\n", encoding="utf-8")
        record = self.store.add_handoff(
            project_id=source["project_id"],
            from_session_id=session_id,
            to_session_id=new["session_id"],
            note_path=str(note_path),
            note_digest="sha256:" + hashlib.sha256(note.encode("utf-8")).hexdigest(),
            send_as_prompt=send_as_prompt,
        )
        self.store.add_event(
            session_id, None, "handoff_out", {"to": new["session_id"], "target": target}
        )
        self.store.add_event(
            new["session_id"],
            None,
            "handoff_in",
            {"from": session_id, "send_as_prompt": send_as_prompt},
        )
        self._changed()
        self.start_run(new["session_id"], "new")
        return {"handoff": record, "session": self._session(new["session_id"])}

    def _handoff_prompt(self, session_id: str) -> str | None:
        for record in self.store.list_handoffs():
            if record["to_session_id"] == session_id and record["send_as_prompt"]:
                return Path(record["note_path"]).read_text(encoding="utf-8").strip()
        return None

    # --- lifecycle ------------------------------------------------------------------------------

    def reconcile(self) -> None:
        """Resolve runs that an earlier App instance left recorded as active."""
        for run in self.store.active_runs():
            if run["pid"] is None:
                self.store.finish_run(
                    run["run_id"], status="interrupted", failure="App 在启动过程中退出"
                )
                continue
            alive = alive_with_birth(run["pid"], run["birth"])
            members = group_members(run["pgid"]) if alive is False else None
            if alive is False and members == []:
                tail = read_log_tail(self.root / "runs" / run["run_id"] / "output.log", 65536)
                self.store.finish_run(
                    run["run_id"],
                    status="interrupted",
                    exit_confirmed=True,
                    failure="RepoBridge 退出时会话仍在运行；可用原生恢复继续",
                    output_tail=strip_ansi_tail(tail),
                )
                self.store.add_event(run["session_id"], run["run_id"], "run_interrupted", {})
            else:
                self.store.note_failure(
                    run["run_id"],
                    "由之前的 App 进程启动，仍在运行或无法确认退出；可在此终止",
                )

    def close(self, timeout: float = 10.0) -> None:
        with self._lock:
            lives = list(self._live.values())
        self.obs.record(
            "app.stop",
            uptime_ms=(time.monotonic() - self.obs.started) * 1000,
            live_runs=len(lives),
            dropped=self.obs.dropped(),
            write_errors=self.obs.write_errors(),
        )
        threads = []
        for live in lives:
            live.stop_requested = True
            self.store.mark_stop_requested(live.run_id)
            t = threading.Thread(target=live.terminate, args=(self.stop_grace,))
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout)
        self._closing.set()
        self._notifier.join(2)
        self.store.close()
        self.obs.close()
        if self._root_lock is not None:
            self._root_lock.release()

    # --- PTY callbacks --------------------------------------------------------------------------

    def _on_output(self, live: LiveRun, data: bytes) -> None:
        if live.phase == "starting":
            live.phase = "running"
            if live.transport == "pty":
                self._observe_ready(live)
            self._changed()
        offset = live.buffer.append(data)
        self._publish(
            "output",
            {
                "session_id": live.session_id,
                "run_id": live.run_id,
                "offset": offset,
                "data": _b64(data),
            },
        )
        for message in live.osc.feed(data):
            self._record(live, {"source": "terminal", "event": "notification", "message": message})

    def _on_tick(self, live: LiveRun) -> None:
        for record in live.tail.poll():
            self._record(live, record)

    def _record(self, live: LiveRun, record: dict[str, Any]) -> None:
        sid = live.session_id
        source, event = record.get("source"), record.get("event")
        native = record.get("native_session_id")
        session = self.store.get_session(sid)
        if session is None:
            return
        if isinstance(native, str) and native and source in ("claude-hook", "codex-notify"):
            current = session["native_session_id"]
            if source == "claude-hook" and event == "SessionStart" and native == current:
                if session["native_binding"] != "confirmed":
                    self.store.set_native(sid, native, "confirmed")
            elif native != current:
                if self.store.native_link(sid):
                    self._structured_fatal(
                        live,
                        "Native identity changed; association retained",
                        "native_identity_changed",
                    )
                    return
                self.store.set_native(sid, native, "observed")
                self.store.add_event(
                    sid,
                    live.run_id,
                    "native_session_changed" if current else "native_session_observed",
                    {"from": current, "to": native, "via": event},
                )
        if (source == "claude-hook" and event == "UserPromptSubmit") or (
            source == "codex-notify" and event == "agent-turn-complete"
        ):
            self.store.count_turn(sid)
        attention: dict[str, Any] | None = None
        if (source in ("claude-hook", "structured")) and (
            event == "PermissionRequest"
            or (event == "Notification" and record.get("notification_type") == "permission_prompt")
        ):
            attention = {"kind": "permission", "message": _attention_text(record)}
        elif source == "terminal" and any(
            w in str(record.get("message", "")).lower() for w in _PERMISSION_WORDS
        ):
            attention = {"kind": "permission", "message": record.get("message")}
        if attention is not None:
            live.attention = attention
        elif source == "structured":
            if live.conv is not None and not live.conv.pending_permissions():
                live.attention = None
        elif event in _CLEARS_ATTENTION or source == "codex-notify":
            live.attention = None
        if source == "claude-hook":
            if event in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure"):
                live.phase = "working"
            elif event in ("SessionStart", "Stop") or (
                event == "Notification" and record.get("notification_type") == "idle_prompt"
            ):
                live.phase = "waiting"
        elif source == "codex-notify":
            live.phase = "waiting"
        stored = self.store.add_event(sid, live.run_id, "activity", record)
        self._publish("activity", stored)
        self._changed()

    def _on_exit(self, live: LiveRun, info: ExitInfo) -> None:
        if live.transport == "pty":
            _, raw_tail = live.buffer.tail(65536)
        else:
            raw_tail = read_log_tail(live.run_dir / "stderr.log", 16384)
            if live.conv is not None:
                live.conv.finish_open_items("interrupted")
                for item in live.conv.items():
                    if item["type"] == "user" and item.get("status") == "sending":
                        live.conv.upsert({"id": item["id"], "status": "failed"})
                if live.conv.turn is not None:
                    live.conv.set_turn(None)
            self._save_conversation(live)
            self._settings_disconnected(live.session_id)
        live.buffer.close()
        tail = strip_ansi_tail(raw_tail)
        if live.transport == "structured" and live.conv is not None:
            errors = [
                i["text"]
                for i in live.conv.items()
                if i["type"] == "notice" and i.get("level") == "error"
            ]
            if errors:
                tail = "\n".join([*errors[-3:], tail]).strip()
        if not info.confirmed:
            failure = f"退出不明：进程组仍有成员 {info.remaining_group}"
            self.store.note_failure(live.run_id, failure)
            self.store.add_event(live.session_id, live.run_id, "exit_unconfirmed", {})
        else:
            noted = (self.store.get_run(live.run_id) or {}).get("failure")
            if live.stop_requested:
                status, failure = "stopped", None
            elif noted:
                # A structured connection that failed before exiting keeps its own reason.
                status, failure = "failed", str(noted)
                if info.exit_code not in (0, None) or info.exit_signal is not None:
                    failure += f"（{_exit_reason(info)}）"
            elif info.exit_code == 0:
                status, failure = "exited", None
            else:
                status, failure = "failed", _exit_reason(info)
                # Only native process output belongs in the exit summary. Conversation notices
                # can describe provisional delivery uncertainty, later settled by native proof.
                # Keep those notices in output_tail, but do not freeze them into run.failure.
                native_tail = strip_ansi_tail(raw_tail).strip()
                last = native_tail.splitlines()[-1].strip() if native_tail else ""
                if live.transport == "structured" and last:
                    # The CLI's own last words (e.g. "No conversation found …") explain it best.
                    failure += f"：{last[:300]}"
            self.store.finish_run(
                live.run_id,
                status=status,
                exit_code=info.exit_code,
                exit_signal=info.exit_signal,
                exit_confirmed=True,
                failure=failure,
                output_tail=tail,
            )
            self.store.add_event(
                live.session_id,
                live.run_id,
                "run_ended",
                {
                    "status": status,
                    "exit_code": info.exit_code,
                    "exit_signal": info.exit_signal,
                    "failure": failure,
                    "transport": live.transport,
                    "released_for": live.release_reason,
                },
            )
            self._detect_cli_desktop_handoff(live, raw_tail)
        self._observe_exit(live, info)
        with self._lock:
            if self._live.get(live.session_id) is live:
                del self._live[live.session_id]
        self._history_cache = {
            k: v for k, v in self._history_cache.items() if not k.startswith(live.session_id)
        }
        self._publish("ended", {"session_id": live.session_id, "run_id": live.run_id})
        self._changed()

    def _observe_exit(self, live: LiveRun, info: ExitInfo) -> None:
        try:
            status = (
                (self.store.get_run(live.run_id) or {}).get("status")
                if info.confirmed
                else "unconfirmed"
            )
            if info.exit_signal is not None:
                exit_class = "signal"
            elif info.exit_code is None:
                exit_class = "unknown"
            else:
                exit_class = "zero" if info.exit_code == 0 else "nonzero"
            self.obs.record(
                "run.end",
                level="warning" if status in ("failed", "unconfirmed") else "info",
                session=live.session_id,
                run=live.run_id,
                duration_ms=self.obs.run_elapsed(live.run_id),
                harness=live.harness,
                transport=live.transport,
                status=status,
                exit_class=exit_class,
                ready=self.obs.was_ready(live.run_id),
                released_for=live.release_reason,
                stop_requested=live.stop_requested,
            )
        except Exception:
            self.obs.invalid += 1

    def _detect_cli_desktop_handoff(self, live: LiveRun, raw_tail: bytes) -> None:
        """``/desktop`` inside the Claude TUI moves the session to Claude Desktop and exits."""
        if live.harness != CLAUDE or live.transport != "pty":
            return
        session = self.store.get_session(live.session_id)
        native = session["native_session_id"] if session else None
        text = strip_ansi_tail(raw_tail, lines=40, limit=8000)
        if native and f"Opening session {native} in Claude Desktop" in text:
            self.store.set_external(
                live.session_id,
                {
                    "app": "Claude Desktop",
                    "harness": CLAUDE,
                    "opened_at": _now(),
                    "status": "acknowledged",
                    "via": "cli /desktop",
                },
            )
            self.store.add_event(live.session_id, live.run_id, "desktop_open", {"via": "/desktop"})

    # --- helpers --------------------------------------------------------------------------------

    def _session_lock(self, session_id: str) -> threading.RLock:
        with self._lock:
            return self._session_locks.setdefault(session_id, threading.RLock())

    def _can_resume(self, session: Mapping[str, Any]) -> bool:
        link = self.store.native_link(session["session_id"])
        if link:
            return bool(link["linked"] and json.loads(link["metadata_json"])["resumable"])
        return bool(session["native_session_id"]) and (
            session["turns_observed"] > 0 or self._has_submitted_delivery(session)
        )

    def _has_submitted_delivery(self, session: Mapping[str, Any]) -> bool:
        # The first turn may have reached Codex even when its reply/turn event was lost.
        # Read that known thread and resume only its ID; do not fabricate an observed turn
        # or allow "new" to replace the binding. Missing history leaves the receipt unknown.
        return session["harness"] == CODEX and any(
            record["delivery"]["state"] in ("sending", "unknown", "sent")
            for record in self.store.message_deliveries(session["session_id"]).values()
        )

    def _project(self, project_id: str) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        if project is None or project["archived"]:
            raise BridgeError("NOT_FOUND", f"project {project_id} not found")
        return project

    def _session(self, session_id: str) -> dict[str, Any]:
        session = self.store.get_session(session_id)
        if session is None:
            raise BridgeError("NOT_FOUND", f"session {session_id} not found")
        return session

    def _preflight(self, harness: str) -> HarnessInfo:
        refusal = environment_refusal(self.base_env)
        if refusal:
            raise BridgeError("PREFLIGHT_FAILED", refusal)
        info = self.harnesses().get(harness)
        if info is None or not info.available:
            info = self.harnesses(refresh=True)[harness]
        if not info.available:
            raise BridgeError("PREFLIGHT_FAILED", f"{info.label} 不可用：{info.problem}")
        return info

    def _ensure_workdir_free(self, workdir: str) -> None:
        for run in self.store.active_runs():
            if run["workdir"] == workdir:
                session = self._session(run["session_id"])
                raise self._busy_error(
                    WorkdirBusy(workdir, session["session_id"], session["title"])
                )

    @staticmethod
    def _busy_error(busy: WorkdirBusy) -> BridgeError:
        return BridgeError(
            "STATE_CONFLICT",
            f"工作目录 {busy.workdir} 已有活动写入会话「{busy.title}」；请先停止它，或切换到该会话",
            details={"reason": "local_writer_busy", "busy_session_id": busy.session_id},
        )

    @staticmethod
    def _is_active(runs: list[dict[str, Any]]) -> bool:
        return bool(runs) and runs[-1]["status"] in ("starting", "running")


def _conn_info(live: LiveRun | None) -> dict[str, Any] | None:
    if live is None or live.structured is None:
        return None
    keep = ("model", "permissionMode", "approval_policy", "sandbox")
    info = live.structured.info
    return {k: info[k] for k in keep if info.get(k)}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _loads(text: str) -> Any:
    return json.loads(text)


def _attention_text(record: dict[str, Any]) -> str:
    if record.get("message"):
        return str(record["message"])
    tool = record.get("tool_name") or "工具"
    summary = record.get("summary")
    return f"{tool}: {summary}" if summary else str(tool)


def _exit_reason(info: ExitInfo) -> str:
    if info.exit_signal is not None:
        try:
            name = signal.Signals(info.exit_signal).name
        except ValueError:
            name = str(info.exit_signal)
        return f"进程被信号 {name} 结束"
    if info.exit_code == 127:
        return "无法启动原生 CLI（退出码 127）"
    return f"原生 CLI 以退出码 {info.exit_code} 结束"


def _wait_until(predicate: Any, timeout: float) -> bool:
    end = threading.Event()
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        end.wait(0.1)
        waited += 0.1
    return bool(predicate())


def _image_mime(data: bytes) -> str | None:
    """Only real image bytes count as images (never a client-supplied type)."""
    for magic, mime in _IMAGE_MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _safe_name(name: str) -> str:
    base = os.path.basename(str(name or "").replace("\\", "/")).strip() or "附件"
    base = re.sub(r"[\x00-\x1f/:]", "_", base)[:120]
    return "_" + base if base.startswith(".") else base


def _fuzzy(query: str, text: str) -> int | None:
    """Lower is better; None when the query letters do not appear in order."""
    if not query:
        return 0
    base = text.rsplit("/", 1)[-1]
    if query in base:
        return base.index(query)
    if query in text:
        return 50 + text.index(query)
    pos = -1
    gaps = 0
    for ch in query:
        nxt = text.find(ch, pos + 1)
        if nxt < 0:
            return None
        gaps += nxt - pos - 1
        pos = nxt
    return 200 + gaps


def _claude_content(text: str, files: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Images as native image blocks; other files as Claude Code ``@"path"`` file mentions."""
    blocks = []
    mentions = []
    for f in files:
        if f["kind"] == "image":
            data = Path(f["path"]).read_bytes()
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": f["mime"],
                        "data": base64.b64encode(data).decode("ascii"),
                    },
                }
            )
        else:
            mentions.append(f'@"{f["path"]}"')
    if mentions:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + "附件：" + " ".join(mentions)
    return text, blocks


def _codex_content(text: str, files: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Images as Codex ``localImage`` inputs; other files by path for Codex to read."""
    inputs = [{"type": "localImage", "path": f["path"]} for f in files if f["kind"] == "image"]
    others = [f for f in files if f["kind"] != "image"]
    if others:
        listing = "\n".join(f"- {f['path']}" for f in others)
        text = (text.rstrip() + "\n\n" if text.strip() else "") + "附件文件（请读取）：\n" + listing
    return text, inputs
