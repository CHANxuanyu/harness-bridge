# Goal and Advisor coordination — P1 local core

Implemented 2026-10-06 on the existing foreground runtime. P1 local coordination now includes
goal controls and unmaterialized child plans; see [PLANNING.md](PLANNING.md). This is not the complete V1 product. No additional model or scheduler was introduced.
The implementation is `coordination.py`, used by the CLI and the existing `Bridge` service.

## What works

- Register a Git project and a goal with a fixed base SHA, a named Advisor session and bounded
  aggregate attempts/repairs. Registration lives in the explicitly selected state directory.
- Link independent child tasks to that goal. Each still owns its existing isolated worktree,
  frozen TaskSpec, attempt history, executor-session binding and evidence.
- Explicitly take over with another existing Advisor session. New binding ID and increasing
  epoch fence the old session, including through the original task CLI commands.
- Read project/goal/task ownership from another CLI process without starting an executor.
- Enforce aggregate budgets and the project execution cap in the attempt transaction.
  Default 1, explicitly configured up to 2; different goals in the project/state share the cap.
  Scope checks and total wall-time/turn reservations are in [CONCURRENCY.md](CONCURRENCY.md).
- Preserve legacy standalone tasks and their original behavior; no invented parent records.

## GoalSpec 1.0

`goal create --file` accepts JSON with these fields; unknown fields are rejected.

| Field | Contract |
|---|---|
| `schema_version` | `"1.0"` |
| `objective` | 1–20000 characters |
| `repo` | existing RepoSpec: absolute top-level path, clean committed Git repo, base ref |
| `advisor` | `{host, native_session_ref?}`; native session reference may be null |
| `constraints` | optional list of nonblank instruction summaries |
| `acceptance` | required nonempty list of nonblank goal acceptance summaries |
| `max_attempts` | integer 1–100, default 3, across all children/retries/repairs |
| `max_repairs` | integer 0–100, default 1, subset of attempts |
| `max_executor_wall_seconds` | optional positive finite total reserved executor-seconds ceiling, ≤ 8,640,000 |
| `max_executor_turns` | optional integer 1–50,000, total requested-turn reservation ceiling |
| `allowed_executors` | nonempty subset of `fake`, `claude-code`, `codex`, `zcode`; default `["fake"]`; ZCode offline-only, native Claude/Codex remain gated |

Goal acceptance/constraint summaries are frozen planning metadata. They are not executable
integrated verification, an automatic policy compiler, or a claim that acceptance passed.
Each child's TaskSpec must still provide its own executable checks and path scope. Goal creation
does not enable live mode; the existing per-dispatch live gate remains independently required.

See `examples/goal.json` for the input shape. Change its placeholder repo path before use.

```bash
hbridge --state-dir /absolute/project-state --json goal create \
  --file goal.json --idempotency-key goal-1
hbridge --state-dir /absolute/project-state --json projects
hbridge --state-dir /absolute/project-state --json goal status GOAL_ID
```

The create receipt includes `goal_id`, `project_id`, `base_sha` and
`advisor_claim: {binding_id, epoch}`. For a child, set `task.json`'s `repo.base_ref` to that
fixed SHA. A moving ref is accepted only if it still resolves to the exact pinned SHA.
Another repo/base/executor is rejected before any child workspace is created.

```bash
hbridge --state-dir /absolute/project-state --json create \
  --goal GOAL_ID --task task.json --idempotency-key child-1 \
  --advisor-binding BINDING_ID --advisor-epoch 1
hbridge --state-dir /absolute/project-state --json run TASK_ID --mode mock \
  --advisor-binding BINDING_ID --advisor-epoch 1
hbridge --state-dir /absolute/project-state --json artifacts TASK_ID
hbridge --state-dir /absolute/project-state --json review TASK_ID --file review.json \
  --advisor-binding BINDING_ID --advisor-epoch 1
```

The Advisor calls these commands in its own session. This reference is not a requirement for
the human user to shuttle prompts or receipts. Plugin installation/discovery wiring is P6.

## Takeover and stale writers

A takeover request contains `advisor`, `expected_epoch` (integer ≥1), and a nonempty `reason`:

```json
{
  "advisor": {"host": "zcode", "native_session_ref": "existing-session-reference"},
  "expected_epoch": 1,
  "reason": "Continue the same goal in this existing agent session"
}
```

```bash
hbridge --state-dir /absolute/project-state --json goal takeover GOAL_ID \
  --file takeover.json --idempotency-key takeover-1
```

Takeover requires an explicit expected epoch, not a responsive old Advisor. Two takeovers
of the same epoch cannot both win. The receipt supplies a new binding at epoch 2; new task
operations must carry it. Merely reading goal status does not take over or refresh a binding.

For linked tasks, `create`, `run`, `review`, `verify`, and `recover` check ownership before
preparation and again inside the mutation transaction. Missing claims yield `ADVISOR_REQUIRED`;
old/wrong-goal claims yield `STALE_ADVISOR` (exit 3). Reads and emergency `cancel` remain available.

