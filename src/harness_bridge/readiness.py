"""Non-executing worktree readiness probes. Presence is not proof a tool/service works."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from harness_bridge.coordination import Contract
from harness_bridge.models import TaskSpec
from harness_bridge.policy import validate_relative_path
from harness_bridge.store import TaskRecord
from harness_bridge.workspace import git


class EnvironmentRequirements(Contract):
    files: list[str] = Field(default_factory=list, max_length=100)
    directories: list[str] = Field(default_factory=list, max_length=100)
    executables: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("files", "directories")
    @classmethod
    def relative_paths(cls, values: list[str]) -> list[str]:
        for value in values:
            validate_relative_path(value)
        return values

    @field_validator("executables")
    @classmethod
    def executable_names(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value or "\0" in value or not value.isprintable():
                raise ValueError("invalid executable")
            if "/" in value and not Path(value).is_absolute():
                validate_relative_path(value)
        return values


def inspect_readiness(
    task: TaskRecord, spec: TaskSpec, requirements: EnvironmentRequirements, env: dict[str, str]
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    root = Path(task.worktree_path or "").resolve()

    def record(kind: str, target: str, present: bool) -> None:
        checks.append(
            {"kind": kind, "target": target, "status": "present" if present else "missing"}
        )

    def confined(path: Path) -> bool:
        return path.resolve().is_relative_to(root)

    def executable(name: str, cwd: Path) -> bool:
        if "/" in name:
            path = Path(name)
            if not path.is_absolute():
                path = cwd / path
                if not confined(path):
                    return False
            return path.is_file() and os.access(path, os.X_OK)
        # Relative PATH entries are interpreted relative to the assigned cwd, not the
        # Advisor's working directory. This does not execute the located binary.
        path_env = os.pathsep.join(
            str(Path(p) if Path(p).is_absolute() else cwd / p)
            for p in env.get("PATH", "").split(os.pathsep)
        )
        return shutil.which(name, path=path_env) is not None

    record("worktree", str(root), bool(task.worktree_path) and root.is_dir())
    if task.worktree_path and root.is_dir():
        common = git(
            ["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, check=False
        )
        branch = git(["symbolic-ref", "-q", "HEAD"], cwd=root, check=False)
        base = git(["merge-base", "--is-ancestor", task.base_sha, "HEAD"], cwd=root, check=False)
        record(
            "repository_identity",
            task.repo_identity,
            common.returncode == 0
            and os.path.realpath(common.stdout.decode().strip()) == task.repo_identity,
        )
        record(
            "owned_branch",
            task.task_branch or "",
            branch.returncode == 0
            and branch.stdout.decode().strip() == f"refs/heads/{task.task_branch}",
        )
        record("base_ancestry", task.base_sha, base.returncode == 0)
    for name in requirements.files:
        path = root / name
        record("file", name, confined(path) and path.is_file())
    for name in requirements.directories:
        path = root / name
        record("directory", name, confined(path) and path.is_dir())
    for name in requirements.executables:
        record("executable", name, executable(name, root))
    for check in spec.verification:
        if check.required:
            cwd = root / check.cwd
            valid = confined(cwd) and cwd.is_dir()
            record("verification_cwd", check.id, valid)
            record("verification_executable", check.id, valid and executable(check.argv[0], cwd))
    return {
        "task_id": task.task_id,
        "ready": all(c["status"] == "present" for c in checks),
        "checks": checks,
        "scope": "presence, ownership and base ancestry only; Git metadata queries are used; "
        "no readiness commands, installs, login, "
        "tool versions, service connectivity or model inference are tested",
    }
