# Exact local branch delivery — third P4 slice

The current Advisor explicitly turns a verified, approved integration into a new named **local**
branch. The branch points to the exact approved candidate commit/tree. Delivery does not checkout,
merge, reset, stash, clean, push or create a PR, and never dispatches an Executor or reruns checks.
Conflict-repair task binding and ownership-safe cleanup remain future P4 work.

## Commands

```sh
hbridge --state-dir /absolute/state --json \
  --advisor-binding adv_CURRENT --advisor-epoch 1 \
  goal deliver goal_ID --integration integration_ID \
  --branch delivered/my-feature --idempotency-key delivery-v1

hbridge --state-dir /absolute/state --json delivery status delivery_ID
hbridge --state-dir /absolute/state --json goal status goal_ID

hbridge --state-dir /absolute/state --json \
  --advisor-binding adv_CURRENT --advisor-epoch 1 \
  delivery abort delivery_ID --reason 'Choose a different branch after inspecting the conflict'
```

`goal deliver` requires a literal new local branch name and the current Advisor binding/epoch.
Names use ASCII letters/digits, `.`, `_`, `-`, `/`, must satisfy Git ref syntax, and cannot be
options, revision expressions, `HEAD`, `hbridge`, `hbridge/...` or `refs/...` (case-insensitive).
Unknown request fields are rejected. Requests and goal-local idempotency keys are frozen.

The target must be absent. Existing refs are refused even if their commit happens to match; an
unowned matching branch is not proof the bridge created it. Case aliases, symbolic/dangling refs,
and an absent branch already selected by an existing worktree are also refused. No adoption or
force-replacement of user branches is exposed. Source checkout dirtiness or advancement is allowed:
it remains untouched, and the receipt records the goal base, observed source HEAD, left/right commit
counts and whether uncommitted changes were present. A changed source HEAD is not rebased into the
candidate. To include newer source commits, create and validate a new goal/candidate explicitly.

## Readiness and selection

`goal status.delivery` is now an object rather than the historical `not_implemented` string:

| `delivery.status` | Goal state | Meaning |
|---|---|---|
| `not_ready` | Existing child/goal projection, or `NEEDS_ATTENTION` for stale approval | No valid current integrated approval; see blockers |
| `ready` | `READY_TO_DELIVER` | Current exact approval and confirmed idle project; no branch delivered yet |
| `pending` | `NEEDS_ATTENTION` | Durable intent exists; inspect or explicitly retry the same request |
| `delivered` | `DELIVERED` | Completed receipt, intact historical bindings and matching branch/proof refs |
| `changed` | `NEEDS_ATTENTION` | Completed delivery's refs or retained metadata are missing/changed; receipt stays historical |

The **latest frozen integration** is the selected candidate. Freezing a newer candidate supersedes
older readiness; the bridge never falls back to an earlier passing integration while a newer one
is unfinished or conflicted. Delivering an older integration ID is refused. To return to earlier
inputs, freeze a new request and explicitly verify/review it; historical approvals do not transfer.

All planned/linked children remain required. Frozen goal membership/inputs, retained approved refs,
current owned candidate, frozen verifier configuration, confirmed total-check exits, manifest/log
digests and the current Advisor's exact review must pass the existing
[verification/review gate](INTEGRATION_CHECKS.md). New check runs, negative decisions, evidence/code
changes or Advisor takeover invalidate readiness. No active or historically unknown execution or
integration check may hold the project, including across its other goals in the same state root.
Dispatch pause does not prevent this explicit deterministic local delivery; cancel/fail does.

A delivery intent freezes the goal against further child/plan/check/review/control mutations,
including emergency cancellation: no Executor is active at this point, and cancelling the goal
cannot erase a pending Git publication. Inspect/retry/abort the intent instead. Once delivery is
completed, use a new goal for new work. A deleted/moved delivery branch does not reopen the goal for
new dispatch. Read operations remain available without an Advisor; takeover can still attach a new
Advisor to inspect or finish a pending operation.

## Durable intent and the Git/SQLite crash boundary

The first transaction persists `prepared` intent before any ref mutation. It binds:

