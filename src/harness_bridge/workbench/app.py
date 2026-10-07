"""``hbridge app`` / ``repobridge``: start the workbench server and open its window.

The native window uses pywebview (``uv sync --extra desktop``). Without it, or with
``--browser``, the same UI opens in the default browser. ``--no-open`` only prints the one-time
launch URL (useful for development); treat that URL as a local secret.
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

CLOSE_CONFIRMATION = (
    "关闭 RepoBridge 会结束窗口中运行的原生会话（之后可在 App 中原生恢复）。确定关闭？"
)


def build_parser(prog: str = "repobridge") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="RepoBridge desktop workbench for native Codex / Claude Code sessions.",
    )
    add_arguments(parser)
    return parser


def add_arguments(parser: argparse.ArgumentParser, *, state_dir: bool = True) -> None:
    if state_dir:
        parser.add_argument("--state-dir", default=None, help="state root directory")
    parser.add_argument("--port", type=int, default=0, help="loopback port (default: any free)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--browser", action="store_true", help="open in the default browser")
    mode.add_argument("--no-open", action="store_true", help="only print the launch URL")
    parser.add_argument("--claude-binary", default=None, help="absolute path to `claude`")
    parser.add_argument("--codex-binary", default=None, help="absolute path to `codex`")


def run(args: argparse.Namespace) -> int:
    from harness_bridge.config import default_state_dir
    from harness_bridge.workbench.harness import CLAUDE, CODEX, WorkbenchConfig
    from harness_bridge.workbench.server import WorkbenchServer
    from harness_bridge.workbench.service import Workbench

    raw_state = getattr(args, "state_dir", None)
    state_dir = Path(raw_state).expanduser() if raw_state else default_state_dir()
    binaries = {k: v for k, v in ((CLAUDE, args.claude_binary), (CODEX, args.codex_binary)) if v}
    workbench = Workbench(state_dir, config=WorkbenchConfig(binaries=binaries))
    server = WorkbenchServer(workbench, port=args.port)
    server.start()
    try:
        if args.no_open:
            print(server.auth_url, flush=True)
            _wait_for_signal()
        elif args.browser or not _have_webview():
            if not args.browser:
                print(
                    "pywebview is not installed; opening the default browser instead "
                    "(install with: uv sync --extra desktop)",
                    file=sys.stderr,
                )
            webbrowser.open(server.auth_url)
            print(f"RepoBridge is running at {server.base_url} (Ctrl+C to quit)", flush=True)
            _wait_for_signal()
        else:
            _run_window(server.auth_url)
    finally:
        workbench.close()
        server.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


def _have_webview() -> bool:
    try:
        import webview  # noqa: F401
    except ImportError:
        return False
    return True


def _wait_for_signal() -> None:
    stop = threading.Event()

    def handler(signum: int, _frame: Any) -> None:
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, handler)
    while not stop.wait(0.5):
        pass


class _JsApi:
    """Methods callable from the page as ``window.pywebview.api.*``."""

    def __init__(self) -> None:
        self._window: Any = None

    def pick_folder(self) -> str | None:
        import webview

        folder = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
        if folder is None:
            folder = webview.FOLDER_DIALOG
        result = self._window.create_file_dialog(folder)
        return str(result[0]) if result else None


def _run_window(url: str) -> None:
    import webview

    api = _JsApi()
    window = webview.create_window(
        "RepoBridge",
        url,
        js_api=api,
        width=1440,
        height=900,
        min_size=(960, 600),
        confirm_close=True,
        background_color="#0f1115",
        text_select=True,
    )
    api._window = window
    webview.start(localization={"global.quitConfirmation": CLOSE_CONFIRMATION})
