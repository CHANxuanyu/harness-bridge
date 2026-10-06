"""Claude adapter through the full bridge pipeline with a STUB executable (not Claude, no model).

Evidence: offline integration with a stub binary replaying synthetic/docs-derived streams.
This exercises runner + adapter + store + verifier + review wiring and the live-path preflight.
It is not a live test (T3) and must never be reported as one.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.service import Bridge
from tests.conftest import Fixture
from tests.helpers.reviews import review_for

HERE = Path(__file__).parents[1]
STREAM = HERE / "fixtures" / "claude_stream"
HELP = HERE / "fixtures" / "claude_help_2.1.291.txt"


@pytest.fixture
def stub(tmp_path: Path) -> Path:
    bindir = tmp_path / "stubbin"
    bindir.mkdir()
    exe = bindir / "cc-stub"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{HERE / "helpers" / "cc_stub.py"}" "$@"\n')
    exe.chmod(0o755)
    return exe


def claude_spec(fx: Fixture, **executor: Any) -> dict[str, Any]:
    spec = fx.spec("success")
    spec["executor"] = {
        "kind": "claude-code",
        "requested_model": "claude-opus-5-5",
        "allowed_tools": ["Read", "Edit"],
        **executor,
    }
    return spec


def bridge(fx: Fixture, **env: str) -> Bridge:
    return Bridge(fx.state_dir, env={**os.environ, **env})


def argv_log(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_stub_flow_with_resume_on_repair(fx: Fixture, stub: Path, tmp_path: Path) -> None:
    log = tmp_path / "argv.jsonl"
    env = {
        "HBRIDGE_STUB_FIXTURE": str(STREAM / "success.jsonl"),
        "HBRIDGE_STUB_ARGV_LOG": str(log),
        "HBRIDGE_STUB_EDIT": "buggy",
        "HBRIDGE_STUB_TRICKLE": "1",
    }
    b = bridge(fx, **env)
    task_id = b.create(claude_spec(fx), "k")["task_id"]
    first = b.run(task_id, mode="mock", executor_binary=str(stub))
    assert first["executor_outcome"] == "succeeded"  # executor says success...
    assert first["verification_status"] == "failed"  # ...the bridge's verifiers disagree
    assert first["evidence_level"] == "offline-stub-binary"
    attempt1 = b.store.list_attempts(task_id)[0]
    assert attempt1.session_id and attempt1.observed_model == "claude-opus-5-5"
    b.review(task_id, review_for(b.artifacts(task_id), "changes_requested", "r1"))
    b2 = bridge(fx, **{**env, "HBRIDGE_STUB_EDIT": "correct"})
    second = b2.run(task_id, mode="mock", executor_binary=str(stub))
    assert second["verification_status"] == "passed"
    calls = argv_log(log)
    assert "--resume" not in calls[0]["argv"]
    assert calls[1]["argv"][-2:] == ["--resume", attempt1.session_id]
    assert "fix it" in calls[1]["stdin_text"]  # review feedback reached the executor via stdin
    assert all(c["cwd"].endswith(task_id) for c in calls)
    b2.review(task_id, review_for(b2.artifacts(task_id), "approve", "r2"))
    assert b2.status(task_id)["state"] == "SUCCEEDED"
    usage = b2.store.list_attempts(task_id)[1].usage
    assert usage is not None and usage["source"] == "executor result event"


def test_stub_resume_not_honoured_blocks(fx: Fixture, stub: Path, tmp_path: Path) -> None:
    env = {"HBRIDGE_STUB_FIXTURE": str(STREAM / "success.jsonl"), "HBRIDGE_STUB_EDIT": "buggy"}
    b = bridge(fx, **env)
    task_id = b.create(claude_spec(fx), "k")["task_id"]
    b.run(task_id, mode="mock", executor_binary=str(stub))
    b.review(task_id, review_for(b.artifacts(task_id), "changes_requested", "r1"))
    b2 = bridge(fx, HBRIDGE_STUB_FIXTURE=str(STREAM / "resume_new_session.jsonl"))
    second = b2.run(task_id, mode="mock", executor_binary=str(stub))
    assert second["state"] == "BLOCKED"
    details = b2.status(task_id)["state_details"]
    assert details["category"] == "resume_failed"


def test_mock_mode_never_runs_a_real_claude(fx: Fixture, stub: Path) -> None:
    b = bridge(fx)
    task_id = b.create(claude_spec(fx), "k")["task_id"]
    with pytest.raises(BridgeError) as exc:
        b.run(task_id, mode="mock")
    assert exc.value.code == "PREFLIGHT_FAILED"
    sentinel = b.env["PATH"].split(os.pathsep)[0] + "/claude"  # the conftest sentinel
    for bad in (sentinel, "relative/stub"):
        with pytest.raises(BridgeError):
            b.run(task_id, mode="mock", executor_binary=bad)
    named = stub.with_name("claude-wrapper")
    named.write_text(stub.read_text())
    named.chmod(0o755)
    with pytest.raises(BridgeError):
        b.run(task_id, mode="mock", executor_binary=str(named))
    assert b.store.list_attempts(task_id) == []


def _live_config(fx: Fixture, binary: Path, extra: str = "") -> None:
    fx.state_dir.mkdir(parents=True, exist_ok=True)
    (fx.state_dir / "config.toml").write_text(
        "[live]\nenabled = true\nhooks_and_permissions_reviewed = true\n"
        f'claude_binary = "{binary}"\n{extra}'
    )


def test_live_code_path_with_stub_binary_is_not_a_real_run(
    fx: Fixture, stub: Path, tmp_path: Path
) -> None:
    """Exercises gate -> help-text preflight -> dispatch using a STUB as the configured binary."""
    log = tmp_path / "argv.jsonl"
    _live_config(fx, stub)
    env = {
        "HBRIDGE_STUB_HELP": str(HELP),
        "HBRIDGE_STUB_FIXTURE": str(STREAM / "success.jsonl"),
        "HBRIDGE_STUB_ARGV_LOG": str(log),
        "HBRIDGE_STUB_EDIT": "correct",
    }
    b = bridge(fx, **env)
    task_id = b.create(claude_spec(fx), "k")["task_id"]
    with pytest.raises(BridgeError) as exc:
        b.run(task_id, mode="live", allow_model_usage=False)
    assert exc.value.code == "LIVE_GATE_CLOSED"
    with pytest.raises(BridgeError) as exc:
        b.run(task_id, mode="live", allow_model_usage=True)
    assert exc.value.code == "PREFLIGHT_FAILED"
    assert exc.value.details["unlisted_flags"] == ["--max-turns"]
    assert not log.exists() and b.store.list_attempts(task_id) == []
    _live_config(fx, stub, 'allow_unlisted_flags = ["--max-turns"]\n')
    b = bridge(fx, **env)
    run = b.run(task_id, mode="live", allow_model_usage=True)
    assert run["verification_status"] == "passed"
    assert argv_log(log)[0]["argv"][:4] == ["-p", "--output-format", "stream-json", "--verbose"]
    attempt = b.store.list_attempts(task_id)[0]
    assert any("0.0.0-stub" in n for n in attempt.invocation["notes"])


def test_live_gate_refuses_in_cloud_even_when_configured(fx: Fixture, stub: Path) -> None:
    _live_config(fx, stub)
    b = bridge(fx, CLAUDE_CODE_REMOTE="true", HBRIDGE_STUB_HELP=str(HELP))
    task_id = b.create(claude_spec(fx), "k")["task_id"]
    with pytest.raises(BridgeError) as exc:
        b.run(task_id, mode="live", allow_model_usage=True)
    assert exc.value.code == "LIVE_GATE_CLOSED"
    assert "cloud" in exc.value.message


def test_model_mismatch_surfaces_as_risk(fx: Fixture, stub: Path) -> None:
    b = bridge(
        fx, HBRIDGE_STUB_FIXTURE=str(STREAM / "model_mismatch.jsonl"), HBRIDGE_STUB_EDIT="correct"
    )
    task_id = b.create(claude_spec(fx), "k")["task_id"]
    b.run(task_id, mode="mock", executor_binary=str(stub))
    summary = b.artifacts(task_id)
    assert "observed model differs from the requested model pin" in summary["risks"]
    assert summary["executor_reported"]["model_pin"] == "mismatch"
