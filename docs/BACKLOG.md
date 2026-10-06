# Backlog

The canonical scope and acceptance sequence is `docs/PROJECT_PLAN.md` (P0–P7, V01–V14).
This file indexes remaining work; it does not maintain a competing implementation plan.

## Completed baseline — reuse, do not redo for handoff

- V0.1 task/review contracts, store, worktrees, runner, verifier and recovery foundation.
- Linux/macOS offline validation, recorded full 192-test result, later affected checks.
- T3/T4 initial smokes and one controlled live repair/resume; captured-redacted stream fixtures.
- Codex/ZCode plugin package alpha; package/contract checks and Codex catalog discovery.
- P0 unified plan: both Advisor and Executor are agent sessions; one Advisor can coordinate
  multiple child sessions across harnesses. The plan is not runtime implementation.

Evidence: `docs/VALIDATION_MATRIX.md`, `docs/LIVE_REPAIR_RESULT.md`, `docs/PLUGIN_ALPHA_RESULT.md`.

## Product work, in dependency order

1. **P1 — Goal/session coordination (local core complete).** Goal/child ownership, current
   Advisor fencing, control/confirmed-stop states, immutable child plans/DAGs, root task
   materialization, project registration within explicit state and backed-up migration.
   Installed-host discovery wiring remains P6; references: `COORDINATION.md`, `PLANNING.md`.
2. **P2 — Execution context (local core implemented).** Fixed approved baselines, successor
   workspaces/context, presence checks and explicit bounded preparation with cancellation,
   crash recovery, candidate binding, output/cache inventory and state-wide resource claims.
   References: `EXECUTION_CONTEXT.md`, `PREPARATION.md`. No persistent service management or
   automatic resource discovery; unknown exits remain reserved until future audited resolution.
3. **P3 — Managed worker and aggregate limits (local core implemented).** Durable workers,
   events/wait, cancel/recover, explicit two-slot project admission, scope guards and cumulative
   executor-ceiling reservations; see `WORKERS.md`, `CONCURRENCY.md`. Simulated host-session
   exit is tested; actual installed desktop-host survival and real harness limits remain later
   acceptance, not a promise of universal background operation.
4. **P4 — Integration / delivery (local core complete).** Frozen input/order/check
   records, owned candidates and conflict partial refs (`INTEGRATION.md`), durable total-goal
   checking/cancel/recovery and exact current-Advisor review (`INTEGRATION_CHECKS.md`) exist.
   Exact local delivery/receipts and READY_TO_DELIVER/DELIVERED projections now exist (`DELIVERY.md`).
   Budgeted repair-child binding and conservative post-delivery cleanup now exist
   (`INTEGRATION_REPAIRS.md`, `CLEANUP.md`); dirty worktrees and all refs/evidence remain retained.
5. **P5 — Codex executor adapter (offline core implemented).** Native contract and foreground/
   worker stub repair now exist (`CODEX_EXECUTOR.md`). Live is unavailable until internal turn
   enforcement, subscription/config provenance and native recovery gaps have evidence; any
   real validation also requires new bounded authorization. ZCode executor remains exploratory.
6. **P6 — Advisor host entrypoints (model-free wiring accepted).** Alpha.2 workflow and prior 24
   package/CLI checks pass; actual Codex profile install/native Skill loader and ZCode install/Skill
   UI pass. Both actual caches share a default connection; native Codex tool PTY exit/reconnection
   passes (`P6_DESKTOP_ACCEPTANCE.md`). Current GUI hot refresh and full app quit are unobserved;
   loading is not full real agent behavior.
7. **P7 — Live product acceptance / distribution.** One Advisor session and two executor harnesses,
   integrated delivery, live limits/interruption evidence, clean setup/update/uninstall,
   license and explicit publication scope. Keep unknown capabilities visibly unknown.
   Preparation now includes a reproducible two-adapter offline rehearsal, 8 new checks and a
   bounded future acceptance packet (`P7_ACCEPTANCE.md`); all pass without models. Native Codex
   capability gaps, new per-run authorization and the actual live/distribution cases remain open.

Any real call needs explicit bounded authorization; the earlier two-attempt repair allowance
is fully used. The plan does not grant calls, push, publication or billing changes.

## Subsequent / optional work

- T5 comparative evaluation (`docs/EVALUATION_PLAN.md`): only evidence can support quality,
  time or cost comparisons. Requires separate authorization for actual model calls.
- Versioned task amendment with explicit re-review rules; do not alter frozen requirements
  or move an active task's baseline in place.
- Other executor harnesses, operating systems, remote execution and team coordination after
  relevant interfaces and supported routes are established.
- Optional observation of ignored files as a risk signal, stronger Linux orphan tracking.
- Explicit manual takeover of an executor's writable directory, after confirmed executor exit;
  distinct from an Advisor session taking over goal management while a worker is still active.
