# Status

_Latest: P7 reproducible two-adapter rehearsal and capability audit; live acceptance remains open._

## Current state

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
