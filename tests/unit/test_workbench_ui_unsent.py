"""UI-only checks for messages that were sent but not delivered (static/composer.js store).

The store decides where an undelivered message goes; the page applies that to the input box. These
run the store in Node through the scenarios that lose text if handled wrongly: empty box, a new
draft typed meanwhile, another session in view, attachments, and a delivery report that arrives
after the copy was kept. No server, no CLI, no network.
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

SETUP = """
const st = unsentStore();
const att = (id) => ({ id, name: id + '.png', kind: 'image' });
const send = (cid, text, atts, sid) =>
  unsentTrack(st, { sid: sid || 's1', clientId: cid, text, atts: atts || [], at: 0 });
const box = (draft, attIds, visible) =>
  ({ visible: visible !== false, draft: draft || '', attIds: attIds || [] });
const held = (sid) => (st.held.get(sid || 's1') || []).map((e) => e.clientId);
"""


def _node(test: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    runner = f"""
const vm = require('vm');
const fs = require('fs');
const ctx = vm.createContext({{ console, Map, Set }});
vm.runInContext(fs.readFileSync({json.dumps(str(STATIC / "composer.js"))}, 'utf8'), ctx);
vm.runInContext({json.dumps(SETUP)}, ctx);
const out = vm.runInContext({json.dumps(test)}, ctx);
process.stdout.write(JSON.stringify(out));
"""
    done = subprocess.run([node, "-e", runner], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_empty_box_gets_the_text_back_once() -> None:
    out = _node(
        """
send('c1', '原消息', [att('a1')]);
const first = unsentFail(st, 's1', 'c1', box(''));
// The backend's failed item and the ended run both report it: restored only once.
const second = unsentFail(st, 's1', 'c1', box(''));
const atts = first.entry.atts.map((a) => a.id);
({ to: first.to, text: first.entry.text, atts, second, held: held() })
"""
    )
    assert out == {"to": "box", "text": "原消息", "atts": ["a1"], "second": None, "held": []}


def test_new_draft_is_never_overwritten_and_the_original_is_kept_visible() -> None:
    out = _node(
        """
send('c1', '原消息');
const r = unsentFail(st, 's1', 'c1', box('等待时写的新草稿'));
const withAtts = (send('c2', '第二条'), unsentFail(st, 's1', 'c2', box('', ['pending-upload'])));
({ r: { to: r.to, visible: r.visible }, withAtts: withAtts.to, held: held() })
"""
    )
    # Not put into the box (it has a draft, or attachments of a new message): kept above it.
    assert out == {"r": {"to": "held", "visible": True}, "withAtts": "held", "held": ["c1", "c2"]}


def test_another_session_in_view_keeps_the_copy_with_its_own_session() -> None:
    out = _node(
        """
send('c1', 'A 会话里的消息', [], 'A');
const r = unsentFail(st, 'A', 'c1', box('', [], false));
({ to: r.to, visible: r.visible, heldA: held('A'), heldB: held('B') })
"""
    )
    assert out == {"to": "held", "visible": False, "heldA": ["c1"], "heldB": []}


def test_attachments_are_merged_without_duplicates() -> None:
    out = _node(
        """
const list = [att('a1')];
const first = mergeAttachments(list, [att('a1'), att('a2')]).map((a) => a.id);
const again = mergeAttachments(list, [att('a1'), att('a2')]).map((a) => a.id);
({ first, again, list: list.map((a) => a.id) })
"""
    )
    assert out == {"first": ["a2"], "again": [], "list": ["a1", "a2"]}


def test_late_delivery_report_takes_back_only_an_untouched_copy() -> None:
    out = _node(
        """
send('c1', '已放回'); unsentFail(st, 's1', 'c1', box(''));
const cleared = unsentDelivered(st, 's1', 'c1', box('已放回')).to;
send('c2', '被改过'); unsentFail(st, 's1', 'c2', box(''));
const edited = unsentDelivered(st, 's1', 'c2', box('被改过，又加了一句')).to;
send('c3', '保留在上方'); unsentFail(st, 's1', 'c3', box('新草稿'));
const unheld = unsentDelivered(st, 's1', 'c3', box('新草稿')).to;
const repeat = unsentDelivered(st, 's1', 'c3', box('新草稿'));
({ cleared, edited, unheld, repeat, held: held() })
"""
    )
    assert out == {
        "cleared": "cleared",
        "edited": "edited",
        "unheld": "unheld",
        "repeat": None,
        "held": [],
    }


def test_delivered_messages_are_never_restored_and_a_resend_releases_the_copy() -> None:
    out = _node(
        """
