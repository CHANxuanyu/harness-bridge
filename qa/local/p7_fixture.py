"""Prepare a fresh, model-free P7 rehearsal. No live configuration or harness invocation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from harness_bridge.coordination import GoalSpec
from harness_bridge.demo_fixture import GIT_IDENTITY_ENV
from harness_bridge.planning import PlanBatch

NORMALIZE = """def normalize_tags(values):
    return list(dict.fromkeys(v.strip().lower() for v in values if v.strip()))
"""
RENDER = """def render_tags(values):
    return ", ".join("[" + v + "]" for v in values)
"""
FILES = {
    ".gitignore": "__pycache__/\n*.pyc\n",
    "README.md": "# P7 disposable tag formatter\n\nSynthetic acceptance fixture.\n",
    "tagnorm/__init__.py": "",
    "tagnorm/normalize.py": "def normalize_tags(values):\n    raise NotImplementedError\n",
    "tagformat/__init__.py": "",
    "tagformat/render.py": "def render_tags(values):\n    raise NotImplementedError\n",
}

# Immutable checks outside all candidate workspaces; all requirements are known initially.
CHECKER = """import os
import sys
sys.path.insert(0, os.getcwd())
mode = sys.argv[1]
assert mode in ("normalize", "render", "combined")
if mode in ("normalize", "combined"):
    from tagnorm.normalize import normalize_tags
    for given, expected in [([" B ", "a", "b", ""], ["b", "a"]), ([], []),
                            (["  ", "\\t"], []), (["É", "é", "Z"], ["é", "z"])]:
        original = list(given)
        assert normalize_tags(given) == expected
        assert given == original
if mode in ("render", "combined"):
    from tagformat.render import render_tags
    for given, expected in [(["b", "a"], "[b], [a]"), ([], ""), (["é"], "[é]")]:
        original = list(given)
        assert render_tags(given) == expected
        assert given == original
if mode == "combined":
    assert render_tags(normalize_tags([" B ", "a", "b", ""])) == "[b], [a]"
print(mode + ": passed")
"""

# Only generated stand-ins are executed. No subprocess, SDK, network or harness discovery here.
STAND_IN = """import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
root = Path(__file__).resolve().parent.parent
args = sys.argv[1:]
cx = Path(__file__).name == "cx-stand-in"
resume = "resume" if cx else "--resume"
sid = args[args.index(resume) + 1] if resume in args else str(uuid.uuid4())
prompt = sys.stdin.buffer.read()
model = args[args.index("--model") + 1]
if cx:
    assert args[0] == "exec" and args[-1] == "-"
    assert args[args.index("--cd") + 1] == os.getcwd()
    assert args[args.index("--config") + 1] == 'approval_policy="never"'
else:
    assert args[args.index("--max-turns") + 1] == "10"
deadline = time.monotonic() + 20
while not (root / "release").exists():
    if time.monotonic() > deadline:
        raise SystemExit("offline rendezvous timed out")
    time.sleep(0.05)
log = {"kind": "codex" if cx else "claude-code", "cwd": os.getcwd(),
       "session_id": sid, "resumed": resume in args,
       "prompt_sha256": hashlib.sha256(prompt).hexdigest()}
with (root / ("cx-calls.jsonl" if cx else "cc-calls.jsonl")).open("a") as f:
    f.write(json.dumps(log) + "\\n")
