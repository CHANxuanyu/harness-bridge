"""Stand-in executable for contract-testing the Claude Code adapter. NOT a model, NOT claude.

Behaviour is driven by environment variables set by the test:
  HBRIDGE_STUB_FIXTURE   jsonl file to replay on stdout (placeholders substituted)
  HBRIDGE_STUB_ARGV_LOG  append a JSON record of argv / stdin digest / cwd to this file
  HBRIDGE_STUB_EDIT      "correct" | "buggy": write tagnorm/normalize.py like an executor would
  HBRIDGE_STUB_EXIT      exit code (default 0)
  HBRIDGE_STUB_STDERR    text written to stderr
  HBRIDGE_STUB_TRICKLE   if "1", write stdout one byte at a time (chunk-boundary test)
  HBRIDGE_STUB_HELP      file whose content is printed for --help (captured help text)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid

CORRECT = (
    "def normalize_tags(values):\n"
    "    seen = set()\n"
    "    out = []\n"
    "    for v in values:\n"
    "        t = v.strip().lower()\n"
    "        if t and t not in seen:\n"
    "            seen.add(t)\n"
    "            out.append(t)\n"
    "    return out\n"
)
BUGGY = (
    "def normalize_tags(values):\n"
    "    return sorted({v.strip().lower() for v in values if v.strip()})\n"
)


def main() -> int:
    argv = sys.argv[1:]
    if argv[:1] == ["--help"]:
        help_file = os.environ.get("HBRIDGE_STUB_HELP")
        if help_file:
            with open(help_file, encoding="utf-8") as fh:
                sys.stdout.write(fh.read())
        else:
            sys.stdout.write("Usage: stub\n")
        return 0
    if argv[:1] == ["--version"]:
        sys.stdout.write("0.0.0-stub (not Claude Code)\n")
        return 0
    stdin = sys.stdin.buffer.read()
    log = os.environ.get("HBRIDGE_STUB_ARGV_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "argv": argv,
                        "cwd": os.getcwd(),
                        "stdin_sha256": hashlib.sha256(stdin).hexdigest(),
                        "stdin_text": stdin.decode("utf-8", "replace"),
                    }
                )
                + "\n"
            )
    edit = os.environ.get("HBRIDGE_STUB_EDIT")
    if edit in ("correct", "buggy"):
        with open(os.path.join("tagnorm", "normalize.py"), "w", encoding="utf-8") as fh:
            fh.write(CORRECT if edit == "correct" else BUGGY)
    session = argv[argv.index("--resume") + 1] if "--resume" in argv else str(uuid.uuid4())
    model = argv[argv.index("--model") + 1] if "--model" in argv else "unknown-model"
    fixture = os.environ.get("HBRIDGE_STUB_FIXTURE")
    data = b""
    if fixture:
        with open(fixture, encoding="utf-8") as fh:
            text = fh.read()
        data = text.replace("__SESSION_ID__", session).replace("__MODEL__", model).encode()
    if os.environ.get("HBRIDGE_STUB_TRICKLE") == "1":
        for b in data:
            sys.stdout.buffer.write(bytes([b]))
            sys.stdout.buffer.flush()
            time.sleep(0.0005)
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    if os.environ.get("HBRIDGE_STUB_STDERR"):
        sys.stderr.write(os.environ["HBRIDGE_STUB_STDERR"] + "\n")
    return int(os.environ.get("HBRIDGE_STUB_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
