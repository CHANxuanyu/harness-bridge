"""Summary semantics: de-duplication, explicit denominators, unknown stays unknown, and message
identity keyed by (session, client message) for current (v2) and earlier (v1) records."""

from __future__ import annotations

import json
from pathlib import Path

from harness_bridge.observability import Observability, report

SID = "ses_000000000001"


def test_summary_dedupes_and_keeps_unknown_unknown(tmp_path: Path) -> None:
    obs = Observability(tmp_path, env_name="test", env={"HBRIDGE_PRODUCT_EVENTS": "1"})
    for cid, states in (
        ("m1", ["queued", "sending", "unknown", "sent"]),
        ("m2", ["queued", "sending", "unknown"]),
        ("m3", ["queued", "not_sent"]),
    ):
        obs.note_message(SID, cid)
        obs.record("message.submit", session=SID, msg=cid, outcome="accepted", harness="codex")
        previous = None
        for state in states:
            obs.record(
                "delivery.state",
                session=SID,
                msg=cid,
                from_state=previous,
                to_state=state,
                latency_ms=None if cid == "m1" else 3,
            )
            previous = state
    # Replays of the same transition and a late downgrade attempt that was refused upstream.
    obs.record("delivery.state", session=SID, msg="m1", from_state="unknown", to_state="sent")
    obs.record("message.submit", session=SID, msg="m1", outcome="accepted", harness="codex")
    obs.record("message.submit", session=SID, msg="m4", outcome="accepted", harness="claude-code")
    obs.record("turn.end", harness="codex")
    assert obs.flush()
    obs.close()
    product_file = tmp_path / "observability" / "product" / "events.jsonl"
    product_file.write_text(product_file.read_text() * 2)  # exact duplicate lines
    summary = report.summarize(tmp_path, envs={"test"})
    delivery = summary["product"]["delivery"]
    assert delivery["submitted"] == 4
    assert delivery["final_state"] == {
        "sent": 1,
        "not_sent": 1,
        "unknown": 1,
        "in_flight": 0,
        "no_receipt": 1,
        "other": 0,
    }
    assert delivery["unknown_later_confirmed_sent"] == 1
    assert delivery["sent_confirmation_latency_ms"]["n"] == 0
    assert delivery["sent_confirmation_latency_ms"]["missing"] == 1
    assert summary["product"]["task_completion"] == "not_observable"
    assert summary["product"]["turns_ended_observed"] == 1
    assert summary["contains_test_data"] is True
    assert summary["samples"]["read_stats"]["product"]["duplicates"] > 0
    samples = summary["samples"]
    assert samples["record_versions"] == {
        "2": samples["product_records"] + samples["diagnostic_records"]
    }
    excluded = report.summarize(tmp_path, envs={"prod"})
    assert excluded["product"]["status"] == "unavailable"
    assert excluded["contains_test_data"] is False
    assert excluded["samples"]["read_stats"]["product"]["excluded_other_env"] > 0
    assert "delivery.final_state.unknown,1" in report.to_csv(summary).replace("product,", "")


def test_same_client_id_in_two_sessions_counts_twice(tmp_path: Path) -> None:
    obs = Observability(tmp_path, env_name="test", env={"HBRIDGE_PRODUCT_EVENTS": "1"})
    a, b = "ses_00000000000a", "ses_00000000000b"
    for sid, final in ((a, "sent"), (b, "unknown")):
        obs.note_message(sid, "same-id")
        obs.record("message.submit", session=sid, msg="same-id", outcome="accepted")
        for state in ("queued", "sending", final):
            obs.record("delivery.state", session=sid, msg="same-id", to_state=state)
    assert obs.flush()
    obs.close()
    delivery = report.summarize(tmp_path, envs={"test"})["product"]["delivery"]
    assert delivery["submitted"] == 2
    assert delivery["final_state"]["sent"] == 1 and delivery["final_state"]["unknown"] == 1
    assert delivery["unknown_later_confirmed_sent"] == 0


def test_v1_records_are_rekeyed_by_session_and_flagged(tmp_path: Path) -> None:
    """v1 wrote the client-ID-only alias; the session alias still separates the messages."""
    product = tmp_path / "observability" / "product"
    product.mkdir(parents=True)
    rows = []
    for seq, (session, event, extra) in enumerate(
        [
            ("s_000000000a", "message.submit", {"outcome": "accepted"}),
            ("s_000000000a", "delivery.state", {"attrs": {"to_state": "sent"}}),
            ("s_000000000b", "message.submit", {"outcome": "accepted"}),
            ("s_000000000b", "delivery.state", {"attrs": {"to_state": "unknown"}}),
        ],
        start=1,
    ):
        rows.append(
            {
                "v": 1,
                "ts": f"2026-10-10T00:00:0{seq}.000Z",
                "seq": seq,
                "proc": "p_00000000",
                "stream": "product",
                "env": "test",
                "level": "info",
                "event": event,
                "session": session,
                "msg": "m_00000000aa",  # same v1 alias in both sessions
                **extra,
            }
        )
    (product / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    summary = report.summarize(tmp_path, envs={"test"})
    delivery = summary["product"]["delivery"]
    assert delivery["submitted"] == 2
    assert delivery["final_state"]["sent"] == 1 and delivery["final_state"]["unknown"] == 1
    assert delivery["unknown_later_confirmed_sent"] == 0
    assert delivery["v1_records"] == 4 and any("v1 records" in n for n in delivery["notes"])
    assert summary["samples"]["record_versions"] == {"1": 4}
