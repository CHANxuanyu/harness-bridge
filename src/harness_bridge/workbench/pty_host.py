"""PTY hosting for native interactive CLIs: spawn, read, write, resize, stop, observe exit.

The child is a new session/process-group leader with the PTY as its controlling terminal (see
``harness._CTTY_EXEC``). Stop mimics closing a terminal (SIGHUP to the group), escalating to
SIGTERM/SIGKILL. Exit is "confirmed" only when the root has been reaped and no live member of
its original process group remains; detached daemons that left the group are not ours to kill.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import select
import signal
import struct
import subprocess
import termios
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness_bridge.process_tree import process_table
from harness_bridge.workbench.harness import LaunchSpec

READ_CHUNK = 65536
_ANSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")


def strip_ansi_tail(data: bytes, lines: int = 20, limit: int = 4000) -> str:
    text = re.sub(r"\r+\n", "\n", _ANSI.sub(b"", data).decode("utf-8", "replace"))
    # A bare CR returns to column 0: keep what was drawn last on that line.
    text = "\n".join(line.rsplit("\r", 1)[-1] for line in text.split("\n"))
    kept = [line.rstrip() for line in text.split("\n") if line.strip()]
    return "\n".join(kept[-lines:])[-limit:]


def group_members(pgid: int) -> list[int] | None:
    table = process_table()
    if table is None:
        return None
    return sorted(p.pid for p in table.values() if p.group == pgid and not p.state.startswith("Z"))


def process_birth(pid: int) -> str | None:
    table = process_table()
    if table is None or pid not in table:
        return None
    return table[pid].birth


def alive_with_birth(pid: int, birth: str | None) -> bool | None:
    """True/False when observable; None when the process table cannot be read."""
    table = process_table()
    if table is None:
        return None
    entry = table.get(pid)
    if entry is None or entry.state.startswith("Z"):
        return False
    return birth is None or entry.birth == birth


class OutputBuffer:
    """In-memory tail for live replay plus a capped on-disk log for history after restart."""

    def __init__(self, log_path: Path, *, keep: int = 1 << 20, log_cap: int = 16 << 20) -> None:
        self.log_path = log_path
        self.keep = keep
        self.log_cap = log_cap
        self.total = 0
        self.log_truncated = False
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._log = open(log_path, "ab")  # noqa: SIM115 - closed explicitly in close()

    def append(self, data: bytes) -> int:
        with self._lock:
            offset = self.total
            self.total += len(data)
            self._buf += data
            if len(self._buf) > self.keep:
                del self._buf[: len(self._buf) - self.keep]
            if not self.log_truncated:
                if self._log.tell() + len(data) > self.log_cap:
                    self.log_truncated = True
                else:
                    self._log.write(data)
                    self._log.flush()
            return offset

    def tail(self, limit: int = 256 << 10) -> tuple[int, bytes]:
        with self._lock:
            data = bytes(self._buf[-limit:])
            return self.total - len(data), data

    def close(self) -> None:
        with self._lock:
            self._log.close()


def read_log_tail(path: Path, limit: int = 256 << 10) -> bytes:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - limit))
            return fh.read()
    except OSError:
        return b""


class OscScanner:
    """Extract OSC 9 desktop-notification payloads (``ESC ] 9 ; text BEL|ST``) from a stream."""

    _START = b"\x1b]9;"

    def __init__(self) -> None:
        self._carry = b""

    def feed(self, data: bytes) -> list[str]:
        buf = self._carry + data
        found: list[str] = []
        pos = 0
        while True:
            start = buf.find(self._START, pos)
            if start < 0:
                keep = max(len(buf) - (len(self._START) - 1), pos)
                self._carry = buf[keep:]
                break
            body = start + len(self._START)
            ends = [i for i in (buf.find(b"\x07", body), buf.find(b"\x1b\\", body)) if i >= 0]
            if not ends:
                self._carry = buf[start:] if len(buf) - start < 8192 else b""
                break
            end = min(ends)
            text = buf[body:end].decode("utf-8", "replace")
            # ConEmu-style progress reports reuse OSC 9 with a numeric sub-command.
            if not re.match(r"^\d;", text):
                found.append(text[:400])
            pos = end + (1 if buf[end : end + 1] == b"\x07" else 2)
        return found


class JsonlTail:
    """Incrementally read complete JSON lines appended by the side-channel relay."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.position = 0
        self._partial = b""

    def poll(self) -> list[dict[str, Any]]:
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.position)
                chunk = fh.read(1 << 20)
        except FileNotFoundError:
            return []
        if not chunk:
            return []
        self.position += len(chunk)
        data = self._partial + chunk
        *lines, self._partial = data.split(b"\n")
        records = []
        for line in lines:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records


