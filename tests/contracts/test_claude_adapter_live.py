"""Offline parser regression against captured-live-redacted stream samples.

Evidence: field-level redactions of the executor stream logs that the bridge
captured during the two authorized live smokes of 2026-10-06 (T3 and T4; see
tests/fixtures/claude_stream_live/PROVENANCE.json and the run records in
docs/LOCAL_SMOKE_HANDOFF.md and docs/T4_SMOKE_RESULT.md). These tests show the
real captured stream shape parses and classifies exactly as the live runs were
recorded. They do NOT re-run any model and do not prove turn-limit enforcement,
resume behaviour, or anything about other tasks or CLI versions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_bridge.adapters.base import InvocationContext, TaskPacket
from harness_bridge.adapters.claude_code import ClaudeCodeAdapter, ClaudeSettings
from harness_bridge.runner import ProcessOutcome, StreamCapture
from harness_bridge.state import AttemptOutcome

FIX = Path(__file__).parents[1] / "fixtures"
LIVE = FIX / "claude_stream_live"
MODEL = "claude-opus-5-5"
VERSION = "2.1.291"

# Fictional ids substituted during redaction (see PROVENANCE.json).
SAMPLES = {
    "t3_live_smoke_redacted.jsonl": {
        "session": "00000000-0000-4000-8000-000000000001",
        "num_turns": 7,
        "cost_usd": 0.1787086,
    },
    "t4_live_smoke_redacted.jsonl": {
        "session": "00000000-0000-4000-8000-000000000002",
        "num_turns": 8,
        "cost_usd": 0.1982224,
    },
}


def adapter() -> ClaudeCodeAdapter:
    settings = {
        "requested_model": MODEL,
        "max_turns": 10,
        "permission_mode": "acceptEdits",
        "allowed_tools": (
            "Read",
            "Edit",
            "Write",
            "Glob",
            "Grep",
            "Bash(python3 -B -m unittest:*)",
        ),
        "strict_mcp_config": True,
    }
    return ClaudeCodeAdapter(ClaudeSettings(**settings))  # type: ignore[arg-type]


def packet() -> TaskPacket:
    return TaskPacket(
        task_id="tsk_live_sample",
        attempt_id="att_live_sample",
        attempt_seq=1,
        attempt_kind="initial",
        goal="Implement slugkit.slugify.slugify per the requirements (single function).",
        requirements=["Lowercase first", "Collapse non-alphanumeric runs to '-'"],
        allowed_paths=["slugkit/**", "tests/**"],
        forbidden_paths=[".env"],
        verification=[
            {
                "id": "repo-tests",
                "argv": ["python3", "-B", "-m", "unittest", "discover"],
                "required": True,
                "trust": "repository-tests",
            }
        ],
        max_turns=10,
    )


def classify(name: str):  # type: ignore[no-untyped-def]
    a = adapter()
    a.build_invocation(
        packet(),
        InvocationContext(
            worktree="/tmp/hbridge-live-sample-nonexistent",
            mode="live",
            python_executable="/usr/bin/python3",
            base_env={"PATH": "/usr/bin", "HOME": "/home/u"},
            executor_binary="/opt/claude/bin/claude",
            resume_session_id=None,
        ),
    )
    events = [a.parse_event(line.encode()) for line in (LIVE / name).read_text().splitlines()]
    err = StreamCapture(4096, 4096)
    proc = ProcessOutcome(pid=1, pgid=1, returncode=0, group_exit_confirmed=True, stderr=err)
    return a, events, a.classify_completion(proc, events)


def test_provenance_lists_exactly_the_live_samples() -> None:
    prov = json.loads((LIVE / "PROVENANCE.json").read_text())
    assert prov["provenance"] == "captured-live-redacted"
    assert prov["cli_version_captured"] == VERSION
    files = sorted(p.name for p in LIVE.glob("*.jsonl"))
    assert files == sorted(prov["files"])


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_model_session_and_success_are_identified(name: str) -> None:
    want = SAMPLES[name]
    _a, events, r = classify(name)
    sessions = [e for e in events if e.kind == "session"]
    results = [e for e in events if e.kind == "result"]
    assert len(sessions) == 1 and len(results) == 1
    assert sessions[0].model == MODEL and sessions[0].session_id == want["session"]
    assert sessions[0].data["api_key_source"] == "none"
    assert sessions[0].data["cli_version"] == VERSION
    assert r.outcome is AttemptOutcome.SUCCEEDED
    assert r.observed_model == MODEL and r.session_id == want["session"]
    assert r.executor_reported["model_pin"] == "satisfied"
    assert r.executor_reported["status"] == "success" and r.executor_reported["is_error"] is False
    assert r.executor_reported["num_turns"] == want["num_turns"]


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_result_and_denial_summaries_match_the_sample(name: str) -> None:
    want = SAMPLES[name]
    _, _, r = classify(name)
    # the final summary is the documented placeholder, not model prose
    assert r.executor_reported["summary"] == "[REDACTED EXECUTOR FINAL SUMMARY]"
    assert r.executor_reported["permission_denials"] == 2
    assert r.executor_reported["permission_denied_tools"] == ["Bash"]
    assert r.usage["input_tokens_reported"] is not None
    assert r.usage["cost_estimate_usd_reported"] == pytest.approx(want["cost_usd"])
    assert r.usage["source"] == "executor result event"


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_unrecognized_events_do_not_break_later_parsing(name: str) -> None:
    _a, events, r = classify(name)
    raw_lines = [json.loads(line) for line in (LIVE / name).read_text().splitlines()]
    unknown_types = {
        d["type"] for d in raw_lines if d["type"] not in ("system", "assistant", "user", "result")
    }
    assert unknown_types == {"rate_limit_event"}
    assert unknown_types <= set(r.protocol["unknown_types"])
    # every unknown event parses as such, and legal events after each one survive
    for i, d in enumerate(raw_lines):
        if d["type"] in unknown_types:
            assert events[i].kind == "unknown"
            later_kinds = {e.kind for e in events[i + 1 :]}
            assert later_kinds <= {"message", "session", "progress", "result", "unknown"}
            assert "result" in later_kinds
    assert r.protocol["result_seen"] and r.protocol["malformed_lines"] == 0


def test_live_samples_leak_no_private_data() -> None:
    forbidden = [
        "/Users/",
        "/private/",
        "chan",
        "79b022b7",
        "8d42c8f1",  # real session prefixes
        "tsk_5a3e",
        "tsk_d83b",
        "hbridge-t3-live",
        "t4-f42e719a1835",
        '"tool_input"',
        '"wire_tool_inputs"',
        '"cwd"',
        '"uuid"',
        '"timestamp"',
        '"content"',
        "slugify",  # no task-specific implementation text either
    ]
    for path in LIVE.glob("*.jsonl"):
        text = path.read_text()
        for marker in forbidden:
            assert marker not in text, f"{path.name} contains {marker!r}"
