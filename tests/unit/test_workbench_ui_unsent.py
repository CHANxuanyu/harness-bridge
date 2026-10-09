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
const first = unsentFail(st, 'c1', box(''));
// The backend's failed item and the ended run both report it: restored only once.
const second = unsentFail(st, 'c1', box(''));
const atts = first.entry.atts.map((a) => a.id);
({ to: first.to, text: first.entry.text, atts, second, held: held() })
"""
    )
    assert out == {"to": "box", "text": "原消息", "atts": ["a1"], "second": None, "held": []}


def test_new_draft_is_never_overwritten_and_the_original_is_kept_visible() -> None:
    out = _node(
        """
send('c1', '原消息');
const r = unsentFail(st, 'c1', box('等待时写的新草稿'));
const withAtts = (send('c2', '第二条'), unsentFail(st, 'c2', box('', ['pending-upload'])));
({ r: { to: r.to, visible: r.visible }, withAtts: withAtts.to, held: held() })
"""
    )
    # Not put into the box (it has a draft, or attachments of a new message): kept above it.
    assert out == {"r": {"to": "held", "visible": True}, "withAtts": "held", "held": ["c1", "c2"]}


def test_another_session_in_view_keeps_the_copy_with_its_own_session() -> None:
    out = _node(
        """
send('c1', 'A 会话里的消息', [], 'A');
const r = unsentFail(st, 'c1', box('', [], false));
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
send('c1', '已放回'); unsentFail(st, 'c1', box(''));
const cleared = unsentDelivered(st, 'c1', box('已放回')).to;
send('c2', '被改过'); unsentFail(st, 'c2', box(''));
const edited = unsentDelivered(st, 'c2', box('被改过，又加了一句')).to;
send('c3', '保留在上方'); unsentFail(st, 'c3', box('新草稿'));
const unheld = unsentDelivered(st, 'c3', box('新草稿')).to;
const repeat = unsentDelivered(st, 'c3', box('新草稿'));
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
const delivered = unsentDelivered(st, 'c1', box('')).to;
const afterDelivered = unsentFail(st, 'c1', box(''));
send('c2', '放回后又发送'); unsentFail(st, 'c2', box(''));
unsentReleaseBox(st, 's1');  // the user sent from the box again
const late = unsentDelivered(st, 'c2', box(''));
send('c3', '放回输入框'); unsentFail(st, 'c3', box('草稿'));
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
    assert "item.id.startsWith('user:')" in app and "`user:${e.clientId}`" in app
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
const r = unsentUnknown(st, 'c1', info('m'));
const again = unsentUnknown(st, 'c1', info('m2'));
const blocking = unsentBlocking(st, 's1') && unsentBlocking(st, 's1').clientId;
const cannotDismiss = unsentDismiss(st, 's1', 'c1');
send('c2', '没有回执的会话');
unsentUnknown(st, 'c2', { receipt: false, message: 'no receipt' });
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
unsentUnknown(st, 'c1', { receipt: true });
const resolved = unsentDelivered(st, 'c1', box('新草稿')).to;
const afterResolve = unsentBlocking(st, 's1');
const lateFail = unsentFail(st, 'c1', box(''));
// After a page reload nothing is tracked: the receipt in the history is adopted, once.
const item = { sid: 's2', client_id: 'r1', text: '重启前的消息',
  attachments: [att('x1'), { name: 'no-id' }] };
const adopted = unsentUnknown(st, 'r1', { receipt: true }, item);
const twice = unsentUnknown(st, 'r1', { receipt: true }, item);
const bare = unsentUnknown(st, 'r2', { receipt: true });
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
unsentUnknown(st, 'c1', { receipt: true });
const r = unsentFail(st, 'c1', box('新草稿'));
const again = unsentFail(st, 'c1', box(''));
({ to: r.to, again, uncertain: (st.uncertain.get('s1') || []).length, held: held() })
"""
    )
    assert out == {"to": "held", "again": None, "uncertain": 0, "held": ["c1"]}
