# PR #5 — independent macOS candidate verification

2026-10-11. **Offline/synthetic only. 1066 passed / 0 failed / 0 errors / 0 skipped; pytest 1104.20s; exit 0. Ruff check, format (208 files) and strict mypy (65 source files, Darwin target) each exit 0.** This record recommends a precise
candidate for review; it does not advance the integration base, merge a PR or replace the installed
App. Previous accepted candidate `78253365266eb5f47f0436dddf4b69522def917e` keeps its historical
1007-test/browser receipt. Its native input/accessibility acceptance was never claimed as passed.

## Fixed inputs and correction

| Role | Full SHA |
|---|---|
| PR #5 base / unchanged existing integration | `92ed653eaa965ae5355ed3270555e22058888afc` |
| Cloud tested code (not fully passing on Linux) | `3186dbca86b64866b0ede02d10be201442ae1863` |
| PR #5 exact input HEAD | `70a5d73f388ec99ff6370dcf8eacdbb0b47b024f` |
| Necessary EF3 fix + added backend regressions / **actual final code tested** | **`560056f11858f9f02b01ee3966ba2aaf41d41c54`** |

PR input's parent→HEAD changes are exactly three Markdown files (ENGINEERING_FOUNDATION,
ENGINEERING_FOUNDATION_RESULT, OBSERVABILITY_EVENTS). New independent worktree:
`/Users/chan/Downloads/repobridge-foundation-candidate`, branch
`codex/engineering-foundation-reverification`. Existing frontend/backend/integration worktrees and
PR #3/#4/#5 branches are preserved. Any later candidate commit appends only the documentation files
listed in the final handoff/receipt; source identity stays the tested commit above.

**Finding EF3-R1, reproduced and fixed:** the App constructed/bound WorkbenchServer, called start,
and only then registered its close callback. When Thread.start failed, or start raised after the
HTTP thread began, both `repobridge` and `hbridge app` leaked the listener. Independent failing
regression: **4 failed / 2 passed, 7.32s** (the existing `_serve` failure path was already clean).
The test's finally block cleaned up its own failed instances; no leaked listener was left behind.

`app.py` now registers HTTP and Workbench cleanup before server.start, retaining Workbench→HTTP→App
lock→root-lock order. `server.close` does not call blocking shutdown on a never-started thread;
started threads are shut down/joined and the socket closes. This is the PM-authorized narrow App
startup/cleanup boundary; no static UI, native_mac.py, window or input implementation changed.
Six repaired entry cases assert real closed sockets, stopped notifier/HTTP threads, root/App lock
reacquisition, rebinding the same port and successful subsequent actual-entry startup.

## Host, environment and execution

- Actual host: **macOS 26.6.2, Darwin, arm64, Python 3.11.16**. No global platform override.
  The six previously failing macOS-capability tests ran against the actual platform. Existing
  unit tests may simulate platform-specific branches; they are not native desktop evidence.
- Directory-lock scope: **local internal APFS**, `/System/Volumes/Data`. `/private/tmp` and pytest's
  `/private/var/folders/.../T` are on this volume. No network disk, external volume, other filesystem
  or Linux process-reaping claim follows from this run.
- Source import and `PYTHONPATH`: `/Users/chan/Downloads/repobridge-foundation-candidate/src`.
  `app.__file__`, `service.__file__`, runtime_env and code SHA were checked. Existing venv at
  `/Users/chan/Downloads/harness-bridge/.claude/worktrees/repobridge-product-direction-8e26f9/.venv`
  was reused; no install/upgrade. Mypy targets darwin and does not validate Linux-only branches.
- Invoking process had all four gate markers **unset**: CLAUDE_CODE_REMOTE,
  CLAUDE_CODE_REMOTE_SESSION_ID, CODEX_CLOUD, CLAUDECODE. None was stripped to run these checks.
  The new sandbox launcher preserves inherited markers; eight new cases inject each marker for
  both Claude and Codex and check actual start/send refusal with no run/resume/turn log.
