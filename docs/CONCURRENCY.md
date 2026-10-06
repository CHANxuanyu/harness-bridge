# Project concurrency and aggregate executor reservations — P3

Implemented on 2026-10-06 on top of the managed worker lifecycle in [WORKERS.md](WORKERS.md).
Foreground and background dispatch share these checks. This is deterministic admission control;
it does not add an agent, a queue, automatic scheduling or a model API dependency.

## Explicit parallelism

A state directory defaults to one active slot per goal-linked Git project. To permit up to two,
add this table to that state's existing `config.toml`, preserving any other configuration:

```toml
[execution]
max_parallel_per_project = 2
```

Only integer 1 or 2 is valid; booleans, strings, other numbers and misspelled execution keys are
refused. This setting does not enable live execution. Each real dispatch still needs the existing
per-run authorization, live gate and current Advisor claim. The bridge does not change this setting
or increase it when a slot is unavailable.

All goals registered for the same repository identity in this state share the cap. Separate projects
have separate caps; separate state roots are not coordinated. Legacy standalone tasks retain their
original behavior. A plugin should keep using the project's registered state, not create new state
directories or omit goal ownership to evade limits.

The current file is read inside each reservation transaction, including for a long-lived Python
caller. Lowering the cap does not kill accepted work; it blocks further reservations until capacity
is available. There is no waiting queue: a refused dispatch must be explicitly requested later by
the Advisor. Accepted worker execution can finish after pause/takeover; these do not grant new work.

## Slots, scopes and preparation

STARTING (including an unclaimed worker), RUNNING and VERIFYING hold execution capacity. Confirmed
completion releases active capacity while awaiting review, but keeps its cumulative goal budget.
Unconfirmed attempt or preparation exits retain capacity even after logical task failure/cancellation.
Multiple unresolved historical executions retain separate slots even on one task; status
includes `slots_by_task`. An unresolved task cannot use a spare second slot to start another attempt on the same worktree.

Parallel execution also requires a conservative proof that the declared `allowed_paths` are disjoint.
For each glob, take all complete literal path components before its first `*` or `?` component.
Two tasks can execute concurrently only if every pair of these roots has neither equal nor ancestor/descendant
roots. Comparisons fold case and normalize Unicode spelling to treat common filesystem aliases as
conflicting. Forbidden paths do not narrow this proof. It applies across different goals too.

| Scopes | Admission with a second slot available |
|---|---|
| `src/a/**` and `src/b/**` | Allowed |
| `src/a.py` and `src/b.py` | Allowed |
| `src/**` and `src/a.py` | Refused |
| `src/*.py` and `src/*.js` | Refused: this proof cannot establish disjointness |
| `**/test.py` and `docs/**` | Refused: first scope has no literal root |
| `Src/A.py` and `src/a.py` | Refused |

This compares declared repository-relative write intent, including not-yet-created paths. It is
not an OS sandbox or proof about scripts, symlink targets, ignored files or shared external services.
Existing post-execution path-policy/snapshot/verification gates remain necessary. Broad globs can
be serialized; they are never silently rewritten to get a second slot. Explicit competing-candidate
parallelism is not exposed in this slice; overlapping proposals remain serial.

Preparation remains foreground and project-exclusive even when the cap is two: trusted setup
commands do not have a complete write-scope contract. A preparing task blocks other execution,
and active execution prevents preparation in the same project. Unknown preparation exit keeps this
exclusive hold. Named shared-resource claims still apply across projects in the same state root.
Manual `verify` and recovery from INTERRUPTED verification acquire capacity/scope protection too.
Resuming an already VERIFYING task retains its existing slot, without spending another executor
attempt. Preparing and rechecking never spend the goal's executor time/turn reservation budget.

Refusals use `STATE_CONFLICT` and structured `details.reason`:
`project_capacity`, `write_scopes_may_overlap`, `preparation_requires_exclusive_project`, or
`task_already_occupied`. Receipts include occupied/conflicting task IDs. They consume no new attempt.
`goal status` exposes project `execution.max_parallel`, occupied slots/tasks, preparation exclusivity
and the scope policy. Dispatch events record the admitted cap and requested time/turn ceilings.