send('c1', '正常送达');
const delivered = unsentDelivered(st, 's1', 'c1', box('')).to;
const afterDelivered = unsentFail(st, 's1', 'c1', box(''));
send('c2', '放回后又发送'); unsentFail(st, 's1', 'c2', box(''));
unsentReleaseBox(st, 's1');  // the user sent from the box again
const late = unsentDelivered(st, 's1', 'c2', box(''));
send('c3', '放回输入框'); unsentFail(st, 's1', 'c3', box('草稿'));
const taken = unsentTake(st, 's1', 'c3').text;
const takenTwice = unsentTake(st, 's1', 'c3');
({ delivered, afterDelivered, late, taken, takenTwice })
"""
    )
    assert out == {
        "delivered": "delivered",
        "afterDelivered": None,
        "late": None,
        "taken": "放回输入框",
        "takenTwice": None,
    }


def test_the_page_tracks_the_same_client_id_it_sends() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    send = app[app.index("async function sendFromComposer") :]
    send = send[: send.index("\nfunction ")]
    # The ID in the request, the tracked entry and the CLI's user item (user:<client_id>) match,
    # so the backend marking a queued message failed and the run ending cannot restore it twice.
    assert re.search(r"client_id: clientId", send)
    assert "unsentTrack(S.unsent, { sid, clientId," in send
    composer = (STATIC / "composer.js").read_text(encoding="utf-8")
    assert "item.id.startsWith('user:')" in composer and "`user:${e.clientId}`" in app
    # The old helper that dropped the text when a draft existed is gone.
    assert "restoreUnsent" not in app


def test_receipt_states_map_to_outcomes() -> None:
    out = _node(
        """
const o = (delivery, status) => deliveryOutcome({ type: 'user', status, delivery });
({
  queued: o({ state: 'queued' }, 'sending'),
  sending: o({ state: 'sending' }, 'sending'),
  notSent: o({ state: 'not_sent' }, 'failed'),
  sent: o({ state: 'sent' }, 'sent'),
  unknown: o({ state: 'unknown' }, 'unknown'),
  claudeEcho: o(undefined, 'sent'),
  claudeFailed: o(undefined, 'failed'),
  nothing: deliveryOutcome(null),
})
"""
    )
    assert out == {
        "queued": "pending",
        "sending": "pending",
        "notSent": "not_sent",
        "sent": "sent",
        "unknown": "unknown",
        "claudeEcho": "sent",
        "claudeFailed": "not_sent",
        "nothing": None,
    }


def test_unknown_is_kept_apart_never_restored_as_unsent_and_blocks_only_with_a_receipt() -> None:
    out = _node(
        """
send('c1', '可能已送达', [att('a1')]);
const info = (message) => ({ receipt: true, reason: 'native_process_exited', message });
const r = unsentUnknown(st, 's1', 'c1', info('m'));
const again = unsentUnknown(st, 's1', 'c1', info('m2'));
const blocking = unsentBlocking(st, 's1') && unsentBlocking(st, 's1').clientId;
const cannotDismiss = unsentDismiss(st, 's1', 'c1');
send('c2', '没有回执的会话');
unsentUnknown(st, 's1', 'c2', { receipt: false, message: 'no receipt' });
const uncertain = (st.uncertain.get('s1') || []).map((e) => [e.clientId, e.receipt]);
const dismissed = unsentDismiss(st, 's1', 'c2').clientId;
({ to: r.to, adopted: r.adopted, againUpdated: again.updated, blocking, cannotDismiss,
   uncertain, dismissed, held: held(), placed: [...st.placed.keys()] })
