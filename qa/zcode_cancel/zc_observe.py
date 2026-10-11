"""Observer plugin for test_cancel_stops_both_transport_and_peer (investigation only).

Loaded with ``-p zc_observe``; changes no test, fixture or product code path. It samples only
processes this test creates (descendants of the pytest process, found through
/proc/<pid>/task/<tid>/children, plus the peer PID the test itself reads from rpc.jsonl) and,
after reparenting, the identity of the process that becomes their parent (the reaper). Per
process it records pid, ppid, pgid, sid, state, comm (kernel 15-char name) and starttime
(clock ticks since boot). It never reads cmdline, environ or any other process.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest

TARGET = "test_cancel_stops_both_transport_and_peer"
OUT = Path(os.environ.get("ZC_OBS_OUT", "zc-observe.json"))
MARKERS = ("CLAUDE_CODE_REMOTE", "CLAUDE_CODE_REMOTE_SESSION_ID", "CODEX_CLOUD", "CLAUDECODE")
INVOKING_MARKERS = {m: bool(os.environ.get(m)) for m in MARKERS}  # at plugin import


def stat(pid: int) -> dict[str, Any] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    rest = raw[raw.rfind(")") + 2 :].split()
    return {
        "pid": pid,
        "comm": raw[raw.index("(") + 1 : raw.rfind(")")][:15],
        "state": rest[0],
        "ppid": int(rest[1]),
        "pgid": int(rest[2]),
        "sid": int(rest[3]),
        "starttime": int(rest[19]),
    }


def children(pid: int) -> list[int]:
    out: list[int] = []
    try:
        tids = os.listdir(f"/proc/{pid}/task")
    except OSError:
        return out
    for tid in tids:
        try:
            out += [int(x) for x in Path(f"/proc/{pid}/task/{tid}/children").read_text().split()]
        except OSError:
            continue
    return out


def probe_kill(pid: int) -> str:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "ProcessLookupError"
    except PermissionError:
        return "PermissionError"
    return "no-exception"


def probe_killpg(pgid: int) -> str:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return "ProcessLookupError"
    except PermissionError:
        return "PermissionError"
    return "no-exception"


class Observer:
    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.me = os.getpid()
        self.log: Path | None = None
        self.tracked: dict[int, dict[str, Any]] = {}  # pid -> first-seen identity
        self.last: dict[int, Any] = {}
        self.transitions: list[dict[str, Any]] = []
        self.snapshots: dict[str, Any] = {}
        self.reapers: dict[int, dict[str, Any] | None] = {}
        self.peer_pids: list[int] = []
        self.samples = 0
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def now(self) -> float:
        return round((time.monotonic() - self.t0) * 1000, 1)

    def discover(self) -> None:
        stack, seen = [self.me], set()
        while stack:
            pid = stack.pop()
            for child in children(pid):
                if child in seen:
                    continue
                seen.add(child)
                stack.append(child)
                if child not in self.tracked:
                    first = stat(child)
                    if first is not None:
                        self.tracked[child] = {**first, "first_seen_ms": self.now()}
        if self.log is not None and self.log.exists():
            try:
                lines = self.log.read_text().splitlines()
            except OSError:
                lines = []
            for line in lines:
                try:
                    pid = int(json.loads(line)["pid"])
                except (ValueError, KeyError, TypeError):
                    continue
                if pid not in self.peer_pids:
                    self.peer_pids.append(pid)
                if pid not in self.tracked:
                    first = stat(pid)
                    if first is not None:
                        self.tracked[pid] = {**first, "first_seen_ms": self.now(), "via": "log"}

    def sample(self) -> None:
        with self.lock:
            self.discover()
            self.samples += 1
            for pid, first in self.tracked.items():
                cur = stat(pid)
                if cur is not None and cur["starttime"] != first["starttime"]:
                    view: Any = {"reused_by": cur}
                elif cur is None:
                    view = "gone"
                else:
                    view = {k: cur[k] for k in ("state", "ppid", "pgid")}
                    if (
                        cur["ppid"] not in self.reapers
                        and cur["ppid"] not in self.tracked
                        and cur["ppid"] != self.me
                    ):
                        parent = stat(cur["ppid"])
                        self.reapers[cur["ppid"]] = parent and {
                            k: parent[k] for k in ("pid", "comm", "state", "ppid")
                        }
                if self.last.get(pid) != view:
                    self.transitions.append({"t_ms": self.now(), "pid": pid, "now": view})
                    self.last[pid] = view

    def snapshot(self, label: str) -> None:
        self.sample()
        with self.lock:
            procs = {}
            for pid, first in self.tracked.items():
                cur = stat(pid)
                procs[str(pid)] = {
                    "current": cur,
                    "same_start_identity": None
                    if cur is None
                    else cur["starttime"] == first["starttime"],
                    "kill0": probe_kill(pid),
                }
            pgids = sorted({f["pgid"] for f in self.tracked.values()})
            self.snapshots[label] = {
                "t_ms": self.now(),
                "processes": procs,
                "killpg0": {str(g): probe_killpg(g) for g in pgids},
            }

    def loop(self) -> None:
        while not self.stop.wait(0.01):
            self.sample()

    def report(self) -> dict[str, Any]:
        return {
            "pytest_pid": self.me,
            "tracked_first_seen": {str(k): v for k, v in self.tracked.items()},
            "peer_pids_from_log": self.peer_pids,
            "reaper_identities": {str(k): v for k, v in self.reapers.items()},
            "transitions": self.transitions,
            "snapshots": self.snapshots,
            "samples": self.samples,
        }


OBS: Observer | None = None
RESULT: dict[str, Any] = {"invoking_markers_present": INVOKING_MARKERS}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item: pytest.Item) -> Any:
    global OBS
    yield
    if item.name != TARGET:
        return
    import harness_bridge
    from harness_bridge.service import Bridge

    OBS = Observer()
    fx = item.funcargs.get("fx")  # type: ignore[attr-defined]
    OBS.log = Path(fx.base) / "rpc.jsonl" if fx is not None else None
    RESULT["import_path"] = harness_bridge.__file__
    RESULT["markers_inside_test_after_fixtures"] = {m: bool(os.environ.get(m)) for m in MARKERS}
    RESULT["pid1"] = (lambda s: s and {k: s[k] for k in ("pid", "comm", "state", "ppid")})(stat(1))
    original = Bridge.cancel

    def observed_cancel(self: Any, *args: Any, **kwargs: Any) -> Any:
        if OBS is not None:
            OBS.snapshot("before_cancel")
        result = original(self, *args, **kwargs)
        if OBS is not None:
            OBS.snapshot("after_cancel_returned")
        return result

    Bridge.cancel = observed_cancel  # type: ignore[method-assign]
    RESULT["_restore"] = (Bridge, original)
    OBS.thread.start()


def pytest_exception_interact(node: Any, call: Any, report: Any) -> None:
    if OBS is not None and getattr(node, "name", "") == TARGET and call.when == "call":
        OBS.snapshot("at_failed_assertion")
        RESULT["failure_type"] = call.excinfo.typename if call.excinfo else None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: Any) -> Any:
    yield
    if OBS is None or item.name != TARGET:
        return
    OBS.snapshot("after_fixture_teardown")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        time.sleep(0.25)
        OBS.sample()
    OBS.snapshot("teardown_plus_5s")
    OBS.stop.set()
    OBS.thread.join(2)
    bridge_cls, original = RESULT.pop("_restore")
    bridge_cls.cancel = original


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.nodeid.endswith(TARGET):
        RESULT.setdefault("phases", {})[report.when] = report.outcome


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    if OBS is not None:
        RESULT.update(OBS.report())
    RESULT["pytest_exitstatus"] = int(exitstatus)
    OUT.write_text(json.dumps(RESULT, indent=1, default=str))
