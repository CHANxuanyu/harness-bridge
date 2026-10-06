"""Durable, explicitly requested integration checks and snapshot-bound Advisor decisions.

No Executor is dispatched. Unknown checker exits retain an exclusive project reservation;
recovery records observations but never guesses process ownership or reruns a check.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from harness_bridge.artifacts import atomic_write_json
from harness_bridge.baselines import read_record
from harness_bridge.coordination import Contract, check_key, parse_contract
from harness_bridge.dispatch import guard_integration_hold, occupied_tasks
from harness_bridge.errors import BridgeError
from harness_bridge.models import Finding, VerificationCommand, canonical_json, sha256_digest
from harness_bridge.preparation import SetupCommand, setup_env
from harness_bridge.runner import runner_alive, runner_identity
from harness_bridge.store import new_id, utc_now
from harness_bridge.verification import CheckResult, aggregate_status, run_checks, warnings_for

if TYPE_CHECKING:
    from harness_bridge.service import Bridge

MAX_RUNS = 10
STREAM_BYTES = 64 * 1024


class IntegrationReview(Contract):
    schema_version: Literal["1.0"]
    integration_id: str = Field(min_length=1, max_length=128)
    verification_run_id: str = Field(min_length=1, max_length=128)
    snapshot_digest: str = Field(min_length=1, max_length=256)
    verdict: Literal["approve", "changes_requested", "blocked"]
    findings: list[Finding] = Field(default_factory=list, max_length=100)
    reviewer_label: str = Field(default="external-advisor", max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def findings_required(self) -> IntegrationReview:
        if self.verdict != "approve" and not self.findings:
            raise ValueError("negative decisions require findings")
        if self.verdict == "approve" and any(
            f.severity in ("blocking", "major") for f in self.findings
        ):
            raise ValueError("approval cannot contain blocking or major findings")
        return self


class IntegrationChecks:
    def __init__(self, bridge: Bridge) -> None:
        self.b = bridge
        self.store = bridge.store

    def latest(self, cur: sqlite3.Cursor, integration_id: str) -> dict[str, Any] | None:
        row = cur.execute(
            "SELECT * FROM integration_verifications WHERE integration_id=? "
            "ORDER BY rowid DESC LIMIT 1",
            (integration_id,),
        ).fetchone()
        if row is None:
            return None
        record = read_record(row)
        assert record is not None
        if (
            record["run_id"] != row["run_id"]
            or record["status"] != row["status"]
            or record["exit_confirmed"] != row["exit_confirmed"]
            or record["integration_id"] != integration_id
        ):
            raise BridgeError("INTEGRITY_ERROR", "integration verification binding changed")
        return record

    def save(self, cur: sqlite3.Cursor, record: dict[str, Any]) -> None:
        cur.execute(
            "UPDATE integration_verifications SET status=?,exit_confirmed=?,record_json=?,"
            "record_digest=? WHERE run_id=?",
            (
                record["status"],
                record["exit_confirmed"],
                canonical_json(record),
                sha256_digest(record),
                record["run_id"],
            ),
        )

    def directory(self, record: dict[str, Any]) -> Path:
        path = (
            self.b.state_dir
            / "artifacts"
            / "integrations"
            / str(record["integration_id"])
            / str(record["run_id"])
        )
        for ancestor in (path, *path.parents):
            if ancestor == self.b.state_dir:
                break
            if ancestor.is_symlink():
                raise BridgeError("INTEGRITY_ERROR", "integration evidence path is a symlink")
        return path

    def candidate(self, cur: sqlite3.Cursor, integration: dict[str, Any]) -> str:
        self.b.integrations._validate(cur, integration)
        if (
            integration["result"] is None
            or integration["result"]["conflict_task_id"]
            or not integration["workspace"]
        ):
            raise BridgeError("STATE_CONFLICT", "materialized conflict-free integration required")
        if self.b.integrations._workspace_check(integration) != "unchanged":
            raise BridgeError("STALE_REVIEW", "integration candidate changed or is not owned")
        return sha256_digest(
            {
                "integration_id": integration["integration_id"],
                "goal_digest": integration["goal_digest"],
                "request_digest": integration["request_digest"],
                "inputs": integration["inputs"],
                "candidate": integration["result"],
                "verifier_digest": integration["verifier_digest"],
            }
        )

    def verify(self, integration_id: str, key: str) -> dict[str, Any]:
        from harness_bridge.service import _fault_point

        check_key(key)
        with self.store.transaction() as cur:
            integration = self.b.integrations.get(cur, integration_id)
            goal = self.b.coordination.guard_goal(cur, integration["goal_id"], self.b.advisor_claim)
            replay = read_record(
                cur.execute(
                    "SELECT * FROM integration_verifications "
                    "WHERE integration_id=? AND idempotency_key=?",
                    (integration_id, key),
                ).fetchone()
            )
            if replay is not None:
                return {**replay, "replayed": True}
            commands = [VerificationCommand.model_validate(c) for c in integration["verification"]]
            try:
                for cmd in commands:
                    SetupCommand.no_inference_command(cmd.argv)
            except ValueError:
                raise BridgeError(
                    "INVALID_INPUT",
                    "integration checks must not invoke a harness or contain credentials",
                ) from None
            fingerprint = self.candidate(cur, integration)
            guard_integration_hold(cur, goal["project_id"])
            if occupied_tasks(cur, goal["project_id"]):
                raise BridgeError("STATE_CONFLICT", "integration checks require an idle project")
            count = cur.execute(
                "SELECT count(*) FROM integration_verifications WHERE integration_id=?",
                (integration_id,),
            ).fetchone()[0]
            if count >= MAX_RUNS:
                raise BridgeError("BUDGET_EXHAUSTED", "integration verification run limit reached")
            record = {
                "run_id": new_id("ivr"),
                "integration_id": integration_id,
                "goal_id": integration["goal_id"],
                "status": "running",
                "exit_confirmed": True,
                "runner": runner_identity(),
                "active_process": None,
                "checks": [],
                "fingerprint_before": fingerprint,
                "fingerprint_after": None,
                "verifier_digest": integration["verifier_digest"],
                "candidate_commit": integration["result"]["commit_sha"],
                "warnings": [],
                "started_at": utc_now(),
                "ended_at": None,
                "manifest_digest": None,
            }
            cur.execute(
                "INSERT INTO integration_verifications VALUES (?,?,?,?,?,0,?,?,?)",
                (
                    record["run_id"],
                    integration_id,
                    key,
                    "running",
                    1,
                    canonical_json(record),
                    sha256_digest(record),
                    record["started_at"],
                ),
            )
            integration.update(
                phase="VERIFYING",
                verification_status="running",
                current_verification_id=record["run_id"],
                review_id=None,
            )
            self.b.integrations.save(cur, integration)
            self.b.coordination.event(
                cur,
                goal["goal_id"],
                goal["advisor_epoch"],
                "integration_verification_reserved",
                {"integration_id": integration_id, "run_id": record["run_id"]},
            )
        _fault_point("after_integration_verification_reserved")
        return self.execute(record, commands)

    def stopped(self, cur: sqlite3.Cursor, record: dict[str, Any]) -> str | None:
        row = cur.execute(
            "SELECT cancel_requested FROM integration_verifications WHERE run_id=?",
            (record["run_id"],),
        ).fetchone()
        if row[0] or self.b.coordination.controls(cur, record["goal_id"])["termination"]:
            return "cancelled"
        return self.b.stop_flag.reason

    def execute(
        self, record: dict[str, Any], commands: list[VerificationCommand]
    ) -> dict[str, Any]:
        from harness_bridge.service import _fault_point

        def stop() -> str | None:
            with self.store.transaction() as cur:
                return self.stopped(cur, record)

        status = "incomplete"
        try:
            with self.store.transaction() as cur:
                integration = self.b.integrations.get(cur, record["integration_id"])
            root = Path(integration["workspace"]["path"])
            logs = self.directory(record)
            home = logs / "home"
            home.mkdir(parents=True, exist_ok=True, mode=0o700)
            results: list[CheckResult] = []
            for cmd in commands:
                if reason := stop():
                    status = reason
                    break
                # Persist the uncertain launch window BEFORE Popen. Recovery never infers
                # non-execution merely from an absent PID after this point.
                record.update(
                    active_process={"check": cmd.id, "pid": None, "pgid": None}, exit_confirmed=None
                )
                with self.store.transaction() as cur:
                    self.save(cur, record)
                _fault_point("before_integration_check_spawn")

                def spawned(pid: int, pgid: int) -> None:
                    record["active_process"].update(pid=pid, pgid=pgid)
                    with self.store.transaction() as cur:
                        self.save(cur, record)
                    _fault_point("after_integration_check_spawn")

                items, stopped = run_checks(
                    [cmd],
                    worktree=root,
                    log_dir=logs,
                    base_env=setup_env(self.b.env, home),
                    bytes_per_stream=STREAM_BYTES,
                    kill_grace=1,
                    should_stop=stop,
                    on_spawn=spawned,
                )
                result = items[0]
                results.append(result)
                record.update(
                    exit_confirmed=result.exit_confirmed,
                    active_process=None if result.exit_confirmed else record["active_process"],
                )
                data = result.to_dict()
                for stream in ("stdout", "stderr"):
                    if data[stream]:
                        path = logs / data[stream]["file"]
                        data[stream]["digest"] = sha256_digest(
                            self.read_bytes(path, STREAM_BYTES * 2)
                        )
                record["checks"].append(data)
                with self.store.transaction() as cur:
                    self.save(cur, record)
                _fault_point("after_integration_check_recorded")
                if not result.exit_confirmed:
                    status = "unknown"
                    break
                if stopped:
                    status = stopped
                    break
            else:
                status = aggregate_status(results, record["fingerprint_before"], None)
            record["warnings"] = warnings_for(results)
        except Exception as exc:
            status = "observation_failed"
            record["observation_error"] = type(exc).__name__
            record["exit_confirmed"] = bool(
                record["exit_confirmed"] and record["active_process"] is None
            )
        with self.store.transaction() as cur:
            integration = self.b.integrations.get(cur, record["integration_id"])
            if record["exit_confirmed"]:
                try:
                    record["fingerprint_after"] = self.candidate(cur, integration)
                except BridgeError as exc:
                    record["candidate_error"] = exc.code
                    if status == "passed":
                        status = "invalidated"
                if reason := self.stopped(cur, record):
                    status = reason
            else:
                status = "unknown"
            record.update(status=status, ended_at=utc_now())
            try:
                manifest = self.manifest(record)
                encoded = atomic_write_json(self.directory(record) / "manifest.json", manifest)
                record["manifest_digest"] = sha256_digest(encoded)
            except (OSError, BridgeError) as exc:
                # Failed evidence storage cannot strand a proven-exited check as running.
                status = "observation_failed" if record["exit_confirmed"] else "unknown"
                record.update(status=status, observation_error=type(exc).__name__)
            self.save(cur, record)
            integration.update(
                phase="AWAITING_REVIEW"
                if record["exit_confirmed"] and status not in ("cancelled", "interrupted")
                else "INTERRUPTED",
                verification_status=status,
            )
            self.b.integrations.save(cur, integration)
            goal = self.b.coordination._goal(cur, integration["goal_id"])
            self.b.coordination.event(
                cur,
                integration["goal_id"],
                goal["advisor_epoch"],
                "integration_verification_finished",
                {
                    "run_id": record["run_id"],
                    "status": status,
                    "exit_confirmed": record["exit_confirmed"],
                },
            )
        return {**record, "replayed": False}

    @staticmethod
    def manifest(record: dict[str, Any]) -> dict[str, Any]:
        return {
            k: record[k]
            for k in (
                "run_id",
                "integration_id",
                "verifier_digest",
                "candidate_commit",
                "fingerprint_before",
                "fingerprint_after",
                "checks",
                "warnings",
                "status",
                "exit_confirmed",
            )
        }

    @staticmethod
    def read_bytes(path: Path, limit: int) -> bytes:
        if path.is_symlink():
            raise BridgeError("INTEGRITY_ERROR", "evidence file is a symlink")
        try:
            with path.open("rb") as source:
                data = source.read(limit + 1)
        except OSError:
            raise BridgeError("INTEGRITY_ERROR", "verification evidence missing") from None
        if len(data) > limit:
            raise BridgeError("INTEGRITY_ERROR", "verification evidence exceeds its bound")
        return data

    def evidence(
        self, cur: sqlite3.Cursor, integration: dict[str, Any], run: dict[str, Any]
    ) -> None:
        if run["status"] != "passed" or not run["exit_confirmed"] or run["active_process"]:
            raise BridgeError(
                "APPROVAL_GATE_FAILED", "integration verification did not pass with confirmed exits"
            )
        fingerprint = self.candidate(cur, integration)
        if run["fingerprint_before"] != fingerprint or run["fingerprint_after"] != fingerprint:
            raise BridgeError("STALE_REVIEW", "integration verification snapshot changed")
        if (
            integration.get("current_verification_id") != run["run_id"]
            or run["verifier_digest"] != integration["verifier_digest"]
            or run["candidate_commit"] != integration["result"]["commit_sha"]
        ):
            raise BridgeError("STALE_REVIEW", "verification is not current for this candidate")
        if len(run["checks"]) != len(integration["verification"]):
            raise BridgeError("INTEGRITY_ERROR", "verification command evidence is incomplete")
        for result, command in zip(run["checks"], integration["verification"], strict=True):
            if (
                any(result[k] != command[k] for k in ("id", "argv", "cwd", "required", "trust"))
                or not result["exit_confirmed"]
                or (command["required"] and result["status"] != "passed")
            ):
                raise BridgeError(
                    "INTEGRITY_ERROR", "check evidence differs from frozen verification"
                )
            for stream in ("stdout", "stderr"):
                if result[stream]:
                    path = self.directory(run) / f"{command['id']}.{stream}.log"
                    if (
                        result[stream]["file"] != path.name
                        or sha256_digest(self.read_bytes(path, STREAM_BYTES * 2))
                        != result[stream]["digest"]
                    ):
                        raise BridgeError("INTEGRITY_ERROR", "check log changed after verification")
        data = self.read_bytes(self.directory(run) / "manifest.json", 4 * 1024 * 1024)
        if sha256_digest(data) != run["manifest_digest"] or json.loads(data) != self.manifest(run):
            raise BridgeError("INTEGRITY_ERROR", "verification manifest changed")

    def cancel(self, integration_id: str) -> dict[str, Any]:
        with self.store.transaction() as cur:
            integration = self.b.integrations.get(cur, integration_id)
            run = self.latest(cur, integration_id)
            if run is None or (run["status"] != "running" and run["exit_confirmed"]):
                raise BridgeError("STATE_CONFLICT", "no active integration verification")
            cur.execute(
                "UPDATE integration_verifications SET cancel_requested=1 WHERE run_id=?",
                (run["run_id"],),
            )
            goal = self.b.coordination._goal(cur, integration["goal_id"])
            self.b.coordination.event(
                cur,
                goal["goal_id"],
                goal["advisor_epoch"],
                "integration_cancel_requested",
                {"run_id": run["run_id"]},
            )
            return {
                "integration_id": integration_id,
                "run_id": run["run_id"],
                "status": "cancellation_pending",
            }

    def recover(self, integration_id: str) -> dict[str, Any]:
        with self.store.transaction() as cur:
            integration = self.b.integrations.get(cur, integration_id)
            goal = self.b.coordination.guard_goal(
                cur, integration["goal_id"], self.b.advisor_claim, allow_stopping=True
            )
            run = self.latest(cur, integration_id)
            if run is None or run["status"] != "running":
                return {"integration_id": integration_id, "verification": run, "action": "none"}
            alive = runner_alive(run["runner"])
            if alive is True:
                return {
                    "integration_id": integration_id,
                    "verification": run,
                    "action": "owner_running",
                }
            if alive is None:
                raise BridgeError(
                    "CANNOT_CONFIRM_EXIT", "integration verifier owner liveness is unknown"
                )
            confirmed = bool(run["exit_confirmed"] and run["active_process"] is None)
            run.update(
                status="interrupted" if confirmed else "unknown",
                exit_confirmed=confirmed,
                ended_at=utc_now(),
            )
            self.save(cur, run)
            integration.update(phase="INTERRUPTED", verification_status=run["status"])
            self.b.integrations.save(cur, integration)
            self.b.coordination.event(
                cur,
                goal["goal_id"],
                goal["advisor_epoch"],
                "integration_verification_recovered",
                {"run_id": run["run_id"], "exit_confirmed": confirmed},
            )
            return {
                "integration_id": integration_id,
                "verification": run,
                "action": "recorded_without_execution",
            }

    def review(self, integration_id: str, data: Any) -> dict[str, Any]:
        decision = parse_contract(IntegrationReview, data)
        check_key(decision.idempotency_key)
        if decision.integration_id != integration_id:
            raise BridgeError("INVALID_INPUT", "review integration does not match argument")
        digest = sha256_digest(decision.model_dump(mode="json"))
        replayed = False
        with self.store.transaction() as cur:
            integration = self.b.integrations.get(cur, integration_id)
            goal = self.b.coordination.guard_goal(cur, integration["goal_id"], self.b.advisor_claim)
            row = cur.execute(
                "SELECT * FROM integration_reviews WHERE integration_id=? AND idempotency_key=?",
                (integration_id, decision.idempotency_key),
            ).fetchone()
            if row:
                if row["request_digest"] != digest:
                    raise BridgeError("IDEMPOTENCY_CONFLICT", "integration review key already used")
                receipt = read_record(row)
                assert receipt is not None
                replayed = True
            else:
                run = self.latest(cur, integration_id)
                if run is None or run["status"] == "running" or not run["exit_confirmed"]:
                    raise BridgeError(
                        "STATE_CONFLICT", "review requires completed, confirmed verification"
                    )
                if (
                    run["run_id"] != decision.verification_run_id
                    or run["fingerprint_before"] != decision.snapshot_digest
                ):
                    raise BridgeError(
                        "STALE_REVIEW", "review must bind the current verification snapshot"
                    )
                blockers = []
                if decision.verdict == "approve":
                    try:
                        self.evidence(cur, integration, run)
                    except BridgeError as exc:
                        blockers.append({"code": exc.code, "message": exc.message})
                receipt = {
                    "review_id": new_id("irev"),
                    "integration_id": integration_id,
                    "verification_run_id": run["run_id"],
                    "snapshot_digest": decision.snapshot_digest,
                    "verdict": decision.verdict,
                    "status": "rejected" if blockers else "accepted",
                    "advisor_binding_id": goal["binding_id"],
                    "advisor_epoch": goal["advisor_epoch"],
                    "reviewer_label": decision.reviewer_label,
                    "findings": [f.model_dump(mode="json") for f in decision.findings],
                    "candidate_commit": run["candidate_commit"],
                    "blockers": blockers,
                }
                cur.execute(
                    "INSERT INTO integration_reviews VALUES (?,?,?,?,?,?,?)",
                    (
                        receipt["review_id"],
                        integration_id,
                        decision.idempotency_key,
                        digest,
                        canonical_json(receipt),
                        sha256_digest(receipt),
                        utc_now(),
                    ),
                )
                if not blockers:
                    integration.update(
                        phase={
                            "approve": "APPROVED",
                            "changes_requested": "CHANGES_REQUESTED",
                            "blocked": "BLOCKED",
                        }[decision.verdict],
                        review_id=receipt["review_id"],
                    )
                    self.b.integrations.save(cur, integration)
                self.b.coordination.event(
                    cur, goal["goal_id"], goal["advisor_epoch"], "integration_reviewed", receipt
                )
        if receipt["status"] == "rejected":
            raise BridgeError(
                "APPROVAL_GATE_FAILED",
                "integration approval rejected",
                details={"receipt": receipt, "replayed": replayed},
            )
        return {**receipt, "replayed": replayed}

    def summary(self, cur: sqlite3.Cursor, integration: dict[str, Any]) -> dict[str, Any]:
        run = self.latest(cur, integration["integration_id"])
        review = read_record(
            cur.execute(
                "SELECT * FROM integration_reviews WHERE review_id=?",
                (integration.get("review_id"),),
            ).fetchone()
        )
        current = False
        blockers = []
        if review and review["verdict"] == "approve" and run:
            try:
                goal = self.b.coordination._goal(cur, integration["goal_id"])
                if self.b.coordination.controls(cur, goal["goal_id"])["termination"]:
                    raise BridgeError("STATE_CONFLICT", "goal termination requested")
                if (
                    review["advisor_epoch"] != goal["advisor_epoch"]
                    or review["advisor_binding_id"] != goal["binding_id"]
                ):
                    raise BridgeError("STALE_ADVISOR", "approval belongs to an older Advisor")
                if (
                    review["integration_id"] != integration["integration_id"]
                    or review["review_id"] != integration.get("review_id")
                    or review["status"] != "accepted"
                    or review["candidate_commit"] != run["candidate_commit"]
                    or review["verification_run_id"] != run["run_id"]
                    or review["snapshot_digest"] != run["fingerprint_before"]
                ):
                    raise BridgeError(
                        "STALE_REVIEW", "approval no longer matches current verification"
                    )
                self.evidence(cur, integration, run)
                current = True
            except BridgeError as exc:
                blockers.append({"code": exc.code, "message": exc.message})
        return {
            "verification_run": run,
            "review": review,
            "approval_current": current,
            "approval_blockers": blockers,
            "review_template": None
            if not run or run["status"] == "running"
            else {
                "schema_version": "1.0",
                "integration_id": integration["integration_id"],
                "verification_run_id": run["run_id"],
                "snapshot_digest": run["fingerprint_before"],
                "verdict": "approve",
                "findings": [],
                "idempotency_key": "REPLACE_WITH_NEW_KEY",
            },
        }
