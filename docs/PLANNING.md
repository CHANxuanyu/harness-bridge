# Goal controls and child planning

Implemented 2026-10-06 on top of the [coordination contract](COORDINATION.md). All operations
use the same SQLite authority and Advisor fencing. No operation here launches a model.
Execution still requires an explicit, separately gated `run` after materialization.

## Goal controls

`goal control GOAL_ID --file control.json --idempotency-key KEY` accepts:

```json
{"action": "pause", "reason": "Review the remaining work before another dispatch"}
```

| Action | Effect | Advisor claim |
|---|---|---|
| `pause` | Block new attempt reservations; running attempts continue; planning, preparation and review remain available | Current binding/epoch |
| `resume` | Allow explicitly requested dispatch again; never starts work automatically | Current binding/epoch |
| `cancel` | Permanently prevent new work; atomically request cancellation of all active children and cancel unstarted work | Emergency local operation; claim not required |
| `fail` | Abandon the goal as failed, with the same stopping mechanics | Current binding/epoch |

`reason` is required and must be nonblank. With the exception of emergency cancellation,
pass the usual `--advisor-binding ID --advisor-epoch N` flags. Requests are idempotent:
same key/content returns its original receipt without applying it again; changed content with
the same key is rejected. Replaying an old pause after resume does not pause the goal again.
The CLI returns `request_receipt` separately from the current `goal` view.

Pause and cancellation are distinct. Cancellation/failure intent is irreversible, even while
an old process is still stopping. A repeated terminal request should reuse its original key;
a different terminal decision or resume is refused. All linked mutation paths check the
intent transactionally, including legacy task commands. Reads and emergency task cancellation
remain available. A new Advisor can take over for inspection/recovery without resurrecting work.

The owning foreground runner sees the durable cancellation flag and stops its process group.
The goal view cannot claim `CANCELLED`/`FAILED` until all materialized children are terminal
and every recorded attempt has confirmed exit. `NEEDS_ATTENTION`, `termination_requested`
and `pending_stop_tasks` describe an incomplete stop. Manually resolving an unknown attempt
as a failed/cancelled task does not prove process exit or release the goal's held slot.

During stopping, `recover` may record a dead runner as interrupted or explicitly resolve a
blocked/interrupted task as failed. It cannot retry execution or resume workspace/verification
work. Dead verification runners may leave a stop pending; there is no new orphan-proof or
unknown-slot-release mechanism in this milestone. These remain P3 lifecycle work.

## Immutable child plans

`goal plan` records a batch of named children before any execution task/workspace exists:

```bash
hbridge --state-dir /absolute/project-state --json goal plan GOAL_ID \
  --file plan.json --idempotency-key plan-1 \
  --advisor-binding BINDING_ID --advisor-epoch 1
```

Input shape:

```json
{
  "schema_version": "1.0",
  "children": [
    {"key": "implementation", "depends_on": [], "task": "TASK_DEFINITION_OBJECT"},
    {"key": "followup", "depends_on": ["implementation"], "task": "TASK_DEFINITION_OBJECT"}
  ]
}
```

The strings above stand for actual objects; [examples/plan.example.json](../examples/plan.example.json)
contains valid input. Each `task` has the existing task fields **except** `repo` and
`schema_version`: goal, requirements, allowed/forbidden paths, verification, limits, executor.
The shared `TaskDefinition` validators enforce the same path, verifier and executor constraints.
Repository/base are assigned during materialization; they are not caller-selected template fields.

Each batch has 1–100 children. Keys match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` and are unique
within a goal. Dependencies name children in the same batch or an earlier batch of the same
goal. Duplicate dependencies, missing/foreign references, self-dependencies and cycles are
rejected atomically, leaving no partial plan/event/workspace. A later batch can extend the DAG,
but cannot overwrite an existing child or its dependencies. Amendment/deletion is not exposed.

Plans are stored with immutable request digests; dependency links are checked against those
plans. Batch replay returns the original child IDs. Changing a request under the same key
fails; takeover requires the new Advisor claim even when replaying an earlier batch.

## Explicit materialization

```bash
hbridge --state-dir /absolute/project-state --json child status CHILD_ID
hbridge --state-dir /absolute/project-state --json child materialize CHILD_ID \
  --advisor-binding BINDING_ID --advisor-epoch 1
