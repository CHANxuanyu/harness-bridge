"""Open a RepoBridge session in the official desktop client, by official routes only.

* Claude Code → Claude Desktop: ``claude --desktop --resume <session-id>`` (Claude Code 2.1.285 or
  later, macOS / x64 Windows, signed in with a Claude subscription). The CLI prints
  ``Opening session <id> in Claude Desktop`` and exits. It does not move a session that is still
  open elsewhere, so RepoBridge releases its own connection first. Desktop continues the same
  session id, so ``--resume`` finds it again afterwards.
* Codex → Codex app: the documented existing-chat link ``codex://threads/<thread-id>`` opened
  with the installed app (bundle ``com.openai.codex``).

A successful command only means the native launcher accepted the request. Whether the right chat
is visible, whether it is listed in the app's sidebar, and whether it can be continued there are
separate observations that RepoBridge cannot make for the user. Vendor storage is never touched.
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness_bridge.desktop import run_handoff
from harness_bridge.workbench.harness import CLAUDE, CODEX, DEFAULT_APP_DIRS
from harness_bridge.workbench.pty_host import strip_ansi_tail

CLAUDE_DESKTOP_MIN = (2, 1, 285)
APP_IDS = {CLAUDE: "com.anthropic.claudefordesktop", CODEX: "com.openai.codex"}
APP_SCHEMES = {CLAUDE: "claude", CODEX: "codex"}
APP_LABELS = {CLAUDE: "Claude Desktop", CODEX: "Codex"}
_UUIDISH = re.compile(r"^[0-9a-fA-F-]{16,64}$")


@dataclass(frozen=True)
class DesktopApp:
    harness: str
    label: str
    path: str
    bundle_id: str
    version: str | None


def find_apps(dirs: Sequence[str] = DEFAULT_APP_DIRS) -> dict[str, DesktopApp]:
    """Installed official clients, identified by bundle id and URL scheme (top level only)."""
    found: dict[str, DesktopApp] = {}
    for base in dirs:
        try:
            entries = sorted(Path(base).expanduser().iterdir())
        except OSError:
            continue
        for app in entries:
            if app.suffix != ".app" or app.is_symlink():
                continue
            try:
                info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
            if not isinstance(info, dict):
                continue
            schemes = {
                s
                for row in info.get("CFBundleURLTypes") or []
                if isinstance(row, dict)
                for s in row.get("CFBundleURLSchemes") or []
            }
            for harness, bundle in APP_IDS.items():
                if harness in found:
                    continue
                if info.get("CFBundleIdentifier") == bundle and APP_SCHEMES[harness] in schemes:
                    found[harness] = DesktopApp(
                        harness,
                        APP_LABELS[harness],
                        str(app),
                        bundle,
                        info.get("CFBundleShortVersionString"),
                    )
    return found


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def capability(
    session: Mapping[str, Any],
    *,
    apps: Mapping[str, DesktopApp],
    cli_version: str | None,
    platform: str = sys.platform,
) -> dict[str, Any]:
    harness = session["harness"]
    native = session.get("native_session_id")
    label = APP_LABELS.get(harness, "")
    app = apps.get(harness)
    out: dict[str, Any] = {
        "app": label,
        "app_found": app is not None,
        "app_version": app.version if app else None,
        "available": False,
        "reason": None,
        "command": None,
        "link": None,
    }
    if harness == CLAUDE and native:
        out["command"] = f"claude --desktop --resume {native}"
    if harness == CODEX and native:
        out["link"] = f"codex://threads/{native}"
    if platform != "darwin":
        out["reason"] = "目前只在 macOS 上提供"
    elif app is None:
        out["reason"] = f"没有在“应用程序”文件夹中找到 {label}"
    elif not native or not _UUIDISH.match(str(native)):
        out["reason"] = "还没有原生会话 ID"
    elif int(session.get("turns_observed") or 0) == 0:
        out["reason"] = "还没有对话；先在这里发出第一条消息"
    elif harness == CLAUDE and (parse_version(cli_version) or (0, 0, 0)) < CLAUDE_DESKTOP_MIN:
        out["reason"] = "需要 Claude Code 2.1.285 或更高版本（claude --desktop）"
    else:
        out["available"] = True
    return out


def open_claude(
    binary: str, session_id: str, *, cwd: str, env: Mapping[str, str], timeout: float = 20
) -> dict[str, Any]:
    """Run the official CLI handoff on a PTY (it refuses redirected stdio); no input is written."""
    try:
        result = run_handoff(
            [binary, "--desktop", "--resume", session_id], cwd=cwd, env=dict(env), timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "failed", "exit_code": None, "message": f"无法运行 claude：{exc}"}
    text = strip_ansi_tail(result.stdout + result.stderr, lines=6, limit=600)
    ack = f"Opening session {session_id} in Claude Desktop"
    if result.returncode == 0 and ack in text:
        return {"status": "acknowledged", "exit_code": 0, "message": ack}
    return {
        "status": "not_acknowledged",
        "exit_code": result.returncode,
        # Shown once to the user, never stored: it can name local paths.
        "message": text.splitlines()[-1] if text else "",
    }


def open_codex(
    app: DesktopApp,
    thread_id: str,
    *,
    opener: str = "/usr/bin/open",
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    link = f"codex://threads/{thread_id}"
    try:
        result = subprocess.run(
            [opener, "-a", app.path, link],
            env=dict(env or os.environ),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "failed", "exit_code": None, "message": f"无法打开 Codex：{exc}"}
    if result.returncode == 0:
        return {"status": "requested", "exit_code": 0, "message": link}
    message = result.stderr.decode("utf-8", "replace").strip().splitlines()
    return {
        "status": "failed",
        "exit_code": result.returncode,
        "message": message[-1][:300] if message else "",
    }
