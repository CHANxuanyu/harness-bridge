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


def _node_page(test: str) -> Any:
    """Run `test` (an async function body) against context.js with a controllable `api`."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the context rules are also exercised in the UI checks")
    stubs = """
var S = {};
var findSession = () => null;
var convFor = () => ({ items: new Map() });
var updateConvChrome = () => {};
var scheduled = [];
var setTimeout = (fn, ms) => { scheduled.push(ms); return scheduled.length; };
var clearTimeout = () => {};
var calls = [];
var api = (method, path) => new Promise((resolve, reject) =>
  calls.push({ method, path, resolve, reject }));
"""
    runner = f"""
const vm = require('vm');
const fs = require('fs');
const ctx = vm.createContext({{ console }});
vm.runInContext({json.dumps(stubs)}, ctx);
vm.runInContext(fs.readFileSync({json.dumps(str(STATIC / "context.js"))}, 'utf8'), ctx);
Promise.resolve(vm.runInContext({json.dumps(f"(async () => {{ {test} }})()")}, ctx)).then(
  (out) => process.stdout.write(JSON.stringify(out)),
  (e) => {{ console.error(e); process.exit(1); }});
"""
    done = subprocess.run([node, "-e", runner], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


SNAP = """
const sid = 'ses_1';
const snap = (run_seq, revision, closed, extra) => Object.assign({
  session_id: sid, run_id: 'run-' + run_seq, order: { run_seq, revision, closed },
  usage: { used_tokens: 1000 * revision, capacity_tokens: 200000, stale: false },
  compaction: { status: 'idle' },
}, extra || {});
const held = () => {
  const c = contextOf(sid);
  return c && {
    rev: c.order && c.order.revision, run: c.run_id, closed: c.order && c.order.closed,
    used: c.usage && c.usage.used_tokens, comp: c.compaction && c.compaction.status,
    caps: c.capabilities, readError: !!c.readError, missing: !!c.missing,
    receipt: 'request_receipt' in c,
  };
};
"""


def test_context_snapshots_are_ordered_by_run_closed_revision() -> None:
    out = _node(
        """
const s = (run_seq, revision, closed, run_id) => ({
  session_id: 'a', run_id: run_id || 'r' + run_seq, order: { run_seq, revision, closed },
});
const v = (prev, next) => contextVerdict(prev, next, 'a');
({
  newerRevision: v(s(1, 3, false), s(1, 5, false)),
  olderRevision: v(s(1, 5, false), s(1, 3, false)),
  equal: v(s(1, 5, false), s(1, 5, false)),
  closedBeatsHigherLive: v(s(1, 9, false), s(1, 2, true)),
  liveAfterClosed: v(s(1, 2, true), s(1, 9, false)),
  newRunAfterClosed: v(s(1, 9, true), s(2, 1, false)),
  oldRunLate: v(s(2, 1, false), s(1, 40, false)),
  otherSession: contextVerdict(s(1, 1, false), { ...s(1, 2, false), session_id: 'b' }, 'a'),
  sameSeqOtherRun: v(s(2, 1, false), s(2, 4, false, 'other')),
  unorderedOverOrdered: v(s(1, 1, false), { session_id: 'a', usage: {} }),
  olderAppBothUnordered: v({ usage: {} }, { usage: {} }),
  first: v(null, s(1, 1, false)),
})
"""
    )
    assert out == {
        "newerRevision": "accept",
        "olderRevision": "older",
        "equal": "equal",
        "closedBeatsHigherLive": "accept",
        "liveAfterClosed": "older",
        "newRunAfterClosed": "accept",
        "oldRunLate": "older",
        "otherSession": "other-session",
        "sameSeqOtherRun": "conflict",
        "unorderedOverOrdered": "unordered",
        "olderAppBothUnordered": "compat",
        "first": "accept",
    }


def test_usage_and_compaction_are_taken_together_from_the_winning_snapshot() -> None:
    out = _node_page(
        SNAP
        + """
