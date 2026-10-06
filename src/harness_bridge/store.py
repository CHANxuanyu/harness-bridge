"""SQLite store: the single authoritative source of task state and events.

State changes use compare-and-swap (``WHERE state = ?``) inside ``BEGIN IMMEDIATE`` transactions,
and the matching event row is written in the same transaction. JSON files under the artifacts
directory are content/export views only; they never compete with this database for state.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness_bridge.errors import BridgeError
from harness_bridge.migrations import MIGRATIONS
from harness_bridge.state import TaskState, check_transition

SCHEMA_REVISION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    spec_digest TEXT NOT NULL,
    verifier_digest TEXT NOT NULL,
    task_version INTEGER NOT NULL DEFAULT 1,
    repo_path TEXT NOT NULL,
    repo_identity TEXT NOT NULL,
    base_ref TEXT NOT NULL,
    base_sha TEXT NOT NULL,
    worktree_path TEXT,
    task_branch TEXT,
    state TEXT NOT NULL,
    state_reason TEXT,
    state_details TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    current_attempt_id TEXT,
    attempts_used INTEGER NOT NULL DEFAULT 0,
    repair_cycles_used INTEGER NOT NULL DEFAULT 0,
    pending_feedback TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    executor_kind TEXT NOT NULL,
    mode TEXT NOT NULL,
    requested_model TEXT,
    observed_model TEXT,
    invocation_digest TEXT NOT NULL,
    invocation_json TEXT NOT NULL,
    feedback_json TEXT,
    launch_token TEXT NOT NULL UNIQUE,
    runner_json TEXT,
    pid INTEGER,
    pgid INTEGER,
    status TEXT NOT NULL,
    outcome TEXT,
    outcome_reason TEXT,
    exit_code INTEGER,
    exit_signal INTEGER,
    exit_confirmed INTEGER,
    session_id TEXT,
    session_binding TEXT,
    executor_reported TEXT,
    process_json TEXT,
    usage_json TEXT,
    evidence_level TEXT,
    fingerprint TEXT,
    manifest_path TEXT,
    manifest_digest TEXT,
    verification_run_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    UNIQUE (task_id, seq)
);

CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    dedupe_key TEXT UNIQUE,
    task_id TEXT NOT NULL,
    attempt_id TEXT,
    type TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_task ON events(task_id, seq);

CREATE TABLE IF NOT EXISTS verification_runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    fingerprint_before TEXT NOT NULL,
    fingerprint_after TEXT,
    verifier_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    results_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    status TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (task_id, idempotency_key)
);
"""


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def _loads(value: str | None) -> Any:
    return None if value is None else json.loads(value)


