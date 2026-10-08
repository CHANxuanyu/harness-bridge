"""Workbench service: projects, native sessions, runs, side-channel events, handoffs.

Thread model: HTTP handler threads call into this object; each live run has one PTY reader
thread; a notifier thread coalesces state snapshots for subscribers. SQLite is the authority for
projects/sessions/runs/events; live PTY objects exist only for runs this App instance spawned.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness_bridge.errors import BridgeError
from harness_bridge.workbench import changes, handoff
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
    stripped_billing_env,
)
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
from harness_bridge.workbench.store import WorkbenchStore, WorkdirBusy

_PERMISSION_WORDS = ("permission", "approval", "approve", "权限", "批准")
_CLEARS_ATTENTION = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop", "UserPromptSubmit"}


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
    # starting → running (output seen) → working (Claude turn) / waiting (ready for input)
    phase: str = "starting"


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
        self.root = state_dir / "workbench"
        (self.root / "runs").mkdir(parents=True, exist_ok=True)
        (self.root / "handoffs").mkdir(parents=True, exist_ok=True)
        self.store = WorkbenchStore(state_dir / "workbench.sqlite3")
        self.prefs = Prefs(self.root / "prefs.json")
        # Native window hooks (title, appearance, folder picker), set by ``hbridge app`` when a
        # pywebview window exists. Called from request threads; never from page JavaScript eval.
        self.native: dict[str, Callable[..., Any]] = {}
        # Development-only window snapshot/reload (``hbridge app --dev-snapshot-dir``).
        self.dev_snapshot: Callable[[str], dict[str, Any]] | None = None
        self.dev_reload: Callable[[str], None] | None = None
        self.dev_resize: Callable[[int, int], None] | None = None
        self.config = config or WorkbenchConfig()
        self.base_env = dict(os.environ if base_env is None else base_env)
        self.stop_grace = stop_grace
        self._lock = threading.RLock()
        self._live: dict[str, LiveRun] = {}
        self._subs: set[Subscriber] = set()
        self._harnesses: dict[str, HarnessInfo] = {}
        self._dirty = threading.Event()
        self._closing = threading.Event()
        self.reconcile()
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
            return dict(self._harnesses)

    # --- snapshot -------------------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        latest = self.store.latest_runs()
        with self._lock:
            live = {
                sid: (lr.attention, lr.stop_requested, lr.phase) for sid, lr in self._live.items()
            }
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
            "environment": {
                "refusal": environment_refusal(self.base_env),
                "stripped_env": stripped_billing_env(self.base_env),
            },
        }

    def _session_view(
        self,
        session: dict[str, Any],
        run: dict[str, Any] | None,
        live: tuple[dict[str, Any] | None, bool, str] | None,
    ) -> dict[str, Any]:
        status = "new" if run is None else run["status"]
        attention, stopping, phase = live if live else (None, False, None)
        active = status in ("starting", "running")
        can_resume = bool(session["native_session_id"]) and (
            session["harness"] == CODEX or session["turns_observed"] > 0
        )
        view = {
            **session,
            "harness_label": LABELS.get(session["harness"], session["harness"]),
            "status": status,
            "active": active,
            "attached": live is not None,
            "stopping": stopping,
            "attention": attention,
            "phase": phase,
            "can_resume": (not active) and can_resume,
            "can_start_fresh": (not active) and session["turns_observed"] == 0,
            "run": None,
        }
        if run is not None:
            view["run"] = {
                k: run[k]
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
                )
            }
        return view

    def session_detail(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        runs = self.store.list_runs(session_id)
        return {
            "session": session,
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
    ) -> dict[str, Any]:
        project = self._project(project_id)
        if harness not in HARNESSES:
            raise BridgeError("INVALID_INPUT", f"unknown harness {harness!r}")
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
        )
        self.store.add_event(session["session_id"], None, "session_created", {"harness": harness})
        self._changed()
        if start:
            self.start_run(session["session_id"], "new")
        return self._session(session["session_id"])

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

    def start_run(self, session_id: str, kind: str) -> dict[str, Any]:
        session = self._session(session_id)
        harness = session["harness"]
        info = self._preflight(harness)
        assert info.binary is not None
        runs = self.store.list_runs(session_id)
        initial_prompt = None
        if kind == "resume":
            if not session["native_session_id"]:
                raise BridgeError("STATE_CONFLICT", "尚未观察到原生会话 ID，无法恢复")
            if harness == CLAUDE and session["turns_observed"] == 0:
                raise BridgeError(
                    "STATE_CONFLICT", "该 Claude Code 会话还没有对话，原生 CLI 中没有可恢复的内容"
                )
        elif kind == "new":
            if session["turns_observed"] > 0:
                raise BridgeError(
                    "STATE_CONFLICT", "该会话已有原生对话；请使用恢复，或在项目中新建会话"
                )
            if not runs:
                initial_prompt = self._handoff_prompt(session_id)
        else:
            raise BridgeError("INVALID_INPUT", f"unknown run kind {kind!r}")
        workdir = session["workdir"]
        if not os.path.isdir(workdir):
            raise BridgeError("PREFLIGHT_FAILED", f"工作目录不存在：{workdir}")
        run_id = "run_" + uuid.uuid4().hex[:12]
        run_dir = self.root / "runs" / run_id
        run_dir.mkdir(parents=True, mode=0o700)
        native_id = session["native_session_id"]
        if kind == "new" and runs:
            # Nothing was said in the earlier run(s): start a fresh native session for this slot.
            native_id = str(uuid.uuid4()) if harness == CLAUDE else None
            self.store.set_native(
                session_id, native_id, "preassigned" if harness == CLAUDE else "pending"
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
        )
        try:
            self.store.begin_run(
                run_id=run_id,
                session_id=session_id,
                kind=kind,
                workdir=workdir,
                argv=native_argv(spec),
                stripped_env=spec.stripped_env,
            )
        except WorkdirBusy as busy:
            shutil.rmtree(run_dir, ignore_errors=True)
            self.store.add_event(
                session_id, None, "writer_refused", {"busy_session_id": busy.session_id}
            )
            raise self._busy_error(busy) from None
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
            with self._lock:
                self._live.pop(session_id, None)
            live.buffer.close()
            failure = f"无法启动 {LABELS[harness]}：{exc.strerror or type(exc).__name__}"
            self.store.finish_run(run_id, status="failed", failure=failure)
            self.store.add_event(session_id, run_id, "run_failed", {"failure": failure})
            self._changed()
            raise BridgeError("EXECUTOR_ERROR", failure) from None
        self.store.mark_running(
            run_id, pid=process.pid, pgid=process.pid, birth=process_birth(process.pid)
        )
        self.store.add_event(
            session_id,
            run_id,
            "run_started",
            {
                "kind": kind,
                "argv": native_argv(spec),
                "stripped_env": spec.stripped_env,
                "native_session_id": spec.native_session_id,
                "handoff_prompt": initial_prompt is not None,
            },
        )
        self._changed()
        return self.store.get_run(run_id) or {}

    def stop(self, session_id: str) -> dict[str, Any]:
        self._session(session_id)
        with self._lock:
            live = self._live.get(session_id)
        if live is not None and live.process is not None:
            live.stop_requested = True
            self.store.mark_stop_requested(live.run_id)
            self.store.add_event(session_id, live.run_id, "stop_requested", {})
            self._changed()
            process = live.process
            threading.Thread(target=process.terminate, args=(self.stop_grace,), daemon=True).start()
            return {"stopping": True}
        runs = self.store.list_runs(session_id)
        run = runs[-1] if runs else None
        if run is None or run["status"] not in ("starting", "running"):
            return {"stopping": False}
        return self._stop_orphan(run)

    def _stop_orphan(self, run: dict[str, Any]) -> dict[str, Any]:
        """A run recorded as active by an earlier App instance (no PTY attached here)."""
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
            raise BridgeError("STATE_CONFLICT", "会话没有在本窗口中运行")
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
        if live is not None:
            offset, data = live.buffer.tail(limit)
            return {"run_id": live.run_id, "live": True, "offset": offset, "data": _b64(data)}
        runs = self.store.list_runs(session_id)
        if not runs:
            return {"run_id": None, "live": False, "offset": 0, "data": ""}
        run = runs[-1]
        data = read_log_tail(self.root / "runs" / run["run_id"] / "output.log", limit)
        return {"run_id": run["run_id"], "live": False, "offset": 0, "data": _b64(data)}

    def live_tails(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = list(self._live)
        return [{"session_id": sid, **self.output(sid)} for sid in sessions]

    def activity(self, session_id: str, after: int = 0) -> list[dict[str, Any]]:
        self._session(session_id)
        return self.store.list_events(session_id, after=after)

    def changes(self, session_id: str) -> dict[str, Any]:
        return changes.status(self._session(session_id)["workdir"])

    def diff(self, session_id: str, path: str) -> dict[str, Any]:
        workdir = self._session(session_id)["workdir"]
        if not path or os.path.isabs(path) or "\0" in path:
            raise BridgeError("INVALID_INPUT", "path must be relative to the working directory")
        target = os.path.realpath(os.path.join(workdir, path))
        if not (target + os.sep).startswith(workdir.rstrip(os.sep) + os.sep):
            raise BridgeError("INVALID_INPUT", "path is outside the working directory")
        return changes.diff(workdir, path)

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
                self.store.finish_run(
                    run["run_id"],
                    status="interrupted",
                    exit_confirmed=True,
                    failure="RepoBridge 退出时会话仍在运行；可用原生恢复继续",
                    output_tail=strip_ansi_tail(
                        read_log_tail(self.root / "runs" / run["run_id"] / "output.log", 65536)
                    ),
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
        threads = []
        for live in lives:
            if live.process is None:
                continue
            live.stop_requested = True
            self.store.mark_stop_requested(live.run_id)
            t = threading.Thread(target=live.process.terminate, args=(self.stop_grace,))
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout)
        self._closing.set()
        self._notifier.join(2)
        self.store.close()

    # --- PTY callbacks --------------------------------------------------------------------------

    def _on_output(self, live: LiveRun, data: bytes) -> None:
        if live.phase == "starting":
            live.phase = "running"
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
        if source == "claude-hook" and (
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
        _, tail = live.buffer.tail(65536)
        live.buffer.close()
        if not info.confirmed:
            failure = f"退出不明：进程组仍有成员 {info.remaining_group}"
            self.store.note_failure(live.run_id, failure)
            self.store.add_event(live.session_id, live.run_id, "exit_unconfirmed", {})
        else:
            if live.stop_requested:
                status, failure = "stopped", None
            elif info.exit_code == 0:
                status, failure = "exited", None
            else:
                status, failure = "failed", _exit_reason(info)
            self.store.finish_run(
                live.run_id,
                status=status,
                exit_code=info.exit_code,
                exit_signal=info.exit_signal,
                exit_confirmed=True,
                failure=failure,
                output_tail=strip_ansi_tail(tail),
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
                },
            )
        with self._lock:
            if self._live.get(live.session_id) is live:
                del self._live[live.session_id]
        self._publish("ended", {"session_id": live.session_id, "run_id": live.run_id})
        self._changed()

    # --- helpers --------------------------------------------------------------------------------

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
            details={"busy_session_id": busy.session_id},
        )

    @staticmethod
    def _is_active(runs: list[dict[str, Any]]) -> bool:
        return bool(runs) and runs[-1]["status"] in ("starting", "running")


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
