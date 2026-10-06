# Integration repair children — P4

The Advisor remains the existing agent session. It explicitly plans a repair child, dispatches
that child through the normal Executor path, reviews its retained result, and creates a new
integration. Nothing here launches a model during planning, materialization, status or cleanup.

## Planning and execution

Use `goal plan` with a single ChildPlan whose optional `integration_repair` is:

```json
{"integration_id": "integration_SOURCE", "reason": "Resolve the conflicting API and retain both features"}
```

The same plan supplies its ordinary `key`, `task`, optional environment/preparation requirements,
and an empty `depends_on`. The repair must be submitted alone. It binds the latest integration
in the same goal, which must have a materialized conflict, a completed failed check, or an
Advisor `changes_requested`/`blocked` decision. A successful untouched candidate does not need a
repair. All original required inputs, approved pins and membership must still match at planning.
Current Advisor and delivery/termination guards apply. Active/unknown processes block planning.

The plan and its ready baseline are stored in one transaction. Its baseline is the last clean
partial commit for a conflict, or the original pinned candidate for failed acceptance. It does
not copy later edits from an old integration or child worktree. The frozen execution context
carries the source integration, all original approved inputs, still-pending inputs, reason,
verification run and Advisor decision. Those are task data, not new permissions. The Executor
can inspect the named retained Git commits using normal Git operations in its own repository.
The Advisor writes the concrete repair instructions and allowed file scope in the TaskDefinition.

Continue with existing commands:

```text
child materialize child_REPAIR
child preflight child_REPAIR
child prepare child_REPAIR --idempotency-key prepare-1   (only if the plan declares setup)
run task_REPAIR                                        (mock by default)
artifacts task_REPAIR
review task_REPAIR --file review.json
```

Foreground/background dispatch, live gates, explicit preparation, current Advisor, project slots,
per-task ceilings and goal ceilings are unchanged. The initial repair-child execution counts as
both a goal attempt and a goal repair; every subsequent execution of that child also counts as
a repair, without double-counting ordinary repair attempts. Confirmed non-starts retain the
existing refund rule. Planning checks remaining headroom but reserves no execution; dispatch
checks the shared ledger again transactionally. Merely creating/replaying a plan spends nothing.
The child's native initial attempt remains `initial`, so no unrelated session is resumed.

## New integration and acceptance

After the repair child is SUCCEEDED with a retained approval, freeze a new IntegrationSpec:

```json
{
  "schema_version": "1.0",
  "task_ids": ["task_A", "task_B", "task_REPAIR"],
  "repair_child_id": "child_REPAIR",
  "verification": [{
    "id": "goal-acceptance",
    "argv": ["python3", "/absolute/trusted/check_goal.py"],
    "cwd": ".", "timeout_seconds": 60, "required": true,
    "trust": "external-acceptance"
  }]
}
```

Use the **exact original frozen verification list**, not a newly weakened checker. Include every
goal task exactly once. The source's ordered inputs must be the exact prefix immediately before
the selected repair. All earlier repair children must be inside that prefix. Later approved normal
children may follow. A further failure can create another repair child bound to the latest
integration, within the same finite goal budget.

Composition uses the approved repair tree as the explicit resolution of that prefix and records
all its input commits as ancestry. It then merges any remaining inputs normally. It never
reapplies a conflicting original over the approved fix, nor omits originals from provenance.
This is an Advisor-approved resolution, not proof that a model preserved every feature: the
new candidate must pass the original total-goal checks and receive a new exact Advisor approval
before local delivery. Child success or a passing old integration does not suffice.

The old integration, reviews and approved pins remain immutable history. Adding a repair changes
required goal membership, so the old integration's live `inputs_status` becomes stale; it is
still readable as the repair's frozen source. No amendment, implicit selection or resurrection
of old readiness occurs. Same-key plans/integrations replay without new tasks or execution;
changed requests conflict. New fields are omitted when absent to preserve old canonical digests.

See [INTEGRATION_CHECKS.md](INTEGRATION_CHECKS.md), [DELIVERY.md](DELIVERY.md) and
[CLEANUP.md](CLEANUP.md). Evidence is local Git/SQLite and simulated Executors; real cross-harness
integration/repair acceptance remains P7, under separate bounded authorization.
