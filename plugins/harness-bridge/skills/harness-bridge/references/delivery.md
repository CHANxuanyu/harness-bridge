# Integration, local delivery and retention

All commands use the connection's absolute runtime/state; mutations include the current
`--advisor-binding BINDING --advisor-epoch N`. Neither a child approval nor a worker exit delivers
the goal. Inspect all required retained approvals, then freeze explicit dependency-respecting order:

```json
{
  "schema_version":"1.0",
  "task_ids":["TASK_A","TASK_B"],
  "verification":[{"id":"goal-acceptance","argv":["python3","/absolute/trusted/check_goal.py"],"cwd":".","timeout_seconds":120,"required":true,"trust":"external-acceptance"}]
}
```

Replace placeholders with all required task IDs and the agreed total-goal checks. These checks
must test combined behavior; child checks alone do not prove integration. Commands are trusted
local scripts, not an OS sandbox. Freeze before execution, never from Executor output.

```sh
hbridge --state-dir /absolute/state --json --advisor-binding BINDING --advisor-epoch 1 \
  goal integrate GOAL_ID --file integration.json --idempotency-key integration-1
hbridge --state-dir /absolute/state --json --advisor-binding BINDING --advisor-epoch 1 \
  integration materialize INTEGRATION_ID
hbridge --state-dir /absolute/state --json --advisor-binding BINDING --advisor-epoch 1 \
  integration verify INTEGRATION_ID --idempotency-key acceptance-1
hbridge --state-dir /absolute/state --json integration status INTEGRATION_ID
```

Materialization creates a separate owned workspace. A conflict records the last clean partial
commit; never manually edit that candidate and declare it approved. Verification is foreground,
bounded and project-exclusive. An unknown checker exit retains the hold; cancellation/recovery
does not prove success or permit another run. Same verification key returns its existing run.

Inspect the candidate code/diff from the fixed base and read `verification_run`, check logs,
`approval_blockers` and `review_template`. Copy the template exactly, add your decision/findings
and a fresh key, then submit `integration review INTEGRATION_ID --file integration-review.json`
with the current claim. Use `approval_current`, not historical `phase: APPROVED`. Takeover,
changed evidence/inputs or a new verification run invalidate earlier integrated approval.

## Integration repair

For a conflict or completed failed/rejected integration, plan one new child with empty `depends_on`
and `integration_repair: {"integration_id":"SOURCE_ID","reason":"Concrete repair needed"}`,
alongside its normal key/task definition. Submit that child alone with `goal plan`. Bridge binds
its baseline and original/pending inputs; do not choose a different starting folder. Materialize,
prepare as needed, dispatch and review using the ordinary workflow and remaining authorization.
Every execution of this child, including the first, consumes the shared repair budget.

Freeze a new integration with `repair_child_id` set to the approved repair child. Include every
goal task exactly once: the original ordered inputs are the exact prefix before the selected
repair; later normal children may follow. Copy the **exact original verification list**. Fresh
materialization/checks/review are required. Never drop a conflicting input or weaken acceptance.

## Local result branch

Once goal status is `READY_TO_DELIVER`, deliver to the agreed new local branch:

```sh
hbridge --state-dir /absolute/state --json --advisor-binding BINDING --advisor-epoch 1 \
  goal deliver GOAL_ID --integration INTEGRATION_ID --branch bridge/result \
  --idempotency-key delivery-1
hbridge --state-dir /absolute/state --json delivery status DELIVERY_ID
hbridge --state-dir /absolute/state --json goal status GOAL_ID
```

Require a confirmed receipt, matching refs and `DELIVERED`. Bridge creates the exact approved
commit/tree on a new branch; it does not switch or merge the source checkout, overwrite a branch,
push or open a PR. Report source/base divergence. Same-key replay recovers the existing intent;
it never resets a changed result branch. A pending unproved intent may be explicitly aborted with
`delivery abort DELIVERY_ID --reason TEXT` and the current claim; completed delivery cannot.

## Retention

`goal cleanup GOAL_ID` previews eligibility without deleting anything. Under explicit cleanup scope,
copy its exact `request_template` (or select a subset), then apply `goal cleanup GOAL_ID --file
cleanup.json --idempotency-key cleanup-1` with the current claim. Inspect `cleanup CLEANUP_ID`.
Only unchanged clean inactive owned worktrees are removable. Retain dirty worktrees, caches,
branches, refs, database and evidence. No force removal, guessed paths or unknown-exit bypass.

Return the local branch/commit and durable locator. A new feature after delivery starts a new goal;
do not reopen a completed delivery or infer remote publication.
