from __future__ import annotations

from harness_bridge.adapters.fake import FakeExecutorAdapter
from harness_bridge.runner import ProcessOutcome
from harness_bridge.state import AttemptOutcome


def finished(rc: int = 0, **kw: object) -> ProcessOutcome:
    out = ProcessOutcome(pid=1, pgid=1, returncode=rc, group_exit_confirmed=True)
    for k, v in kw.items():
        setattr(out, k, v)
    return out


def classify(lines: list[bytes], process: ProcessOutcome) -> tuple[AttemptOutcome, str]:
    a = FakeExecutorAdapter("success")
    events = [a.parse_event(line) for line in lines]
    r = a.classify_completion(process, events)
    return r.outcome, r.reason


START = b'{"type":"start","session_id":"fake-1","model":"fake-executor"}'
OK = b'{"type":"result","status":"success","summary":"done","tests_reported":"passed"}'


def test_success() -> None:
    assert classify([START, OK], finished())[0] is AttemptOutcome.SUCCEEDED


def test_missing_final_result_is_protocol_error() -> None:
    assert classify([START], finished())[0] is AttemptOutcome.PROTOCOL_ERROR


def test_malformed_output_is_protocol_error() -> None:
    outcome, reason = classify([START, b"not json", b'{"type": "result", "status": '], finished())
    assert outcome is AttemptOutcome.PROTOCOL_ERROR and "malformed" in reason


def test_nonzero_exit_without_result_is_crash() -> None:
    assert classify([START], finished(rc=3))[0] is AttemptOutcome.CRASHED


def test_success_result_with_nonzero_exit_is_inconsistent() -> None:
    assert classify([START, OK], finished(rc=2))[0] is AttemptOutcome.PROTOCOL_ERROR


def test_duplicate_results_are_protocol_error() -> None:
    assert classify([START, OK, OK], finished())[0] is AttemptOutcome.PROTOCOL_ERROR


def test_structured_blocking_errors() -> None:
    perm = b'{"type":"result","status":"error","error":{"category":"permission_denied"}}'
    assert classify([START, perm], finished(rc=1))[0] is AttemptOutcome.BLOCKED
    other = b'{"type":"result","status":"error","error":{"category":"compile_error"}}'
    assert classify([START, other], finished(rc=1))[0] is AttemptOutcome.FAILED


def test_unknown_events_are_tolerated() -> None:
    a = FakeExecutorAdapter("success")
    ev = a.parse_event(b'{"type":"telemetry","x":1}')
    assert ev.kind == "unknown" and ev.raw_type == "telemetry"
    assert classify([START, b'{"type":"telemetry"}', OK], finished())[0] is (
        AttemptOutcome.SUCCEEDED
    )


def test_process_level_outcomes_dominate() -> None:
    assert classify([START, OK], finished(group_exit_confirmed=False))[0] is (
        AttemptOutcome.OUTCOME_UNKNOWN
    )
    assert classify([START, OK], finished(timed_out=True))[0] is AttemptOutcome.TIMED_OUT
    assert classify([START, OK], finished(stop_reason="cancelled"))[0] is AttemptOutcome.CANCELLED
    spawn = ProcessOutcome(spawn_error="FileNotFoundError", group_exit_confirmed=True)
    assert classify([], spawn)[0] is AttemptOutcome.SPAWN_FAILED
