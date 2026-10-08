# Existing native sessions — frontend/backend contract v1

2026-10-09. Base: `ef75a625577c1848e1079dd6d487a5cdc3afa166` (code `2f26d23`).
Owner: Codex backend/integration. This commit freezes the minimal interface; implementation follows.
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
    "candidate_id": "nat_example",
    "harness": "claude-code",
    "native_session_id": "00000000-0000-4000-8000-000000000001",
    "environment": {"id":"env_example","kind":"local","label":"Claude Code local"},
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
already_linked: null or `{"session_id":"ses_…","archived":false}`.
directory_state: `available | missing`; project_match: `root | registered_workdir`.
occupancy.state: `repobridge | external | unknown`; unknown never means free. A linked external
hold is reported as external. Existing same-workdir admission plus native writer refusal remain.
Freshly linked unknown occupancy requires user confirmation before first resume/send; confirmation
is not proof that every external process has exited. No automatic takeover or killing outside apps.
Completeness refers to the native source, not whether pagination has more rows. `local_only` means
cloud/unindexed/other-project histories were not searched; bounded/malformed sources add reasons.

## History page (same conversation item shapes as existing conversation endpoint)

```json
{
  "items": [{"id":"user:example","type":"user","text":"Fix parser","history":true}],
  "history": {"source":"claude-transcript","error":null},
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

Requests are synchronous: show loading while pending; no new progress SSE protocol. Do not poll
while the dialog is closed. Refresh is user initiated; transient failures preserve the last view
with an error indicator. Existing state SSE reports link/unlink and external hold changes.
Invalid/expired discovery or before cursor: HTTP409 STATE_CONFLICT, details.reason=`cursor_expired`;
restart from first page. Bad input:400 INVALID_INPUT; unknown candidate/session/project:404 NOT_FOUND;
unavailable native capability or missing directory:412 PREFLIGHT_FAILED; busy/unlinked/env mismatch:
409 STATE_CONFLICT. Known unsupported discovery returns a capability error, never an empty list.
Native failures are sanitized; no raw credentials or unrelated transcript content in errors.

## Verification and acceptance boundary

Use isolated homes/native histories, stub CLIs, temp state and server port 0. Fixtures must be seeded
outside RepoBridge before link. Assert no new native session/turn/send/replay for list/preview/link;
exact ID on resume, writer/hold guards, dedupe under concurrent link, restart, unlink/relink,
paging/refresh/updated tool items, missing paths, malformed/partial/native errors and 3→current
migration retention. Existing W6–W8 allowance is exhausted. Real outside-created samples and real
Desktop-return continuity remain a separately scoped acceptance step, not implied by stub success.
