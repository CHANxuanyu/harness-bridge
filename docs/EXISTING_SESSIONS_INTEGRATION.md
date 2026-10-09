# Existing-session independent acceptance — 2026-10-10 (frontend 72a3255)

**P1 closed. Offline/synthetic integration acceptance passed.**
Both P2 findings stay closed within their recorded scope. Real outside-created native sessions and
real official-desktop continuation remain a separate acceptance step. No frontend implementation
was changed by Codex this round.

## Fixed versions and actual checks

| Input | Full SHA |
|---|---|
| Integration input | `9f866e901b623a770b729afd460cef5ffe8acbf7` |
| Frontend PR #3 input | `72a32557cc7f0196655841628d3c2dcf5a81383e` |
| Exact frontend parent (not reapplied) | `462cda4d34bfbd5e13a22a79783758b26fde4bf6` |
| **Actual fixed integrated code tested** | **`1676fdc8b412a565bc2b697d262f29fdc3bb561d`** |
| Retained backend factual-banner fix | `a35a868f191f8377444a0cad136cf387906e0bf8` |
| Retained backend first-submission ID protection | `1856bd44f950ec456d9becf53d4c24f368c0b95d` |

Preserved worktree `/Users/chan/Downloads/repobridge-integration`, branch
`codex/existing-session-integration`. Merge was conflict-free. Backend PR #4 remains draft, stacked
on draft PR #3. Final documentation and integration head SHAs are in PR #4; only seven Markdown
files follow the tested code. Source/tests/assets/scripts/dependencies remain identical. Frontend
worktree and old main directory untouched; no default-branch merge/release/install.

Final fixed-code offline check: **1004 passed in 1006.77s (16m46s), zero failures and zero skips**. Ruff check and format passed (190 files); strict mypy passed (59 source files).

Focused tests: **43 passed / 42.60s**, comprising backend delivery/conversation plus UI retention
regressions. Independent older-page probe: **35 explicit assertions passed** (4 setup, 31 behavior
and health). These are new execution results on the actual integration, not Opus's 27/105/14/968
input evidence and not the previous 1003-test integrated result.

Runtime import paths and absolute `PYTHONPATH=/Users/chan/Downloads/repobridge-integration/src` were
verified. Existing frontend virtualenv reused read-only. Every fixture has isolated HOME/config/
native history/state and port 0 with explicit stub executables/fake desktop apps. Browser plugin
not available; regular Playwright used installed Chrome in fresh contexts, with loopback-only
traffic. No real model, account credential, private-history scan, real DB upgrade or current-instance
access. The four owned UI services were stopped after verification; fixture data remain available.

## Remaining P1 independently verified and closed

The flow tested is: actual backend submission-lost-reply stub produces unknown → a read of synthetic
native history with the same clientId produces sent → controlled first/older-page HTTP ordering
→ actual “加载更早的消息” button clears only the confirmed message's pending card.

Opus's `artifacts/qa-older-72a3255/README.md`, scripts and reports were read as inputs. `older.cjs`
was copied into Codex's own QA directory, adapted to its fresh fixtures and actual integration
source, and strengthened with attachment isolation, full content/order, reading-anchor and protocol
count assertions. Original artifacts and ix4 instance were not changed or executed. The old shell
launchers with their temporary paths/cleanup commands were not used.

M2 (linked Codex) and M4 (ordinary Codex, first turn) originate from **actual backend + exit-after-
submission stub**, each with a durable unknown receipt. Only M2 receives exact-clientId proof in
its owned synthetic native history; M4 stays actually unknown. First/older page placement, stale
receipt delivery and the extra unknown X are **browser HTTP injection**, not real-native disorder.
X is a separate synthetic injected receipt; it is not claimed as a second native accepted turn.

| Required behavior | Explicit evidence/result |
|---|---|
| Current session, first confirmation in older page | Before: confirmed=false, target uncertain=1, item absent, card present and send disabled. After: cached=sent, confirmed=true, target uncertain=0, one sent bubble, no recovery button, valid draft makes send usable. Draft and its attachment unchanged. |
| Same ID already cached and skipped by pagination dedupe | Confirmation is retained and existing bubble repainted. Deliberately different cached text and marker survive. Full relative order remains; index advances only by the two newly prepended items. Reading anchor moved **0.078125 px** (88.671875→88.59375), below the asserted 1 px tolerance. |
| Switch sessions while older page is outstanding | A clears M2 while not visible. B retains actual unknown M4, disabled send, its own draft and B-draft.txt. A retains its separate draft/A-draft.txt. Switching back displays one sent M2 bubble and only the remaining X card. Background toast names A. |
| Same session has another unknown | A's injected X remains uncertain and blocking; only M2 is removed. B's actual M4 is also untouched. |
| Repeated/late page | One bubble, unique item IDs, unchanged draft/attachment, no repeated confirmation/recovery notice. No `/send` request and no new run in either session. Actual stub `turn/start` count stays **2→2** throughout paging. |

**Isolation of the clearing path:** while each older page is gated, all other history and receipt
responses for A are held and counted. In the three windows there were **zero** such competing
requests; no hidden successful refresh could clear the card. Switching back to A triggers a quiet
history refresh, which is held and cannot settle anything. Report entries clone assertion-time
snapshots so subsequent duplicate-page requests do not mutate earlier recorded counters.