```

| Plan facts | View and permitted action |
|---|---|
| No dependencies, not materialized | `READY_TO_MATERIALIZE`; explicit materialization permitted |
| At least one dependency is not an approved task | `WAITING_DEPENDENCIES`; no workspace/task creation |
| Dependencies approved, but preserved dependency baseline unavailable | `WAITING_BASELINE`; refused, not silently replaced by original HEAD |
| Approved inputs available | `READY_TO_MATERIALIZE`; fixed composition precedes task creation |
| Conflicting approved inputs | `BASELINE_CONFLICT`; no task/worktree, goal needs attention |
| Materialized | Actual execution-task state and `task_id`; querying creates nothing |
| Unmaterialized and goal termination requested | `CANCELLED`; no task or workspace created |

Independent roots freeze TaskSpec 1.0 against the goal's original pinned SHA. Successors
freeze against the composed approved dependency baseline described in
[EXECUTION_CONTEXT.md](EXECUTION_CONTEXT.md). Materialization attaches the child/task relationship
and task-created event in one transaction, then prepares the existing owned worktree. The original checkout must still
be clean. Per-task limits and goal aggregate limits both apply to later attempts.

Competing requests get one execution task and one owned workspace. Materialization uses a
stable internal key per child; an unrelated task with a colliding key cannot be adopted.
A crash after the task/link commit leaves that same task in `CREATED`; replay returns it,
and the existing explicit `recover` finishes preparation. It does not create another task or
start an executor. If goal cancellation races with accepted workspace preparation, the result
stays cancelled and any successfully created workspace remains recorded under that task.

The P2 first slice preserves approved dependency snapshots, composes fixed baselines and
checks workspace readiness before successors run. `WAITING_BASELINE` now means an older approval
has no retained snapshot; `BASELINE_CONFLICT` records a failed composition. Controlled setup
commands remain pending. Do not create a substitute standalone task to bypass dependency checks.

## Goal state projection

| Facts/decision | Goal state |
|---|---|
| No plans or tasks | `DRAFT` |
| Work registered, no attention condition | `ACTIVE` |
| Child awaiting review, blocked, interrupted, failed or cancelled; or dependency baseline unavailable/conflicting | `NEEDS_ATTENTION` |
| Cancel/fail requested, a task remains nonterminal or any attempt exit is unknown | `NEEDS_ATTENTION` with pending stop IDs |
| Cancel requested, stopping fully confirmed | `CANCELLED` |
| Fail requested, stopping fully confirmed | `FAILED` |

`dispatch_paused` is independent of the projected state. All children approved still does
not imply integrated success: `READY_TO_DELIVER` and `DELIVERED` require P4's future integration
and exact-delivery gates. No command can set those states directly.

## Storage and evidence

Revision 3 added goal control receipts, child plans/dependency edges and batch receipts. Both
v1→v3 and v2→v3 run under one writer transaction after a WAL-consistent backup; a failure in
the final migration rolls back every stage. Existing v2 goals/bindings/tasks remain identical.
Backup files are owner-readable/writable from creation. No live/user state directory was used
for validation. Recovery guidance remains in [COORDINATION.md](COORDINATION.md).

Revision 4 adds the retained snapshot/baseline records; see the execution context reference.

Evidence: `tests/integration/test_goal_planning.py`, the prior coordination suite, and
`tests/unit/test_migrations.py`. These are offline simulated executors with real subprocesses,
Git workspaces and SQLite transactions; no new native-harness or host-teardown claim is made.