def _dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    idempotency_key: str
    request_digest: str
    spec_json: str
    spec_digest: str
    verifier_digest: str
    task_version: int
    repo_path: str
    repo_identity: str
    base_ref: str
    base_sha: str
    worktree_path: str | None
    task_branch: str | None
    state: TaskState
    state_reason: str | None
    state_details: dict[str, Any] | None
    revision: int
    current_attempt_id: str | None
    attempts_used: int
    repair_cycles_used: int
    pending_feedback: list[dict[str, Any]] | None
    cancel_requested: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TaskRecord:
        return cls(
            task_id=row["task_id"],
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
            spec_json=row["spec_json"],
            spec_digest=row["spec_digest"],
            verifier_digest=row["verifier_digest"],
            task_version=row["task_version"],
            repo_path=row["repo_path"],
            repo_identity=row["repo_identity"],
            base_ref=row["base_ref"],
            base_sha=row["base_sha"],
            worktree_path=row["worktree_path"],
            task_branch=row["task_branch"],
            state=TaskState(row["state"]),
            state_reason=row["state_reason"],
            state_details=_loads(row["state_details"]),
            revision=row["revision"],
            current_attempt_id=row["current_attempt_id"],
            attempts_used=row["attempts_used"],
            repair_cycles_used=row["repair_cycles_used"],
            pending_feedback=_loads(row["pending_feedback"]),
            cancel_requested=bool(row["cancel_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: str
    task_id: str
    seq: int
    kind: str
    executor_kind: str
    mode: str
    requested_model: str | None
    observed_model: str | None
    invocation_digest: str
    invocation: dict[str, Any]
    feedback: list[dict[str, Any]] | None
    launch_token: str
    runner: dict[str, Any] | None
    pid: int | None
    pgid: int | None
    status: str
    outcome: str | None
    outcome_reason: str | None
    exit_code: int | None
    exit_signal: int | None
    exit_confirmed: bool | None
    session_id: str | None
    session_binding: dict[str, Any] | None
    executor_reported: dict[str, Any] | None
    process: dict[str, Any] | None
    usage: dict[str, Any] | None
    evidence_level: str | None
    fingerprint: str | None
    manifest_path: str | None
    manifest_digest: str | None
    verification_run_id: str | None
    started_at: str
    ended_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> AttemptRecord:
        ec = row["exit_confirmed"]
        return cls(
            attempt_id=row["attempt_id"],
            task_id=row["task_id"],
            seq=row["seq"],
            kind=row["kind"],
            executor_kind=row["executor_kind"],
            mode=row["mode"],
            requested_model=row["requested_model"],
            observed_model=row["observed_model"],
            invocation_digest=row["invocation_digest"],
            invocation=_loads(row["invocation_json"]),
            feedback=_loads(row["feedback_json"]),
            launch_token=row["launch_token"],
            runner=_loads(row["runner_json"]),
            pid=row["pid"],
            pgid=row["pgid"],
            status=row["status"],
            outcome=row["outcome"],
            outcome_reason=row["outcome_reason"],
            exit_code=row["exit_code"],
            exit_signal=row["exit_signal"],
            exit_confirmed=None if ec is None else bool(ec),
            session_id=row["session_id"],
            session_binding=_loads(row["session_binding"]),
            executor_reported=_loads(row["executor_reported"]),
            process=_loads(row["process_json"]),
            usage=_loads(row["usage_json"]),
            evidence_level=row["evidence_level"],
            fingerprint=row["fingerprint"],
            manifest_path=row["manifest_path"],
            manifest_digest=row["manifest_digest"],
            verification_run_id=row["verification_run_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
        )


_JSON_ATTEMPT_FIELDS = {
    "invocation": "invocation_json",
    "feedback": "feedback_json",
    "runner": "runner_json",
    "session_binding": "session_binding",
    "executor_reported": "executor_reported",
    "process": "process_json",
    "usage": "usage_json",
}
_JSON_TASK_FIELDS = {"state_details", "pending_feedback"}


class Store:
    def __init__(self, db_path: Path, *, clock: Callable[[], str] = utc_now) -> None:
        self.db_path = db_path
        self.clock = clock
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path), timeout=30.0, isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout = 30000")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = FULL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        try:
            self._initialize_schema()
        except BaseException:
            self._conn.close()
            raise

    def _initialize_schema(self) -> None:
        # Do not use executescript here: it commits before executing its statements.
        with self.transaction() as cur:
            tables = {
                r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not tables:
                self._apply_schema(cur, _SCHEMA)
                for schema in MIGRATIONS.values():
                    self._apply_schema(cur, schema)
                cur.execute(
                    "INSERT INTO meta(key, value) VALUES ('schema_revision', ?)",
                    (str(SCHEMA_REVISION),),
                )
                return
            row = (
                cur.execute("SELECT value FROM meta WHERE key='schema_revision'").fetchone()
                if "meta" in tables
                else None
            )
            revision = row["value"] if row else "unknown"
            if revision not in {str(n) for n in range(1, SCHEMA_REVISION + 1)}:
                raise BridgeError(
                    "INTEGRITY_ERROR",
                    f"state database schema revision {revision} is not supported "
                    f"(expected {SCHEMA_REVISION})",
                )
            if int(revision) < SCHEMA_REVISION:
                # Separate read connection can snapshot committed WAL data while this
                # connection holds the migration writer lock; no other writer can race us.
                backup_dir = self.db_path.parent / "backups"
                backup_dir.mkdir(mode=0o700, exist_ok=True)
                backup_path = backup_dir / f"pre-v{SCHEMA_REVISION}-{uuid.uuid4().hex}.sqlite3"
                backup_path.touch(mode=0o600, exist_ok=False)
                source = sqlite3.connect(str(self.db_path))
                try:
                    destination = sqlite3.connect(str(backup_path))
                    try:
                        source.backup(destination)
                    finally:
                        destination.close()
                finally:
                    source.close()
                backup_path.chmod(0o600)
                for target in range(int(revision) + 1, SCHEMA_REVISION + 1):
                    self._apply_schema(cur, MIGRATIONS[target])
                cur.execute(
                    "UPDATE meta SET value=? WHERE key='schema_revision'", (str(SCHEMA_REVISION),)
                )

    @staticmethod
    def _apply_schema(cur: sqlite3.Cursor, schema: str) -> None:
        for statement in schema.split(";"):
            if statement.strip():
                cur.execute(statement)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            yield cur
        except BaseException:
            cur.execute("ROLLBACK")
            raise
        else:
            cur.execute("COMMIT")
        finally:
            cur.close()

    # --- events ---------------------------------------------------------------------------

    def add_event(
        self,
        cur: sqlite3.Cursor,
        task_id: str,
        type_: str,
        payload: dict[str, Any] | None = None,
        *,
        attempt_id: str | None = None,
        from_state: str | None = None,
        to_state: str | None = None,
        dedupe_key: str | None = None,
    ) -> bool:
        """Insert an event. Returns False if ``dedupe_key`` was already recorded (replay)."""
        cur.execute(
            "INSERT OR IGNORE INTO events(event_id, dedupe_key, task_id, attempt_id, type, "
            "from_state, to_state, payload, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                new_id("evt"),
                dedupe_key,
                task_id,
                attempt_id,
                type_,
                from_state,
                to_state,
                json.dumps(payload or {}, sort_keys=True, ensure_ascii=False),
                self.clock(),
            ),
        )
        return cur.rowcount == 1

    def list_events(self, task_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM (SELECT * FROM events WHERE task_id=? ORDER BY seq DESC LIMIT ?) "
            "ORDER BY seq ASC",
            (task_id, limit),
        ).fetchall()
        return [
            {
                "seq": r["seq"],
                "event_id": r["event_id"],
                "type": r["type"],
                "attempt_id": r["attempt_id"],
                "from_state": r["from_state"],
                "to_state": r["to_state"],
                "payload": json.loads(r["payload"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # --- tasks ----------------------------------------------------------------------------

    def insert_task(self, cur: sqlite3.Cursor, values: dict[str, Any]) -> None:
        now = self.clock()
        row = dict(values)
        row.setdefault("state", TaskState.CREATED.value)
        row["created_at"] = now
        row["updated_at"] = now
        for key in _JSON_TASK_FIELDS & row.keys():
            row[key] = _dumps(row[key])
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur.execute(f"INSERT INTO tasks({cols}) VALUES ({marks})", tuple(row.values()))  # noqa: S608

    def get_task(self, task_id: str, cur: sqlite3.Cursor | None = None) -> TaskRecord:
        c = cur or self._conn
        row = c.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise BridgeError("NOT_FOUND", f"task {task_id!r} not found", task_id=task_id)
        return TaskRecord.from_row(row)

    def find_task_by_key(self, key: str) -> TaskRecord | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE idempotency_key=?", (key,)).fetchone()
        return None if row is None else TaskRecord.from_row(row)

    def list_tasks(self, limit: int = 50) -> list[TaskRecord]:
        rows = self._conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [TaskRecord.from_row(r) for r in rows]

    def update_task(self, cur: sqlite3.Cursor, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets = []
        vals: list[Any] = []
        for key, value in fields.items():
            sets.append(f"{key}=?")
            vals.append(_dumps(value) if key in _JSON_TASK_FIELDS else value)
        sets.append("updated_at=?")
        vals.append(self.clock())
        vals.append(task_id)
        cur.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE task_id=?", vals)  # noqa: S608

    def transition(
        self,
        cur: sqlite3.Cursor,
        task_id: str,
        expected: TaskState,
        new: TaskState,
        *,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
        event_type: str = "state_changed",
        payload: dict[str, Any] | None = None,
        attempt_id: str | None = None,
        dedupe_key: str | None = None,
        **fields: Any,
    ) -> None:
        """Compare-and-swap the task state and record the event in the same transaction."""
        check_transition(expected, new, task_id=task_id)
        sets = ["state=?", "state_reason=?", "state_details=?", "revision=revision+1"]
        vals: list[Any] = [new.value, reason, _dumps(details)]
        for key, value in fields.items():
            sets.append(f"{key}=?")
            vals.append(_dumps(value) if key in _JSON_TASK_FIELDS else value)
        sets.append("updated_at=?")
        vals.append(self.clock())
        vals.extend([task_id, expected.value])
        cur.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE task_id=? AND state=?",  # noqa: S608
            vals,
        )
        if cur.rowcount != 1:
            current = cur.execute("SELECT state FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            actual = current["state"] if current else "missing"
            raise BridgeError(
                "STATE_CONFLICT",
                f"task state is {actual}, expected {expected}",
                task_id=task_id,
                details={"actual_state": actual, "expected_state": expected.value},
            )
        body = dict(payload or {})
        if reason:
            body.setdefault("reason", reason)
        self.add_event(
            cur,
            task_id,
            event_type,
            body,
            attempt_id=attempt_id,
            from_state=expected.value,
            to_state=new.value,
            dedupe_key=dedupe_key,
        )

    # --- attempts -------------------------------------------------------------------------

    def insert_attempt(self, cur: sqlite3.Cursor, values: dict[str, Any]) -> None:
        row = dict(values)
        for key, col in _JSON_ATTEMPT_FIELDS.items():
            if key in row:
                row[col] = _dumps(row.pop(key))
        row.setdefault("started_at", self.clock())
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur.execute(f"INSERT INTO attempts({cols}) VALUES ({marks})", tuple(row.values()))  # noqa: S608

    def update_attempt(self, cur: sqlite3.Cursor, attempt_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets = []
        vals: list[Any] = []
        for key, value in fields.items():
            if key in _JSON_ATTEMPT_FIELDS:
                sets.append(f"{_JSON_ATTEMPT_FIELDS[key]}=?")
                vals.append(_dumps(value))
            else:
                sets.append(f"{key}=?")
                vals.append(value)
        vals.append(attempt_id)
        cur.execute(f"UPDATE attempts SET {', '.join(sets)} WHERE attempt_id=?", vals)  # noqa: S608

    def get_attempt(self, attempt_id: str, cur: sqlite3.Cursor | None = None) -> AttemptRecord:
        c = cur or self._conn
        row = c.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        if row is None:
            raise BridgeError("NOT_FOUND", f"attempt {attempt_id!r} not found")
        return AttemptRecord.from_row(row)

    def list_attempts(self, task_id: str) -> list[AttemptRecord]:
        rows = self._conn.execute(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY seq", (task_id,)
        ).fetchall()
        return [AttemptRecord.from_row(r) for r in rows]

    # --- verification runs ----------------------------------------------------------------

    def insert_verification_run(self, cur: sqlite3.Cursor, values: dict[str, Any]) -> None:
        row = dict(values)
        row["results_json"] = _dumps(row.pop("results"))
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur.execute(
            f"INSERT INTO verification_runs({cols}) VALUES ({marks})",  # noqa: S608
            tuple(row.values()),
        )

    def get_verification_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM verification_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["results"] = json.loads(out.pop("results_json"))
        return out

    # --- reviews --------------------------------------------------------------------------

    def find_review(self, task_id: str, key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM reviews WHERE task_id=? AND idempotency_key=?", (task_id, key)
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["receipt"] = json.loads(out.pop("receipt_json"))
        return out

    def insert_review(self, cur: sqlite3.Cursor, values: dict[str, Any]) -> None:
        row = dict(values)
        row["receipt_json"] = _dumps(row.pop("receipt"))
        row.setdefault("created_at", self.clock())
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur.execute(f"INSERT INTO reviews({cols}) VALUES ({marks})", tuple(row.values()))  # noqa: S608

    def list_reviews(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT review_id, attempt_id, verdict, status, idempotency_key, created_at "
            "FROM reviews WHERE task_id=? ORDER BY created_at",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]
