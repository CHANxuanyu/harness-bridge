"""Workbench UI preferences (appearance, layout, last selection), persisted in the state dir.

Kept server-side so the native window (pywebview runs in private mode, without persistent
localStorage) restores the same layout after a restart. Only known keys with valid values are
stored; anything else is rejected rather than silently kept.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from harness_bridge.errors import BridgeError

_ID = re.compile(r"^(ses|prj)_[0-9a-f]{12}$")


def _choice(*values: str) -> Callable[[Any], bool]:
    return lambda v: v in values


def _int_range(low: int, high: int) -> Callable[[Any], bool]:
    return lambda v: type(v) is int and low <= v <= high


def _bool(v: Any) -> bool:
    return type(v) is bool


def _optional_session(v: Any) -> bool:
    return v is None or (isinstance(v, str) and _ID.match(v) is not None and v.startswith("ses_"))


def _project_ids(v: Any) -> bool:
    return (
        isinstance(v, list)
        and len(v) <= 500
        and all(isinstance(i, str) and _ID.match(i) and i.startswith("prj_") for i in v)
    )


SCHEMA: dict[str, Callable[[Any], bool]] = {
    "appearance": _choice("system", "light", "dark"),
    "terminal_theme": _choice("auto", "dark"),
    "terminal_font_size": _int_range(11, 18),
    "sidebar_width": _int_range(200, 420),
    "sidebar_collapsed": _bool,
    "inspector_open": _bool,
    "inspector_tab": _choice("changes", "activity", "details"),
    "inspector_width": _int_range(300, 900),
    "collapsed_projects": _project_ids,
    "selected_session": _optional_session,
    "show_archived": _bool,
    "last_harness": _choice("claude-code", "codex"),
}
DEFAULTS: dict[str, Any] = {
    "appearance": "system",
    "terminal_theme": "auto",
    "terminal_font_size": 13,
    "sidebar_width": 260,
    "sidebar_collapsed": False,
    "inspector_open": False,
    "inspector_tab": "changes",
    "inspector_width": 420,
    "collapsed_projects": [],
    "selected_session": None,
    "show_archived": False,
    "last_harness": "claude-code",
}


class Prefs:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._values = dict(DEFAULTS)
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in SCHEMA and SCHEMA[key](value):
                    self._values[key] = value

    def get(self) -> dict[str, Any]:
        with self._lock:
            return _copy(self._values)

    def update(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        bad = [k for k, v in changes.items() if k not in SCHEMA or not SCHEMA[k](v)]
        if bad:
            raise BridgeError("INVALID_INPUT", f"invalid preference(s): {sorted(bad)}")
        with self._lock:
            self._values.update(changes)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._values, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return _copy(self._values)


def _copy(values: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = json.loads(json.dumps(values))
    return copied
