# Managed background attempts — P3 first slice

Implemented locally on 2026-10-06. A background dispatch reserves one exact attempt, starts a
separate local worker, and returns a durable handle. The worker uses the same executor runner,
output parser, timeout/cancellation, verification and evidence code as foreground `run`.
Bridge does not add a planning model, queue, network daemon or automatic repair scheduler.

The subsequent [concurrency contract](CONCURRENCY.md) adds an explicit per-project opt-in to
two slots, conservative scope checks and cumulative goal wall-time/turn ceiling reservations.
One slot remains the default; aggregate attempt/repair guards apply in both modes. Legacy standalone tasks retain their old scope;
they are not a machine-wide quota system. Preparation still uses explicit foreground
`child prepare`; background dispatch requires its current readiness evidence.

## Entry points

All examples use an explicit state root. For a goal-linked task, include the current
`--advisor-binding` and `--advisor-epoch` on dispatch/recovery/review as before.

```bash
hbridge --state-dir /absolute/project-state --json run TASK_ID \
  --background --idempotency-key dispatch-1
hbridge --state-dir /absolute/project-state --json job JOB_ID
hbridge --state-dir /absolute/project-state --json events TASK_ID --after 0 --limit 100
hbridge --state-dir /absolute/project-state --json events TASK_ID --after CURSOR --wait 20
hbridge --state-dir /absolute/project-state --json cancel TASK_ID --wait 10
hbridge --state-dir /absolute/project-state --json recover TASK_ID
```

Foreground is still the default. `--background` requires a per-task dispatch key; a key without
`--background` is rejected. The key binds mode, explicit live authorization and stub-binary
selection. Repeating it returns the original job/attempt and its current observations, including
a failed launch, without starting another worker. Different content gives `IDEMPOTENCY_CONFLICT`.
A later attempt requires an explicit task recovery/review decision and a new key. Current Advisor
ownership is required even to replay dispatch; `job`, `status`, `events` and emergency cancel
remain readable/available without that claim. `status` lists the task's worker handles.

The handle includes `job_id`, `task_id`, `attempt_id`, `phase`, current task `state`, runner identity
and observed liveness, executor outcome/exit confirmation and an `event_cursor`. Task state may
later refer to a newer attempt; the job and attempt IDs never change. A worker finishing is not
an approval or goal delivery. Inspect artifacts and submit a snapshot-bound review as before.

## Transaction and crash contract

The attempt, task STARTING transition, dispatch key, immutable task packet and worker reservation
commit in one SQLite writer transaction, using the existing Advisor/budget/readiness guards.
No worker starts before that commit. A single transaction can claim the reservation, updating the
attempt's runner identity. Duplicate worker processes cannot claim it again.

| Persisted phase | Meaning / recovery |
|---|---|
| `reserved` | No worker has claimed permission to execute. The recorded runner is the launcher. |
| `claimed` | A worker owns this attempt; executor launch may already have happened. |
| `finished` | Worker returned from execution/verification. Read task outcome and exit confirmation separately. |
| `abandoned` | Execution was proved not to start: failed worker spawn, fenced unclaimed reservation, or owned worker preflight refusal. |
| `recovered` | Explicit recovery observed a dead claimed worker and handled the task. This does **not** assert executor exit. |

If the launcher dies before claim, explicit recovery atomically abandons the reservation.
Even an already spawned but delayed worker can no longer claim it, so this window has positive
non-execution proof. Unknown launcher liveness retains the reservation; emergency cancellation
can fence an unclaimed reservation regardless. Cancellation already requested at claim/preflight
is checked before executor invocation. A cancel racing with actual spawn is observed by the
owning runner, which stops its group and positively observed detached descendants.
Exit confirmation also requires no known survivors or process-inspection failure.

After claim, a dead worker is handled conservatively by ordinary recovery. STARTING/RUNNING
become INTERRUPTED with unknown executor exit; no guessed-PID signals and no automatic executor
restart occur. Unconfirmed attempts keep their goal budget and project slot, even after logical
failure/cancellation. A worker crash after confirmed executor exit in VERIFYING can resume the
frozen checks without another executor attempt. Recovery annotations do not release uncertainty.

A proven non-start is recorded as `spawn_failed` with confirmed exit, so the existing goal
attempt/repair ledger excludes it. The task still retains that attempt number and consumes its
conservative per-task attempt ceiling. A non-started repair retains pending feedback, and a later
explicit repair can reuse the last actually observed compatible Claude session. An unknown or
actually executed intervening attempt cannot be skipped to select an older session.

