"""Offline Codex contracts. No installed binary, auth read, network or model call."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.adapters.base import InvocationContext, ParsedEvent
from harness_bridge.adapters.codex import LIVE_GAPS, CodexAdapter, CodexSettings
from harness_bridge.errors import BridgeError
from harness_bridge.models import ExecutorSpec, parse_task_spec
from harness_bridge.runner import ProcessOutcome, StreamCapture
from tests.contracts.test_claude_adapter import packet
from tests.unit.test_models import spec

SESSION = "0199a213-81c0-7800-8aa1-bbab2a035a53"
STREAM = Path(__file__).parents[1] / "fixtures/codex_stream"


def context(resume: str | None = None) -> InvocationContext:
    return InvocationContext(
        "/work/task", "mock", "/python", {"TOKEN": "not-in-describe"}, "/bin/stand-in", resume
    )


def lines() -> list[dict[str, Any]]:
    return [
        json.loads(x)
        for x in (STREAM / "success.jsonl")
        .read_text()
        .replace("__SESSION_ID__", SESSION)
        .splitlines()
    ]


def classify(
    data: list[Any], *, rc: int = 0, resume: str | None = None, stderr: bytes = b"", **process: Any
) -> Any:
    adapter = CodexAdapter(CodexSettings("test-pin"))
    adapter.build_invocation(packet(), context(resume))
    err = StreamCapture(4096, 4096)
    err.feed(stderr)
    outcome = ProcessOutcome(pid=1, pgid=1, returncode=rc, group_exit_confirmed=True, stderr=err)
    outcome = replace(outcome, **process)
    events = [
        x if isinstance(x, ParsedEvent) else adapter.parse_event(json.dumps(x).encode())
        for x in data
    ]
    return adapter.classify_completion(outcome, events)


def test_native_argv_stdin_environment_and_permissions() -> None:
    a = CodexAdapter(CodexSettings("test-pin"))
    p = packet("repair", [{"severity": "blocking", "explanation": "keep order"}])
    inv = a.build_invocation(p, context(SESSION))
    assert inv.argv == [
        "/bin/stand-in",
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "--cd",
        "/work/task",
        "--config",
        'approval_policy="never"',
        "--model",
        "test-pin",
        "resume",
        SESSION,
        "-",
    ]
    assert inv.cwd == "/work/task" and b"keep order" in inv.stdin
    assert all("keep order" not in item for item in inv.argv)
    assert inv.env == context().base_env
    assert "not-in-describe" not in json.dumps(inv.describe())
    assert "--max-turns" not in inv.argv  # no invented Codex flag
    assert any("not enforced" in n for n in inv.notes)


def test_live_is_refused_even_by_direct_adapter() -> None:
    a = CodexAdapter(CodexSettings())
    with pytest.raises(BridgeError) as exc:
        a.build_invocation(packet(), replace(context(), mode="live"))
    assert exc.value.details["gaps"] == list(LIVE_GAPS)
    assert a.describe_capabilities()["live_dispatch"] == "gated_wall_time_only"


@pytest.mark.parametrize("sid", ["--last", "latest", "-", "", SESSION.upper(), SESSION + "x"])
def test_session_names_options_or_invalid_uuid_refused(sid: str) -> None:
    with pytest.raises(BridgeError):
        CodexAdapter(CodexSettings()).build_invocation(packet(), context(sid))


def test_report_does_not_infer_model_calls_cost_subscription_or_test_success() -> None:
    r = classify(lines())
    assert r.outcome == "succeeded" and r.session_id == SESSION
    assert r.observed_model is None and r.executor_reported["model_pin"] == "unknown"
    assert (
        r.executor_reported["num_turns"] is None and r.executor_reported["tests_reported"] is None
    )
    assert r.usage["input_tokens_reported"] == 120
    assert r.usage["cache_read_tokens_reported"] == 80
    assert r.usage["cost_estimate_usd_reported"] is None
    assert r.usage["subscription_remaining"] is None


@pytest.mark.parametrize(
    "case",
    [
        "missing-init",
        "missing-start",
        "missing-final",
        "duplicate-init",
        "duplicate-final",
        "after-final",
        "reorder",
        "unknown",
        "malformed",
        "oversized",
        "bad-usage",
        "boolean-usage",
        "negative-usage",
        "bad-id",
        "array",
        "unknown-item",
    ],
)
def test_incomplete_ambiguous_stream_never_succeeds(case: str) -> None:
    data: list[Any] = lines()
    if case == "missing-init":
        data.pop(0)
    elif case == "missing-start":
        data.pop(1)
    elif case == "missing-final":
        data.pop()
    elif case == "duplicate-init":
        data.insert(1, data[0])
    elif case == "duplicate-final":
        data.append(data[-1])
    elif case == "after-final":
        data.append(data[2])
    elif case == "reorder":
        data[0], data[1] = data[1], data[0]
    elif case == "unknown":
        data.insert(2, {"type": "future.event"})
    elif case in ("malformed", "oversized"):
        data.insert(2, ParsedEvent(case))
    elif case == "bad-usage":
        data[-1]["usage"].pop("input_tokens")
    elif case == "boolean-usage":
        data[-1]["usage"]["input_tokens"] = True
    elif case == "negative-usage":
        data[-1]["usage"]["input_tokens"] = -1
    elif case == "bad-id":
        data[0]["thread_id"] = "--last"
    elif case == "array":
        data.insert(2, [])
    elif case == "unknown-item":
        data[2]["item"]["type"] = "future.tool"
    assert classify(data).outcome == "protocol_error"


@pytest.mark.parametrize(
    "error, category",
    [
        ("quota exceeded", "usage_limit"),
        ("401 unauthorized", "auth"),
        ("permission denied", "permission_denied"),
        ("session not found", "resume_failed"),
        ("unexpected argument --bad", "cli_rejected_argument"),
    ],
)
def test_refusal_stops_without_retry_or_reset_guess(error: str, category: str) -> None:
    data = [*lines()[:2], {"type": "turn.failed", "error": {"message": error}}]
    r = classify(data, rc=1)
    assert r.outcome == "blocked" and r.blocked["category"] == category
    assert r.blocked["reset_at"] is None
    stderr = classify([], rc=1, stderr=error.encode())
    assert stderr.blocked["classification"] == "heuristic_stderr"


def test_error_event_or_error_item_cannot_be_hidden_by_completion() -> None:
    for error in (
        {"type": "error", "message": "transport disconnected"},
        {
            "type": "item.completed",
            "item": {"id": "e", "type": "error", "message": "transport disconnected"},
        },
    ):
        assert classify([*lines()[:2], error, *lines()[2:]]).outcome == "failed"
    assert classify(lines(), rc=2).outcome == "protocol_error"
    assert classify([], rc=2).outcome == "crashed"


def test_mismatched_resume_never_rebinds_new_thread() -> None:
    r = classify(lines(), resume="0199a213-81c0-7800-8aa1-bbab2a035a54")
    assert r.outcome == "blocked" and r.blocked["category"] == "resume_failed"
    assert r.session_id is None
    assert classify(lines(), resume=SESSION).outcome == "succeeded"


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({"timed_out": True}, "timed_out"),
        ({"stop_reason": "cancelled"}, "cancelled"),
        ({"stop_reason": "interrupted"}, "interrupted"),
        ({"group_exit_confirmed": False}, "outcome_unknown"),
        ({"spawn_error": "missing binary"}, "spawn_failed"),
    ],
)
def test_process_evidence_dominates_success(fields: dict[str, Any], expected: str) -> None:
    assert classify(lines(), **fields).outcome == expected
    mismatch = classify(lines(), resume="0199a213-81c0-7800-8aa1-bbab2a035a54", **fields)
    assert mismatch.outcome == expected and mismatch.session_id is None


def test_parser_discards_tool_payload_reasoning_and_unknown_model_claim() -> None:
    a = CodexAdapter(CodexSettings())
    for kind in ("reasoning", "command_execution", "mcp_tool_call", "file_change"):
        e = a.parse_event(
            json.dumps(
                {
                    "type": "item.completed",
                    "model": "fake-proof",
                    "item": {
                        "id": "i",
                        "type": kind,
                        "text": "private",
                        "arguments": "private",
                        "aggregated_output": "private",
                        "command": "private",
                    },
                }
            ).encode()
        )
        assert "private" not in json.dumps(e.data) and e.model is None
    for raw in (
        b"{",
        b"\xff",
        b"null",
        b"{}",
        b'{"n":' + b"9" * 5000 + b"}",
        b"[" * 2000 + b"0" + b"]" * 2000,
    ):
        assert a.parse_event(raw).kind == "malformed"


@pytest.mark.parametrize(
    "extra",
    [
        {"allowed_tools": ["Read"]},
        {"permission_mode": "acceptEdits"},
        {"strict_mcp_config": True},
        {"sandbox": "danger-full-access"},
        {"scenario": "success"},
        {"requested_model": "--oss"},
        {"requested_model": ""},
        {"requested_model": "x\x00"},
    ],
)
def test_codex_contract_refuses_claude_options_and_unsafe_values(extra: dict[str, Any]) -> None:
    with pytest.raises(BridgeError):
        parse_task_spec(spec(executor={"kind": "codex", **extra}))


def test_codex_defaults_do_not_change_legacy_canonical_executor() -> None:
    legacy = ExecutorSpec(kind="claude-code").model_dump(mode="json")
    parsed = parse_task_spec(spec(executor=legacy))
    assert parsed.executor.model_dump(mode="json") == legacy
    native = parse_task_spec(spec(executor={"kind": "codex"})).executor.model_dump(mode="json")
    assert native == {
        "kind": "codex",
        "requested_model": None,
        "sandbox": "workspace-write",
        "resume_on_repair": True,
    }


def test_fixture_provenance() -> None:
    p = json.loads((STREAM / "PROVENANCE.json").read_text())
    assert p["cli_version_captured"] is None
    assert sorted(p["files"]) == sorted(f.name for f in STREAM.glob("*.jsonl"))
