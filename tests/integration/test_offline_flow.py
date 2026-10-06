"""Offline integration tests: real fake-executor subprocess, real temporary git repo, real
verifier commands, real SQLite. Evidence level: offline integration (simulated executor)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.workspace import checkout_fingerprint
from tests.conftest import Fixture
from tests.helpers.reviews import review_for
from tests.unit.test_runner import alive as pid_alive


def create_and_run(fx: Fixture, scenario: str, key: str = "k1", **limits: object):  # type: ignore[no-untyped-def]
    b = fx.bridge()
    created = b.create(fx.spec(scenario, **limits), key)
    run = b.run(created["task_id"])
    return b, created["task_id"], run


def test_c01_success_flow_end_to_end(fx: Fixture) -> None:
    before = checkout_fingerprint(str(fx.repo))
    b, task_id, run = create_and_run(fx, "success")
    assert run["state"] == "AWAITING_REVIEW"
    assert run["executor_outcome"] == "succeeded"
    assert run["verification_status"] == "passed"
    summary = b.artifacts(task_id)
    assert summary["approval_gate"] == {"approvable": True, "blockers": []}
    assert [c["path"] for c in summary["changes"]["paths"]] == ["tagnorm/normalize.py"]
    # the executor really changed the file in the bridge-owned worktree
    worktree = Path(b.status(task_id)["worktree"])
    assert "seen = set()" in (worktree / "tagnorm/normalize.py").read_text()
    receipt = b.review(task_id, review_for(summary, "approve", "r1"))
    assert receipt["status"] == "accepted" and receipt["resulting_state"] == "SUCCEEDED"
    assert b.status(task_id)["state"] == "SUCCEEDED"
    # C12: user's checkout untouched (branch, HEAD, index, files)
    assert checkout_fingerprint(str(fx.repo)) == before
    assert "NotImplementedError" in (fx.repo / "tagnorm/normalize.py").read_text()


def test_c03_executor_false_success_claim_cannot_be_approved(fx: Fixture) -> None:
    b, task_id, run = create_and_run(fx, "false-success-report")
    assert run["executor_outcome"] == "succeeded"
    assert run["verification_status"] == "failed"
    summary = b.artifacts(task_id)
    assert summary["executor_reported"]["tests_reported"] == "passed"
    assert "executor claimed tests passed but bridge verification did not pass" in summary["risks"]
    with pytest.raises(BridgeError) as exc:
        b.review(task_id, review_for(summary, "approve", "r1"))
    assert exc.value.code == "APPROVAL_GATE_FAILED"
    assert b.status(task_id)["state"] == "AWAITING_REVIEW"


def test_tampered_repository_tests_do_not_fool_external_acceptance(fx: Fixture) -> None:
    b, task_id, run = create_and_run(fx, "tamper-tests")
    checks = {c["id"]: c["status"] for c in b.artifacts(task_id)["verification"]["checks"]}
    assert checks == {"repo-tests": "passed", "acceptance": "failed"}
    assert run["verification_status"] == "failed"


def test_c04_create_idempotency(fx: Fixture) -> None:
    b = fx.bridge()
    first = b.create(fx.spec(), "same-key")
    again = b.create(fx.spec(), "same-key")
    assert again["task_id"] == first["task_id"] and again["created"] is False
    assert len(b.store.list_tasks()) == 1
    with pytest.raises(BridgeError) as exc:
        b.create(fx.spec("bug-then-repair"), "same-key")
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"
    other = b.create(fx.spec(), "other-key")
    assert other["task_id"] != first["task_id"]


def test_c05_repeated_run_does_not_spawn(fx: Fixture) -> None:
    b, task_id, _ = create_and_run(fx, "success")
    with pytest.raises(BridgeError) as exc:
        b.run(task_id)
    assert exc.value.code == "STATE_CONFLICT"
    assert len(b.store.list_attempts(task_id)) == 1


def test_c06_malformed_output_is_protocol_error_not_success(fx: Fixture) -> None:
    b, task_id, run = create_and_run(fx, "malformed-output")
    assert run["executor_outcome"] == "protocol_error"
    assert run["state"] == "AWAITING_REVIEW"
    summary = b.artifacts(task_id)
    assert not summary["approval_gate"]["approvable"]
    assert any("protocol_error" in x for x in summary["approval_gate"]["blockers"])


def test_c07_hang_times_out_and_kills_owned_group(fx: Fixture) -> None:
    b, task_id, run = create_and_run(fx, "hang", wall_timeout_seconds=1.5, kill_grace_seconds=0.5)
    assert run["executor_outcome"] == "timed_out"
    attempt = b.store.list_attempts(task_id)[0]
    assert attempt.exit_confirmed is True
    assert attempt.process and attempt.process["timed_out"] and attempt.process["term_sent"]
    assert not b.artifacts(task_id)["approval_gate"]["approvable"]
    # the fake started a helper child in its process group; it must be gone too
    log = fx.state_dir / "artifacts" / task_id / attempt.attempt_id / "executor.stdout.log"
    child = next(json.loads(x) for x in log.read_text().splitlines() if '"child"' in x)
    assert not pid_alive(child["pid"])


def test_c07_crash_is_classified(fx: Fixture) -> None:
    b, task_id, run = create_and_run(fx, "crash")
    assert run["executor_outcome"] == "crashed"
    assert b.store.list_attempts(task_id)[0].exit_code == 3


def test_c08_scope_violation_and_secret_handling(fx: Fixture) -> None:
    b, task_id, run = create_and_run(fx, "scope-violation")
    assert run["executor_outcome"] == "succeeded"
    summary = b.artifacts(task_id)
    rules = {(v["path"], v["rule"]) for v in summary["scope_violations"]}
    assert (".env", "forbidden_path") in rules
    assert (".env", "secret_path") in rules
    assert ("notes.txt", "outside_allowed_paths") in rules
    assert not summary["approval_gate"]["approvable"]
    with pytest.raises(BridgeError) as exc:
        b.review(task_id, review_for(summary, "approve", "r1"))
    assert exc.value.code == "APPROVAL_GATE_FAILED"
    # S02: the fake token never reaches stored artifacts (secret path content is withheld)
    adir = Path(summary["artifact_dir"])
    for f in adir.rglob("*"):
        if f.is_file():
            assert b"THISISAFAKETESTTOKEN" not in f.read_bytes(), f
    manifest = json.loads((adir / "manifest.json").read_text())
    assert manifest["diff"]["content_withheld_paths"] == [".env"]


def test_c09_stale_reviews_are_rejected(fx: Fixture) -> None:
    b, task_id, _ = create_and_run(fx, "success")
    summary = b.artifacts(task_id)
    for bad in (
        {"snapshot_digest": "sha256:" + "0" * 64},
        {"attempt_id": "att_not_current"},
        {"task_version": 2},
    ):
        with pytest.raises(BridgeError) as exc:
            b.review(task_id, review_for(summary, "approve", f"k-{next(iter(bad))}", **bad))
        assert exc.value.code == "STALE_REVIEW"
    with pytest.raises(BridgeError) as exc:
        b.review("tsk_other", review_for(summary, "approve", "k"))
    assert exc.value.code == "INVALID_INPUT"
    assert b.status(task_id)["state"] == "AWAITING_REVIEW"


def test_c10_verifier_timeout_is_not_a_pass(fx: Fixture) -> None:
    b = fx.bridge()
    spec = fx.spec("success")
    spec["verification"].append(
        {
            "id": "slow",
            "argv": [sys.executable, "-c", "import time; time.sleep(30)"],
            "timeout_seconds": 0.5,
            "required": True,
            "trust": "external-acceptance",
        }
    )
    spec["limits"]["kill_grace_seconds"] = 0.3
    task_id = b.create(spec, "k")["task_id"]
    run = b.run(task_id)
    checks = {c["id"]: c["status"] for c in b.artifacts(task_id)["verification"]["checks"]}
    assert checks["slow"] == "timed_out"
    assert run["verification_status"] == "failed"
    assert not b.artifacts(task_id)["approval_gate"]["approvable"]


def test_verifier_that_cannot_start_is_error_not_pass(fx: Fixture) -> None:
    b = fx.bridge()
    spec = fx.spec("success")
    spec["verification"][0]["argv"] = ["/nonexistent/verifier"]
    task_id = b.create(spec, "k")["task_id"]
    assert b.run(task_id)["verification_status"] == "failed"
    checks = {c["id"]: c["status"] for c in b.artifacts(task_id)["verification"]["checks"]}
    assert checks["repo-tests"] == "error"


def test_optional_check_failure_is_a_warning_only(fx: Fixture) -> None:
    b = fx.bridge()
    spec = fx.spec("success")
    spec["verification"].append(
        {
            "id": "lint",
            "argv": [sys.executable, "-c", "raise SystemExit(1)"],
            "timeout_seconds": 10,
            "required": False,
            "trust": "repository-tests",
        }
    )
    task_id = b.create(spec, "k")["task_id"]
    assert b.run(task_id)["verification_status"] == "passed"
    summary = b.artifacts(task_id)
    assert summary["verification"]["warnings"]
    assert summary["approval_gate"]["approvable"]


def test_c11_live_gate_closed_by_default(fx: Fixture) -> None:
    b = fx.bridge()
    spec = fx.spec("success")
    spec["executor"] = {"kind": "claude-code"}
    task_id = b.create(spec, "k")["task_id"]
    with pytest.raises(BridgeError) as exc:
        b.run(task_id, mode="live", allow_model_usage=True)
    assert exc.value.code == "LIVE_GATE_CLOSED"
    assert "config.toml" in exc.value.message
    assert b.status(task_id)["state"] == "READY"
    assert b.store.list_attempts(task_id) == []


def test_c12_dirty_source_checkout_is_refused(fx: Fixture) -> None:
    (fx.repo / "scratch.txt").write_text("uncommitted user work\n")
    before = checkout_fingerprint(str(fx.repo))
    with pytest.raises(BridgeError) as exc:
        fx.bridge().create(fx.spec(), "k")
    assert exc.value.code == "SOURCE_REPO_DIRTY"
    assert checkout_fingerprint(str(fx.repo)) == before
    assert (fx.repo / "scratch.txt").read_text() == "uncommitted user work\n"


def test_repo_without_commits_is_refused(tmp_path: Path, fx: Fixture) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["git", "init", "-q", str(empty)], check=True)
    spec = fx.spec()
    spec["repo"]["path"] = str(empty)
    with pytest.raises(BridgeError) as exc:
        fx.bridge().create(spec, "k")
    assert "no commits" in exc.value.message


def test_base_ref_is_pinned_to_a_sha(fx: Fixture) -> None:
    b = fx.bridge()
    created = b.create(fx.spec(), "k")
    head_then = created["base_sha"]
    (fx.repo / "README.md").write_text("moved on\n")
    subprocess.run(["git", "-C", str(fx.repo), "commit", "-qam", "move"], check=True)
    b.run(created["task_id"])
    assert b.store.get_task(created["task_id"]).base_sha == head_then


def test_r07_candidate_change_after_evidence_invalidates_review(fx: Fixture) -> None:
    b, task_id, _ = create_and_run(fx, "success")
    summary = b.artifacts(task_id)
    worktree = Path(b.status(task_id)["worktree"])
    (worktree / "tagnorm" / "normalize.py").write_text("def normalize_tags(v):\n    return v\n")
    assert not b.artifacts(task_id)["approval_gate"]["approvable"]
    with pytest.raises(BridgeError) as exc:
        b.review(task_id, review_for(summary, "approve", "r1"))
    assert exc.value.code == "STALE_REVIEW"
    assert b.status(task_id)["state"] == "AWAITING_REVIEW"


def test_s03_tampered_verifier_config_is_detected(fx: Fixture) -> None:
    b = fx.bridge()
    task_id = b.create(fx.spec(), "k")["task_id"]
    db = fx.state_dir / "bridge.sqlite3"
    conn = sqlite3.connect(db)
    spec_json = conn.execute("SELECT spec_json FROM tasks").fetchone()[0]
    weakened = json.loads(spec_json)
    weakened["verification"] = [
        dict(weakened["verification"][0], argv=[sys.executable, "-c", "pass"])
    ]
    conn.execute("UPDATE tasks SET spec_json=?", (json.dumps(weakened, sort_keys=True),))
    conn.commit()
    conn.close()
    with pytest.raises(BridgeError) as exc:
        b.run(task_id)
    assert exc.value.code == "INTEGRITY_ERROR"
    assert b.store.list_attempts(task_id) == []


def test_tampered_manifest_file_is_detected(fx: Fixture) -> None:
    b, task_id, _ = create_and_run(fx, "success")
    summary = b.artifacts(task_id)
    manifest = Path(summary["artifact_dir"]) / "manifest.json"
    data = json.loads(manifest.read_text())
    data["scope_violations"] = []
    data["note"] = "edited"
    manifest.write_text(json.dumps(data))
    with pytest.raises(BridgeError) as exc:
        b.review(task_id, review_for(summary, "approve", "r1"))
    assert exc.value.code == "INTEGRITY_ERROR"


def test_a04_permission_and_quota_errors_block(fx: Fixture) -> None:
    b, task_id, run = create_and_run(fx, "permission-denied")
    assert run["state"] == "BLOCKED" and run["executor_outcome"] == "blocked"
    assert b.status(task_id)["state_details"]["category"] == "permission_denied"
    b2 = Fixture(fx.base / "second")
    bridge2 = b2.bridge()
    tid = bridge2.create(b2.spec("budget-exhausted"), "k")["task_id"]
    assert bridge2.run(tid)["state"] == "BLOCKED"
    details = bridge2.status(tid)["state_details"]
    assert details["category"] == "usage_limit"
    assert details["reset_at"] == "2099-01-01T00:00:00Z"
    assert details["classification"] == "structured"
    # no automatic re-dispatch
    with pytest.raises(BridgeError):
        bridge2.run(tid)
    assert len(bridge2.store.list_attempts(tid)) == 1


def test_noisy_executor_output_is_bounded(fx: Fixture) -> None:
    b, task_id, run = create_and_run(fx, "noisy", max_artifact_bytes=256 * 1024)
    assert run["verification_status"] == "passed"
    attempt = b.store.list_attempts(task_id)[0]
    assert attempt.process is not None
    stdout = attempt.process["stdout"]
    assert stdout["original_bytes"] > 3_000_000 and stdout["truncated"]
    adir = fx.state_dir / "artifacts" / task_id / attempt.attempt_id
    assert (adir / "executor.stdout.log").stat().st_size < 256 * 1024
    assert attempt.outcome == "succeeded"  # final result line survived truncation of the log


def test_summary_stays_under_24k(fx: Fixture) -> None:
    b, task_id, _ = create_and_run(fx, "bug-then-repair")
    summary = b.artifacts(task_id)
    assert len(json.dumps(summary).encode()) <= 24 * 1024


def test_show_artifact_is_restricted_to_known_names(fx: Fixture) -> None:
    b, task_id, _ = create_and_run(fx, "success")
    diff = b.artifacts(task_id, show="diff")
    assert "tagnorm/normalize.py" in diff["content"]
    with pytest.raises(BridgeError) as exc:
        b.artifacts(task_id, show="../../bridge.sqlite3")
    assert exc.value.code == "INVALID_INPUT"