- Independent state/native HOME/config, explicit fake CLIs and fake desktop apps, loopback-only
  browser requests and fresh ports. Discovery may start read-only query CLI processes; “no model
  sends” is not a claim that discovery starts no process. No actual personal history/auth/state,
  native desktop window/control request, model, remote CI or installed version was used.

Cloud evidence remains **1041 passed / 7 failed / 0 skipped, check.sh exit 1**, Linux, with exactly
three markers removed from its pytest process. Do not relabel that run green or macOS-native.

## EF1–EF4 and regression conclusions

| Item | Independent result and evidence |
|---|---|
| EF1 state isolation | PASS: synthetic schema-4 unmarked prod state reached by inherited, explicit and symlink paths is refused; byte/size/mtime snapshots unchanged. Dev/test fresh markers, same-owner reuse and foreign-owner refusal pass. Both real App entry functions also start default prod and custom legacy prod against self-created full schema-4 stores, no ownership marker, no run, no path change. |
| EF2 directory locks | PASS on the APFS scope above: parent→child, child→parent, same root, symlink alias refusal; unrelated siblings coexist. Separate-process races: 8 nested + 8 same-root pairs, one winner; sibling pair both hold. Killing only the test-owned holder releases locks. These are actual macOS flock calls; PM's earlier single-process probe alone was not treated as sufficient. |
| EF3 entry preflight/cleanup | PASS **after 560056f**. Original input has the additional listener leak described above. Both entries refuse illegal paths before writes/construction, preserve old prod snapshots, and clean up constructor/thread-start/after-start/serve failure boundaries. HTTP resources, Workbench, App lock and test-root lock can be reused after failure. |
| EF4 session-scoped receipts/statistics | PASS: same client_id in A/B, actual HTTP+stubs, A sent/B unknown, business receipts distinct; submitted=2/sent=1/unknown=1/unknown_later_confirmed_sent=0. Reused requests and rereads add no turn or accepted submission. Distinct v2 aliases and operation traces, original latency starts retained, summary equals local export. v1 lines re-key by session and retain their latency/op-link limitation flag. sent is CLI acceptance, never task success. |
| Diagnostic failures/privacy | PASS: disabled/broken sink, recorder initialization failure, queue.Full and ENOSPC preserve unknown→sent, failed run, attachment, one native turn and original ID. Product events default off. Synthetic secrets in body/paths/headers/URL/native error/session/client IDs are absent from validated diagnostics/summary/zip; exports stay local. |
| Execution gate | PASS: all four markers survive sandbox env construction; actual start/send refused for each harness, no run or native start/turn. Existing linked-session gate tests separately allow discovery queries and refuse resume/send. No product gate changes. |
| Existing business/UI | PASS: scoped discovery/link/dedupe/original ID, first-turn protection, single writer and no replacement thread, unknown send block, late sent, not_sent restore once, draft/attachment retention, older/background cleanup and confirmation-only desktop return. Backend suites + fresh actual-page probes, not old receipts alone. |
| Both existing P2 | Browser regression PASS: factual failed exit/diagnostics survive sent+reload; uncertainty clears only by proof. 900×640, 700×640, 1280×900 have no document/body horizontal overflow and visible composer controls. Prior long-model/native-window evidence retains its old scope; no new native window check. |

## Actual check results

| Run | Result |
|---|---|
| Original PR input: four foundation test modules + exact cloud-seven cases | **48 passed / 66.34s, exit 0** (41 foundation + 7 formerly failing cloud cases) |
| New independent startup regression against unfixed input | **4 failed / 2 passed / 7.32s, exit 1**, retained as reproduction |
| Added startup/gates/sink-parity tests after fix | **17 passed / 38.21s, exit 0** |
| Added HTTP alias/op/latency/export/privacy test | **1 passed / 3.00s, exit 0** |
| Final required offline/static/type check at 560056f | **1066 passed / 0 failed / 0 errors / 0 skipped; pytest 1104.20s; exit 0. Ruff check, format (208 files) and strict mypy (65 source files, Darwin target) each exit 0** |
| Existing-page independent checks | 15 delivery/banner + 4 busy + late-proof + 5 response-loss + 4 event-order cases; all pass, no page exceptions |
| Older-page independent checks after actual service restart | **35 explicit assertions pass** (4 setup, 31 behavior/health); competing reads held/count-checked, no send/run added |
| Default/custom prod actual-entry compatibility probe | **4 cases pass**, exit 0; _serve replaced by assertion callback, no window or native execution |

