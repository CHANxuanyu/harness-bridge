"""The ``normalize_tags`` fixture project used by the offline demos and integration tests.

Requirement (fixed): strip surrounding whitespace, lowercase, drop empty strings, de-duplicate,
and **preserve first-occurrence order**. Inputs are lists of strings only.

Two independent checks exist:
* repository tests (``tests/test_normalize.py`` inside the repo — an executor could edit them);
* an external acceptance script written *outside* the repository by the test driver; the fake
  executor never generates or edits it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

FIXTURE_FILES: dict[str, str] = {
    ".gitignore": "__pycache__/\n*.pyc\n.pytest_cache/\n",
    "README.md": "# tagnorm\n\nFixture project for Harness Bridge offline demos.\n",
    "tagnorm/__init__.py": (
        "from tagnorm.normalize import normalize_tags\n\n__all__ = ['normalize_tags']\n"
    ),
    "tagnorm/normalize.py": (
        '"""Tag normalization."""\n\n\n'
        "def normalize_tags(values):\n"
        '    """Strip, lowercase, drop empty, de-duplicate; keep first-occurrence order."""\n'
        "    raise NotImplementedError\n"
    ),
    "tests/__init__.py": "",
    "tests/test_normalize.py": """import unittest

from tagnorm import normalize_tags


class NormalizeTagsTest(unittest.TestCase):
    def test_strips_and_lowercases(self):
        self.assertEqual(normalize_tags(["  Python ", "RUST"]), ["python", "rust"])

    def test_removes_duplicates(self):
        self.assertEqual(normalize_tags(["a", "A", " a "]), ["a"])

    def test_all_empty(self):
        self.assertEqual(normalize_tags(["", "   ", "\\t"]), [])

    def test_empty_input(self):
        self.assertEqual(normalize_tags([]), [])

    def test_preserves_first_occurrence_order(self):
        self.assertEqual(
            normalize_tags(["zeta", "Alpha", "mid", "alpha", "ZETA"]),
            ["zeta", "alpha", "mid"],
        )


if __name__ == "__main__":
    unittest.main()
""",
}

ACCEPTANCE_SCRIPT = '''"""External acceptance check for normalize_tags.

Owned by the test driver and stored outside the repository; the executor does not write it.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from tagnorm import normalize_tags  # noqa: E402

CASES = [
    (["b", "a", "B"], ["b", "a"]),
    (["  Go", "go", "RUST", "", "rust ", "Zig", "c"], ["go", "rust", "zig", "c"]),
    ([], []),
    (["  ", ""], []),
    (["Tag"], ["tag"]),
]
failures = []
for given, expected in CASES:
    original = list(given)
    try:
        got = normalize_tags(given)
    except Exception as exc:  # noqa: BLE001
        failures.append({"input": original, "error": repr(exc)})
        continue
    if got != expected or not isinstance(got, list):
        failures.append({"input": original, "expected": expected, "got": got})
    if given != original:
        failures.append({"input": original, "error": "input list was mutated"})
print(json.dumps({"cases": len(CASES), "failures": failures}))
sys.exit(1 if failures else 0)
'''

GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "hbridge fixture",
    "GIT_AUTHOR_EMAIL": "fixture@hbridge.invalid",
    "GIT_COMMITTER_NAME": "hbridge fixture",
    "GIT_COMMITTER_EMAIL": "fixture@hbridge.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}


def _git(args: list[str], cwd: Path) -> None:
    env = dict(os.environ)
    env.update(GIT_IDENTITY_ENV)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
        cwd=str(cwd),
        env=env,
        check=True,
        capture_output=True,
    )


def create_fixture_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=False)
    for rel, content in FIXTURE_FILES.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(["init", "-q", "-b", "main"], path)
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "fixture: normalize_tags stub"], path)
    return path


def write_acceptance_script(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ACCEPTANCE_SCRIPT, encoding="utf-8")
    return path


def make_task_spec(
    repo: Path,
    acceptance: Path,
    scenario: str,
    *,
    python: str | None = None,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    py = python or sys.executable
    spec: dict[str, Any] = {
        "schema_version": "1.0",
        "goal": "Implement tagnorm.normalize.normalize_tags per the requirements.",
        "repo": {"path": str(repo), "base_ref": "HEAD"},
        "requirements": [
            "Strip surrounding whitespace from each tag",
            "Lowercase each tag",
            "Drop empty strings",
            "Remove duplicates",
            "Preserve the order of first occurrences",
        ],
        "allowed_paths": ["tagnorm/**", "tests/**"],
        "forbidden_paths": [".github/**", ".env", ".env.*", "**/.env", "**/.env.*"],
        "verification": [
            {
                "id": "repo-tests",
                "argv": [py, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                "cwd": ".",
                "timeout_seconds": 60,
                "required": True,
                "trust": "repository-tests",
            },
            {
                "id": "acceptance",
                "argv": [py, "-B", str(acceptance)],
                "cwd": ".",
                "timeout_seconds": 60,
                "required": True,
                "trust": "external-acceptance",
            },
        ],
        "limits": {
            "max_attempts": 3,
            "max_repair_cycles": 2,
            "wall_timeout_seconds": 60,
            "max_turns_per_attempt": 20,
            "max_artifact_bytes": 10485760,
            "kill_grace_seconds": 2,
        },
        "executor": {"kind": "fake", "requested_model": None, "scenario": scenario},
    }
    if limits:
        spec["limits"].update(limits)
    return spec
