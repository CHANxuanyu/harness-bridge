# Frozen integration candidates — first P4 slice

Implemented 2026-10-06. The Advisor can freeze every required child's approved snapshot and an
explicit integration order, then materialize a separate Bridge-owned candidate. This slice does
**not** run the frozen total-goal checks, approve the integration or deliver a branch. Those remain
P4 work. A `CANDIDATE` is not `READY_TO_DELIVER` and is not `DELIVERED`.

## Commands and contract

```sh
hbridge --state-dir /absolute/state --json \
  --advisor-binding adv_CURRENT --advisor-epoch 1 \
  goal integrate goal_ID --file integration.json --idempotency-key integration-v1

hbridge --state-dir /absolute/state --json \
  --advisor-binding adv_CURRENT --advisor-epoch 1 \
  integration materialize integration_ID

hbridge --state-dir /absolute/state --json integration status integration_ID
```

`goal integrate` only freezes the request and its exact approved inputs. It returns the durable
integration ID in `FROZEN`; it creates no worktree. `integration materialize` composes the frozen
versions and creates the candidate worktree, or records `CONFLICT`. JSON receipts use the existing
flat CLI envelope (`ok` plus receipt fields). Neither command dispatches an Executor.

IntegrationSpec 1.0 rejects unknown fields:

| Field | Contract |
|---|---|
| `schema_version` | `"1.0"` |
| `task_ids` | 1–100 distinct task IDs, in explicit integration order |
| `verification` | 1–50 existing VerificationCommand objects; unique IDs, at least one required check |

The verification commands, cwd, timeout, required flag and trust labels are frozen now for the later
verification stage. They are **not executed by freezing or materializing**. Example:

```json
{
  "schema_version": "1.0",
  "task_ids": ["task_FIRST", "task_SECOND"],
  "verification": [{
    "id": "goal-acceptance",
    "argv": ["python3", "/absolute/trusted/check_goal.py"],
    "cwd": ".",
    "timeout_seconds": 60,
    "required": true,
    "trust": "external-acceptance"
  }]
}
```

Every planned and directly linked task is required in this first slice. Every plan must be
materialized, every task must be SUCCEEDED with a retained accepted approval, and every recorded
attempt/preparation must have a confirmed exit. The request must include all those tasks exactly
once. Foreign, omitted, unfinished or unknown-exit children are refused. Planned dependencies must
appear before their successors. Optional/competing input selection and scope amendments are not
exposed; this does not silently discard an inconvenient failed child.

The frozen record binds goal/base/repository identity, task definitions, plan membership, approved
review/fingerprint/commit/tree/private ref, order, and verification configuration. Existing approval
refs from [EXECUTION_CONTEXT.md](EXECUTION_CONTEXT.md) are reused; no resnapshot of child workspaces.
An older approval without a retained tree requires the existing explicit `retain-approved` flow.

## Git behavior and source preservation

Composition begins at the goal's fixed commit, even if the source branch has moved. It uses Git's
three-way tree merge over retained approval commits and their baseline ancestry, in the supplied
order. Additions, deletions, binary content, renames and modes are represented by Git trees. Parent
changes already inherited by a successor are not reapplied over its descendant edits. Shared Git
merge drivers are refused; hooks are disabled by the existing Git wrapper.

A successful candidate has a deterministic commit pinned at
`refs/hbridge/integrations/<integration_id>/candidate`. Its owned worktree is
`<state>/integrations/<integration_id>` on an internal `hbridge/integration/<integration_id>` branch.
That branch is workspace metadata, **not a final delivery branch**. The commit binds the complete
frozen request and inputs, including verification configuration, even if two candidates have the
same tree. No user checkout/index is modified, stashed or reset. The source may contain new user
edits by this point; they are preserved and are not included in the fixed-base candidate.

On conflict, the record identifies the incoming task and the preceding applied task IDs, and pins
the last clean composition under `/partial`. No conflict-filled candidate worktree is created. All
original approved trees remain unchanged. The retained partial commit, original input bases and
approved commits are the evidence for a future explicit integration-repair child. Automatic conflict
resolution, a repair-child baseline binding and final conflict supersession are not yet implemented.
The latest materialized conflict makes the goal need attention; it does not spend model budget.

Worktrees share Git configuration/objects and are not an OS sandbox. Existing Git filter and ignored
file limitations remain in force. `workspace_status` checks HEAD, path/branch/common-dir ownership, Git status and an independent
snapshot using a fresh index (including edits hidden by assume-unchanged). It is not total-goal
verification or an approval fingerprint.
The next verification/review stage must independently bind a fresh exact snapshot.

## Retry, ownership and interruption

Freeze and materialization both require the current Advisor binding/epoch. New mutation requests
are refused after goal cancellation/failure. Read-only integration status remains available without
an Advisor claim. Dispatch pause does not block this deterministic Git-only work; no attempt, slot,
time or turn reservation is consumed and no verifier/setup command is launched.

Same-key freeze with the same contract returns the existing record; changed order/verification
under that key gives `IDEMPOTENCY_CONFLICT`. Replay does not refresh the frozen inputs. A later
required plan/task makes the old input set invalid for materialization; status exposes this through
`inputs_status`, and the old evidence remains available. New input/configuration means a new key.

Materialization is serialized by the existing SQLite writer transaction, including finite Git
operations. Concurrent requests cannot create two candidate receipts. Git and SQLite are not an
atomic storage system: a process crash may leave private refs and a worktree while the database
record remains FROZEN. An explicit retry only accepts the same deterministic Git object and an
unchanged worktree with the expected path, repository, branch and HEAD. Symlink destinations are
refused. A conflicting ref/branch, foreign directory, dirty candidate or moved HEAD is never reset
or overwritten. An incomplete Git operation may require inspection; retry does not force-clean it.

After CANDIDATE or CONFLICT has been recorded, materialization replay never recomposes or recreates
a missing worktree. It returns the existing receipt and an observed workspace status (`unchanged`,
`changed`, `foreign` or `missing`). Status also checks the frozen inputs and private refs. A changed
candidate is never promoted to approval or delivery by replay. No cleanup command is added: retain
all workspaces, private refs and evidence until the later ownership-safe retention/cleanup stage.

## Persistence and acceptance boundary

Schema revision 7 adds the `integrations` table and index. Revision 1–6 upgrades reuse the WAL-aware
backup and all-stage rollback mechanism. Existing task/goal/plan/worker contracts and replay digests
are unchanged. Opening an old state upgrades it; this development round used isolated fixtures only
and did not migrate actual user/live state. Preserve backups and the repository's retained Git refs.

Offline coverage includes two-child composition, dependency edits, full Git change types, conflict
receipts, stale/unknown input refusal, Advisor takeover, source preservation, races, tampered pins,
changed/foreign/symlink workspaces, actual process exit after Git materialization, and migration with
real simulated-worker history. No real harness, auth or model usage was invoked.

Next P4 work: run/recover the frozen total-goal checks, bind exact integration review, materialize
budgeted conflict-repair children, create the exact idempotent local delivery branch and implement
ownership-safe retention/cleanup. Installed-host and real multi-harness acceptance remain later gates.
