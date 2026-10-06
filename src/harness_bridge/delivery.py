"""Exact local branch delivery: durable intent, atomic ref pair, read-only replay.

Git and SQLite cannot share a transaction. A private ref created atomically with the
requested branch proves publication after a crash; neither missing nor moved completed
branches are recreated. No checkout, reset, push, merge, cleanup or model invocation.
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, field_validator

from harness_bridge.baselines import read_record
from harness_bridge.coordination import Contract, check_key, parse_contract
from harness_bridge.dispatch import integration_holds, occupied_tasks
from harness_bridge.errors import BridgeError
from harness_bridge.models import canonical_json, sha256_digest
from harness_bridge.store import new_id, utc_now
from harness_bridge.workspace import git, source_status

if TYPE_CHECKING:
    from harness_bridge.service import Bridge


class DeliveryRequest(Contract):
    schema_version: Literal["1.0"] = "1.0"
    integration_id: str = Field(min_length=1, max_length=128)
    branch: str = Field(min_length=1, max_length=200)

    @field_validator("branch")
    @classmethod
    def safe_branch(cls, value: str) -> str:
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", value)
            or value.lower() in ("head", "hbridge")
            or value.lower().startswith(("refs/", "hbridge/"))
        ):
            raise ValueError("delivery requires an ordinary non-reserved local branch name")
        return value


class Deliveries:
    def __init__(self, bridge: Bridge) -> None:
        self.b = bridge
        self.store = bridge.store

    def get(self, cur: sqlite3.Cursor, delivery_id: str) -> dict[str, Any]:
        row = cur.execute("SELECT * FROM deliveries WHERE delivery_id=?", (delivery_id,)).fetchone()
        if row is None:
            raise BridgeError("NOT_FOUND", "delivery does not exist")
        record = read_record(row)
        assert record is not None
        if any(
            record[k] != row[k]
            for k in ("delivery_id", "goal_id", "project_id", "branch", "status")
        ):
            raise BridgeError("INTEGRITY_ERROR", "delivery record binding changed")
        if sha256_digest(record["request"]) != row["request_digest"]:
            raise BridgeError("INTEGRITY_ERROR", "delivery request digest changed")
        if (
            record["branch"] != record["request"]["branch"]
            or record["integration_id"] != record["request"]["integration_id"]
            or record["proof_ref"] != f"refs/hbridge/deliveries/{delivery_id}"
        ):
            raise BridgeError("INTEGRITY_ERROR", "delivery intent fields differ from its request")
        return record

    def save(self, cur: sqlite3.Cursor, record: dict[str, Any]) -> None:
        cur.execute(
            "UPDATE deliveries SET status=?,record_json=?,record_digest=? WHERE delivery_id=?",
            (
                record["status"],
                canonical_json(record),
                sha256_digest(record),
                record["delivery_id"],
            ),
        )

    def active(self, cur: sqlite3.Cursor, goal_id: str) -> dict[str, Any] | None:
        row = cur.execute(
            "SELECT delivery_id FROM deliveries WHERE goal_id=? AND status<>'aborted'",
            (goal_id,),
        ).fetchone()
        return self.get(cur, row[0]) if row else None

    def latest_integration(self, cur: sqlite3.Cursor, goal_id: str) -> str | None:
        row = cur.execute(
            "SELECT integration_id FROM integrations WHERE goal_id=? ORDER BY rowid DESC LIMIT 1",
            (goal_id,),
        ).fetchone()
        return str(row[0]) if row else None

    def approved(
        self, cur: sqlite3.Cursor, goal: sqlite3.Row, integration_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.b.coordination.controls(cur, goal["goal_id"])["termination"]:
            raise BridgeError("STATE_CONFLICT", "goal termination has been requested")
        if self.latest_integration(cur, goal["goal_id"]) != integration_id:
            raise BridgeError(
                "STALE_REVIEW", "only the latest frozen goal integration can be delivered"
            )
        integration = self.b.integrations.get(cur, integration_id)
        summary = self.b.integration_checks.summary(cur, integration)
        if integration["phase"] != "APPROVED" or not summary["approval_current"]:
            raise BridgeError(
                "APPROVAL_GATE_FAILED",
                "delivery requires current exact integration approval",
                details={"blockers": summary["approval_blockers"]},
            )
        if integration_holds(cur, goal["project_id"]) or occupied_tasks(cur, goal["project_id"]):
            raise BridgeError(
                "STATE_CONFLICT", "delivery requires a project with no active or unknown exits"
            )
        return integration, summary

    @staticmethod
    def identity(record: dict[str, Any]) -> None:
        actual = (
            git(
                ["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=record["repo_path"]
            )
            .stdout.decode()
            .strip()
        )
        if os.path.realpath(actual) != record["repo_identity"]:
            raise BridgeError("INTEGRITY_ERROR", "delivery repository identity changed")

    @staticmethod
    def refs(repo: str) -> dict[str, tuple[str, str]]:
        # Git ref names/object IDs contain no LF; for-each-ref appends one after each
        # NUL-separated tuple. Preserve exact names; never resolve a symbolic target.
        data = git(
            ["for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)%00"], cwd=repo
        ).stdout
        fields = data.replace(b"\n", b"").decode("utf-8", "surrogateescape").split("\0")
        return {fields[i]: (fields[i + 1], fields[i + 2]) for i in range(0, len(fields) - 1, 3)}

    @staticmethod
    def symbolic(repo: str, ref: str) -> str | None:
        result = git(["symbolic-ref", "-q", ref], cwd=repo, check=False)
        if result.returncode not in (0, 1):
            raise BridgeError("REPO_ERROR", "could not inspect delivery symbolic ref")
        return result.stdout.decode().strip() if result.returncode == 0 else None

    def observations(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            self.identity(record)
            refs = self.refs(record["repo_path"])
            branch = refs.get(f"refs/heads/{record['branch']}")
            proof = refs.get(record["proof_ref"])
            if target := self.symbolic(record["repo_path"], f"refs/heads/{record['branch']}"):
                branch = (branch[0] if branch else "", target)
            if target := self.symbolic(record["repo_path"], record["proof_ref"]):
                proof = (proof[0] if proof else "", target)
            expected = (record["commit_sha"], "")
            state = (
                "matching"
                if branch == proof == expected
                else "absent"
                if branch is None and proof is None
                else "changed"
            )
            return {"ref_status": state, "branch": branch, "proof": proof, "error": None}
        except BridgeError as exc:
            return {
                "ref_status": "unavailable",
                "branch": None,
                "proof": None,
                "error": {"code": exc.code, "message": exc.message},
            }

    def vacant(self, repo: str, branch: str, proof_ref: str) -> None:
        ref = f"refs/heads/{branch}"
        if git(["check-ref-format", ref], cwd=repo, check=False).returncode:
            raise BridgeError("INVALID_INPUT", "invalid Git branch name")
        refs = self.refs(repo)
        if self.symbolic(repo, ref) or self.symbolic(repo, proof_ref):
            raise BridgeError("DELIVERY_CONFLICT", "delivery ref is symbolic")
        if any(r.casefold() == ref.casefold() for r in refs) or proof_ref in refs:
            raise BridgeError("DELIVERY_CONFLICT", "delivery target or proof ref already exists")
        fields = git(["worktree", "list", "--porcelain", "-z"], cwd=repo).stdout.split(b"\0")
        if any(
            f.startswith(b"branch ") and f[7:].decode().casefold() == ref.casefold() for f in fields
        ):
            raise BridgeError(
                "DELIVERY_CONFLICT", "delivery branch is selected by an existing worktree"
            )

    @staticmethod
    def source_observation(record: dict[str, Any]) -> dict[str, Any]:
        repo = record["repo_path"]
        head = git(["rev-parse", "--verify", "HEAD^{commit}"], cwd=repo).stdout.decode().strip()
        counts = git(
            ["rev-list", "--left-right", "--count", f"{record['base_sha']}...{head}", "--"],
            cwd=repo,
        )
        base_only, source_only = map(int, counts.stdout.split())
        return {
            "head": head,
            "base_sha": record["base_sha"],
            "base_only_commits": base_only,
            "source_only_commits": source_only,
            "head_differs_from_base": head != record["base_sha"],
            "has_uncommitted_changes": bool(source_status(repo)),
        }

    def deliver(self, goal_id: str, data: Any, key: str) -> dict[str, Any]:
        from harness_bridge.service import _fault_point

        check_key(key)
        request = parse_contract(DeliveryRequest, data).model_dump(mode="json")
        digest = sha256_digest(request)
        with self.store.transaction() as cur:
            goal = self.b.coordination.guard_goal(
                cur, goal_id, self.b.advisor_claim, allow_delivery=True
            )
            prior = cur.execute(
                "SELECT delivery_id,request_digest FROM deliveries "
                "WHERE goal_id=? AND idempotency_key=?",
                (goal_id, key),
            ).fetchone()
            if prior:
                if prior["request_digest"] != digest:
                    raise BridgeError(
                        "IDEMPOTENCY_CONFLICT", "delivery key already binds another request"
                    )
                record = self.get(cur, prior["delivery_id"])
                replayed = True
            else:
                if self.active(cur, goal_id):
                    raise BridgeError(
                        "STATE_CONFLICT", "goal already has an active delivery intent or receipt"
                    )
                integration, summary = self.approved(cur, goal, request["integration_id"])
                ident = new_id("delivery")
                proof_ref = f"refs/hbridge/deliveries/{ident}"
                self.vacant(goal["repo_path"], request["branch"], proof_ref)
                if cur.execute(
                    "SELECT 1 FROM deliveries WHERE project_id=? AND branch=? "
                    "AND status<>'aborted'",
                    (goal["project_id"], request["branch"]),
                ).fetchone():
                    raise BridgeError("DELIVERY_CONFLICT", "branch is reserved by another delivery")
                record = {
                    "delivery_id": ident,
                    "goal_id": goal_id,
                    "project_id": goal["project_id"],
                    "status": "prepared",
                    "request": request,
                    "branch": request["branch"],
                    "integration_id": integration["integration_id"],
                    "goal_digest": goal["request_digest"],
                    "base_sha": goal["base_sha"],
                    "repo_path": goal["repo_path"],
                    "repo_identity": goal["repo_identity"],
                    "commit_sha": integration["result"]["commit_sha"],
                    "tree_sha": integration["result"]["tree_sha"],
                    "proof_ref": proof_ref,
                    "review_id": summary["review"]["review_id"],
                    "review_digest": sha256_digest(summary["review"]),
                    "verification_run_id": summary["verification_run"]["run_id"],
                    "verification_digest": sha256_digest(summary["verification_run"]),
                    "snapshot_digest": summary["review"]["snapshot_digest"],
                    "advisor_binding_id": goal["binding_id"],
                    "advisor_epoch": goal["advisor_epoch"],
                    "prepared_at": utc_now(),
                    "delivered_at": None,
                    "aborted_at": None,
                }
                record["source_at_preparation"] = self.source_observation(record)
                cur.execute(
                    "INSERT INTO deliveries VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        ident,
                        goal_id,
                        goal["project_id"],
                        key,
                        digest,
                        request["branch"],
                        "prepared",
                        canonical_json(record),
                        sha256_digest(record),
                        record["prepared_at"],
                    ),
                )
                self.b.coordination.event(
                    cur, goal_id, goal["advisor_epoch"], "delivery_prepared", record
                )
                replayed = False
        if record["status"] == "prepared":
            _fault_point("after_delivery_reserved")
            record = self.publish(record["delivery_id"])
        return {**self.status(record["delivery_id"]), "replayed": replayed}

    def historical_binding(self, cur: sqlite3.Cursor, record: dict[str, Any]) -> None:
        goal = self.b.coordination._goal(cur, record["goal_id"])
        if any(
            goal[k] != record[v]
            for k, v in (
                ("repo_path", "repo_path"),
                ("repo_identity", "repo_identity"),
                ("base_sha", "base_sha"),
                ("request_digest", "goal_digest"),
            )
        ):
            raise BridgeError("INTEGRITY_ERROR", "delivery no longer binds its recorded goal")
        for query, key, digest in (
            ("SELECT * FROM integration_reviews WHERE review_id=?", "review_id", "review_digest"),
            (
                "SELECT * FROM integration_verifications WHERE run_id=?",
                "verification_run_id",
                "verification_digest",
            ),
        ):
            evidence = read_record(cur.execute(query, (record[key],)).fetchone())
            if evidence is None or sha256_digest(evidence) != record[digest]:
                raise BridgeError(
                    "INTEGRITY_ERROR", "recorded delivery approval/check binding changed"
                )
        tree = (
            git(
                ["rev-parse", "--verify", f"{record['commit_sha']}^{{tree}}"],
                cwd=record["repo_path"],
            )
            .stdout.decode()
            .strip()
        )
        if tree != record["tree_sha"]:
            raise BridgeError("INTEGRITY_ERROR", "delivery commit tree differs from approved tree")

    def publish(self, delivery_id: str) -> dict[str, Any]:
        from harness_bridge.service import _fault_point

        with self.store.transaction() as cur:
            record = self.get(cur, delivery_id)
            goal = self.b.coordination.guard_goal(
                cur, record["goal_id"], self.b.advisor_claim, allow_delivery=True
            )
            if record["status"] != "prepared":
                return record
            observed = self.observations(record)
            self.historical_binding(cur, record)
            recovered = observed["ref_status"] == "matching"
            if not recovered:
                if observed["ref_status"] != "absent":
                    raise BridgeError(
                        "DELIVERY_CONFLICT",
                        "delivery refs changed; refusing overwrite",
                        details=observed,
                    )
                integration, summary = self.approved(cur, goal, record["integration_id"])
                if (
                    sha256_digest(summary["review"]) != record["review_digest"]
                    or sha256_digest(summary["verification_run"]) != record["verification_digest"]
                    or integration["result"]["commit_sha"] != record["commit_sha"]
                ):
                    raise BridgeError(
                        "STALE_REVIEW", "prepared delivery no longer matches current approval"
                    )
                self.vacant(record["repo_path"], record["branch"], record["proof_ref"])
                _fault_point("before_delivery_refs_created")
                # Both refs are create-only with no dereference, committed by one Git
                # ref transaction. An external creation race must fail, never overwrite.
                commands = (
                    "start\noption no-deref\n"
                    f"create refs/heads/{record['branch']} {record['commit_sha']}\n"
                    f"create {record['proof_ref']} {record['commit_sha']}\nprepare\ncommit\n"
                )
                git(
                    ["update-ref", "--stdin"],
                    cwd=record["repo_path"],
                    input_bytes=commands.encode(),
                )
                _fault_point("after_delivery_refs_created")
            if self.observations(record)["ref_status"] != "matching":
                raise BridgeError("DELIVERY_CONFLICT", "could not confirm exact delivered ref pair")
            record.update(
                status="delivered", delivered_at=utc_now(), recovered_publication=recovered
            )
            self.save(cur, record)
            self.b.coordination.event(
                cur, record["goal_id"], goal["advisor_epoch"], "goal_delivered", record
            )
            return record

    def abort(self, delivery_id: str, reason: str) -> dict[str, Any]:
        if not reason.strip() or len(reason) > 2000:
            raise BridgeError("INVALID_INPUT", "abort requires a short reason")
        with self.store.transaction() as cur:
            record = self.get(cur, delivery_id)
            goal = self.b.coordination.guard_goal(
                cur,
                record["goal_id"],
                self.b.advisor_claim,
                allow_stopping=True,
                allow_delivery=True,
            )
            if record["status"] == "aborted":
                if record["abort_reason"] != reason:
                    raise BridgeError(
                        "IDEMPOTENCY_CONFLICT", "abort already recorded with another reason"
                    )
                return {**record, "replayed": True}
            if record["status"] != "prepared":
                raise BridgeError("STATE_CONFLICT", "completed deliveries cannot be aborted")
            self.identity(record)
            if record["proof_ref"] in self.refs(record["repo_path"]) or self.symbolic(
                record["repo_path"], record["proof_ref"]
            ):
                raise BridgeError(
                    "DELIVERY_CONFLICT", "publication proof exists; inspect or complete delivery"
                )
            record.update(status="aborted", aborted_at=utc_now(), abort_reason=reason)
            self.save(cur, record)
            self.b.coordination.event(
                cur, record["goal_id"], goal["advisor_epoch"], "delivery_aborted", record
            )
            return {**record, "replayed": False}

    def status(self, delivery_id: str) -> dict[str, Any]:
        with self.store.transaction() as cur:
            record = self.get(cur, delivery_id)
            return {**record, "observed": self.inspect(cur, record)}

    def inspect(self, cur: sqlite3.Cursor, record: dict[str, Any]) -> dict[str, Any]:
        observed = self.observations(record)
        try:
            self.historical_binding(cur, record)
        except BridgeError as exc:
            observed.update(
                ref_status="unavailable", error={"code": exc.code, "message": exc.message}
            )
        return observed

    def goal_view(self, cur: sqlite3.Cursor, goal: sqlite3.Row) -> dict[str, Any]:
        record = self.active(cur, goal["goal_id"])
        if record:
            observed = self.inspect(cur, record)
            status = (
                "pending"
                if record["status"] == "prepared"
                else ("delivered" if observed["ref_status"] == "matching" else "changed")
            )
            return {
                "status": status,
                "receipt": record,
                "observed": observed,
                "integration_id": record["integration_id"],
                "blockers": [],
            }
        ident = self.latest_integration(cur, goal["goal_id"])
        view: dict[str, Any] = {
            "status": "not_ready",
            "receipt": None,
            "integration_id": ident,
            "blockers": [],
        }
        if ident is None:
            return view
        try:
            self.approved(cur, goal, ident)
            view["status"] = "ready"
        except BridgeError as exc:
            view["blockers"] = [{"code": exc.code, "message": exc.message, "details": exc.details}]
        return view
