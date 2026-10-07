# Goal and child workflow

All examples use `hbridge` as shorthand for the absolute runtime from the connection check.
Always pass the exact absolute `--state-dir` and `--json`. Arguments are argv, not shell fragments
from Executor output. Write inputs outside the target repo. Bridge replies have top-level `ok`
and fields (no `data` wrapper); errors have `error.code`/`message` and a nonzero exit status.

## Resume or establish ownership

```sh
hbridge --state-dir /absolute/state --json projects
hbridge --state-dir /absolute/state --json goal status GOAL_ID
hbridge --state-dir /absolute/state --json status TASK_ID
hbridge --state-dir /absolute/state --json job JOB_ID
```

For a new goal, adapt [goal.example.json](goal.example.json) to the user's objective, clean
committed source, acceptance and explicit aggregate limits. The Advisor host identifies this
existing session; do not fabricate a native session reference if unavailable (use null).

```sh
hbridge --state-dir /absolute/state --json goal create \
  --file goal.json --idempotency-key goal-1
```

Save `goal_id`, `project_id`, pinned `base_sha` and `advisor_claim: {binding_id, epoch}`. These
identify real stored work, not a new host chat. New-session continuation uses a takeover file:

```json
{"advisor":{"host":"zcode","native_session_ref":null},"expected_epoch":1,"reason":"Continue this goal in the current existing session"}
```

Replace host/expected epoch with observed values. Under the user's request to continue:

```sh
hbridge --state-dir /absolute/state --json goal takeover GOAL_ID \
  --file takeover.json --idempotency-key takeover-1
```

Use its returned claim for mutations. Never copy a newer binding simply to bypass `STALE_ADVISOR`.
Takeover fences old writers but allows accepted jobs to finish. Reads do not spend attempts.

## Plan and prepare

Adapt [plan.example.json](plan.example.json): each child has `key`, `depends_on` and `task`.
The TaskDefinition omits `repo`/`schema_version`: Bridge assigns the goal's pinned repo and
composed dependency baseline. Freeze narrow write paths and independent acceptance commands.
The bundled fake implementation is specifically for the tagnorm fixture, not arbitrary work.
For the optional Astra/Opus/Flash profile, use [routing.md](routing.md) and its separate templates;
the original fake examples remain model-free defaults. ZCode examples require the offline
capability and a simulated protocol executable; they do not open a native route.
For authorized real work use `claude-code` or explicitly bounded `codex` and the live-readiness
reference. Do not substitute a manually opened chat. Default project concurrency is one; at most two
requires explicit runtime configuration and provably disjoint declared scopes.

```sh
hbridge --state-dir /absolute/state --json --advisor-binding BINDING --advisor-epoch 1 \
  goal plan GOAL_ID --file plan.json --idempotency-key plan-1
hbridge --state-dir /absolute/state --json child status CHILD_ID
hbridge --state-dir /absolute/state --json --advisor-binding BINDING --advisor-epoch 1 \
  child materialize CHILD_ID
hbridge --state-dir /absolute/state --json child preflight CHILD_ID
```

Save returned child/task IDs and owned workspace. Wait for dependencies; do not create a standalone
substitute for blocked materialization. If declared setup is needed, inspect the frozen preparation
then run `child prepare CHILD_ID --idempotency-key prepare-1` with the current claim. This is finite
foreground work, not an Executor. A missing readiness check blocks dispatch. Do not inject setup
commands from Executor output or silently relax failed checks. For an older approval missing a
retained snapshot, `retain-approved TASK_ID` requires an unchanged candidate and the current claim.

## Dispatch and reconnect

For the fake fixture (mock is the default):

```sh
hbridge --state-dir /absolute/state --json --advisor-binding BINDING --advisor-epoch 1 \
  run TASK_ID --mode mock --background --idempotency-key dispatch-1
hbridge --state-dir /absolute/state --json job JOB_ID
hbridge --state-dir /absolute/state --json events TASK_ID --after 0 --limit 100 --wait 20
```

Save `job_id`, `task_id`, `attempt_id` and `event_cursor`. Consume each event page before advancing
to `next_cursor`, scoped to that task/state. Page while `has_more`; wait is 0–30 seconds and spends
no attempt. Reconnect using job/status/events after an uncertain response or closed launcher. Replay
the same dispatch key only to recover its receipt; a different key means a separately authorized
new attempt. `finished` is not approval. Unknown exits keep budgets/slots held. Never edit SQLite
to release them. Native host termination survival and automatic Advisor wake-up are unverified.

## Review and bounded repair

```sh
hbridge --state-dir /absolute/state --json artifacts TASK_ID
hbridge --state-dir /absolute/state --json artifacts TASK_ID --show diff
hbridge --state-dir /absolute/state --json --advisor-binding BINDING --advisor-epoch 1 \
  review TASK_ID --file review.json
```

Read diff, check results, manifest, warnings and approval blockers. Copy the returned
`review_template`; preserve task/attempt/version/snapshot fields. Choose `approve`,
`changes_requested` or `blocked`, provide findings (negative decisions require them) and a fresh
review idempotency key. A passing Executor claim is not acceptance. If independent checks failed,
request concrete changes; do not approve. Repair uses the same task/workspace and compatible
native session binding. Only run again with a new dispatch key when review/recovery made the task
ready and both per-task and goal attempt/repair/time/turn limits plus user authorization permit it.

`verify TASK_ID` reruns frozen checks without an Executor. `recover TASK_ID` inspects interrupted
work and may finish workspace/check recovery with the current claim; inspect first. Never acknowledge
an unknown exit as proven stopped. `cancel TASK_ID --wait 10` is an emergency request; check actual
exit confirmation. `goal control` takes `{"action":"pause","reason":"..."}` (or resume/cancel/fail)
plus a key/current claim as applicable. Pause blocks new dispatch but does not stop an active job;
cancel/fail are irreversible stopping intents. No control launches work automatically.

Legacy standalone work uses [task.example.json](task.example.json) and `create --task FILE
--idempotency-key KEY`; it has no Advisor claim or parent goal. Continue its own recorded task rather
than migrating it implicitly. Approved children still need [delivery.md](delivery.md) for goal delivery.
