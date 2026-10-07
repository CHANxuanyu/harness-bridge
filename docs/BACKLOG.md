# Backlog

The canonical scope is `docs/PROJECT_PLAN.md` (P0–P7, V01–V15), extended by `docs/ROUTING_PROFILE.md` for P8.
This file indexes remaining work; it does not maintain a competing implementation plan.

## Current next work — P8 user-selected route

Codex Astra is the Advisor; Claude Code Opus 5.5 handles difficult work and ZCode GLM 5.3 Flash
handles bounded simple work. P7 is accepted for its existing scope and source113b0a7 was pushed.
P8.0 route/discovery is documented. P8.1 has a model-free native capability probe; P8.2 has an
**offline ZCode protocol adapter**, including same-session repair, managed cancellation and
existing independent review. [ZCODE_EXECUTOR.md](ZCODE_EXECUTOR.md) separates this evidence from
native support. Next qualify account/permission metadata and native session semantics, add
Advisor routing/escalation templates, then prepare newly authorized bounded real acceptance
of the exact three-model route. Native ZCode dispatch remains closed. Do not spend the P7 allowance.

Current continuation: native blank-session probes found the initialization-preference callback,
plan/build mismatch and unavailable empty-session resume. Offline profile revision2 handles the
bound initialization and explicit Start Plan choices; source plugin alpha.7 supplies the selected
route templates. Installed alpha.6 remains unchanged. Before claiming explicit failure escalation,
implement reviewed partial-work transfer/task supersession: today's integration requires every
child approved, so an unapproved failed child cannot simply be replaced or omitted.

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
5. **P5 — Codex adapter and gated native route implemented.** New explicit null-turn tasks use
   attempts/wall/cancel budgeting; native subscription/config preflight and strict worker
   reconstruction exist. Real initial diagnosis and native same-session repair passed.
   Old numeric-turn tasks are unchanged. See `CODEX_EXECUTOR.md` and `P7_RESULT.md`.
6. **P6 — Advisor entrypoints accepted for model-free wiring.** Alpha.3 installed in both actual
   hosts with shared connection/native skill discovery. Native ZCode full quit/relaunch with a
   fake worker passes; Codex full GUI shutdown remains unverified. Installed native lifecycle
   and independent runtime retention checks pass. See `LOCAL_RELEASE.md`.
7. **P7 — Real collaboration delivered; lifecycle acceptance incomplete.** Claude/Codex parallel
   work, exact-session Codex repair, combined external review and exact local delivery passed.
   Codex cancellation failed its secondary OS audit: a detached tool survived. Runner tracking
   is corrected with offline regression; native retest and the unused Claude turn-limit case
   remain open. Claude timeout fired at 15s with the test tool started. Apache-2.0/local-only
   scope is resolved; the candidate is not fully accepted.

Six actual executions / 825 reserved seconds are spent. Prepared remaining proposal: Codex
cancellation retest plus Claude turn-limit, 2 executions / 150 seconds, making total ceilings
8 / 975. The additional Codex execution and resume need explicit authorization. Do not repeat
successful collaboration, resume, integration, installation or host tests. No billing/push is authorized.

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

- Expose an obvious child-session locator/history view in the Advisor experience; native CLI
  transcripts and desktop chat-list visibility are different surfaces.