"""
    )
    assert out["to"] == "uncertain" and out["adopted"] is False and out["againUpdated"] is True
    assert out["blocking"] == "c1"  # a receipt-backed unknown waits for evidence
    assert out["cannotDismiss"] is None  # only native evidence resolves it
    assert out["uncertain"] == [["c1", True], ["c2", False]]
    assert out["dismissed"] == "c2"  # no receipt: the user may remove the kept copy after checking
    assert out["held"] == [] and out["placed"] == []  # never put back as a definite failure


def test_late_sent_resolves_unknown_and_a_reload_adopts_the_receipt_once() -> None:
    out = _node(
        """
send('c1', '提交后失去回复');
unsentUnknown(st, 's1', 'c1', { receipt: true });
const resolved = unsentDelivered(st, 's1', 'c1', box('新草稿')).to;
const afterResolve = unsentBlocking(st, 's1');
const lateFail = unsentFail(st, 's1', 'c1', box(''));
// After a page reload nothing is tracked: the receipt in the history is adopted, once.
const item = { client_id: 'r1', text: '重启前的消息',
  attachments: [att('x1'), { name: 'no-id' }] };
const adopted = unsentUnknown(st, 's2', 'r1', { receipt: true }, item);
const twice = unsentUnknown(st, 's2', 'r1', { receipt: true }, item);
const bare = unsentUnknown(st, 's2', 'r2', { receipt: true });
const adoptedView = [adopted.to, adopted.adopted, adopted.entry.atts.length];
({ resolved, afterResolve, lateFail, adopted: adoptedView,
   twice: twice.updated, bare, heldS2: held('s2') })
"""
    )
    assert out["resolved"] == "resolved" and out["afterResolve"] is None
    assert out["lateFail"] is None  # a confirmed message is never downgraded
    assert out["adopted"] == ["uncertain", True, 1]  # attachment references with an ID only
    assert out["twice"] is True and out["bare"] is None and out["heldS2"] == []


def test_a_definite_failure_after_unknown_follows_the_not_sent_rules_once() -> None:
    out = _node(
        """
send('c1', '原本不确定', [att('a1')]);
unsentUnknown(st, 's1', 'c1', { receipt: true });
const r = unsentFail(st, 's1', 'c1', box('新草稿'));
const again = unsentFail(st, 's1', 'c1', box(''));
({ to: r.to, again, uncertain: (st.uncertain.get('s1') || []).length, held: held() })
"""
    )
    assert out == {"to": "held", "again": None, "uncertain": 0, "held": ["c1"]}


# ---- sent is final: an older copy from any source never undoes a confirmed message

STALE = """
const sentItem = (cid) => ({ id: 'user:' + cid, type: 'user', client_id: cid, text: '已送达',
  status: 'sent', delivery: { state: 'sent', reason: null, message: '原生历史已确认这条消息。' } });
const older = (cid, state) => ({ id: 'user:' + cid, type: 'user', client_id: cid, text: '已送达',
  status: { unknown: 'unknown', not_sent: 'failed', sending: 'sending', queued: 'sending' }[state],
  delivery: { state, reason: 'native_process_exited', message: 'older' } });
const shown = (it) => [deliveryOutcome(it), it.status, it.delivery ? it.delivery.state : null];
"""


def test_sent_first_seen_after_a_reload_is_never_undone_by_an_older_copy() -> None:
    # A fresh page: nothing tracked or kept. The history says sent; older copies arrive afterwards.
    out = _node(
        STALE
        + """
const first = deliveryView(st, 's1', sentItem('c1'));
const unknown = unsentUnknown(st, 's1', 'c1', { receipt: true }, older('c1', 'unknown'));
const failed = unsentFail(st, 's1', 'c1', box(''));
({
  first: first.status,
  unknown, failed,
  blocking: unsentBlocking(st, 's1'),
  held: held(), uncertain: (st.uncertain.get('s1') || []).length,
  views: ['unknown', 'not_sent', 'sending', 'queued']
    .map((s) => shown(deliveryView(st, 's1', older('c1', s)))),
})
"""
    )
    assert out["first"] == "sent"
    assert out["unknown"] is None and out["failed"] is None  # no card, no "放回输入框"
    assert out["blocking"] is None and out["held"] == [] and out["uncertain"] == 0
    assert out["views"] == [["sent", "sent", "sent"]] * 4  # cache and bubble stay sent


def test_a_confirmation_without_any_kept_copy_is_still_remembered() -> None:
    # The receipt query or event says sent while nothing is kept for it on this page.
    out = _node(
        STALE
        + """
