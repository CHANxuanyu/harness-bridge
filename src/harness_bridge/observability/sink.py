"""Bounded, non-blocking JSON-lines files with rotation, retention and a cross-process lock.

``submit`` never blocks and never raises: a full queue, a closed sink, a read-only or full disk
and a busy lock all drop records and count them. Only the background writer touches the disk.
Files are 0600 in a 0700 directory. A torn last line (crash or ENOSPC mid-write) is isolated by
starting the next batch on a new line; readers skip and count malformed lines.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import queue
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

MAX_LINE = 16 << 10


class JsonlSink:
    def __init__(
        self,
        directory: Path,
        stem: str,
        *,
        max_bytes: int = 1 << 20,
        max_files: int = 5,
        max_age_seconds: float = 14 * 86400,
        queue_size: int = 1000,
        lock_timeout: float = 1.0,
        retry_after: float = 2.0,
        drop_record: Callable[[dict[str, int]], str | None] | None = None,
    ) -> None:
        self.directory = directory
        self.stem = stem
        self.max_bytes = max_bytes
        self.max_files = max(1, max_files)
        self.max_age_seconds = max_age_seconds
        self.lock_timeout = lock_timeout
        self.retry_after = retry_after
        self._drop_record = drop_record
        self._queue: queue.Queue[str] = queue.Queue(maxsize=queue_size)
        self._closing = threading.Event()
        self._start = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pruned = False
        self._unreported = 0
        self._unreported_errors = 0
        self._stats_lock = threading.Lock()
        self.stats = {
            "submitted": 0,
            "written": 0,
            "dropped_full": 0,
            "dropped_closed": 0,
            "dropped_error": 0,
            "write_errors": 0,
        }

    @property
    def path(self) -> Path:
        return self.directory / f"{self.stem}.jsonl"

    def submit(self, line: str) -> bool:
        try:
            if self._closing.is_set():
                self._count("dropped_closed")
                return False
            self._ensure_thread()
            self._queue.put_nowait(line)
            self._count("submitted")
            return True
        except queue.Full:
            self._count("dropped_full", unreported=True)
            return False
        except Exception:
            self._count("dropped_error", unreported=True)
            return False

    def _count(
        self, key: str, n: int = 1, *, unreported: bool = False, error: bool = False
    ) -> None:
        with self._stats_lock:
            self.stats[key] += n
            if unreported:
                self._unreported += n
            if error:
                self._unreported_errors += 1

    def dropped(self) -> int:
        return self.stats["dropped_full"] + self.stats["dropped_error"]

    def close(self, timeout: float = 2.0) -> None:
        self._closing.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        # Whatever is still queued after the timeout is dropped, never written later.
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            self._count("dropped_closed")

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait (bounded) until the queue is drained; for tests and the export command."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.01)
        return False

    # --- writer --------------------------------------------------------------------------------

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        with self._start:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._loop, name=f"obs-{self.stem}", daemon=True
                )
                self._thread.start()

    def _loop(self) -> None:
        backoff_until = 0.0
        while True:
            try:
                first = self._queue.get(timeout=0.2)
            except queue.Empty:
                if self._closing.is_set():
                    return
                continue
            batch = [first]
            while len(batch) < 200:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            try:
                if time.monotonic() < backoff_until:
                    raise OSError(errno.EAGAIN, "write backoff")
                self._write(batch)
                self._count("written", len(batch))
            except Exception as exc:
                self._count("dropped_error", len(batch), unreported=True)
                if not (isinstance(exc, OSError) and exc.errno == errno.EAGAIN):
                    self._count("write_errors", error=True)
                    backoff_until = time.monotonic() + self.retry_after
            finally:
                for _ in batch:
                    self._queue.task_done()

    def _lock(self) -> int:
        fd = os.open(self.directory / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise OSError(errno.EBUSY, "observability lock busy") from None
                time.sleep(0.01)

    def _write(self, batch: list[str]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            os.chmod(self.directory, 0o700)
        lock = self._lock()
        try:
            if not self._pruned:
                self._prune()
                self._pruned = True
            with self._stats_lock:
                pending = {"dropped": self._unreported, "write_errors": self._unreported_errors}
            if pending["dropped"] and self._drop_record is not None:
                report = self._drop_record(pending)
                if report:
                    batch = [report, *batch]
            size = self.path.stat().st_size if self.path.exists() else 0
            chunk: list[bytes] = []
            chunk_bytes = 0
            for line in batch:
                encoded = line.encode("utf-8")
                if size + chunk_bytes + len(encoded) > self.max_bytes and (size or chunk):
                    if chunk:
                        self._append(b"".join(chunk), size)
                    self._rotate()
                    size, chunk, chunk_bytes = 0, [], 0
                chunk.append(encoded)
                chunk_bytes += len(encoded)
            if chunk:
                self._append(b"".join(chunk), size)
            with self._stats_lock:
                self._unreported -= pending["dropped"]
                self._unreported_errors -= pending["write_errors"]
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(lock, fcntl.LOCK_UN)
            os.close(lock)

    def _append(self, data: bytes, size: int) -> None:
        fd = os.open(self.path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            with contextlib.suppress(OSError):
                os.fchmod(fd, 0o600)
            if size and os.pread(fd, 1, size - 1) != b"\n":
                data = b"\n" + data  # isolate a torn last line from an earlier crash
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
        finally:
            os.close(fd)

    def _rotated(self, index: int) -> Path:
        return self.directory / f"{self.stem}.{index}.jsonl"

    def _rotate(self) -> None:
        if self.max_files == 1:
            self.path.unlink(missing_ok=True)
            return
        self._rotated(self.max_files - 1).unlink(missing_ok=True)
        for index in range(self.max_files - 2, 0, -1):
            source = self._rotated(index)
            if source.exists():
                os.replace(source, self._rotated(index + 1))
        os.replace(self.path, self._rotated(1))

    def _prune(self) -> None:
        cutoff = time.time() - self.max_age_seconds
        for path in files(self.directory, self.stem):
            with contextlib.suppress(OSError):
                if path.stat().st_mtime < cutoff:
                    path.unlink()
        for index in range(self.max_files, self.max_files + 50):
            self._rotated(index).unlink(missing_ok=True)


def files(directory: Path, stem: str) -> list[Path]:
    """Rotated files oldest first, then the current file."""
    rotated = []
    for path in directory.glob(f"{stem}.*.jsonl") if directory.is_dir() else []:
        middle = path.name[len(stem) + 1 : -len(".jsonl")]
        if middle.isdigit():
            rotated.append((int(middle), path))
    out = [p for _, p in sorted(rotated, reverse=True)]
    current = directory / f"{stem}.jsonl"
    if current.is_file():
        out.append(current)
    return out


def read(
    directory: Path, stem: str, stats: dict[str, int] | None = None
) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON objects; malformed, oversize or non-object lines are counted, skipped."""
    stats = stats if stats is not None else {}
    stats.setdefault("lines", 0)
    stats.setdefault("corrupt", 0)
    for path in files(directory, stem):
        try:
            handle = path.open("rb")
        except OSError:
            stats["unreadable_files"] = stats.get("unreadable_files", 0) + 1
            continue
        with handle:
            for raw in handle:
                if not raw.strip():
                    continue
                stats["lines"] += 1
                if len(raw) > MAX_LINE:
                    stats["corrupt"] += 1
                    continue
                try:
                    value = json.loads(raw)
                except ValueError:
                    stats["corrupt"] += 1
                    continue
                if not isinstance(value, dict):
                    stats["corrupt"] += 1
                    continue
                yield value
