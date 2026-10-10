"""Summary semantics: de-duplication, explicit denominators, unknown stays unknown."""

from __future__ import annotations

from pathlib import Path

from harness_bridge.observability import Observability, report


def test_summary_dedupes_and_keeps_unknown_unknown(tmp_path: Path) -> None:
    obs = Observability(tmp_path, env_name="test", env={"HBRIDGE_PRODUCT_EVENTS": "1"})
    for cid, states in (
        ("m1", ["queued", "sending", "unknown", "sent"]),
        ("m2", ["queued", "sending", "unknown"]),
        ("m3", ["queued", "not_sent"]),
    ):
        obs.note_message(cid)
        obs.record("message.submit", msg=cid, outcome="accepted", harness="codex")
        previous = None
        for state in states:
            obs.record(
                "delivery.state",
                msg=cid,
                from_state=previous,
                to_state=state,
                latency_ms=None if cid == "m1" else 3,
            )
            previous = state
    # Replays of the same transition and a late downgrade attempt that was refused upstream.
    obs.record("delivery.state", msg="m1", from_state="unknown", to_state="sent")
    obs.record("message.submit", msg="m1", outcome="accepted", harness="codex")
    obs.record("message.submit", msg="m4", outcome="accepted", harness="claude-code")
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
    excluded = report.summarize(tmp_path, envs={"prod"})
    assert excluded["product"]["status"] == "unavailable"
    assert excluded["contains_test_data"] is False
    assert excluded["samples"]["read_stats"]["product"]["excluded_other_env"] > 0
    assert "delivery.final_state.unknown,1" in report.to_csv(summary).replace("product,", "")
