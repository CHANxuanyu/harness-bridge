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
2. **P2 — Execution context (next).** Preserve exact approved dependency snapshots, form fixed
   dependency baselines, then materialize successors and prepare their environments/context.
   DAG validation and root materialization already exist; `WAITING_BASELINE` must not be
   bypassed by substituting the original goal SHA or creating a standalone task.
3. **P3 — Managed worker and aggregate limits.** Bounded concurrent attempts, goal budgets,
   reservations held for unknown exits, incremental events, cancel/recover and host teardown.
   Validate the actual macOS worker lifecycle before claiming detached operation.
4. **P4 — Integration / delivery.** Immutable approved snapshots, conflict handling, integrated
   goal verification, exact local delivery branch, idempotent receipts and ownership-safe cleanup.
5. **P5 — Codex executor adapter.** Stub/contract evidence first; capability-specific live
   validation only under new bounded authorization. ZCode executor remains exploratory.
6. **P6 — Advisor host entrypoints.** Install/activate Codex and ZCode packages, stable project
   discovery, task operations and session continuation. Loading a plugin is not full behavior.
7. **P7 — Live product acceptance / distribution.** One Advisor session and two executor harnesses,
   integrated delivery, live limits/interruption evidence, clean setup/update/uninstall,
   license and explicit publication scope. Keep unknown capabilities visibly unknown.

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
