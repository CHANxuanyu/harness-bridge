"""Small macOS-only window integrations for the pywebview (WKWebView) window.

Everything here is best effort and optional: the App works without it, and nothing changes the
user's system settings. Uses PyObjC, which the ``desktop`` extra installs with pywebview.

* the menu bar shows "RepoBridge" instead of "Python";
* the window title follows the selected session; its appearance follows the App's
  System/Light/Dark preference (``NSWindow.appearance``, so the title bar matches);
* a development-only snapshot of the window's own content for visual verification.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

APP_NAME = "RepoBridge"
_LIGHT_BG = "#F7F6F3"
_DARK_BG = "#1C1B1A"


def available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import AppKit  # noqa: F401
    except ImportError:
        return False
    return True


def set_app_name() -> None:
    """Must run before pywebview is imported: it reads the bundle info at import time."""
    if not available():
        return
    import AppKit
    import Foundation

    bundle = Foundation.NSBundle.mainBundle()
    info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
    if info is not None:
        info["CFBundleName"] = APP_NAME
    Foundation.NSProcessInfo.processInfo().setProcessName_(APP_NAME)
    AppKit.NSApplication.sharedApplication()


def system_is_dark() -> bool:
    if not available():
        return False
    import Foundation

    style = Foundation.NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle")
    return bool(style) and str(style).lower() == "dark"


def background_for(appearance: str) -> str:
    dark = appearance == "dark" or (appearance == "system" and system_is_dark())
    return _DARK_BG if dark else _LIGHT_BG


def _on_main(fn: Any, timeout: float = 10.0) -> Any:
    from PyObjCTools import AppHelper

    done = threading.Event()
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:
            box["error"] = exc
        finally:
            done.set()

    AppHelper.callAfter(run)
    if not done.wait(timeout):
        raise TimeoutError("main thread did not respond")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def set_appearance(window: Any, mode: str) -> None:
    if not available() or window is None or window.native is None:
        return
    import AppKit

    names = {"light": AppKit.NSAppearanceNameAqua, "dark": AppKit.NSAppearanceNameDarkAqua}
    appearance = AppKit.NSAppearance.appearanceNamed_(names[mode]) if mode in names else None
    _on_main(lambda: window.native.setAppearance_(appearance))


def snapshot(window: Any, directory: Path, name: str, timeout: float = 15.0) -> dict[str, Any]:
    """Write ``name.png`` (WKWebView content, full resolution) and, when macOS allows an app to
    capture its own window, ``name-window.png`` (including the title bar)."""
    import AppKit
    from webview.platforms.cocoa import BrowserView

    directory.mkdir(parents=True, exist_ok=True)
    content_path = directory / f"{name}.png"
    done = threading.Event()
    box: dict[str, Any] = {}

    def handler(image: Any, error: Any) -> None:
        try:
            if image is None:
                box["error"] = str(error)
                return
            rep = AppKit.NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
            png = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
            png.writeToFile_atomically_(str(content_path), True)
        finally:
            done.set()

    def take() -> None:
        view = BrowserView.instances[window.uid].webview
        view.takeSnapshotWithConfiguration_completionHandler_(None, handler)

    _on_main(take)
    if not done.wait(timeout):
        raise TimeoutError("snapshot timed out")
    if "error" in box:
        raise RuntimeError(box["error"])
    result: dict[str, Any] = {"content": str(content_path), "window": None}
    try:
        result["window"] = _capture_own_window(window, directory / f"{name}-window.png")
    except Exception as exc:
        result["window_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _capture_own_window(window: Any, path: Path) -> str | None:
    import AppKit
    import Quartz

    number = _on_main(lambda: window.native.windowNumber())
    image = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        number,
        Quartz.kCGWindowImageBoundsIgnoreFraming,
    )
    if image is None:
        return None
    rep = AppKit.NSBitmapImageRep.alloc().initWithCGImage_(image)
    png = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    png.writeToFile_atomically_(str(path), True)
    return str(path)
