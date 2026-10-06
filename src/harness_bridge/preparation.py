"""Explicit, bounded workspace setup, with durable process observations and resource leases.

Commands are trusted Advisor inputs, never discovered from executor output or repo scripts.
This is not a sandbox: wrappers/install scripts need the same review as their top-level argv.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, field_validator, model_validator

from harness_bridge.artifacts import store_capture
from harness_bridge.baselines import read_record
from harness_bridge.coordination import Contract, check_key
from harness_bridge.errors import BridgeError
from harness_bridge.models import canonical_json, sha256_digest
from harness_bridge.policy import is_secret_path, redact_text, validate_relative_path
from harness_bridge.runner import ProcessSpec, RunLimits, run_process, runner_identity
from harness_bridge.state import TaskState as S
from harness_bridge.store import new_id, utc_now

if TYPE_CHECKING:
    from harness_bridge.service import Bridge


class SetupCommand(Contract):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    argv: list[str] = Field(min_length=1, max_length=256)
    cwd: str = "."
    timeout_seconds: float = Field(gt=0, le=3600)

    @field_validator("cwd")
    @classmethod
    def local_cwd(cls, value: str) -> str:
        return value if value == "." else validate_relative_path(value)

    @field_validator("argv")
    @classmethod
    def no_inference_command(cls, value: list[str]) -> list[str]:
        if not value[0] or any("\0" in arg for arg in value):
            raise ValueError("setup argv must be nonempty and contain no NUL")
        name = Path(value[0]).name.lower()
        if name in {"claude", "codex", "zcode", "hbridge", "harness-bridge"}:
            raise ValueError("setup must not dispatch a coding harness")
        if any(redact_text(arg)[1] for arg in value):
            raise ValueError("setup argv must not contain credential material")
        return value


class PreparedOutput(Contract):
    path: str
    kind: Literal["artifact", "cache"] = "artifact"

    @field_validator("path")
    @classmethod
    def local_nonsecret(cls, value: str) -> str:
        validate_relative_path(value)
        if any(is_secret_path(p) for p in value.split("/")):
            raise ValueError("do not declare credential material as a preparation output")
        return value


class PreparationSpec(Contract):
    steps: list[SetupCommand] = Field(min_length=1, max_length=20)
    outputs: list[PreparedOutput] = Field(default_factory=list, max_length=100)
    resources: list[str] = Field(default_factory=list, max_length=30)
    max_runs: int = Field(default=3, ge=1, le=10)
    wall_timeout_seconds: float = Field(default=300, gt=0, le=3600)
    max_log_bytes: int = Field(default=256 * 1024, ge=8192, le=4 * 1024 * 1024)

    @field_validator("resources")
    @classmethod
    def resource_names(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value or len(value) > 100 or not all(c.isalnum() or c in "-_.:" for c in value):
                raise ValueError("resource names must be short local identifiers")
        if len(set(values)) != len(values):
            raise ValueError("duplicate resource")
        return values

    @model_validator(mode="after")
    def unique_entries(self) -> PreparationSpec:
        if len({s.id for s in self.steps}) != len(self.steps):
            raise ValueError("duplicate setup step")
        if len({o.path for o in self.outputs}) != len(self.outputs):
            raise ValueError("duplicate output path")
        return self


def setup_env(base: dict[str, str], home: Path) -> dict[str, str]:
    # Deliberately small inherited environment; no host auth/config or credential variables.
    env = {k: v for k, v in base.items() if k in {"PATH", "LANG", "LC_ALL", "TMPDIR"}}
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_DATA_HOME": str(home / "data"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "CI": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return env


class Preparations:
    def __init__(self, bridge: Bridge) -> None:
        self.bridge = bridge
        self.store = bridge.store

    def latest(self, cur: sqlite3.Cursor, task_id: str) -> dict[str, Any] | None:
        return read_record(
            cur.execute(
                "SELECT * FROM preparation_runs WHERE task_id=? ORDER BY rowid DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        )

    def save(self, cur: sqlite3.Cursor, record: dict[str, Any]) -> None:
        cur.execute(
            "UPDATE preparation_runs SET status=?,exit_confirmed=?,record_json=?,record_digest=? "
            "WHERE preparation_id=?",
            (
                record["status"],
                record["exit_confirmed"],
                canonical_json(record),
                sha256_digest(record),
                record["preparation_id"],
            ),
        )

    @staticmethod
    def unresolved(cur: sqlite3.Cursor, task_id: str) -> bool:
        return (
            cur.execute(
                "SELECT 1 FROM preparation_runs WHERE task_id=? AND COALESCE(exit_confirmed,0)<>1",
                (task_id,),
            ).fetchone()
            is not None
        )

    def reserve_resources(
        self, cur: sqlite3.Cursor, project_id: str, record: dict[str, Any]
    ) -> None:
        # Release only terminal, confirmed-stopped owners. Unknown runs keep their claims
        # even if someone manually resolves the task to FAILED/CANCELLED.
        cur.execute(
            "DELETE FROM preparation_resources WHERE task_id IN ("
            "SELECT task_id FROM tasks t WHERE state IN ('SUCCEEDED','FAILED','CANCELLED') "
            "AND NOT EXISTS (SELECT 1 FROM attempts a WHERE a.task_id=t.task_id "
            "AND COALESCE(a.exit_confirmed,0)<>1) AND NOT EXISTS (SELECT 1 FROM preparation_runs p "
            "WHERE p.task_id=t.task_id AND COALESCE(p.exit_confirmed,0)<>1))",
        )
        for name in record["resources"]:
            row = cur.execute(
                "SELECT task_id FROM preparation_resources WHERE name=?",
                (name,),
            ).fetchone()
            if row and row["task_id"] != record["task_id"]:
                raise BridgeError(
                    "STATE_CONFLICT",
                    "preparation resource is already held",
                    details={"resource": name, "owner_task_id": row["task_id"]},
                )
            cur.execute(
                "INSERT INTO preparation_resources VALUES (?,?,?,?) ON CONFLICT(name) "
                "DO UPDATE SET preparation_id=excluded.preparation_id",
                (project_id, name, record["task_id"], record["preparation_id"]),
            )

    def inventory(self, root: Path, spec: PreparationSpec) -> list[dict[str, Any]]:
        outputs = []
        for output in spec.outputs:
            path = root / output.path
            safe = path.resolve().is_relative_to(root.resolve())
            exists = safe and path.exists()
            outputs.append(
                {
                    "path": output.path,
                    "kind": output.kind,
                    "present": exists,
                    "type": ("directory" if path.is_dir() else "file") if exists else None,
                    "bytes": path.stat().st_size if exists and path.is_file() else None,
                }
            )
        return outputs

    def readiness(
        self, cur: sqlite3.Cursor, task_id: str, spec_data: dict[str, Any]
    ) -> dict[str, Any]:
        record = self.latest(cur, task_id)
        spec = PreparationSpec.model_validate(spec_data)
        task = self.store.get_task(task_id, cur=cur)
        valid = bool(
            record
            and record["status"] == "passed"
            and record["exit_confirmed"]
            and record["spec_digest"] == sha256_digest(spec.model_dump(mode="json"))
            and record["fingerprint_after"] == self.bridge.current_fingerprint(task)
            and all(o["present"] for o in self.inventory(Path(task.worktree_path or ""), spec))
        )
        brief = (
            {
                k: record[k]
                for k in (
                    "preparation_id",
                    "status",
                    "exit_confirmed",
                    "spec_digest",
                    "fingerprint_after",
                    "ended_at",
                )
            }
            if record
            else None
        )
        return {"required": True, "ready": valid, "latest": brief}

    def prepare(self, child_id: str, key: str) -> dict[str, Any]:
        from harness_bridge.service import _fault_point

        check_key(key)
        b = self.bridge
        with self.store.transaction() as cur:
            child = b.plans.get(cur, child_id)
            goal = b.coordination.guard_goal(cur, child["goal_id"], b.advisor_claim)
            if not child["task_id"]:
                raise BridgeError("STATE_CONFLICT", "materialize the child before preparation")
            data = json.loads(child["spec_json"]).get("preparation")
            if data is None:
                raise BridgeError("STATE_CONFLICT", "child has no explicit preparation steps")
            spec = PreparationSpec.model_validate(data)
            task = self.store.get_task(child["task_id"], cur=cur)
            replay = read_record(
                cur.execute(
                    "SELECT * FROM preparation_runs WHERE task_id=? AND idempotency_key=?",
                    (task.task_id, key),
                ).fetchone()
            )
            if replay:
                return {**replay, "replayed": True}
            if task.state != S.READY:
                raise BridgeError("STATE_CONFLICT", "preparation requires READY")
            b.coordination.guard_project_slot(
                cur, goal["project_id"], task.task_id, preparation=True
            )
            count = cur.execute(
                "SELECT count(*) FROM preparation_runs WHERE task_id=?", (task.task_id,)
            ).fetchone()[0]
            if count >= spec.max_runs:
                raise BridgeError("BUDGET_EXHAUSTED", "explicit preparation run limit reached")
            context = b._child_context(
                cur, task.task_id, require_ready=False, check_preparation=False
            )
            assert context is not None
            ownership = {"worktree", "repository_identity", "owned_branch", "base_ancestry"}
            if any(
                c["status"] != "present"
                for c in context["readiness"]["checks"]
                if c["kind"] in ownership
            ):
                raise BridgeError("PREFLIGHT_FAILED", "workspace ownership check failed")
            record = {
                "preparation_id": new_id("prep"),
                "task_id": task.task_id,
                "child_id": child_id,
                "goal_id": child["goal_id"],
                "status": "running",
                "spec_digest": sha256_digest(spec.model_dump(mode="json")),
                "runner": runner_identity(),
                "exit_confirmed": None,
                "steps": [],
                "outputs": [],
                "resources": spec.resources,
                "fingerprint_before": b.current_fingerprint(task),
                "fingerprint_after": None,
                "started_at": utc_now(),
                "ended_at": None,
                "active_process": None,
            }
            cur.execute(
                "INSERT INTO preparation_runs VALUES (?,?,?,?,?,?,?,?)",
                (
                    record["preparation_id"],
                    task.task_id,
                    key,
                    "running",
                    None,
                    canonical_json(record),
                    sha256_digest(record),
                    record["started_at"],
                ),
            )
            self.reserve_resources(cur, goal["project_id"], record)
            self.store.transition(
                cur,
                task.task_id,
                S.READY,
                S.PREPARING,
                reason="preparation_started",
                details={"runner": record["runner"], "preparation_id": record["preparation_id"]},
                event_type="preparation_started",
                payload={"preparation_id": record["preparation_id"]},
            )
        _fault_point("after_preparation_reserved")
        return self.execute(record, spec)

    def execute(self, record: dict[str, Any], spec: PreparationSpec) -> dict[str, Any]:
        from harness_bridge.service import _fault_point

        b = self.bridge
        task = self.store.get_task(record["task_id"])
        root = Path(task.worktree_path or "")
        logs = b.artifacts_root / task.task_id / record["preparation_id"]
        record["artifacts_directory"] = str(logs)
        home = logs / "home"
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = setup_env(b.env, home)
        stop = b._should_stop_factory(task.task_id)
        deadline = time.monotonic() + spec.wall_timeout_seconds
        status, confirmed = "passed", True
        try:
            for step in spec.steps:
                record["last_step"] = step.id
                stopped = stop()
                if stopped:
                    status = stopped
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    status = "timed_out"
                    break
                cwd = (root / step.cwd).resolve()
                if not cwd.is_relative_to(root.resolve()) or not cwd.is_dir():
                    status = "invalid_cwd"
                    break
                record["active_process"] = {"step": step.id, "pid": None, "pgid": None}
                with self.store.transaction() as cur:
                    self.save(cur, record)

                def spawned(pid: int, pgid: int, step_id: str = step.id) -> None:
                    record["active_process"] = {"step": step_id, "pid": pid, "pgid": pgid}
                    with self.store.transaction() as cur:
                        self.save(cur, record)
                    _fault_point("after_preparation_spawn")

                size = spec.max_log_bytes // (len(spec.steps) * 4)
                outcome = run_process(
                    ProcessSpec(argv=list(step.argv), cwd=str(cwd), env=env),
                    RunLimits(
                        wall_timeout=min(remaining, step.timeout_seconds),
                        kill_grace=1,
                        stdout_head=size,
                        stdout_tail=size,
                        stderr_head=size,
                        stderr_tail=size,
                    ),
                    on_spawn=spawned,
                    should_stop=stop,
                )
                confirmed = bool(outcome.spawn_error or outcome.group_exit_confirmed)
                step_status = (
                    "unknown"
                    if not confirmed
                    else "spawn_failed"
                    if outcome.spawn_error
                    else outcome.stop_reason
                    or (
                        "timed_out"
                        if outcome.timed_out
                        else "background_process"
                        if outcome.background_killed
                        else "passed"
                        if outcome.returncode == 0
                        else "failed"
                    )
                )
                record["steps"].append(
                    {
                        "id": step.id,
                        "argv": list(step.argv),
                        "cwd": step.cwd,
                        "status": step_status,
                        "exit_code": outcome.returncode,
                        "exit_confirmed": confirmed,
                        "duration_seconds": round(outcome.duration, 3),
                        "stdout": store_capture(logs / f"{step.id}.stdout.log", outcome.stdout),
                        "stderr": store_capture(logs / f"{step.id}.stderr.log", outcome.stderr),
                    }
                )
                record["active_process"] = None if confirmed else record["active_process"]
                with self.store.transaction() as cur:
                    self.save(cur, record)
                if step_status != "passed":
                    status = step_status
                    break
            if confirmed:
                record["fingerprint_after"] = b.current_fingerprint(task)
                record["outputs"] = self.inventory(root, spec)
            if status == "passed":
                context = b._child_context_for_preparation(task.task_id)
                if record["fingerprint_after"] != record["fingerprint_before"]:
                    status = "candidate_changed"
                elif not all(o["present"] for o in record["outputs"]) or not context["ready"]:
                    status = "requirements_missing"
            # Cancellation arriving during post-process checks still wins.
            if confirmed and stop():
                status = stop() or "interrupted"
        except Exception as exc:
            # Never infer that a spawned process stopped merely because local recording failed.
            status, confirmed = "observation_failed", False
            record["observation_error"] = type(exc).__name__
        with self.store.transaction() as cur:
            # Completion is a mechanical observation of already accepted work, including
            # after an Advisor takeover. It cannot reserve another setup/executor run.
            if confirmed and self.store.get_task(task.task_id, cur=cur).cancel_requested:
                status = "cancelled"
            record.update(status=status, exit_confirmed=confirmed, ended_at=utc_now())
            target = (
                S.INTERRUPTED
                if not confirmed or status == "interrupted"
                else S.CANCELLED
                if status == "cancelled"
                else S.READY
                if status == "passed"
                else S.BLOCKED
            )
            self.save(cur, record)
            self.store.transition(
                cur,
                task.task_id,
                S.PREPARING,
                target,
                reason="preparation_" + status,
                details={
                    "phase": "preparation",
                    "outcome_known": confirmed,
                    "preparation_id": record["preparation_id"],
                },
                event_type="preparation_completed",
                payload={"preparation_id": record["preparation_id"], "status": status},
            )
            if confirmed and status != "passed":
                cur.execute("DELETE FROM preparation_resources WHERE task_id=?", (task.task_id,))
        return {**record, "replayed": False}