const steps = {};
steps.first = putContext(sid, snap(1, 5, false, { compaction: { status: 'running' } }));
// A late, older snapshot: neither its usage nor its "completed" compaction is merged in.
steps.late = putContext(sid, snap(1, 3, false, { compaction: { status: 'completed' } }));
steps.afterLate = held();
// The run closes: its tombstone wins over the higher live revision.
steps.closed = putContext(sid, snap(1, 2, true, { compaction: { status: 'unknown' } }));
steps.liveAfterClose = putContext(sid, snap(1, 9, false));
steps.afterClose = held();
steps.newRun = putContext(sid, snap(2, 1, false));
steps.otherSession = putContext(sid, Object.assign(snap(3, 1, false), { session_id: 'ses_2' }));
steps.conflict = putContext(sid, Object.assign(snap(2, 7, false), { run_id: 'run-x' }));
steps.unordered = putContext(sid, { usage: { used_tokens: 1 }, compaction: { status: 'failed' } });
steps.afterInvalid = held();
// A repeated compact answer: current state plus an old request's receipt, which is not state.
steps.reused = putContext(sid, Object.assign(
  snap(2, 8, false, { compaction: { status: 'running' } }),
  { request_receipt: { status: 'completed' }, reused: true }));
steps.afterReused = held();
// The same state read again only refreshes its capabilities.
const caps = { compact: { available: false } };
steps.equal = putContext(sid, Object.assign(snap(2, 8, false), { capabilities: caps }));
steps.afterEqual = held();
return steps;
"""
    )
    assert out["first"] is True and out["late"] is False
    assert out["afterLate"]["rev"] == 5 and out["afterLate"]["used"] == 5000
    assert out["afterLate"]["comp"] == "running"
    assert out["closed"] is True and out["liveAfterClose"] is False
    assert out["afterClose"] == {**out["afterClose"], "rev": 2, "closed": True, "comp": "unknown"}
    assert out["newRun"] is True
    assert out["otherSession"] is False and out["conflict"] is False and out["unordered"] is False
    assert out["afterInvalid"]["run"] == "run-2" and out["afterInvalid"]["rev"] == 1
    assert out["reused"] is True and out["afterReused"]["comp"] == "running"
    assert out["afterReused"]["receipt"] is False
    assert out["equal"] is False and out["afterEqual"]["caps"] == {"compact": {"available": False}}
    assert out["afterEqual"]["comp"] == "running"


def test_read_failures_keep_values_and_never_mark_newer_data_failed() -> None:
    out = _node_page(
        SNAP
        + """
const r = {};
putContext(sid, snap(1, 5, false));
// 1. A read fails after a newer event arrived: the failure is about older data, not shown.
let p = fetchContext(sid);
putContext(sid, snap(1, 6, false));
calls.shift().reject({ code: 'INTERNAL', message: 'boom' });
await p;
r.afterNewerEvent = held();
// 2. An older read fails after a newer read succeeded.
const p1 = fetchContext(sid); const c1 = calls.shift();
const p2 = fetchContext(sid); const c2 = calls.shift();
c2.resolve(snap(1, 7, false));
await p2;
c1.reject({ code: 'INTERNAL', message: 'late' });
await p1;
r.afterNewerRead = held();
// 3. Nothing newer: the failure is shown and the last accepted values stay, as stale.
p = fetchContext(sid);
calls.shift().reject({ code: 'INTERNAL', message: '读取超时' });
await p;
r.failed = held();
const v = contextView(contextOf(sid));
r.view = { readFailed: v.readFailed, stale: v.stale, tone: v.tone, text: v.text };
// 4. A newer event clears it.
putContext(sid, snap(1, 8, false));
r.afterEvent = held();
// 5. A later successful read clears a failure even when it brings nothing newer.
p = fetchContext(sid); calls.shift().reject({ code: 'INTERNAL', message: 'x' }); await p;
p = fetchContext(sid); calls.shift().resolve(snap(1, 8, false)); await p;
r.afterEqualRead = held();
// 6. 404 from an App without the interface marks "missing" only when nothing versioned is held.
S.ctx.delete(sid);
p = fetchContext(sid); calls.shift().reject({ code: 'NOT_FOUND', message: 'no' }); await p;
r.missing = held();
return r;
"""
    )
    assert out["afterNewerEvent"]["rev"] == 6 and out["afterNewerEvent"]["readError"] is False
    assert out["afterNewerRead"]["rev"] == 7 and out["afterNewerRead"]["readError"] is False
    assert out["failed"]["readError"] is True and out["failed"]["rev"] == 7
    assert out["failed"]["used"] == 7000
    assert out["view"] == {"readFailed": True, "stale": True, "tone": "warn", "text": "≈4%"}
    assert out["afterEvent"]["readError"] is False and out["afterEvent"]["rev"] == 8
    assert out["afterEqualRead"]["readError"] is False
    assert out["missing"]["missing"] is True


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
        reason = out[key]["reason"]
        assert "开头加一个空格" in reason and "Codex 会按原文接收" in reason, key
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
   text: r('review /tmp please', cat) }})
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
    assert out["text"] == {"kind": "text"}
    # No Claude Code refusal promises that a leading space makes "/…" ordinary text.
    assert not any("加一个空格" in v.get("reason", "") for v in out.values())


def test_claude_slash_text_is_refused_not_sent_or_compacted() -> None:
    # Claude Code trims before reading "/": leading blanks or line breaks do not make it text.
    out = _node(
        """
