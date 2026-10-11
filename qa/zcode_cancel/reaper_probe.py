"""Controlled orphan-reaping probe using only processes this script creates.

Case "orphan": parent P forks C, C forks G and exits at once (P reaps C), G exits after 0.2 s.
G is orphaned, so the kernel reparents it to the nearest child subreaper or the PID namespace's
init; G stays a zombie (state Z) until that process wait()s for it.
Case "subreaper": same, but P first sets PR_SET_CHILD_SUBREAPER, so G is reparented to P, which
deliberately waits only after observing G as a zombie (control for kill(pid, 0) semantics).
Records pid, ppid, state, starttime and comm only.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PR_SET_CHILD_SUBREAPER = 36


def stat(pid: int) -> dict[str, Any] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    rest = raw[raw.rfind(")") + 2 :].split()
    return {
        "comm": raw[raw.index("(") + 1 : raw.rfind(")")][:15],
        "state": rest[0],
        "ppid": int(rest[1]),
        "starttime": int(rest[19]),
    }


def kill0(pid: int) -> str:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "ProcessLookupError"
    return "no-exception"


def run(case: str, watch: float = 3.0) -> dict[str, Any]:
    if case == "subreaper":
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            return {"case": case, "error": "prctl failed"}
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:  # C
        os.close(read_fd)
        grandchild = os.fork()
        if grandchild == 0:  # G
            time.sleep(0.2)
            os._exit(0)
        os.write(write_fd, str(grandchild).encode())
        os._exit(0)
    os.close(write_fd)
    g = int(os.read(read_fd, 32))
    os.waitpid(child, 0)
    first = stat(g)
    series = []
    deadline = time.monotonic() + watch
    last = None
    while time.monotonic() < deadline:
        cur = stat(g)
        view = None if cur is None else (cur["state"], cur["ppid"], cur["starttime"])
        if view != last:
            series.append(
                {
                    "t_ms": round((watch - (deadline - time.monotonic())) * 1000),
                    "stat": cur,
                    "kill0": kill0(g),
                }
            )
            last = view
        time.sleep(0.02)
    reaper = stat(last[1]) if last else None
    out: dict[str, Any] = {
        "case": case,
        "probe_pid": os.getpid(),
        "grandchild_first": first,
        "series": series,
        "final_parent": None if not last else {"pid": last[1], **(reaper or {})},
    }
    if case == "subreaper" and last and last[0] == "Z" and last[1] == os.getpid():
        os.waitpid(g, 0)
        out["after_wait"] = {"stat": stat(g), "kill0": kill0(g)}
    return out


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1]), indent=1))
