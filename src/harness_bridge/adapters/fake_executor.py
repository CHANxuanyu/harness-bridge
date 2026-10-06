"""Standalone fake executor process (stdlib only; never imports harness_bridge).

It is launched by the bridge as a real OS process (``python -I -B fake_executor.py --scenario X``)
with the task packet on stdin and the task worktree as cwd. It really edits files in the
worktree, writes JSON lines to stdout ("hbridge-fake/1" wire protocol), writes to stderr, and
exits with real exit codes. It is a deterministic stand-in for a model executor and is coupled to
the ``normalize_tags`` demo fixture (it edits ``tagnorm/normalize.py``). It makes no network
requests and calls no model.

Wire protocol (one JSON object per line on stdout):
  {"type":"start","session_id":...,"model":"fake-executor","protocol":"hbridge-fake/1"}
  {"type":"progress","message":...}
  {"type":"child","pid":...}
  {"type":"result","status":"success"|"error","summary":...,"tests_reported":...,
   "error":{"category":...,"message":...,"reset_at":...}}
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid

TARGET = os.path.join("tagnorm", "normalize.py")

CORRECT_IMPL = '''"""Tag normalization."""


def normalize_tags(values):
    """Strip, lowercase, drop empty, de-duplicate; keep first-occurrence order."""
    seen = set()
    result = []
    for value in values:
        tag = value.strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result
'''

BUGGY_IMPL = '''"""Tag normalization."""


def normalize_tags(values):
    """Strip, lowercase, drop empty, de-duplicate."""
    return sorted({value.strip().lower() for value in values if value.strip()})
'''

TAMPERED_TESTS = """import unittest


class NormalizeTagsTest(unittest.TestCase):
    def test_nothing(self):
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
"""


def emit(obj: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def result(
    status: str, summary: str, tests_reported: str = "not_run", error: dict[str, str] | None = None
) -> None:
    payload: dict[str, object] = {
        "type": "result",
        "status": status,
        "summary": summary,
        "tests_reported": tests_reported,
    }
    if error:
        payload["error"] = error
    emit(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    args = parser.parse_args()
    packet = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    feedback = packet.get("feedback") or []
    attempt = int(packet.get("attempt_seq", 1))
    scenario = args.scenario

    emit(
        {
            "type": "start",
            "session_id": "fake-" + uuid.uuid4().hex,
            "model": "fake-executor",
            "protocol": "hbridge-fake/1",
        }
    )
    sys.stderr.write(f"fake-executor: scenario={scenario} attempt={attempt}\n")

    if scenario == "success":
        write(TARGET, CORRECT_IMPL)
        emit({"type": "progress", "message": f"wrote {TARGET}"})
        result("success", "Implemented normalize_tags.", "passed")
        return 0

    if scenario == "bug-then-repair":
        if attempt == 1 or not feedback:
            write(TARGET, BUGGY_IMPL)
            emit({"type": "progress", "message": "implemented with a set + sorted()"})
            result("success", "Implemented normalize_tags; all tests pass.", "passed")
        else:
            write(TARGET, CORRECT_IMPL)
            emit({"type": "progress", "message": f"addressed {len(feedback)} finding(s)"})
            result("success", "Preserved first-occurrence order per review feedback.", "passed")
        return 0

    if scenario == "false-success-report":
        write(TARGET, BUGGY_IMPL)
        result("success", "All tests pass (claimed by executor).", "passed")
        return 0

    if scenario == "tamper-tests":
        write(TARGET, BUGGY_IMPL)
        write(os.path.join("tests", "test_normalize.py"), TAMPERED_TESTS)
        result("success", "Simplified the tests; everything passes.", "passed")
        return 0

    if scenario == "scope-violation":
        write(TARGET, CORRECT_IMPL)
        write(".env", "API_TOKEN=sk-ant-THISISAFAKETESTTOKEN000000\n")
        write("notes.txt", "scratch notes outside the allowed paths\n")
        result("success", "Implemented normalize_tags and saved some notes.", "passed")
        return 0

    if scenario == "noisy":
        write(TARGET, CORRECT_IMPL)
        line = "x" * 1023
        for i in range(3000):  # ~3 MiB on each stream
            emit({"type": "progress", "message": f"{i}:{line}"})
            sys.stderr.write(f"noise {i}: {line}\n")
        result("success", "Implemented normalize_tags noisily.", "passed")
        return 0

    if scenario == "hang":
        child = subprocess.Popen(
            [sys.executable, "-c", "import time\nwhile True: time.sleep(1)"],
        )
        emit({"type": "child", "pid": child.pid})
        emit({"type": "progress", "message": "hanging"})
        while True:
            time.sleep(1)

    if scenario == "crash":
        write(TARGET, BUGGY_IMPL[: len(BUGGY_IMPL) // 2])
        sys.stdout.write('{"type": "progress", "message": "about to')
        sys.stdout.flush()
        sys.stderr.write("fake-executor: simulated crash\n")
        os._exit(3)

    if scenario == "malformed-output":
        write(TARGET, CORRECT_IMPL)
        sys.stdout.write("this is not json\n")
        sys.stdout.write('{"type": "result", "status": \n')
        sys.stdout.flush()
        return 0

    if scenario == "permission-denied":
        result(
            "error",
            "Could not write files.",
            error={"category": "permission_denied", "message": "write to tagnorm/ denied"},
        )
        return 1

    if scenario == "budget-exhausted":
        result(
            "error",
            "Usage limit reached.",
            error={
                "category": "usage_limit",
                "message": "simulated usage limit",
                "reset_at": "2099-01-01T00:00:00Z",
            },
        )
        return 1

    sys.stderr.write(f"unknown scenario {scenario}\n")
    return 64


if __name__ == "__main__":
    sys.exit(main())
