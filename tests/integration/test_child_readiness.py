"""Explicit child requirements prevent dispatch without consuming model attempts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from harness_bridge.adapters.base import InvocationContext, TaskPacket
from harness_bridge.adapters.fake import FakeExecutorAdapter
from harness_bridge.errors import BridgeError
from harness_bridge.workspace import git
from tests.conftest import Fixture
from tests.integration.test_coordination import setup_goal
from tests.integration.test_dependency_baselines import children
from tests.integration.test_goal_planning import plan, submit


@pytest.mark.parametrize("missing", ["file", "directory", "executable", "check-cwd", "check-bin"])
def test_missing_requirements_prevent_spawn_and_keep_budget(fx: Fixture, missing: str) -> None:
    b, g = setup_goal(fx)
    p = plan(fx, "a")
    requirements: dict[str, Any] = {"files": [], "directories": [], "executables": []}
    if missing == "file":
        requirements["files"] = ["tagnorm/required.txt"]
    elif missing == "directory":
        requirements["directories"] = ["local-dependencies"]
    elif missing == "executable":
        requirements["executables"] = ["tools/required-tool"]
    elif missing == "check-cwd":
        p["task"]["verification"][0]["cwd"] = "absent-check-directory"
    else:
        p["task"]["verification"][0]["argv"][0] = "hbridge-nonexistent-tool"
    p["environment"] = requirements
    child = children(b, g, p)["a"]
    task = b.materialize(child)["task_id"]
    initial = b.coordination.status(g["goal_id"])["budget"]
    assert not b.child_preflight(child)["ready"]
    with pytest.raises(BridgeError) as err:
        b.run(task)
    assert err.value.code == "PREFLIGHT_FAILED"
    assert err.value.details["ready"] is False
    assert b.store.list_attempts(task) == []
    assert b.status(task)["state"] == "READY"
    assert b.coordination.status(g["goal_id"])["budget"] == initial
    b.close()


def test_explicit_local_preparation_unblocks_same_task_without_running_probe_binary(
    fx: Fixture,
) -> None:
    b, g = setup_goal(fx)
    p = plan(fx, "a")
    p["environment"] = {
        "files": ["tagnorm/__init__.py"],
        "directories": ["__pycache__"],
        "executables": ["__pycache__/probe"],
    }
    child = children(b, g, p)["a"]
    task = b.materialize(child)["task_id"]
    assert not b.child_preflight(child)["ready"]
    root = Path(b.store.get_task(task).worktree_path)
    (root / "__pycache__").mkdir()
    marker = fx.base / "probe-executed"
    binary = root / "__pycache__/probe"
    binary.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    binary.chmod(0o755)
    assert b.child_preflight(child)["ready"]
    _, output = fx.cli("child", "preflight", child)
    assert output["ready"]
    assert not marker.exists()
    b.run(task)
    assert b.status(task)["state"] == "AWAITING_REVIEW"
    assert not marker.exists()
    assert b.store.get_task(task).attempts_used == 1
    b.close()


def test_late_environment_change_is_checked_at_dispatch_reservation(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, g = setup_goal(fx)
    p = plan(fx, "a")
    p["environment"] = {"files": ["README.md"]}
    child = children(b, g, p)["a"]
    task = b.materialize(child)["task_id"]
    build = FakeExecutorAdapter.build_invocation

    def change(self: FakeExecutorAdapter, packet: TaskPacket, ctx: InvocationContext) -> Any:
        (Path(ctx.worktree) / "README.md").unlink()
        return build(self, packet, ctx)

    monkeypatch.setattr(FakeExecutorAdapter, "build_invocation", change)
    with pytest.raises(BridgeError) as err:
        b.run(task)
    assert err.value.code == "PREFLIGHT_FAILED"
    assert b.store.list_attempts(task) == []
    assert b.status(task)["state"] == "READY"
    b.close()


def test_required_paths_cannot_borrow_another_workspace_through_symlinks(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    p = plan(fx, "a")
    p["environment"] = {
        "files": ["borrowed/file"],
        "directories": ["borrowed"],
        "executables": ["borrowed/tool"],
    }
    child = children(b, g, p)["a"]
    task = b.materialize(child)["task_id"]
    outside = fx.base / "outside"
    outside.mkdir()
    (outside / "file").touch()
    (outside / "tool").write_text("#!/bin/sh\nexit 0\n")
    (outside / "tool").chmod(0o755)
    (Path(b.store.get_task(task).worktree_path) / "borrowed").symlink_to(outside)
    result = b.child_preflight(child)
    assert not result["ready"]
    assert len([c for c in result["checks"] if c["status"] == "missing"]) == 3
    b.close()


def test_wrong_branch_prevents_dispatch(fx: Fixture) -> None:
    b, g = setup_goal(fx)
    child = children(b, g, plan(fx, "a"))["a"]
    task = b.materialize(child)["task_id"]
    git(["checkout", "--detach"], cwd=b.store.get_task(task).worktree_path)
    with pytest.raises(BridgeError) as err:
        b.run(task)
    assert err.value.code == "PREFLIGHT_FAILED"
    assert b.store.list_attempts(task) == []
    b.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("files", "../secret"),
        ("directories", "/tmp"),
        ("executables", "../tool"),
        ("executables", "tool\0arg"),
    ],
)
def test_invalid_environment_requirements_never_create_a_plan(
    fx: Fixture, field: str, value: str
) -> None:
    b, g = setup_goal(fx)
    p = plan(fx, "a")
    p["environment"] = {field: [value]}
    with pytest.raises(BridgeError) as err:
        submit(b, g, p)
    assert err.value.code == "INVALID_INPUT"
    assert b.coordination.status(g["goal_id"])["plans"] == []
    b.close()
