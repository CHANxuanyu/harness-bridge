# Handoff

## Current state (2026-10-06, P5 Codex offline adapter)

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
  P1–P4 local cores and P5 offline adapter are implemented; Codex live readiness and P6–P7 remain pending. Advisor is
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
- **New local plugin alpha:** `plugins/harness-bridge/` has portable, Codex and ZCode
  manifests plus one self-contained supervisor Skill. Codex catalog lives under
  `.agents/plugins/marketplace.json`; ZCode catalog is root `marketplace.json`.
  Package/copy/CLI-contract checks and Codex catalog discovery passed. Temporary catalog
  registration was removed; no plugin installed or real model called. Installed activation,
  ZCode loading, automatic task discovery, worker persistence and delivery remain unverified
  or unimplemented as detailed in `docs/PLUGIN_ALPHA_RESULT.md` and product definition.

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

## Next bounded work

1. P4 local core and P5 Codex offline adapter are implemented. Next bounded work is
   model-free investigation of a supported Codex turn ceiling/config provenance, and P6 Advisor
   entrypoint wiring against goals/children/workers (`docs/CODEX_EXECUTOR.md`). Live Codex is
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