Artifacts: `older-out/report.json` contains all before/after states, page counts and toasts;
`older-run.log` lists the assertions. `older-1-before.png` / `older-1-after.png` show the card clearing
and editable draft/attachment; `older-3-other-session.png` / `older-3-back.png` show independent
remaining uncertainty and attachments. Screenshots were visually inspected separately from DOM
measurements. Product acceptance is based on those state assertions, not script exit or source text.

## Related regressions and both P2 findings

| Regression | New evidence |
|---|---|
| Same-page/reload old unknown/not_sent/queued/sending after sent; earlier query returns stale unknown while history refresh fails | `p1-result.json`: actual page entrypoints with explicit event/HTTP injection keep cache/bubble/recovery sent, preserve draft/attachment, add no turn. First-page and history refresh also pass. |
| Lost `/send` response + missed SSE, failed/missing receipt read | `network-result.json`: never infer definitely not_sent. Accepted backend receipt later settles sent; aborted-before-accept + real 404 remains unknown. |
| Native event before delayed/lost HTTP response | `races-result.json`: four ordinary Codex/Claude cases; no retracking, duplicate bubble/attachment or overwrite of independent draft. Claude proof is native echo, not durable receipt. |
| Normal not_sent restoration and late confirmation | `busy-result.json`, `late-not-sent-result.json`: retain text/attachment once; manual restore preserves newer draft; later exact proof removes offer but keeps user edits. External-held unlink uses details.external; return adds no run. |
| Ordinary Codex first-turn ID protection and restart | Focused/full backend regression proves no fresh replacement, missing/wrong-ID proof remains unknown, and explicit next message resumes original ID. `restart-result.json` independently verifies actual service restart, durable unknown/attachment, exact proof→sent, edited draft retained and no added turn. |
| **Run-banner P2** | `banner-unknown.png`, `sent-after-reload.png`, `restart-sent.png`: failed status/exit 3 retained; unresolved unknown warns separately. Proof/reload/restart remove delivery uncertainty without changing the run or starting it. Diagnostics preserved; old stored failure summaries not migrated. |
| **Narrow-window P2** | `layout-result.json`: Chrome 900×640/sidebar open, 700×640, 1280×900 have body/document width equal viewport and composer controls inside bounds. `layout-900.png` separately inspected with draft/attachment. Short stub model this round; previous long-model and isolated WKWebView acceptance retained, not represented as rerun. No CSS change. |

Pagination probe: page identity/content, no framework overlay, no JS page errors and no console
errors all pass. Related fault probes report no JS page errors; console resource failures are the
expected deliberate 409, 404, 500, 503 and aborted requests, recorded in `console.jsonl`. Native
capability/read-failure semantics and association flows remain covered by the full offline suite;
the previous independent UI classification evidence is retained, not re-counted as a new probe.

## Reproduction and retained evidence

Durable local directory:
`/Users/chan/Documents/Codex/2026-10-06/harness-bridge-agent-local-glm-macos/repobridge-qa-72a3255/`.
`verification.json`, `focused-check.log`, `final-check.log` and `SHA256SUMS` fix versions/results and
artifact contents. No launch authorization URL, runtime.json, credentials or real native data are
copied into it. Original Opus input script/README retained separately for provenance.

[Isolated startup commands](EXISTING_SESSIONS_SANDBOX.md). To reproduce the primary probe with
already installed machine-local runtimes, first copy the retained `.cjs` files and `sandbox.py` to
`/private/tmp/repobridge-recheck-72a3255` (use a new output directory or preserve existing reports
before another run). Then:

1. Launch `sandbox.py --scenario unknown` with absolute integration PYTHONPATH. Record its printed
   ROOT; never use the current App's state or launch URL.
2. Run `node older.cjs setup ROOT`. This explicitly sends only to the stub and records M2/M4 unknown.
3. Stop that owned service, reopen **the same** `--root ROOT --scenario normal`.
4. Run `node older.cjs older ROOT`. It reads runtime metadata locally, adds proof only to this
   synthetic native store and exercises all five paging behaviors. Inspect the boolean assertions
   and before/after details in `older-out/report.json`, not just the exit code.
5. Related probes use fresh separate fixtures: busy→`busy.cjs`, `late-not-sent.cjs`; normal→
   `network.cjs`, `races.cjs`; another unknown→`p1.cjs`, `layout.cjs`, `restart-setup.cjs`, then reopen
   that last root as normal and run `restart-check.cjs`.

Node: `/Users/chan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`.
The retained helper specifies installed Playwright/Chrome paths. No dependency installation or
original ix4 launcher is needed. The final pagination probe was repeated only to freeze diagnostic
objects at assertion time; no product change or additional turn was involved. No failing behavior
was removed, skipped or relabelled to obtain acceptance.

## Limits and future real acceptance

- Real sessions created outside RepoBridge and official Claude/Codex desktop continuation remain
  **not validated** by these stubs. Prior App-created samples do not substitute. No new real-turn
  allowance is granted here.
- IME, system clipboard and VoiceOver remain unverified. This round did not launch a native window;
  prior narrow-window native evidence keeps its stated scope.
- Claude has no corresponding durable receipt; exit before native echo has limited evidence.
- Full-page reload loses ordinary unsent drafts. History refresh and accepted-message receipt
  recovery are different; no new draft-storage feature was added.
- Historical persisted run-failure summaries are not migrated. Corrected new summaries keep failure
  facts separate from message acceptance while preserving diagnostic output.

---

# Historical independent revalidation — 2026-10-10 (462cda4)

**P1 remains open for one older-page cleanup gap. The previous original sent-downgrade reproductions
are corrected. The new run-banner P2 passes on corrected runs; narrow-window P2 remains closed.**
The final offline check is recorded below, but full offline/synthetic feature acceptance cannot be
claimed while P1 remains. Real-native acceptance is separately pending. No frontend-owned code was
changed by Codex.