## Worker execution and live gate

Workers start a new process session with stdin/stdout/stderr detached and inherited descriptors
closed. They own executor process groups; the launching CLI does not need to stay open. Long-lived
Python callers reap child workers with a daemon wait thread. All observations go through SQLite
and existing bounded/redacted executor evidence; worker exceptions persist error codes, not raw
exception messages/environment values. Execution records contain task packets and configuration
choices, never copied credentials or environment values.

Before execution, the worker rebuilds the accepted invocation, compares its description digest,
rechecks planned-child ownership/preparation and rechecks the live gate from current local config
and inherited environment. Foreground help/flag preflight evidence is retained. A closed gate or
changed invocation blocks before execution; it does not silently select another binary/provider.
There is no blanket authorization to retry a live dispatch. Existing per-run authorization,
config opt-in, non-cloud/non-nested restrictions and provider/API-env refusal still apply.

Accepted work may finish after Advisor takeover or pause; a stale Advisor cannot reserve more.
A goal stop request remains visible to the worker and stops execution through the existing path.
No executor is launched merely because a dependency became ready, a query timed out or the
Advisor disappeared. Resources and preparation retain their existing lifecycle rules.

## Incremental observation

`events TASK_ID` accepts a nonnegative signed-64-bit `--after` sequence, `--limit` 1–500 and `--wait` 0–30 seconds.
It returns ordered events after that cursor, `next_cursor`, `has_more`, current task state and
`wait_timed_out`. Sequence gaps are valid: numbering is shared across tasks in the state root.
Keep each cursor scoped to the same task/state root. Start at 0 to read history; the cursor in a
job receipt intentionally starts after events already present at the receipt's snapshot.

A wait returns when events arrive, its deadline expires or the task is no longer executing.
It holds no database lock while waiting, does not mutate the task and never invokes a model.
A query timeout is independent of the executor's wall timeout. Query again with the same cursor
if interrupted; consume `next_cursor` only after processing its page. Existing recent-event
summaries remain bounded views. Goal-wide incremental streams are not included in this slice.

## Migration and evidence limits

Schema revision 6 adds `worker_jobs`. Revisions 1–5 upgrade with one owner-only, WAL-aware backup
and all-stage rollback. Existing tasks/plans, preparation evidence, Advisor bindings and replay
keys are preserved; no historical worker identity is invented. Preserve the state directory
and repository Git objects as before. No actual user/live state was migrated during development.

Offline macOS tests use real local worker/fake/stub subprocesses, Git worktrees, SQLite and frozen
verifiers. They cover launcher exit/lost receipt, duplicate dispatch/claim races, cancel/timeout,
worker death, known versus unknown crash windows, verification recovery, preparation changes,
Advisor takeover, Claude stub resume, gate closure, event pagination/wait and migrations.

This proves separation from the simulated launching CLI process on this Mac. It does **not**
prove survival of every desktop host's descendant cleanup, GUI app termination, macOS logout,
sleep/reboot, service supervision or real-model background execution. There is no launchd
registration or automatic worker restart. The local P3 core also has concurrency/budget and
simulated host-session teardown evidence in [CONCURRENCY.md](CONCURRENCY.md). Installed-host
lifecycle and real cross-harness behavior still need their later bounded acceptance.

## P7 detached tool correction

The native Codex cancellation case exposed a tool in a new process group after its CLI exited.
The runner now samples PID/parent/group/state/birth metadata, retains observed descendants across
reparenting, and checks identity again before individually signalling a detached descendant.
It never signals an inferred detached group, unrelated PID, or original group already observed dead.
TERM grace and KILL escalation include these observed descendants. Inspection failure or known
survivors prevents confirmed exit and keeps existing unknown-outcome/slot guards in effect.

A process group alone is not descendant containment: Python's `start_new_session` starts a new
session, and termination targets a process or group; see the [Python subprocess reference](https://docs.python.org/3.11/library/subprocess.html).
Sampling can miss a fork/reparent between observations, and birth-marker checks are not an atomic
OS process handle. This is lifecycle observation for cooperative tools, not an adversarial sandbox
or machine-wide cleanup guarantee. Native retest is distinct from the offline detached-child cases.
