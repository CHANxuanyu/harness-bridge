"""Shared test setup.

Every test runs with:
* a temporary HOME / XDG_STATE_HOME and an isolated git config with a test identity, so no real
  ``~/.claude``, ``~/.codex``, ZCode profile or user git configuration is read;
* model / provider / cloud environment variables removed;
* sentinel ``claude``, ``codex`` and ``zcode`` executables first on PATH record any invocation, so a
  test (or the code under test) accidentally spawning a real harness binary fails loudly (C11);
* a process-level network guard (socket connects outside AF_UNIX raise). This guards the test
  process only, not its subprocesses; it is not an OS firewall.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.demo_fixture import create_fixture_repo, make_task_spec, write_acceptance_script
from harness_bridge.service import Bridge

_SCRUB_PREFIXES = ("ANTHROPIC_", "CLAUDE", "CODEX", "ZCODE_", "ZAI_", "OPENAI_", "HBRIDGE_", "GIT_")
_SCRUB_EXACT = ("GITHUB_TOKEN", "GH_TOKEN", "AWS_BEARER_TOKEN_BEDROCK", "XDG_STATE_HOME")

SENTINEL = """#!/bin/sh
echo "$0 $*" >> "{marker}"
echo "sentinel: real harness binary must not be executed in tests" >&2
exit 97
"""


@pytest.fixture(autouse=True)
def isolated_env(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("env")
    home = root / "home"
    home.mkdir()
    for key in list(os.environ):
        if key.startswith(_SCRUB_PREFIXES) or key in _SCRUB_EXACT:
            monkeypatch.delenv(key, raising=False)
    gitconfig = root / "gitconfig"
    gitconfig.write_text(
        "[user]\n\tname = hbridge test\n\temail = test@hbridge.invalid\n"
        "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(root / "xdg-state"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    bin_dir = root / "sentinel-bin"
    bin_dir.mkdir()
    marker = root / "sentinel-invocations.log"
    for name in ("claude", "codex", "zcode"):
        exe = bin_dir / name
        exe.write_text(SENTINEL.format(marker=marker))
        exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    yield marker
    assert not marker.exists(), f"a real harness binary was invoked: {marker.read_text()}"


@pytest.fixture(autouse=True)
def network_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> Any:
        if self.family == socket.AF_UNIX:
            return real_connect(self, address)
        raise RuntimeError(f"network access attempted in tests: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setattr(
        socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net"))
    )


class Fixture:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.repo = create_fixture_repo(base / "repo")
        self.acceptance = write_acceptance_script(base / "acceptance" / "check_normalize.py")
        self.state_dir = base / "state"

    def spec(self, scenario: str = "success", **limits: Any) -> dict[str, Any]:
        return make_task_spec(self.repo, self.acceptance, scenario, limits=limits or None)

    def bridge(self) -> Bridge:
        return Bridge(self.state_dir)

    def cli(
        self,
        *args: str,
        check_ok: bool | None = True,
        env: dict[str, str] | None = None,
        timeout: float = 120,
    ) -> tuple[int, dict[str, Any]]:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness_bridge",
                "--state-dir",
                str(self.state_dir),
                "--json",
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            if check_ok is None:  # e.g. an injected crash: no receipt is expected
                return proc.returncode, {"stdout": proc.stdout, "stderr": proc.stderr}
            raise AssertionError(f"non-JSON CLI output: {proc.stdout!r} {proc.stderr!r}") from None
        if check_ok is not None:
            assert payload["ok"] is check_ok, (payload, proc.stderr)
        return proc.returncode, payload


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)
