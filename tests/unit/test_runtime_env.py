"""Environment profiles: prod compatibility, dev/test boundaries, alias refusal, build identity."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from harness_bridge import runtime_env
from harness_bridge.config import default_state_dir
from harness_bridge.errors import BridgeError
from harness_bridge.workbench.harness import WorkbenchConfig


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stand-in for the account's real home (protected directories derive from it)."""
    home = tmp_path / "real-home"
    (home / ".local" / "state" / "harness-bridge").mkdir(parents=True)
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    monkeypatch.setattr(runtime_env, "real_home", lambda: home)
    return home


def test_prod_default_is_the_historical_path() -> None:
    env = {"XDG_STATE_HOME": "/x/state"}
    assert default_state_dir(env) == Path("/x/state/harness-bridge")
    assert default_state_dir({}) == Path(os.path.expanduser("~")) / ".local/state/harness-bridge"
    assert default_state_dir({"HBRIDGE_STATE_DIR": "~/s"}) == Path(os.path.expanduser("~/s"))
    assert default_state_dir({"HBRIDGE_ENV": "prod", "XDG_STATE_HOME": "/x"}) == Path(
        "/x/harness-bridge"
    )
    assert runtime_env.profile_name({}) == ("prod", "default")


def test_dev_default_and_alias_refusal(fake_home: Path, tmp_path: Path) -> None:
    env = {"HBRIDGE_ENV": "dev", "XDG_STATE_HOME": str(fake_home / ".local/state")}
    dev = default_state_dir(env)
    assert dev == fake_home / ".local/state/harness-bridge-dev"
    assert runtime_env.resolve(dev, env).name == "dev"
    prod = fake_home / ".local/state/harness-bridge"
    alias = tmp_path / "looks-different"
    alias.symlink_to(prod)
    for target in (prod, alias, prod / "nested", fake_home / ".local/state"):
        with pytest.raises(BridgeError, match="prod state"):
            runtime_env.resolve(target, env)
    with pytest.raises(BridgeError):
        runtime_env.profile_name({"HBRIDGE_ENV": "staging"})


def _test_env(root: Path, **extra: str) -> dict[str, str]:
    return {
        "HBRIDGE_ENV": "test",
        "HBRIDGE_TEST_ROOT": str(root),
        "HOME": str(root / "home"),
        **extra,
    }


def test_test_profile_requires_everything_inside_the_root(fake_home: Path, tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    (root / "home").mkdir(parents=True)
    env = _test_env(root)
    assert default_state_dir(env) == root / "state"
    profile = runtime_env.resolve(root / "state", env)
    assert (profile.name, profile.native_env) == ("test", "isolated")
    with pytest.raises(BridgeError, match="HBRIDGE_TEST_ROOT"):
        default_state_dir({"HBRIDGE_ENV": "test"})
    with pytest.raises(BridgeError, match="inside the test root"):
        runtime_env.resolve(tmp_path / "elsewhere", env)
    escape = root / "escape"
    escape.symlink_to(tmp_path / "outside")
    (tmp_path / "outside").mkdir()
    with pytest.raises(BridgeError, match="inside the test root"):
        runtime_env.resolve(escape / "state", env)
    with pytest.raises(BridgeError, match="HOME"):
        runtime_env.resolve(root / "state", _test_env(root, HOME=str(fake_home)))
    with pytest.raises(BridgeError, match="CODEX_HOME"):
        runtime_env.resolve(root / "state", _test_env(root, CODEX_HOME=str(fake_home / ".codex")))
    with pytest.raises(BridgeError, match="real home"):
        runtime_env.resolve(fake_home / "x" / "state", _test_env(fake_home))
    inside_claude = fake_home / ".claude" / "sandbox"
    inside_claude.mkdir()
    with pytest.raises(BridgeError, match="overlaps"):
        runtime_env.resolve(inside_claude / "state", _test_env(inside_claude))


def test_test_profile_binaries_desktop_and_discovery(fake_home: Path, tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    (root / "home").mkdir(parents=True)
    (root / "bin").mkdir()
    env = _test_env(root)
    inside = WorkbenchConfig(
        binaries={"codex": str(root / "bin/codex")},
        app_dirs=(str(root / "Applications"),),
        opener=str(root / "bin/open"),
    )
    profile, checked = runtime_env.workbench_profile(root / "state", inside, env)
    assert profile.name == "test" and checked.discover is False
    for config in (
        WorkbenchConfig(
            binaries={"codex": "/usr/bin/codex"}, app_dirs=inside.app_dirs, opener=inside.opener
        ),
        WorkbenchConfig(binaries=inside.binaries, opener=inside.opener),  # /Applications
        WorkbenchConfig(binaries=inside.binaries, app_dirs=inside.app_dirs),  # /usr/bin/open
    ):
        with pytest.raises(BridgeError, match="test profile"):
            runtime_env.workbench_profile(root / "state", config, env)


def test_root_lock_is_exclusive_alias_proof_and_refuses_nesting(tmp_path: Path) -> None:
    root = tmp_path / "a"
    root.mkdir()
    lock = runtime_env.TestRootLock(root)
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    for candidate in (root, alias):
        with pytest.raises(BridgeError, match="already using"):
            runtime_env.TestRootLock(Path(os.path.realpath(candidate)))
    nested = root / "inner"
    nested.mkdir()
    with pytest.raises(BridgeError, match="nested"):
        runtime_env.TestRootLock(nested)
    lock.release()
    runtime_env.TestRootLock(root).release()
    runtime_env.TestRootLock(nested).release()


def test_build_info_reports_exact_sha_or_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    info = runtime_env.build_info()
    checkout = Path(runtime_env.__file__).resolve().parents[2]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True, text=True, check=False
    ).stdout.strip()
    if info["code_source"] == "git-checkout":
        assert info["code_sha"] == head and isinstance(info["code_dirty"], bool)
    else:
        assert info["code_sha"] == "unknown"
    runtime_env.build_info.cache_clear()
    monkeypatch.setattr(runtime_env, "_git", lambda *_a: None)
    try:
        unknown = runtime_env.build_info()
        assert unknown["code_sha"] == "unknown" and unknown["code_dirty"] is None
        assert runtime_env.short_sha(unknown) == "unknown"
    finally:
        runtime_env.build_info.cache_clear()


def test_schema_revision_is_read_only(tmp_path: Path) -> None:
    missing = tmp_path / "none.sqlite3"
    assert runtime_env.schema_revision(missing) is None and not missing.exists()
    db = tmp_path / "workbench.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('schema_revision', '3')")
    conn.commit()
    conn.close()
    before = (db.read_bytes(), db.stat().st_mtime_ns)
    assert runtime_env.schema_revision(db) == 3
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before


def test_describe_reports_refusal_without_creating_state(tmp_path: Path) -> None:
    out = runtime_env.describe(None, {"HBRIDGE_ENV": "test"})
    assert out["isolation"] == "refused" and "build" in out
    target = tmp_path / "never"
    out = runtime_env.describe(target, {"HBRIDGE_ENV": "test", "HBRIDGE_TEST_ROOT": str(tmp_path)})
    assert out["isolation"] == "refused" and not target.exists()
