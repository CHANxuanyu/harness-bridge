# Status

## W8 model / effort / permission-mode controls, attachments and native forms — 2026-10-08

**Controls (W8).** Under the conversation input: permission mode, model and reasoning effort
selectors. Options come only from the catalog the installed CLI reports (Claude Code `initialize`:
models with their effort levels and auto-mode support, commands; Codex `model/list` with per-model
reasoning efforts and image support, filtered by `configRequirements/read`), fetched by a short-lived
process that starts no session and no turn when nothing is connected. Choices are applied with each
harness's own mechanism — Claude Code control requests `set_model`, `apply_flag_settings
{effortLevel}`, `set_permission_mode` (idle, or before the next message); Codex `thread/start` /
`thread/resume` parameters and `turn/start` overrides (Codex has no separate "set" request, so a
choice travels with the next message) — and shown as **confirmed only when the harness reports it
back** (`get_settings`, the echoed mode, `system/init`, the API's own per-turn model; Codex
`thread/read` and the loaded thread's `thread/resume`). States: selected → applying → confirmed /
failed. A refusal shows the CLI's reason and keeps the previous value in force; dependent changes roll
back; a choice refused while connecting blocks that send (draft kept). Terminal launches pass explicit
choices as the CLIs' own flags (shown as "passed, not confirmable"). Not offered: Claude
`bypassPermissions`, Codex full access.

**Input (W8).** Images (pasted, dropped or picked with the native open panel) go as Claude image
blocks / Codex `localImage`; other files as Claude's own `@"path"` mention / a Codex path list; `@`
searches project files; `/` lists Claude Code's own commands. Codex `requestUserInput` questions and
MCP forms (form and URL modes) are answered in the conversation instead of being refused; secret
answers are not stored.

Defects found while using it and fixed: clicks swallowed when the selectors re-rendered; a refused
model's reason overwritten by the read-back; an effort reset surviving a refused model change; the
read-back overwriting a confirmed mode with the settings-file default; a send going out with the old
model after a refusal at connect; a guessed effort shown before Codex reported one; two ticks in the
Codex model menu; a `.pill` class collision; `[object HTMLDivElement]` in Details (deep-flattening
children also fixes the technical-details rows); misleading "not in effect" wording; attachment paths
in history; native snapshots missing popups (animations frozen while the display sleeps).

Checks: workbench tests 81 (23 new); Codex behaviour checked against the real 0.162 app-server with
a local fake model endpoint (no account, no network); Claude Code control-protocol definitions read
from the 2.1.291 binary; native-window screenshots `docs/screenshots/w8-*.jpg` (synthetic project,
stub CLIs). Support categories (implemented-not-yet-real-verified / native-but-not-implemented /
not-supported-or-not-offered) are listed in docs/WORKBENCH.md.

**Real acceptance (2026-10-08, approved batch, synthetic repo `~/rb-acceptance/demo`, your logins;
Claude Code 6/6 turns, Codex 6/6 turns, nothing added).** Passed: real model catalogs (Claude 12
models, Codex 7, each with its own effort levels); model/effort/mode chosen in the UI and confirmed by
the CLIs themselves (Claude `get_settings` / `system/init` / per-turn API model; Codex
`thread/start` / `thread/read` / `thread/resume`, and Codex's own rollout records match every turn);
Claude acceptEdits vs. a real permission card denied; Codex workspace-write vs. read-only; images on
both; Claude `@notes.md` expanded by the CLI; view switch both ways with the chosen flags and
re-confirmation; App restart; open in Claude Desktop / Codex App with the right history, listed in
both apps, one turn continued in each, history refreshed in RepoBridge; Claude resumed natively after.
Recorded, not passed: no Codex approval card (this machine's Codex uses `approvals_reviewer =
auto_review`); Codex refuses a RepoBridge re-connect while the thread stays open in the Codex App
(its own single-writer lock — reported, not forced). Found and fixed during the run: the toolbar
view toggle had been disabled since W6; Codex mode wording; the Codex writer-lock message; Claude
Desktop wrappers in history. Not verified: account-refused models (none in the catalogs), Codex
questions/MCP forms, file attachments, clipboard/Finder/native picker, the pywebview window with real
sessions, terminal input (both TUIs stopped at their own first-run prompts, left for you).

## W6 conversation view + W7 official desktop continuation — 2026-10-08

**Conversation view (W6).** Every session can now be used in a *terminal* view (the native
interactive CLI, unchanged) or a *conversation* view built only on the harness's own structured
protocol: Claude Code `-p --input-format/--output-format stream-json --permission-prompt-tool stdio`
(the Agent SDK control protocol) and `codex app-server` (JSON-RPC, checked against the schema the
installed 0.162.0-alpha.2 generates). It shows user/assistant messages, streamed Markdown and code,
collapsible thinking/tool calls (input, output, errors, exit codes, files → diff), real permission
cards (allow / deny / the CLI's own "remember" suggestion, Edit shown as −/+), stop-this-turn, retry
and failure notes, and history read from native stores (Codex `thread/turns/list`; the Claude Code
session transcript). The view is chosen per session (default remembered); switching while connected
waits for an idle point, releases the process with confirmed exit and reconnects with the native
resume — same native ID, nothing sent, never two writers.

**Official desktop continuation (W7).** Session menu / Details › “Open in Claude Desktop / Codex”
uses only `claude --desktop --resume <id>` (PTY, official acknowledgement required) and
`codex://threads/<id>`. RepoBridge releases its own connection first and then holds the session
(“opened in X”) until the user confirms the other side is done; `/desktop` typed in the Claude TUI is
detected. History can be refreshed from the native store after continuing elsewhere. Executor-era
desktop evidence is not counted for workbench sessions.

Defects found while using it in a test instance and fixed: `[hidden]` overridden by button display
(stale “new messages” button); absolute/truncated paths in tool titles; diff not opening from a tool
(absolute vs relative path); Edit permission shown as raw JSON and an unexplained “remember” option;
user-declined tools shown as failed; permission-card class colliding with the activity timeline;
failed native resume without its reason; narrow toolbar squeezing the title; dev snapshots stale when
the window is covered; a test instance able to open the real desktop apps (now fake bundles +
recording opener in dev mode).

Checks: workbench tests 58 (22 new); full offline suite 917 passed / 18m04s (details in HANDOFF); real
`codex app-server` interface shape probed without credentials or turns; native-window screenshots in
`docs/screenshots/conv-*.jpg` (synthetic data, stub CLIs, fake app bundles).

**Not verified (needs your authorization or your own run):** real Claude Code / Codex turns in the
conversation view; a real view switch; real desktop open of the right history, presence in the
official sidebar/list, continuing there and continuity back in RepoBridge; real IME, clipboard,
VoiceOver. Policy note (DECISIONS 133): Anthropic's Agent SDK docs say third-party products may not
offer claude.ai login/rate limits without approval; RepoBridge runs your own CLI with its own login
locally, but distributing it to others needs that approval or terminal-only Claude sessions.

Authorization request for real acceptance (one bounded run, synthetic repo `~/rb-acceptance/demo`,
dedicated state dir, your existing logins, App started by you from a normal terminal):
Claude Code ≤ 6 short turns and Codex ≤ 6 short turns (reply, one guarded file edit allowed, one
denied, one stopped turn, one turn continued in the official desktop app, one turn back in
RepoBridge); 2 view switches per harness (no messages); 1 open in Claude Desktop and 1 in Codex;
screenshots/clicks via computer use on RepoBridge, Claude and ChatGPT(Codex) only. The test sessions
will remain in your native histories (named “RepoBridge 验收 …”); nothing is deleted or rewritten.

