# Handoff

## Independent integration delivered; Opus recovery correction remains — 2026-10-09

- Backend input: `ad585c59fc932280f49833414e8ea5b90ca3ff75`.
- Frontend confirmed in PR #3: `202630f659d0411ef81a611ccc98bf09bfc4b4aa` (includes initial
  `b866e093db3200923ed181f8c98513fcbee3ec87`).
- Backend fixes: `9a9d6f9c9be4bedb840edbf931d8f39f38c055b9`, PR #4 remains based on PR #3.
- Fixed integrated code: `fee9971c6ed5599a679b4a9193c6ba1940609fdc` in
  `/Users/chan/Downloads/repobridge-integration`, branch `codex/existing-session-integration`.
  Frontend and old main checkout were not modified; no default merge or installed replacement.
- Exact interface: [EXISTING_SESSIONS_API.md](docs/EXISTING_SESSIONS_API.md).
  Final evidence and reproduction: [EXISTING_SESSIONS_INTEGRATION.md](docs/EXISTING_SESSIONS_INTEGRATION.md).

Final fixed-integration offline suite: **990 passed in 1055.66s (17m35s)**; no failures or skips.
No live test was run.
Use **absolute** `PYTHONPATH=/Users/chan/Downloads/repobridge-integration/src` when reusing the
frontend virtualenv: detached workers change cwd and otherwise import its editable frontend source.
The initial mixed-path attempt was interrupted and is not final evidence. Static checks passed;
rendered tests used only isolated native-shaped histories, actual fault stubs and fake desktop apps.

**Next frontend integration:** Opus must handle `delivery.state=unknown` before treating an ended
run as definitely unsent. Reproduced P1: backend says possibly delivered, UI says “没有发出的消息”
and offers recovery into the composer. Query the durable `/delivery?client_id=` after missed events,
ended run or reload; preserve uncertain text/attachments separately, with no automatic resend.
Keep current late-sent/new-draft/attachment protections. The backend already blocks new sends while
unknown. Also review 900×640 composer overflow (P2); optional explicit unsupported display now has
`capability_unsupported`. Deliver a confirmed new frontend SHA for Codex to merge and reverify in the
independent integration checkout. Codex does not edit frontend-owned files to bypass this handoff.

External-held unlink now correctly returns `details.external`; its confirmation requirement is
unchanged and remains atomic. `/desktop/return` is the intended native-link external-ended
confirmation: records a user statement, clears hold/cache, starts/sends nothing, and does not claim
observed external exit. New receipts use existing event storage; no additional schema migration.

Real designated outside-created sessions and official-desktop continuity remain unverified and
unbudgeted. No unrelated history, credentials, live database, model calls or prior-allowance reuse.

## Prior backend delivery — 2026-10-09

Use backend branch `codex/existing-session-backend` in `/Users/chan/Downloads/repobridge-backend`;
it starts at exact common handoff `ef75a625577c1848e1079dd6d487a5cdc3afa166`. The first pushed commit
`c20679e3d7e0915756a4901ab1b80a5ef91123c3` delivered the API/ownership contract before implementation.
The frontend worktree/branch and old main checkout have not been switched or edited.

