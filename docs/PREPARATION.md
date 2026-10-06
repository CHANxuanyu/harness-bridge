# Explicit workspace preparation (P2 local core)

The Advisor can now freeze bounded preparation steps in a child plan and explicitly run them
after materialization. Bridge records their lifecycle independently of executor attempts.
This completes the local P2 preparation contract for finite, trusted setup/check commands;
background executor workers are described in [WORKERS.md](WORKERS.md). Preparation remains
foreground and project-exclusive even when executor parallelism is explicitly set to two; see
[CONCURRENCY.md](CONCURRENCY.md). Broader process/resource administration is still pending.

## Plan and command

The optional `preparation` field is beside `task`, `depends_on` and `environment` in a child
plan. For example, when the project already has an explicitly reviewed preparation script:

```json
{
  "preparation": {
    "steps": [
      {
        "id": "prepare-dependencies",
        "argv": ["python3", "-B", "tools/prepare_environment.py"],
        "cwd": ".",
        "timeout_seconds": 120
      }
    ],
    "outputs": [{"path": "local-cache", "kind": "cache"}],
    "resources": ["cache:my-project"],
    "max_runs": 3,
    "wall_timeout_seconds": 300,
    "max_log_bytes": 262144
  }
}
```

The script/path above is illustrative, not supplied or discovered by Bridge. Scripts and all
commands they may invoke are trusted Advisor inputs and require review in the project context.
There is no automatic discovery, package install, credential copying or re-preparation.

```bash
hbridge --state-dir STATE --json child prepare CHILD_ID \
  --idempotency-key SETUP_KEY --advisor-binding BINDING_ID --advisor-epoch 1
```

The worktree must exist and the task must be `READY`. Preparation shares the project's serial
execution slot with executors/verifiers. Pause blocks new executor dispatch, but still permits
explicit preparation; permanent goal cancellation/failure prevents new preparation. A stale
Advisor cannot start or replay a preparation request. Already accepted observations can finish
after takeover without giving the old Advisor permission to start another run.

The plan freezes step IDs, argv, relative cwd, timeouts, declared outputs and resource names.
Unknown fields and duplicate step/output/resource identifiers are refused. Commands use argv,
not an implicit shell. Every step is required; execution stops at the first failed/unknown step.
At most 20 steps and 10 explicitly requested runs are allowed, with a configured lower run cap.
Each step has a deadline, bounded by the remaining aggregate command deadline. Group shutdown,
draining and Git evidence collection may extend beyond that execution deadline.

The idempotency key returns the same preparation record, including while the original is
running or after it failed. It never runs commands again. An intentional retry needs explicit
task recovery and a new key. Preparation never creates an executor attempt or consumes the
goal's model attempt/repair budget; its own finite `max_runs` is charged when reserved.

## Evidence, readiness and repair

The durable record includes preparation/task/child/goal IDs, plan-derived specification digest,
runner identity, active step process IDs, timestamps, per-step exit status, confirmed exit,
bounded redacted stdout/stderr metadata, declared output inventory and source fingerprints.
`status TASK_ID` exposes the latest preparation. The receipt's `artifacts_directory` locates
logs and a private setup HOME. Older records remain in `preparation_runs` and task events.

Files declared as outputs are inventoried as artifacts or caches, with presence/type and file
size where applicable. They must remain inside the worktree; credential-looking paths are
refused. This is an inventory of declared outputs, not a hash of every ignored file or a
complete audit of arbitrary external side effects. Setup's private HOME/cache remains under
the recorded preparation artifact directory and is not automatically copied or shared.

A preparation passes only when all steps pass, their owned processes have confirmed exit,
declared outputs exist, ordinary child readiness checks pass, and Git-visible candidate content
has not changed during setup. A step changing tracked/non-ignored source leaves the task blocked;
Bridge does not revert those edits or silently change the execution baseline. Projects should
commit appropriate ignore rules before materialization for dependency/cache directories.

