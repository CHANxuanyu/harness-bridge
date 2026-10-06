"""Generic foreground subprocess runner shared by executors and verifiers.

Responsibilities (adapters do not reimplement these):

* spawn with an argv list (no shell) in a **new session / process group** owned by this runner;
* feed stdin and drain stdout/stderr concurrently with a selector loop, so a chatty child can
  never deadlock on a full pipe;
* split stdout into lines on raw bytes (chunk boundaries cannot corrupt UTF-8 sequences);
* bounded capture (head + tail, tail prioritized) with total byte counts and SHA-256;
* wall timeout, cooperative stop (cancel / runner interrupt), TERM -> grace -> KILL of the owned
  process group, and an explicit ``group_exit_confirmed`` flag.

Only process groups this runner created are ever signalled. After the direct child exits and is
reaped, surviving members of its group (background processes) are terminated because the group
id cannot be reused while any member exists. Processes that left the group (``setsid``) are not
observable; if they keep our pipes open the outcome is reported as not confirmed.
"""

from __future__ import annotations

import hashlib
import os
import selectors
import signal
import socket
import subprocess
import sys
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProcessSpec:
    argv: list[str]
    cwd: str
    env: dict[str, str]
    stdin: bytes = b""


@dataclass
class RunLimits:
    wall_timeout: float
    kill_grace: float = 5.0
    kill_wait: float = 5.0
    max_line_bytes: int = 1024 * 1024
    stdout_head: int = 64 * 1024
    stdout_tail: int = 192 * 1024
    stderr_head: int = 32 * 1024
    stderr_tail: int = 96 * 1024
    drain_after_exit: float = 2.0
    poll_interval: float = 0.05
    stop_poll_interval: float = 0.25


class StreamCapture:
    """Keeps the first ``head`` bytes and a rolling tail of ``tail`` bytes of a stream."""

    def __init__(self, head: int, tail: int) -> None:
        self.head_limit = head
        self.tail_limit = tail
        self.head = bytearray()
        self.tail: deque[bytes] = deque()
        self.tail_size = 0
        self.total = 0
        self.sha = hashlib.sha256()

    def feed(self, data: bytes) -> None:
        self.total += len(data)
        self.sha.update(data)
        room = self.head_limit - len(self.head)
        if room > 0:
            self.head += data[:room]
            data = data[room:]
        if not data or self.tail_limit <= 0:
            return
        self.tail.append(data)
        self.tail_size += len(data)
        while self.tail_size - len(self.tail[0]) >= self.tail_limit:
            self.tail_size -= len(self.tail.popleft())

    def render(self) -> bytes:
        tail = b"".join(self.tail)
        if len(tail) > self.tail_limit:
            tail = tail[-self.tail_limit :]
        omitted = self.total - len(self.head) - len(tail)
        if omitted <= 0:
            return bytes(self.head) + tail
        marker = f"\n[... {omitted} bytes omitted by hbridge ...]\n".encode()
        return bytes(self.head) + marker + tail

    def meta(self) -> dict[str, Any]:
        rendered_len = len(self.head) + min(self.tail_size, self.tail_limit)
        return {
            "original_bytes": self.total,
            "stored_bytes": rendered_len,
            "truncated": rendered_len < self.total,
            "sha256": self.sha.hexdigest(),
        }


@dataclass
class ProcessOutcome:
    pid: int | None = None
    pgid: int | None = None
    returncode: int | None = None
    exit_signal: int | None = None
    spawn_error: str | None = None
    timed_out: bool = False
    stop_reason: str | None = None  # "cancelled" | "interrupted"
    group_exit_confirmed: bool = False
    background_killed: bool = False
    pipes_held_open: bool = False
    term_sent: bool = False
    kill_sent: bool = False
    lines: int = 0
    oversized_lines: int = 0
    started_at: float = 0.0
    ended_at: float = 0.0
    stdout: StreamCapture = field(default_factory=lambda: StreamCapture(0, 0))
    stderr: StreamCapture = field(default_factory=lambda: StreamCapture(0, 0))

    @property
    def duration(self) -> float:
        return max(0.0, self.ended_at - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "pgid": self.pgid,
            "returncode": self.returncode,
            "exit_signal": self.exit_signal,
            "spawn_error": self.spawn_error,
            "timed_out": self.timed_out,
            "stop_reason": self.stop_reason,
            "group_exit_confirmed": self.group_exit_confirmed,
            "background_killed": self.background_killed,
            "pipes_held_open": self.pipes_held_open,
            "term_sent": self.term_sent,
            "kill_sent": self.kill_sent,
            "stdout_lines": self.lines,
            "oversized_lines": self.oversized_lines,
            "duration_seconds": round(self.duration, 3),
            "stdout": self.stdout.meta(),
            "stderr": self.stderr.meta(),
        }


# --- process group inspection ------------------------------------------------------------------