GitHub: development branch `claude/repobridge-product-direction-8e26f9`, draft
[PR #3](https://github.com/CHANxuanyu/harness-bridge/pull/3) into `claude/new-repo-plan-dn1eac`.

## W5 workbench experience and interface redesign — 2026-10-08

The workbench was used end to end in its own test instance (synthetic projects, stub CLIs) and
redesigned: Claude Desktop Code-style organisation (project/session sidebar, main terminal, on-demand
resizable Changes/Activity/Details pane) with macOS HIG visual and interaction rules, independent
light and dark appearances, plain-language states with shape + text, one primary action, anchored
confirmations, shortcuts (⌘N, ⌘⇧D/A/I, ⌘\, ⌃⌘S, ⌃Tab, ⌘,, ⌘/). Details and the defect list:
[WORKBENCH.md](docs/WORKBENCH.md) (interface, design principles, "W5 体验改进").

Defects found by using it and fixed: hidden inspector still reserved a 420 px column; pywebview's JS
bridge was blocked by our CSP in the native window (no folder picker, no title/appearance sync) —
replaced by authenticated `/api/native/*` routes, CSP kept strict; dialogs left keyboard focus in the
terminal (keys could leak to the CLI); new/resumed sessions did not get focus; state pushes stole
focus and re-fetched details; activity forced scroll-to-bottom; narrow windows squeezed the terminal
to 50×11; repeated buttons/badges and technical fields; App-written markers in native output; two App
instances could manage one state dir (now a per-state lock).

Native verification is real pixels: a dev-only `--dev-snapshot-dir` mode captures the App's own
pywebview window (title bar included) while a browser drives the same local server. Light/dark main,
changes/diff, handoff dialog, failure/details, first run and 900×640 overlay were captured and
checked; representative synthetic screenshots are in `docs/screenshots/`.

Checks: full offline `scripts/check.sh` **897 passed / 17m11s** (ruff, format, strict mypy 54 files),
including 36 workbench tests (4 new). JS syntax checked with `node --check`. No case removed or skipped.

Not verified: real Claude Code / Codex sessions in the new UI (T3-W/T4-W; this development session
runs inside Claude Code), real IME composition, system clipboard paste, pointer-drag resizing,
VoiceOver. No model call, credential read, release, tag or visibility change.

GitHub: development branch `claude/repobridge-product-direction-8e26f9` pushed (non-force) at
`c02b5f8`; [PR #1](https://github.com/CHANxuanyu/harness-bridge/pull/1) was then **merged into the
default branch** `claude/new-repo-plan-dn1eac` on the user's instruction (2026-10-08, regular merge
commit `e348c85`, parents `f2cd6e6` + `c02b5f8`, tree identical to `c02b5f8`). The local branch
`local/glm-macos-validation` and the user's main checkout `/Users/chan/Downloads/harness-bridge` were
not changed (still `f2cd6e6`, without the workbench). The repository's CI workflow is manual-dispatch
only, so the PR showed no checks.

Next: the user runs W4 real acceptance from WORKBENCH.md; then fix what real TUIs reveal inside
xterm.js (keys, IME, alt-screen, Codex resume) and decide on `.app` packaging/launch from Finder.

## W1–W3 RepoBridge workbench — 2026-10-07

**A desktop window that runs native Claude Code / Codex sessions is implemented**
(`src/harness_bridge/workbench/`, `hbridge app` / `repobridge`). Projects organise sessions;
each session runs one harness's **interactive** CLI in an App-owned PTY rendered by xterm.js;
the CLI keeps conversation, tools, permissions, login and billing. Same-project session management
(list, stop, native resume, restart-before-first-turn, rename/remove, single writer per real
workdir, reconcile after App restart) and manual cross-harness handoff (editable note from observed
facts + user progress, new session in the same project, chain recorded, note kept out of the repo)
are in place. Guide, structure and evidence: [WORKBENCH.md](docs/WORKBENCH.md).

Visibility: Claude Code record-only hooks (prompt, tools, permission requests, stop, session ID
confirmation); Codex per-invocation notify (turn completion + thread ID) and OSC 9 approval
notifications; read-only git changes/diff; exit code/signal/failure reason/output tail; resume
state. Session env drops API/provider variables (names shown); real sessions are refused when the
App itself runs inside an agent session (`CLAUDECODE`) or a cloud agent environment.

Evidence: T1 + T2-W with **stub CLIs** (real PTY/subprocess/git/SQLite/loopback HTTP), UI-offline
in the built-in browser, and the pywebview 6.2.1 window opened (1440×900 on screen, WebKit connected
to the loopback server) with stub CLIs. Real discovery is model-free only: `claude --version`
2.1.291 and ChatGPT.app-bundled `codex --version` 0.162.0-alpha.2. **Real native sessions in the App
(T3-W/T4-W) have not been run:** this development session itself runs inside Claude Code, so it may
not spawn real harness sessions; W4 steps for the user are in WORKBENCH.md.

Checks: full offline `scripts/check.sh` **891 passed / 17m10s** (ruff, format, strict mypy 52 files);
after the final small changes (Codex `--no-daemon`, run-dir cleanup on refusal, UI focus) lint/format/
mypy and the 30 workbench tests were re-run and pass (18s). Wheel build includes static assets,
the `desktop` extra and both entry points. No failing case removed or skipped.

No model call, credential read, push, tag or release. Optional dependency `desktop` = pywebview
(lock updated); xterm.js 6.0.0 / addon-fit 0.11.0 vendored unmodified (MIT, NOTICE updated).

Next: W4 — the user runs the real acceptance in WORKBENCH.md (or authorizes a bounded run outside an
agent session); then fix what it finds, and decide on `.app` packaging. Later: worktree-parallel
sessions, read-only sessions, ZCode, structured conversation view.

## W0 product direction v2.0 — RepoBridge workbench — 2026-10-07

The user redirected the product: **RepoBridge is a project-centred, lightweight local desktop
workbench that runs native Codex and Claude Code CLI sessions in one window.** It is not a further
Advisor/Executor orchestration layer and not a dashboard over the task scheduler.
[PRODUCT_FORM.md](docs/PRODUCT_FORM.md) is rewritten; [PROJECT_PLAN.md](docs/PROJECT_PLAN.md) v2.0
lists, row by row, which v1.5 scope is superseded (§0) and keeps the v1.5 text as Appendix A.
Secretary's product goal is untouched. AGENTS.md now carries workbench rules (interactive native
CLIs only on user action, no token reads, API/provider env stripped, stub harnesses in tests) and
records that commits are authored by the repository owner.

Technical decision (DECISIONS 112–117): Python `workbench` subpackage, stdlib loopback HTTP/SSE
server, optional pywebview window with `--browser` fallback, vendored xterm.js; native interactive
CLIs in an App-owned PTY; record-only Claude hooks and per-invocation Codex notify/OSC 9 side
channels; separate `workbench.sqlite3`. Existing kernel, plugins and P7/P8 evidence are retained;
P8 Astra/Opus/Flash routing is paused, not deleted.

