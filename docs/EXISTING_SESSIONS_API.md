# Existing native sessions — frontend/backend contract v1

2026-10-09. Base: `ef75a625577c1848e1079dd6d487a5cdc3afa166` (code `2f26d23`).
Owner: Codex backend/integration. Implemented on `codex/existing-session-backend`.
The contract-first commit is `c20679e3d7e0915756a4901ab1b80a5ef91123c3`.
No frontend/native-shell files change. No new model allowance is granted.

## Boundary and ownership

Backend: Python, native protocols, state/migrations, HTTP/SSE and backend tests. Frontend: `static/**`,
UI-only `test_workbench_ui_*.py`, screenshots, **app.py and native_mac.py**. New native window hooks
need a backend route; coordinate before either owner edits the other's file. No new window hook is
needed here. Codex alone updates AGENTS, STATUS, HANDOFF, VALIDATION_MATRIX and DECISIONS; Opus puts
progress/interface requests in its commits and PR description. Codex folds them into shared docs at
integration. Do not edit separate sections of one shared document simultaneously.

Discovery is explicitly requested for one registered, non-archived project and one harness. Scope is
its exact root and workdirs already registered under it; other worktrees must be added as projects.
No global private-history scan, auth file read, vendor-store mutation, model message or native resume
is performed by discovery/preview/link/history. Codex discovery uses native `thread/list` with exact
cwd filters and `useStateDbOnly`; no unscoped fallback on unsupported versions. Claude discovery reads
only the corresponding project transcript directories and validates native UUID/cwd metadata.
Cloud, unsupported sources and unknown provenance must stay distinguishable; nothing is inferred
from title alone. Native environment = harness + canonical local storage root (opaque ID in API).

All routes retain the existing cookie/Host/Origin protection and envelope:
`{"ok":true,"result":...}` or `{"ok":false,"error":{"code":"...","message":"...","details":{...}}}`.
No frontend reads native files. Empty and error are different. No auto-start on link.

## Routes

| Request | Response / effect |
|---|---|
| `GET /api/history?project_id=prj_…&harness=claude-code&limit=20&q=fix&cursor=…` | Discovery page below; harness is `claude-code` or `codex`; q searches title/native ID for Claude, native title search for Codex. limit 1–100, default 20. Cursor opaque, bound to filters, expires on App restart; omit cursor to refresh. |
| `GET /api/history/<candidate_id>?limit=50&before=…&since=…` | Preview using the history page below. Candidate must have been discovered in this App instance; no arbitrary native ID/path lookup. before and since are mutually exclusive. |
| `POST /api/sessions/link` body `{"candidate_id":"nat_…","view_mode":"conversation"}` | `{"session":<existing session detail>,"created":true,"relinked":false}`. Defaults to conversation; terminal also supported. Atomic dedupe by harness/environment/native ID. Duplicate returns same session with created=false; relink after unlink reuses that session with relinked=true. Never starts/resumes/sends. |
| `GET /api/sessions/<id>/conversation?limit=50&before=…&since=…&refresh=1` | Opt-in paged history. Existing calls without paging params keep the old response. First request gives newest page in chronological order; before gets older. since refresh returns changed/new items (upsert by stable item ID), not just appended messages. |
| `POST /api/sessions/<id>/unlink` body `{}` | `{"session_id":"ses_…","unlinked":true,"native_history_preserved":true}`. Hide association, keep local audit and native history. Idempotent. Refuse active/unknown-exit/external-held sessions; no force release. |
| Existing `POST …/start` body `{"kind":"resume","confirm_external":true}` | Explicit native resume of the linked ID. Never `new`, no fallback/fork/replay. confirm_external only after the user confirms the outside writer has ended. Missing folder/environment mismatch/unsupported sources refuse before spawn. |
| Existing `POST …/desktop/open` body `{"release":true,"confirm_unknown":true}` | Existing official desktop route; release at idle with confirmed exit. Existing result and external hold unchanged. Flags require the same explicit user confirmation as before. |
| Existing `POST …/desktop/return` body `{}` | User confirms outside use ended; clears hold and invalidates history cache. Then request conversation with refresh=1 and since, or load newest page; resume remains a separate explicit action. |

Existing rename/archive/unarchive/stop/view/send routes remain compatible. Archive is not unlink.
Unlinked sessions cannot start/send/open until relinked. Discovery may include a missing-directory
session for history; restoring the directory is required before native resume.

## Discovery page (synthetic example)

