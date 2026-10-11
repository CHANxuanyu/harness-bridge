"""Environment profiles: prod compatibility, dev/test boundaries, alias refusal, build identity."""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
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


def snapshot(root: Path) -> list[tuple[str, int, int, bytes]]:
    """Every entry below root with size, mtime and content: proves "nothing changed"."""
    out = []
    for path in sorted([root, *root.rglob("*")]):
        st = path.lstat()
        data = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
        out.append((str(path.relative_to(root)), st.st_size, st.st_mtime_ns, data))
    return out


def legacy_prod_state(path: Path) -> Path:
    """A synthetic custom prod state directory as an older App left it (no marker)."""
    (path / "workbench").mkdir(parents=True)
    conn = sqlite3.connect(path / "workbench.sqlite3")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('schema_revision', '4')")
    conn.commit()
    conn.close()
    (path / "workbench" / "prefs.json").write_text("{}")
    return path


def test_dev_and_test_refuse_an_existing_unmarked_state_directory(
    fake_home: Path, tmp_path: Path
) -> None:
    custom = legacy_prod_state(tmp_path / "custom-prod")
    alias = tmp_path / "alias"
    alias.symlink_to(custom)
    before = snapshot(custom)
    inherited = {"HBRIDGE_ENV": "dev", "HBRIDGE_STATE_DIR": str(custom)}
    assert default_state_dir(inherited) == custom  # HBRIDGE_STATE_DIR still wins ...
    for state, env in (
        (default_state_dir(inherited), inherited),  # ... but dev may not claim it
        (custom, {"HBRIDGE_ENV": "dev"}),  # explicit --state-dir
        (alias, {"HBRIDGE_ENV": "dev"}),  # path alias
    ):
        with pytest.raises(BridgeError, match="not marked for dev"):
            runtime_env.resolve(state, env)
        with pytest.raises(BridgeError, match="not marked for dev"):
            runtime_env.claim_state_dir(runtime_env.Profile("dev", "explicit", state))
    assert runtime_env.state_owner(custom) == "unmarked"
    assert runtime_env.resolve(custom, {}).name == "prod"  # legacy prod use unchanged
    root = tmp_path / "sandbox"
    (root / "home").mkdir(parents=True)
    legacy_prod_state(root / "state")
    with pytest.raises(BridgeError, match="not marked for test"):
        runtime_env.resolve(root / "state", _test_env(root))
    assert snapshot(custom) == before


def test_new_dev_and_test_directories_are_claimed_and_owners_kept_apart(
    fake_home: Path, tmp_path: Path
) -> None:
    dev = tmp_path / "dev-state"
    profile = runtime_env.resolve(dev, {"HBRIDGE_ENV": "dev"})
    assert not dev.exists()  # resolve is read-only
    runtime_env.claim_state_dir(profile)
    marker = json.loads((dev / "environment.json").read_text())
    assert marker == {"format": runtime_env.MARKER_FORMAT, "env": "dev"}
    assert (dev / "environment.json").stat().st_mode & 0o777 == 0o600
    runtime_env.claim_state_dir(profile)  # idempotent for the same environment
    assert runtime_env.resolve(dev, {"HBRIDGE_ENV": "dev"}).name == "dev"
    with pytest.raises(BridgeError, match="belongs to the dev"):
        runtime_env.resolve(dev, {})  # prod never takes a dev directory
    empty = tmp_path / "empty"
    empty.mkdir()
    runtime_env.claim_state_dir(runtime_env.resolve(empty, {"HBRIDGE_ENV": "dev"}))
    assert runtime_env.state_owner(empty) == "dev"
    root = tmp_path / "sandbox"
    (root / "home").mkdir(parents=True)
    test_profile = runtime_env.resolve(root / "state", _test_env(root))
    runtime_env.claim_state_dir(test_profile)
    assert runtime_env.state_owner(root / "state") == "test"
    garbage = tmp_path / "garbage"
    garbage.mkdir()
    (garbage / "environment.json").write_text("not json")
    with pytest.raises(BridgeError, match="not marked for dev"):
        runtime_env.resolve(garbage, {"HBRIDGE_ENV": "dev"})
    prod = tmp_path / "prod-new"
    runtime_env.claim_state_dir(runtime_env.resolve(prod, {}))
    assert not prod.exists()  # prod never writes a marker


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    parent = tmp_path / "parent"
    child = parent / "child"
    sibling = tmp_path / "sibling"
    child.mkdir(parents=True)
    sibling.mkdir()
    return parent, child, sibling


def test_root_locks_refuse_nesting_in_both_orders_and_aliases(tmp_path: Path) -> None:
    parent, child, sibling = _roots(tmp_path)
    (parent / ".hbridge-test-root.lock").write_text("stale file from an older build")
    for first, second in ((parent, child), (child, parent)):
        held = runtime_env.TestRootLock(first)
        with pytest.raises(BridgeError, match=r"nested|using this test root"):
            runtime_env.TestRootLock(second)
        held.release()
    held = runtime_env.TestRootLock(parent)
    alias = tmp_path / "alias"
    alias.symlink_to(parent)
    for same in (parent, alias):
        with pytest.raises(BridgeError, match="using this test root"):
            runtime_env.TestRootLock(same)
    other = runtime_env.TestRootLock(sibling)  # unrelated sibling roots run side by side
    held.release()
    child_lock = runtime_env.TestRootLock(child)  # parent gone, child (and sibling) fine
    for lock in (other, child_lock):
        lock.release()


_HOLDER = """
import os, sys, time
from pathlib import Path
from harness_bridge.errors import BridgeError
from harness_bridge.runtime_env import TestRootLock
go = Path(sys.argv[2])
while not go.exists():
    time.sleep(0.001)
try:
    lock = TestRootLock(Path(sys.argv[1]))
except BridgeError:
    print("refused", flush=True)
    sys.exit(0)
print("held", flush=True)
time.sleep(float(sys.argv[3]))
"""


def _race(tmp_path: Path, first: Path, second: Path, tag: str) -> list[str]:
    go = tmp_path / f"go-{tag}"
    env = {**os.environ, "PYTHONPATH": str(Path(runtime_env.__file__).resolve().parents[1])}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _HOLDER, str(root), str(go), "0.4"],
            stdout=subprocess.PIPE,
            text=True,
            env=env,
        )
        for root in (first, second)
    ]
    time.sleep(0.2)
    go.write_text("")
    return sorted(p.communicate(timeout=30)[0].strip() for p in procs)


def test_concurrent_starts_never_hold_nested_or_identical_roots(tmp_path: Path) -> None:
    parent, child, sibling = _roots(tmp_path)
    for i in range(8):
        assert _race(tmp_path, parent, child, f"n{i}") == ["held", "refused"]
        assert _race(tmp_path, parent, parent, f"s{i}") == ["held", "refused"]
    assert _race(tmp_path, child, sibling, "sib") == ["held", "held"]


def test_killed_holder_releases_its_root(tmp_path: Path) -> None:
    parent, _, _ = _roots(tmp_path)
    go = tmp_path / "go"
    go.write_text("")
    env = {**os.environ, "PYTHONPATH": str(Path(runtime_env.__file__).resolve().parents[1])}
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(parent), str(go), "60"],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdout is not None and proc.stdout.readline().strip() == "held"
    with pytest.raises(BridgeError):
        runtime_env.TestRootLock(parent)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    runtime_env.TestRootLock(parent).release()


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
