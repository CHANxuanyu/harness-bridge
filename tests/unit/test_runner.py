"""Runner tests with real OS subprocesses (no mocks of subprocess/os)."""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

from harness_bridge.runner import (
    ProcessSpec,
    RunLimits,
    StreamCapture,
    group_alive,
    run_process,
    runner_alive,
    runner_identity,
)

PY = sys.executable


def alive(pid: int) -> bool:
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists():
        try:
            raw = stat.read_text()
        except OSError:
            return False
        return raw[raw.rfind(")") + 2 :].split()[0] != "Z"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def spec(code: str, stdin: bytes = b"") -> ProcessSpec:
    return ProcessSpec(argv=[PY, "-c", code], cwd=os.getcwd(), env=dict(os.environ), stdin=stdin)


def test_stream_capture_keeps_head_and_tail() -> None:
    cap = StreamCapture(head=10, tail=10)
    for i in range(100):
        cap.feed(f"{i:03d}\n".encode())
    rendered = cap.render()
    assert rendered.startswith(b"000\n001\n00")
    assert rendered.endswith(b"098\n099\n")
    meta = cap.meta()
    assert meta["original_bytes"] == 400 and meta["truncated"] is True
    assert b"bytes omitted by hbridge" in rendered


def test_lines_survive_arbitrary_chunk_boundaries_with_utf8() -> None:
    # A06: write a multi-byte UTF-8 JSON line one byte at a time with flushes in between.
    code = (
        "import sys,time\n"
        "data='{\"msg\": \"héllo – 世界\"}\\n'.encode('utf-8')\n"
        "for b in data:\n"
        "    sys.stdout.buffer.write(bytes([b])); sys.stdout.buffer.flush(); time.sleep(0.002)\n"
    )
    lines: list[bytes] = []
    out = run_process(spec(code), RunLimits(wall_timeout=20), on_line=lambda b, t: lines.append(b))
    assert out.returncode == 0 and out.group_exit_confirmed
    assert lines == ['{"msg": "héllo – 世界"}'.encode()]


def test_large_interleaved_output_does_not_deadlock() -> None:
    # A05: 4 MiB on each stream; pipes must be drained concurrently.
    code = (
        "import sys\n"
        "chunk='y'*1023+'\\n'\n"
        "for i in range(4096):\n"
        "    sys.stdout.write(chunk); sys.stderr.write(chunk)\n"
    )
    limits = RunLimits(
        wall_timeout=60, stdout_head=1024, stdout_tail=4096, stderr_head=1024, stderr_tail=4096
    )
    out = run_process(spec(code), limits)
    assert out.returncode == 0 and not out.timed_out
    assert out.stdout.meta()["original_bytes"] == 4096 * 1024
    assert out.stderr.meta()["original_bytes"] == 4096 * 1024
    assert out.stdout.meta()["truncated"] and len(out.stdout.render()) < 8192
    assert out.lines == 4096


def test_stdin_is_delivered() -> None:
    payload = b"x" * 300_000  # larger than a pipe buffer
    out = run_process(
        spec("import sys; print(len(sys.stdin.buffer.read()))", stdin=payload),
        RunLimits(wall_timeout=20),
    )
    assert out.stdout.render().strip() == b"300000"


def test_timeout_kills_whole_process_group() -> None:
    # C07: the child starts a grandchild in the same group and both ignore nothing.
    code = (
        "import subprocess,sys,time\n"
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        "print(p.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    lines: list[bytes] = []
    started = time.monotonic()
    out = run_process(
        spec(code),
        RunLimits(wall_timeout=1.0, kill_grace=0.5),
        on_line=lambda b, t: lines.append(b),
    )
    assert time.monotonic() - started < 15
    assert out.timed_out and out.term_sent
    assert out.group_exit_confirmed
    grandchild = int(lines[0])
    assert not alive(grandchild)
    assert out.pgid is not None and not group_alive(out.pgid)


def test_term_ignoring_child_is_killed() -> None:
    code = (
        "import signal,time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('ready', flush=True)\n"
        "time.sleep(60)\n"
    )
    out = run_process(spec(code), RunLimits(wall_timeout=0.8, kill_grace=0.3))
    assert out.timed_out and out.kill_sent and out.group_exit_confirmed
    assert out.exit_signal == signal.SIGKILL


def test_background_process_left_in_group_is_terminated() -> None:
    code = (
        "import subprocess,sys\n"
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],"
        " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "print(p.pid, flush=True)\n"
    )
    lines: list[bytes] = []
    out = run_process(
        spec(code), RunLimits(wall_timeout=20, kill_grace=0.5), on_line=lambda b, t: lines.append(b)
    )
    assert out.returncode == 0
    assert out.background_killed and out.group_exit_confirmed
    assert not alive(int(lines[0]))


def test_process_escaping_the_group_is_reported_unconfirmed() -> None:
    code = (
        "import subprocess,sys\n"
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
        " start_new_session=True)\n"
        "print(p.pid, flush=True)\n"
    )
    lines: list[bytes] = []
    out = run_process(
        spec(code),
        RunLimits(wall_timeout=20, drain_after_exit=0.5),
        on_line=lambda b, t: lines.append(b),
    )
    escaped = int(lines[0])
    try:
        assert out.returncode == 0
        assert out.pipes_held_open
        assert out.group_exit_confirmed is False
    finally:
        os.kill(escaped, signal.SIGKILL)


def test_spawn_failure_is_definite() -> None:
    out = run_process(
        ProcessSpec(argv=["/nonexistent/hbridge-binary"], cwd=os.getcwd(), env={}),
        RunLimits(wall_timeout=5),
    )
    assert out.spawn_error and out.pid is None and out.group_exit_confirmed


def test_cooperative_stop_terminates() -> None:
    started = time.monotonic()
    out = run_process(
        spec("import time; time.sleep(60)"),
        RunLimits(wall_timeout=60, kill_grace=0.5, stop_poll_interval=0.05),
        should_stop=lambda: "cancelled" if time.monotonic() - started > 0.3 else None,
    )
    assert out.stop_reason == "cancelled" and out.group_exit_confirmed and not out.timed_out


def test_oversized_line_is_flagged() -> None:
    flags: list[bool] = []
    out = run_process(
        spec("print('z'*5000); print('ok')"),
        RunLimits(wall_timeout=10, max_line_bytes=100),
        on_line=lambda b, t: flags.append(t),
    )
    assert flags == [True, False] and out.oversized_lines == 1


def test_runner_identity_liveness() -> None:
    me = runner_identity()
    assert runner_alive(me) is True
    dead = dict(me, pid=2**22 + 12345)
    assert runner_alive(dead) in (False, None)
    reused = dict(me, start_marker="linux-starttime:0")
    assert runner_alive(reused) is False
