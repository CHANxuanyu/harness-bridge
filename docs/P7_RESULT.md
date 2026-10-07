# P7 result and local candidate — 2026-10-07

**Current status: bounded native packet complete; finished-session desktop visibility observed after unlock; full Codex GUI lifecycle remains open.**
The [V01–V15 closeout matrix](P7_CLOSEOUT.md) is the concise current acceptance index; the
chronological observations below preserve original failures and later authorized corrections.
Runtime 0.1.0.dev2 / plugin 0.1.0-alpha.5. Apache-2.0, local candidate only; no remote
publication or push. This is the current result; the earlier synthetic rehearsal remains
historical evidence in [P7_ACCEPTANCE.md](P7_ACCEPTANCE.md).

## Desktop continuation after unlock — 2026-10-07

Runtime **0.1.0.dev2**, plugin **0.1.0-alpha.5**. Claude's original session is visible in its
sidebar with the same UUID, full prompt/tool/final history and original worktree (verified
through Claude and Finder accessibility). The human explicitly confirmed the original Codex
page and sidebar item after native navigation. Its list API still omits the exec session:
list-source filtering is not a reliable proxy for actual GUI visibility.

Real acceptance exposed a Bridge defect: dev1 redirected Claude desktop-launcher streams;
2.1.291 rejects that before opening. Preserve the initial exit-1/unknown receipt. The correction
uses a bounded PTY with no input; one explicit, narrowly qualified legacy-pipe retry retains the
old record. Native acknowledgement and GUI checks then passed, and receipt replay did not
reopen. Missing exits, success, timeout and newer transports never qualify for that recovery.

