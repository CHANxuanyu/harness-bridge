from __future__ import annotations

from typing import Any

import pytest

from harness_bridge.cleanup import CleanupRequest
from harness_bridge.coordination import parse_contract
from harness_bridge.errors import BridgeError
from harness_bridge.integration import IntegrationSpec
from harness_bridge.models import TaskDefinition, VerificationCommand
from harness_bridge.planning import ChildPlan
from tests.conftest import Fixture
from tests.integration.test_goal_planning import plan
from tests.integration.test_integration_candidates import request


def test_old_plan_and_integration_normalization_preserves_digests(fx: Fixture) -> None:
    p = plan(fx, "old")
    assert parse_contract(ChildPlan, p).normalized() == {
        **p,
        "task": TaskDefinition.model_validate(p["task"]).model_dump(mode="json"),
    }
    spec = request(fx, "old-task")
    assert parse_contract(IntegrationSpec, spec).normalized() == {
        **spec,
        "verification": [
            VerificationCommand.model_validate(c).model_dump(mode="json")
            for c in spec["verification"]
        ],
    }


@pytest.mark.parametrize(
    "patch",
    [
        {"reason": ""},
        {"integration_id": ""},
        {"extra": True},
        {"reason": "x" * 4001},
    ],
)
def test_repair_request_rejects_invalid_binding(fx: Fixture, patch: dict[str, Any]) -> None:
    p = {
        **plan(fx, "repair"),
        "integration_repair": {
            "integration_id": "integration_fixed",
            "reason": "resolve conflict",
            **patch,
        },
    }
    with pytest.raises(BridgeError):
        parse_contract(ChildPlan, p)


def test_repair_cannot_combine_a_second_mutable_dependency_baseline(fx: Fixture) -> None:
    p = {
        **plan(fx, "repair", "a"),
        "integration_repair": {"integration_id": "integration_fixed", "reason": "resolve conflict"},
    }
    with pytest.raises(BridgeError):
        parse_contract(ChildPlan, p)


@pytest.mark.parametrize("case", ["policy", "empty", "duplicate", "digest", "path", "unknown"])
def test_cleanup_rejects_unbound_or_destructive_contracts(case: str) -> None:
    data: dict[str, Any] = {
        "schema_version": "1.0",
        "retention": "clean_worktrees_keep_refs_and_evidence",
        "resources": [{"resource_id": "integration_fixed", "fingerprint": "sha256:" + "0" * 64}],
    }
    if case == "policy":
        data["retention"] = "delete_everything"
    elif case == "empty":
        data["resources"] = []
    elif case == "duplicate":
        data["resources"] *= 2
    elif case == "digest":
        data["resources"][0]["fingerprint"] = "unbound"
    elif case == "path":
        data["resources"][0]["path"] = "/arbitrary/path"
    else:
        data["force"] = True
    with pytest.raises(BridgeError):
        parse_contract(CleanupRequest, data)