This step is documentation only: no code, model call, credential read, push or release.
Next: W1 — a desktop window that really runs native sessions; then W2 session management and
W3 manual handoff across the two harnesses in one project.

## P8 native findings and Advisor routing source — 2026-10-07

Source58a3771 is already pushed. This continuation adds explicit Z.ai/BigModel **Start Plan**
profiles and the native runtime-preference initialization handshake to the offline ZCode client.
Doctor advertises `protocol_profile_revision: 2`; matching runtime version0.1.0.dev2 alone does
not establish this newer capability. Initialization is bound to the created/resumed session and
turns off memory, search enhancements and automatic user-input resolution; arbitrary/duplicate/
wrong-scope callbacks remain refused. Native live dispatch stays unavailable before reservation.

Read-only ZCode UI inspection and isolated native blank-session probes exposed concrete gaps:
empty MCP settings do not exclude host/plugin servers; false feature fields do not by themselves
prove effective isolation; requested plan mode returned build; the same empty session could not
be resumed after reopening (-32004). Creation/read/usage returned modelRequestCount0 and tokens0,
with process exit0; failed resume was deliberately terminated (exit143). Preserve both results.
No prompt/model-connectivity test, real credential read, account/settings change or model call.
UI returned to the existing workspace. See [native findings](docs/ZCODE_NATIVE_PREFLIGHT.md).

**Source plugin alpha.7** now includes an optional Astra Advisor → Opus5.5 difficult-work / Flash
bounded-work profile, rationale guidance and strict goal/child templates with fixed dependencies
and aggregate budgets. Actual Codex/ZCode installations stay alpha.6; P7 candidate stays113b0a7.
No cache install, package release, new model allowance or state migration happened.

The P8.3 supersession gap is now explicit: unapproved failed Flash work cannot be replaced by a
new Opus child and then omitted from integration. Current goals require every child approved.
Pre-freeze rerouting and a new child after a correctly approved predecessor are supported;
reviewed partial-work transfer/task supersession must be implemented separately. The Skill never
invents that transition, approves failed work or starts a replacement goal to reset its budget.

Checks: plugin baseline26/18.25s; ZCode contracts/integration68/41.75s; copied plugin/templates and
legacy model contracts46/22.11s; capability discovery1/0.51s; native-field refusal regressions2/0.48s.
All pass (117 post-change cases across the separate runs). Lint/format 156 files and strict mypy 42
runtime files pass. Skill Creator validator passes using existing cached PyYAML; no dependency
installation. One initial test-path typo collected0 tests; first validator attempts lacked YAML.
Reuse previous235 core checks/P7 native evidence instead of rerunning them.

Next: implement effective native account/config isolation and understand actual mode/resume
semantics; separately add reviewed task supersession and acceptance. Then prepare the exact
bounded Astra/Opus/Flash live packet before requesting fresh allowance. Do not spend closed P7
budget, auto-install source alpha.7, or loosen a guard to accommodate the native findings.
Private receipts: takeover work/p8-native-contract/; selected public native fields are under
`tests/fixtures/zcode_protocol/native_blank_projection.json`.

## Historical P8 offline protocol slice — 2026-10-07

The selected route remains **Codex Astra Advisor → Claude Code Opus5.5 for difficult work +
ZCode GLM5.3Flash for bounded simple work**. ZCode now has an offline adapter and bidirectional
stdio client, a separate exact-model/account-provider task contract and explicit null-turn
budgeting. Managed goal children/worktrees, background dispatch replay, same-session repair,
independent verification/review, timeout and cancellation work with a simulated protocol peer.
See [ZCODE_EXECUTOR.md](docs/ZCODE_EXECUTOR.md) for the implemented contract and native gaps.

The isolated native ZCode0.16.9 `runtime/capabilities` probe returned successfully and exited
cleanly, without creating a session or sending a prompt. Earlier missing-config and socket-path
failures remain recorded. Session request/event shapes come from static installed schemas;
the successful session/repair/cancel checks are **synthetic**, not native execution evidence.
Model/provider/workspace/permission mismatches, malformed/duplicate/unrelated events, native
permission requests and unknown process exits cannot become approved success. Raw snapshots,
history and native error prose are not forwarded to receipts. No history-deleting session/close.

Validation: pre-edit affected baseline **87 passed / 24.82s**. New ZCode/doctor checks **62 passed /
33.72s**; affected models/Claude/Codex/goal planning/coordination/workers/concurrency **235 passed /
117.44s**. Global lint/format (154 Python files) and strict mypy (42 runtime files) pass. This is
scoped regression, not a repeat of the P7 full suite or paid/GUI acceptance. Initial checks found
and fixed empty resume-ID admission; incorrect test setup/approval-state/cleanup assumptions
were corrected against existing contracts. No failing cases removed or skipped.

**Native ZCode dispatch stays unavailable before attempt reservation**, including background
and explicit opt-in. Account entitlement/subscription provenance, effective permissions/hooks/MCP,
native model/turn correlation/resume/stop and original desktop history still need qualification.
Doctor reports this as offline-only. No current Advisor model change, new model call, authentication
or billing setting change, host plugin update, state migration or release rebuild. P7 native
allowance remains closed at8 executions/1 repair/975 reserved seconds; candidate stays113b0a7.

Next: finish P8.1 account/permission and session-protocol qualification, then P8.3 Advisor routing
and explicit escalation templates. Prepare the exact bounded P8.4 packet before any new model
allowance is requested. Do not enable live merely because offline tests pass. The current source
slice is ready for the already-authorized non-force push; release/tag/package publication remains
outside scope. Private probes: takeover `work/p8-protocol-probe/`; public sanitized receipt:
[ZCODE_PROTOCOL_PROBE.json](docs/ZCODE_PROTOCOL_PROBE.json).

## Historical P8.0 route discovery — 2026-10-07

The user selected **Codex Astra Advisor → Claude Code Opus5.5 for difficult work + ZCode
GLM5.3Flash for simple bounded work**. See [ROUTING_PROFILE.md](docs/ROUTING_PROFILE.md) for
routing, explicit escalation and the P8 sequence. Existing ZCode Advisor/Codex Executor routes
remain; they do not substitute for the missing Flash Executor. ZCode Executor is **not implemented**.

P8.0 documents the exact route and examines installed ZCode0.16.9 help/bundle without inference:
--cwd/--resume/--surface/--mode/app-server exist; model-selection and session protocol symbols
and GLM-5.3-Flash canonical name are present. Account entitlement, effective model selection,
permissions, event semantics, cancel/resume and desktop continuity remain unverified for this
Executor. The headless prompt default is yolo, so the adapter must choose and verify explicit
permissions. No prompt, native session, protocol server, auth/config change or model call.
Private evidence: takeover chat work/p8-routing-discovery/result.json and zcode-help.txt.

P7 remains accepted within its recorded scope. Its source113b0a7 was non-force pushed to the
existing public branch under the user's subsequent authorization, and a fresh offline demo
completed with3 simulated attempts/1 repair. An initial restricted demo could not run ps;
its uncertainty is retained separately, not rewritten as successful exit. See takeover outputs
P7-push-receipt.json and P7-demo-evidence.json. Local release candidate remains pinned to113b0a7;
this planning change does not rebuild/release it. All prior native allowances remain closed.

Next: P8.1 qualify native metadata and protocol contracts, then implement and exercise the
ZCode adapter offline. Prepare a concrete bounded acceptance packet before seeking any new
model allowance. Do not repeat P7 acceptance, change the current Advisor model implicitly,
or call the exact three-model route complete because the plan now names it.