## Fixed version and independent checks

| Input | Full SHA |
|---|---|
| Integration input | `fc1550220d7b183ed51c495b39563d3e865a74a6` |
| Confirmed frontend input, PR #3 | `462cda4d34bfbd5e13a22a79783758b26fde4bf6` |
| Previous frontend, already included | `0253b2f3ee89511c0222607dc3d418cfc742731e` |
| Backend factual run-summary fix | `a35a868f191f8377444a0cad136cf387906e0bf8` |
| Backend first-turn receipt/identity correction | `1856bd44f950ec456d9becf53d4c24f368c0b95d` |
| **Exact final code tested** | **`e2512ee9b952be940f030f30ab2047e2ccc928c0`** |

Preserved worktree `/Users/chan/Downloads/repobridge-integration`, branch
`codex/existing-session-integration`. PR #4 remains draft and stacked on draft frontend PR #3.
Final documentation receipt/merge hashes are recorded in PR #4, avoiding a self-referential hash in
this file. Only seven Markdown files follow the code under test; source/tests/assets/scripts and
dependencies are identical. The frontend checkout, old main directory and default branch were not
modified.

Final fixed-code offline check: **1003 passed in 1011.98s (16m51s), zero failures and zero skips**.
Ruff check and format passed (190 files); strict mypy passed (59 source files).

Focused backend delivery/conversation tests: **25 passed / 35.31s** (earlier banner-only change:
24 / 32.05s). These are actual runs, not Opus's 105 browser / 14 regression / 967 offline inputs or
previous 994 integration evidence. Runtime imports printed the absolute integration source paths.
Existing virtualenv was used read-only with `PYTHONPATH=/Users/chan/Downloads/repobridge-integration/src`.

Tests use isolated HOME/native history/config/SQLite, explicit stub CLIs, fake desktop applications
and separate loopback port-0 servers. Regular Playwright drives installed Chrome with a fresh profile
and loopback-only request policy. No model account, credential/private-history scan, live database
migration, current-instance access, native production app launch, default merge, release or install.

## P1: independent actual-page results

All final probes below ran on `e2512ee`; native proof means evidence deliberately added to an owned
synthetic fixture, never a real native conversation. Page/HTTP injections are explicitly separate.

| Case | Evidence and result | Local receipt |
|---|---|---|
| Linked Codex resume rejected by native writer lock | Actual backend + busy RPC stub → not_sent. Original text/attachment retained once; newer draft kept; manual restore appends once. External-held unlink keeps details.external; return adds no run. | `busy-result.json` |
| Ordinary/linked Codex submit then exit before reply | Actual backend + exit stub → unknown. Separate card, input editable, send blocked, no unsent/retry action. Unknown warning remains while unresolved. | `p1-result.json`, `restart-setup-result.json` |
| Ordinary first-turn unknown survives actual service restart | Same isolated state/new process and port, receipt + attachment restored. Exact native clientId proof → sent; edited draft retained; full reload keeps sent. Run still failed/exit 3; no extra turn. | `restart-result.json`, `restart-sent.png` |
| Same-page sent followed by unknown/not_sent/queued/sending and duplicates | **Injected old page events** through actual `onConv`: cache/bubble/confirmed/recovery remain sent; no blocked send, duplicate bubble or restored copy. New draft and attachment preserved. | `p1-result.json` |
| Fresh page first reads sent, then those four old states | **Injected old events**, real full reload: no new unknown card or “放回输入框”; no downgrade. Ordinary unsent draft loss on reload separately acknowledged. | `p1-result.json`, `sent-after-reload.png` |
| Earlier delivery query arrives after sent with stale unknown; history refresh fails | Gate actual `recheckDelivery` request, confirm via fixture history, release old HTTP result and inject history 503. Still sent, editable draft retained, no extra send/run. **HTTP ordering injection**, not native disorder. | `p1-result.json`, `sent-after-stale-query.png` |
| First history load and history refresh return old receipt | **HTTP response injection** through actual `loadConversation`/`refreshConversation`. Confirmed sent and draft/attachment remain intact. | `p1-result.json` |
| Lost send response and missed conversation SSE, then query error / absent receipt | **Browser/network injection** over real backend; absent evidence is never not_sent. Actual accepted receipt later settles sent; aborted-before-accept plus real 404 remains unknown. | `network-result.json` |
| Native echo/acceptance arrives before held/lost HTTP send response | Ordinary Codex and Claude, four cases. Actual stub events, controlled HTTP response timing/drop, followed by stale page event. No retracking/recovery/duplicate or replay; independent draft/new attachment retained. Claude evidence is echo, not durable receipt. | `races-result.json` |
| not_sent already restored and edited, then matching proof arrives | Actual busy result + added synthetic native proof → sent; recovery offer disappears; user's edited text and attachment remain; no new execution. | `late-not-sent-result.json` |
| First confirmation arrives in an older history page after existing unknown card | **FAIL P1.** Controlled HTTP ordering through `recheckDelivery` and `loadOlder`: confirmed/cache become sent, but existing uncertainty remains and blocks sending. | `older-focused-result.json`, `older-focused.png` |

No JavaScript page exceptions in completed final probes. Expected 409/412/500/503/404 responses and
aborts are deliberately exercised fault paths, not hidden passing errors. These scenario tables
are not added to pytest's test count.

### Remaining older-page reproduction for Opus

