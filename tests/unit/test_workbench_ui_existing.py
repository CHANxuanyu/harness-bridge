"""UI-only checks for adding existing native sessions (static/existing.js and its wiring).

The paging/merge rules run in Node against contract-shaped synthetic pages
(docs/EXISTING_SESSIONS_API.md on the backend branch); the rest are static checks on the page
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

STATIC = Path(__file__).resolve().parents[2] / "src" / "harness_bridge" / "workbench" / "static"
SCRIPTS = ["markdown.js", "composer.js", "existing.js", "app.js"]


def _node(test: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the paging rules are also exercised in the UI checks")
    runner = f"""
const vm = require('vm');
const fs = require('fs');
const ctx = vm.createContext({{ console, Map, Set, URLSearchParams }});
vm.runInContext(fs.readFileSync({json.dumps(str(STATIC / "existing.js"))}, 'utf8'), ctx);
const out = vm.runInContext({json.dumps(test)}, ctx);
process.stdout.write(JSON.stringify(out));
"""
    done = subprocess.run([node, "-e", runner], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def page(items: list[dict[str, Any]], **page: Any) -> dict[str, Any]:
    base = {
        "state": "ready",
        "next_before": None,
        "next_since": "since-1",
        "has_more": False,
        "reset": False,
        "completeness": {"state": "complete", "reasons": []},
    }
    return {
        "items": items,
        "history": {"source": "claude-transcript", "error": None},
        "partial_reasons": [],
        "page": {**base, **page},
    }


def msg(i: int, **extra: Any) -> dict[str, Any]:
    return {"id": f"user:{i}", "type": "user", "text": f"m{i}", "history": True, **extra}


def test_newest_page_then_older_pages_prepend_without_duplicates() -> None:
    newest = page([msg(3), msg(4), msg(5)], next_before="b-1", has_more=True)
    older = page([msg(1), msg(2), msg(3, text="stale copy")], next_before=None, has_more=False)
    out = _node(
        f"""
const m = {{}};
pagerReplace(m, {json.dumps(newest)});
const first = {{
  order: m.order.slice(), hasMore: m.hasMore, nextBefore: m.nextBefore, paged: m.paged,
}};
const fresh = pagerPrepend(m, {json.dumps(older)});
({{ first, fresh, order: m.order, hasMore: m.hasMore, kept: m.items.get('user:3').text }})
"""
    )
    assert out["first"] == {
        "order": ["user:3", "user:4", "user:5"],
        "hasMore": True,
        "nextBefore": "b-1",
        "paged": True,
    }
    assert out["fresh"] == ["user:1", "user:2"]
    assert out["order"] == ["user:1", "user:2", "user:3", "user:4", "user:5"]
    assert out["hasMore"] is False
    assert out["kept"] == "m3"  # the newer version already loaded is not replaced by an old page


def test_since_refresh_updates_by_stable_id_and_appends_new_items() -> None:
    first = page(
        [msg(1), {"id": "toolu_1", "type": "tool", "status": "unknown"}, msg(2)],
        next_before="b-1",
        has_more=True,
    )
    delta = page(
        [{"id": "toolu_1", "type": "tool", "status": "ok", "output": "done"}, msg(3)],
        next_since="since-2",
    )
    out = _node(
        f"""
const m = {{}};
pagerReplace(m, {json.dumps(first)});
const r = pagerMerge(m, {json.dumps(delta)});
({{
  r, order: m.order, tool: m.items.get('toolu_1'), since: m.nextSince,
  before: m.nextBefore, hasMore: m.hasMore,
}})
"""
    )
    assert out["r"] == {"reset": False, "added": ["user:3"], "changed": ["toolu_1"]}
    assert out["order"] == ["user:1", "toolu_1", "user:2", "user:3"]  # updated in place
    assert out["tool"]["status"] == "ok" and out["tool"]["output"] == "done"
    assert out["since"] == "since-2"
    # A refresh never drops the way to older pages that are not loaded yet.
    assert out["before"] == "b-1" and out["hasMore"] is True


def test_reset_replaces_loaded_history() -> None:
    first = page([msg(1), msg(2)])
    reset = page([msg(7)], reset=True, next_before="b-9", has_more=True)
    out = _node(
        f"""
