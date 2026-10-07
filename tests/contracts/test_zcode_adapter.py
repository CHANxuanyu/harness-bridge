"""Offline boundary contracts; native metadata != execution/permission qualification."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from harness_bridge.adapters.zcode import ZCodeAdapter
from harness_bridge.errors import BridgeError
from harness_bridge.models import ZCodeExecutorSpec, parse_task_spec
from harness_bridge.runner import ProcessOutcome
from tests.contracts.test_claude_adapter import packet
from tests.contracts.test_codex_adapter import context
from tests.unit.test_models import spec

SID = "sess_0199a213-81c0-7800-8aa1-bbab2a035a53"


def settings() -> ZCodeExecutorSpec:
    return ZCodeExecutorSpec(kind="zcode", provider_id="account:zai-individual-coding-plan")


def adapter(resume: str | None = None) -> ZCodeAdapter:
    a = ZCodeAdapter(settings())
    a.build_invocation(replace(packet(), max_turns=None), context(resume))
    return a


def stream() -> list[dict[str, Any]]:
    return [
        {
            "type": "zcode.session",
            "session_id": SID,
            "model": "GLM-5.3-Flash",
            "provider": settings().provider_id,
            "workspace": "/work/task",
            "permission_mode": "edit",
        },
        {"type": "zcode.started", "session_id": SID},
        {"type": "zcode.completed", "session_id": SID},
    ]


def test_invocation_frozen_stdin_no_secret_or_prompt_in_argv() -> None:
    inv = adapter().build_invocation(replace(packet(), max_turns=None), context(SID))
    assert inv.argv == ["/python", "-m", "harness_bridge.zcode_transport"]
    data = json.loads(inv.stdin)
    assert data["resume"] == SID and data["settings"]["permission_mode"] == "edit"
    assert "not-in-describe" not in json.dumps(inv.describe())
    assert data["mode"] == "mock" and data["workspace"] == "/work/task"


@pytest.mark.parametrize("mode,turns", [("live", None), ("live", 5), ("mock", 5)])
def test_live_and_numeric_turn_limits_refused(mode: str, turns: int | None) -> None:
    with pytest.raises(BridgeError):
        ZCodeAdapter(settings()).build_invocation(
            replace(packet(), max_turns=turns), replace(context(), mode=mode)
        )


@pytest.mark.parametrize("sid", ["latest", "sess_bad", SID.upper(), "", SID + "x"])
def test_invalid_resume_refused(sid: str) -> None:
    with pytest.raises(BridgeError):
        adapter(sid)


@pytest.mark.parametrize(
    "change",
    [
        {"requested_model": "GLM-5.3"},
        {"requested_model": "GLM-5.3-FlashX"},
        {"permission_mode": "yolo"},
        {"allowed_tools": ["Bash"]},
        {"provider_id": "custom-api"},
        {"sandbox": "workspace-write"},
    ],
)
def test_profile_rejects_silent_fallbacks_and_foreign_options(change: dict[str, Any]) -> None:
    d = spec()
    d["limits"] = {"max_turns_per_attempt": None}
    d["executor"] = {**settings().model_dump(), **change}
    with pytest.raises(BridgeError):
        parse_task_spec(d)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "order",
        "wrong-session",
        "model",
        "provider",
        "workspace",
        "mode",
        "unknown",
        "malformed-category",
    ],
)
def test_incomplete_or_mismatched_protocol_never_succeeds(mutation: str) -> None:
    a = adapter(SID)
    data = stream()
    if mutation == "missing":
        data.pop()
    elif mutation == "duplicate":
        data.append(data[-1])
    elif mutation == "order":
        data.reverse()
    elif mutation == "wrong-session":
        data[1]["session_id"] = "sess_0199a213-81c0-7800-8aa1-bbab2a035a54"
    elif mutation in ("model", "provider", "workspace"):
        data[0][mutation] = "wrong"
    elif mutation == "mode":
        data[0]["permission_mode"] = "yolo"
    elif mutation == "unknown":
        data.append({"type": "invented"})
    else:
        data.append({"type": "zcode.error", "category": []})
    events = [a.parse_event(json.dumps(x).encode()) for x in data]
    r = a.classify_completion(ProcessOutcome(returncode=0, group_exit_confirmed=True), events)
    assert r.outcome != "succeeded"


@pytest.mark.parametrize(
    "process,expected",
    [
        ({"group_exit_confirmed": False}, "outcome_unknown"),
        ({"timed_out": True}, "timed_out"),
        ({"stop_reason": "cancelled"}, "cancelled"),
        ({"returncode": 1}, "protocol_error"),
        ({}, "succeeded"),
    ],
)
def test_process_evidence_dominates_completion(process: dict[str, Any], expected: str) -> None:
    a = adapter(SID)
    outcome = replace(ProcessOutcome(returncode=0, group_exit_confirmed=True), **process)
    result = a.classify_completion(
        outcome, [a.parse_event(json.dumps(x).encode()) for x in stream()]
    )
    assert result.outcome == expected
    assert result.usage.get("cost_estimate_usd_reported") is None