[Direct handoff in PR #3](https://github.com/CHANxuanyu/harness-bridge/pull/3#issuecomment-6089874021).

1. Obtain unknown from the actual exit-after-submission backend stub and later sent from matching
   clientId in the same synthetic native history. Keep those receipt shapes.
2. On a fresh page, first history response omits this message, reports an older cursor, and gates
   the older HTTP response. Through actual `recheckDelivery`, return the saved unknown receipt.
3. Assert before: `confirmed=false, uncertain=1, hasItem=false`.
4. Release `loadOlder` with the sent item. Observed after:
   `cached="sent", confirmed=true, uncertain=1, blocked=true`.

`app.js:loadOlder` uses `viewItems` → `deliveryView` to remember confirmed, but does not call the
recovery reconciliation used by first-page load and refresh. The sent bubble/cache protection is
working; cleanup of an **already present** card is missing. Opus should reconcile older-page input
including non-selected sessions and items skipped by pager deduplication. Preserve normal paging,
edited drafts and attachments; do not auto-restore or resend. Codex has not modified frontend files.
This is deterministic HTTP/page injection, not proof of native traffic arriving in this order.

### Additional backend first-turn defect found and fixed during revalidation

The original restart probe used an ordinary Codex session whose first `turn/start` reply was lost.
`turns_observed` remained 0, so `_history` returned before reading exact-ID native evidence. It also
left fresh native creation available for the local slot. A new backend regression failed before
fixing (`1 failed, 14 deselected / 8.38s`) and passed in the 25-test affected run afterward.

`1856bd4` lets a persisted sending/unknown/sent receipt preserve a known Codex ID despite zero
observed turns: exact-thread read and original-ID resume are allowed, fresh replacement is refused.
It does not fabricate a turn count. Regression verifies missing history and same text with a wrong
clientId remain unknown, exact clientId settles, failure/attachments survive restart, no automatic
turn is added, and the explicitly sent next message resumes the same ID with no second thread/start.
The final browser restart probe independently confirms the unknown→sent/read-only part.

## New run-failure banner P2

`a35a868` removes application delivery notices from the source of a new exit-summary suffix.
The summary retains native exit facts and native stderr; `output_tail` still retains notices and
all existing diagnostic content. A deterministic pre-fix test failed with stale uncertainty in the
summary (1 failed, 1 passed, 12 deselected / 3.49s). Empty and nonempty stderr regressions now pass.

Final actual backend + exit-stub screenshots verify:

- Before proof: failed run / exit 3 in the main banner, separate unresolved unknown warning/card.
- After exact synthetic proof and full reload: failed run / exit 3 still shown, no assertion in the
  main banner that acceptance is unknown; receipt sent, uncertainty removed, edited draft kept.
- Actual service restart preserves the same outcome and diagnostic record. Run object before and
  after confirmation is unchanged. No resume/send is triggered by proof or refresh.

Images: `banner-unknown.png`, `sent-after-stale-query.png`, `sent-after-reload.png`, `restart-sent.png`.
This is closed for runs generated by corrected code. Previously stored `run.failure` strings are
not migrated or rewritten; the user's real database was not opened. Historic diagnostic notices
remain evidence of what was known at that time, not current delivery status.

## Narrow-window P2 and semantic regression

Narrow-window P2 remains closed. Final Chrome DOM measurements at **900×640, 700×640 and 1280×900**
show body/document width equals viewport and all composer controls lie inside it, with draft and
attachment. `layout-result.json` contains bounds. Separate visual inspection of `layout-900.png`
confirms sidebar expanded and permission/model/effort/send controls visible. This minimal regression
uses the default short stub label; previous long-model/unknown-card/native WKWebView acceptance is
retained below and in `repobridge-qa-0253b2f`, not falsely reported as rerun. No CSS changed this round.

Actual unsupported/read-failure stubs still return/render respectively
`native_capability_unsupported` / “当前不支持” and `native_read_failed` / “读取失败”
(`classify-result.json`). External-held return/removal behavior is exercised in `busy-result.json`;
full offline tests also cover local active-writer distinction, atomic refusal, confirmation audit,
discovery/preview/link/dedupe/paging/original-ID resume/fake desktop return/unlink/relink.

## Reproduction and evidence

Local durable evidence directory:
`/Users/chan/Documents/Codex/2026-10-06/harness-bridge-agent-local-glm-macos/repobridge-qa-462cda4/`.
`verification.json` maps code versions/results, and `SHA256SUMS` fixes artifact contents. Authorization
URLs/runtime.json and credentials are excluded. `prior-f706/` preserves pre-final probe outputs and
the interrupted full-suite log; these do not substitute for final-code evidence.

[Exact isolated startup](EXISTING_SESSIONS_SANDBOX.md). For ordering reproduction, copy the retained
`.cjs` probes and `sandbox.py` to `/private/tmp/repobridge-recheck-462cda4`. Use the absolute integration
PYTHONPATH and Node/Playwright executable paths in `common.cjs` (machine-specific, already installed).
Probe order with each printed sandbox root:

1. Fresh `unknown` sandbox → `p1.cjs ROOT` (creates linked fault message, saves `p1-result.json`).
2. Same root → `older-focused.cjs ROOT` reproduces the one open P1 from saved old receipt and live
   sent receipt. The script deliberately records observed failure state; exit 0 is **not** a pass.
3. Same root → `layout.cjs ROOT`; `restart-setup.cjs ROOT` submits the ordinary first-turn fault.
4. Stop only that sandbox PID, reopen its `--root ROOT --scenario normal`, run `restart-check.cjs`.
5. Fresh `busy` sandbox → `busy.cjs ROOT` then `late-not-sent.cjs ROOT`.
6. Fresh `normal` sandbox → `network.cjs ROOT` then `races.cjs ROOT`.
7. Fresh `unsupported` and `readfail` sandboxes → `classify.cjs UNSUPPORTED_ROOT READFAIL_ROOT`.

The first full run on `f706849` was deliberately interrupted at 43% when the backend first-turn
problem was discovered; it is not reported as passing. Two probe-only issues were corrected without
product changes: waiting for the next UI paint after a card appears, and not expecting an empty
composer to have an enabled send button after reload. An earlier ungated older-page probe could be
cleared by concurrent refresh; the final gated HTTP probe isolates the cleanup omission. All final
probes were rerun after the second backend fix; final checks run once on the fixed final code.

## Boundaries retained

- Full-page reload loses ordinary unsent drafts. This differs from history-refresh retention and
  persistent accepted-message receipt recovery. No new draft persistence feature was added.
- Claude lacks corresponding durable delivery receipts; exit before native echo remains limited
  evidence. Normal echo races were verified, not a new Claude persistence protocol.
- Real sessions created outside RepoBridge, real official desktop continuation, IME, clipboard and
  VoiceOver remain unverified. Prior App-created samples do not qualify. No model allowance renewed.
- Only owned temporary test services were used/closed. No real state upgrade, current app replacement,
  release, default-branch merge or private-history/credential access.

---

# Historical independent revalidation — 2026-10-09

**P1 remains open; P2 is closed for the tested offline browser/WKWebView surfaces.** The original
unknown-as-unsent fault is fixed in normal delivery paths, but stale events/queries can still
regress a frontend message that was already confirmed sent. The durable backend receipt stays
sent. Therefore this combination is **not yet fully accepted for offline/synthetic integration**.
Real-native acceptance is separately pending. No frontend-owned implementation was changed here.

## Fixed version and ownership

| Input | Full commit |
|---|---|
| Previous integration input | `67d6e1e52e6b26a2318284c04ae1c4d9963bd674` |
| New confirmed frontend, PR #3 (includes 202630f and b866e09) | `0253b2f3ee89511c0222607dc3d418cfc742731e` |
| Backend fix, retained unchanged | `9a9d6f9c9be4bedb840edbf931d8f39f38c055b9` |
| Backend documentation input | `47583acfda53d0b65bdba37dfa156858f99dde30` |
| **Exact merged code tested in this revalidation** | **`a0381264eed8c120ac7be3787d71d7ff76f8ee7b`** |

Existing integration worktree `/Users/chan/Downloads/repobridge-integration`, branch
`codex/existing-session-integration`, was preserved and merged once without conflict. No old delivery
was reapplied. Backend PR #4 remains stacked on frontend PR #3. The frontend worktree and old main
checkout were not edited. Subsequent commits consolidate documentation only; source, tests, scripts,
assets and dependency files are identical to the fixed code above. Final pushed documentation and
integration-head SHAs are recorded in PR #4 (avoids a self-referential commit hash in this file).

## New independent checks on that code

Final fixed-code offline check: **994 passed in 983.79s (16m23s), zero failures and zero skips**.
Ruff check and format passed (189 files); strict mypy passed (59 source files).

Focused regression first: **62 passed in 50.40s**, covering existing sessions, delivery,
conversation and frontend recovery/paging rules. Previous 961 frontend / 990 integration / 102
backend results do not stand in for this run. No live test was run; no test was removed or skipped
to obtain green. Tests and browsers used isolated HOME/config/native fixtures, temporary databases,
explicit stub binaries, fake desktop applications and port 0. The frontend virtualenv was reused
read-only with **absolute** `PYTHONPATH=/Users/chan/Downloads/repobridge-integration/src`.

The flow under test was: load an ordinary or linked native conversation → explicitly send a
synthetic message → observe the fault stub's actual receipt → reload/restart/read native evidence
→ retain drafts and correct delivery state. Browser plugin not available; regular Playwright drove
installed Chrome in fresh profiles, with only test-owned 127.0.0.1 traffic allowed. Server roots and
safe loopback addresses are listed in the local evidence; auth metadata is not published.

| P1 case | Evidence type | New result |
|---|---|---|
| Linked Codex handshake writer refusal | Actual backend + RPC fault stub, rendered UI | `not_sent/native_writer_busy`; text and attachment retained once; separate newer draft preserved; explicit restore appends without duplicating attachment; reload exposes retained receipt. |
| Ordinary and linked Codex submit then exit before response | Actual backend + fault stub | `unknown/native_process_exited`; separate “发送结果待确认” card, no unsent recovery action; send blocked, editor usable. |
| Refresh result without native confirmation | UI + actual backend RPC log/run counts | Still unknown; no run or `turn/start` added; draft retained. |
| Reload and actual service-process restart | Same isolated database, new server process/port | Unknown receipt/card restored with text and attachment. Ordinary unsent draft does not survive full page reload. |
| Exact `clientId` added to same synthetic native history, then refresh | Actual backend reads fixture; synthetic proof, not real native acceptance | Receipt sent, one matching user item, uncertainty removed, sending unblocked, edited draft retained; no run starts. |
| Ordinary Codex and ordinary Claude with attachments | UI + actual normal stub protocols | Codex sent receipt and Claude native user echo, no leftover recovery copy. Claude is not claimed to have durable receipts. |
| Drop conversation SSE and `/send` response; make history/query reads fail | **Browser/network fault injection** over actual backend | Never inferred not_sent; receipt recovery settled sent. Dropping a request before acceptance and receiving real 404 also stayed unknown. |
| Late/duplicate/old unknown or not_sent after known sent | **Page event / stale HTTP response injection** | **FAIL P1** below; backend receipt remained sent. |

Capability checks used separate **actual fault-stub services**: method-not-found gave
`native_capability_unsupported` and “当前不支持”; general failure gave `native_read_failed` and
“读取失败”. Opening the dialog was scripted; payload/error classification came from the backend.
External-held unlink remained 409 with `details.external`, no self `busy_session_id`;
`desktop/return` confirmation cleared the hold without adding a run. The final offline suite also
regresses true local-writer distinction, atomic removal, confirmation audit, original-ID resume,
discovery, preview, deduplication, paging, refresh, unlink/relink and fake desktop continuation.

## Remaining P1: sent must stay sent in the frontend

[Handoff to Opus in PR #3](https://github.com/CHANxuanyu/harness-bridge/pull/3#issuecomment-6085409315).
Reproduction on the exact fixed code (all fixtures isolated):

1. Send through the exit-after-submission Codex stub; keep the resulting unknown user receipt.
2. Add matching `clientId` evidence to that fixture's native history. UI refresh confirms sent,
   removes uncertainty and preserves the edited new draft. Backend GET delivery also says sent.
3. Reload the page. Feed the saved older user receipt through the real event entry point:
   `onConv({session_id:sid,run_id:S.convs.get(sid).runId,op:'upsert',item:oldUnknownItem})`.
4. One unknown card reappears and send becomes disabled. Injecting the same-ID old not_sent on a
   fresh sent page instead displays a failed bubble with “放回输入框”. No automatic resend occurred.
5. Same-page late unknown after live settlement does not re-block, but still downgrades the
   rendered/cached user item to unknown. A fresh sent page receiving repeated stale unknown HTTP
   delivery responses through `recheckDelivery`, with history refresh failing, also re-blocks.
   The independent draft survives; backend GET delivery stays sent throughout.

These are controlled event/network ordering injections, **not observed real-native out-of-order
traffic**. They verify the requested frontend invariant; no vendor history or receipt was forged
in the backend. Precise owner locations on 0253b2f: `composer.js:581` (`unsentDelivered` does not
remember sent when the page has no tracked recovery entry), `app.js:799` (`onConv` overwrites the
confirmed user item after `noteDelivery`), and shared receipt handling around `app.js:465/538`.
Opus should preserve confirmed sent across every receipt/history/event entry point, including the
bubble and recovery maps after reload. Recheck duplicates/ordering and preserve edited drafts.
Codex did not patch these frontend-owned files or claim their tests already cover this boundary.

## P2: measurements and screenshot observation are separate evidence

Actual stub model catalog supplied a deliberately long model display name. Each measured page
contained attachments, a new draft and an unknown card. Sending was disabled intentionally by
unknown; model/permission/effort menus opened, and normal sends worked in the separate flow above.

| Surface | Requested size | Measured content / body / html width | Send control right edge |
|---|---|---|---|
| Chrome, sidebar expanded | 900×640 | 900 / 900 / 900 | 861 |
| Chrome, responsive sidebar hidden | 700×640 | 700 / 700 / 700 | 661 |
| Chrome, sidebar expanded | 1280×900 | 1280 / 1280 / 1280 | 1149 |
| Isolated native WKWebView, sidebar expanded | 900×640 outer | 900×612 content; 900 / 900 / 900 | 861 |
| Isolated native WKWebView, dev resize | 700×640 outer | 700×612 content; 700 / 700 / 700 | 661 |
| Isolated native WKWebView | 1280×900 outer | 1280×872 content; 1280 / 1280 / 1280 | 1149 |

DOM measurements (`unknown-result.json`, `native-result.json`) verify widths and all composer
button rectangles. Browser controls were clicked through Playwright; native menus used scripted
DOM clicks inside the test-owned window. Native draft/attachment setup was scripted from the
synthetic receipt. This is not physical pointer, IME or clipboard acceptance. 700px native size was
requested through the development resize API, not a claim about manual minimum-size dragging.

Screenshots were separately opened and visually inspected: `layout-900.png`, `layout-700.png`,
`layout-1280.png` and native **content** snapshots `native-900.png`, `native-700.png`,
`native-1280.png`. Controls are visible, long labels truncate inside their buttons, cards and draft
stay inside the window. No horizontal page overflow or control clipping observed. The companion
`native-*-window.png` captures include a title bar but have blank content; those captures are **not
visual passing evidence**. WKWebView content snapshots contain the actual rendered interface.
The temporary native window was closed after measurement; the installed app was not replaced.

## QA record / local evidence

| Check | Result |
|---|---|
| Correct page/project/session; nonblank content | Pass on completed browser probes and native content snapshots |
| Fatal overlay / JavaScript page exceptions | No application overlay or page exceptions in completed browser probes |
| Console/network health | Expected exercised 409/412/500/503, aborted response/event and 404 errors; not zero-network-error claim |
| Interaction proof | Retained message + editable draft, read-only refresh, receipt settlement and menus verified above |
| Screenshot evidence | Browser and WKWebView content pass P2; stale-not-sent/stale-unknown/stale-query demonstrate open P1 |
| Whole feature | **Not fully accepted** while sent monotonicity remains open |

Evidence initially saved to `/private/tmp/repobridge-recheck-0253b2f/`; a durable copy is at
`/Users/chan/Documents/Codex/2026-10-06/harness-bridge-agent-local-glm-macos/repobridge-qa-0253b2f/`.
Contains probe source, final test log, result JSON and screenshots; excludes auth URL/runtime files,
real user data and credentials. Initial probe failures were probe defects: wrong expected title,
ambiguous locator, incorrect Claude client-ID field, polling/async assumptions and leftover test
writer. They were corrected before the completed observations reported here. Native evaluator
first hit CSP `unsafe-eval`, then Foundation serialization; the probe switched to supported direct
`run_js` and JSON serialization without changing product CSP or product code. Blank full-window
captures remain recorded as a capture limitation rather than converted to a pass.

[Exact isolated launch instructions](EXISTING_SESSIONS_SANDBOX.md). Key browser APIs:
Playwright `chromium.launch`, locator fill/click/filechooser, screenshot and DOM measurement;
`route.fetch/abort/fulfill` only for labelled network faults. Native own-window snapshot and resize
used the existing development hooks. No real harness binary, official desktop or model was invoked.

## Separate limitations

- Full-page refresh loses **ordinary unsent composer drafts**. History refresh retaining a draft
  and persistent receipts recovering already accepted messages are different behaviors. No draft
  persistence feature was added.
- Claude has no corresponding durable receipt mechanism. Normal echo/send was tested; Claude
  exit-before-echo evidence is limited to existing unit/page injection coverage, not a new actual
  fault-stub/real-native proof.
- Real outside-created sessions, real official desktop continuation, IME, clipboard and VoiceOver
  remain unverified. All real model allowances remain exhausted and were not renewed.
- No private history scan, credential reads, installed database upgrade, default-branch merge,
  release, or replacement of the user's running version.

---

## Previous integration evidence (historical, superseded for current acceptance)

The following record is retained for provenance. Its old frontend findings/counts do not describe
0253b2f; the current findings and fixed-version evidence are above.

### Prior independent integration — 2026-10-09

Backend corrections are implemented. The integrated UI still has an **open P1 delivery-state
finding**, so this is not a claim of complete frontend or real-native acceptance.

## Fixed inputs

| Input | Full commit |
|---|---|
| Backend input, PR #4 | `ad585c59fc932280f49833414e8ea5b90ca3ff75` |
| Initial frontend delivery, PR #3 | `b866e093db3200923ed181f8c98513fcbee3ec87` |
| Opus-confirmed frontend follow-up, includes initial delivery | `202630f659d0411ef81a611ccc98bf09bfc4b4aa` |
| Backend delivery/error fixes | `9a9d6f9c9be4bedb840edbf931d8f39f38c055b9` |
| Initial independent combination | `0a16d235ce700e92603461958bce3feca0e37dcf` |
| **Fixed integrated code tested below** | **`fee9971c6ed5599a679b4a9193c6ba1940609fdc`** |

Integration checkout: `/Users/chan/Downloads/repobridge-integration`, branch
`codex/existing-session-integration`. Backend checkout: `/Users/chan/Downloads/repobridge-backend`,
branch `codex/existing-session-backend`. Frontend checkout and the old main checkout were not
modified. PR #4 continues to target the frontend branch in PR #3; neither PR was merged.
Later documentation receipts do not change the fixed code under test.

## Backend outcomes

- Every accepted Codex message has a durable `client_id` receipt in existing events. A queued
  handshake rejection/timeout/early exit is `not_sent`; confirmed native acceptance is `sent`;
  loss of a response after submission is `unknown`. Original text and attachment references survive
  connection/history reload and service restart. Same-ID retries replay the receipt, never the
  message. A late native confirmation can settle uncertainty; a late exit cannot undo `sent`.
- The backend refuses new Codex sends while a previous receipt is unknown. It does not infer
  delivery from equal text, automatically resend, or automatically clear uncertainty on restart.
- External-held unlink returns `details.external` and `reason=external_confirmation_required`.
  Actual local activity returns `busy_session_id` and `reason=local_writer_busy`. Both checks remain
  inside the atomic unlink transaction. Confirmation is still required before external-held unlink.
- Read failures carry stable reasons and Chinese messages. `history.error` remains a compatible
  string/null; explicit unsupported capabilities carry `capability_unsupported=true`. A generic
  failure does not mean unsupported.
- `POST /api/sessions/<id>/desktop/return` also handles native-link holds. It records user
  confirmation, clears the hold and invalidates history cache. It does not start, send, kill another
  process, or claim observed external exit. Audit records `process_exit_observed:false`.
- No new schema revision in these corrections. Existing association schema 4 remains; all test
  databases were temporary. The user's installed state was not read or upgraded.

Exact additive contract and examples: [EXISTING_SESSIONS_API.md](EXISTING_SESSIONS_API.md).

## Offline evidence on the fixed integration

Final fixed-integration offline suite: **990 passed in 1055.66s (17m35s)**; no failures or skips.
No live test was run.

Static checks on the fixed integration passed: ruff check, formatting (188 files), strict mypy
(59 source files). Related backend regression passed 53 tests in 63.18s; the final receipt/restart
regression passed 12 cases in 17.89s. Those focused counts and earlier per-branch totals are not
substitutes for the final integrated suite.

The final suite uses an absolute source root. A first attempt with `PYTHONPATH=src` was stopped
(485 passed, one failure, 801.78s): detached workers change cwd and loaded the frontend virtualenv's
editable package, producing a different fake-executor invocation path and an integrity refusal.
The failing migration case passed unchanged with the absolute integration source path (1.40s).
That interrupted mixed-path run is not accepted as final evidence; no test was deleted or skipped
and no runtime guard was weakened.

Reproduce from the integration checkout with an available development environment:

```sh
export PYTHONPATH="$(pwd)/src"
python -m pytest -m 'not live' -q --durations=8
ruff check .
ruff format --check .
mypy src/harness_bridge
```

On this machine the existing frontend `.venv/bin/{python,ruff,mypy}` was reused read-only; no
package/environment files were changed. Absolute `PYTHONPATH` is essential with a virtualenv
installed from another checkout. Tests isolate HOME/config/Git/state, reject real CLI binaries,
and permit only test-owned loopback traffic. Prior real-turn allowances remain exhausted.

## Rendered integration with simulated native sessions

Chrome was launched by Playwright with a new temporary profile and 1280×900/900×640 viewports.
Only the three loopback test servers were allowed by the browser route. Each server used an
independent temporary HOME/native-history/state directory, port 0, stub CLIs and fake application
bundles. Native-shaped histories were created **before** association, outside RepoBridge; unrelated
project fixture history was excluded. No account, real private history, or model call was involved.

| Flow | Observed result |
|---|---|
| Page identity and discovery | Correct project/window, nonblank controls, two scoped Claude candidates, partial visibility and true empty-history state; no extra discovery request during a 2.1s idle interval. |
| Preview paging | Loaded all 151 native user items with 151 distinct IDs; no duplicate pages. |
| Link and concurrent duplicates | No native run on add; concurrent adds returned the same local association. |
| External protection | Unlink returned 409 with `details.external`; UI confirmation alone created no run and sent nothing. |
| Original-ID continuation | Composer explicitly submitted a new message; CLI resumed the original Claude ID, one resume run, no old-message replay. |
| Simulated desktop return | UI opened the fake Claude Desktop and released the local writer. Appending to the same synthetic transcript then returning refreshed the new item; confirmation added no run. |
| Remove and re-add | Actual UI removal preserved native history; re-add returned the same local/native IDs and reinstated the external hold. |
| Codex handshake writer refusal | Actual stub RPC refusal, no injected page event: receipt `not_sent/native_writer_busy`, original text + one attachment retained, newer composer draft not overwritten. |
| Codex submission then process loss | Actual stub process exit: receipt `unknown/native_process_exited`, text + attachment retained; backend rejected a new send with 409 `delivery_unknown`. **Frontend misclassification below remains.** |
| Normal sessions | Included in final offline regression: start/send/stop, conversation/settings/attachments, history, view switch and desktop guards use the same existing routes. |

Observed JavaScript page exceptions: zero in completed delivery/continuation probes. Browser
console errors were the deliberately exercised 409 refusals. Two keep-alive connections reset when
browser contexts closed; the stdlib server logged ConnectionResetError, with no failed flow response.
The three owned test servers and their stub processes were shut down after the probes.
Initial probe attempts used incorrect
locators (an inactive conversation intentionally has no toolbar Resume button), wrong detail-vs-state
fields, or failed to wait for asynchronous re-link completion; these were corrected in the probe,
not hidden as product passes. Final flow observations above are based on completed operations.

Local evidence directory: `/private/tmp/repobridge-integration-acceptance/` contains
`final-check.log`, `ui-delivery-result.json`, `ui-relink-result.json`, the earlier per-flow records,
probe scripts and screenshots. `desktop-return.png`, `delivery-busy.png`, `delivery-unknown.png`,
`long-preview.png`, and `relinked-900-stable.png` are synthetic evidence, not real desktop proof.
Temporary auth URL metadata is not published to the repository or PR.

## Required Opus review

1. **P1 — unknown is still presented as definitely unsent in frontend `202630f`.** Reproduction:
   link the isolated Codex fixture, confirm external ended, attach a text file, send while handshake
   is pending, type a new draft; the stub exits after receiving `turn/start` and before replying.
   Backend receipt is `unknown`, but `checkInflight` converts ended-run/no-sent into `unsentFail`;
   the UI says “没有发出的消息” / “连接失败，这条消息没有发出” and offers “放回输入框”. New sends
   are safely blocked by the backend, but the interface invites the wrong recovery action. Consume
   `delivery.state` and the durable `/delivery?client_id=` receipt before classification; keep
   uncertain text/attachments separate, including after reload or missed SSE; never auto-retry.
   Preserve existing late-`sent`, new-draft, attachment and double-failure protections. Add a UI
   regression driven by these real stub outcomes rather than only synthetic page events.
2. **P2 — narrow window clipping.** In a fresh 900×640 browser context, sidebar open, linked Claude
   conversation, the body measured 955px and the composer mode/model/effort row extended past the
   right edge. The stable screenshot is `relinked-900-stable.png`. Review the controls' responsive
   layout in the owned frontend/desktop shell; the 1280×900 path was usable. This is not a claim
   about the installed native window.
3. Consume `history.reason` / `capability_unsupported` for explicit unsupported display if desired;
   current generic “读取失败” is safe and must not regress to treating every failure as unsupported.
   Recheck external-held unlink using the now-correct `details.external`, without loosening the rule.

Full UI acceptance remains open until the P1 correction is delivered in a confirmed frontend SHA
and independently integrated/retested. Real designated outside-created sessions, official desktop
continuation, IME/clipboard/VoiceOver and native-window rendering remain unverified in this round.
No default merge, release, installed-version replacement, real database migration, extra model
allowance, or unrelated-history scan occurred.
