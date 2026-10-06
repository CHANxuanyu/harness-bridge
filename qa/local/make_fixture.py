#!/usr/bin/env python3
"""Generate the one-shot T3 smoke fixture: a single-function repo, an external
acceptance script, and a claude-code TaskSpec.

This is qa/local material for the *first real Claude CLI run* (T3) described in
docs/LOCAL_HANDOFF.md §2. It targets a disposable fixture project only — never
Harness Bridge itself. It creates files; it never calls a model and never
touches ~/.claude, credentials or global configuration.

Usage:
    uv run --frozen python qa/local/make_fixture.py <workdir> [--force]

Layout created under <workdir>:
    fixture-repo/                      one-shot git repo (slugify stub, main @ HEAD)
    acceptance/check_slugify.py        external acceptance check, OUTSIDE the repo,
                                       owned by the supervisor; the executor cannot
                                       pass by editing repository tests
    task-live-smoke.json               TaskSpec for `hbridge create`

The generated TaskSpec pins the agreed first-run limits:
    max_attempts = 1, max_repair_cycles = 0,
    max_turns_per_attempt = 10, wall_timeout_seconds = 600
and the real executor (claude-code / claude-opus-5-5) with a scoped
Bash auto-approval that matches the repo-tests command exactly.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

MODEL = "claude-opus-5-5"
IDEMPOTENCY_KEY = "live-smoke-1"

REQUIREMENTS = [
    "Accept exactly one str argument and return a str",
    "Convert the input to lowercase first",
    "Replace every run of one or more characters that are not ASCII letters "
    "(a-z, after lowercasing) or digits (0-9) with a single hyphen '-'",
    "Then remove leading and trailing hyphens from the result",
    "If nothing remains, return the empty string ''",
]

FIXTURE_FILES: dict[str, str] = {
    ".gitignore": "__pycache__/\n*.pyc\n",
    "README.md": (
        "# slugkit-smoke\n\n"
        "One-shot fixture for a Harness Bridge T3 live smoke test. Disposable; "
        "contains no secrets.\n"
    ),
    "slugkit/__init__.py": ("from slugkit.slugify import slugify\n\n__all__ = ['slugify']\n"),
    "slugkit/slugify.py": (
        '"""URL slug from a title."""\n\n\n'
        "def slugify(text):\n"
        '    """Lowercase; collapse non-[a-z0-9] runs to \'-\'; trim edge hyphens."""\n'
        "    raise NotImplementedError\n"
    ),
    "tests/__init__.py": "",
    "tests/test_slugify.py": """import unittest

from slugkit import slugify


class SlugifyTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_collapses_separators(self):
        self.assertEqual(slugify("A--B///C"), "a-b-c")

    def test_no_alphanumerics(self):
        self.assertEqual(slugify("!!!"), "")


if __name__ == "__main__":
    unittest.main()
""",
}

ACCEPTANCE_SCRIPT = '''"""External acceptance check for slugify (single function).

Owned by the supervisor and stored OUTSIDE the fixture repository. The
executor never writes or edits this file; repository tests alone do not
decide acceptance.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from slugkit import slugify  # noqa: E402

CASES = [
    ("Hello World", "hello-world"),
    ("  Multiple   Spaces  ", "multiple-spaces"),
    ("Hello, World! 2026", "hello-world-2026"),
    ("A--B///C", "a-b-c"),
    ("!!!", ""),
    ("", ""),
    ("Café au lait", "caf-au-lait"),
    ("2026-10-06_release", "2026-10-06-release"),
    ("Zeta", "zeta"),
]

failures = []
for given, expected in CASES:
    try:
        got = slugify(given)
    except Exception as exc:  # noqa: BLE001
        failures.append({"input": given, "error": repr(exc)})
        continue
    if got != expected or not isinstance(got, str):
        failures.append({"input": given, "expected": expected, "got": got})

print(json.dumps({"cases": len(CASES), "failures": failures}))
sys.exit(1 if failures else 0)
'''