@dataclass(frozen=True)
class ExitInfo:
    exit_code: int | None
    exit_signal: int | None
    confirmed: bool
    remaining_group: list[int]


class PtyProcess:
    def __init__(
        self,
        spec: LaunchSpec,
        *,
        cols: int = 120,
        rows: int = 32,
        on_output: Callable[[bytes], None],
        on_tick: Callable[[], None],
        on_exit: Callable[[ExitInfo], None],
    ) -> None:
        self.spec = spec
        self.cols, self.rows = cols, rows
        self._on_output = on_output
        self._on_tick = on_tick
        self._on_exit = on_exit
        self._master = -1
        self._write_lock = threading.Lock()
        self._exited = threading.Event()
        self._stop_lock = threading.Lock()
        self.proc: subprocess.Popen[bytes] | None = None
        self.exit_info: ExitInfo | None = None
        self._thread: threading.Thread | None = None

    @property
    def pid(self) -> int:
        assert self.proc is not None
        return self.proc.pid

    def start(self) -> None:
        master, slave = os.openpty()
        try:
            _set_winsize(slave, self.cols, self.rows)
            self.proc = subprocess.Popen(
                self.spec.argv,
                cwd=self.spec.cwd,
                env=self.spec.env,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
                close_fds=True,
            )
        except BaseException:
            os.close(master)
            os.close(slave)
            raise
        os.close(slave)
        self._master = master
        self._thread = threading.Thread(target=self._pump, name=f"pty-{self.pid}", daemon=True)
        self._thread.start()

    def write(self, data: bytes) -> None:
        if self._exited.is_set() or self._master < 0:
            raise OSError(errno.EPIPE, "session process has exited")
        with self._write_lock:
            view = memoryview(data)
            while view:
                written = os.write(self._master, view)
                view = view[written:]

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        if self._master >= 0 and not self._exited.is_set():
            _set_winsize(self._master, cols, rows)

    def wait(self, timeout: float | None = None) -> bool:
        return self._exited.wait(timeout)

    def terminate(self, grace: float = 3.0) -> ExitInfo | None:
        """Hang up the session's process group, escalating; returns exit info if reaped."""
        with self._stop_lock:
            pgid = self.pid
            for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGKILL):
                if self._exited.is_set() and not group_members(pgid):
                    break
                try:
                    os.killpg(pgid, sig)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    break
                self._exited.wait(grace)
                if self._exited.is_set() and not group_members(pgid):
                    break
            self._exited.wait(grace)
            return self.exit_info

    def _pump(self) -> None:
        assert self.proc is not None
        master = self._master
        try:
            while True:
                try:
                    ready, _, _ = select.select([master], [], [], 0.25)
                except InterruptedError:
                    continue
                if ready:
                    try:
                        data = os.read(master, READ_CHUNK)
                    except OSError as exc:
                        if exc.errno not in (errno.EIO, errno.EBADF):
                            raise
                        data = b""
                    if not data:
                        break
                    self._on_output(data)
                elif self.proc.poll() is not None:
                    self._drain(master)
                    break
                self._on_tick()
        finally:
            code = self.proc.wait()
            pgid = self.proc.pid
            remaining = group_members(pgid)
            if remaining:
                # The leader is gone; its tty session is over. Hang up what stayed in the group.
                for sig in (signal.SIGHUP, signal.SIGKILL):
                    try:
                        os.killpg(pgid, sig)
                    except (ProcessLookupError, PermissionError):
                        break
                    if _wait_group_empty(pgid, 2.0):
                        break
                remaining = group_members(pgid)
            self._on_tick()
            with self._write_lock:
                os.close(master)
                self._master = -1
            self.exit_info = ExitInfo(
                exit_code=code if code >= 0 else None,
                exit_signal=-code if code < 0 else None,
                confirmed=remaining == [],
                remaining_group=remaining or [],
            )
            self._exited.set()
            self._on_exit(self.exit_info)

    def _drain(self, master: int) -> None:
        while True:
            ready, _, _ = select.select([master], [], [], 0)
            if not ready:
                return
            try:
                data = os.read(master, READ_CHUNK)
            except OSError:
                return
            if not data:
                return
            self._on_output(data)


def _wait_group_empty(pgid: int, timeout: float) -> bool:
    deadline = threading.Event()
    waited = 0.0
    while waited < timeout:
        if group_members(pgid) == []:
            return True
        deadline.wait(0.1)
        waited += 0.1
    return group_members(pgid) == []


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