```json
{
  "items": [{
    "candidate_id": "nat_000000000000000000000001",
    "harness": "claude-code",
    "native_session_id": "00000000-0000-4000-8000-000000000001",
    "environment": {"id":"env_000000000000000000000001","kind":"local","label":"Claude Code local"},
    "source": "unknown",
    "title": "Fix parser",
    "updated_at": "2026-10-09T00:00:00Z",
    "workdir": "/example/project",
    "directory_state": "available",
    "project_match": "root",
    "already_linked": null,
    "resumable": true,
    "resume_reason": null,
    "occupancy": {"state":"unknown","reason":"External activity is not observable"}
  }],
  "next_cursor": null,
  "completeness": {"state":"partial","reasons":["local_only"]}
}
```

source: `cli | desktop | cloud | other | unknown`; only label proven origin. Local unknown origin can
be resumable when native ID/cwd/local history are verified; cloud/unsupported sources cannot.
Current local discovery emits `cli`, `other` or `unknown`; desktop/cloud are reserved for proven
sources, not inferred. Codex's native default interactive-source and non-archived filters apply.
already_linked: null or `{"session_id":"ses_…","archived":false}`.
directory_state: `available | missing`; project_match: `root | registered_workdir`.
occupancy.state: `repobridge | external | unknown`; unknown never means free. A linked external
hold is reported as external. Existing same-workdir admission plus native writer refusal remain.
Freshly linked unknown occupancy requires user confirmation before first resume/send; confirmation
is not proof that every external process has exited. No automatic takeover or killing outside apps.
Relinking after removal requires this confirmation again.
Completeness refers to the native source, not whether pagination has more rows. `local_only` means
cloud/unindexed/other-project histories were not searched; bounded/malformed sources add reasons.

## History page (same conversation item shapes as existing conversation endpoint)

```json
{
  "items": [{"id":"user:example","type":"user","text":"Fix parser","history":true}],
  "history": {"source":"claude-transcript","error":null},
  "partial_reasons": [],
  "page": {
    "state":"ready", "next_before":null, "next_since":"opaque-token",
    "has_more":false, "reset":false,
    "completeness":{"state":"complete","reasons":[]}
  }
}
```

page.state: `ready | empty | partial | unavailable`. empty means successful native read with no
visible items, never failed read. partial retains readable items with explicit reasons (e.g. native
limit/truncated record). unavailable includes history.error. Stable IDs are inherited from native
items/transcript UUIDs; no terminal parsing. A since cursor compares item contents as well as IDs,
so completed tool results replace their earlier versions. `reset=true` tells the UI to replace its
loaded history (e.g. native rewrite or expired snapshot); otherwise merge by ID. before cursors use
an immutable bounded snapshot, so appends do not shift older pages. Cursors never grant new scope.
Preview returns exactly `items`, `history`, `partial_reasons`, `page`. Session conversation retains
its existing additional fields (`live`, `run_id`, `turn`, and live `info`). For a live connection,
paging adds `history.source="live-structured"`; unpaged legacy responses are unchanged. Consumers
should use `page.completeness` (not assume `partial_reasons` exists on live/legacy responses).

Snapshots are local and bounded: cursors expire after 10 minutes, on restart or cache eviction
(64 entries, 32 MiB total); candidates are retained for the latest 2,000 discoveries. Claude scans
at most 2,000 transcript candidates in the scoped directories and validates the first 256 KiB of
metadata. Its history reader has a 64 MiB file cap. Codex reads at most 20 native pages of 100 turns,
newest first; normalized history retains at most 10,000 items / 8 MiB. Truncation is explicit in
`page.completeness.reasons` (`native_file_limit`, `native_page_limit`, `history_snapshot_limit`),
so a page is only the newest part of the **visible bounded history**, not proof of exhaustive history.
Discovery reasons include `local_only`, `native_index_only`, `scan_limit`, `symlink_skipped`,
`directory_unreadable`, `invalid_native_metadata`; malformed JSONL history adds
`malformed_native_record`. Native read failures appear in `history.error`.

## Link response and state integration (synthetic)

Request: `POST /api/sessions/link`, body
`{"candidate_id":"nat_000000000000000000000001","view_mode":"conversation"}`.
Successful `result` below reuses **the full existing session-detail response** under `session`.
Select `result.session.session.session_id`; do not invent a flat response:

```json
{
  "session": {
    "session": {
      "session_id":"ses_000000000001", "project_id":"prj_000000000001",
      "harness":"claude-code", "title":"Fix parser", "workdir":"/example/project",
      "native_session_id":"00000000-0000-4000-8000-000000000001",
      "native_binding":"linked", "handoff_from":null, "turns_observed":0,
      "created_at":"2026-10-09T00:00:00.000+00:00",
      "updated_at":"2026-10-09T00:00:00.000+00:00",
      "archived":0, "view_mode":"conversation"
    },
    "structured_info":{}, "runs":[], "handoffs_in":[], "handoffs_out":[]
  },
  "created":true, "relinked":false
}
```

