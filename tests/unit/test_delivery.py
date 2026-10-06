"""Delivery branch input is a literal local ref, never an option or revision expression."""

import pytest
from pydantic import ValidationError

from harness_bridge.delivery import DeliveryRequest


@pytest.mark.parametrize(
    "branch",
    [
        "",
        "-flag",
        "HEAD",
        "head",
        "hbridge",
        "refs/heads/test",
        "hbridge/test",
        "HBRIDGE/test",
        "@{-1}",
        "name\ncreate other",
        "a b",
        "a:other",
        "a\\b",
    ],
)
def test_branch_contract_refuses_reserved_options_and_expressions(branch: str) -> None:
    with pytest.raises(ValidationError):
        DeliveryRequest(integration_id="integration_fixture", branch=branch)