## Goal-level ceilings

GoalSpec 1.0 accepts two optional immutable limits, in addition to `max_attempts` and `max_repairs`:

| Field | Meaning |
|---|---|
| `max_executor_wall_seconds` | Positive finite number, at most 8,640,000 seconds |
| `max_executor_turns` | Integer 1–50,000 |

For example, a goal can allow three attempts while reserving at most 2,700 executor-seconds and
60 requested turns in total. See `examples/goal.json`. The corresponding values must fit the
child TaskSpecs; the bridge never silently lowers their frozen limits to fit remaining budget.
Absent/null fields mean that aggregate dimension was not configured. Existing per-attempt and
per-task limits and goal attempt/repair ceilings still apply; absence does not invent a new cap.

Before committing an attempt, atomically reserve its full `wall_timeout_seconds` and
`max_turns_per_attempt`. Sum these ceilings over all of this goal's recorded attempts, including
repairs, retries and any future integration executor tasks linked to the goal. This accounting is
cumulative, not a simultaneous-time pool: success, failure, timeout and executed cancellation all
retain their full ceilings. An ended attempt releasing a concurrency slot does not refund budget.
Unknown exits retain both. Only `spawn_failed` with confirmed non-execution is excluded, using the
same rule as the existing aggregate attempt/repair ledger. Task attempt numbers/ceilings remain
conservatively consumed even after a proven non-start.

Attempts plus their integrity-checked frozen TaskSpecs are the durable reservation ledger; no second
usage table needs reconciliation. The guard, slot/scope checks, attempt insertion and event all
share the SQLite writer transaction. Two concurrent requests cannot each spend the same remainder.
Decimal arithmetic avoids rejecting an exact fractional-seconds boundary due to binary-float addition.
Changed historical task specs fail integrity checks instead of silently shrinking a past reservation.

An exhausted dimension gives `BUDGET_EXHAUSTED`, with the dimensions exceeded, current reservations
and requested ceilings. `goal status.budget` shows `reserved_wall_seconds`, `reserved_turns`, both
optional maxima and the explicit accounting basis. Same-key background replay returns its original
attempt and adds no reservation. Changing a goal ceiling under the same creation key is a conflict;
this slice does not offer budget amendments or task-ID-based refunds.

These numbers are **requested execution ceilings, not observed model usage, subscription balance
or a bill**. The wall reservation covers the executor's configured runner deadline, not setup,
verification, waiting, shutdown grace or Advisor inference. Actual harness turn-limit enforcement
retains its existing evidence status; a flag accepted by a tool is not a cross-provider cost metric.
No self-reported remaining turns, latency or cost is used to release budget automatically.

## Compatibility and validation scope

Database revision stays 6: existing attempt/task records already contain the frozen data needed.
No migration or historical record rewrite is required. Absent new fields are omitted from canonical
GoalSpec serialization so historical creation digests and replay keys remain valid. Old goals expose
new reservation projections while their unset total ceilings stay visibly unset.

Offline integration checks use two actual detached fake processes, separate worktrees/process groups,
independent cancellation, scope refusals, concurrent capacity/budget races, non-start refunds,
unknown-exit retention, repair and verifier paths, older goal replay, and simulated host session exit.
Unit checks cover config/limits and a bounded comparison against the existing glob matcher.

This closes the local worker/concurrency/ceiling implementation, subject to the recorded offline
checks. It does not validate every desktop host's process cleanup, logout/sleep/reboot survival,
real two-harness concurrent execution or vendor turn-limit enforcement. Host-specific acceptance
and installed entrypoints remain in the project plan; no real-model authorization is renewed.
Integration and exact local-branch delivery (P4), second executor (P5), installed entrypoints (P6)
and complete real-product acceptance (P7) remain outstanding.