_Accepted baseline: P7 passed for the documented local scope, including desktop history persistence and Codex GUI lifecycle; P8 primary-route work is recorded above._

## Final local closure after app update — 2026-10-07

Original-repository write access and its separately protected Git directory were restored
through scoped permission grants. The retained P7 acceptance commit was fast-forwarded into
the original branch; no replacement checkout, force update or remote publication.

The GUI restart also updated the app from 26.930.31730 to 26.930.51102 (build 13100); embedded
CLI remains 0.160.0. The restricted command returned LaunchServices -10827 although the
executable existed. The exact same original-thread URL command succeeded (exit 0) in the
explicitly approved system execution context. Preserve the restricted failures separately;
no native task/open receipt was reset, and no model turn or replacement chat was created.
Only these two observed app versions are accepted; identity, scheme, embedded CLI and original
binding guards remain. Fresh runtime status has no blockers for either original Executor.

The applied code/test diff exactly matches the prior 8-pass / 2.10s compatibility patch;
its 6-pass / 2.17s baseline is retained. No repeated paid, GUI-lifecycle or full-suite tests.
Final lint/format (147 files) and strict mypy (40 runtime files) pass. Prior full 732 and affected
73/26/6 checks retain their original labels and dates.

Advisor plugin **alpha.6** documents both supported app versions and still requires runtime
**0.1.0.dev2**. Actual native upgrades in Codex/ZCode preserve enabled state, the connection,
all 34/15 unrelated plugins, and match all 16 package files per host. Both 36-command checkers
pass without opening selected state; fresh Codex skills/list loads enabled alpha.6 for repo/chat.
No plugin model or native Executor was invoked. The original 8-execution allowance stays closed.

Private receipts: takeover chat `work/p7-finalization/app-update-compatible-confirmed.json`,
`tested-patch-identity.json`, `current-runtime-status.json`, and `work/p7-plugin-alpha6/`.
No remaining planned P7 acceptance or repository-write blocker. Preserve the earlier failures,
original real worktrees/histories, and the completed fake lifecycle records. See the current
[P7 closeout matrix](docs/P7_CLOSEOUT.md) for scope; OS/backend restart and running-session control
remain outside the tested contract. The new candidate is distinguished by its source revision.

## P7 final acceptance — 2026-10-07

**P7 V01–V15 are accepted within the explicit evidence boundaries in
[P7_CLOSEOUT.md](docs/P7_CLOSEOUT.md).** Runtime 0.1.0.dev2 / Advisor plugin alpha.6;
Apache-2.0, local candidate only. No remote release/push or new model allowance.

The human quit/reopened the Codex GUI. A detached, bounded observer recorded the main GUI
absent at 13:02:39.231 UTC and a replacement process at 13:02:40.372 UTC. The same fake worker,
goal, job and attempt remained RUNNING across that gap. Fresh-connection dispatch replay
returned the same job; exactly one attempt existed. The observer cancelled the fake task,
confirmed its exit and unchanged source. This Advisor reconnected after restart and found
zero occupied slots; the isolated test goal was then closed as CANCELLED. No model ran.
The human additionally confirmed “仍在列表，原历史也能打开” for the original Codex Executor.
Post-restart Skill availability now includes installed alpha.5 in this Advisor's supplied catalog.

Private evidence: takeover chat `work/p7-codex-gui-lifecycle/` (`result.json`,
`advisor-reconnected.json`, `fixture-closed.json`, `desktop-persistence-human.json`).
Do not rerun the helper or native packet. Preserve real histories/worktrees. The final native
ledger stays 8 executions (4 per harness), 1 repair, 975 reserved wall seconds; all gates closed.
This proves the tested GUI lifecycle; backend termination, sleep, logout and OS reboot remain
outside the claim. Finished-session desktop handoff does not implement running-session control.
See [GUI evidence](docs/P7_GUI_LIFECYCLE.md). No runtime change or repeated full suite was needed.

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
Fresh native Codex skills/list resolves enabled alpha.5 for both repo and chat cwd; no thread or turn is created.
No new Executor attempt/model message, provider/billing change or remote publication.
Private receipts: takeover chat `work/p7-desktop-unlocked/result.json` and `work/p7-plugin-alpha5/`.

**Completed:** the subsequent human-driven Codex GUI quit/relaunch retained exactly one fake
attempt, followed by confirmed cancellation and fresh Advisor reconnection. The human confirmed
the original Executor remained in the list with its original history. See [P7_GUI_LIFECYCLE.md](docs/P7_GUI_LIFECYCLE.md).
All real task histories/worktrees remain intact and native model allowances stay spent.

## Previous continuation (historical; superseded above)

- **P7 closeout matrix:** `docs/P7_CLOSEOUT.md` maps V01–V15 to existing evidence. V08 is partial (Codex full GUI lifecycle), V15 is not accepted (desktop lists); all other items retain their stated offline/native scope. Claude awaits manual unlock; Codex still needs a supported existing-session list route, not merely an unlocked screen. The README's outdated alpha.3/cancellation/turn-stop status and the plan's unresolved-license row are corrected.
- **Complete local build:** the repository builder now emits committed source, full docs, wheel, plugin, standalone verifier and transport ZIP. It refuses dirty source/collisions/concurrent edits and checks artifact/source consistency; session-local packaging helpers are no longer required. New synthetic distribution suite **12 passed / 2.81s**; lint/format 144 files and strict mypy 40 runtime files pass. Pre-edit compatibility baseline: 26 passed / 17.47s. Runtime, installed plugin, state and native allowance did not change; prior core/full evidence is reused.

- **Advisor desktop follow-up installed:** plugin alpha.4 is enabled in actual Codex and ZCode profiles. It carries the user's requested desktop visibility through delivery, queries exact child bindings, handles the supported handoff and reports pending/unsupported results separately. Both cached packages match all 16 source files, both connection checks pass 36 command surfaces without opening selected state; 34 other Codex plugins / 15 other ZCode plugins and the shared connection are unchanged. Native Codex skills/list loads alpha.4 for repo and chat cwd; current GUI refresh remains unobserved.
- **Codex diagnostic:** a read-only worktree-scoped native probe confirms source `exec`; default/interactive lists omit the session, while explicit exec filtering returns its exact UUID. No new session/turn, resume, import or metadata mutation was used. This demonstrates native filtering, not a completed desktop synchronization route.
- **This slice's checks:** plugin suite 26 passed / 17.22s, including two new incompatible-runtime refusals; Skill Creator validator passes; lint/format 142 files and mypy 40 runtime files pass. Runtime/source execution logic is unchanged, so prior full/desktop evidence is reused.
- **P7 bounded native packet completed.** The approved final two executions passed: fixed Codex cancellation stopped all observed descendants (independent fixture survivor check empty); Claude stopped with native `error_max_turns`. Real dual-harness collaboration, same-session repair, integrated review and exact local delivery remain passed. Preserve the earlier failed cancellation and permission stop as historical evidence.
- **Final allowance accounting:** 8 actual executions (Claude 4 / Codex 4), 1 repair, 975 reserved wall seconds; observed native duration 145.629s, not billed usage. One older Codex reservation is a proven non-start. All validation gates are closed; no additional real execution is authorized or needed for this packet.
- **New desktop requirement remains open.** `desktop status` locates the original native session without invoking a harness. `desktop open` adds a once-only Claude CLI-to-desktop handoff for terminal tasks / delivered goals, with current Advisor guards, exact binding and version checks. No prompt or new attempt. Native acknowledgement is not desktop visibility. Codex is explicitly `native_history_only`: title/section/pin metadata probes did not make the Executor appear in the app list; the temporary section was removed.
- **UI verification deferred by the user:** the user is away from home and will unlock the Mac after returning; continue CLI/code only meanwhile. No Claude desktop handoff has been run. Full Codex GUI shutdown remains unverified. ZCode quit/relaunch with a fake worker, native plugin lifecycle and independent runtime retention evidence remain valid.
- **Validation:** reuse the pre-change full **732 passed / 922.88s**. New desktop/CLI/coordination run **55 passed / 37.69s**, including 26 new desktop cases; lint/format 141 files and strict mypy 40 runtime files pass. Final native-session selection hardening: 26 desktop cases passed / 6.98s. This is affected coverage, not a new full-suite run.
- **Distribution:** runtime 0.1.0.dev1 / installed plugin alpha.4 / schema 10. Apache-2.0, local candidate only. No push, tag, publication, provider/billing change, shared-state migration, new model turn for desktop visibility. See `docs/P7_RESULT.md` and `docs/DESKTOP_SESSIONS.md`.

