"""Detached tool lifecycles: real local subprocesses, never a native coding agent."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness_bridge import process_tree
from harness_bridge.process_tree import ProcessEntry, ProcessTree
from harness_bridge.runner import ProcessSpec, RunLimits, group_alive, run_process


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
@pytest.mark.parametrize("ignore_term", [False, True])
def test_stops_detached_tool_with_closed_pipes(stop: str, ignore_term: bool) -> None:
    child = "import time,signal; "
    if ignore_term:
        child += "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    child += "time.sleep(30)"
    code = (
        "import subprocess,sys,time; "
        f'p=subprocess.Popen([sys.executable,"-c",{child!r}],start_new_session=True,'
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        "print(p.pid,flush=True); time.sleep(30)"
    )
    pids: list[int] = []
    started = time.monotonic()
    out = run_process(
        ProcessSpec([sys.executable, "-c", code], str(Path.cwd()), dict(os.environ)),
        RunLimits(wall_timeout=0.8 if stop == "timeout" else 10, kill_grace=0.15),
        on_line=lambda line, _: pids.append(int(line)),
        should_stop=lambda: (
            "cancelled" if stop == "cancel" and time.monotonic() - started > 0.8 else None
        ),
    )
    try:
        assert pids and not group_alive(pids[0])
        assert out.group_exit_confirmed and out.descendants["observed_exits_confirmed"]
        assert pids[0] in out.descendants["signalled_descendants"]
        assert out.descendants["remaining_descendants"] == []
        assert out.kill_sent == ignore_term
        assert out.timed_out == (stop == "timeout")
        assert (out.stop_reason == "cancelled") == (stop == "cancel")
    finally:
        for pid in pids:
            if group_alive(pid):
                os.killpg(pid, signal.SIGKILL)


def test_normal_exit_cannot_confirm_observed_detached_survivor() -> None:
    code = (
        "import subprocess,sys,time; "
        'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],'
        "start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        "print(p.pid,flush=True); time.sleep(0.5)"
    )
    pids: list[int] = []
    out = run_process(
        ProcessSpec([sys.executable, "-c", code], str(Path.cwd()), dict(os.environ)),
        RunLimits(wall_timeout=5),
        on_line=lambda line, _: pids.append(int(line)),
    )
    try:
        assert out.returncode == 0 and not out.pipes_held_open
        assert not out.group_exit_confirmed
        assert out.descendants["remaining_descendants"] == pids
    finally:
        for pid in pids:
            if group_alive(pid):
                os.killpg(pid, signal.SIGKILL)


def test_failed_inspection_cannot_confirm_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process_tree, "process_table", lambda: None)
    out = run_process(
        ProcessSpec([sys.executable, "-c", "pass"], str(Path.cwd()), dict(os.environ)),
        RunLimits(wall_timeout=5),
    )
    assert out.returncode == 0 and not out.group_exit_confirmed
    assert out.descendants["inspection_failed"] is True


def test_reused_pid_never_signalled_or_used_as_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    table = {10: ProcessEntry(10, 1, 10, "S", "root"), 11: ProcessEntry(11, 10, 11, "S", "child")}
    monkeypatch.setattr(process_tree, "process_table", lambda: dict(table))
    tracker = ProcessTree(10)
    assert tracker.remaining() == [11]
    table[11] = ProcessEntry(11, 1, 11, "S", "different-process")
    table[12] = ProcessEntry(12, 11, 12, "S", "unrelated-child")
    sent: list[int] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append(pid))
    tracker.signal_detached(signal.SIGTERM)
    assert sent == [] and tracker.remaining() == []
    assert 12 not in tracker.known


def test_revalidate_identity_immediately_before_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    table = {10: ProcessEntry(10, 1, 10, "S", "root"), 11: ProcessEntry(11, 10, 11, "S", "child")}
    monkeypatch.setattr(process_tree, "process_table", lambda: dict(table))
    tracker = ProcessTree(10)
    snapshots = iter([dict(table), {10: table[10], 11: ProcessEntry(11, 1, 11, "S", "reused")}])
    monkeypatch.setattr(process_tree, "process_table", lambda: next(snapshots))
    sent: list[int] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append(pid))
    tracker.signal_detached(signal.SIGTERM)
    assert sent == []


def test_inspection_failure_stays_unconfirmed_after_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process_tree, "process_table", lambda: None)
    tracker = ProcessTree(10)
    monkeypatch.setattr(process_tree, "process_table", lambda: {})
    tracker.refresh()
    assert not tracker.confirmed()


def test_failed_ps_does_not_mean_empty_process_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "exists", lambda self: False)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1, "", "")
    )
    assert process_tree.process_table() is None