Duplicate: same local/native IDs, `created=false,relinked=false`. Re-add after unlink: same IDs,
`created=false,relinked=true`. Existing runs/handoffs remain in their existing arrays; no history
is copied into them. `turns_observed=0` counts App-observed turns, not native history length.

The existing `/api/state` / SSE session row adds `native_link` (null for ordinary App sessions):
`{"linked":true,"environment":{"id":"env_…","kind":"local","label":"Claude Code local"},
"source":"unknown","resumable":true,"resume_reason":null,"directory_state":"available"}`.
`resume_reason`: null, `unsupported_source`, `directory_missing`, `environment_changed`, `unlinked`.
Existing `can_resume` reflects capability/current directory/environment and active run;
`can_start_fresh=false` for associations. It does **not** override external-writer confirmation.
Read existing `external` for the hold; an initial/relinked hold is
`{"app":"external client","status":"unknown","via":"native-link"}`.
Unlink archives the session; `native_link.linked=false` distinguishes it from ordinary archive.
Display it only where removed/archived records are intended, not as a resumable active association.

Requests are synchronous: show loading while pending; no new progress SSE protocol. Do not poll
while the dialog is closed. Refresh is user initiated; transient failures preserve the last view
with an error indicator. Existing state SSE reports link/unlink and external hold changes.
Invalid/expired discovery or before cursor: HTTP409 STATE_CONFLICT, details.reason=`cursor_expired`;
restart from first page. Bad input:400 INVALID_INPUT; unknown candidate/session/project:404 NOT_FOUND;
unavailable native capability or missing directory:412 PREFLIGHT_FAILED; busy/unlinked/env mismatch:
409 STATE_CONFLICT. Known unsupported discovery returns a capability error, never an empty list.
Native failures are sanitized; no raw credentials or unrelated transcript content in errors.
The existing external-hold error has `details.external`; same-workdir busy has
`details.busy_session_id`. Do not parse message text for these states. Native writer conflicts
detected after asynchronous resume appear in the existing failed run/state event, not a successful
connection. Example error envelope:

```json
{"ok":false,"error":{"code":"STATE_CONFLICT","message":"历史分页已过期，请从第一页重新加载。","details":{"reason":"cursor_expired"}}}
```

## Verification and acceptance boundary

### Integration correction: message receipts and stable errors (2026-10-09)

Frontend input: `202630f659d0411ef81a611ccc98bf09bfc4b4aa` (includes `b866e09`). The delivered
frontend already restores definitely-unsent messages by client ID; the additions below also cover
ambiguous delivery and must be consumed before treating UI acceptance as complete.

**Codex send receipts apply to both ordinary and linked sessions.** `/send` still returns
`client_id`, and adds `delivery:{state,reason,message}`. HTTP 200 acknowledges local acceptance,
not native delivery. Each accepted message is persisted in the existing event store before native
submission, with original text and attachment IDs/names; no new schema version. Existing
conversation/SSE user items use `id="user:<client_id>"`, add `client_id` and the same `delivery`.

| delivery.state | item.status | Meaning and required UI behavior |
|---|---|---|
| `queued` | `sending` | Accepted locally, awaiting handshake; not submitted yet. Keep tracked text/attachments. |
| `sending` | `sending` | Native submission attempted; wait for a receipt. This is not proof of delivery. |
| `not_sent` | `failed` | Definitely not submitted (handshake refusal/timeout/early exit), or explicit native request rejection. Restore once or hold next to a newer draft; never resend automatically. |
| `sent` | `sent` | Native `turn/start` success with turn ID, matching native user item, or matching client ID in native history confirms acceptance. This says nothing about whether the turn later succeeded. Remove any unedited recovery copy. |
| `unknown` | `unknown` | Submission may have reached Codex, but reply was lost/timed out. Preserve a separate uncertain copy; show the supplied explanation and require checking native history. **Do not label it “没有发出”, restore it as definitely unsent, or resend it.** |

`GET /api/sessions/<id>/delivery?client_id=<id>` returns the durable user-item receipt (same normal
envelope), including `text`, `attachments`, `run_id`, `delivery`. Use this after an ended run, missed
SSE/HTTP response, view switch or restart. A missing receipt returns 404 with
`details.reason="message_not_found"`; absence/error alone is not native delivery proof.

