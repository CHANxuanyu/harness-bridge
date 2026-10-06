"""Strict integration decision and command admission contracts."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from harness_bridge.integration import IntegrationSpec
from harness_bridge.integration_checks import IntegrationReview


@pytest.mark.parametrize(
    "extra",
    [
        {"verdict": "changes_requested"},
        {"verdict": "blocked"},
        {"verdict": "approve", "findings": [{"severity": "blocking", "explanation": "broken"}]},
        {"verdict": "approve", "findings": [{"severity": "major", "explanation": "broken"}]},
        {"verification_run_id": ""},
        {"unexpected": "ignored data must be rejected"},
    ],
)
def test_review_rejects_unbound_or_inconsistent_decisions(extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        IntegrationReview.model_validate(
            {
                "schema_version": "1.0",
                "integration_id": "integration_fixture",
                "verification_run_id": "ivr_fixture",
                "snapshot_digest": "sha256:fixture",
                "verdict": "approve",
                "findings": [],
                "idempotency_key": "review",
                **extra,
            }
        )


@pytest.mark.parametrize(
    "argv",
    [["codex", "exec"], ["zcode"], ["claude"], ["check", "ANTHROPIC_API_KEY=fixture-secret"]],
)
def test_harness_or_credential_commands_rejected_before_freezing(argv: list[str]) -> None:
    with pytest.raises(ValidationError):
        IntegrationSpec.model_validate(
            {
                "schema_version": "1.0",
                "task_ids": ["task_fixture"],
                "verification": [
                    {
                        "id": "check",
                        "argv": argv,
                        "timeout_seconds": 1,
                        "trust": "external-acceptance",
                    }
                ],
            }
        )
