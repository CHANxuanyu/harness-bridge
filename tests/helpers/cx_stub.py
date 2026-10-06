"""Offline stand-in emitting documented Codex envelopes with synthetic values only."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

from cc_stub import BUGGY, CORRECT


def main() -> int:
    args = sys.argv[1:]
    assert args[0] == "exec" and args[-1] == "-"
    assert args[args.index("--sandbox") + 1] in ("workspace-write", "read-only")
    assert args[args.index("--cd") + 1] == os.getcwd()
    assert args[args.index("--config") + 1] == 'approval_policy="never"'
    text = sys.stdin.read()
    log = os.environ.get("HBRIDGE_CX_LOG")
    if log:
        with open(log, "a") as f:
            f.write(json.dumps({"argv": args, "cwd": os.getcwd(), "stdin": text}) + "\n")
    time.sleep(float(os.environ.get("HBRIDGE_CX_DELAY", "0")))
    mode = os.environ.get("HBRIDGE_CX_MODE", "success")
    sid = args[args.index("resume") + 1] if "resume" in args else str(uuid.uuid4())
    if mode == "mismatch":
        sid = str(uuid.uuid4())
    edit = os.environ.get("HBRIDGE_CX_EDIT", "correct")
    if edit != "none":
        Path("tagnorm/normalize.py").write_text(CORRECT if edit == "correct" else BUGGY)
    fixture = Path(__file__).parents[1] / "fixtures/codex_stream/success.jsonl"
    data = fixture.read_text().replace("__SESSION_ID__", sid).splitlines()
    if mode == "quota":
        data = [
            *data[:2],
            json.dumps({"type": "turn.failed", "error": {"message": "quota exceeded"}}),
        ]
    elif mode == "truncated":
        data = data[:-1]
    elif mode == "malformed":
        data.insert(2, '{"type":')
    elif mode == "flood":
        data[2:2] = [data[2]] * 20
    output = ("\n".join(data) + "\n").encode()
    if os.environ.get("HBRIDGE_CX_TRICKLE"):
        for b in output:
            sys.stdout.buffer.write(bytes([b]))
            sys.stdout.buffer.flush()
    else:
        sys.stdout.buffer.write(output)
    return 1 if mode == "quota" else 0


if __name__ == "__main__":
    sys.exit(main())