The cloud seven are recorded individually by test ID in `focused-input.xml` and final JUnit:
existing-session desktop roundtrip Claude/Codex (2); Claude desktop release, Codex deep link,
desktop unavailable/CLI command (3); server conversation routes (1); ZCode cancel transport/peer
(1). All seven pass on this Mac. **The Linux ZCode cancel failure's cause remains unresolved**;
local ProcessLookupError success does not establish cloud zombie reaping or close that Linux issue.

Full check is the four scripts/check.sh commands using existing venv binaries, without dependency
resolution. One completed replacement full run after the interrupted attempt (retained below); no repeated full baseline, skips, weakened
assertions or simulated platform used to make the macOS result green. CI is workflow_dispatch-only
and remains **NOT_RUN**; no workflow, GitHub merge/close or default-branch operation performed.

## Page evidence and reproducibility

Durable local evidence directory:
`/Users/chan/Documents/Codex/2026-10-06/harness-bridge-agent-local-glm-macos/repobridge-pr5-qa/`.
`README.md` gives exact commands; `manifest.sha256` fingerprints evidence. Index:

- `environment.json`, `focused-input.log/xml`, `ef3-before.log/xml`, `review-after.log/xml`,
  `ef4-http.log`, `final-check.log/xml`, `final-check-result.json`, `final-check.incomplete-20261010.log`, `evidence-audit.json`, `prod-compatibility.json` and its script.
- `ui/*-result.json`, `ui/older-out/report.json`, retained replay scripts, logs, screenshots and
  `ui/service-stop.json`. Four owned UI servers stopped; process/port checks recorded.
- `cloud-handoff.md`: exact wording correction, fix/verification SHA and remaining cloud limitation
  for PR #5; no change to Cloud's historical counts.

Browser plugin absent: installed headless Chrome/Playwright reused, fresh contexts and only the
owned 127.0.0.1 URLs. Page identity/meaningful content/no framework overlay and actual interactions
pass. No JS exceptions; resource errors are deliberate HTTP 409/500/503/404 or aborted-request
injections. Server BrokenPipe/ConnectionReset output accompanies those test client disconnects.
Geometry JSON and inspected screenshots are distinct evidence. Backend+fault-stub receipts and
synthetic native clientId proof are distinct from page-injected stale event/HTTP/pagination order.
No browser result is real IME, VoiceOver or real native-session proof.


## Resumed check and evidence boundary — 2026-10-11

The prior full attempt stopped without a pytest summary, JUnit report or recorded exit code.
On takeover there was no matching process; its 1009-byte log last changed at 2026-10-10 22:05:47
Europe/Paris and its last complete progress line was 54%. No failure trace or termination reason
was recorded. It is **INCOMPLETE, exit unknown**, not a pass or a proven test failure; the session's
compaction failure alone does not establish the process's cause of termination. The original bytes
are preserved as `final-check.incomplete-20261010.log` (SHA-256
`e1649aca49908c9d5db394fdac0cae19368ccfd278fe23098f636c1ba6beff56`).

One necessary complete replacement check ran from the clean, unchanged 560056f checkout using
the existing venv and absolute candidate PYTHONPATH. `final-check-result.json` records UTC start/end,
exact argv/cwd, Python/import identity, owned process IDs and each actual exit code;
`final-check.log` and `final-check.xml` record the complete result. The wrapper reports elapsed
process time separately from pytest/JUnit durations. No source changed while it ran.