Pushed implementation: `d638e9aec41ee193db3283efccc3fc029ca13b3f`.
Draft [backend PR #4](https://github.com/CHANxuanyu/harness-bridge/pull/4) targets the frontend
handoff branch (stacked on open PR #3), not the default branch. No merge or release performed.

Delivered by Opus in `202630f`: the scoped discovery/preview/link UI against
[EXISTING_SESSIONS_API.md](docs/EXISTING_SESSIONS_API.md). Keep current /api/state + SSE, session
detail, conversation, start and desktop routes; new fields/route examples are exact in that document.
In particular, link's local ID is `result.session.session.session_id`, association history is not
copied, `turns_observed=0` does not imply an empty native session, and `can_start_fresh=false`.
An unknown/external writer requires the user's confirmation; never infer idle from unknown.

Backend acceptance: 102 related tests passed, 21 new external-session cases; static checks passed.
Details and test command: [EXISTING_SESSIONS_RESULT.md](docs/EXISTING_SESSIONS_RESULT.md).
Schema 3→4 is one additive association table. Test with a **fresh isolated state directory and
port 0**; do not point this branch at the user's live database. Runtime tools were reused read-only
from the frontend `.venv`. That earlier focused run used a relative source path; for integrated
checks including detached workers, use the absolute source path documented above.

Current integration owner remains Codex: integrate Opus's next confirmed recovery correction,
then separately check user-designated outside-created native samples when authorized. Do not use prior App-created acceptance threads, scan other project histories, or
start model turns under the exhausted W6–W8 allowance. Full real continuation needs a new explicit
bounded allowance and designated samples. Read-only scoped checks need no model allowance.

Public status docs and AGENTS are Codex-owned; Opus reports via its commits/PR. No merge to default,
release, automatic frontend cherry-pick, new PRD, or phase-approval cycle is part of this delivery.

## Existing-session backend contract — 2026-10-09

Backend branch `codex/existing-session-backend`, independent worktree
`/Users/chan/Downloads/repobridge-backend`, exact base `ef75a625577c1848e1079dd6d487a5cdc3afa166`.
Minimal frontend contract is [docs/EXISTING_SESSIONS_API.md](docs/EXISTING_SESSIONS_API.md).
app.py/native_mac.py remain frontend-owned; shared status docs are integrator-owned.
Historical contract milestone: implementation and scoped checks are delivered above. No real state opened,
no personal history scanned, no new model allowance. Current W6–W8 evidence is retained.

## Role split from here: Codex owns backend and integration, Opus owns frontend — 2026-10-09

From this handoff point, Codex implements the backend, protocols, storage and tests directly, and
integrates. Claude Code (Opus 5.5) owns the frontend, desktop interaction, visuals and UI testing, and
verifies the real interface after integration. The GLM split is not restored. Verified work is kept,
not rewritten. Opus makes no further backend, migration or public-interface changes until Codex
publishes the minimal interface contract for the next feature.

**Checkpoint.**

- Frontend workspace (Opus, stays here, no branch switch):
  `/Users/chan/Downloads/harness-bridge/.claude/worktrees/repobridge-product-direction-8e26f9`,
  branch `claude/repobridge-product-direction-8e26f9`, pushed, draft
  [PR #3](https://github.com/CHANxuanyu/harness-bridge/pull/3) into `claude/new-repo-plan-dn1eac`
  (not merged).
- Code baseline: `2f26d237e73cb8fdf0a94793036bfd60b15164c9`. Full `scripts/check.sh` passed on it
  (ruff, format, strict mypy over 58 files, 942 tests in 17m34s, exit 0). The commit that adds this
  section changes only `STATUS.md` and `HANDOFF.md`. Codex's backend worktree should start from that
  commit, or from `2f26d23` (same code).
- Do not branch the backend from the default branch: `claude/new-repo-plan-dn1eac` (`4eb1b21`) does not
  yet contain W6–W8 (`db0b1d4`..`2f26d23`). If PR #3 is later squash-merged, rebase the backend branch
  onto the new default branch.
- Main checkout `/Users/chan/Downloads/harness-bridge` is on `local/glm-macos-validation` (`f2cd6e6`)
  and clean. It is GLM-era work, not part of this split: do not switch, sync or reuse it.
- Nothing left running from this workspace: no RepoBridge test instances, no background jobs, no stash
  entries. Processes still running belong to the user's Claude/Codex desktop apps; leave them.

**File ownership (one owner per file; ask the owner instead of editing).**

| Owner | Files |
|---|---|
| Codex: backend, protocols, storage, tests, integration | `src/harness_bridge/**/*.py` except the two desktop-shell files below — notably workbench `service.py`, `store.py` (schema and migrations), `structured.py`, `conversation.py`, `controls.py`, `harness.py`, `desktop_apps.py`, `handoff.py`, `changes.py`, `relay.py`, `pty_host.py`, `prefs.py`, and `server.py` (its routes and JSON shapes are the public interface); `tests/**` including `tests/helpers/wb_stub.py`; `scripts/`, `pyproject.toml`, `uv.lock`; `AGENTS.md` (the role split is not yet written there), `docs/DECISIONS.md`, `docs/PROJECT_PLAN.md`, `docs/VALIDATION_MATRIX.md`; `STATUS.md` and `HANDOFF.md` from now on (integrator) |
| Opus: frontend, desktop interaction, visuals, UI testing | `src/harness_bridge/workbench/static/**` (`app.js`, `composer.js`, `markdown.js`, `app.css`, `index.html`; `vendor/` unchanged); `docs/screenshots/**`; in `docs/WORKBENCH.md` the sections 界面, 设计原则 and 原生窗口集成 and the screenshot rows under 证据; new UI-only test files named `tests/**/test_workbench_ui_*.py` |
| Proposed for Opus, Codex to confirm or change in its first contract note | `workbench/app.py` and `workbench/native_mac.py` (pywebview window, native panels and dev snapshot loop). Anything they expose to the page goes through `/api/native/*` in `server.py`, so a new native hook needs a route from Codex |

Opus's frontend progress goes in its commit messages and PR description; Codex folds it into STATUS
and HANDOFF at integration. A new UI preference key needs a whitelist entry in `prefs.py`, so Opus asks
Codex for it.

**What the frontend currently depends on (keep compatible, or announce the change in the contract).**

- `GET /api/state` (snapshot, including `catalogs`) and the SSE stream `GET /api/stream`.
- Sessions:
  - `GET /api/sessions/<id>`, `…/activity`, `…/changes`, `…/conversation[?refresh]`,
    `…/diff?path=`, `…/files?q=`, `…/output`.
  - `POST /api/sessions` and `…/start|stop|send|input|interrupt|permission|settings|attachments|view`.
  - `POST …/desktop/open|desktop/return|handoff|handoff/draft|rename|resize|archive|unarchive`.
- Projects: `POST /api/projects`, `…/archive`, `…/reveal`.
- Other routes:
  - `POST /api/catalog/<harness>/refresh` and `/api/harnesses/refresh`;
  - `POST /api/prefs`;
  - `POST /api/native/*`;
  - dev-only `/api/dev/snapshot|reload|resize`, used for native screenshots.
- The session view's `settings` object (states selected / applying / confirmed / failed / launched)
  and conversation items as produced by `conversation.py`.

**Frontend needs for the next feature (input for Codex's contract, not a contract).** The feature:
add an existing native session, preview it, read its history, continue it, continue in the official
client, come back. The UI needs the following.

- **Discovery list.** Filtered by harness and project, and only for projects the user allowed. It must
  be paged. Each entry needs:
  - native id and storage environment;
  - source: CLI, official Desktop Code page, or cloud/other, with a resumable flag and the reason;
  - title, updated time, working directory (exists or not, project or worktree match);
  - already-linked (with the RepoBridge session id);
  - whether it is in use elsewhere, or unknown.
  - The list also needs a completeness flag (complete, or partial plus the reason).
- **Preview.** The same item shape as `/conversation`, paged, with explicit states: loading, truly
  empty, failed (reason), partial.
- **Link and unlink.**
  - Link must be idempotent on native id plus storage environment and must return the RepoBridge
    session.
  - Unlink keeps the native history.
- **History paging.**
  - A cursor to load older pages.
  - A "since" refresh after the official client added turns.
  - Stable item ids, so a refresh never duplicates messages.
- **Progress.** SSE events for list and preview progress, or a documented polling rule.
- **Boundary.** The frontend never reads vendor session files or databases itself.

**Open items that affect both sides.**

1. PR #3 (W6–W8) is still a draft. Merging it is the user's decision.
2. Store schema revision 3 (`settings_json`, additive from 2) exists only on this branch, so the next
   migration is 3 → 4. The user's own state directory has not been migrated. Their App runs an older
   build, and the in-use state database must not be upgraded. Test migrations on copies or test state
   directories.
3. The real-turn budget for W6–W8 is used up (Claude Code 6/6, Codex 6/6). New real-message tests need
   a new minimal batch approved by the user. Listing, preview, UI and offline work can proceed without
   one.
4. Implemented but not verified for real:
   - an account-refused model;
   - Codex approval card, questions and MCP forms;
   - Claude AskUserQuestion;
   - file (non-image) attachments;
   - clipboard paste, Finder drag-in and the native open panel;
   - the pywebview window with real sessions;
   - terminal-view input (both CLIs stop at their own first-run prompts, which are left for the user).
5. Two machine facts matter for "continue in the official client and come back".
   - This machine's Codex uses `approvals_reviewer = auto_review`, so no approval card appears.
   - Codex refuses a second writer while the Codex App holds the thread (`thread … already has an
     active writer`). RepoBridge reports this and does not force it.
6. Acceptance leftovers, left in place (nothing deleted):
   - `~/rb-acceptance/demo`, whose `notes.md` has uncommitted edits;
   - the state directory `~/rb-acceptance/state`;
   - the native sessions titled "RepoBridge 验收 Claude" and "RepoBridge 验收 Codex".
   These were created by RepoBridge, so they do not count as sessions created outside RepoBridge.
7. Agent SDK distribution caveat for the Claude conversation view (DECISIONS 133).

**Opus next (independent of the contract).**

- Frontend visual and interaction work only, for example:
  - long-history scrolling stability;
  - drafts and focus kept across refreshes;
  - empty, loading and error states that are distinct and honest.
- Once Codex publishes the contract, build the add-existing-session dialog, the preview and the
  history paging against it.
- Verify the integrated real interface.

## W8 controls, attachments and native forms done offline; real acceptance next — 2026-10-08

Read [WORKBENCH.md](docs/WORKBENCH.md) (W8 sections, the three support categories) and DECISIONS
139–146 first. Where things are:

- `workbench/controls.py`: catalog normalisation (Claude `initialize`, Codex `model/list` +
  requirements), mode lists (bypass / full access deliberately absent), choice validation and
  re-validation on model change, host-report matching.
- `workbench/structured.py`: Claude `control_wait` (control_response correlation),
  `apply_settings` (set_model / apply_flag_settings effortLevel / set_permission_mode),
  `read_settings` (get_settings), `message_start.model` and `system/init` reports, image blocks and
  uuid-matched echo; Codex `_load_catalog`, `connect_settings` → thread/start|resume params,
  `turn/start` overrides, `read_settings` (thread/read after turn/started, loaded-thread
  thread/resume after turn/completed), `model/rerouted`; `probe_catalog` (no session, no turn);
  Codex question/form answers.
- `workbench/service.py`: per-session `settings_json` (schema 3, additive), `choose_settings`,
  `_apply_now` (model first, dependents roll back), `_on_settings` (confirm/fail by authoritative
  source per harness), `_connect_settings`, `connect_failures` (blocks a send), terminal flags via
  `harness.claude_setting_flags` / `codex_setting_flags`, attachments (`add_attachment`, image
  detection by bytes, size limits), `search_files`, catalog cache/probe.
- `server.py`: `POST /api/sessions/<id>/settings|attachments`, `GET /api/sessions/<id>/files`,
  `POST /api/catalog/<harness>/refresh`, `POST /api/native/pick-files` (native open panel), larger
  body limit only for uploads.
- `static/composer.js` (new): composer, selectors and pickers, attachments, `@` / `/` popups,
  question and form cards. `app.js` wires it in; `#dev=model|effort|mode|attach` open pickers for
  snapshots; dev mode disables animations (`.dev-still`).
- Stubs keep model/effort/mode state, log every control request / RPC (`claude-controls.log`,
  `codex-rpc.log` in WB_STUB_HOME) and honour acceptEdits/dontAsk. Offline Codex behaviour probe with a
  local fake Responses endpoint: scratch scripts only (not in the repo); results in DECISIONS 140.

Real acceptance ran on 2026-10-08 (results table in WORKBENCH.md “真实验收结果”; budget used up:
Claude 6/6, Codex 6/6 — any further real check needs a new authorization). Open items from it: Codex
approval card (needs `approvals_reviewer = user` in the user's Codex settings — never changed by
RepoBridge); re-connecting after the Codex App still holds the thread (Codex's writer lock);
questions/MCP forms and AskUserQuestion with a real model; file attachments and clipboard/Finder/native
picker; the pywebview window with real sessions; terminal view after the CLIs' own first-run prompts.

## W6/W7 conversation view and desktop continuation done offline; real acceptance next — 2026-10-08

Code: branch `claude/repobridge-product-direction-8e26f9`, draft
[PR #3](https://github.com/CHANxuanyu/harness-bridge/pull/3) into `claude/new-repo-plan-dn1eac`.
Read [WORKBENCH.md](docs/WORKBENCH.md) (W6/W7 sections, support matrix) and DECISIONS 132–138 first.

Where things are: `workbench/structured.py` (Claude stream-json + SDK control protocol, Codex
app-server JSON-RPC, history readers), `workbench/conversation.py` (native messages → items;
transcript and `thread/turns/list` projections), `workbench/desktop_apps.py` (official desktop
routes), `service.py` (`start_run` picks PTY or structured by `sessions.view_mode`; `switch_view`,
`send_message`, `interrupt`, `answer_permission`, `conversation`, `open_in_desktop`,
`desktop_return`; external hold in `sessions.external_json`), store schema 2 (additive migration
from 1), `static/app.js` conversation section + `static/markdown.js`. Stubs:
`tests/helpers/wb_stub.py` (stream-json, app-server, `--desktop`, `demo` turn for screenshots).

Test-instance loop (stub CLIs, fake apps, nothing real opened): `hbridge app --state-dir <s>
--claude-binary <stub> --codex-binary <stub> --dev-snapshot-dir <d> --dev-app-dir <fake Applications>
--dev-opener <recorder>` with HOME/WB_STUB_HOME/CLAUDE_CONFIG_DIR inside a scratch dir; dev hashes
`#dev=view|desktop|new|menu|settings|handoff|diff:N`. Dev mode keeps rendering when the window is covered.

Checks run: full offline `scripts/check.sh` — ruff, format, strict mypy (57 files) and **917 passed in
18m04s**, exit 0 — on the tree before the last workbench-only edits (cache save order, a static
UI-safety test, an open-link route test, a stub trigger, docs); after those, all 58 workbench tests,
ruff, format and mypy were re-run and pass (suite total now 919). No test skipped or removed.

Next: (1) real acceptance per WORKBENCH.md “W6/W7 真实验收” — by the user, or by me after the
bounded authorization in STATUS; record T3-W/T4-W results and the four desktop observations separately.
(2) Likely follow-ups from real CLIs: exact stream-json event shapes in 2.1.291 (init timing, interrupt
result, AskUserQuestion answer format), Codex app-server approval params in practice, Desktop list
filtering of `-p` / app-server sessions. (3) Then `.app` packaging.

## W5 redesign done; W4 real acceptance next — 2026-10-08

Code: branch `claude/repobridge-product-direction-8e26f9`, merged into the default branch
`claude/new-repo-plan-dn1eac` via [PR #1](https://github.com/CHANxuanyu/harness-bridge/pull/1)
(merge commit `e348c85`, 2026-10-08); local worktree
`/Users/chan/Downloads/harness-bridge/.claude/worktrees/repobridge-product-direction-8e26f9`. The main
checkout `/Users/chan/Downloads/harness-bridge` stays on `local/glm-macos-validation` (`f2cd6e6`) and
does not contain the workbench; do not switch or sync it without the user's instruction.
Read [WORKBENCH.md](docs/WORKBENCH.md) and DECISIONS 124–131 before changing the UI.

Frontend lives in `src/harness_bridge/workbench/static/` (no build step). Native window glue:
`workbench/app.py` (single-instance lock, pywebview window, native hooks) and `workbench/native_mac.py`.
Layout/appearance prefs: `workbench/prefs.py` (whitelist). Do not re-enable pywebview js_api or add
`unsafe-eval`; extend `/api/native/*` instead.

Visual check loop (no real CLI, no model): start
`hbridge app --state-dir <test-state> --claude-binary <stub> --codex-binary <stub> --dev-snapshot-dir <dir>`
outside an agent env (`env -u CLAUDECODE`), open `<dir>/launch-url.txt` in a browser to drive the
same server, then `POST /api/dev/reload` (optional `{"hash": "dev=handoff|settings|new|diff:N"}`),
`/api/dev/resize`, `/api/dev/snapshot {"name": ...}` and read `<dir>/<name>-window.png`. Stub wrappers
exec `tests/helpers/wb_stub.py` (supports `edit`, `perm`, `crash`, `/clear`, `size`, `spam N`).

## W1–W3 workbench implemented; W4 real acceptance next — 2026-10-07

State: workbench code in `src/harness_bridge/workbench/`, tests in
`tests/unit/test_workbench_units.py`, `tests/integration/test_workbench.py`,
`tests/integration/test_workbench_server.py`, stub CLIs in `tests/helpers/wb_stub.py`.
Read [WORKBENCH.md](docs/WORKBENCH.md) (run/use/structure/evidence/W4 steps) and DECISIONS 112–122.

To continue:
0. Location: this code is on branch `claude/repobridge-product-direction-8e26f9` in worktree
   `/Users/chan/Downloads/harness-bridge/.claude/worktrees/repobridge-product-direction-8e26f9`; the main
   checkout `/Users/chan/Downloads/harness-bridge` (`local/glm-macos-validation`, f2cd6e6) does not contain
   it (PR #1 merged it into the default branch `claude/new-repo-plan-dn1eac` on 2026-10-08, not into that
   local branch). Running there gives "Extra desktop is not defined"/"invalid choice: app".
1. W4: in a normal terminal (not an agent session), from that worktree:
   `uv sync --frozen --extra desktop && uv run --frozen --extra desktop hbridge app`,
   then follow WORKBENCH.md "真实验收步骤". Record results as T3-W/T4-W in VALIDATION_MATRIX with
   exact CLI versions; keep failures as found.
2. Likely follow-ups: native quirks of Claude/Codex TUIs inside xterm.js (keys, IME, alt-screen),
   Codex resume semantics for the bundled 0.162 CLI, `.app` packaging/launch from Finder.
3. Offline UI checks: start `hbridge app --no-open --claude-binary <stub> --codex-binary <stub>`
   with `WB_STUB_HOME` set and without `CLAUDECODE`; stub wrappers exec `tests/helpers/wb_stub.py`.

Boundaries unchanged: no real `claude`/`codex` spawn from tests or agent sessions, no token reads,
no API-billing switch, no push/release without the user's instruction, commit author = owner.

## W0 product direction v2.0 — 2026-10-07

Read [PRODUCT_FORM.md](docs/PRODUCT_FORM.md) and [PROJECT_PLAN.md](docs/PROJECT_PLAN.md) §0–§9
first; everything below this section describes the paused Advisor/Executor line and its evidence.
The workbench lives in `src/harness_bridge/workbench/` (from W1). Development rules: AGENTS.md.
Boundaries still in force: no real `claude`/`codex` spawn in tests, no token reads, no API billing
switch, no push/release without the user's instruction, commit author = repository owner.

Next work package: W1 desktop window + native sessions (see STATUS for the latest state).

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

- **Start from `docs/P7_CLOSEOUT.md`:** one current V01–V15 evidence matrix now separates completed native/offline scope from V08/V15 gaps. README and license/release status are reconciled. Do not rerun native checks or ask about unlocking while the user is away.
- **Distribution no longer needs chat helpers:** from a clean committed checkout, `scripts/build_release.py --out ABSOLUTE_FRESH_DIR` creates source/docs/wheel/plugin/manifest/verifier and sibling ZIP; `VERIFY.py` checks a relocated candidate without installing anything. Twelve new synthetic release checks passed / 2.81s (144-file lint/format; mypy 40 runtime files). Core and actual alpha.4 plugin files are unchanged. Build receipt/candidate location is retained in the takeover chat's `work/p7-distribution/` and `outputs/`; rebuilding is not a release authorization.

- **Advisor desktop follow-up installed:** plugin alpha.4 is enabled in actual Codex and ZCode profiles. It carries the user's requested desktop visibility through delivery, queries exact child bindings, handles the supported handoff and reports pending/unsupported results separately. Both cached packages match all 16 source files, both connection checks pass 36 command surfaces without opening selected state; 34 other Codex plugins / 15 other ZCode plugins and the shared connection are unchanged. Native Codex skills/list loads alpha.4 for repo and chat cwd; current GUI refresh remains unobserved.
- **Codex diagnostic:** a read-only worktree-scoped native probe confirms source `exec`; default/interactive lists omit the session, while explicit exec filtering returns its exact UUID. No new session/turn, resume, import or metadata mutation was used. This demonstrates native filtering, not a completed desktop synchronization route.
- **This slice's checks:** plugin suite 26 passed / 17.22s, including two new incompatible-runtime refusals; Skill Creator validator passes; lint/format 142 files and mypy 40 runtime files pass. Runtime/source execution logic is unchanged, so prior full/desktop evidence is reused.
- **P7 bounded native packet completed.** The approved final two executions passed: fixed Codex cancellation stopped all observed descendants (independent fixture survivor check empty); Claude stopped with native `error_max_turns`. Real dual-harness collaboration, same-session repair, integrated review and exact local delivery remain passed. Preserve the earlier failed cancellation and permission stop as historical evidence.
- **Final allowance accounting:** 8 actual executions (Claude 4 / Codex 4), 1 repair, 975 reserved wall seconds; observed native duration 145.629s, not billed usage. One older Codex reservation is a proven non-start. All validation gates are closed; no additional real execution is authorized or needed for this packet.
- **New desktop requirement remains open.** `desktop status` locates the original native session without invoking a harness. `desktop open` adds a once-only Claude CLI-to-desktop handoff for terminal tasks / delivered goals, with current Advisor guards, exact binding and version checks. No prompt or new attempt. Native acknowledgement is not desktop visibility. Codex is explicitly `native_history_only`: title/section/pin metadata probes did not make the Executor appear in the app list; the temporary section was removed.
- **UI verification deferred by the user:** the user is away from home and will unlock the Mac after returning; continue CLI/code only meanwhile. No Claude desktop handoff has been run. Full Codex GUI shutdown remains unverified. ZCode quit/relaunch with a fake worker, native plugin lifecycle and independent runtime retention evidence remain valid.
- **Validation:** reuse the pre-change full **732 passed / 922.88s**. New desktop/CLI/coordination run **55 passed / 37.69s**, including 26 new desktop cases; lint/format 141 files and strict mypy 40 runtime files pass. Final native-session selection hardening: 26 desktop cases passed / 6.98s. This is affected coverage, not a new full-suite run.
- **Distribution:** runtime 0.1.0.dev1 / installed plugin alpha.4 / schema 10. Apache-2.0, local candidate only. No push, tag, publication, provider/billing change, shared-state migration, new model turn for desktop visibility. See `docs/P7_RESULT.md` and `docs/DESKTOP_SESSIONS.md`.

The latest human continuation accepted the already-proposed 2 executions / 150 seconds,
adding exactly one Codex execution / 90 seconds to the original envelope. Both are spent.
Receipts under the takeover chat's `work/p7-live-20261007/`:
`retest-authorization.json`, `codex-cancel-retest/result.json`,
`claude-turn-limit/result.json`, `final-bounded-acceptance.json`.
Do not rerun these cases. Claude configured max-turns 1 returned `num_turns: 2`, with one
assistant Read tool and no Write; native `error_max_turns` proves the stop path, not a universal
internal-model-call ceiling. All gates are closed.

Delivered goal remains `goal_e77ac7ce90244b89ac7e`, Advisor `adv_8a7a7f97287b421293f3` epoch 1,
fixture branch `bridge/p7-result`, commit `73f485d437bc5bcf1796f6bd141e0b3d1be0033f`.
Claude task `tsk_fe53cbb261c549c89176`, native session `347cb6dd-57aa-4157-9860-d67a2cd5e1b1`;
Codex task `tsk_190c432213004a20863a`, native session `01a11375-1bfc-7ba3-a351-8d206887423c`.
Their state is `work/p7-live-20261007/dual-recovered/state`. Both exact bindings are confirmed
by the new read-only desktop status command. Do not create another native session.

Latest plugin receipts: takeover chat `work/p7-plugin-alpha4/result.json` and `codex-native-skills.json`; native source-filter proof: `work/p7-codex-list-probe.json`.

Continue desktop acceptance after manual Mac unlock. Do not ask again while the user remains away. The user explicitly chose CLI/code first;
do not bypass the lock or prior Codex computer-use refusal. Claude's official handoff is ready
but NOT_RUN. Codex app read_thread can read the Executor; list_threads still omitted it after
successful metadata operations. Its helpful title is retained; section/pin experiments were
reverted, the empty temporary section deleted. This is not a sidebar-sync pass. No raw vendor
history/DB edits and no extra model turns are acceptable visibility workarounds.

## Historical state before the P7 native/distribution run

- **New P7 preparation slice:** `qa/local/p7_fixture.py` generates a fresh synthetic two-child packet;
  `qa/local/p7_rehearsal.py` drives both adapter paths through fresh CLI processes with live disabled.
  Two concurrent stand-ins, active-job Advisor takeover, stale-write refusal, exact-session repair,
  external integrated verification and local delivery all pass. **8 new checks passed / 13.91s**;
  pre-change affected baseline **44 passed / 38.80s**. Lint/format/mypy pass; no full-suite repeat.
  A separate standalone invocation also passed: the takeover chat's
  `work/p7-rehearsal-20261007/result.json` retains 3 attempts / 1 repair, 30 reserved turns / 1800s,
  confirmed exits, source/check/packet preservation and the delivered commit. No running job remains.
- **Continue with remaining P7 evidence, not this rehearsal again:** see `docs/P7_ACCEPTANCE.md`.
  The Codex capability audit reused native 0.160.0 schemas and current official references without
  reading auth or invoking a native turn. It still does not establish internal model-turn enforcement,
  effective subscription/config provenance or native resume/workspace behavior. Do not unlock live,
  substitute token/wall/prompt limits, or rename a real binary as a stub. Synthetic packet pins are
  not actual model/session choices. The proposed future 3-execution scenario is not authorized;
  the prior 2-attempt allowance is spent. Native lifecycle/failure cases and distribution remain.
  Runtime, plugin alpha.2 caches, default connection and historical stores are unchanged; no push.

- **P6 no-model wiring accepted:** Codex actual profile now installed/enabled alpha.2 through its
  native CLI. Existing 34 plugins unchanged. A short-lived native app-server `skills/list` resolves
  enabled `harness-bridge:harness-bridge` for repo/chat cwd without creating threads/turns. Actual
  ZCode installed/enabled evidence remains valid; both caches match 13 source files.
- **Default connection now configured:** `~/.config/harness-bridge/connection.json` (0600), runtime
  in the source checkout's `.venv/bin/hbridge`, new dedicated state under `Documents/Codex/harness-bridge-state`.
  Both installed cache checkers resolve it with no arguments. Explicit normal projects read created
  an empty store, live disabled. Existing smoke/repair state was not opened/migrated; its explicit
  locators still win. Do not silently move historical tasks or enable live on this default.
- **Native tool lifecycle:** current Codex tool PTY exited; one mock job remained RUNNING. A fresh
  reader reconnected via its saved locator and cancelled it with confirmed exit. Exactly one attempt,
  unchanged source, no surviving fixture job. Raw evidence: takeover chat `work/p6-desktop/`.
  No runtime/package edit, model call or prior test-suite rerun. See `docs/P6_DESKTOP_ACCEPTANCE.md`.
  Computer-use access to Codex itself was refused; no GUI workaround/restart was attempted. Native
  metadata loading passes but the already-open window's hot refresh is unobserved. Full app
  termination and real agent behavior remain P7. Leave both installed plugins/connection intact.

- **Prior P6 slice:** shared plugin alpha.2 now documents the full goal/child/job/review/delivery path
  and resolves a shared local runtime/state connection. Its checker uses temporary state/home,
  34 help surfaces and offline diagnostics; it never opens the selected database or calls a model.
  New copied-package/CLI integration suite: **24 passed**, 19.96s, lint/format/mypy clean.
  Codex CLI 0.160.0 installed/enabled the plugin in the takeover chat's isolated profile; its 13
  cached files match source and checker passed. No active Codex profile/auth was changed.
  With explicit user confirmation, ZCode added the local source and installed alpha.2. Its Settings
  Skill detail reports enabled; all 13 cached files match and the same connection check passes.
  Leave the installed plugin intact. Actual Codex desktop discovery and host behavior remain;
  do not start an agent turn merely to prove discovery. See `docs/P6_ENTRYPOINT_RESULT.md`.
  The prior P5 full suite remains historical; no broad repeat, model call, state migration or push.

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

- **Completion slice:** optional ChildPlan `integration_repair` atomically binds a retained source
  integration baseline. Optional IntegrationSpec `repair_child_id` resolves that exact input prefix;
  original required inputs and checks remain. `integration_repairs.py` reuses existing task execution,
  ownership/preparation/worker controls; shared dispatch accounting counts repair children.
- **Cleanup:** `cleanup.py` adds read-only preview, explicit policy/fingerprint-bound apply and durable
  receipts; current Advisor + completed matching delivery + known inactive project are required.
  Raw file/mode/registration/metadata checks precede non-force Git worktree removal. No source edits,
  branch deletion, evidence GC or cache deletion. Unconfirmed removals are retained and not relaunched.
- **Schema 10:** `cleanup_requests` only; old canonical digests remain compatible. Isolated fixture
  upgrades/backups only. Full validation details and corrected failures are in `VALIDATION_MATRIX.md`.

- **Canonical plan:** `docs/PROJECT_PLAN.md` consolidates the product, session relationships,
  contracts, V1 scope defaults, P0–P7 milestones and V01–V14 acceptance. P0 is complete;
  P1–P4 local cores, P5 offline adapter and P6 model-free wiring are implemented; Codex live readiness and P7 remain pending. Advisor is
  explicitly an existing agent session; Bridge does not create its own planning model. `PRODUCT_FORM.md` is now a short summary, and the
  original cloud execution plan is clearly historical, not renewed authorization.
- Key plan choices: dependencies are fixed before child execution-task/worktree materialization;
  task mutations cannot bypass goal budgets or the active Advisor epoch through old CLI paths;
  unknown exits retain reservations/slots; V1 targets managed workers and exact local-branch
  delivery with integrated acceptance. Epoch and initial aggregate guards now exist;
  managed workers, scoped parallel admission and frozen integration candidates now exist;
  integrated checking/review, explicit local delivery, budgeted conflict repair and conservative cleanup now exist.

- **New P3 slice:** `jobs.py` + internal `worker.py` add idempotent `run --background`,
  atomic attempt/reservation/single claim and detached process sessions. Both foreground and
  background use `Bridge._execute_attempt`; worker rebuilds/digest-checks the accepted invocation
  and rechecks preparation/live gates. Reads (`job`, `events`) never dispatch; task status lists
  worker handles. Current Advisor required for dispatch/replay; accepted work may finish after
  takeover. No auto restart/repair, queue, launchd service or new model dependency.
- **Worker failure contract:** unclaimed dead-launcher reservations can be transactionally fenced
  and marked confirmed non-start, so even delayed workers cannot execute; emergency cancel also
  fences unclaimed work. After claim, ordinary recovery retains unknown exits/budgets/slots and
  sends no guessed-process signals. Confirmed executor exit allows verifier-only recovery.
  `recovered` job phase does not mean confirmed exit. Goal ledger excludes proven non-starts;
  task attempt numbers/ceilings remain conservatively consumed. Non-started repairs retain
  feedback and skip only proven non-starts when selecting the last observed compatible session.
- **Revision 6:** additive `worker_jobs`; atomic WAL-aware backed-up upgrades from revisions
  1–5, preserving all previous contracts/digests. Isolated migration fixtures updated and old
  prepared-task evidence preserved. No actual live/user state was migrated.
- **P3 parallel-admission milestone:** `dispatch.py` projects cumulative attempt wall-time/turn
  ceilings from integrity-checked frozen TaskSpecs. GoalSpec adds optional total ceilings while
  omitting absent values from canonical JSON to preserve old goal digests/replay. Revision stays
  6; no migration/new usage table. Only proven non-starts refund goal ledger; completed, cancelled,
  failed or unknown execution retains full requested ceilings, not self-reported usage.
- **Concurrency:** local `[execution] max_parallel_per_project = 2` explicitly enables two;
  default 1, max 2, all goals in the same repo/state share it. Reload config at reservation, record
  the admitted cap in events, never kill accepted work on a lower cap. Require disjoint literal
  write roots (case/Unicode aliases conservative); broad globs/refined forbidden sets do not prove
  disjointness. Unknown executions retain slots, including multiple historical unknowns per task.
  A spare slot cannot admit another attempt on that same unresolved worktree. No queue.
- **Preparation / verification:** setup remains foreground and project-exclusive because its
  arbitrary trusted scripts lack complete effect scopes. Existing named resource holds remain.
  Manual verify and INTERRUPTED verifier recovery reserve capacity/scope too; already VERIFYING
  keeps its slot. No new executor budget is spent by preparation/checks.
- **P3 boundary:** offline evidence includes two running fake processes, independent cancellation,
  race-safe reservation, scope refusal, worker death and simulated host process-session teardown.
  Actual Codex/ZCode desktop cleanup, logout/sleep/reboot, vendor turn enforcement and real two-harness
  behavior remain unverified. Goal-wide event cursors are not exposed. See `docs/CONCURRENCY.md`.

- **P4 candidate slice:** `integration.py` implements `goal integrate` (freeze) and `integration
  materialize/status`. Requires every planned/linked task approved and all exits confirmed;
  binds input order, dependencies, retained approvals, goal/base/repo and verifier configuration.
  Git composition reuses the custom-driver-refusing merge helper. Candidate/partial refs are
  immutable; worktrees are separate from the user checkout. A crash after Git but before DB commit
  can retry only the identical pin and an unchanged owned workspace. Existing candidate replay
  never recreates/overwrites a changed/missing worktree. These two commands never execute checks;
  the new explicit check/review commands are described below. No delivery, automatic conflict
  resolution or cleanup is exposed. Read `docs/INTEGRATION.md`.
- **Revision 7:** additive `integrations` table/index with existing WAL-aware backup and atomic
  v1–v6 upgrade/rollback. Older test fixtures now reconstruct their actual schema before upgrade.
  No real state migration, auth/network/model call or live config change. P4 is still partial.

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
  below. Conflict-repair binding and retention/cleanup were completed by the subsequent slice above.
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
  conflict-repair child binding and cleanup were pending at that milestone, now completed above. No real user/live state migrated.
- **Current delivery checks:** full `scripts/check.sh` ran all 519 cases: **518 passed, 1 failed**
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

- **Prior P3 checks:** final `scripts/check.sh` → **395 passed / 0 failures / 0 skipped**,
  226.17s; ruff/format clean (98 files), mypy clean (31 source files). Adds 54 offline cases:
  29 unit and 25 integration. Before edits, affected coordination/migration baseline 35 passed;
  an intermediate full run passed 394 cases, then one additional historical unknown-slot case
  and its conservative fix were included in the final 395-case run. No live/model/auth/network
  calls or real user-state migration. See `docs/VALIDATION_MATRIX.md` for coverage and limits.

- **Prior worker checks:** final `scripts/check.sh` → **341 passed / 0 failures / 0 skipped**,
  199.87s; ruff/format clean (94 files), mypy clean (30 source files). Adds 33 cases: 32 workers
  plus v5 migration rollback. Affected baseline 50 passed before edits; final worker subset 32
  passed. First expanded run had one incorrect stub-fault injection, corrected without deleting
  or skipping a test; details in the validation matrix. No new real model/auth/network calls.

- **New P1 code:** `coordination.py` implements GoalSpec/AdvisorClaim/TakeoverRequest, project
  registration within an explicit state root, goal/child links, takeover fencing and initial
  aggregate attempt/repair/serial-slot guards. Every old mutation entrypoint checks linked
  ownership, including inside the transaction. Reads/emergency cancel remain available;
  accepted attempts can finish after takeover. No model calls or automatic scheduling.
- **P1 completion:** `planning.py` adds immutable child plans, batch idempotency, same-goal DAG
  checks and explicit independent-root materialization. Goal controls pause/resume dispatch or
  request permanent cancel/fail; goal terminal states require all children terminal and every
  attempt exit confirmed. Emergency cancel remains possible without an Advisor. A cancelled
  preparation keeps any resulting workspace attributed to its cancelled task.
- **P2 first slice:** `baselines.py` retains accepted verified trees in private Git refs,
  composes approved dependencies deterministically and pins each child baseline. Successors
  materialize from that fixed commit. Conflicts persist without creating a task/workspace.
  Snapshot refs may outlive a rolled-back DB transaction; only identical deterministic objects
  are adopted on retry. Missing/tampered refs fail closed. External merge drivers are refused.
- **Execution context:** planned children receive goal/child/base and approved-input attribution.
  `child preflight` checks presence, branch/repo/base ownership and required verifier cwd/binaries,
  without executing located tools. `run` checks twice, including the reservation transaction;
  failures consume no attempt. Presence checks do not install dependencies or prove tool/service
  functionality by themselves. `child prepare` now executes explicitly frozen finite commands,
  stores PREPARING/process/step evidence and output/cache inventory, and binds success to the
  current candidate. Same-key replay never runs again; retry requires explicit recovery/new key.
  It preserves task feedback/session binding across preparation before repair.
- **Resources and stop:** preparation shares the project execution slot and holds named exclusive
  resources across all projects in one state root. Unknown exits retain claims even after task
  failure/cancellation and keep goal termination pending. Confirmed failed preparation releases
  claims; successful owners retain them through execution/review until terminal and stopped.
  Late cancel is checked inside the completion transaction. Stale Advisors cannot reserve more
  work, but accepted observations finish. No persistent services/cross-state coordination.
- **Migration:** revision 1/2/3/4→5 adds preparation/resource records (v4 retains snapshots)
  with one WAL-aware backup and
  all-stage rollback. Old plan digests and replay keys are preserved. Older approved tasks need
  explicit `retain-approved` with matching unchanged evidence/candidate; no silent resnapshot.
  No actual live/user state directory was migrated. Preserve Git refs/objects and state/artifacts.
- **P2 checks (prior milestone):** full shared-core `scripts/check.sh`: **307 passed**, 163.10s; lint/format/mypy
  clean (28 source files). One later added preparation→repair/session regression also passed
  via exact-test `scripts/check.sh`, 4.95s. **308 current cases were executed across these runs**;
  do not report a single 308-case full run. 30 new cases in this milestone; affected 72-case
  checks passed before adding cross-project resource/session cases. No real model/auth/network
  calls or user-state migration. `docs/PREPARATION.md` defines completed P2 finite-command scope;
  no integrated delivery, worker survival or installed-host activation claim.

- **Latest user clarification:** target developers who already use several coding-agent
  subscriptions, such as ZCode/GLM, Claude Code and Codex. This is not a Codex-only product.
  `docs/PRODUCT_FORM.md` defines the intended experience: one independent local runtime,
  multiple host entrypoints, shared evidence, explicit delivery back to the project.
- **Subsequent explicit product correction:** one Advisor + one or more Executors, equivalent
  to a main agent with cross-harness subagents. Advisor inspects the repo and dispatches/reviews;
  Bridge creates per-child workspaces and launches the executor with the assigned cwd.
  Treat plugins as entrypoints to that relationship. Parent/child coordination, dependency
  baselines and integration remain product priorities; goal/child links and initial aggregate
  attempt/repair guards, fixed dependency plans and local integrated delivery are now code.
- **Historical plugin alpha.1 (superseded by P6 above):** `plugins/harness-bridge/` has portable, Codex and ZCode
  manifests plus one self-contained supervisor Skill. Codex catalog lives under
  `.agents/plugins/marketplace.json`; ZCode catalog is root `marketplace.json`.
  Package/copy/CLI-contract checks and Codex catalog discovery passed. Temporary catalog
  registration was removed; no plugin installed or real model called. Installed activation,
  ZCode loading, discovery, worker persistence and delivery were not verified/implemented at that
  milestone (`docs/PLUGIN_ALPHA_RESULT.md`). Current evidence is in `docs/P6_ENTRYPOINT_RESULT.md`.

- **Both bounded real smoke levels passed on this Mac:** T3 (GLM operator → bridge →
  Claude Code) and T4 single-run (local Codex session, supervisor model `gpt-6-astra` per
  local turn-context metadata → bridge → Claude Code → review → SUCCEEDED). One initial
  attempt each, zero repairs, all gates satisfied, live gates closed after each run.
  Evidence: `docs/LOCAL_SMOKE_HANDOFF.md` (T3) and `docs/T4_SMOKE_RESULT.md` (T4); matrix
  rows in `docs/VALIDATION_MATRIX.md`.
- **Controlled live repair/resume now passed:** local Codex/Astra directly dispatched
  diagnosis → changes_requested → same-session repair → approve → SUCCEEDED, exactly
  two attempts / one repair. Session and conversation context preserved; 10 repo tests +
  9 external cases passed. See `docs/LIVE_REPAIR_RESULT.md`.
- **Not verified — do not assume:** real interruption recovery,
  live timeout enforcement, long/multi-task behaviour, T5 comparative evaluation, and any
  claim that delegating through the bridge is cheaper or better than direct Opus use.
  Subscription quota remaining: unknown.
- **Repository:** `CHANxuanyu/harness-bridge`, **public** by the user's explicit choice
  (do not change visibility; no license added yet). Working branch
  `local/glm-macos-validation` (contains cloud head `fcbd21a`); remote queried at takeover:
  **pushed through `470f5b0`** at that check. Repair/evidence `94f7c4d`, product/plugin
  `7efd2bf`, product clarification `bab602a`, plan `24ee6ad`, first P1 slice `83f0793` and
  P1 completion `9d73e1c` and P2 first slice `72c73a8` precede the new preparation milestone;
  preparation `591752b`, workers `934b6c2`, P3 concurrency `8409f77` and the new P4 candidate
  milestone follow. All are local, not auto-pushed.
  Remote was not re-queried during this offline implementation round;
  visibility remains public by instruction.
- **Live-gate hygiene:** the global default state dir was never live-enabled; the T3/T4 test
  state dirs had live on only during authorized attempts; the repair state gate was closed
  after each of its two attempts. Raw logs, databases, review files and worktrees stay **outside** the
  repository; only redacted summaries are committed.
- **Offline regression samples:** field-level redacted streams from the initial smokes and
  controlled repair pair live in
  `tests/fixtures/claude_stream_live/` (see its PROVENANCE.json) with parser tests in
  `tests/contracts/test_claude_adapter_live.py`. No model was invoked to build them.
- For future live runs: reuse the checklist in `docs/LOCAL_HANDOFF.md` §2 and the materials
  in `qa/local/`; confirm per-flag evidence and the config opt-in in a fresh isolated state
  dir every time.

## Known issues

- Process-group tests need the explicit "steady state" handshake: killing the runner before
  the fake executor writes its first line makes the executor die of a broken pipe
  (legitimate, but a different path). Tests wait for 2 live group members first.
- Git filters configured in the shared `.git/config` can run during snapshots (documented in
  SECURITY.md); ignored files are outside the observed scope.
- T4 procedural deviation (recorded, closed): one initial read-only `hbridge --help` omitted
  `--state-dir`; every stateful command used the explicit isolated test state dir.
- Permission denials seen in the live runs are permission-layer events (scoped tool
  allowance), not OS-sandbox isolation and not executor failures.
- ~~macOS behaviour (no `/proc`, `ps` fallbacks) is untested~~ — verified 2026-10-06 (full
  suite + 28 targeted tests; macOS rows in `docs/VALIDATION_MATRIX.md`).
- `--max-turns` on CLI 2.1.291: absent from `--help`, accepted in a real minimal call
  (parse-level). Enforcement beyond acceptance remains unproven; per-flag confirmation is
  still required by the live preflight.

## Constraints still in force

- Development model for the bridge itself: `claude-opus-5-5`; no extra model API budget.
- Runtime mode remains `mock` unless locally and explicitly authorized per run.
- Never add `--bare` or `--dangerously-skip-permissions`; never weaken the live gate; never
  convert failing tests into skips.

## History (cloud delivery, 2026-10-06 — superseded)

- Developed in a Claude Code Cloud session through `aeea786` (code) plus docs-only head
  `fcbd21a`; the offline suite and both demos were verified there and from a clone of an
  exported bundle. Working branch at the time: `claude/new-repo-plan-dn1eac`.
- Delivery was a self-contained git bundle because the user's then-authorization to make the
  repository private could not be executed with the cloud session's GitHub tooling and
  pushing to a public repo was not authorized at that time. **Superseded later the same
  day:** the repository stays public by the user's explicit choice and the branches are
  pushed.

## Historical next-work note (superseded by current continuation above)

1. P4 local core/P5 offline adapter and P6 model-free installed entrypoint wiring are implemented.
   Actual Codex native Skill loading, ZCode Skill UI, shared default connection and one native Codex
   tool PTY reconnection now pass. Next is P7 preparation: model-free investigation of supported
   Codex turn ceiling/config provenance (`docs/CODEX_EXECUTOR.md`), host lifecycle constraints and
   concrete bounded real acceptance packets. Do not spend another model call to refresh a host.
   Live Codex is
   unavailable until capability gaps are resolved; new bounded authorization is also required.
   P4 references: `INTEGRATION_REPAIRS.md` and `CLEANUP.md` complete the
   existing candidate/check/review/delivery chain. Preserve all required inputs and original total
   checks when selecting a repair; every execution of a repair child counts against goal repairs.
   Cleanup intentionally retains dirty approved worktrees, caches, all refs/evidence and unknown
   lifetimes; never force cleanup, delete evidence or infer exit from an acknowledgement.
2. Interruption / timeout behaviour with a live executor (SIGTERM to the runner, wall
   timeout) — offline tests exist; live behaviour does not.
3. T5 evaluation per `docs/EVALUATION_PLAN.md` — the only place where "cheaper/better than
   direct Opus" can ever be answered.
4. Full backlog: `docs/BACKLOG.md`.

Any real call still needs explicit bounded authorization. The authorized two-attempt repair
budget was fully used and its live gate closed. Plugin development does not renew that budget.
Raw evidence locator: takeover chat `work/repair-resume-20261006/`, outside this repo.
Do not rerun prior suites/demos/smokes just because the operator or session changes.
Doctor now distinguishes historical project validation from current-host live readiness;
its live statuses intentionally stay unknown because diagnostics perform no inference.