def _git(args: list[str], cwd: Path) -> None:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "hbridge qa fixture",
            "GIT_AUTHOR_EMAIL": "qa-fixture@hbridge.invalid",
            "GIT_COMMITTER_NAME": "hbridge qa fixture",
            "GIT_COMMITTER_EMAIL": "qa-fixture@hbridge.invalid",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
        cwd=str(cwd),
        env=env,
        check=True,
        capture_output=True,
    )


def build_task_spec(workdir: Path) -> dict[str, object]:
    repo = workdir / "fixture-repo"
    acceptance = workdir / "acceptance" / "check_slugify.py"
    return {
        "schema_version": "1.0",
        "goal": "Implement slugkit.slugify.slugify per the requirements (single function).",
        "repo": {"path": str(repo), "base_ref": "HEAD"},
        "requirements": REQUIREMENTS,
        "allowed_paths": ["slugkit/**", "tests/**"],
        "forbidden_paths": [".github/**", ".env", ".env.*", "**/.env", "**/.env.*"],
        "verification": [
            {
                "id": "repo-tests",
                "argv": ["python3", "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                "cwd": ".",
                "timeout_seconds": 120,
                "required": True,
                "trust": "repository-tests",
            },
            {
                "id": "acceptance",
                "argv": ["python3", "-B", str(acceptance)],
                "cwd": ".",
                "timeout_seconds": 120,
                "required": True,
                "trust": "external-acceptance",
            },
        ],
        "limits": {
            "max_attempts": 1,
            "max_repair_cycles": 0,
            "wall_timeout_seconds": 600,
            "max_turns_per_attempt": 10,
            "max_artifact_bytes": 10485760,
            "kill_grace_seconds": 5,
        },
        "executor": {
            "kind": "claude-code",
            "requested_model": MODEL,
            "allowed_tools": [
                "Read",
                "Edit",
                "Write",
                "Glob",
                "Grep",
                "Bash(python3 -B -m unittest:*)",
            ],
        },
    }


def _validate_with_bridge_models(spec: dict[str, object]) -> str:
    """Offline schema check against the bridge's own TaskSpec model, if importable."""
    try:
        from harness_bridge.models import TaskSpec
    except ImportError:
        return "SKIP (harness_bridge not importable; run via `uv run --frozen`)"
    TaskSpec.model_validate(spec)
    return "PASS (TaskSpec schema 1.0 accepted)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workdir", type=Path, help="fresh directory for the fixture")
    parser.add_argument("--force", action="store_true", help="reuse an existing workdir")
    args = parser.parse_args()

    workdir = args.workdir.resolve()
    if workdir.exists() and any(workdir.iterdir()) and not args.force:
        print(f"refusing to overwrite non-empty {workdir} (use --force)", file=sys.stderr)
        return 2
    repo = workdir / "fixture-repo"
    if repo.exists():
        print(f"refusing to reuse existing fixture repo {repo}", file=sys.stderr)
        return 2

    repo.mkdir(parents=True)
    for rel, content in FIXTURE_FILES.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(["init", "-q", "-b", "main"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "fixture: slugify stub"], repo)

    acceptance = workdir / "acceptance" / "check_slugify.py"
    acceptance.parent.mkdir(parents=True, exist_ok=True)
    acceptance.write_text(ACCEPTANCE_SCRIPT, encoding="utf-8")

    spec = build_task_spec(workdir)
    task_file = workdir / "task-live-smoke.json"
    task_file.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")

    print(f"fixture repo:      {repo}")
    print(f"acceptance script: {acceptance}")
    print(f"task spec:         {task_file}")
    print(f"TaskSpec validation: {_validate_with_bridge_models(spec)}")
    print()
    print("Next (only after the LOCAL_HANDOFF.md §2 checklist is fully confirmed):")
    print("  cd <bridge-repo>")
    print(
        f"  uv run --frozen hbridge --json create --task {task_file} "
        f"--idempotency-key {IDEMPOTENCY_KEY}"
    )
    print("  uv run --frozen hbridge --json run <TASK_ID> --mode live --allow-model-usage")
    print("  uv run --frozen hbridge --json artifacts <TASK_ID>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