Submitting the same client ID and content returns the existing receipt with `reused:true` and
never spawns/resends; changed content for that ID returns 409 `client_id_conflict`. A deliberate
retry of a definitely-unsent message uses a new client ID. While a prior receipt is `unknown`,
new Codex sends are refused with 409 `delivery_unknown` (and the unresolved client ID) until exact
native evidence confirms it. Never infer delivery from matching text or from the process ending.
Read-only refresh can reconcile a native item with the same `clientId`; it does not start a turn.
Late receipts may change unknown/not_sent to sent; a confirmed sent receipt cannot be downgraded
by a later timeout/exit. Consumers must preserve that monotonicity across all event, history and
query sources, including when sent is first loaded after a page reload. An older unknown/not_sent
must not overwrite the confirmed bubble or reintroduce a recovery/uncertainty card. No sequence
field was added: this is an invariant of confirmed native acceptance, not timestamp guessing.
Failed/uncertain local items remain recoverable after native history reload.

Synthetic accepted response:

```json
{"ok":true,"result":{"client_id":"send-example","delivery":{"state":"queued","reason":null,"message":"等待 Codex 连接完成，尚未发送。"}}}
```

Synthetic receipt after a refused handshake (attachment bytes stay in the existing App attachment
store; the response contains references only):

```json
{"id":"user:send-example","type":"user","client_id":"send-example","text":"修复解析器","attachments":[{"id":"att_example","kind":"file","name":"notes.txt","size":18}],"status":"failed","run_id":"run_example","delivery":{"state":"not_sent","reason":"native_writer_busy","message":"这条消息明确没有发出；文字和附件已保留，不会自动重发。"}}
```

**Error classification.** Existing status codes and `history.error` string/null stay compatible.
HTTP errors add `details.reason` and, for history capability decisions, `details.capability_unsupported`.
Successful preview/conversation responses with a native read failure add `history.reason` and
`history.capability_unsupported` next to `history.error`. Display Chinese `message`/`history.error`;
branch on the fields, not English text. A generic `PREFLIGHT_FAILED` is not “unsupported”.

| Reasons | Meaning |
|---|---|
| `native_capability_unsupported`, `native_protocol_unsupported`, `storage_layout_unsupported`, `unsupported_source` | Explicit unsupported capability/source/layout, `capability_unsupported=true`. Native method-not-found is recognized from RPC code -32601. |
| `native_read_failed`, `native_timeout`, `native_process_exited`, `native_transport_error`, `native_exit_unconfirmed`, `harness_unavailable` | Read/connection failure, **not** unsupported; retry/inspect as appropriate. No global scan fallback. |
| `native_history_missing`, `native_history_invalid`, `native_identity_changed` | Missing history, invalid metadata, or mismatched ID/cwd; no invented empty-success history. |
| `candidate_expired`, `cursor_expired` | Rediscover or reload the first page. |
| `external_confirmation_required` | 409 with `details.external`; external use has not been confirmed ended. |
| `local_writer_busy` | 409 with `details.busy_session_id`; a real local run (including unconfirmed exit) still owns the slot. |
| `directory_missing`, `environment_changed`, `unlinked`, `resume_required` | Restore the correct directory/environment/association or use resume. |
| `native_writer_busy`, `native_request_rejected`, `connection_unavailable`, `connection_ended` | Delivery refusal/lifecycle reason. `delivery.state` determines definite failure versus uncertainty. |

An external-held unlink is checked atomically in the same transaction as local activity and removal.
It returns `details.external`, **not a busy-session pointer to itself**. An actual local run takes
the local-writer branch. The rule is unchanged: external confirmation is required before unlink.

**`POST …/desktop/return` is the intended confirmation for `via:"native-link"` too.** The user
explicitly confirms outside use has ended; it records that statement, clears the external hold and
invalidates the history cache. Result stays `{"external":null}`. The audit payload says
`source:"user_confirmation",process_exit_observed:false`. It never resumes, sends, kills an
external process or asserts observed exit. The next resume/send remains a separate explicit action.

Frontend `0253b2f` consumes these fields and passes the normal fault-stub recovery and capability
classification checks. Remaining review: stale events/queries can regress frontend sent after
reload even though the backend remains sent. Exact reproduction and owner locations are in
EXISTING_SESSIONS_INTEGRATION.md; this is not permission to edit Opus's worktree.

Use isolated homes/native histories, stub CLIs, temp state and server port 0. Fixtures must be seeded
outside RepoBridge before link. Assert no new native session/turn/send/replay for list/preview/link;
exact ID on resume, writer/hold guards, dedupe under concurrent link, restart, unlink/relink,
paging/refresh/updated tool items, missing paths, malformed/partial/native errors and 3→current
migration retention. Existing W6–W8 allowance is exhausted. Real outside-created samples and real
Desktop-return continuity remain a separately scoped acceptance step, not implied by stub success.