The invoking environment had none of the four cloud/nested markers, and the wrapper removed none.
The pre-existing `tests/conftest.py::isolated_env` fixture scrubs provider/harness variable prefixes;
this is distinct from the product sandbox, which preserves markers. Explicit gate tests reinsert
each marker after fixture setup and test both harnesses. This run is not evidence that the entire
suite passed under an inherited cloud/nested marker. No assertion, skip or platform rule changed.

Saved 2026-10-10 focused/UI evidence was audited and reused, not silently re-executed. Focused log
durations and JUnit suite durations are retained separately; verdicts/counts agree. The final full
run includes the added regressions and the same seven formerly failing Cloud test IDs.

## Cloud/Linux follow-up ownership

Cloud's six desktop failures reach the `sys.platform == "darwin"` capability gate; their expected
desktop success/reason differs from Linux's refusal. This explains those recorded failures and
does not make the Linux full suite pass. The seventh test is
`tests/integration/test_zcode_stub_flow.py::test_cancel_stops_both_transport_and_peer`.
It passes cancellation, exit-confirmation and `not group_alive(...)`, then fails because
`os.kill(peer_pid, 0)` did not raise. Source inspection shows `runner.group_alive` excludes zombie
members, so zombie retention is a plausible explanation, **not a verified cause**.

Cloud should capture the test-owned peer/transport PID, PPID, PGID, state and start identity at the
assertion, plus the container init/reaper behavior and bounded post-cancel observations; distinguish
a zombie, a live leaked process and PID reuse. Preserve the existing assertion and gate markers;
record invocation and fixture conditions explicitly. No Linux process snapshot exists in this Mac
receipt, so this item stays OPEN. No Linux rerun or remote workflow was launched here.

PM may review this exact separate candidate for the next macOS offline/synthetic stage. Local Opus
continues to own static UI, native_mac.py and native IME/clipboard/VoiceOver/focus acceptance. The
old real-session checklist remains bound to its old candidate until a separate scoped update.
The prepared Cloud/PR text is a local handoff artifact; it has not been posted or sent.

## Post-test documentation-only differences

The final receipt commit changes only these eight files; no test/source/asset/script/dependency
changes follow 560056f:

1. STATUS.md — current candidate recommendation and retained old receipt.
2. HANDOFF.md — independent branch, actual versions, limitations and next owner.
3. docs/VALIDATION_MATRIX.md — EF1–EF4/macOS/privacy/gates/CI evidence scopes.
4. docs/DECISIONS.md — state ownership, directory locks, cleanup and diagnostic identity decisions.
5. docs/ENGINEERING_FOUNDATION.md — actual macOS lock scope, EF3-R1 and isolated startup commands.
6. docs/ENGINEERING_FOUNDATION_RESULT.md — correct old “local native acceptance” to offline/synthetic; link local follow-up without changing Cloud counts.
7. docs/ENGINEERING_FOUNDATION_MACOS.md — this independent result and evidence index.
8. docs/ENGINEERING_FOUNDATION_CLOUD_HANDOFF.md — exact fix and wording correction for Cloud/PR #5.

Final candidate HEAD and confirmation of this exact diff are recorded in the delivered
verification.json and PR handoff. No full-suite rerun is needed solely for these Markdown edits.

## Recommendation and unchanged limits

Recommend this exact candidate for review as the next macOS offline/synthetic acceptance version. The local scope passes; Linux cancellation remains open and native/CI scope remains NOT_RUN. Do not move PR #5's integration base to this branch before review. PR #3/#4/#5
stay draft, with their original dependency chain. Old candidate 7825336 remains available and its
historical receipt is not rewritten. Source after the final test stays identical; documentation
changes and final candidate HEAD are listed in the delivered receipt.

Real outside-created sessions, official-desktop continuation, native IME, system clipboard,
VoiceOver and native focus remain **NOT_RUN**. Claude has no durable receipt/pre-echo proof is
limited; ordinary unsent drafts are lost on full-page reload; persisted old failure summaries are
not migrated. No new real model budget, database schema upgrade, install, release or replacement.