## Historical milestones (state as recorded at each milestone)


- **P7 preparation complete, live acceptance NOT_RUN:** a fresh-directory packet generator and
  executable rehearsal now cover two concurrent Claude/Codex-shaped stand-ins, disjoint worktrees,
  dispatch replay, Advisor takeover while running, stale-writer refusal, exact Claude-session repair,
  combined external acceptance and exact local-branch delivery. Exactly 3 attempts / 1 repair reserve
  30 turns / 1800 seconds; all exits confirmed, source and packet/check hashes unchanged. Standalone
  CLI rehearsal also passes. `docs/P7_ACCEPTANCE.md` distinguishes synthetic evidence, future bounded
  authorization and remaining native/distribution cases. Current Codex schema/docs audit does not
  close any live gap; live refusal remains unchanged. New checks: **8 passed**, 13.91s; pre-change
  affected baseline **44 passed**, 38.80s; lint/format (131 files) and mypy (37 runtime files) clean.
  No core/package change, new model call, shared-state migration, profile change or push.

- **P6 model-free entrypoint acceptance:** actual Codex profile now has alpha.2 installed/enabled;
  its native skills loader resolves the enabled Skill for both repository and current chat cwd.
  Existing 34 plugins are unchanged. Actual Codex/ZCode caches each match all 13 source files and
  resolve the same new default connection. The dedicated empty shared store has live mode closed;
  no old task database was opened/migrated. An actual Codex tool PTY exit left one fake job running;
  reconnection/cancel confirmed its exit, one attempt only, source unchanged.
  See `docs/P6_DESKTOP_ACCEPTANCE.md`. P6 installation/connection acceptance passes; current GUI
  hot refresh is unobserved, full app termination and real cross-harness behavior remain P7.
  No new model call, runtime change, broad test repeat or push.

- **Prior P6 Advisor entrypoint slice:** plugin alpha.2 now covers shared connection discovery,
  goals/children/Advisor takeover, background observation, repair, integration and local delivery.
  A bundled model-free checker validates 34 command surfaces in temporary state without opening
  the selected store. Cached examples exercise failure/takeover/repair/delivery through fresh CLI
  processes: **24 new checks passed**, 19.96s; lint/format (125 files) and mypy (37 source files) clean.
  Codex CLI installed/enabled alpha.2 in an isolated profile; 13 cached files match source and its
  connection check passed. After explicit UI installation authorization, ZCode installed alpha.2
  and reports its Skill enabled; its 13 cached files and the same connection check also pass.
  Actual Codex desktop Skill discovery and host behavior/lifecycle acceptance remain pending.
  P6 was partial at that slice; the continuation above closes model-free wiring acceptance.
  See `docs/P6_ENTRYPOINT_RESULT.md`. No model call, user-state migration or push in that slice.

- **P5 Codex offline adapter:** native options, strict JSONL completion/refusal handling and
  exact UUID repair resume now reuse shared worktrees/workers/checks/reviews/budgets. Live dispatch
  is unavailable before reservation, including with ordinary live opt-ins enabled; internal turn
  enforcement, subscription/config provenance and native resume need evidence. No new model calls.
  See `docs/CODEX_EXECUTOR.md`. Adds 68 offline cases (48 contracts, 20 integration).
  Shared full regression: **642 passed**, 839.69s; following Codex-only resume/parser hardening:
  **68 passed**, 20.87s. Lint/format and strict mypy (37 source files) clean. The final hardening
  was checked with its affected suite, not another full run. Schema stays 10; legacy normalized
  executor shapes are preserved.

- **Final P4 completion checks:** full `scripts/check.sh` → **574 passed / 0 failed / 0 skipped**,
  769.51s (12m49s); ruff/format clean (116 files), strict mypy clean (36 source files).
  Adds 55 cases relative to 519: 18 repair integration, 24 cleanup integration, 12 strict contracts
  and one migration revision. Source/tests were unchanged throughout the final shared-core run;
  no further broad rerun was needed. Evidence is offline T0/T1/T2, not real multi-harness acceptance.
  No new model/auth/network call, actual user-state migration or remote publication.

- **P4 local core completion:** budgeted integration-repair children bind the last clean partial
  or failed candidate, original/pending inputs and acceptance evidence. New integrations explicitly
  select the approved resolution, retain all required inputs and preserve the original total checks;
  each candidate needs fresh exact verification/review before delivery. Initial and later repair-child
  executions consume shared goal attempt/repair/time/turn ceilings. See `docs/INTEGRATION_REPAIRS.md`.
- **Explicit retention/cleanup:** `goal cleanup` previews owned resources and frozen fingerprints;
  apply requires the current Advisor, matching completed delivery and idle known-exit project.
  Only clean, raw-byte/mode-matching owned worktrees are non-force removed. User changes, ignored
  extras, unfinished Git operations, unknown removals, all refs/branches/evidence and caches remain.
  Durable per-resource outcomes make replay preserve recreated directories. See `docs/CLEANUP.md`.
- **Revision 10:** additive cleanup receipts with atomic backed-up v1–v9 migrations, preserving
  prior plan/integration/approval/delivery digests. Only isolated test databases were upgraded.
  P4 completion means the local offline core; real cross-harness and installed-host acceptance remain P5–P7.

- **Planning milestone P0 complete:** `docs/PROJECT_PLAN.md` is the canonical product and
  engineering plan. Advisor is the user's existing agent session; Executor is a bound child
  agent session. P1/P2/P3 local cores are implemented and offline-validated.
  P5 offline adapter and P6 model-free wiring are implemented; Codex live readiness and P7 remain incomplete. Scope defaults,
  dependency materialization, budget/ownership checks, worker lifecycle, integration and
  local-branch delivery are specified with V01–V14 acceptance criteria.
- **P1 first vertical slice implemented:** project/goal registration, independent child links,
  Advisor binding/epoch takeover, shared guards on old task mutation paths, goal attempt/repair
  ceilings and one execution slot across a project's goals. Revision 1→2 migration backs up
  committed WAL data and rolls back failed upgrades. See `docs/COORDINATION.md`.
