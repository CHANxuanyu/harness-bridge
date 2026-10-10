"""UI-only checks for keys that belong to an input method composition (static/*.js).

WebKit, which renders the native window, delivers the Enter (or Escape) that confirms (or cancels) a
pinyin/kana candidate as keydown with isComposing=false and keyCode 229; Chromium reports
isComposing=true. Text fields must ignore both, or confirming a candidate would send, create a
session, commit a rename or submit a path. No server, no browser.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "harness_bridge" / "workbench" / "static"

# Each text field that acts on Enter/Escape/arrows, and the guard it must start with.
GUARDED = {
    "composer.js": [
        "ta.addEventListener('keydown', (e) => {\n    if (composingKey(e)) return;",  # message box
    ],
    "app.js": [
        # global shortcuts and Escape; then rename, new-session title, project path, sidebar filter
        "window.addEventListener('keydown', (e) => {\n  if (composingKey(e)) return;",
        "input.addEventListener('keydown', (e) => {\n    if (composingKey(e)) return;",
        "title.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !composingKey(e))",
        "path.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !composingKey(e))",
        "if (e.key === 'Escape' && !composingKey(e))",
    ],
    "existing.js": [
        "search.addEventListener('keydown', (e) => {\n    if (composingKey(e)) return;",
    ],
}


def _composing(events: list[dict[str, object]]) -> list[bool]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    runner = f"""
const vm = require('vm');
const fs = require('fs');
const ctx = vm.createContext({{ console, Map, Set }});
vm.runInContext(fs.readFileSync({json.dumps(str(STATIC / "composer.js"))}, 'utf8'), ctx);
ctx.events = {json.dumps(events)};
process.stdout.write(JSON.stringify(vm.runInContext('events.map((e) => composingKey(e))', ctx)));
"""
    done = subprocess.run([node, "-e", runner], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    result: list[bool] = json.loads(done.stdout)
    return result


def test_both_engines_ways_of_reporting_a_composition_key_count() -> None:
    chromium = {"key": "Enter", "isComposing": True, "keyCode": 229}
    webkit_confirm = {"key": "Enter", "isComposing": False, "keyCode": 229}
    webkit_cancel = {"key": "Escape", "isComposing": False, "keyCode": 229}
    plain = [{"key": "Enter", "keyCode": 13}, {"key": "Escape", "keyCode": 27}]
    assert _composing([chromium, webkit_confirm, webkit_cancel, *plain]) == [
        True,
        True,
        True,
        False,
        False,
    ]


def test_every_text_field_key_handler_uses_the_same_guard() -> None:
    sources = {name: (STATIC / name).read_text(encoding="utf-8") for name in GUARDED}
    everything = "\n".join(sources.values())
    # Defined once; no handler checks isComposing on its own, which misses WebKit's confirm key.
    assert everything.count(".isComposing") == 1 and everything.count("keyCode === 229") == 1
    assert "return !!(e && (e.isComposing || e.keyCode === 229));" in sources["composer.js"]
    for name, sites in GUARDED.items():
        for site in sites:
            assert site in sources[name], (name, site)