Codex uses the official existing-thread URL in the validated macOS app (26.930.31730,
CLI 0.160.0), checking identity/URL registration and the original embedded executable. The
first version probe refused because the implementation expected `codex` instead of the observed
`codex-cli` version prefix; no request was reserved. Corrected the pin and independent fixture;
the native URL request and replay then succeeded. No prompt/new/fork route or model turn.
Official route: [existing-chat links](https://learn.chatgpt.com/docs/reference/commands).

Checks: pre-edit desktop baseline **26 / 8.21s**; PTY/CLI **41 / 23.87s**; expanded desktop/
Codex/CLI/plugin **73 / 52.42s**; dev2 plugin compatibility **26 / 24.44s**; corrected Codex
version pin **6 / 2.56s**. Lint/format 146 files and strict mypy 40 runtime files pass.
A mistyped test path collected zero tests before the corrected command. No failed test was
removed/skipped. Prior full 732 remains reused; this is affected coverage, not another full run.

Actual Codex/ZCode alpha.5 upgrades retain the connection and all 34/15 unrelated plugins.
All 16 files per cache match, both 36-command checks pass, and Skill validation passes.
No new Executor attempt/model message, provider/billing change or remote publication.
Private receipts: takeover chat `work/p7-desktop-unlocked/result.json` and `work/p7-plugin-alpha5/`.

**Remaining:** full Codex GUI quit/relaunch with a bounded fake job, plus checking the original
Codex chat after that restart. Do not close this app through a refused automation route. The
human performs the actual quit/reopen; a prepared observer records process identity and job
continuity. Preserve all real task histories/worktrees. All native model allowances stay spent.

## Explicit decisions and limits

The user approved different budget contracts by harness for new tasks: Codex explicitly has
no native internal-turn ceiling and uses attempts, wall timeout and cancellation. Old frozen
numeric-turn tasks remain refused. Native ChatGPT/provider/configuration checks, permissions,
workspace ownership and explicit real-call authorization remain mandatory.

The separately authorized native packet allowed at most **7 Executor executions: Claude 4,
Codex 3; 2 repairs; 885 cumulative reserved wall seconds**. Stop on authentication, permission,
quota errors or unknown exits; no extra billing or provider changes. This is an execution
ceiling, not an assertion that Codex can count/limit internal model calls.

## Initial live observations and first stop

1. First goal: Claude completed diagnosis without edits or permission denials (12.858s,
   reported 2 turns). Codex's worker rejected its reconstructed command before spawning an
   Executor: `INTEGRITY_ERROR`, `spawn_failed`, confirmed non-start. It had omitted verified
   configuration overrides. This was a Bridge defect, not a Codex model failure. The failed
   goal and frozen task/attempt records were preserved and terminated; no limits were edited.
2. Fixed both worker command reconstruction and its Codex-specific environment gate. The
   worker now rechecks native metadata, rebuilds the overrides and compares the full reserved
   invocation digest; changed configuration or provider environment fails before spawn.
3. Reallocated the remaining budget to a fresh goal: Claude one implementation execution,
   Codex diagnosis + one repair. This preserves the original global per-harness/attempt/wall
   ceilings and the three planned fault cases. Prior real Claude exact-session repair evidence
   is reused from [LIVE_REPAIR_RESULT.md](LIVE_REPAIR_RESULT.md), not claimed as rerun in P7.
4. Both native Executors were observed **RUNNING concurrently** in distinct owned worktrees,
   on the same pinned base. Claude changed only `tagnorm/normalize.py`; the frozen external
   check passed, scope was clean, and the Advisor inspected the diff and approved its exact
   snapshot. Claude took 10.186s, reported 4 turns, observed model `claude-opus-5-5`.
5. Claude attempted an extra Python sanity check through Bash, outside its allowed tool list.
   Native permissions denied that command once. The command did not execute. Its requested
   code change and Bridge verification passed, but the user-authorized stop condition still
   applies. All further live calls stopped and isolated live gates were closed.
6. Codex completed diagnosis-only in 29.021s, changed no files, returned one native UUID and
   mnemonic `BOXJOIN`; its expected mandatory checks failed on the untouched stub. Requested
   model was `gpt-5.6-sol`; observed model remains unknown. The Advisor saved specific repair
   feedback on that same task/session/worktree. No repair was dispatched after the stop.

## Authorized continuation and current result

The human explicitly resumed the stopped packet on 2026-10-07. No limits or permissions were
expanded. The original Codex task resumed its exact native UUID
`01a11375-1bfc-7ba3-a351-8d206887423c` and unchanged worktree, recalled `BOXJOIN`, and changed only
`tagformat/render.py`. Independent external checks passed in 0.023s; the Advisor inspected the
one-line implementation and approved that exact snapshot. Native execution took 33.567s.

The two approved inputs were composed into a separate integration workspace. The unchanged
combined verifier passed in 0.027s, the full two-file diff was reviewed, and the exact approved
commit **73f485d437bc5bcf1796f6bd141e0b3d1be0033f** was delivered to `bridge/p7-result` in the
isolated fixture repository. Same-key delivery replay retained the identical receipt/commit.
Goal `goal_e77ac7ce90244b89ac7e` is **DELIVERED**; source checkout/index and frozen checks are
unchanged. This proves the real one-Advisor/two-harness collaboration/delivery scenario, not
completion of every P7 fault case.

| Native case | Observation | Acceptance |
| --- | --- | --- |
| Codex exact-session repair | Same UUID/cwd, recalled mnemonic, clean assigned diff and external check | Passed |
| Codex running cancellation | Tool start observed; CLI ended after cancel; old receipt said CANCELLED/confirmed, but secondary OS audit found its separately grouped Python sleeper alive | **Failed** |
| Claude wall timeout | Tool start observed; timeout at 15.576s for a 15s limit; finish absent, no matching sleeper remained in OS audit | Timeout path observed; no successful task claim |
| Claude native turn cap (initial stop) | Not launched before explicit continuation | Historical NOT_RUN; completed below |
| Combined integration and exact local delivery | Both required inputs, frozen combined check, exact review/commit and replay | Passed |

The detached Codex sleeper had a different process group and was reparented to PID 1. Its
identity and exact known fixture command were checked before manual TERM; a subsequent OS
check found no matching fixture survivor. That cleanup does not turn the failed cancellation
case into a pass. Preserve the old native/job receipt alongside the contradictory observation.
Claude timeout was already in flight when the secondary audit discovered the Codex survivor;
it finished under its existing bound. No further real Executor was started after discovery.

## Final authorized bounded checks

The user accepted the concrete remaining proposal on 2026-10-07: two executions / 150 seconds,
adding exactly one Codex execution / 90 seconds beyond the original envelope. The distinct
new receipt preserves the previously unauthorized proposal and all frozen historical tasks.

- **Codex cancellation retest passed:** 11.694s; tool start observed, finish absent; six observed
  descendants, five individually signalled, no known survivor and no inspection failure.
  Independent OS inspection found no matching fixture sleeper. The old failed case stays failed.
- **Claude native turn-stop passed:** 4.442s; native `error_max_turns`, exit 1, no permission
  denials, rate-limit status allowed. The configured value was 1; native `num_turns` was **2**.
  The stream contains one assistant Read tool, no Write and no completion marker. This proves
  native stopping behavior, not that the numeric report or internal call count is at most 1.
  The task remains AWAITING_REVIEW with failed Executor outcome, as expected for fault injection.

**Final spent: 8 actual executions (Claude 4 / Codex 4), 1 repair, 975 reserved wall seconds.**
Observed native duration totals 145.629s, not billed usage. One additional Codex reservation is
proven non-start. All gates are closed. No further native execution is required or authorized.
The bounded packet is complete; full Codex GUI shutdown and the newly requested desktop-list
experience are separate, still unverified product acceptance boundaries.

## Runner correction after the failed cancellation

The runner now observes process ancestry while the native CLI is alive, retains positively
observed descendants across reparenting, and checks birth identity immediately before signalling
a detached child individually. TERM grace and KILL escalation include those observed children.
It never signals an unrelated guessed PID, an inferred detached group, or the original group
after it was observed dead. Process inspection failure or a known survivor prevents confirmed
exit, preserving existing unknown-outcome/project-slot blocking.

Ten new offline cases exercise closed-pipe detached children during cancel/timeout, ignored
TERM, normal root exit with a surviving detached child, failed observation and PID reuse.
These use ordinary local Python subprocesses and no model/auth/network calls. They are not
native Codex acceptance. Sampling is not OS containment: an unobserved fork/reparent between
samples can be missed, and identity check plus signal is not an atomic OS handle. The separate
native cancellation retest passed; these sampling limits remain release considerations.

## Why Claude Desktop did not show an obvious new conversation

Actual Claude Code CLI transcript files were found under the two isolated task worktree project
folders. Their native IDs are `8baf095d-4452-4601-881e-ff61a1f348db` (diagnosis) and
`347cb6dd-57aa-4157-9860-d67a2cd5e1b1` (implementation); metadata matches each Bridge worktree.
The timeout has a third native session, `48604823-c9f4-46c1-8c00-094100797a8f`. No raw transcript
or credential is committed here. Native CLI `--resume` is available; automatic desktop sidebar
synchronization was not tested. No model turn was created to populate a history list. Bridge's
worktree/session/evidence records are the supported locator; a clearer Advisor history surface
is recorded as a product follow-up.

## Native capabilities without inference

- Codex **0.160.0**: native initial/resume help-parse probes accepted explicit cwd/model/sandbox
  and UUID syntax without creating a thread/turn. App-server account/config reads establish
  current ChatGPT account type and default OpenAI provider. A second read confirms each
  per-invocation override, including disabled auxiliary apps/MCP/subagents/plugins/hooks,
  network/extra-root restrictions, explicit model and never approvals.
- Native `_default: null` app configuration is a valid unset value; the preflight recognizes
  it and still requires the effective default and each configured app to be disabled. Raw
  credential/account/config values are never persisted by the preflight. It reads no credential
  file directly. Actual model identity, subscription balance and charges remain unknown.
- Claude **2.1.291**: existing native login reports claude.ai / firstParty / Pro; no provider,
  cloud or nested marker was present. Native turn-stop and wall-timeout behavior were observed
  above; the configured/reported turn-count discrepancy remains explicitly recorded.

## Actual host lifecycle

ZCode **0.16.9**, on this Mac: launched one fake bounded worker from its integrated terminal.
Recorded process ancestry proves that launcher → terminal → ZCode host → ZCode belonged to
that application. Full GUI quit removed those original host/terminal processes; the same
worker remained RUNNING. Relaunched ZCode, used its new integrated terminal to discover the
same goal/job and replay the dispatch key, then cancelled via Bridge. Result: one attempt,
confirmed CANCELLED/exit, no repeated Executor, source unchanged, zero model calls.

This is native **ZCode full-app quit/relaunch with a fake Executor**. P6's actual Codex tool PTY
exit/reconnect is also retained. Full Codex GUI quit, logout, sleep/reboot and native agent-chat
transfer remain unverified; no workaround was used for the refused Codex GUI automation route.

## Distribution and retention

Both hosts passed isolated native alpha.1 → alpha.3 upgrade, uninstall and reinstall. Each
cache matched all 15 packaged files. A dedicated state with one completed fake task and goal
kept every state file unchanged throughout plugin operations. ZCode initially refused a
noninteractive uninstall without confirmation; its documented `--force` confirmation succeeded
in the isolated test profile. This flag only confirms plugin removal, not execution permissions.

An independently installed wheel/runtime passed dev0 → dev1 upgrade, runtime uninstall and
reinstall with the same goal/task ID, one attempt, SUCCEEDED and retained approval. Initial
installation used the ordinary package registry for Pydantic dependencies because the complete
wheel set was not cached; reinstall was offline. No model SDK, authentication or model execution
was involved. Runtime and task state are separate from plugin caches.

Actual user Codex/ZCode plugins were upgraded to alpha.3. All 15 source files match both caches;
34 other Codex plugins and 15 other ZCode entries were unchanged. Both cached connection
checkers pass all 34 command surfaces and still resolve the same existing runtime/shared-state
connection, without opening that selected database. Native Codex skills/list resolves the
new enabled Skill for repo and chat cwd, with no new thread/turn. Current GUI hot refresh is
not inferred from this native catalog result.

See [LOCAL_RELEASE.md](LOCAL_RELEASE.md) for installation, retention and supported-version
boundaries. The fresh-only local builder inventories package members and emits hashes,
LICENSE/NOTICE and these acceptance notes; building never upgrades acceptance status.

## Offline checks and fixes

| Run | Result |
| --- | --- |
| Pre-change plugin baseline | 24 passed; lint/type checks clean |
| Pre-change Codex/concurrency baseline | 93 passed |
| Initial affected budget/preflight run | 143 passed, 1 failed (receipt wording); corrected without weakening guard |
| Corrected Codex affected suite | 101 passed / 23.39s |
| Full shared regression before final preflight hardening | **707 passed / 902.56s**, no failures/skips |
| App/tmp restriction and service wiring hardening | 112 passed / 28.57s |
| Native-null config test before correction | 43 passed, 1 failed; null effective default must yield structured refusal |
| Corrected native-null preflight suite | 44 passed / 9.39s |
| Worker reconstruction and worker/Codex regression | **98 passed / 60.91s** |
| Worker preflight refusal cases | 46 passed / 5.95s |
| Pre-descendant-fix runner/adapter baseline | 70 passed / 4.23s |
| Descendant fix affected runner/adapter cases | 80 passed / 9.23s |
| Final shared regression after descendant correction | **732 passed / 922.88s**, no failures/skips |

The earlier tree had 722 cases covered across full and affected runs. The current runner adds
ten cases: the final shared regression passed all **732 / 922.88s**, with no failures/skips.
Source and tests were unchanged during the run. Lint/format covers 138 Python files and strict
mypy passes on 39 runtime files.
Additional exact worker provider-change/digest-change checks are in the validation matrix. No ordinary test reads actual auth, makes network requests
or spawns a real Claude/Codex binary. Native probes and real acceptance are separate evidence.

## Desktop session continuity (new user requirement)

The user explicitly requested desktop chat-list synchronization, then chose CLI/code work while
the Mac is locked. `desktop status` now reads exact native session/worktree bindings; `desktop
open` implements the official Claude same-session handoff without a prompt. Terminal task,
delivered parent, confirmed exits, current Advisor, binding integrity and validated CLI version
are required. Durable requests make repeated/racing/interrupted calls avoid duplicate handoffs.
No task, approval, delivery or Executor budget is changed; no vendor transcript/DB is edited.
Native acknowledgement remains separate from verified desktop visibility. Actual Claude handoff
and UI-list verification are NOT_RUN. Codex metadata probes could read/name the original Executor
but section/pin changes did not expose it in list_threads; those organization changes were undone.
See [DESKTOP_SESSIONS.md](DESKTOP_SESSIONS.md).

Affected desktop/CLI/coordination checks: **55 passed / 37.69s**, including 26 new cases; lint/format
141 files and mypy 40 runtime files pass. Initial test run had 26 pass / 2 fixture assertion failures
(CLI adds `ok`; synthetic goal omitted allowed executor), both corrected. Earlier corrected desktop
run: 23 passed / 5.92s, before adding race/Advisor-probe checks. Full 732-case baseline is reused;
no new full-suite claim and no real model was used for desktop code/tests.

## Evidence location

Private raw evidence remains outside the public repository, in the takeover chat's
`work/p7-live-20261007/`, `work/p7-host-lifecycle/`, `work/p7-distribution/`, and `work/p7-codex/`.
Records include authorization, immutable packet hashes, stop receipt, failed first goal,
replacement delivered goal, native invocation receipts, descendant failure/cleanup observations
and independent check artifacts. These logs are
not inherently safe to publish; only this manually reviewed summary is committed.

Final desktop session selection rejects a later executed attempt with missing identity, rather than silently opening an older session. Affected desktop rerun: **26 passed / 6.98s**; no additional full run.

## Alpha.4 delivery follow-up

The Advisor plugin now handles requested desktop continuity after delivery, before cleanup,
using exact native bindings and status-specific reporting. A locked/unavailable desktop stays
pending. Unsupported Codex synchronization never falls back to a replacement chat or model turn.
The user explicitly remains away from home; no GUI handoff has been attempted.

Plugin regression: **26 passed / 17.22s** (24 existing plus 2 new incompatible-runtime refusal
cases); Skill Creator validator passed using cached PyYAML after the repo venv lacked that
validation-only dependency. No dependency was added to the project. Lint/format 142 files and
mypy 40 runtime files pass. Core runtime did not change and prior core checks were not repeated.

Native upgrades enabled alpha.4 in both actual host profiles. Each cache matches 16 files;
each model-free checker covers 36 commands without inspecting selected state. All 34 unrelated
Codex and 15 unrelated ZCode plugin entries and the connection file are unchanged. A fresh
native Codex skills/list resolves the enabled alpha.4 Skill for repo and chat cwd, with no error.
Current desktop refresh is unobserved.

Read-only Codex 0.160.0 probing verifies `source: exec`: its exact worktree has zero default/
interactive results, one explicit exec result with the original UUID. Native source filtering
is proven; the GUI query and a supported sync route remain open. No thread/turn, resume, import,
source rewrite or new real execution was performed. Evidence: private `work/p7-plugin-alpha4/`
and `work/p7-codex-list-probe.json` in the takeover chat. Final native packet counts remain 8
executions / 1 repair / 975 reserved seconds, gates closed.

## Local distribution closeout

The repository build now produces the committed source archive, complete linked documentation,
standalone standard-library verifier and transport ZIP, alongside the runtime/plugin artifacts.
It replaces the temporary chat-only packaging steps. A clean commit is required; mixed source,
output collisions and changed build inputs are refused. Verification checks hashes and compares
runtime, plugin, docs and license files against the source archive without installing or executing
them. The README no longer incorrectly reports alpha.3 or unfinished cancellation/turn-stop checks.

New isolated distribution suite: **12 passed / 2.81s**, lint/format 144 files and mypy 40 runtime
files clean. Initial 6 failures exposed a legitimate Git archive root-directory handling bug,
corrected without removing path/links checks. Runtime/plugin code and the native ledger are
unchanged. Current remaining work is defined in [P7_CLOSEOUT.md](P7_CLOSEOUT.md); user-deferred
UI acceptance and unresolved Codex sync are not upgraded by a successful build.
