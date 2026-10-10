"""UI-only accessibility checks on the page source (static/*.js). No server, no browser.

Modal dialogs are announced by assistive technology with their accessible name; a role=dialog
without aria-label/aria-labelledby is read as a bare "dialog".
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "harness_bridge" / "workbench" / "static"


def test_every_dialog_is_named_by_its_heading() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    body = app[app.index("function dialog(") :]
    body = body[: body.index("\n}\n")]
    assert "box.querySelector('h2')" in body and "box.setAttribute('aria-labelledby'" in body
    # Every dialog opened through dialog() starts with a heading to be named by.
    for name in ("app.js", "existing.js"):
        src = (STATIC / name).read_text(encoding="utf-8")
        for call in re.finditer(r"close = dialog\(\[", src):
            opening = src[call.end() : call.end() + 200]
            assert re.match(r"\s*h\('h2', \{\}, '[^']+'\)", opening), (name, opening[:60])
