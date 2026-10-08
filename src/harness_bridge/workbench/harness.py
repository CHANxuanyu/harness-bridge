"""Native harness discovery, launch argv and session environment.

Only interactive native CLIs are launched. Side channels are record-only: Claude Code hooks from a
per-run ``--settings`` file and Codex per-invocation ``-c notify`` / ``tui.notifications`` (OSC 9).
Nothing here reads login state, and API/provider variables are removed from the session env so a
subscription session is never silently switched to API billing.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness_bridge.config import (
    API_PROVIDER_ENV,
    CLOUD_ENV_MARKERS,
    CODEX_PROVIDER_ENV,
    NESTED_ENV_MARKERS,
)

CLAUDE = "claude-code"
CODEX = "codex"
HARNESSES = (CLAUDE, CODEX)
LABELS = {CLAUDE: "Claude Code", CODEX: "Codex"}
BINARY_NAMES = {CLAUDE: "claude", CODEX: "codex"}

_HOME = Path.home()
DEFAULT_LOCATIONS: dict[str, tuple[str, ...]] = {
    CLAUDE: (
        str(_HOME / ".local/bin/claude"),
        str(_HOME / ".claude/local/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ),
    CODEX: (
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
        str(_HOME / ".local/bin/codex"),
        # The Codex/ChatGPT desktop app bundles the official CLI.
        "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
        "/Applications/Codex.app/Contents/Resources/codex-cli/bin/codex",
    ),
}
EXTRA_PATH_DIRS = (str(_HOME / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin")

# Terminal identity inherited from whatever launched the App would mislead the native TUI.
_TERMINAL_IDENTITY_ENV = (
    "TERM_PROGRAM",
    "TERM_PROGRAM_VERSION",
    "TERM_SESSION_ID",
    "ITERM_SESSION_ID",
    "ITERM_PROFILE",
    "TMUX",
    "TMUX_PANE",
    "STY",
    "KITTY_WINDOW_ID",
    "WEZTERM_PANE",
    "VSCODE_INJECTION",
    "VSCODE_GIT_IPC_HANDLE",
)
BILLING_ENV = tuple(dict.fromkeys(API_PROVIDER_ENV + CODEX_PROVIDER_ENV))

CLAUDE_HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "Notification",
    "Stop",
    "SessionEnd",
)
_TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"}

RELAY = Path(__file__).with_name("relay.py")
# Make the session tty controlling for the new session leader, then exec the native CLI in place
# (same pid). Popen cannot set a controlling tty itself; without one the TUI gets no SIGWINCH.
_CTTY_EXEC = (
    "import fcntl,os,sys,termios\n"
    "fcntl.ioctl(0,termios.TIOCSCTTY,0)\n"
    "try:\n os.execv(sys.argv[1],sys.argv[1:])\n"
    "except OSError as e:\n"
    " sys.stderr.write('repobridge: cannot start %s: %s\\n'%(sys.argv[1],e))\n"
    " sys.exit(127)\n"
)


@dataclass(frozen=True)
class HarnessInfo:
    kind: str
    label: str
    binary: str | None
    version: str | None
    problem: str | None

    @property
    def available(self) -> bool:
        return self.binary is not None and self.problem is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "binary": self.binary,
            "version": self.version,
            "available": self.available,
            "problem": self.problem,
        }


@dataclass(frozen=True)
class WorkbenchConfig:
    """Explicit binaries win; discovery searches PATH and well-known install locations."""

    binaries: Mapping[str, str] = field(default_factory=dict)
    discover: bool = True
    locations: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: DEFAULT_LOCATIONS)
    python: str = sys.executable


def environment_refusal(env: Mapping[str, str]) -> str | None:
    nested = [n for n in NESTED_ENV_MARKERS if env.get(n)]
    if nested:
        return (
            "RepoBridge was started from inside another agent session ("
            + ", ".join(nested)
            + "); start the App from Finder or a normal terminal to run native sessions"
        )
    cloud = [n for n in CLOUD_ENV_MARKERS if env.get(n)]
    if cloud:
        return "cloud agent environment detected (" + ", ".join(cloud) + "); refusing"
    return None


def stripped_billing_env(env: Mapping[str, str]) -> list[str]:
    return [n for n in BILLING_ENV if env.get(n)]


def session_env(base: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """Inherit the user's env minus API/provider variables (names returned, values never kept)."""
    stripped = stripped_billing_env(base)
    drop = set(BILLING_ENV) | set(_TERMINAL_IDENTITY_ENV)
    env = {k: v for k, v in base.items() if k not in drop}
    path = env.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin").split(os.pathsep)
    path += [d for d in EXTRA_PATH_DIRS if d not in path]
    env["PATH"] = os.pathsep.join(path)
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["TERM_PROGRAM"] = "RepoBridge"
    if not any(env.get(k) for k in ("LC_ALL", "LC_CTYPE", "LANG")):
        env["LANG"] = "en_US.UTF-8"
    return env, stripped