const m = {{}};
pagerReplace(m, {json.dumps(first)});
const r = pagerMerge(m, {json.dumps(reset)});
({{ r, order: m.order, hasMore: m.hasMore }})
"""
    )
    assert out == {
        "r": {"reset": True, "added": [], "changed": []},
        "order": ["user:7"],
        "hasMore": True,
    }


def test_unpaged_legacy_response_and_history_states() -> None:
    out = _node(
        """
const hist = (error) => ({ source: 'codex', error: error || null });
const legacy = {};
pagerReplace(legacy, { items: [{ id: 'a', type: 'user' }], history: hist() });
const st = (p, error) => {
  const m = {};
  pagerReplace(m, { items: [], history: hist(error), page: p });
  return historyState(m);
};
const done = (state, reasons) => ({ state, completeness: { state: 'x', reasons: reasons || [] } });
({
  legacy: { paged: legacy.paged, hasMore: legacy.hasMore, state: historyState(legacy).state },
  empty: st(done('empty')).state,
  partial: st(done('partial', ['native_file_limit'])),
  unavailable: st(done('unavailable'), 'boom'),
})
"""
    )
    assert out["legacy"] == {"paged": False, "hasMore": False, "state": "legacy"}
    assert out["empty"] == "empty"  # a successful empty read, never a failure
    assert out["partial"] == {"state": "partial", "reasons": ["native_file_limit"], "error": None}
    assert out["unavailable"]["state"] == "unavailable" and out["unavailable"]["error"] == "boom"


def test_failures_are_classified_by_code_and_details_not_message_text() -> None:
    out = _node(
        """
const f = (code, details, message) => historyFailure({ code, details, message }).kind;
({
  expired: f('STATE_CONFLICT', { reason: 'cursor_expired' }, 'anything'),
  conflict: f('STATE_CONFLICT', {}, 'History cursor expired; reload the first page'),
  unsupported: f('PREFLIGHT_FAILED', {}, 'x'),
  gone: f('NOT_FOUND', {}, 'x'),
  other: f('INVALID_INPUT', {}, 'x'),
})
"""
    )
    assert out == {
        "expired": "expired",
        "conflict": "error",
        "unsupported": "unsupported",
        "gone": "gone",
        "other": "error",
    }


def test_existing_session_ui_uses_only_contract_routes() -> None:
    src = (STATIC / "existing.js").read_text(encoding="utf-8")
    calls = re.findall(r"api\('(GET|POST)', `([^`]*)`", src) + re.findall(
        r"api\('(GET|POST)', '([^']*)'", src
    )
    routes = {(m, re.sub(r"\$\{[^}]*\}", "X", p).split("?")[0]) for m, p in calls}
    assert routes == {
        ("GET", "/api/history"),
        ("GET", "/api/history/X"),
        ("POST", "/api/sessions/link"),
        ("POST", "/api/sessions/X/unlink"),
        ("POST", "/api/sessions/X/desktop/return"),
    }
    # The linked local session ID is read from result.session.session (the full session detail).
    assert "res.session && res.session.session" in src and "session.session_id" in src


def test_page_never_reads_vendor_storage_and_never_polls_discovery() -> None:
    for name in SCRIPTS:
        src = (STATIC / name).read_text(encoding="utf-8")
        for needle in (".claude/projects", "/.codex", ".jsonl", "sqlite"):
            assert needle not in src, f"{name} mentions vendor storage: {needle}"
    existing = (STATIC / "existing.js").read_text(encoding="utf-8")
    assert "setInterval" not in existing
    # Discovery/preview requests only run from user actions; none sits inside a timer except the
    # search debounce, which calls discover() once per edit.
    assert existing.count("setTimeout(") == 2


def test_scripts_load_in_order_without_top_level_name_clashes() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    order = re.findall(r'<script src="/static/([a-z]+\.js)"></script>', html)
    assert order == SCRIPTS
    seen: dict[str, str] = {}
    for name in SCRIPTS:
        src = (STATIC / name).read_text(encoding="utf-8")
        names = re.findall(r"^(?:async\s+)?(?:const|let|function|class)\s+([\w$]+)", src, re.M)
        for decl in names:
            assert decl not in seen, f"{decl} is declared in both {seen[decl]} and {name}"
            seen[decl] = name