- **P1 completion slice:** goal pause/resume/cancel/fail controls, confirmed-stop projections,
  immutable child plans and DAG validation, explicit idempotent root materialization. Accepted
  workspace preparation racing with cancel retains ownership without reviving the task.
  Schema revision 3 upgrades v1/v2 atomically with a pre-upgrade backup. See `docs/PLANNING.md`.
- **P2 first slice:** approval retains immutable Git snapshots; dependencies compose into
  pinned baselines before successor task/worktree creation. Conflicts block materialization;
  old approvals require explicit unchanged-candidate retention. Child packets carry goal/base/
  dependency attribution. Read-only presence/ownership checks run before child dispatch and
  consume no attempt on failure. See `docs/EXECUTION_CONTEXT.md`. Revision 4 adds retained records.
- **P2 preparation completion:** explicit bounded setup/check commands, PREPARING lifecycle,
  redacted logs, candidate-bound readiness, cancellation/crash recovery, declared output/cache
  inventory and state-wide resource claims. Existing child `run` cannot bypass preparation;
  same-key replay never re-executes, unknown exits retain slots/resources. No persistent service
  hosting or cross-state coordination is claimed. Schema revision 5 upgrades v1–v4 atomically
  with backup, preserving old plan digests. See `docs/PREPARATION.md`.
  P4 repair/cleanup is completed below; P6 installed entrypoints remain future work.
- **P3 first worker slice:** `run --background --idempotency-key` atomically reserves an
  attempt/worker handle before a detached process claims it once. It reuses the foreground
  executor/verification path; current Advisor, preparation, project-slot and aggregate-attempt
  checks still apply. `job`, task `status` worker handles and incremental `events --after/--wait`
  support reconnection without redispatch. Cancel and recovery distinguish fenced unclaimed
  work from unknown exits after claim. Proven non-started repairs retain feedback/session
  continuity. Schema revision 6 upgrades v1–v5 with backup/rollback. See `docs/WORKERS.md`.
  This first slice is extended by the parallel-admission milestone below. Goal-wide streams and
  actual desktop-host lifecycle acceptance remain pending. Preparation stays explicit foreground
  work. No new real calls or user-state migrations.
- **P3 local concurrency/ceiling core:** explicit state configuration permits up to two active
  executors per goal-linked project; all goals share the cap, and disjoint declared write roots
  are required. Preparation is project-exclusive. Reverify/resumed verification use the same
  slot guards. Optional frozen goal wall-time/turn ceilings reserve each attempt's full limits,
  retain executed/unknown attempts and exclude only confirmed non-starts. Status and dispatch
  events expose the accounting and cap; old GoalSpec digests/replays remain valid. No schema
  migration: revision 6's immutable task/attempt history is the ledger. `docs/CONCURRENCY.md`
  specifies conservative scope proof, historical unknown holds and evidence limitations.
- **P4 first slice:** freeze all required approved inputs in explicit dependency-respecting order,
  with immutable total-goal verification commands. Materialization composes retained Git trees into
  a separate owned worktree or records a conflict and last clean partial commit. Same-key replay,
  current-Advisor guards, crash retry and changed-workspace preservation are implemented. Revision 7
  adds integration records with backed-up v1–v6 upgrades. The next slice below implements total-goal
  checks/approval; `CANDIDATE` is not delivered. See `docs/INTEGRATION.md`. No real user state was migrated.
- **P4 integrated verification/review:** explicit `integration verify/cancel/recover/review`,
  durable run/checkpoint/log/manifest evidence, exact candidate/run/Advisor-bound review and
  persisted rejected approvals. Same-key requests never execute again; a new explicit key may
  recheck only an idle project with known exits. Goal-linked checks are project-exclusive even
  with cap two; unknown exits retain the hold and keep goal termination pending. Checks consume
  no Executor budget; maximum ten local runs per integration. Status exposes `verification_run`,
  review/template and dynamic `approval_current`. See `docs/INTEGRATION_CHECKS.md`.
- **Revision 8:** additive integration verification/review records, backed-up atomic v1–v7
  upgrades preserving prior candidates. Isolated test state only; no actual user/live migration.
  Checks use isolated environment and bounded logs, but remain trusted scripts, not OS sandboxed.
  Changed candidates/evidence, unknown exits and stale Advisor epochs cannot yield current
  approval. `APPROVED` alone is not goal delivery; explicit exact branch delivery is implemented
  below. Conflict-repair binding and retention/cleanup were completed in the subsequent slice below.
- **P4 exact local delivery:** `goal deliver` freezes an intent and creates a new named local
  branch at the exact approved commit/tree, paired atomically with a private publication proof.
  READY_TO_DELIVER requires the latest frozen integration's current exact approval and an idle
  project; DELIVERED requires a confirmed receipt/ref pair. Existing/unowned/symbolic/selected
  branches and case aliases are refused. Source checkout/index/user edits remain untouched;
  advanced source/base differences are reported, never silently rebased. No push/PR/model call.
- **Delivery lifecycle:** same-key recovery can finalize the proven prior publication; completed
  replay never recreates/reset changed refs. Pending/completed delivery fences new goal mutations.
  Current Advisor may abort an unproved pending intent without deleting any refs; completed goals
  need new goals for new work. Reads/takeover remain available. Receipt/ref/evidence changes need
  attention rather than reopening the goal. See `docs/DELIVERY.md`.
- **Revision 9:** additive delivery records and goal/branch reservations, backed-up atomic v1–v8
  migrations retaining old approved integration digests. All workspaces and evidence remain;
  conflict-repair child binding and cleanup were still pending at that milestone. No real user/live state migrated.
- **Prior delivery checks:** full `scripts/check.sh` ran all 519 cases: **518 passed, 1 failed**
  (509.18s). The sole failure expected the retired `delivery: not_implemented` string. Updated
  that assertion to require structured `not_ready` plus ACTIVE (child approvals still cannot
  imply delivery); its exact-test `scripts/check.sh` then **passed**, 5.92s. Runtime code was
  unchanged. All **519 current cases passed across these runs**, not a claimed single green
  519-case suite. Ruff/format clean (109 files), strict mypy clean (34 source files).
  Adds 45 cases: 31 integration, 13 contract, one migration revision. No new real model/auth/network
  call or user-state migration. Details and earlier corrections: `docs/VALIDATION_MATRIX.md`.

- **Prior P4 verification/review checks:** final `scripts/check.sh` → **474 passed / 0 failed /
  0 skipped**, 374.63s; ruff/format clean (105 files), strict mypy clean (33 source files).
  Adds 36 cases: 25 integration, 10 strict contracts and one migration revision. Real local
  checker/fake processes use isolated HOME/auth sentinels. Targeted runs and fixture corrections
  are in `docs/VALIDATION_MATRIX.md`. No new real harness/model/auth call or user-state migration;
  no push or repository visibility change.

- **Prior P4 candidate checks:** final `scripts/check.sh` → **438 passed / 0 failed / 0 skipped**,
  277.87s; ruff/format clean (101 files), strict mypy clean (32 source files). Adds 43 cases:
  42 integration/contract checks and one migration revision. A sandbox-limited run was stopped
  after process-visibility failures, then the unchanged process checks passed in the final local
  run. Fixtures retain isolated HOME/auth sentinels; no real model or user-state migration.
  Detailed runs and corrected test-fixture expectations are in `docs/VALIDATION_MATRIX.md`.