const r = unsentDelivered(st, 's1', 'c1', box('草稿'), sentItem('c1').delivery);
const later = unsentUnknown(st, 's1', 'c1', { receipt: true }, older('c1', 'unknown'));
const view = shown(deliveryView(st, 's1', older('c1', 'not_sent')));
const message = deliveryView(st, 's1', older('c1', 'unknown')).delivery.message;
const track = unsentTrack(st, { sid: 's1', clientId: 'c1', text: 'x', atts: [], at: 0 });
({ r, later, view, message, track })
"""
    )
    assert out["r"] is None and out["later"] is None
    assert out["view"] == ["sent", "sent", "sent"]
    assert out["message"] == "原生历史已确认这条消息。"  # the confirmed receipt, not the older one
    assert out["track"] is False  # a /send answer arriving after its own event tracks nothing


def test_confirmation_belongs_to_one_session_and_client_id() -> None:
    out = _node(
        STALE
        + """
deliveryView(st, 's1', sentItem('c1'));
({
  otherSession: shown(deliveryView(st, 's2', older('c1', 'unknown'))),
  otherMessage: shown(deliveryView(st, 's1', older('c2', 'unknown'))),
  adoptedElsewhere: unsentUnknown(st, 's2', 'c1', { receipt: true }, older('c1', 'unknown')).to,
})
"""
    )
    assert out["otherSession"] == ["unknown", "unknown", "unknown"]
    assert out["otherMessage"] == ["unknown", "unknown", "unknown"]
    assert out["adoptedElsewhere"] == "uncertain"


def test_confirmed_and_recovered_are_separate_records() -> None:
    out = _node(
        STALE
        + """
// Recovered once (put back) but not confirmed: an older unknown neither re-keeps it nor shows sent.
send('c1', '放回过'); const back = unsentFail(st, 's1', 'c1', box('')).to;
const reKept = unsentUnknown(st, 's1', 'c1', { receipt: true }, older('c1', 'unknown'));
const notConfirmed = shown(deliveryView(st, 's1', older('c1', 'not_sent')));
// Then really confirmed: the untouched copy leaves the box; older copies now show sent.
const late = unsentDelivered(st, 's1', 'c1', box('放回过'), sentItem('c1').delivery).to;
const afterwards = [unsentFail(st, 's1', 'c1', box('')),
  shown(deliveryView(st, 's1', older('c1', 'not_sent')))];
// Confirmed without a recovery step: nothing was handled for it.
deliveryView(st, 's1', sentItem('c9'));
({ back, reKept, notConfirmed, late, afterwards,
   handled: [...st.handled], confirmed: st.confirmed.size })
"""
    )
    assert out["back"] == "box" and out["reKept"] is None
    assert out["notConfirmed"] == ["not_sent", "failed", "not_sent"]
    assert out["late"] == "cleared"
    assert out["afterwards"] == [None, ["sent", "sent", "sent"]]
    assert out["handled"] == ["c1"] and out["confirmed"] == 2


def test_claude_echo_without_receipt_also_stays_sent() -> None:
    out = _node(
        """
const echo = { id: 'user:k1', type: 'user', client_id: 'k1', text: '你好', status: 'sent' };
deliveryView(st, 's1', echo);
const stale = deliveryView(st, 's1', { ...echo, status: 'failed' });
({ status: stale.status, hasDelivery: 'delivery' in stale, outcome: deliveryOutcome(stale) })
"""
    )
    assert out == {"status": "sent", "hasDelivery": False, "outcome": "sent"}


def test_every_cache_write_in_the_page_goes_through_the_delivery_view() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    # Events (onConv), receipts that move a bubble, and each kind of history page.
    assert "c.items.set(msg.item.id, deliveryView(S.unsent, msg.session_id," in app
    assert "c.items.set(id, deliveryView(S.unsent, sid," in app
    for pager in ("pagerReplace", "pagerMerge", "pagerPrepend"):
        assert f"{pager}(c, data);\n    viewItems(" in app, pager
    # No other writes of user items into the conversation cache.
    writes = re.findall(r"c\.items\.set\([^;]*", app)
    assert all("deliveryView" in w or w.startswith("c.items.set(id, v)") for w in writes), writes
