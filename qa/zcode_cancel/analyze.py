"""Summarize one observe.json: identities, transitions and snapshots of test-owned PIDs."""

import json
import sys
from pathlib import Path

FIELDS = ("comm", "state", "ppid", "pgid", "starttime")

data = json.loads(Path(sys.argv[1]).read_text())
print("phases", data.get("phases"), "failure", data.get("failure_type"))
print("import", data.get("import_path"))
print("markers invoking", data["invoking_markers_present"])
print("markers inside test", data.get("markers_inside_test_after_fixtures"))
print(
    "pid1", data.get("pid1"), "pytest_pid", data.get("pytest_pid"), "samples", data.get("samples")
)
print("peer pids from log", data.get("peer_pids_from_log"))
print("reapers", data.get("reaper_identities"))
print("-- first seen")
for pid, first in data["tracked_first_seen"].items():
    print("  ", pid, {k: first[k] for k in (*FIELDS, "sid", "first_seen_ms")})
print("-- transitions")
for item in data["transitions"]:
    print("  ", item)
for label, snap in data["snapshots"].items():
    print("--", label, "t_ms", snap["t_ms"], "killpg0", snap["killpg0"])
    for pid, proc in snap["processes"].items():
        cur = proc["current"]
        view = None if cur is None else {k: cur[k] for k in FIELDS}
        print("    ", pid, view, "same_start", proc["same_start_identity"], "kill0", proc["kill0"])
