# Fixed dependency baselines and workspace readiness (P2 local core)

Implemented locally on 2026-10-06. This extends [child planning](PLANNING.md). Explicit bounded
setup commands and resource claims are now covered by [PREPARATION.md](PREPARATION.md).
All tests for this slice use isolated repositories and fake executors. No real harness was called.

## What the Advisor and Executor receive

The Advisor submits an immutable child plan, explicitly materializes it, and explicitly runs
the resulting task. Bridge retains each accepted approval and composes declared dependencies
before creating the child's TaskSpec or worktree. The assigned executor receives its own cwd,
goal ID/objective, child ID/key, fixed base SHA, approved dependency task/attempt/review IDs,
fingerprints and commits. This context appears in both JSON packets and Claude's rendered
prompt. Existing per-attempt feedback remains bound to the task and attempt.

These are explicit references to approved work. Bridge does not copy the Advisor's conversation,
authentication, `.env`, virtual environments or running services into a child session.

## Retaining approval

An accepted `review` now retains the verified Git tree as a deterministic, unsigned synthetic
commit, parented to the task's fixed base, under `refs/hbridge/approved/TASK_ID/ATTEMPT_ID`.
The snapshot record and accepted review commit in one SQLite transaction. The executor's
HEAD/index/branch and source checkout contents are unchanged. These refs retain Git objects
through garbage collection; they are not delivery branches or a merge into the user's branch.

Git and SQLite cannot commit atomically. If a crash rolls back SQLite after creating a ref,
the ref may remain without a claimed approval. A retry can adopt only the exact deterministic
commit; a mismatching existing ref is never overwritten. Cleanup of retained/unclaimed refs
is deferred to P4. Keep the repository objects/refs and state directory together when backing up.

An older `SUCCEEDED` task may have no retained snapshot. It remains approved, but dependent
children report `WAITING_BASELINE / approved_dependency_snapshot_missing`. To retain it:

```bash
hbridge --state-dir STATE --json retain-approved TASK_ID \
  --advisor-binding BINDING_ID --advisor-epoch 1
```

This explicit operation requires the accepted approval, digest-checked evidence and unchanged
current candidate. It refuses changed or missing evidence; migration does not silently resnapshot
old work. Repeating retention returns the same record. `status TASK_ID` exposes `approved_snapshot`.
Current Advisor fencing applies to new approval, retention and materialization.

## Dependency composition

Roots retain the goal's original base. Successors use preserved approved commits in stable
child-key order. Git's three-way merge preserves dependency ancestry, including chains and
diamonds. A successful composition gets its own `refs/hbridge/baselines/CHILD_ID` and a digested,
immutable database record containing the plan digest and every approved input. Only then may
the task/worktree be created. Replays use this same baseline, never current parent worktree files.
The ordinary `create --goal` command still cannot choose an arbitrary alternative base.

| Situation | Result |
|---|---|
| A dependency is not approved | `WAITING_DEPENDENCIES`; no task/worktree |
| An older approval has no retained snapshot | `WAITING_BASELINE`; explicit retention needed |
| Approved inputs are available | `READY_TO_MATERIALIZE`; composition runs only when requested |
| Git reports a merge conflict | Durable `BASELINE_CONFLICT`; input attribution retained; no task/worktree/model |
| Retained record/ref/object missing or changed | Integrity error; no fallback or automatic replacement |
| Configured custom Git merge driver | Preflight refusal; no driver command executed |
| Successful materialization | Task state plus fixed `baseline` in `child status` |

Git must support `merge-tree --write-tree -z`; unsupported operations fail before task creation.
Merge renormalization is disabled and configured external merge drivers are conservatively
refused. Existing snapshot Git-filter limitations in `SECURITY.md` still apply.

A clean merge is not evidence that combined code works. The successor still has its own
verification/review, and the goal still needs P4 integrated acceptance/delivery. Conflict
resolution and plan supersession are not automated; a conflict is not retried against a moved
base or silently dispatched to an executor. Existing plan identities remain immutable.

## Non-executing readiness checks

A child can optionally declare requirements alongside `task` and `depends_on`:

```json
{
  "environment": {
    "files": ["package-lock.json"],
    "directories": ["node_modules"],
    "executables": ["node", "node_modules/.bin/tsc"]
  }
}
```

Files/directories are relative to the assigned worktree and cannot escape through symlinks.
Executables can be PATH names, worktree-relative paths, or explicitly supplied absolute paths.
Requirements are immutable with the plan; old plans without the field retain their original
canonical digests and replay keys. Nothing is inferred from package scripts or copied from
the source checkout. Installation/authentication is not performed by these probes.

```bash
hbridge --state-dir STATE --json child preflight CHILD_ID
```

The child must already be materialized. The read-only report checks worktree presence, repository
identity, owned branch, fixed-base ancestry, declared requirements and required verification
command cwd/executable presence. Only Git metadata commands run; located tools are not executed.
`ready: true` means these presence checks pass, not that tool versions, credentials, dependencies
or services actually work. No successful report is cached as a lasting guarantee.

Every planned child `run` repeats these checks before invocation construction and inside the
dispatch transaction. Missing requirements return `PREFLIGHT_FAILED`, leave the task `READY`,
and consume no attempt/budget. An explicit local environment fix can unblock a presence-only task. If the plan also has
`preparation`, its latest successful preparation must match the current candidate and outputs;
see `child prepare` in the preparation reference.
Standalone/unplanned legacy tasks retain their prior preflight behavior. Emergency cancellation,
Advisor takeover, live gating and verification/review rules remain in force.

The transaction coordinates bridge actors, not arbitrary external filesystem writers. Checks
cannot prevent another same-user process changing files immediately afterward. Worktrees are
not a sandbox, and ignored preparation artifacts are outside Git snapshot evidence.

## Storage and following milestones

Revision 4 adds approved-snapshot and child-baseline tables. Upgrades from v1/v2/v3 run under
the existing writer lock with one WAL-consistent, owner-only pre-upgrade backup. Failed upgrades
roll back all stages. Old task/spec/plan digests and task identity remain intact. No real user
state was migrated in this implementation round.

Revision 5 subsequently adds preparation/resource records and preserves old plan digests.
Explicit bounded preparation, cancellation/recovery, output/cache inventory and named resource
claims complete the local P2 core; see [PREPARATION.md](PREPARATION.md) for its finite-command
scope and remaining lifecycle limits. [WORKERS.md](WORKERS.md) covers the subsequent P3
background-attempt slice. Two-executor concurrency, P4 integration/delivery, a second live
executor adapter and installed host entrypoints remain later work. This is not a
finished V1 product.
