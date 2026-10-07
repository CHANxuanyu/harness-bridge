"""CLI contract tests: every step is a separate OS process (state must persist in SQLite)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import Fixture
from tests.helpers.reviews import review_for


def write(path: Path, obj: object) -> str:
    path.write_text(json.dumps(obj))
    return str(path)


def test_r01_cli_flow_across_fresh_processes(fx: Fixture, tmp_path: Path) -> None:
    task_file = write(tmp_path / "task.json", fx.spec("success"))
    code, created = fx.cli("create", "--task", task_file, "--idempotency-key", "k1")
    assert code == 0 and created["state"] == "READY"
    task_id = created["task_id"]
    code, again = fx.cli("create", "--task", task_file, "--idempotency-key", "k1")
    assert again["task_id"] == task_id and again["created"] is False
    code, run = fx.cli("run", task_id, "--mode", "mock")
    assert run["state"] == "AWAITING_REVIEW" and run["verification_status"] == "passed"
    code, summary = fx.cli("artifacts", task_id)
    review = write(tmp_path / "review.json", review_for(summary, "approve", "r1"))
    code, receipt = fx.cli("review", task_id, "--file", review)
    assert receipt["resulting_state"] == "SUCCEEDED"
    code, dup = fx.cli("review", task_id, "--file", review)
    assert dup["duplicate"] is True and dup["review_id"] == receipt["review_id"]
    code, status = fx.cli("status", task_id)
    assert status["state"] == "SUCCEEDED"
    assert [e["type"] for e in status["recent_events"]][-1] == "review_accepted"


def test_error_envelopes_and_exit_codes(fx: Fixture, tmp_path: Path) -> None:
    code, payload = fx.cli("status", "tsk_missing", check_ok=False)
    assert code == 5 and payload["error"]["code"] == "NOT_FOUND"
    code, payload = fx.cli(
        "create", "--task", str(tmp_path / "nope.json"), "--idempotency-key", "k", check_ok=False
    )
    assert code == 2 and payload["error"]["code"] == "INVALID_INPUT"
    bad = write(tmp_path / "bad.json", {"schema_version": "9.9"})
    code, payload = fx.cli("create", "--task", bad, "--idempotency-key", "k", check_ok=False)
    assert code == 2 and "schema_version" in payload["error"]["message"]
    task_file = write(tmp_path / "task.json", fx.spec("success"))
    _, created = fx.cli("create", "--task", task_file, "--idempotency-key", "k2")
    fx.cli("run", created["task_id"])
    code, payload = fx.cli("run", created["task_id"], check_ok=False)
    assert code == 3 and payload["error"]["code"] == "STATE_CONFLICT"
    assert set(payload["error"]) >= {"code", "message", "retryable", "task_id"}


def test_live_mode_refused_without_all_gates(fx: Fixture, tmp_path: Path) -> None:
    spec = fx.spec()
    spec["executor"] = {"kind": "claude-code"}
    _, created = fx.cli(
        "create", "--task", write(tmp_path / "t.json", spec), "--idempotency-key", "k"
    )
    code, payload = fx.cli("run", created["task_id"], "--mode", "live", check_ok=False)
    assert code == 4 and payload["error"]["code"] == "LIVE_GATE_CLOSED"
    reasons = payload["error"]["details"]["closed_reasons"]
    assert any("--allow-model-usage" in r for r in reasons)
    assert any("config.toml" in r for r in reasons)


def test_doctor_offline_is_non_inference(fx: Fixture) -> None:
    code, report = fx.cli("doctor", "--offline")
    assert code == 0
    assert report["inference_performed"] is False
    assert report["tools"]["claude"]["version"] is None  # offline: binary never executed
    assert report["live_gate_preview"]["open"] is False
    statuses = {c["name"]: c["status"] for c in report["capabilities"]}
    assert statuses["claude_code_live_dispatch"] == "unknown"
    assert statuses["zcode_executor_adapter"] == "offline_only"
    zcode = next(
        c["evidence"] for c in report["capabilities"] if c["name"] == "zcode_executor_adapter"
    )
    assert zcode["live_dispatch"] == "unavailable" and zcode["gaps"]


def test_demo_success_and_bug_then_repair(fx: Fixture, tmp_path: Path) -> None:
    for scenario in ("success", "bug-then-repair"):
        code, report = fx.cli(
            "demo", "--scenario", scenario, "--workdir", str(tmp_path / scenario), timeout=300
        )
        assert code == 0 and report["demo_passed"] is True, report
        assert all(report["checks"].values())
        assert report["final_state"] == "SUCCEEDED"
    timeline = report["timeline"]
    assert [t["bridge_verification"] for t in timeline] == ["failed", "passed"]
    assert timeline[0]["executor_claimed_tests"] == "passed"
    assert timeline[0]["approve_probe_rejected_with"] == "APPROVAL_GATE_FAILED"
