"""Offline contract tests for the Claude Code adapter.

Evidence: synthetic / docs-derived fixtures (see tests/fixtures/claude_stream/PROVENANCE.json)
and captured ``claude --help`` text of CLI 2.1.291. Real captured streams from the bounded
live smokes of 2026-10-06 are covered separately, as redacted regression samples, in
tests/contracts/test_claude_adapter_live.py (see tests/fixtures/claude_stream_live/).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from harness_bridge.adapters.base import InvocationContext, TaskPacket
from harness_bridge.adapters.claude_code import (
    ClaudeCodeAdapter,
    ClaudeSettings,
    check_forbidden,
    preflight,
)
from harness_bridge.config import BridgeConfig, evaluate_live_gate
from harness_bridge.errors import BridgeError
from harness_bridge.runner import ProcessOutcome, StreamCapture
from harness_bridge.state import AttemptOutcome

FIX = Path(__file__).parents[1] / "fixtures"
STREAM = FIX / "claude_stream"
MODEL = "claude-opus-5-5"
SESSION = "6c1f0c8e-1111-4222-8333-444455556666"


def adapter(**kw: object) -> ClaudeCodeAdapter:
    settings = {
        "requested_model": MODEL,
        "max_turns": 20,
        "permission_mode": "acceptEdits",
        "allowed_tools": ("Read", "Edit", "Bash(python -m unittest:*)"),
        "strict_mcp_config": True,
    }
    settings.update(kw)
    return ClaudeCodeAdapter(ClaudeSettings(**settings))  # type: ignore[arg-type]


def packet(kind: str = "initial", feedback: list[dict[str, str]] | None = None) -> TaskPacket:
    return TaskPacket(
        task_id="tsk_1",
        attempt_id="att_1",
        attempt_seq=1 if kind == "initial" else 2,
        attempt_kind=kind,
        goal="Implement normalize_tags",
        requirements=["Preserve the order of first occurrences"],
        allowed_paths=["tagnorm/**"],
        forbidden_paths=[".env"],
        verification=[
            {
                "id": "t",
                "argv": ["python", "-m", "unittest"],
                "required": True,
                "trust": "repository-tests",
            }
        ],
        max_turns=20,
        feedback=feedback,
    )


def ctx(resume: str | None = None) -> InvocationContext:
    return InvocationContext(
        worktree="/w/tsk_1",
        mode="live",
        python_executable="/usr/bin/python3",
        base_env={"PATH": "/usr/bin", "HOME": "/home/u"},
        executor_binary="/opt/claude/bin/claude",
        resume_session_id=resume,
    )


# --- A01: command construction -------------------------------------------------------------


def test_a01_command_is_exact_bounded_and_shell_free(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_process(*a: object, **k: object) -> None:
        raise AssertionError("build_invocation must not start processes")

    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.setattr(subprocess, "run", no_process)
    inv = adapter().build_invocation(packet(), ctx())
    assert inv.argv == [
        "/opt/claude/bin/claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        MODEL,
        "--max-turns",
        "20",
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "Read,Edit,Bash(python -m unittest:*)",
        "--strict-mcp-config",
    ]
    for banned in (
        "--bare",
        "--dangerously-skip-permissions",
        "--continue",
        "-c",
        "bypassPermissions",
    ):
        assert banned not in inv.argv
    assert inv.cwd == "/w/tsk_1"
    prompt = inv.stdin.decode()
    assert "Implement normalize_tags" in prompt and "Preserve the order" in prompt
    assert all("Implement normalize_tags" not in a for a in inv.argv)  # task text via stdin only
    assert inv.requested_model == MODEL and inv.resume_session_id is None
    assert inv.describe()["env_names"] == ["HOME", "PATH"]


def test_a01_resume_is_explicit_and_feedback_is_in_prompt() -> None:
    fb = [
        {"severity": "blocking", "explanation": "sorted output", "requested_change": "keep order"}
    ]
    inv = adapter().build_invocation(packet("repair", fb), ctx(resume=SESSION))
    assert inv.argv[-2:] == ["--resume", SESSION]
    assert "sorted output" in inv.stdin.decode() and "keep order" in inv.stdin.decode()
    fresh = adapter().build_invocation(packet("repair", fb), ctx())
    assert "--resume" not in fresh.argv
    assert any("new session" in n for n in fresh.notes)


def test_a01_rejects_comma_in_tool_and_forbidden_flags() -> None:
    with pytest.raises(BridgeError):
        adapter(allowed_tools=("Bash(a,b)",)).build_invocation(packet(), ctx())
    for bad in ("--bare", "--dangerously-skip-permissions", "-c", "bypassPermissions"):
        with pytest.raises(BridgeError) as exc:
            check_forbidden(["claude", "-p", bad])
        assert exc.value.code == "PREFLIGHT_FAILED"


def test_a01_without_model_pin_omits_flag() -> None:
    inv = adapter(requested_model=None).build_invocation(packet(), ctx())
    assert "--model" not in inv.argv


# --- A02/A03/A04: parsing and classification ---------------------------------------------------


def classify(
    name: str,
    *,
    rc: int = 0,
    stderr: bytes = b"",
    resume: str | None = None,
    model: str = MODEL,
    session: str = SESSION,
):  # type: ignore[no-untyped-def]
    a = adapter()
    a.build_invocation(packet("repair" if resume else "initial"), ctx(resume=resume))
    text = (STREAM / name).read_text().replace("__SESSION_ID__", session)
    text = text.replace("__MODEL__", model)
    events = [a.parse_event(line.encode()) for line in text.splitlines()]
    err = StreamCapture(4096, 4096)
    err.feed(stderr)
    proc = ProcessOutcome(pid=1, pgid=1, returncode=rc, group_exit_confirmed=True, stderr=err)
    return a.classify_completion(proc, events)


def test_a02_fixture_provenance_is_honest() -> None:
    prov = json.loads((STREAM / "PROVENANCE.json").read_text())
    assert prov["cli_version_captured"] is None
    files = sorted(p.name for p in STREAM.glob("*.jsonl"))
    assert files == sorted(prov["files"])
    for meta in prov["files"].values():
        assert meta["provenance"] in ("synthetic", "docs-derived")


def test_a02_success_stream() -> None:
    r = classify("success.jsonl")
    assert r.outcome is AttemptOutcome.SUCCEEDED
    assert r.session_id == SESSION and r.observed_model == MODEL
    assert r.executor_reported["model_pin"] == "satisfied"
    assert r.executor_reported["num_turns"] == 3
    assert r.usage["input_tokens_reported"] == 2400
    assert r.usage["cache_read_tokens_reported"] == 1800
    assert r.usage["cost_estimate_usd_reported"] == 0.0123
    assert r.usage["model_calls_made_by_test"] is None
    assert r.protocol["result_seen"] and r.protocol["malformed_lines"] == 0


def test_a02_assistant_content_is_not_retained() -> None:
    a = adapter()
    line = (STREAM / "success.jsonl").read_text().splitlines()[1]
    ev = a.parse_event(line.encode())
    assert ev.kind == "message" and "I will edit" not in json.dumps(ev.data)


@pytest.mark.parametrize(
    "name, outcome",
    [
        ("max_turns.jsonl", AttemptOutcome.FAILED),
        ("error_during_execution.jsonl", AttemptOutcome.FAILED),
        ("missing_result.jsonl", AttemptOutcome.PROTOCOL_ERROR),
        ("duplicate_result.jsonl", AttemptOutcome.PROTOCOL_ERROR),
        ("session_id_changed.jsonl", AttemptOutcome.PROTOCOL_ERROR),
        ("unknown_terminal_subtype.jsonl", AttemptOutcome.PROTOCOL_ERROR),
    ],
)
def test_a02_terminal_classification(name: str, outcome: AttemptOutcome) -> None:
    assert classify(name).outcome is outcome


def test_a03_unknown_events_and_missing_usage() -> None:
    r = classify("unknown_events_no_usage.jsonl")
    assert r.outcome is AttemptOutcome.SUCCEEDED
    assert "brand_new_event_type" in r.protocol["unknown_types"]
    assert r.usage["input_tokens_reported"] is None
    assert r.usage["cost_estimate_usd_reported"] is None
    assert r.usage["source"] == "not_observed"


def test_a04_permission_denials_block_structurally() -> None:
    r = classify("permission_denied.jsonl", rc=1)
    assert r.outcome is AttemptOutcome.BLOCKED
    assert r.blocked == {
        "category": "permission_denied",
        "classification": "structured",
        "tools": ["Bash"],
        "reset_at": None,
    }


def test_a04_rate_limit_text_is_only_heuristic_and_invents_no_reset() -> None:
    r = classify("api_error_rate_limit.jsonl", rc=1)
    assert r.outcome is AttemptOutcome.BLOCKED
    assert r.blocked is not None
    assert r.blocked["classification"] == "heuristic" and r.blocked["reset_at"] is None


def test_a04_budget_flag_stop_blocks() -> None:
    r = classify("max_budget.jsonl", rc=1)
    assert r.outcome is AttemptOutcome.BLOCKED and r.blocked is not None
    assert r.blocked["category"] == "budget_limit"


def test_stderr_only_provider_error_without_result() -> None:
    r = classify("missing_result.jsonl", rc=1, stderr=b"Error: Invalid API key - please run /login")
    assert r.outcome is AttemptOutcome.BLOCKED and r.blocked is not None
    assert r.blocked["hint"] == "auth" and r.blocked["classification"] == "heuristic"
    plain = classify("missing_result.jsonl", rc=2, stderr=b"segfault-ish")
    assert plain.outcome is AttemptOutcome.CRASHED


def test_model_mismatch_is_reported_not_hidden() -> None:
    r = classify("model_mismatch.jsonl")
    assert r.outcome is AttemptOutcome.SUCCEEDED
    assert r.observed_model == "claude-other-model"
    assert r.executor_reported["model_pin"] == "mismatch"


def test_resume_must_be_confirmed_by_output() -> None:
    ok = classify("success.jsonl", resume=SESSION)
    assert ok.outcome is AttemptOutcome.SUCCEEDED
    bad = classify("resume_new_session.jsonl", resume=SESSION)
    assert bad.outcome is AttemptOutcome.BLOCKED and bad.blocked is not None
    assert bad.blocked["category"] == "resume_failed"
    assert bad.blocked["requested_session_id"] == SESSION


def test_malformed_lines_are_counted() -> None:
    a = adapter()
    assert a.parse_event(b"{not json").kind == "malformed"
    assert a.parse_event(b"[1,2]").kind == "malformed"
    assert a.parse_event(b"\xff\xfe").kind == "malformed"


# --- S04: preflight ---------------------------------------------------------------------------


def listed_flags() -> set[str]:
    import re

    text = (FIX / "claude_help_2.1.291.txt").read_text()
    return set(re.findall(r"(?<![\w-])(--[a-zA-Z][\w-]*|-[a-zA-Z])\b", text))


def test_s04_preflight_reports_unlisted_max_turns_for_cli_2_1_291() -> None:
    flags = listed_flags()
    assert {
        "-p",
        "--output-format",
        "--verbose",
        "--model",
        "--permission-mode",
        "--allowedTools",
        "--strict-mcp-config",
        "--resume",
    } <= flags
    inv = adapter().build_invocation(packet(), ctx())
    with pytest.raises(BridgeError) as exc:
        preflight(adapter(), inv.argv, listed_flags=flags, allow_unlisted=())
    assert exc.value.details["pending_local_confirmation"] == ["--max-turns"]
    ok = preflight(adapter(), inv.argv, listed_flags=flags, allow_unlisted=("--max-turns",))
    assert ok["flag_evidence"]["--max-turns"]["status"] == "confirmed_locally_by_user"


# --- --max-turns capability judgement: docs vs local help vs local confirmation ---------------


def test_help_absence_is_not_treated_as_unsupported() -> None:
    """CLI reference: --help does not list every flag; absence there is not evidence of absence."""
    inv = adapter().build_invocation(packet(), ctx())
    with pytest.raises(BridgeError) as exc:
        preflight(adapter(), inv.argv, listed_flags=listed_flags(), allow_unlisted=())
    ev = exc.value.details["flag_evidence"]["--max-turns"]
    assert ev["official_docs"] == {
        "declared": True,
        "source": "https://code.claude.com/docs/en/cli-reference",
        "checked": "2026-10-06",
    }
    assert ev["local_help"] == "not_listed"
    assert ev["local_confirmation"] == "none"
    assert ev["status"] == "documented_pending_local_confirmation"  # unknown, not unsupported
    assert ev["usable_for_live"] is False  # existing protection kept: held until confirmed
    msg = exc.value.message
    assert "not evidence of absence" in msg and "unknown" in msg
    assert "unsupported" not in msg.lower()
    # every other adapter flag is listed by the captured 2.1.291 help text
    others = {f: e["status"] for f, e in exc.value.details["flag_evidence"].items()}
    others.pop("--max-turns")
    assert set(others.values()) == {"listed_in_local_help"}


def test_documentation_alone_never_marks_a_flag_usable() -> None:
    from harness_bridge.adapters.claude_code import flag_evidence

    ev = flag_evidence(["--max-turns"], listed_flags=set(), confirmed=())
    assert ev["--max-turns"]["official_docs"]["declared"] is True
    assert ev["--max-turns"]["usable_for_live"] is False
    unchecked = flag_evidence(["--max-turns"], listed_flags=None, confirmed=())
    assert unchecked["--max-turns"]["local_help"] == "not_checked"
    assert unchecked["--max-turns"]["usable_for_live"] is False


def test_undocumented_unlisted_flag_is_unknown_and_held() -> None:
    argv = ["/opt/claude", "-p", "--some-future-flag", "x"]
    with pytest.raises(BridgeError) as exc:
        preflight(adapter(), argv, listed_flags=listed_flags(), allow_unlisted=())
    ev = exc.value.details["flag_evidence"]["--some-future-flag"]
    assert ev["status"] == "undocumented_and_unlisted" and ev["official_docs"]["declared"] is False
    assert exc.value.details["pending_local_confirmation"] == ["--some-future-flag"]


def test_confirmation_is_per_flag_and_forbidden_flags_stay_forbidden() -> None:
    inv = adapter().build_invocation(packet(), ctx())
    with pytest.raises(BridgeError) as exc:  # confirming a different flag does not help
        preflight(adapter(), inv.argv, listed_flags=listed_flags(), allow_unlisted=("--model",))
    assert exc.value.details["pending_local_confirmation"] == ["--max-turns"]
    with pytest.raises(BridgeError) as exc:  # a confirmation cannot whitelist a forbidden flag
        preflight(
            adapter(),
            [*inv.argv, "--bare"],
            listed_flags=listed_flags(),
            allow_unlisted=("--max-turns", "--bare"),
        )
    assert "forbidden" in exc.value.message


@pytest.mark.parametrize("entry", ["*", "--*", "all", "", "--max-turns=5", "max-turns"])
def test_no_global_preflight_bypass_in_config(tmp_path: Path, entry: str) -> None:
    from harness_bridge.config import load_config

    (tmp_path / "config.toml").write_text(f'[live]\nallow_unlisted_flags = ["{entry}"]\n')
    with pytest.raises(BridgeError) as exc:
        load_config(tmp_path)
    assert exc.value.code == "INVALID_INPUT"


@pytest.mark.parametrize(
    "stderr",
    [
        b"error: unknown option '--max-turns'\n",
        b"Error: Unknown option: --max-turns",
        b"unrecognized arguments: --max-turns",
    ],
)
def test_cli_rejecting_a_flag_stops_the_attempt(stderr: bytes) -> None:
    a = adapter()
    a.build_invocation(packet(), ctx())
    err = StreamCapture(4096, 4096)
    err.feed(stderr)
    proc = ProcessOutcome(pid=1, pgid=1, returncode=1, group_exit_confirmed=True, stderr=err)
    r = a.classify_completion(proc, [])
    assert r.outcome is AttemptOutcome.BLOCKED and r.blocked is not None
    assert r.blocked["category"] == "cli_rejected_argument"
    assert r.blocked["flag"] == "--max-turns"
    assert "never removes a limit flag" in r.blocked["next_step"]


def test_s04_api_env_closes_live_gate_without_echoing_values() -> None:
    secret = "sk-ant-" + "Z" * 30
    cfg = BridgeConfig(live_enabled=True, hooks_and_permissions_reviewed=True)
    gate = evaluate_live_gate(
        mode="live", allow_model_usage=True, config=cfg, env={"ANTHROPIC_API_KEY": secret}
    )
    assert not gate.open and gate.api_env_present == ["ANTHROPIC_API_KEY"]
    assert secret not in json.dumps(gate.to_dict())
    clean = evaluate_live_gate(mode="live", allow_model_usage=True, config=cfg, env={})
    assert clean.open
    for marker in ("CLAUDE_CODE_REMOTE", "CLAUDECODE"):
        assert not evaluate_live_gate(
            mode="live", allow_model_usage=True, config=cfg, env={marker: "1"}
        ).open
    unreviewed = BridgeConfig(live_enabled=True)
    assert not evaluate_live_gate(
        mode="live", allow_model_usage=True, config=unreviewed, env={}
    ).open
