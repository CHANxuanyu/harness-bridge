from __future__ import annotations

import copy
from typing import Any

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.models import parse_review, parse_task_spec

BASE: dict[str, Any] = {
    "schema_version": "1.0",
    "goal": "do the thing",
    "repo": {"path": "/tmp/repo", "base_ref": "HEAD"},
    "allowed_paths": ["src/**"],
    "verification": [
        {"id": "t", "argv": ["python", "-V"], "timeout_seconds": 5, "trust": "repository-tests"}
    ],
    "executor": {"kind": "fake", "scenario": "success"},
}


def spec(**patch: Any) -> dict[str, Any]:
    out = copy.deepcopy(BASE)
    out.update(patch)
    return out


def test_valid_spec_gets_conservative_defaults() -> None:
    s = parse_task_spec(spec())
    assert s.limits.max_attempts == 3
    assert s.limits.max_repair_cycles == 2
    assert ".env" in s.forbidden_paths
    assert s.executor.requested_model == "claude-opus-5-5"


@pytest.mark.parametrize(
    "patch, fragment",
    [
        ({"surprise": 1}, "surprise"),
        ({"schema_version": "2.0"}, "schema_version"),
        ({"limits": {"max_attempts": -1}}, "max_attempts"),
        ({"limits": {"max_attempts": 2, "max_repair_cycles": 2}}, "max_repair_cycles"),
        ({"repo": {"path": "relative/path"}}, "absolute"),
        ({"repo": {"path": "/tmp/r", "base_ref": "--upload-pack=x"}}, "base_ref"),
        ({"allowed_paths": ["../outside/**"]}, "allowed_paths"),
        ({"allowed_paths": ["/etc/**"]}, "allowed_paths"),
        ({"allowed_paths": []}, "allowed_paths"),
        ({"executor": {"kind": "fake", "scenario": "nope"}}, "scenario"),
        ({"executor": {"kind": "claude-code", "scenario": "success"}}, "scenario"),
        ({"executor": {"kind": "claude-code", "allowed_tools": ["Bash"]}}, "Bash"),
        ({"executor": {"kind": "claude-code", "allowed_tools": ["Bash(*)"]}}, "Bash"),
        (
            {"executor": {"kind": "claude-code", "permission_mode": "bypassPermissions"}},
            "permission",
        ),
        ({"executor": {"kind": "other"}}, "kind"),
    ],
)
def test_invalid_specs_are_rejected(patch: dict[str, Any], fragment: str) -> None:
    with pytest.raises(BridgeError) as exc:
        parse_task_spec(spec(**patch))
    assert exc.value.code == "INVALID_INPUT"
    assert fragment in exc.value.message


def test_verification_rules() -> None:
    dup = spec(verification=BASE["verification"] * 2)
    with pytest.raises(BridgeError, match="unique"):
        parse_task_spec(dup)
    optional_only = copy.deepcopy(BASE["verification"])
    optional_only[0]["required"] = False
    with pytest.raises(BridgeError, match="required"):
        parse_task_spec(spec(verification=optional_only))
    bad_cwd = copy.deepcopy(BASE["verification"])
    bad_cwd[0]["cwd"] = "../up"
    with pytest.raises(BridgeError, match="cwd"):
        parse_task_spec(spec(verification=bad_cwd))
    nul = copy.deepcopy(BASE["verification"])
    nul[0]["argv"] = ["python", "a\x00b"]
    with pytest.raises(BridgeError, match="NUL"):
        parse_task_spec(spec(verification=nul))


def test_scoped_bash_pattern_is_allowed() -> None:
    s = parse_task_spec(
        spec(executor={"kind": "claude-code", "allowed_tools": ["Bash(python -m pytest:*)"]})
    )
    assert s.executor.allowed_tools == ["Bash(python -m pytest:*)"]


REVIEW = {
    "schema_version": "1.0",
    "task_id": "t",
    "attempt_id": "a",
    "task_version": 1,
    "snapshot_digest": "sha256:x",
    "verdict": "approve",
    "idempotency_key": "k",
}


def test_review_contract() -> None:
    assert parse_review(REVIEW).verdict == "approve"
    with pytest.raises(BridgeError, match="finding"):
        parse_review({**REVIEW, "verdict": "changes_requested"})
    with pytest.raises(BridgeError, match="verdict"):
        parse_review({**REVIEW, "verdict": "merge-it"})
    with pytest.raises(BridgeError):
        parse_review({**REVIEW, "extra": True})
    with pytest.raises(BridgeError, match="schema_version"):
        parse_review({**REVIEW, "schema_version": "0.9"})
