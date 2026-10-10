"""Runtime environments (dev / test / prod), their isolation rules and build identity.

``HBRIDGE_ENV`` selects the profile; unset means ``prod`` with the historical defaults, so the
existing entry points and the user's current state directory behave exactly as before.

* ``prod``: ``--state-dir`` / ``HBRIDGE_STATE_DIR`` / ``$XDG_STATE_HOME/harness-bridge``.
* ``dev``: default state ``$XDG_STATE_HOME/harness-bridge-dev``; an explicit state directory may
  not resolve to the prod default. Only RepoBridge state is separated: the native CLIs still use
  the developer's own HOME, history and login unless HOME/CODEX_HOME/CLAUDE_CONFIG_DIR are set.
* ``test``: needs ``HBRIDGE_TEST_ROOT``, an existing sandbox directory. State, the native CLIs'
  HOME/config/history, explicitly configured stub binaries, desktop-client lookup and the opener
  must all live inside it; PATH discovery is off. One running instance per root (lock), and a root
  may not be nested in another running test root or alias a protected directory.

Build identity (package version, exact git SHA, dirty flag) is read once per process. An installed
wheel has no checkout, so its SHA is reported as ``unknown``, never guessed.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import os
import platform
import pwd
import re
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness_bridge import __version__
from harness_bridge.errors import BridgeError

ENV_VAR = "HBRIDGE_ENV"
TEST_ROOT_VAR = "HBRIDGE_TEST_ROOT"
PROFILES = ("prod", "dev", "test")
STATE_NAMES = {"prod": "harness-bridge", "dev": "harness-bridge-dev"}
# Variables that point a native CLI at its home, config, history or login.
NATIVE_HOME_VARS = (
    "HOME",
    "CODEX_HOME",
    "CLAUDE_CONFIG_DIR",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "XDG_CACHE_HOME",
)
TEST_LOCK = ".hbridge-test-root.lock"


def profile_name(env: Mapping[str, str]) -> tuple[str, str]:
    """(profile, source) where source is ``explicit`` or ``default``."""
    raw = (env.get(ENV_VAR) or "").strip().lower()
    if not raw:
        return "prod", "default"
    if raw not in PROFILES:
        raise BridgeError("USAGE_ERROR", f"{ENV_VAR} must be one of {', '.join(PROFILES)}")
    return raw, "explicit"


def real_home() -> Path:
    """The account's home from the password database, independent of an overridden HOME."""
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (KeyError, OSError):
        return Path(os.path.expanduser("~"))


def state_base(env: Mapping[str, str]) -> Path:
    # Same expression as the historical prod default, so prod paths are unchanged.
    base = env.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base)


def default_state_dir(env: Mapping[str, str]) -> Path:
    """Profile-aware default (``HBRIDGE_STATE_DIR`` always wins, as before)."""
    if env.get("HBRIDGE_STATE_DIR"):
        return Path(env["HBRIDGE_STATE_DIR"]).expanduser()
    name, _ = profile_name(env)
    if name == "test":
        root = env.get(TEST_ROOT_VAR)
        if not root:
            raise BridgeError(
                "USAGE_ERROR",
                f"{ENV_VAR}=test needs {TEST_ROOT_VAR} (a sandbox directory) or an explicit "
                "state directory inside it",
            )
        return Path(root).expanduser() / "state"
    return state_base(env) / STATE_NAMES[name]


def protected_dirs() -> list[Path]:
    """Real-user locations a dev/test instance must never use or alias.

    Derived from the account's home in the password database, not from HOME, so a sandbox that
    overrides HOME cannot hide the real directories.
    """
    home = real_home()
    base = home / ".local" / "state"
    return [
        base / STATE_NAMES["prod"],
        base / STATE_NAMES["dev"],
        home / ".claude",
        home / ".codex",
    ]


def _resolved(path: Path) -> Path:
    return Path(os.path.realpath(path.expanduser()))


