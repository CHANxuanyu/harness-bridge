# Existing-session independent revalidation — 2026-10-09

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
