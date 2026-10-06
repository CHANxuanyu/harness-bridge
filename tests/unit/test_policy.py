from __future__ import annotations

import pytest

from harness_bridge.policy import (
    PathPolicy,
    glob_match,
    is_secret_path,
    redact_text,
    symlink_escapes,
    validate_relative_path,
)


@pytest.mark.parametrize(
    "pattern, path, expected",
    [
        ("src/**", "src/a.py", True),
        ("src/**", "src/deep/b/c.py", True),
        ("src/**", "src", False),
        ("src/**", "src2/a.py", False),  # prefix confusion
        ("src/**", "other/src/a.py", False),
        ("**/.env", ".env", True),
        ("**/.env", "a/b/.env", True),
        (".env.*", ".env.local", True),
        (".env.*", "sub/.env.local", False),
        ("tests/*.py", "tests/test_a.py", True),
        ("tests/*.py", "tests/sub/test_a.py", False),
        ("a?c", "abc", True),
        ("a?c", "a/c", False),
        ("docs/**/*.md", "docs/x.md", True),
        ("docs/**/*.md", "docs/a/b/x.md", True),
    ],
)
def test_glob_semantics(pattern: str, path: str, expected: bool) -> None:
    assert glob_match(pattern, path) is expected


@pytest.mark.parametrize("bad", ["", "/abs/**", "a/../b", "a//b", "a\\b", "src/**x", "./src"])
def test_invalid_globs_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        PathPolicy([bad], [])


@pytest.mark.parametrize("bad", ["", "/etc/passwd", "../x", "a/../../x", "a//b", "a\\b", "a\x00b"])
def test_relative_path_validation(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_relative_path(bad)


def test_policy_forbidden_wins_and_is_case_insensitive() -> None:
    policy = PathPolicy(["**"], [".github/**", "**/.env"])
    rules = {v.rule for v in policy.check_path(".GitHub/workflows/x.yml")}
    assert "forbidden_path" in rules
    assert {v.rule for v in policy.check_path("pkg/.ENV")} >= {"forbidden_path", "secret_path"}
    assert policy.check_path("src/ok.py") == []


def test_policy_outside_allowed_and_invalid_paths() -> None:
    policy = PathPolicy(["src/**"], [])
    assert [v.rule for v in policy.check_path("notes.txt")] == ["outside_allowed_paths"]
    assert [v.rule for v in policy.check_path("src/../etc/passwd")] == ["invalid_path"]


@pytest.mark.parametrize(
    "path, secret",
    [
        (".env", True),
        ("config/.env.production", True),
        (".env.example", False),
        ("keys/server.PEM", True),
        ("home/id_rsa", True),
        ("src/token.py", False),
        ("app/credentials.json", True),
    ],
)
def test_secret_paths(path: str, secret: bool) -> None:
    assert is_secret_path(path) is secret


@pytest.mark.parametrize(
    "link, target, escapes",
    [
        ("a/link", "../b.txt", False),
        ("a/link", "../../etc/passwd", True),
        ("link", "/etc/passwd", True),
        ("link", "sub/file", False),
        ("a/b/link", "../../../x", True),
    ],
)
def test_symlink_escape(link: str, target: str, escapes: bool) -> None:
    assert symlink_escapes(link, target) is escapes


def test_redaction_of_fake_credentials() -> None:
    fake_ant = "sk-ant-" + "A" * 30
    fake_gh = "ghp_" + "b" * 36
    text = (
        f"key={fake_ant}\nAuthorization: Bearer {'c' * 40}\n"
        f"GITHUB_TOKEN: {fake_gh}\nAWS AKIAABCDEFGHIJKLMNOP\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----\n"
        "password = hunter2hunter2\nordinary text stays\n"
    )
    out, n = redact_text(text)
    for leaked in (fake_ant, fake_gh, "c" * 40, "AKIAABCDEFGHIJKLMNOP", "MIIabc", "hunter2hunter2"):
        assert leaked not in out
    assert "ordinary text stays" in out
    assert n >= 6
