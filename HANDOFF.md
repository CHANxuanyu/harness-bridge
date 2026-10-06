# Handoff

## Current state (2026-10-06, P1 local coordination complete)

- **Canonical plan:** `docs/PROJECT_PLAN.md` consolidates the product, session relationships,
  contracts, V1 scope defaults, P0–P7 milestones and V01–V14 acceptance. P0 is complete;
  P1 local coordination is implemented and offline-validated; P2–P7 are pending. Advisor is
  explicitly an existing agent session; Bridge does not create its own planning model. `PRODUCT_FORM.md` is now a short summary, and the
  original cloud execution plan is clearly historical, not renewed authorization.
- Key plan choices: dependencies are fixed before child execution-task/worktree materialization;
  task mutations cannot bypass goal budgets or the active Advisor epoch through old CLI paths;
  unknown exits retain reservations/slots; V1 targets managed workers and exact local-branch
  delivery with integrated acceptance. Epoch and initial aggregate guards now exist;
  managed workers/integration/delivery remain proposed runtime behavior.

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
- **Migration:** schema revision 1/2→3, additive tables only, WAL-aware backup before migration,
  atomic rollback and concurrent-upgrade tests. No actual live/user state directory was opened
  for migration in this implementation round. Keep backups/artifacts/worktrees for recovery.
- **Checks:** latest `scripts/check.sh` passed **249 tests**, ruff/format and mypy clean on
  macOS (85.27 seconds). 26 new planning/control/migration cases since the previous 223-test
  milestone; affected 55-case checks also passed. Current contracts: `docs/COORDINATION.md`
  and `docs/PLANNING.md`. P1 local core is complete. Dependent tasks deliberately report
  `WAITING_BASELINE` after approval until P2 preserves/composes exact baselines. Environment,
  P3 workers, P4 delivery and P6 installed-host discovery remain unfinished.

- **Latest user clarification:** target developers who already use several coding-agent
  subscriptions, such as ZCode/GLM, Claude Code and Codex. This is not a Codex-only product.
  `docs/PRODUCT_FORM.md` defines the intended experience: one independent local runtime,
  multiple host entrypoints, shared evidence, explicit delivery back to the project.
- **Subsequent explicit product correction:** one Advisor + one or more Executors, equivalent
  to a main agent with cross-harness subagents. Advisor inspects the repo and dispatches/reviews;
  Bridge creates per-child workspaces and launches the executor with the assigned cwd.
  Treat plugins as entrypoints to that relationship. Parent/child coordination, dependency
  baselines and integration remain product priorities; goal/child links and initial aggregate
  attempt/repair guards are now code, while dependency plans and integration are not.
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
  the new P1 completion milestone are
  local, not auto-pushed. Remote was not re-queried during this offline implementation round;
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

1. Continue P2 from `docs/PROJECT_PLAN.md`: preserve approved snapshots as reproducible
   dependency baselines, compose multiple dependency results, then materialize successors and
   prepare environments/context. Reuse `planning.py` and existing ownership/stop/budget guards.
   A complete 249-test offline regression passed for this shared-core change; no live budget
   is renewed. Do not rerun past smokes or replan the product merely for handoff.
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
