"""UI-only checks for native context and commands in the conversation view (static/context.js).

The routing and display rules run in Node against contract-shaped synthetic snapshots
(docs/NATIVE_CONTEXT_API.md on the backend branch); the rest are static checks on the page
sources. No server, no CLI, no network.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.workbench.app import TEST_TITLE, window_title

STATIC = Path(__file__).resolve().parents[2] / "src" / "harness_bridge" / "workbench" / "static"


def _node(test: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the context rules are also exercised in the UI checks")
    runner = f"""
const vm = require('vm');
const fs = require('fs');
const ctx = vm.createContext({{ console, Map, Set }});
vm.runInContext(fs.readFileSync({json.dumps(str(STATIC / "context.js"))}, 'utf8'), ctx);
const out = vm.runInContext({json.dumps(test)}, ctx);
process.stdout.write(JSON.stringify(out));
"""
    done = subprocess.run([node, "-e", runner], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def usage(used: int | None, cap: int | None = 272000, **extra: Any) -> dict[str, Any]:
    return {
        "used_tokens": used,
        "capacity_tokens": cap,
        "capacity_kind": "model_context_window",
        "stale": False,
        "reason": None,
        **extra,
    }


def view(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = _node(
        f"const v = contextView({json.dumps(snapshot)}); "
        "({ text: v.text, tone: v.tone, pct: v.pct, busy: v.busy, known: v.known, stale: v.stale })"
    )
    return out


def test_slash_parsing_only_takes_a_leading_command() -> None:
    out = _node(
        """
[parseSlash('/compact'), parseSlash('/compact  \\n'), parseSlash('/review pr 12'),
 parseSlash(' /compact'), parseSlash('see /compact'), parseSlash('/'), parseSlash('/1x')]
"""
    )
    assert out == [
        {"name": "compact", "args": ""},
        {"name": "compact", "args": ""},
        {"name": "review", "args": "pr 12"},
        None,
        None,
        None,
        None,
    ]


def test_codex_slash_commands_follow_its_tui_and_never_become_prompts() -> None:
    out = _node(
        """
const r = (t) => slashRoute('codex', t, []);
({ plain: r('hello'), compact: r('/compact'), compactArgs: r('/compact now'),
   model: r('/model'), modelArgs: r('/model gpt-6-astra'), mention: r('/mention'),
   review: r('/review'), quit: r('/quit') })
"""
    )
    assert out["plain"] == {"kind": "text"}
    assert out["compact"] == {"kind": "compact"}
    assert out["model"] == {"kind": "action", "name": "model"}
    assert out["mention"] == {"kind": "action", "name": "mention"}
    for key in ("compactArgs", "modelArgs", "review", "quit"):
        assert out[key]["kind"] == "refuse", key
        assert "开头加一个空格" in out[key]["reason"], key
    assert "Codex 终端界面" in out["review"]["reason"]


def test_claude_slash_commands_use_its_catalog_and_refuse_identity_changes() -> None:
    catalog = [{"name": "compact"}, {"name": "review"}, {"name": "clear"}]
    out = _node(
        f"""
const r = (t, c) => slashRoute('claude-code', t, c);
const cat = {json.dumps(catalog)};
({{ clear: r('/clear', cat), resume: r('/resume', cat), fork: r('/fork', cat),
   unknown: r('/nope', cat), noCatalog: r('/review', []), compact: r('/compact', cat),
   compactArgs: r('/compact keep tests', cat), review: r('/review pr 12', cat),
   plain: r(' /review', cat) }})