- goal/project/repository identity and fixed base;
- integration ID, exact candidate commit/tree and approval fingerprint;
- review/check IDs and their retained record digests;
- approving Advisor binding/epoch, requested branch, source observation and idempotency key.

Only one non-aborted delivery intent/receipt is allowed per goal. Branch reservations are unique
within a project/state root, including ASCII case aliases. Admission and publication use the same
SQLite writer lock as other goal mutations. The project is checked again immediately before ref
creation, along with current exact approval and the frozen intent bindings.

One Git ref transaction creates both `refs/heads/<requested-name>` and
`refs/hbridge/deliveries/<delivery_id>` pointing to the approved commit. Both are **create-only**,
without symbolic-ref dereferencing. The private ref is a publication proof associated with the
durable intent, not a separate user delivery branch. An external target creation race fails without
leaving a partial proof. Both refs and the commit tree are checked before recording `delivered` and
the `goal_delivered` event together in SQLite.

Git and SQLite are not one atomic database. If the process dies:

- Before publication, the intent stays `prepared`. An explicit same-key retry revalidates the
  current approval and absent target before attempting publication.
- After the atomic ref pair exists but before the database completion, status reports `pending`
  with matching refs. An explicit same-key retry records the existing publication without changing
  refs. Retained historical approval/check bindings and exact tree must still match.
- One missing/moved/symbolic ref, unavailable repository identity or changed retained binding
  stops recovery. Nothing is overwritten, removed or guessed.

Publication that already happened under the prior valid Advisor is a historical fact. A new current
Advisor can record it after takeover, even if the candidate workspace later changed; the branch is
still the exact earlier approved commit. If no publication exists, takeover makes the old approval
stale: abort the intent, explicitly review under the current Advisor and submit a new delivery key.

A completed same-key replay returns the original receipt plus current observations. It never
recreates a deleted branch or resets a moved one. Changing integration/branch under that key is
`IDEMPOTENCY_CONFLICT`. Changed refs are `DELIVERY_CONFLICT` (CLI exit 3, no automatic retry). Read-only
status never finalizes an intent or writes refs.

`delivery abort` only abandons a **prepared** intent with no private publication proof. It records
the reason and releases that intent's reservation; it does not delete refs, undo Git work or
promise cancellation of an orphaned Git subprocess after a parent-process failure. This is intent
abandonment, not process recovery; pending Git activity needs inspection before further operations.
A foreign target branch is preserved. An existing proof, including a dangling symbolic proof,
prevents abort; completed receipts cannot be aborted. Same-reason abort replay is idempotent;
changing the recorded reason is rejected. Replaying an aborted delivery returns that historical
abort; a new key is required for another intent. Missing proof is not a claim that no external Git
mutation ever occurred.

These guarantees cover cooperating bridge operations in one state root and Git's create-only ref
transaction. External Git commands/worktree selections are not serialized by SQLite. Status is an
observation, not a permanent lock on user branches; the private refs are integrity/ownership evidence,
not authentication against the same local user deliberately rewriting all records. All candidate,
verification, private-ref and delivery evidence is retained. [CLEANUP.md](CLEANUP.md) now documents
explicit post-delivery cleanup of selected clean owned worktrees while retaining this evidence.

## Persistence and acceptance

Schema 9 adds `deliveries` and active-goal/branch uniqueness indexes. Existing v1–v8 upgrades retain
WAL-aware backup and atomic all-stage rollback. Integration approval records and digests are not
rewritten by migration; v8 approved candidates can be delivered without rerunning checks. No real
user/live state was migrated during development.

Tests use isolated repositories, real local Git/SQLite and CLI crash injection, with simulated
Executors. They cover exact commit/tree delivery, dirty/advanced source preservation, current
readiness and stale approval, unowned/symbolic/unborn/case-alias branch refusal, atomic publication
races, three crash windows, takeover, abort, completed replay after ref changes, retained evidence
loss, cross-goal unknown holds, migration and CLI receipts. See [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md)
for actual results. No new model calls, remote push, installed-host acceptance or real multi-harness
completion is implied by this milestone.
