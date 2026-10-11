"""Runtime environments (dev / test / prod), their isolation rules and build identity.

``HBRIDGE_ENV`` selects the profile; unset means ``prod`` with the historical defaults, so the
existing entry points and the user's current state directory behave exactly as before.

* ``prod``: ``--state-dir`` / ``HBRIDGE_STATE_DIR`` / ``$XDG_STATE_HOME/harness-bridge``. Never
  writes an ownership marker; refuses a directory marked for dev/test.
* ``dev``: default state ``$XDG_STATE_HOME/harness-bridge-dev``. The state directory must be
  new/empty or carry the dev marker (``environment.json``); an existing unmarked directory — for
  example a custom prod directory inherited through ``HBRIDGE_STATE_DIR`` — is refused. Only
  RepoBridge state is separated: the native CLIs still use the developer's own HOME, history and
  login unless HOME/CODEX_HOME/CLAUDE_CONFIG_DIR are set.
* ``test``: needs ``HBRIDGE_TEST_ROOT``, an existing sandbox directory. State (new/empty or marked
  test), the native CLIs' HOME/config/history, explicitly configured stub binaries, desktop-client
  lookup and the opener must all live inside it; PATH discovery is off. Directory locks allow one
  running instance per root and no two running roots nested in each other, in either start order.

All checks are read-only (``resolve``/``prepare_start``); the marker is written only after they
pass (``claim_state_dir``), as the first write of a legal start.

Build identity (package version, exact git SHA, dirty flag) is read once per process. An installed
wheel has no checkout, so its SHA is reported as ``unknown``, never guessed.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import json
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


# --- state ownership -----------------------------------------------------------------------
# A dev/test start may only use a state directory that is absent, empty, or carries that
# environment's marker. An existing directory without a marker cannot be proven to be dev/test
# data (it may be a prod directory reused through HBRIDGE_STATE_DIR or --state-dir), so it is
# refused rather than claimed. prod never writes a marker (legacy directories stay untouched)
# and refuses a directory marked for dev/test. Adopting a copy of prod data needs a future,
# explicit command; nothing is migrated automatically.

MARKER_FILE = "environment.json"
MARKER_FORMAT = "repobridge.state-environment.v1"
_IGNORED_ENTRIES = frozenset({".DS_Store"})


def state_owner(state_dir: Path) -> str:
    """``absent`` | ``empty`` | ``dev`` | ``test`` | ``unmarked`` | ``invalid`` (read-only)."""
    path = _resolved(state_dir)
    if not os.path.lexists(path):
        return "absent"
    if not path.is_dir():
        return "invalid"
    marker = path / MARKER_FILE
    if os.path.lexists(marker):
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "invalid"
        if (
            isinstance(data, dict)
            and data.get("format") == MARKER_FORMAT
            and data.get("env") in ("dev", "test")
            and not marker.is_symlink()
        ):
            return str(data["env"])
        return "invalid"
    try:
        entries = [e for e in os.listdir(path) if e not in _IGNORED_ENTRIES]
    except OSError:
        return "invalid"
    return "unmarked" if entries else "empty"


def check_owner(name: str, state_dir: Path) -> str:
    owner = state_owner(state_dir)
    if name == "prod":
        if owner in ("dev", "test"):
            raise refuse(f"this state directory belongs to the {owner} environment")
        return owner
    if owner in ("absent", "empty") or owner == name:
        return owner
    if owner in ("dev", "test"):
        raise refuse(f"this state directory belongs to the {owner} environment")
    raise refuse(
        f"existing state directory is not marked for {name}; it may be prod state "
        "(e.g. inherited HBRIDGE_STATE_DIR). Use a new directory; nothing was opened or changed"
    )


def claim_state_dir(profile: Profile) -> None:
    """dev/test: create the state directory and its marker. First write of a legal start."""
    if profile.name not in ("dev", "test"):
        return
    path = _resolved(profile.state_dir)
    check_owner(profile.name, path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = path / MARKER_FILE
    payload = json.dumps({"format": MARKER_FORMAT, "env": profile.name}) + "\n"
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        check_owner(profile.name, path)  # a concurrent start of the same environment
        return
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)


def resolve(state_dir: Path, env: Mapping[str, str]) -> Profile:
    """Read-only validation of profile, paths, ownership and native environment."""
    name, source = profile_name(env)
    root = check_state_dir(name, state_dir, env)
    check_owner(name, state_dir)
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
    """Exclusive lock on the active test root, shared locks on its possible-root ancestors.

    Kernel ``flock`` on the directories themselves (no lock files): a parent root cannot be
    locked exclusively while a child holds it shared, a child cannot lock its parent shared
    while the parent is held exclusively, siblings share their common parents, and a crashed
    process releases everything. Both start orders and concurrent starts are refused with one
    winner. Ancestors that cannot be a test root (``/``, directories containing the real home,
    unreadable ones) are skipped; nothing below the root is scanned.
    """

    __test__ = False  # not a pytest test class

    def __init__(self, root: Path) -> None:
        import fcntl

        self._fcntl = fcntl
        self.root = _resolved(root)
        self._fds: list[int] = []
        try:
            for ancestor in reversed(self.root.parents):
                if ancestor == Path("/") or _same_or_inside(real_home(), ancestor):
                    continue
                fd = self._open(ancestor, required=False)
                if fd is not None:
                    self._flock(fd, fcntl.LOCK_SH, "this test root is nested inside a running one")
            fd = self._open(self.root, required=True)
            assert fd is not None
            self._flock(
                fd,
                fcntl.LOCK_EX,
                "another test instance is using this test root or a root nested inside it",
            )
        except BaseException:
            self.release()
            raise

    def _open(self, path: Path, *, required: bool) -> int | None:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            if required:
                raise refuse("cannot open the test root for locking") from None
            return None  # unreadable: no instance of this user can lock it as a root either
        self._fds.append(fd)
        return fd

    def _flock(self, fd: int, mode: int, busy: str) -> None:
        try:
            self._fcntl.flock(fd, mode | self._fcntl.LOCK_NB)
        except BlockingIOError:
            raise refuse(busy) from None
        except OSError:
            raise refuse("the test root's file system does not support reliable locks") from None

    def release(self) -> None:
        fds, self._fds = self._fds, []
        for fd in fds:
            with contextlib.suppress(OSError):
                os.close(fd)  # closing the descriptor releases its flock


@dataclass
class StartPlan:
    """A validated start: checks done and the test-root lock held, nothing written yet."""

    profile: Profile
    config: Any
    root_lock: TestRootLock | None

    def claim(self) -> None:
        claim_state_dir(self.profile)

    def release(self) -> None:
        if self.root_lock is not None:
            self.root_lock.release()


def prepare_start(state_dir: Path, config: Any, env: Mapping[str, str]) -> StartPlan:
    """App preflight: validate everything and take the test-root lock before any file write."""
    profile, checked = workbench_profile(state_dir, config, env)
    lock = TestRootLock(profile.test_root) if profile.test_root is not None else None
    return StartPlan(profile, checked, lock)


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
    target: Path | None = None
    try:
        name, source = profile_name(env)
        out.update(env=name, env_source=source)
        target = state_dir or default_state_dir(env)
        out["state_dir"] = str(target)
        profile = resolve(target, env)
        out.update(
            native_env=profile.native_env,
            isolation="ok",
            schema_revision=schema_revision(target / "workbench.sqlite3"),
        )
    except BridgeError as err:
        out.update(isolation="refused", refusal=err.message)
    if target is not None:
        out["state_owner"] = state_owner(target)
    out["argv0"] = Path(sys.argv[0]).name if sys.argv else None
    return out