- **Prior P3 checks:** final `scripts/check.sh` → **395 passed / 0 failed / 0 skipped**, 226.17s;
  ruff/format clean (98 files), strict mypy clean (31 source files). Adds 54 offline cases:
  29 scope/config/limit unit cases and 25 parallel/budget/lifecycle integration cases. Includes
  simulated host process-session teardown, not actual desktop-app lifecycle acceptance.
  No real model/auth/network calls or user-state migrations. See `docs/VALIDATION_MATRIX.md`.
- **Prior worker checks:** final `scripts/check.sh` → **341 passed / 0 failed / 0 skipped**, 199.87s;
  ruff/format clean (94 files), strict mypy clean (30 source files). This milestone adds 33
  cases (32 worker/observation cases plus one migration revision), all offline. Detailed prior
  runs and the corrected fault-injection fixture are recorded in `docs/VALIDATION_MATRIX.md`.
- **Experimental prototype (V0.1, milestones M0–M4).** The live path has now been exercised
  for real in bounded initial smokes and one controlled repair/resume task on 2026-10-06.
- **Verified so far**
  - T0–T2 offline suite (184 tests) and both demos: green on Linux (cloud) and macOS (local).
  - T3 live single-harness initial smoke: **PASS** — exactly 2 real invocations (one
    `--max-turns` flag-acceptance probe, one bridge-run slugify task), bridge verification
    passed including the external acceptance check, snapshot-bound approve → SUCCEEDED
    (`docs/LOCAL_SMOKE_HANDOFF.md`).
  - T4 single-run smoke: **PASS** — the local Codex session (supervisor model `gpt-6-astra`,
    evidenced by local turn-context metadata) performed create → run → artifacts → diff
    review → snapshot-bound approve → SUCCEEDED through the bridge, one initial attempt,
    zero repairs (`docs/T4_SMOKE_RESULT.md`).
  - Controlled live repair/resume: **PASS** — two real attempts (diagnosis-only initial
    against a seeded bug, then one repair), failed verification → changes_requested →
    matching `--resume` → passed verification → approve → SUCCEEDED. Session id and an
    unrepeated conversation mnemonic preserved; 10 repo tests + 9 external cases passed
    (`docs/LIVE_REPAIR_RESULT.md`).
  - Redacted stream logs from all three tasks are now offline parser regression samples
    (`tests/fixtures/claude_stream_live/`, provenance recorded; no model was invoked to
    build them).
- **Not verified (do not assume)**
  - real interruption recovery, live timeout/turn-limit enforcement,
    multi-task or long-task stability;
  - T5 comparative evaluation — in particular **whether delegating through the bridge is
    cheaper or better than using Opus directly is NOT established** by these smokes;
  - subscription quota remaining: **unknown** (usage figures are executor-reported; CLI cost
    numbers are API-equivalent estimates, not bills or subscription usage).
- **Standing constraints:** development model `claude-opus-5-5`; default runtime mode `mock`;
  the live gate (`--mode live --allow-model-usage` + local config opt-in + clean environment)
  unchanged; repository **public** by the user's explicit choice — do not change visibility,
  no license added yet.
- **Product direction:** developers with multiple coding-agent subscriptions; independent
  local runtime, shared task evidence, host-specific plugin entrypoints. The user confirmed
  this audience (ZCode/GLM + Claude Code + Codex). Final use and delivery boundaries are in
  `docs/PRODUCT_FORM.md`; the runtime still has only a Claude Code live executor.
- **User clarification:** the primary relationship is one Advisor (main agent) directing one
  or more Executors (cross-harness subagents). The Advisor inspects/plans/reviews/integrates;
  Bridge prepares workspaces and runs/records tasks. `supervisor` is the existing name for
  Advisor. Parent goals, child ownership, takeover fencing and initial aggregate
  attempt/repair limits, fixed child dependencies and controlled finite preparation are implemented.
  Background/concurrent workers and exact local delivery now exist in the local core; conflict repair/cleanup and installed
  host experience remain pending. This is not the full product behavior.

## Implemented

| Area | State |
|---|---|
| TaskSpec / ReviewDecision contracts, versioned, strict | done, tested |
| SQLite store, CAS transitions + same-transaction events, idempotent create/review | done, tested |
| Bridge-owned worktree from pinned base SHA; dirty source refused; user checkout untouched | done, tested |
| Runner: own process group, concurrent drain, bounded capture, timeout, cancel, signals, confirmed-exit | done, tested (Linux, macOS) |
| Fake executor (11 scenarios) + adapter | done, tested |
| Independent verifier, snapshot fingerprint, manifest, scope/secret checks, redaction, approval gate | done, tested |
| Repair loop with attempt/repair budgets | done; offline tests + one controlled live repair/resume PASS |
| recover / cancel / verify; crash windows fail closed; no auto re-dispatch | done, tested (real crash injection + signals; Linux, macOS) |
| Claude Code adapter: command builder, stream parser, classification, resume binding, live gate + per-flag evidence preflight, run-time argument-rejection stop | done, offline contract + live smoke evidence (T3/T4) |
| Captured-live-redacted stream fixtures + parser regression tests (from the T3/T4 logs) | done |
| CLI: doctor, create, run, status, list, artifacts, verify, review, recover, cancel, demo | done |
| Goal/project registration, child ownership, Advisor takeover and old-entrypoint fencing | implemented first P1 slice; offline checks pass |
| Goal attempt/repair/time/turn ceiling reservations; default 1 / explicit 2 project slots; scope checks | implemented, atomic; unknown exits retain all reservations |
| Goal controls and confirmed-stop terminal projections | implemented; offline active fake-process cancellation and unknown-exit checks pass |
| Immutable child plans / DAG validation / explicit root and dependent materialization | implemented; fixed approved inputs and conflict refusal |
| Retained approval snapshots / goal-child context / presence preflight | implemented, offline-validated |
| Explicit finite preparation / output-cache inventory / resource claims / cancel-recover | implemented; unknown exits stay reserved; no persistent services or cross-state locks |
| SQLite revision 1/2/3/4/5/6/7/8→9 upgrade + WAL-consistent backup/rollback | implemented; isolated fixtures only, real user state not migrated |
| Durable background dispatch / task event cursors and bounded wait | implemented first P3 slice; offline worker lifecycle checks |
| Frozen integration inputs / owned candidate / conflict and crash retry | implemented P4 candidate slice; exact verification/review and local delivery now available |
| Durable total-goal verification / cancellation / crash recovery / exact Advisor review | implemented, offline-tested; no automatic repair/delivery |
| Exact local branch delivery / durable intent / atomic proof / current goal readiness | implemented; no automatic checkout, push, merge or cleanup |
| Offline demos `success`, `bug-then-repair` | pass |
| Manual offline CI workflow (`workflow_dispatch`) | written, never run |
| Codex / ZCode plugin package, shared Advisor Skill, host catalogs | alpha.2; 24 prior package/CLI checks pass; actual Codex install/native Skill loader and ZCode install/Skill UI pass; shared default connection and native tool PTY reconnection pass; GUI hot refresh/full app termination/real behavior unverified |

## Tests actually executed (chronological, by environment)

- **Linux cloud container** (Python 3.11.17, git 2.43.0, SQLite 3.45.1), 2026-10-06:
  `scripts/check.sh` → 184 passed at `aeea786`; earlier 169 at `1cc850b`; both demos pass.