"""
    )
    for key in ("clear", "resume", "fork"):
        assert out[key]["kind"] == "refuse"
        assert "会话身份" in out[key]["reason"]
    assert out["unknown"]["kind"] == "refuse" and "命令目录里没有 /nope" in out["unknown"]["reason"]
    assert out["noCatalog"]["kind"] == "refuse" and "还没有取得" in out["noCatalog"]["reason"]
    assert out["compact"] == {"kind": "compact"}
    assert out["compactArgs"]["kind"] == "refuse"
    assert out["review"] == {"kind": "command", "name": "review", "args": "pr 12"}
    assert out["plain"] == {"kind": "text"}


def test_unknown_usage_stays_unknown() -> None:
    assert view(None) == {
        "text": "—",
        "tone": "",
        "pct": None,
        "busy": False,
        "known": False,
        "stale": False,
    }
    missing = view({"usage": usage(None, None, stale=True, reason="not_observed")})
    assert missing["known"] is False and missing["text"] == "—"
    bogus = view({"usage": usage(-5)})
    assert bogus["known"] is False


def test_usage_is_shown_as_reported_including_estimates_over_the_window() -> None:
    assert view({"usage": usage(35000)})["text"] == "13%"
    assert view({"usage": usage(800, 270000)})["text"] == "<1%"
    over = view({"usage": usage(300000)})
    assert over["pct"] == 110 and over["text"] == "110%" and over["tone"] == "warn"
    stale = view({"usage": usage(77000, stale=True, reason="compaction_changed_context")})
    assert stale["text"] == "≈28%" and stale["stale"] is True
    no_cap = view({"usage": usage(12000, None)})
    assert no_cap["text"] == "12k" and no_cap["pct"] is None


def test_a_started_compaction_is_never_shown_as_finished() -> None:
    for status in ("requested", "running"):
        v = view({"usage": usage(91000), "compaction": {"status": status}})
        assert v["busy"] is True and v["text"] == "压缩中", status
        # The global .busy class is the loading-button overlay (transparent text, no clicks).
        assert v["tone"] == "compacting", status
    done = view({"usage": usage(800, 270000), "compaction": {"status": "completed"}})
    assert done["busy"] is False and done["text"] == "<1%"
    failed = view({"compaction": {"status": "failed", "error": "native_connection_lost"}})
    assert failed["text"] == "压缩失败" and failed["tone"] == "bad"
    unknown = view({"compaction": {"status": "unknown"}})
    assert unknown["text"] == "压缩结果未知" and unknown["tone"] == "warn"
    known_unknown = view({"usage": usage(35000), "compaction": {"status": "unknown"}})
    assert known_unknown["text"] == "13%" and known_unknown["tone"] == "warn"


def test_token_counts_are_compact() -> None:
    counts = _node("[null, 999, 1234, 35000, 1500000].map(fmtTokens)")
    assert counts == ["—", "999", "1.2k", "35k", "1.5M"]


def test_context_script_is_loaded_between_composer_and_app() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    order = re.findall(r'<script src="/static/([\w.]+)"></script>', html)
    assert order.index("composer.js") < order.index("context.js") < order.index("app.js")


def test_input_bar_menus_announce_themselves_and_return_focus() -> None:
    composer = (STATIC / "composer.js").read_text(encoding="utf-8")
    context = (STATIC / "context.js").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function pushLayer(el, onClose, { returnFocus = null } = {})" in app
    # Pickers and the command menu share menuPanel; the context panel is a dialog.
    assert "'aria-haspopup': 'menu', 'aria-expanded': 'false'" in composer
    assert composer.count("{ returnFocus: opener }") >= 1
    assert "'aria-haspopup': 'dialog', 'aria-expanded': 'false'" in context
    assert "{ returnFocus: opener }" in context
    assert "role: 'menu'" in composer and "role: 'dialog'" in context


def test_pending_choices_sit_next_to_their_control_not_above_the_input() -> None:
    composer = (STATIC / "composer.js").read_text(encoding="utf-8")
    body = composer.split("function settingsStatus(s) {", 1)[1].split("\n}\n", 1)[0]
    # Only a refused choice is shown above the input box; pending ones are the control's note.
    assert "rec.state === 'failed'" in body
    assert "selected" not in body and "applying" not in body


def test_composer_has_no_harness_switcher() -> None:
    composer = (STATIC / "composer.js").read_text(encoding="utf-8")
    bar = composer.split("function renderControls(s) {", 1)[1].split("\n}\n", 1)[0]
    assert "harness" not in re.sub(r"s\.harness|HARNESS\[s\.harness\]", "", bar)


def test_test_instance_is_named_in_the_native_window_title() -> None:
    assert window_title("test")(None) == f"RepoBridge — {TEST_TITLE}"
    assert window_title("test")("修复导出金额精度") == f"修复导出金额精度 — {TEST_TITLE}"
    assert window_title("default")("修复导出金额精度") == "修复导出金额精度"
    assert window_title(None)(None) == "RepoBridge"
