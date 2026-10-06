"""Conservative concurrency scopes and explicit local opt-in contract."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from harness_bridge.config import load_config
from harness_bridge.coordination import GoalSpec, parse_contract
from harness_bridge.dispatch import scopes_overlap
from harness_bridge.errors import BridgeError
from harness_bridge.policy import glob_match


@pytest.mark.parametrize(
    ("left", "right", "overlap"),
    [
        (["src/a/**"], ["src/b/**"], False),
        (["src/a.py"], ["src/b.py"], False),
        (["src/a"], ["src/a/b"], True),
        (["src/**"], ["src/a/**"], True),
        (["**/test.py"], ["src/a.py"], True),
        (["a*"], ["b*"], True),  # intentionally conservative wildcard proof
        (["src/*.py"], ["src/*.js"], True),
        (["src/a?.py"], ["docs/**"], False),
        (["src/a[0].py"], ["src/a[1].py"], False),  # [] are literals in our glob grammar
        (["Src/Foo.py"], ["src/foo.py"], True),
        (["cafe\u0301/**"], ["café/a.py"], True),
        (["src/a/**", "docs/**"], ["docs/a.md"], True),
        (["src/a/**", "tests/a/**"], ["src/b/**", "tests/b/**"], False),
    ],
)
def test_scope_proof_covers_paths_and_filesystem_aliases(
    left: list[str], right: list[str], overlap: bool
) -> None:
    assert scopes_overlap(left, right) is overlap
    assert scopes_overlap(right, left) is overlap


def test_disjoint_proof_never_allows_a_shared_matched_path_in_bounded_glob_corpus() -> None:
    patterns = ["a", "a/b", "b/*", "a/**", "**/a", "a?/*", "a*/b", "**", "b/a", "a/*/b"]
    paths = [
        "/".join(parts)
        for n in (1, 2, 3)
        for parts in itertools.product(("a", "b", "aa"), repeat=n)
    ]
    for left, right in itertools.combinations(patterns, 2):
        if not scopes_overlap([left], [right]):
            assert not any(glob_match(left, p) and glob_match(right, p) for p in paths)


@pytest.mark.parametrize("value", ["true", "0", "3", "2.0", '"2"'])
def test_parallel_configuration_rejects_unapproved_values(tmp_path: Path, value: str) -> None:
    (tmp_path / "config.toml").write_text(f"[execution]\nmax_parallel_per_project = {value}\n")
    with pytest.raises(BridgeError) as err:
        load_config(tmp_path)
    assert err.value.code == "INVALID_INPUT"


@pytest.mark.parametrize("body", ['execution = "parallel"', "[execution]\nmax_parallel = 2"])
def test_parallel_configuration_typos_do_not_silently_change_limits(
    tmp_path: Path, body: str
) -> None:
    (tmp_path / "config.toml").write_text(body)
    with pytest.raises(BridgeError):
        load_config(tmp_path)


def test_default_and_explicit_parallel_config_leave_live_gate_closed(tmp_path: Path) -> None:
    assert load_config(tmp_path).max_parallel_per_project == 1
    (tmp_path / "config.toml").write_text("[execution]\nmax_parallel_per_project = 2\n")
    config = load_config(tmp_path)
    assert config.max_parallel_per_project == 2
    assert not config.live_enabled and not config.hooks_and_permissions_reviewed


@pytest.mark.parametrize(
    "limits",
    [
        {"max_executor_turns": True},
        {"max_executor_turns": 0},
        {"max_executor_turns": 50001},
        {"max_executor_wall_seconds": 0},
        {"max_executor_wall_seconds": 8640001},
        {"max_executor_wall_seconds": float("nan")},
        {"max_executor_wall_seconds": float("inf")},
    ],
)
def test_invalid_aggregate_limits_fail_contract_validation(limits: dict[str, object]) -> None:
    with pytest.raises(BridgeError) as err:
        parse_contract(
            GoalSpec,
            {
                "schema_version": "1.0",
                "objective": "goal",
                "repo": {"path": "/repo"},
                "advisor": {"host": "codex"},
                "acceptance": ["passes"],
                **limits,
            },
        )
    assert err.value.code == "INVALID_INPUT"