def _same_or_inside(path: Path, other: Path) -> bool:
    """True when ``path`` is ``other`` or below it (after resolving symlinks / bind aliases)."""
    p, o = _resolved(path), _resolved(other)
    if p == o or o in p.parents:
        return True
    # Bind mounts and other aliases: compare inode identity of the path and each ancestor.
    try:
        target = os.stat(o)
    except OSError:
        return False
    for candidate in (p, *p.parents):
        with contextlib.suppress(OSError):
            st = os.stat(candidate)
            if (st.st_dev, st.st_ino) == (target.st_dev, target.st_ino):
                return True
    return False


@dataclass(frozen=True)
class Profile:
    name: str
    source: str
    state_dir: Path
    test_root: Path | None = None
    native_env: str = "shared"  # shared | isolated (test) | custom (dev with overrides)

    def describe(self) -> dict[str, Any]:
        """Path-free description for diagnostics."""
        return {
            "env": self.name,
            "env_source": self.source,
            "native_env": self.native_env,
            "test_root_set": self.test_root is not None,
        }


def refuse(message: str) -> BridgeError:
    return BridgeError("PREFLIGHT_FAILED", message, details={"reason": "environment_refused"})


def check_state_dir(name: str, state_dir: Path, env: Mapping[str, str]) -> Path | None:
    """Validate the state directory for the profile; returns the resolved test root (test)."""
    if name == "prod":
        return None
    if name == "dev":
        prod = state_base(env) / STATE_NAMES["prod"]
        for protected in (prod, real_home() / ".local" / "state" / STATE_NAMES["prod"]):
            if _same_or_inside(state_dir, protected) or _same_or_inside(protected, state_dir):
                raise refuse("dev state directory resolves to the prod state directory")
        return None
    raw_root = env.get(TEST_ROOT_VAR)
    if not raw_root or not os.path.isabs(os.path.expanduser(raw_root)):
        raise refuse(f"{ENV_VAR}=test needs {TEST_ROOT_VAR} set to an absolute sandbox directory")
    root = _resolved(Path(raw_root))
    if not root.is_dir():
        raise refuse(f"{TEST_ROOT_VAR} does not exist or is not a directory")
    if root == Path("/") or _same_or_inside(real_home(), root):
        raise refuse(f"{TEST_ROOT_VAR} may not be the filesystem root or contain the real home")
    for protected in protected_dirs():
        if _same_or_inside(root, protected) or _same_or_inside(protected, root):
            raise refuse(f"{TEST_ROOT_VAR} overlaps a real state, Claude or Codex directory")
    resolved_state = _resolved(state_dir)
    if root not in resolved_state.parents:
        raise refuse("test state directory must be inside the test root (no path aliases)")
    for protected in protected_dirs():
        if _same_or_inside(state_dir, protected):
            raise refuse("test state directory aliases a real state directory")
    return root


def check_native_env(name: str, root: Path | None, env: Mapping[str, str]) -> str:
    """Test: every native home/config variable that is set must stay inside the root."""
    if name != "test":
        custom = any(env.get(v) for v in ("CODEX_HOME", "CLAUDE_CONFIG_DIR")) or (
            env.get("HOME") and _resolved(Path(env["HOME"])) != _resolved(real_home())
        )
        return "custom" if custom else "shared"
    assert root is not None
    if not env.get("HOME"):
        raise refuse("test profile needs HOME inside the test root for the native CLIs")
    for var in NATIVE_HOME_VARS:
        value = env.get(var)
        if value and root not in _resolved(Path(value)).parents:
            raise refuse(f"test profile: {var} must point inside the test root")
    return "isolated"


def check_binaries(root: Path, binaries: Mapping[str, str], extra: Mapping[str, Any]) -> None:
    """Test: explicit stub binaries, desktop lookup and opener must live in the root."""
    for kind, path in binaries.items():
        if not os.path.isabs(path) or root not in _resolved(Path(path)).parents:
            raise refuse(f"test profile: the {kind} binary must be inside the test root")
    for app_dir in extra.get("app_dirs", ()):
        if root not in _resolved(Path(app_dir)).parents:
            raise refuse("test profile: desktop-client lookup must be inside the test root")
    opener = extra.get("opener")
    if opener and root not in _resolved(Path(opener)).parents:
        raise refuse("test profile: the desktop opener must be inside the test root")


def resolve(state_dir: Path, env: Mapping[str, str]) -> Profile:
    name, source = profile_name(env)
    root = check_state_dir(name, state_dir, env)
    native = check_native_env(name, root, env)
    return Profile(name, source, state_dir, root, native)