Every child `run`, including an old CLI entrypoint, checks both ordinary readiness and the
latest successful preparation's specification/current-candidate binding before dispatch and
inside its reservation transaction. An older successful run cannot override a newer failed run.
Missing outputs or changed source invalidate readiness. `child preflight` exposes this condition
without starting preparation or a model.

After an executor changes source and the Advisor requests repair, that candidate requires a
fresh explicit preparation run. It leaves the previous attempt/session and pending review
feedback intact. The next executor invocation remains a repair of the same task/session;
preparation is not another executor session or a restart of the goal.

## Cancellation and recovery

| Observation/action | Task state and behavior |
|---|---|
| Reservation accepted | `PREPARING`; runner and record persist before spawn |
| All checks pass with unchanged source | `READY`, with current preparation evidence |
| Failed step, timeout, spawn failure, missing output/cwd, background helper or changed source | `BLOCKED`; no executor dispatch |
| Task or goal cancel while preparing | Request stop; owning runner terminates its group; `CANCELLED` only after confirmed exit |
| SIGTERM to owning runner, exit confirmed | `INTERRUPTED`; explicit `recover --resolve retry`, then a new preparation key |
| Runner dies / exit cannot be confirmed | Recovery records `INTERRUPTED` with unknown outcome; no signals to unproven processes and no automatic restart |
| Unknown outcome resolved as failed/cancelled | Task may stop logically, but slot/resource reservations remain; goal termination stays pending |

Use the existing `cancel TASK_ID` / `recover TASK_ID` commands. Cancelling during final
observations is rechecked transactionally so a late cancel cannot be overwritten by `READY`.
An acknowledged unknown preparation does not unlock retry; a cooperative acknowledgement is
not proof of exit. Audited release of unknown reservations remains future lifecycle work.

## Shared resources and scope

Resource names are explicit logical exclusivity keys across **all projects in one state root**,
for example `port:3000` or `cache:my-project`. The Advisor must use the same name for the same
resource. Claims are reserved transactionally before any setup command; a conflicting request
creates no run and consumes no preparation allowance. Claims persist through execution/review,
then become reclaimable when the owner task is terminal and every preparation/attempt exit is
confirmed. Confirmed failed preparation releases its claims; unknown exits never do.

These are coordination records, not OS port allocation, filesystem locks against unrelated
programs, or cross-state-root leases. External availability checks can be explicit preparation
steps. Bridge does not start persistent services: background processes discovered by the runner
are terminated and the preparation is blocked. Undeclared/escaped external side effects remain
outside the runner's observation scope; worktree isolation is not a sandbox.

Setup gets an isolated HOME/XDG tree and a small inherited environment (PATH, locale, temporary
directory). It does not inherit host API/provider credentials or user configuration directories.
Direct coding-harness commands are refused in setup plans; the existing model live gate is
unchanged. Arbitrary scripts/wrappers are trusted code and can have their own side effects:
the command checks are misuse prevention, not proof that arbitrary code cannot call a model.
Use setup only for approved finite environment preparation/checks.

## Upgrade and evidence

Revision 5 adds preparation runs and resource claims, with the existing atomic v1–v4 upgrade,
WAL-consistent backup and rollback. Absent `preparation` remains omitted from canonical old
plans, preserving replay digests. Old plans with only presence requirements continue working.
No actual user/live state was migrated during this implementation round.

Evidence is offline: `tests/integration/test_preparation.py`, the readiness/planning suites and
migration checks. They use isolated Git repos, fake executors and real local setup subprocesses,
including injected process crashes. No real coding harness, authentication or billing path was
invoked. A subsequent P3 slice adds background executor workers and task event cursors, while
the subsequent P3 local core adds scoped concurrency and total executor-ceiling reservations.
P4 local integration/delivery/retention is implemented; P5–P7 (second executor and installed-host acceptance) remain unfinished; this is not final product acceptance.
