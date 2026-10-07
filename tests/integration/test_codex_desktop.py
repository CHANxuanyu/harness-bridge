"""Documented existing-thread URL, with a synthetic app and no actual UI/native harness."""

from __future__ import annotations

import json
import plistlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from harness_bridge import desktop
from harness_bridge.desktop import DesktopSessions
from harness_bridge.errors import BridgeError
from harness_bridge.models import sha256_digest
from harness_bridge.service import Bridge
from tests.conftest import Fixture
from tests.integration.test_desktop import SID, synthetic


def codex_fixture(
    fx: Fixture, b: Bridge, monkeypatch: pytest.MonkeyPatch, app_version: str = "26.930.31730"
) -> Path:
    app = fx.base / "ChatGPT.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "com.openai.codex",
                "CFBundleShortVersionString": app_version,
                "CFBundleURLTypes": [{"CFBundleURLSchemes": ["codex"]}],
            }
        )
    )
    binary = app / "Contents/codex-fixture"
    invocation = dict(b.store.get_attempt("att_fixture").invocation)
    invocation["argv"] = [str(binary)]
    with b.store.transaction() as cur:
        b.store.update_attempt(
            cur, "att_fixture", invocation=invocation, invocation_digest=sha256_digest(invocation)
        )
    monkeypatch.setattr(desktop, "CODEX_APP", app)
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    return binary


@pytest.mark.parametrize("app_version", ["26.930.31730", "26.930.51102"])
@pytest.mark.parametrize("exit_code", [0, 1])
def test_codex_only_opens_existing_uuid_and_replays_without_new_turn(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    app_version: str,
) -> None:
    b, tid = synthetic(fx, "codex")
    binary = codex_fixture(fx, b, monkeypatch, app_version)
    calls: list[list[str]] = []
    original = subprocess.run

    def run(argv: list[str], **kwargs: Any) -> Any:
        if argv[0] not in (str(binary), "/usr/bin/open"):
            return original(argv, **kwargs)
        calls.append(argv)
        assert kwargs["stdin"] == subprocess.DEVNULL
        if argv == [str(binary), "--version"]:
            return subprocess.CompletedProcess(argv, 0, b"codex-cli 0.160.0", b"")
        assert argv == ["/usr/bin/open", "-a", str(desktop.CODEX_APP), f"codex://threads/{SID}"]
        return subprocess.CompletedProcess(argv, exit_code, b"", b"private-value")

    monkeypatch.setattr(desktop.subprocess, "run", run)
    d = DesktopSessions(b)
    assert d.status(tid)["can_request_open"] and not calls
    task, attempts = b.store.get_task(tid), b.store.list_attempts(tid)
    result = d.open(tid, "open-codex")
    assert result["transport"] == "native_url" and result["desktop_visibility"] == "unverified"
    assert (result["status"] == "native_open_requested") == (exit_code == 0)
    assert d.open(tid, "another") == {**result, "replayed": True}
    assert (
        len(calls) == 2 and b.store.get_task(tid) == task and b.store.list_attempts(tid) == attempts
    )
    assert "private-value" not in json.dumps(b.store.list_events(tid))


@pytest.mark.parametrize("damage", ["wrong-id", "wrong-version", "wrong-scheme", "foreign-binary"])
def test_codex_app_preflight_refuses_changed_or_unbound_app(
    fx: Fixture,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    b, tid = synthetic(fx, "codex")
    binary = codex_fixture(fx, b, monkeypatch)
    plist = desktop.CODEX_APP / "Contents/Info.plist"
    info = plistlib.loads(plist.read_bytes())
    if damage == "wrong-id":
        info["CFBundleIdentifier"] = "another-app"
    if damage == "wrong-version":
        info["CFBundleShortVersionString"] = "unvalidated"
    if damage == "wrong-scheme":
        info["CFBundleURLTypes"] = []
    plist.write_bytes(plistlib.dumps(info))
    calls: list[list[str]] = []
    original = subprocess.run
    if damage == "foreign-binary":
        invocation = dict(b.store.get_attempt("att_fixture").invocation)
        binary = fx.base / "foreign-codex-fixture"
        invocation["argv"] = [str(binary)]
        with b.store.transaction() as cur:
            b.store.update_attempt(
                cur,
                "att_fixture",
                invocation=invocation,
                invocation_digest=sha256_digest(invocation),
            )

    def run(argv: list[str], **kwargs: Any) -> Any:
        if argv[0] == str(binary):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, b"codex-cli 0.160.0", b"")
        assert argv[0] != "/usr/bin/open"
        return original(argv, **kwargs)

    monkeypatch.setattr(desktop.subprocess, "run", run)
    with pytest.raises(BridgeError):
        DesktopSessions(b).open(tid, "refused")
    assert len(calls) == (1 if damage == "foreign-binary" else 0)