def workbench_profile(state_dir: Path, config: Any, env: Mapping[str, str]) -> tuple[Profile, Any]:
    """Validate a Workbench start; in test, disable binary discovery. Returns (profile, config)."""
    profile = resolve(state_dir, env)
    if profile.name == "test":
        assert profile.test_root is not None
        check_binaries(
            profile.test_root,
            dict(config.binaries),
            {"app_dirs": config.app_dirs, "opener": config.opener},
        )
        if config.discover:
            config = dataclasses.replace(config, discover=False)
    return profile, config


class TestRootLock:
    """One running instance per test root; refuse when an ancestor test root is in use."""

    def __init__(self, root: Path) -> None:
        import fcntl

        self._fcntl = fcntl
        for ancestor in root.parents:
            marker = ancestor / TEST_LOCK
            if marker.is_file():
                with contextlib.suppress(OSError), open(marker, "rb") as probe:
                    try:
                        fcntl.flock(probe.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                    except OSError:
                        raise refuse(
                            "this test root is nested inside another running one"
                        ) from None
        self.path = root / TEST_LOCK
        self._handle = open(self.path, "a+")  # noqa: SIM115 - held for the instance lifetime
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._handle.close()
            raise refuse("another test instance is already using this test root") from None

    def release(self) -> None:
        with contextlib.suppress(OSError, ValueError):
            self._fcntl.flock(self._handle.fileno(), self._fcntl.LOCK_UN)
            self._handle.close()


# --- build identity ---------------------------------------------------------------------------

_SHA = re.compile(r"[0-9a-f]{40}")


def _git(checkout: Path, *args: str) -> str | None:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
    }
    try:
        proc = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "--no-optional-locks",
                *args,
            ],
            cwd=checkout,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


@functools.cache
def build_info() -> dict[str, Any]:
    """Version, exact source SHA and dirty flag of the code actually imported."""
    import harness_bridge

    package = Path(harness_bridge.__file__).resolve().parent
    checkout = package.parent.parent
    sha: str = "unknown"
    dirty: bool | None = None
    source = "installed"
    if package.parent.name == "src" and (checkout / "pyproject.toml").is_file():
        top = _git(checkout, "rev-parse", "--show-toplevel")
        if top is not None and _resolved(Path(top.strip())) == _resolved(checkout):
            head = (_git(checkout, "rev-parse", "HEAD") or "").strip()
            if _SHA.fullmatch(head):
                sha, source = head, "git-checkout"
                status = _git(checkout, "status", "--porcelain=v1", "--untracked-files=normal")
                dirty = None if status is None else bool(status.strip())
    return {
        "version": __version__,
        "code_sha": sha,
        "code_dirty": dirty,
        "code_source": source,
        "python": platform.python_version(),
        "os": platform.system(),
    }


def short_sha(info: Mapping[str, Any] | None = None) -> str:
    sha = str((info or build_info())["code_sha"])
    return sha[:12] if _SHA.fullmatch(sha) else "unknown"


def schema_revision(db: Path) -> int | None:
    """Read the workbench schema revision without creating or upgrading the database."""
    if not db.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_revision'").fetchone()
        return int(row[0]) if row else None
    except (sqlite3.Error, ValueError, TypeError):
        return None
    finally:
        conn.close()


def describe(state_dir: Path | None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """``hbridge env``: resolved profile, isolation verdict and build identity (read-only)."""
    env = dict(os.environ) if env is None else dict(env)
    from harness_bridge.workbench.store import SCHEMA_REVISION

    out: dict[str, Any] = {"build": build_info(), "expected_schema_revision": SCHEMA_REVISION}
    try:
        name, source = profile_name(env)
        out.update(env=name, env_source=source)
        target = state_dir or default_state_dir(env)
        profile = resolve(target, env)
        out.update(
            state_dir=str(target),
            native_env=profile.native_env,
            isolation="ok",
            schema_revision=schema_revision(target / "workbench.sqlite3"),
        )
    except BridgeError as err:
        out.update(isolation="refused", refusal=err.message)
    out["argv0"] = Path(sys.argv[0]).name if sys.argv else None
    return out
