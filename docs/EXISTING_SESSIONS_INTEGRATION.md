# Existing-session independent integration — 2026-10-09

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