Once an attempt or verification operation was transactionally accepted, its observations may
finish after takeover. Revoking the old Advisor must not discard the already-running attempt's
result or spawn it again. Further planning/review/dispatch by the old Advisor is rejected.
This is logical ownership between cooperating local sessions, not authentication or isolation
against another same-user process. Host/session references are declared metadata.

Create and takeover keys bind to their normalized request. Same key/content returns the
original receipt; conflicting content is rejected. Replaying an old create/takeover never
silently upgrades its claim to the current epoch. Task creation replay cannot move a child
to another goal, detach it, or attach a historical standalone task.

## Budgets, state and evidence

All goal attempts count once at reservation, including retry and unknown-exit attempts;
repairs also count against the repair ceiling. Only a confirmed `spawn_failed` outcome refunds
the goal reservation. Existing per-task attempt ceilings remain conservative and unchanged.
Goal exhaustion leaves a READY task unlaunched and returns `BUDGET_EXHAUSTED`.

One project slot is the default. Explicit local configuration permits two, subject to disjoint
scope checks. Running/starting/verifying tasks and unconfirmed exits hold capacity, including after
manual cancellation or resolution. Unknown reservations have no release mechanism yet; do not
edit the database to bypass them. Preparation remains project-exclusive. Managed workers and
durable dispatch keys are in [WORKERS.md](WORKERS.md); scope checks, optional total time/turn
ceilings and their conservative accounting are in [CONCURRENCY.md](CONCURRENCY.md).
Limits apply within one state root; this is not a cross-installation quota broker.

Goal status combines child facts, integrated readiness and durable delivery receipts:

| Child facts | Goal view |
|---|---|
| No child plan or task | `DRAFT` |
| Any awaiting review, blocked, interrupted, failed or cancelled child | `NEEDS_ATTENTION` |
| Otherwise, including all children approved but without integrated approval | `ACTIVE` |
| Latest integration has current exact approval and project is idle | `READY_TO_DELIVER` |
| Completed delivery has intact retained bindings and matching refs | `DELIVERED` |
| Delivery pending, changed, or integrated approval stale | `NEEDS_ATTENTION` |
| Cancel/fail requested, stop pending | `NEEDS_ATTENTION` |
| Cancel/fail requested, all tasks terminal and attempt exits confirmed | `CANCELLED` / `FAILED` |

`delivery` is now a structured readiness/receipt view; valid current integrated approval projects
`READY_TO_DELIVER`, and confirmed exact branch publication projects `DELIVERED`. See [DELIVERY.md](DELIVERY.md).
Child `SUCCEEDED` does not mean integrated goal success. Goal controls and confirmed-stop terminal states are now available; the complete state table
and child-plan views are in [PLANNING.md](PLANNING.md). Integrated approval/delivery gates are now implemented within the partial P4 scope. Recent goal events
include sequence, epoch and associated task IDs; the view is limited to 50 events. Incremental
task cursor/wait APIs are now implemented in `events`; goal-wide incremental streams remain
pending. Existing task events/manifests retain detailed evidence.

## Storage upgrade (original P1 slice; current upgrades in [DELIVERY.md](DELIVERY.md))

SQLite schema revisions 1 and 2 now upgrade additively to 3. Before DDL, while holding the writer lock,
SQLite's backup API saves committed data including WAL to `backups/pre-v3-<id>.sqlite3`
with mode 0600. New tables and revision change commit atomically. Backup failure aborts the
upgrade; a migration exception rolls it back. Unsupported revisions fail closed. Reopening v3
does not recreate tables or another backup. TaskSpec/ReviewDecision remain schema 1.0.

For rollback, stop all bridge processes and preserve the entire state directory first. Restore
the pre-upgrade backup to a separate recovery directory as `bridge.sqlite3` and use the matching older
runtime. Inspect records before choosing a replacement state root. A database backup does not
copy external worktrees/artifacts/config; retain their original paths and files. Do not overwrite
a live database or mix a restored database with another database's WAL/SHM sidecars. Changes made
after the backup are not present in it.

## P1/P2 boundary

P1 local coordination now includes goal controls, immutable child plans and validated dependency
DAGs. Independent roots can be explicitly materialized; dependency execution waits for P2's
preserved approved baselines. Environment preparation, installed-host discovery, background
workers and integrated delivery remain later milestones. See [PLANNING.md](PLANNING.md).
No placeholder CLI claims those features work.

Offline evidence is in `tests/integration/test_coordination.py`,
`tests/integration/test_goal_planning.py` and
`tests/unit/test_migrations.py`; results are recorded in `VALIDATION_MATRIX.md`.

The first P4 slice adds `goal integrate` and `integration materialize/status`; see
[INTEGRATION.md](INTEGRATION.md). Goal status includes frozen integration records. Subsequent
[verification/review](INTEGRATION_CHECKS.md) and [local delivery](DELIVERY.md) slices add exact
integrated acceptance and explicit branch publication. A candidate or successful child does not
imply goal delivery. Pending/completed delivery intents fence further goal mutations; status and
Advisor takeover remain available, and only an unproved pending intent may be explicitly aborted.
