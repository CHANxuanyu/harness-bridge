"""Schema upgrade snapshots include committed WAL data and failures leave v1 usable."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.migrations import COORDINATION_SCHEMA
from harness_bridge.store import _SCHEMA, Store


def legacy(path: Path, revision: str = "1") -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO meta VALUES ('schema_revision', ?)", (revision,))
    conn.execute(
        "INSERT INTO events(event_id,task_id,type,payload,created_at) "
        "VALUES ('historic-event','historic-task','task_created','{}','2026-01-01')"
    )
    return conn


def test_upgrade_snapshot_contains_wal_and_reopen_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    old = legacy(path)
    assert Path(str(path) + "-wal").stat().st_size > 0
    upgraded = Store(path)
    assert len(upgraded.list_events("historic-task")) == 1
    with upgraded.transaction() as cur:
        assert cur.execute("SELECT count(*) FROM goal_tasks").fetchone()[0] == 0
    upgraded.close()
    backups = list((tmp_path / "backups").glob("*.sqlite3"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    backup = sqlite3.connect(backups[0])
    assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert backup.execute("SELECT value FROM meta").fetchone()[0] == "1"
    assert backup.execute("SELECT event_id FROM events").fetchone()[0] == "historic-event"
    assert backup.execute("SELECT name FROM sqlite_master WHERE name='goals'").fetchone() is None
    backup.close()
    again = Store(path)
    again.close()
    assert list((tmp_path / "backups").glob("*.sqlite3")) == backups
    old.close()


def test_interrupted_migration_rolls_back_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.sqlite3"
    old = legacy(path)
    original = Store._apply_schema

    def fail(cur: sqlite3.Cursor, schema: str) -> None:
        if schema == COORDINATION_SCHEMA:
            cur.execute("CREATE TABLE partial_change (id TEXT)")
            raise RuntimeError("injected migration interruption")
        original(cur, schema)

    monkeypatch.setattr(Store, "_apply_schema", staticmethod(fail))
    with pytest.raises(RuntimeError, match="interruption"):
        Store(path)
    assert old.execute("SELECT value FROM meta").fetchone()[0] == "1"
    assert (
        old.execute("SELECT name FROM sqlite_master WHERE name='partial_change'").fetchone() is None
    )
    assert old.execute("SELECT event_id FROM events").fetchone()[0] == "historic-event"
    monkeypatch.setattr(Store, "_apply_schema", staticmethod(original))
    Store(path).close()
    assert old.execute("SELECT value FROM meta").fetchone()[0] == "2"
    old.close()


def test_unknown_revision_is_not_modified(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    old = legacy(path, "99")
    before = list(old.iterdump())
    with pytest.raises(BridgeError) as err:
        Store(path)
    assert err.value.code == "INTEGRITY_ERROR"
    assert list(old.iterdump()) == before
    assert not (tmp_path / "backups").exists()
    old.close()


def test_concurrent_upgrade_creates_one_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    old = legacy(path)
    barrier = Barrier(2)

    def open_store(_: int) -> None:
        barrier.wait(timeout=10)
        Store(path).close()

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(open_store, [1, 2]))
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1
    assert old.execute("SELECT value FROM meta").fetchone()[0] == "2"
    old.close()


def test_backup_failure_aborts_upgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "state.sqlite3"
    old = legacy(path)
    (tmp_path / "backups").write_text("not a directory")
    with pytest.raises(FileExistsError):
        Store(path)
    assert old.execute("SELECT value FROM meta").fetchone()[0] == "1"
    assert old.execute("SELECT name FROM sqlite_master WHERE name='goals'").fetchone() is None
    old.close()
