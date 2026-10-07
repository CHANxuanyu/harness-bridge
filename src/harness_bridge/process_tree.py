"""Observe descendants without reading command arguments, environments or credentials.

This is sampled process ancestry, not OS containment: a process which reparents between
observations can be missed. Only positively observed identities are ever signalled.
"""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessEntry:
    pid: int
    parent: int
    group: int
    state: str
    birth: str


def process_table() -> dict[int, ProcessEntry] | None:
    if Path("/proc/self/stat").exists():
        entries: dict[int, ProcessEntry] = {}
        try:
            paths = list(Path("/proc").iterdir())
        except OSError:
            return None
        for path in paths:
            if not path.name.isdigit():
                continue
            try:
                raw = (path / "stat").read_text()
                rest = raw[raw.rfind(")") + 2 :].split()
                pid = int(path.name)
                entries[pid] = ProcessEntry(pid, int(rest[1]), int(rest[2]), rest[0], rest[19])
            except FileNotFoundError:
                continue
            except (OSError, IndexError, ValueError):
                return None
        return entries
    try:
        result = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid=,pgid=,stat=,lstart="],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None
    if result.returncode:
        return None
    entries = {}
    for line in result.stdout.splitlines():
        fields = line.split(None, 4)
        if len(fields) != 5:
            return None
        try:
            pid, parent, group = map(int, fields[:3])
        except ValueError:
            return None
        entries[pid] = ProcessEntry(pid, parent, group, fields[3], fields[4])
    return entries


class ProcessTree:
    def __init__(self, root: int):
        self.root = root
        self.known: dict[int, str] = {}
        self.current: dict[int, ProcessEntry] = {}
        self.inspection_failed = False
        self.signalled: set[int] = set()
        self._first_observation = True
        self.refresh()

    def refresh(self) -> None:
        table = process_table()
        if table is None:
            self.inspection_failed = True
            self.current = {}
            return
        # The direct Popen child has not been reaped on the first observation.
        if self._first_observation:
            self._first_observation = False
            if self.root in table:
                self.known[self.root] = table[self.root].birth
            else:
                self.inspection_failed = True
        owned = {
            pid for pid, birth in self.known.items() if pid in table and table[pid].birth == birth
        }
        while True:
            children = {p.pid for p in table.values() if p.parent in owned}
            new = {
                pid
                for pid in children - owned
                if pid not in self.known or self.known[pid] == table[pid].birth
            }
            if not new:
                break
            for pid in new:
                # A reused PID is never adopted as the old descendant.
                if pid not in self.known:
                    self.known[pid] = table[pid].birth
            owned |= new
        self.current = {
            pid: table[pid]
            for pid, birth in self.known.items()
            if pid in table and table[pid].birth == birth
        }

    def remaining(self) -> list[int]:
        return sorted(
            p.pid
            for p in self.current.values()
            if p.pid != self.root and not p.state.startswith("Z")
        )

    def confirmed(self) -> bool:
        return not self.inspection_failed and not self.remaining()

    def signal_detached(self, sig: signal.Signals) -> bool:
        # Group signalling handles members of the original group. Signal only individually
        # observed detached descendants, after a fresh birth-marker check; never their groups.
        self.refresh()
        targets = [
            p
            for p in self.current.values()
            if p.pid != self.root and p.group != self.root and not p.state.startswith("Z")
        ]
        sent = False
        for target in targets:
            table = process_table()
            if table is None:
                self.inspection_failed = True
                continue
            current = table.get(target.pid)
            if current is None or current.birth != target.birth or current.state.startswith("Z"):
                continue
            try:
                os.kill(target.pid, sig)
                self.signalled.add(target.pid)
                sent = True
            except ProcessLookupError:
                pass
            except PermissionError:
                self.inspection_failed = True
        return sent

    def report(self) -> dict[str, object]:
        return {
            "scope": "sampled descendants; not OS containment",
            "observed_descendants": len(self.known) - int(self.root in self.known),
            "signalled_descendants": sorted(self.signalled),
            "remaining_descendants": self.remaining(),
            "inspection_failed": self.inspection_failed,
            "observed_exits_confirmed": self.confirmed(),
        }
