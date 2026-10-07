"""Workbench SQLite store: projects, sessions, runs, events and handoffs.

Separate from the task/goal database (``bridge.sqlite3``); nothing is migrated or rewritten.
Single-writer admission for a real working directory happens inside one ``BEGIN IMMEDIATE``
transaction, so two App instances on the same state directory cannot both start a writer.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_REVISION = 1
ACTIVE = ("starting", "running")
ENDED = ("exited", "failed", "stopped", "interrupted")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    harness TEXT NOT NULL CHECK (harness IN ('claude-code', 'codex')),
    title TEXT NOT NULL,
    workdir TEXT NOT NULL,
    native_session_id TEXT,
    native_binding TEXT NOT NULL,
    handoff_from TEXT REFERENCES sessions(session_id),
    turns_observed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
);
CREATE INDEX IF NOT EXISTS sessions_by_project ON sessions(project_id, created_at);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('new', 'resume')),
    workdir TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('starting', 'running', 'exited', 'failed', 'stopped', 'interrupted')
    ),
    argv_json TEXT NOT NULL,
    stripped_env_json TEXT NOT NULL,
    pid INTEGER,
    pgid INTEGER,
    birth TEXT,
    exit_code INTEGER,
    exit_signal INTEGER,
    exit_confirmed INTEGER,
    stop_requested INTEGER NOT NULL DEFAULT 0,
    failure TEXT,
    output_tail TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS runs_by_workdir ON runs(workdir, status);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    run_id TEXT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_session ON events(session_id, seq);
CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    from_session_id TEXT NOT NULL REFERENCES sessions(session_id),
    to_session_id TEXT NOT NULL UNIQUE REFERENCES sessions(session_id),
    note_path TEXT NOT NULL,
    note_digest TEXT NOT NULL,
    send_as_prompt INTEGER NOT NULL CHECK (send_as_prompt IN (0, 1)),
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class WorkdirBusy(Exception):
    def __init__(self, workdir: str, session_id: str, title: str) -> None:
        super().__init__(workdir)
        self.workdir = workdir
        self.session_id = session_id
        self.title = title


class WorkbenchStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.executescript(_SCHEMA)
        row = self._db.execute("SELECT value FROM meta WHERE key='schema_revision'").fetchone()
        if row is None:
            self._db.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_revision', ?)",
                (str(SCHEMA_REVISION),),
            )
        elif int(row["value"]) != SCHEMA_REVISION:
            raise RuntimeError(
                f"workbench schema revision {row['value']} is not supported "
                f"(expected {SCHEMA_REVISION})"
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def _rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def _row(self, sql: str, args: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, args)
        return rows[0] if rows else None

    # --- projects -------------------------------------------------------------------------------

    def add_project(self, name: str, root_path: str) -> tuple[dict[str, Any], bool]:
        with self.tx() as db:
            row = db.execute("SELECT * FROM projects WHERE root_path=?", (root_path,)).fetchone()
            if row is not None:
                if row["archived"]:
                    db.execute(
                        "UPDATE projects SET archived=0 WHERE project_id=?", (row["project_id"],)
                    )
                return {**dict(row), "archived": 0}, False
            project = {
                "project_id": "prj_" + uuid.uuid4().hex[:12],
                "name": name,
                "root_path": root_path,
                "created_at": now(),
                "archived": 0,
            }
            db.execute(
                "INSERT INTO projects(project_id, name, root_path, created_at, archived) "
                "VALUES (:project_id, :name, :root_path, :created_at, :archived)",
                project,
            )
            return project, True

    def archive_project(self, project_id: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE projects SET archived=1 WHERE project_id=?", (project_id,))

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM projects WHERE project_id=?", (project_id,))

    def list_projects(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM projects WHERE archived=0 ORDER BY created_at")

    # --- sessions -------------------------------------------------------------------------------

    def create_session(
        self,
        *,
        project_id: str,
        harness: str,
        title: str,
        workdir: str,
        native_session_id: str | None,
        native_binding: str,
        handoff_from: str | None = None,
    ) -> dict[str, Any]:
        stamp = now()
        session = {
            "session_id": "ses_" + uuid.uuid4().hex[:12],
            "project_id": project_id,
            "harness": harness,
            "title": title,
            "workdir": workdir,
            "native_session_id": native_session_id,
            "native_binding": native_binding,
            "handoff_from": handoff_from,
            "turns_observed": 0,
            "created_at": stamp,
            "updated_at": stamp,
            "archived": 0,
        }
        with self.tx() as db:
            db.execute(
                "INSERT INTO sessions(session_id, project_id, harness, title, workdir, "
                "native_session_id, native_binding, handoff_from, created_at, updated_at, "
                "archived) VALUES (:session_id, :project_id, :harness, :title, :workdir, "
                ":native_session_id, :native_binding, :handoff_from, :created_at, :updated_at, "
                ":archived)",
                session,
            )
        return session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM sessions WHERE session_id=?", (session_id,))

    def list_sessions(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id is None:
            return self._rows("SELECT * FROM sessions WHERE archived=0 ORDER BY created_at")
        return self._rows(
            "SELECT * FROM sessions WHERE archived=0 AND project_id=? ORDER BY created_at",
            (project_id,),
        )

    def set_native(self, session_id: str, native_session_id: str | None, binding: str) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE sessions SET native_session_id=?, native_binding=?, updated_at=? "
                "WHERE session_id=?",
                (native_session_id, binding, now(), session_id),
            )

    def count_turn(self, session_id: str) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE sessions SET turns_observed=turns_observed+1, updated_at=? "
                "WHERE session_id=?",
                (now(), session_id),
            )

    def rename_session(self, session_id: str, title: str) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE sessions SET title=?, updated_at=? WHERE session_id=?",
                (title, now(), session_id),
            )

    def archive_session(self, session_id: str) -> None:
        with self.tx() as db:
            active = db.execute(
                "SELECT 1 FROM runs WHERE session_id=? AND status IN ('starting','running')",
                (session_id,),
            ).fetchone()
            if active is not None:
                raise ValueError("an active session cannot be archived; stop it first")
            db.execute(
                "UPDATE sessions SET archived=1, updated_at=? WHERE session_id=?",
                (now(), session_id),
            )

    # --- runs -----------------------------------------------------------------------------------

    def begin_run(
        self,
        *,
        run_id: str,
        session_id: str,
        kind: str,
        workdir: str,
        argv: list[str],
        stripped_env: list[str],
    ) -> dict[str, Any]:
        """Admit a writer for ``workdir`` or raise WorkdirBusy, atomically."""
        with self.tx() as db:
            busy = db.execute(
                "SELECT r.session_id, s.title FROM runs r JOIN sessions s USING (session_id) "
                "WHERE r.workdir=? AND r.status IN ('starting','running') LIMIT 1",
                (workdir,),
            ).fetchone()
            if busy is not None:
                raise WorkdirBusy(workdir, busy["session_id"], busy["title"])
            seq = db.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM runs WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            run = {
                "run_id": run_id,
                "session_id": session_id,
                "seq": seq,
                "kind": kind,
                "workdir": workdir,
                "status": "starting",
                "argv_json": json.dumps(argv, ensure_ascii=False),
                "stripped_env_json": json.dumps(stripped_env),
                "started_at": now(),
            }
            db.execute(
                "INSERT INTO runs(run_id, session_id, seq, kind, workdir, status, argv_json, "
                "stripped_env_json, started_at) VALUES (:run_id, :session_id, :seq, :kind, "
                ":workdir, :status, :argv_json, :stripped_env_json, :started_at)",
                run,
            )
            db.execute(
                "UPDATE sessions SET updated_at=? WHERE session_id=?",
                (run["started_at"], session_id),
            )
        return self.get_run(run["run_id"])  # type: ignore[return-value]

    def mark_running(self, run_id: str, *, pid: int, pgid: int, birth: str | None) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE runs SET status='running', pid=?, pgid=?, birth=? "
                "WHERE run_id=? AND status='starting'",
                (pid, pgid, birth, run_id),
            )

    def note_failure(self, run_id: str, failure: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE runs SET failure=? WHERE run_id=?", (failure, run_id))

    def mark_stop_requested(self, run_id: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE runs SET stop_requested=1 WHERE run_id=?", (run_id,))

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        exit_code: int | None = None,
        exit_signal: int | None = None,
        exit_confirmed: bool | None = None,
        failure: str | None = None,
        output_tail: str | None = None,
    ) -> None:
        if status not in ENDED:
            raise ValueError(status)
        with self.tx() as db:
            db.execute(
                "UPDATE runs SET status=?, exit_code=?, exit_signal=?, exit_confirmed=?, "
                "failure=?, output_tail=?, ended_at=? WHERE run_id=? "
                "AND status IN ('starting','running')",
                (
                    status,
                    exit_code,
                    exit_signal,
                    None if exit_confirmed is None else int(exit_confirmed),
                    failure,
                    output_tail,
                    now(),
                    run_id,
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM runs WHERE run_id=?", (run_id,))

    def list_runs(self, session_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM runs WHERE session_id=? ORDER BY seq", (session_id,))

    def latest_runs(self) -> dict[str, dict[str, Any]]:
        rows = self._rows(
            "SELECT r.* FROM runs r JOIN (SELECT session_id, MAX(seq) AS seq FROM runs "
            "GROUP BY session_id) m ON r.session_id=m.session_id AND r.seq=m.seq"
        )
        return {r["session_id"]: r for r in rows}

    def active_runs(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM runs WHERE status IN ('starting','running')")

    # --- events ---------------------------------------------------------------------------------

    def add_event(
        self, session_id: str, run_id: str | None, kind: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        stamp = now()
        text = json.dumps(payload, ensure_ascii=False)
        with self.tx() as db:
            cur = db.execute(
                "INSERT INTO events(session_id, run_id, kind, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, run_id, kind, text, stamp),
            )
            seq = cur.lastrowid
        return {
            "seq": seq,
            "session_id": session_id,
            "run_id": run_id,
            "kind": kind,
            "payload": payload,
            "created_at": stamp,
        }

    def list_events(
        self, session_id: str, *, after: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT * FROM (SELECT * FROM events WHERE session_id=? AND seq>? "
            "ORDER BY seq DESC LIMIT ?) ORDER BY seq",
            (session_id, after, limit),
        )
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return rows

    # --- handoffs -------------------------------------------------------------------------------

    def add_handoff(
        self,
        *,
        project_id: str,
        from_session_id: str,
        to_session_id: str,
        note_path: str,
        note_digest: str,
        send_as_prompt: bool,
    ) -> dict[str, Any]:
        handoff = {
            "handoff_id": "hof_" + uuid.uuid4().hex[:12],
            "project_id": project_id,
            "from_session_id": from_session_id,
            "to_session_id": to_session_id,
            "note_path": note_path,
            "note_digest": note_digest,
            "send_as_prompt": int(send_as_prompt),
            "created_at": now(),
        }
        with self.tx() as db:
            db.execute(
                "INSERT INTO handoffs(handoff_id, project_id, from_session_id, to_session_id, "
                "note_path, note_digest, send_as_prompt, created_at) VALUES (:handoff_id, "
                ":project_id, :from_session_id, :to_session_id, :note_path, :note_digest, "
                ":send_as_prompt, :created_at)",
                handoff,
            )
        return handoff

    def list_handoffs(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id is None:
            return self._rows("SELECT * FROM handoffs ORDER BY created_at")
        return self._rows(
            "SELECT * FROM handoffs WHERE project_id=? ORDER BY created_at", (project_id,)
        )