- **macOS local** (26.6.2 arm64, CPython 3.11.16 via uv, git 2.50.1, SQLite 3.53.1/3.51.0),
  2026-10-06, `fcbd21a`: `scripts/check.sh` → **184 passed / 0 skipped / 0 failed**; targeted
  `test_runner.py` + `test_recovery.py -v` → 28 passed; doctor and both demos pass.
- **Live smokes, same day:** T3 (2 real calls) and T4 (1 real executor attempt) as recorded
  in `docs/LOCAL_SMOKE_HANDOFF.md` and `docs/T4_SMOKE_RESULT.md`.
- **Offline consolidation at `470f5b0`:** 8 new parser regression tests; full check was
  reported clean (192 tests), corroborated at takeover by 192 cached nodeids and no cached failures.
- **Controlled repair/resume, this round at `470f5b0`:** exactly 2 real executor attempts,
  one repair; final independent verification and approval passed. No new smoke/probe/demo.
- **Affected offline checks after this round’s additions:** `scripts/check.sh
  tests/contracts/test_claude_adapter_live.py
  tests/integration/test_cli.py::test_doctor_offline_is_non_inference
  tests/integration/test_claude_stub_flow.py::test_doctor_reports_flag_evidence_not_unsupported`
  → 12 passed; ruff, format and mypy clean. Two new regression cases are included.
  The earlier 192-test full suite was not repeated; no claim of a new 194-test full-suite run.
- **Historical plugin alpha.1 checks (no model; superseded by P6 above):** skill-creator validator passed; copied package has
  internally resolving references and matching manifests/catalogs; bundled task validates
  against the runtime model; 16 documented command forms parse without dispatch. Codex
  0.160.0 recognized the temporarily registered catalog and version; source removed after
  inspection, no plugin installed. See `docs/PLUGIN_ALPHA_RESULT.md`.

- **P1 first runtime slice (macOS, 2026-10-06):** before changes, affected store/CLI baseline
  → 14 passed. New coordination/migration checks → 29 passed. Final `scripts/check.sh` →
  **223 passed / 0 skipped / 0 failed**, 74.68 seconds; ruff/format clean (78 files), strict
  mypy clean (24 source files). Full regression is justified by changes to shared store and
  mutation paths; it includes existing CLI demos, not new live smokes. No model/network/auth
  calls; test isolation/sentinel guards remain in force. No real user state directory migrated.

- **P1 completion slice (macOS, 2026-10-06):** affected baseline 29 passed before edits;
  plan/control/migration/coordination checks 55 passed; final `scripts/check.sh` → **249 passed /
  0 skipped / 0 failed**, 85.27 seconds. Ruff/format clean (81 files), strict mypy clean
  (25 source files). 26 new cases: 23 planning/control and 3 migration. Includes real fake
  subprocess cancellation; no live harness, network/auth calls or user-state migration.

- **P2 first slice (macOS, 2026-10-06):** affected planning/migration baseline 31 passed;
  final dependency/readiness/planning/migration checks 60 passed (62.25s). Final
  `scripts/check.sh` → **278 passed / 0 skipped / 0 failed**, 157.26 seconds;
  ruff/format clean (87 files), strict mypy clean (27 source files). Adds 29 cases:
  15 dependency/retention/context, 13 readiness, one migration revision case. Includes
  real local Git/worktrees/SQLite and fake/stub subprocesses, no real model, auth/network
  calls or user-state migration. Full regression was required by shared approval/store/run
  changes; previous live smokes/repair were not repeated. P2 remains incomplete.

- **P2 preparation completion (macOS, 2026-10-06):** affected pre-edit baseline 22 passed;
  preparation/readiness/planning/migration checks 72 passed (50.58s). Final shared-core
  `scripts/check.sh` → **307 passed**, 163.10s, ruff/format/mypy clean (28 source files).
  After that run, one additional preparation→repair/session-binding regression was added and
  passed via `scripts/check.sh <exact test>` (4.95s, lint/format/types clean). Total current
  coverage is **308 cases, all executed successfully across those runs**, not a claimed
  308-case single suite run. Adds 30 cases: 29 preparation and one migration revision case.
  The added session check uses the Claude adapter's offline stub because the fake executor
  deliberately creates new synthetic sessions. No real model, auth/network calls or user state
  migration. P2 local core is complete within the finite-command scope in `PREPARATION.md`.

## Findings worth knowing

- `--max-turns`: official docs declare it; `--help` of CLI 2.1.291 does not list it; on this
  installation the CLI **accepted** the flag in a real minimal call (2026-10-06). That is
  parse-level evidence, **not** proof that the turn limit is enforced in every scenario. The
  live preflight consumed per-flag confirmation from the isolated test state dir only; a
  run-time CLI rejection still stops the attempt, never a retry without the flag.
- The two Bash permission denials in each initial smoke show the scoped tool allowance
  intercepting out-of-scope commands. Permission rules are one layer — **not** OS-level
  sandbox isolation, and not executor failures.
- Process-group tests need the explicit "steady state" handshake (see HANDOFF known issues).
- Git filters configured in the shared `.git/config` can run during snapshots (SECURITY.md).

## History (cloud delivery, 2026-10-06 — superseded)

- The bridge was developed in a Claude Code Cloud session through `aeea786` (code) plus a
  docs-only head `fcbd21a`; the offline suite and demos were verified there and from a clone
  of an exported bundle. The user authorized making the repository private, but the cloud
  session's GitHub tooling had no visibility operation, so the branch was delivered as a
  self-contained git bundle and not pushed.
- **Superseded the same day:** the user chose to keep the repository **public**; branches are
  pushed (`claude/new-repo-plan-dn1eac` == `fcbd21a`; `local/glm-macos-validation` carries all
  later work). Clone via `gh repo clone CHANxuanyu/harness-bridge`. Do not change visibility.

## Next

Continue P4 in `docs/PROJECT_PLAN.md`: budgeted conflict-repair binding and safe retention/cleanup.
Frozen candidates, total checks/exact Advisor review and idempotent exact local delivery are
implemented in `docs/INTEGRATION.md`, `docs/INTEGRATION_CHECKS.md` and `docs/DELIVERY.md`; reuse them.
P3 local worker/concurrency/ceiling checks are implemented; actual installed-host lifecycle and
real multi-harness validation remain later acceptance. Reuse `docs/WORKERS.md` and
`docs/CONCURRENCY.md`; no live authorization is renewed.
P2 fixed baselines/context and explicit preparation are implemented; reuse them. Unknown
preparation exits retain project slots/resource claims even after manual task failure;
future audited release must not treat acknowledgement as proof of exit. Persistent service
management and cross-state resource coordination are unsupported. Contracts:
`docs/PREPARATION.md`, `docs/EXECUTION_CONTEXT.md`, `docs/COORDINATION.md`, `docs/PLANNING.md`.
`docs/PRODUCT_FORM.md` is an overview only. The plan is documentation, not execution evidence.

Real interruption/timeout validation and T5 evaluation (`docs/EVALUATION_PLAN.md`) still
need explicit bounded authorization before any real call. The prior repair allowance is used.
Controlled repair/resume is complete for one bounded task; do not rerun it merely to hand off.
Engineering backlog (no model needed): `docs/BACKLOG.md`.