if cx:
    Path("tagformat/render.py").write_text(RENDER)
    events = [{"type": "thread.started", "thread_id": sid}, {"type": "turn.started"},
              {"type": "turn.completed", "usage": {
                  "input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1}}]
else:
    if resume in args:
        Path("tagnorm/normalize.py").write_text(NORMALIZE)
    events = [{"type": "system", "subtype": "init", "session_id": sid, "model": model},
              {"type": "result", "subtype": "success", "is_error": False,
               "session_id": sid, "num_turns": 1, "result": "Synthetic staged execution"}]
for event in events:
    print(json.dumps(event), flush=True)
"""


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def isolated_env(root: Path) -> dict[str, str]:
    # Only for this synthetic fixture; never scrub markers to make a live run pass.
    env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TMPDIR") if k in os.environ}
    env.update(
        HOME=str(root / "home"),
        CODEX_HOME=str(root / "home/.codex"),
        XDG_CONFIG_HOME=str(root / "home/.config"),
        XDG_STATE_HOME=str(root / "home/.state"),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"),
        PYTHONDONTWRITEBYTECODE="1",
        **GIT_IDENTITY_ENV,
    )
    return env


def check(root: Path, mode: str) -> dict[str, Any]:
    return {
        "id": mode,
        "argv": [sys.executable, "-B", str(root / "acceptance.py"), mode],
        "cwd": ".",
        "timeout_seconds": 10,
        "required": True,
        "trust": "external-acceptance",
    }


def prepare(root: Path) -> dict[str, Any]:
    root = root.absolute()
    # Refuse even an empty pre-existing directory or dangling symlink; never reuse live state.
    root.mkdir(parents=True, exist_ok=False)
    (root / "home").mkdir()
    repo = root / "repo"
    repo.mkdir()
    for rel, text in FILES.items():
        file = repo / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "--", "."],
        ["commit", "-q", "-m", "P7 synthetic baseline"],
    ):
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
            cwd=repo,
            env=isolated_env(root),
            capture_output=True,
            check=True,
            timeout=30,
        )
    (root / "acceptance.py").write_text(CHECKER, encoding="utf-8")
    (root / "bin").mkdir()
    for name in ("cc-stand-in", "cx-stand-in"):
        file = root / "bin" / name
        file.write_text(
            f"#!{sys.executable}\nNORMALIZE = {NORMALIZE!r}\nRENDER = {RENDER!r}\n" + STAND_IN,
            encoding="utf-8",
        )
        file.chmod(0o700)
    goal = GoalSpec.model_validate(
        {
            "schema_version": "1.0",
            "objective": "Normalize and render tags using two child sessions",
            "repo": {"path": str(repo), "base_ref": "HEAD"},
            "advisor": {"host": "codex", "native_session_ref": "synthetic-advisor-a"},
            "acceptance": [
                "Combined external acceptance passes; source checkout remains unchanged"
            ],
            "max_attempts": 3,
            "max_repairs": 1,
            "max_executor_wall_seconds": 1800,
            "max_executor_turns": 30,
            "allowed_executors": ["claude-code", "codex"],
        }
    ).normalized()
    children = []
    for key, kind, path, requirements in (
        (
            "normalize",
            "claude-code",
            "tagnorm/normalize.py",
            [
                "Strip and lowercase strings; remove empty strings and duplicates",
                "Preserve first-occurrence order",
                "Return a new list; do not mutate input",
                "First attempt: diagnosis only, make no edits. After Advisor feedback: implement",
            ],
        ),
        (
            "render",
            "codex",
            "tagformat/render.py",
            [
                "Render each supplied string in square brackets, joined by comma and space",
                "Preserve order and values; empty input gives empty string; do not mutate input",
            ],
        ),
    ):
        executor = {"kind": kind, "requested_model": "synthetic-pin"}
        if kind == "claude-code":
            executor["allowed_tools"] = ["Read", "Edit", "Write"]
        children.append(
            {
                "key": key,
                "depends_on": [],
                "task": {
                    "goal": f"Implement {key} for the tag formatter",
                    "requirements": requirements,
                    "allowed_paths": [path],
                    "verification": [check(root, key)],
                    "limits": {
                        "max_attempts": 2 if key == "normalize" else 1,
                        "max_repair_cycles": 1 if key == "normalize" else 0,
                        "wall_timeout_seconds": 600,
                        "max_turns_per_attempt": 10,
                    },
                    "executor": executor,
                },
            }
        )
    plan = PlanBatch.model_validate({"schema_version": "1.0", "children": children})
    write_json(root / "goal.json", goal)
    write_json(root / "plan.json", plan.model_dump(mode="json"))
    write_json(root / "integration-checks.json", [check(root, "combined")])
    manifest = {
        "evidence_level": "synthetic-fixture",
        "inference_performed": False,
        "live_ready": False,
        "live_authorized": False,
        "blocked_by": [
            "Codex live capability gaps",
            "New bounded per-run authorization required",
            "Synthetic model/session pins must be replaced in a fresh reviewed packet",
        ],
        "ceilings": {"attempts": 3, "repairs": 1, "reserved_turns": 30, "reserved_seconds": 1800},
        "files": {
            str(p.relative_to(root)): digest(p)
            for p in [
                root / "acceptance.py",
                root / "goal.json",
                root / "plan.json",
                root / "integration-checks.json",
                root / "bin/cc-stand-in",
                root / "bin/cx-stand-in",
            ]
        },
    }
    write_json(root / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="new disposable directory (must not exist)")
    args = parser.parse_args()
    try:
        result = prepare(args.root)
    except FileExistsError:
        parser.error("refusing to reuse an existing directory")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
