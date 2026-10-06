"""Executable P7 packet: fresh isolation, independent checks and two synthetic adapters only."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from qa.local.p7_fixture import NORMALIZE, RENDER, digest, isolated_env, prepare
from qa.local.p7_rehearsal import Rehearsal

from harness_bridge.coordination import GoalSpec
from harness_bridge.planning import PlanBatch


def test_preparation_only_creates_valid_frozen_packets(tmp_path: Path) -> None:
    root = tmp_path / "fresh fixture"
    manifest = prepare(root)
    assert not (root / "state").exists()
    assert list((root / "home").iterdir()) == []
    assert manifest["live_ready"] is False and manifest["live_authorized"] is False
    assert manifest["inference_performed"] is False
    goal = GoalSpec.model_validate_json((root / "goal.json").read_text())
    plan = PlanBatch.model_validate_json((root / "plan.json").read_text())
    assert goal.max_attempts == 3 and goal.max_repairs == 1
    assert {c.task.executor.kind for c in plan.children} == {"claude-code", "codex"}
    assert all(c.task.executor.requested_model == "synthetic-pin" for c in plan.children)
    for path, expected in manifest["files"].items():
        assert digest(root / path) == expected


@pytest.mark.parametrize("existing", ["empty", "occupied", "symlink"])
def test_preparation_refuses_reused_or_linked_root(tmp_path: Path, existing: str) -> None:
    root = tmp_path / "fixture"
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep").write_text("user data")
    if existing == "symlink":
        root.symlink_to(target, target_is_directory=True)
    else:
        root.mkdir()
        if existing == "occupied":
            (root / "keep").write_text("user data")
    with pytest.raises(FileExistsError):
        prepare(root)
    assert (target / "keep").read_text() == "user data"
    assert not (root / "repo").exists()


def test_combined_check_requires_both_independent_implementations(tmp_path: Path) -> None:
    root = tmp_path / "checks"
    prepare(root)
    expected_hash = digest(root / "acceptance.py")

    def check(mode: str) -> int:
        return subprocess.run(
            [sys.executable, "-B", str(root / "acceptance.py"), mode],
            cwd=root / "repo",
            env=isolated_env(root),
            capture_output=True,
            timeout=10,
        ).returncode

    assert check("normalize") != 0 and check("render") != 0 and check("combined") != 0
    (root / "repo/tagnorm/normalize.py").write_text(NORMALIZE)
    assert check("normalize") == 0 and check("combined") != 0
    (root / "repo/tagformat/render.py").write_text(RENDER)
    assert check("render") == 0 and check("combined") == 0
    assert digest(root / "acceptance.py") == expected_hash


def test_two_adapter_rehearsal_takeover_repair_and_exact_delivery(tmp_path: Path) -> None:
    root = tmp_path / "p7 with spaces"
    result = Rehearsal(root).run()
    assert result == json.loads((root / "result.json").read_text())
    assert result["two_workers_observed_running"] and result["stale_advisor_refused"]
    assert result["exact_session_resume"] and result["source_unchanged"]
    assert result["acceptance_and_packets_unchanged"] and not result["inference_performed"]
    assert result["stub_calls"] == {"claude-code": 2, "codex": 1}
    assert result["budget"]["attempts"] == 3
    assert all(j["executor_exit_confirmed"] for j in result["initial_jobs"])
    assert result["repair_job"]["executor_exit_confirmed"]
    assert (root / "state/config.toml").read_text().endswith("enabled=false\n")


@pytest.mark.parametrize("option", ["--live", "--allow-model-usage"])
def test_rehearsal_has_no_live_command_option(tmp_path: Path, option: str) -> None:
    root = tmp_path / "refused"
    proc = subprocess.run(
        [sys.executable, "-m", "qa.local.p7_rehearsal", str(root), option],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 2 and "unrecognized arguments" in proc.stderr
    assert not root.exists()
