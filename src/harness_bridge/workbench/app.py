"""``hbridge app`` / ``repobridge``: start the workbench server and open its window.

The native window uses pywebview (``uv sync --extra desktop``). Without it, or with
``--browser``, the same UI opens in the default browser. ``--no-open`` only prints the one-time
launch URL (useful for development); treat that URL as a local secret.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import sys
import threading
import time
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
    # Development only: lets a tester join the window's server from a browser and capture the
    # window's own pixels. Not shown in --help.
    parser.add_argument("--dev-snapshot-dir", default=None, help=argparse.SUPPRESS)
    # Development only: test instances point desktop-client discovery at fake app bundles and
    # "open" requests at a recorder, so a stub session can never open the real Claude/Codex app.
    parser.add_argument("--dev-app-dir", action="append", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--dev-opener", default=None, help=argparse.SUPPRESS)


def run(args: argparse.Namespace) -> int:
    from harness_bridge import runtime_env
    from harness_bridge.config import default_state_dir
    from harness_bridge.errors import BridgeError
    from harness_bridge.workbench.harness import CLAUDE, CODEX, WorkbenchConfig
    from harness_bridge.workbench.server import WorkbenchServer
    from harness_bridge.workbench.service import Workbench

    binaries = {k: v for k, v in ((CLAUDE, args.claude_binary), (CODEX, args.codex_binary)) if v}
    extra: dict[str, Any] = {}
    if getattr(args, "dev_app_dir", None):
        extra["app_dirs"] = tuple(args.dev_app_dir)
    if getattr(args, "dev_opener", None):
        extra["opener"] = args.dev_opener
    raw_state = getattr(args, "state_dir", None)
    try:
        # Environment and path checks (and the test-root lock) before anything is written:
        # a refused start leaves no directory, lock file, database or process behind.
        state_dir = Path(raw_state).expanduser() if raw_state else default_state_dir()
        plan = runtime_env.prepare_start(
            state_dir, WorkbenchConfig(binaries=binaries, **extra), dict(os.environ)
        )
    except BridgeError as err:
        print(f"RepoBridge did not start: {err.message}", file=sys.stderr)
        return err.exit_status
    with contextlib.ExitStack() as cleanup:
        cleanup.callback(plan.release)
        try:
            plan.claim()
        except BridgeError as err:
            print(f"RepoBridge did not start: {err.message}", file=sys.stderr)
            return err.exit_status
        lock = _single_instance(state_dir)
        if lock is None:
            print(
                f"RepoBridge is already running for {state_dir}; use its window "
                "(or quit it first). Two Apps on one state would fight over the same sessions.",
                file=sys.stderr,
            )
            return 1
        cleanup.callback(lock.close)
        workbench = Workbench(state_dir, config=plan.config, root_lock=plan.root_lock)
        try:
            server = WorkbenchServer(workbench, port=args.port)
            server.start()
        except BaseException:
            workbench.close()
            raise
        # Same shutdown order as before: workbench, server, lock (then the test-root lock).
        cleanup.callback(server.close)
        cleanup.callback(workbench.close)
        _serve(args, server, workbench)
    return 0


def _serve(args: argparse.Namespace, server: Any, workbench: Any) -> None:
    """Run until the window closes or a signal arrives (cleanup is the caller's)."""
    dev_dir = Path(args.dev_snapshot_dir).expanduser() if args.dev_snapshot_dir else None
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
        _run_window(server.auth_url, server.base_url, workbench, dev_dir)


def _single_instance(state_dir: Path) -> Any:
    """Hold an exclusive lock on the state dir for the App's lifetime (released on exit/crash)."""
    import fcntl

    path = state_dir / "workbench" / "app.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")  # noqa: SIM115 - kept open to hold the lock
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


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


def _open_url(url: str) -> None:
    """Open a link from a reply in the default browser (the server validated the scheme)."""
    import subprocess

    subprocess.run(["/usr/bin/open", "--", url], check=False, timeout=10, capture_output=True)


def _pick_folder(window: Any) -> str | None:
    import webview

    folder = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
    if folder is None:
        folder = webview.FOLDER_DIALOG
    result = window.create_file_dialog(folder)
    return str(result[0]) if result else None


def _pick_files(window: Any) -> list[str]:
    """The system open panel (several files); the page only ever sees the chosen paths."""
    import webview

    kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
    if kind is None:
        kind = webview.OPEN_DIALOG
    result = window.create_file_dialog(kind, allow_multiple=True)
    return [str(p) for p in result] if result else []


def _run_window(url: str, base_url: str, workbench: Any, dev_dir: Path | None) -> None:
    from harness_bridge.workbench import native_mac

    native_mac.set_app_name()  # before pywebview reads the bundle name
    import webview

    appearance = workbench.prefs.get()["appearance"]
    # No js_api: pywebview builds its JS bridge with `new Function`, which the page's CSP
    # (script-src 'self', no eval) forbids. Native calls go through the authenticated loopback
    # API instead and reach the window from Python.
    window = webview.create_window(
        "RepoBridge",
        url,
        width=1360,
        height=860,
        min_size=(880, 560),
        confirm_close=True,
        background_color=native_mac.background_for(appearance),
        text_select=True,
        focus=dev_dir is None,
    )
    if window is None:
        raise RuntimeError("pywebview did not create a window")
    workbench.native = {
        "title": lambda title: window.set_title(title or "RepoBridge"),
        "appearance": lambda mode: native_mac.set_appearance(window, mode),
        "pick_folder": lambda: _pick_folder(window),
        "pick_files": lambda: _pick_files(window),
        "open_url": _open_url,
    }
    if dev_dir is not None and native_mac.available():
        dev_dir.mkdir(parents=True, exist_ok=True)
        url_file = dev_dir / "launch-url.txt"
        url_file.touch(mode=0o600)
        url_file.write_text(url + "\n", encoding="utf-8")
        workbench.dev_snapshot = lambda name: native_mac.snapshot(window, dev_dir, name)
        # A new query forces a real navigation (a changed fragment alone is same-document).
        workbench.dev_reload = lambda fragment: window.load_url(
            f"{base_url}/?reload={time.monotonic_ns()}" + (f"#{fragment}" if fragment else "")
        )
        workbench.dev_resize = lambda width, height: window.resize(width, height)

    def on_loaded() -> None:
        with contextlib.suppress(Exception):
            native_mac.set_appearance(window, workbench.prefs.get()["appearance"])
        if dev_dir is not None:
            with contextlib.suppress(Exception):
                native_mac.keep_rendering_when_covered(window)

    window.events.loaded += on_loaded
    webview.start(localization={"global.quitConfirmation": CLOSE_CONFIRMATION})