def resolve_binary(kind: str, config: WorkbenchConfig, env: Mapping[str, str]) -> str | None:
    configured = config.binaries.get(kind)
    if configured:
        return configured if _executable(configured) else None
    if not config.discover:
        return None
    path = env.get("PATH", "") + os.pathsep + os.pathsep.join(EXTRA_PATH_DIRS)
    found = shutil.which(BINARY_NAMES[kind], path=path)
    if found:
        return found
    return next((p for p in config.locations.get(kind, ()) if _executable(p)), None)


def _executable(path: str) -> bool:
    return os.path.isabs(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def probe(kind: str, config: WorkbenchConfig, env: Mapping[str, str]) -> HarnessInfo:
    """Locate the CLI and read ``--version`` (no session, no prompt, no model call)."""
    label = LABELS[kind]
    binary = resolve_binary(kind, config, env)
    if binary is None:
        configured = config.binaries.get(kind)
        problem = (
            f"configured binary {configured!r} is not an executable absolute path"
            if configured
            else f"`{BINARY_NAMES[kind]}` not found on PATH or in the usual install locations"
        )
        return HarnessInfo(kind, label, None, None, problem)
    child_env, _ = session_env(env)
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env=child_env,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return HarnessInfo(kind, label, binary, None, f"`--version` failed: {type(exc).__name__}")
    if proc.returncode != 0:
        return HarnessInfo(kind, label, binary, None, f"`--version` exited {proc.returncode}")
    lines = proc.stdout.strip().splitlines()
    return HarnessInfo(kind, label, binary, lines[0][:120] if lines else None, None)


@dataclass(frozen=True)
class LaunchSpec:
    argv: list[str]
    env: dict[str, str]
    cwd: str
    native_session_id: str | None
    binding: str
    stripped_env: list[str]
    side_channel_files: list[str]


def relay_command(config: WorkbenchConfig, mode: str, events_path: Path) -> list[str]:
    return [config.python, "-I", "-S", "-B", str(RELAY), mode, str(events_path)]


def claude_settings(config: WorkbenchConfig, events_path: Path) -> dict[str, Any]:
    command = shlex.join(relay_command(config, "claude-hook", events_path))
    hook = {"type": "command", "command": command, "timeout": 10}
    hooks: dict[str, Any] = {}
    for event in CLAUDE_HOOK_EVENTS:
        entry: dict[str, Any] = {"hooks": [hook]}
        if event in _TOOL_EVENTS:
            entry["matcher"] = "*"
        hooks[event] = [entry]
    return {"hooks": hooks}


def _toml_array(values: list[str]) -> str:
    # JSON string escapes are valid TOML basic-string escapes.
    return "[" + ",".join(json.dumps(v) for v in values) + "]"


def build_launch(
    kind: str,
    binary: str,
    *,
    mode: str,
    workdir: str,
    title: str,
    native_session_id: str | None,
    initial_prompt: str | None,
    run_dir: Path,
    config: WorkbenchConfig,
    base_env: Mapping[str, str],
) -> LaunchSpec:
    if mode not in ("new", "resume"):
        raise ValueError(mode)
    if mode == "resume" and not native_session_id:
        raise ValueError("resume requires a native session id")
    env, stripped = session_env(base_env)
    events_path = run_dir / "events.jsonl"
    files = [str(events_path)]
    argv: list[str]
    if kind == CLAUDE:
        settings_path = run_dir / "claude-settings.json"
        settings_path.write_text(json.dumps(claude_settings(config, events_path), indent=2))
        files.append(str(settings_path))
        if mode == "new":
            sid = native_session_id or str(uuid.uuid4())
            argv = [binary, "--session-id", sid, "-n", title, "--settings", str(settings_path)]
            binding = "preassigned"
        else:
            sid = native_session_id  # type: ignore[assignment]
            argv = [binary, "--resume", sid, "--settings", str(settings_path)]
            binding = "resume_requested"
    elif kind == CODEX:
        # --no-daemon keeps the session in this process tree: App-owned stop, the stripped env
        # and per-invocation overrides apply, instead of a shared background app-server.
        overrides = [
            "--no-daemon",
            "-c",
            "notify=" + _toml_array(relay_command(config, "codex-notify", events_path)),
            "-c",
            "tui.notifications=true",
            "-c",
            'tui.notification_method="osc9"',
            "-c",
            'tui.notification_condition="always"',
        ]
        if mode == "new":
            sid = None
            argv = [binary, "-C", workdir, *overrides]
            binding = "pending"
        else:
            sid = native_session_id
            argv = [binary, "resume", sid, *overrides]  # type: ignore[list-item]
            binding = "resume_requested"
    else:
        raise ValueError(f"unknown harness {kind!r}")
    if initial_prompt:
        argv += ["--", initial_prompt]
    wrapped = [config.python, "-I", "-S", "-B", "-c", _CTTY_EXEC, *argv]
    return LaunchSpec(wrapped, env, workdir, sid, binding, stripped, files)


def native_argv(spec: LaunchSpec) -> list[str]:
    """The native CLI argv without the controlling-tty exec shim (for display/records)."""
    return spec.argv[6:]