const cat = [{name: 'compact'}, {name: 'review'}];
const texts = [' /compact', '\\n/compact', '  /review 12', '/', '/1x', '\\t/nope'];
texts.map((t) => slashRoute('claude-code', t, cat))
"""
    )
    for route in out:
        assert route["kind"] == "refuse" and route["code"] == "native_text_ambiguous"
        assert "不能作为普通文字发送" in route["reason"] and "草稿和附件都还在" in route["reason"]
        assert "加一个空格" not in route["reason"]
    # Codex receives text as written: the same text is an ordinary message there.
    codex = _node("[' /compact', '\\n/compact'].map((t) => slashRoute('codex', t, []))")
    assert codex == [{"kind": "text"}, {"kind": "text"}]


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


def test_refused_slash_text_is_shown_above_the_kept_draft() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    composer = (STATIC / "composer.js").read_text(encoding="utf-8")
    context = (STATIC / "context.js").read_text(encoding="utf-8")
    # Not a toast over the input box: a line above it, cleared when the draft changes.
    assert "if (route.kind === 'refuse') { composerNotice(sid, route.reason); return; }" in app
    assert "if (S.composerNotes) S.composerNotes.delete(sid);" in composer
    assert "fromComposer ? composerNotice(sid, m) : toast(m, 'error')" in context
    # The Ultracode refusal of a terminal switch offers the off switch, at the current button.
    assert "e.details.reason === 'ultracode_terminal_not_integrated'" in app
    assert "confirmPopover(toggleNow()" in app


def test_composer_has_no_harness_switcher() -> None:
    composer = (STATIC / "composer.js").read_text(encoding="utf-8")
    bar = composer.split("function renderControls(s) {", 1)[1].split("\n}\n", 1)[0]
    assert "harness" not in re.sub(r"s\.harness|HARNESS\[s\.harness\]", "", bar)


def test_test_identity_and_catalog_provenance_come_from_the_app() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    composer = (STATIC / "composer.js").read_text(encoding="utf-8")
    # A persistent badge from /api/state.runtime (sidebar footer, toolbar when the sidebar is
    # hidden), with the exact build one click away; production shows no badge.
    assert 'id="runtime-slot"' in html
    assert "S.state.runtime" in app
    assert "const PROFILE_LABEL = { test: '测试环境', dev: '开发环境' };" in app
    assert app.count("runtimeBadge()") >= 2 and "code_sha" in app and "code_dirty" in app
    # A demo catalog says what it is, from the App's provenance, not from a model name.
    assert "const prov = cat.provenance || null;" in composer
    assert "c.provenance" in app and "provenanceText(" in app


def test_test_instance_is_named_in_the_native_window_title() -> None:
    assert window_title("test")(None) == f"RepoBridge — {TEST_TITLE}"
    assert window_title("test")("修复导出金额精度") == f"修复导出金额精度 — {TEST_TITLE}"
    assert window_title("default")("修复导出金额精度") == "修复导出金额精度"
    assert window_title(None)(None) == "RepoBridge"
