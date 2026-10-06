from __future__ import annotations

from pathlib import Path

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.state import TERMINAL, TRANSITIONS, TaskState, check_transition
from harness_bridge.store import Store

S = TaskState


def test_terminal_states_have_no_exits() -> None:
    for state in TERMINAL:
        assert TRANSITIONS[state] == frozenset()


def test_success_only_from_awaiting_review() -> None:
    sources = [s for s, targets in TRANSITIONS.items() if S.SUCCEEDED in targets]
    assert sources == [S.AWAITING_REVIEW]


def test_run_only_from_ready() -> None:
    sources = [s for s, targets in TRANSITIONS.items() if S.STARTING in targets]
    assert sources == [S.READY]


def test_illegal_transition_raises() -> None:
    with pytest.raises(BridgeError) as exc:
        check_transition(S.RUNNING, S.SUCCEEDED)
    assert exc.value.code == "STATE_CONFLICT"


def _task(store: Store, task_id: str = "t1") -> None:
    with store.transaction() as cur:
        store.insert_task(
            cur,
            {
                "task_id": task_id,
                "idempotency_key": f"k-{task_id}",
                "request_digest": "d",
                "spec_json": "{}",
                "spec_digest": "s",
                "verifier_digest": "v",
                "repo_path": "/r",
                "repo_identity": "/r/.git",
                "base_ref": "HEAD",
                "base_sha": "0" * 40,
            },
        )


def test_cas_transition_and_event_atomicity(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite3")
    _task(store)
    with store.transaction() as cur:
        store.transition(cur, "t1", S.CREATED, S.READY, reason="ok")
    # A second writer that still believes the task is CREATED must lose.
    with pytest.raises(BridgeError) as exc, store.transaction() as cur:
        store.transition(cur, "t1", S.CREATED, S.READY, reason="again")
    assert exc.value.code == "STATE_CONFLICT"
    # Failed transaction rolled back: exactly one state_changed event.
    events = [e for e in store.list_events("t1") if e["type"] == "state_changed"]
    assert len(events) == 1
    assert store.get_task("t1").revision == 1


def test_rolled_back_transaction_leaves_no_event(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite3")
    _task(store)
    with pytest.raises(RuntimeError), store.transaction() as cur:
        store.transition(cur, "t1", S.CREATED, S.READY)
        raise RuntimeError("crash before commit")
    assert store.get_task("t1").state == S.CREATED
    assert [e["type"] for e in store.list_events("t1")] == []


def test_event_dedupe_key_prevents_replay(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite3")
    _task(store)
    with store.transaction() as cur:
        assert store.add_event(cur, "t1", "x", dedupe_key="once") is True
        assert store.add_event(cur, "t1", "x", dedupe_key="once") is False
    assert len(store.list_events("t1")) == 1


def test_reopen_reads_same_state(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    store = Store(db)
    _task(store)
    with store.transaction() as cur:
        store.transition(cur, "t1", S.CREATED, S.READY)
    store.close()
    again = Store(db)
    assert again.get_task("t1").state == S.READY
    assert again.list_events("t1")[-1]["to_state"] == "READY"


def test_unknown_task_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(BridgeError) as exc:
        Store(tmp_path / "db.sqlite3").get_task("missing")
    assert exc.value.code == "NOT_FOUND"