def _linux_group_members(pgid: int) -> list[tuple[int, str]] | None:
    proc = Path("/proc")
    if not (proc / "self" / "stat").exists():
        return None
    members: list[tuple[int, str]] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text()
        except OSError:
            continue
        rest = raw[raw.rfind(")") + 2 :].split()
        # rest[0]=state, rest[1]=ppid, rest[2]=pgrp
        if len(rest) > 2 and int(rest[2]) == pgid:
            members.append((int(entry.name), rest[0]))
    return members


def _ps_group_members(pgid: int) -> list[tuple[int, str]] | None:
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,pgid=,stat="],
            capture_output=True,
            timeout=10,
            check=False,
        ).stdout.decode()
    except (OSError, subprocess.TimeoutExpired):
        return None
    members = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1].isdigit() and int(parts[1]) == pgid:
            members.append((int(parts[0]), parts[2]))
    return members


def group_alive(pgid: int) -> bool:
    """True if any non-zombie process is still in process group ``pgid``."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    members = _linux_group_members(pgid)
    if members is None:
        members = _ps_group_members(pgid)
    if members is None:
        return True  # cannot tell: assume alive (conservative)
    return any(not state.startswith("Z") for _, state in members)


# --- runner identity / liveness -----------------------------------------------------------------


def _boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


def process_start_marker(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        return "linux-starttime:" + raw[raw.rfind(")") + 2 :].split()[19]
    except (OSError, IndexError):
        pass
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = out.stdout.decode().strip()
    return f"ps-lstart:{text}" if out.returncode == 0 and text else None


def runner_identity() -> dict[str, Any]:
    pid = os.getpid()
    return {
        "pid": pid,
        "start_marker": process_start_marker(pid),
        "hostname": socket.gethostname(),
        "boot_id": _boot_id(),
        "token": uuid.uuid4().hex,
        "platform": sys.platform,
    }


def runner_alive(identity: dict[str, Any] | None) -> bool | None:
    """True/False if the recorded runner process is (not) alive; None if it cannot be decided."""
    if not identity:
        return None
    if identity.get("hostname") != socket.gethostname():
        return None
    boot = _boot_id()
    if boot and identity.get("boot_id") and boot != identity["boot_id"]:
        return False
    pid = identity.get("pid")
    if not isinstance(pid, int):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    if _is_zombie(pid):
        return False
    marker = process_start_marker(pid)
    if marker is None or identity.get("start_marker") is None:
        return None
    return bool(marker == identity["start_marker"])


def _is_zombie(pid: int) -> bool:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        return raw[raw.rfind(")") + 2 :].split()[0] == "Z"
    except (OSError, IndexError):
        pass
    try:
        out = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.stdout.decode().strip().startswith("Z")


# --- the runner ---------------------------------------------------------------------------------


def run_process(
    spec: ProcessSpec,
    limits: RunLimits,
    *,
    on_spawn: Callable[[int, int], None] | None = None,
    on_line: Callable[[bytes, bool], None] | None = None,
    should_stop: Callable[[], str | None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> ProcessOutcome:
    out = ProcessOutcome(
        stdout=StreamCapture(limits.stdout_head, limits.stdout_tail),
        stderr=StreamCapture(limits.stderr_head, limits.stderr_tail),
    )
    out.started_at = monotonic()
    try:
        proc = subprocess.Popen(
            spec.argv,
            cwd=spec.cwd,
            env=spec.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
            bufsize=0,
        )
    except OSError as exc:
        out.spawn_error = f"{type(exc).__name__}: {exc.strerror or exc}"
        out.ended_at = monotonic()
        out.group_exit_confirmed = True  # nothing was started
        return out

    out.pid = proc.pid
    out.pgid = proc.pid  # start_new_session => the child leads its own group
    assert proc.stdin and proc.stdout and proc.stderr

    def terminate_now() -> None:
        _hard_stop(proc, out, limits, monotonic)

    if on_spawn is not None:
        try:
            on_spawn(out.pid, out.pgid)
        except BaseException:
            terminate_now()
            raise

    sel = selectors.DefaultSelector()
    stdin_buf = memoryview(spec.stdin)
    stdin_fd = proc.stdin.fileno()
    os.set_blocking(stdin_fd, False)
    if stdin_buf:
        sel.register(stdin_fd, selectors.EVENT_WRITE, "stdin")
    else:
        proc.stdin.close()
    sel.register(proc.stdout.fileno(), selectors.EVENT_READ, "stdout")
    sel.register(proc.stderr.fileno(), selectors.EVENT_READ, "stderr")
    open_readers = 2
    line_buf = bytearray()
    line_overflow = False

    def emit_line(data: bytes, truncated: bool) -> None:
        out.lines += 1
        if truncated:
            out.oversized_lines += 1
        if on_line is not None:
            on_line(data, truncated)

    def handle_stdout(chunk: bytes) -> None:
        nonlocal line_overflow
        out.stdout.feed(chunk)
        start = 0
        while True:
            nl = chunk.find(b"\n", start)
            if nl < 0:
                piece = chunk[start:]
                if not line_overflow:
                    line_buf.extend(piece)
                    if len(line_buf) > limits.max_line_bytes:
                        del line_buf[limits.max_line_bytes :]
                        line_overflow = True
                return
            piece = chunk[start:nl]
            if not line_overflow:
                line_buf.extend(piece)
                if len(line_buf) > limits.max_line_bytes:
                    del line_buf[limits.max_line_bytes :]
                    line_overflow = True
            emit_line(bytes(line_buf), line_overflow)
            line_buf.clear()
            line_overflow = False
            start = nl + 1

    deadline = out.started_at + limits.wall_timeout
    next_stop_poll = out.started_at
    phase: str | None = None  # None | "term" | "kill" | "gave_up"
    phase_deadline = 0.0
    child_exit_at: float | None = None
    group_dead = False

    def begin_termination(now: float) -> None:
        nonlocal phase, phase_deadline
        if phase is not None:
            return
        try:
            os.killpg(out.pgid or proc.pid, signal.SIGTERM)
            out.term_sent = True
        except ProcessLookupError:
            pass
        phase = "term"
        phase_deadline = now + limits.kill_grace

    while True:
        now = monotonic()
        timeout = limits.poll_interval
        for key, _mask in sel.select(timeout):
            tag = key.data
            if tag == "stdin":
                try:
                    n = os.write(stdin_fd, stdin_buf[:65536])
                    stdin_buf = stdin_buf[n:]
                except BlockingIOError:
                    n = 0
                except (BrokenPipeError, OSError):
                    stdin_buf = stdin_buf[:0]
                if not stdin_buf:
                    sel.unregister(stdin_fd)
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                continue
            stream = proc.stdout if tag == "stdout" else proc.stderr
            try:
                chunk = os.read(stream.fileno(), 65536)
            except OSError:
                chunk = b""
            if not chunk:
                sel.unregister(stream.fileno())
                open_readers -= 1
                continue
            if tag == "stdout":
                handle_stdout(chunk)
            else:
                out.stderr.feed(chunk)

        now = monotonic()
        if proc.poll() is not None and child_exit_at is None:
            child_exit_at = now

        if phase is None and child_exit_at is None:
            if now >= deadline:
                out.timed_out = True
                begin_termination(now)
            elif should_stop is not None and now >= next_stop_poll:
                next_stop_poll = now + limits.stop_poll_interval
                reason = should_stop()
                if reason:
                    out.stop_reason = reason
                    begin_termination(now)

        if child_exit_at is not None and not group_dead:
            group_dead = not group_alive(out.pgid or proc.pid)
            if not group_dead and phase is None:
                out.background_killed = True
                begin_termination(now)

        if phase == "term" and now >= phase_deadline:
            if child_exit_at is None or not group_dead:
                try:
                    os.killpg(out.pgid or proc.pid, signal.SIGKILL)
                    out.kill_sent = True
                except ProcessLookupError:
                    pass
            phase = "kill"
            phase_deadline = now + limits.kill_wait
        elif (
            phase == "kill" and now >= phase_deadline and (child_exit_at is None or not group_dead)
        ):
            phase = "gave_up"
            break

        if child_exit_at is not None and group_dead:
            if open_readers == 0:
                break
            if now - child_exit_at > limits.drain_after_exit:
                out.pipes_held_open = True
                break

    if line_buf:
        emit_line(bytes(line_buf), line_overflow)
    sel.close()
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        try:
            stream.close()
        except OSError:
            pass
    rc = proc.poll()
    out.returncode = rc
    if rc is not None and rc < 0:
        out.exit_signal = -rc
    out.group_exit_confirmed = (
        rc is not None and group_dead and phase != "gave_up" and not out.pipes_held_open
    )
    out.ended_at = monotonic()
    return out


def _hard_stop(
    proc: subprocess.Popen[bytes],
    out: ProcessOutcome,
    limits: RunLimits,
    monotonic: Callable[[], float],
) -> None:
    """Synchronous TERM -> grace -> KILL used when a spawn callback fails."""
    pgid = out.pgid or proc.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
        out.term_sent = True
    except ProcessLookupError:
        pass
    end = monotonic() + limits.kill_grace
    while monotonic() < end:
        proc.poll()
        if not group_alive(pgid):
            break
        time.sleep(0.05)
    if group_alive(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
            out.kill_sent = True
        except ProcessLookupError:
            pass
        end = monotonic() + limits.kill_wait
        while monotonic() < end and group_alive(pgid):
            proc.poll()
            time.sleep(0.05)
    out.returncode = proc.poll()
    out.group_exit_confirmed = out.returncode is not None and not group_alive(pgid)
    out.ended_at = monotonic()
