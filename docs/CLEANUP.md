# Retention and conservative cleanup — P4

Cleanup is an explicit local operation after a confirmed delivery. Its only policy is
`clean_worktrees_keep_refs_and_evidence`: remove selected clean, unchanged, inactive Bridge
worktrees; retain every branch, private Git ref, database record, artifact, log and cache.
It never resets, stashes, force-removes, prunes registrations, deletes branches or pushes.

## Preview and apply

```sh
hbridge --state-dir /absolute/state --json goal cleanup goal_ID
```

This read-only preview returns prior cleanup receipts, blockers, per-resource eligibility/reasons, the retention policy,
and a `request_template` when there are eligible worktrees. Save that exact template (or a subset
of its resources) as `cleanup.json`, then apply under the current Advisor:

```sh
hbridge --state-dir /absolute/state --json \
  --advisor-binding adv_CURRENT --advisor-epoch 1 \
  goal cleanup goal_ID --file cleanup.json --idempotency-key cleanup-1

hbridge --state-dir /absolute/state --json cleanup cleanup_ID
```

A request contains schema version `1.0`, the literal retention policy, and 1–200 unique resource
IDs with the preview's SHA-256 fingerprints. It accepts no caller-supplied deletion path, force
flag or evidence-deletion policy. The file and idempotency key must be provided together.

## Removal checks

A matching historical delivery receipt and exact branch/proof refs are required. Undelivered,
failed/cancelled goals and changed/missing delivery refs retain everything. All goals in the
same project must have known inactive Executor/preparation/check lifetimes and no unfinished
worker claims. No acknowledgement can bypass an unknown exit.

Eligible resources are discovered only from goal-linked approved task records and materialized
integration records, at their expected state-directory paths and internal branches. Cleanup
checks retained snapshots, repository/common-directory identity, top-level path, reciprocal Git
worktree registration, symlink ancestors, worktree locks, HEAD/index/status and exact raw file
bytes/modes against the retained tree. Extra ignored files, empty directories, embedded repositories,
submodules, symlink destinations and edits hidden by index flags or clean filters prevent removal.
Unfinished Git operations, additional per-worktree metadata/refs and an ORIG_HEAD not reachable
from the preserved branch also retain the worktree. Normal empty refs directories and reachable
ORIG_HEAD metadata created by Git itself do not imply unretained work. COMMIT_EDITMSG is removable
only when its bytes exactly match the preserved current commit; different drafts stay retained.
File observation failures retain the resource. Git still has the final non-force removal check.

Approved task changes are often left uncommitted by the Executor. These **remain in their
worktrees**, even if the approved tree is safely pinned, because cleanup does not force-delete
working changes. A clean committed child whose files equal its retained approval can be removed;
its commit remains reachable on its preserved internal branch. Caches and external preparation
resources are retained, not recursively garbage-collected. These are intentional retention rules,
not a claim to reclaim all disk space.

The preview is not an authorization cache. Apply checks current ownership, delivery, activity and
fingerprints again before reserving, before each removal and after the durable launch marker.
Changed resources are retained with reasons. After delivery, a removed integration workspace makes
its live workspace/approval observation unavailable, while the historical delivery remains
DELIVERED through its preserved exact refs and evidence.

## Idempotency and interruption

Schema 10 stores cleanup requests and per-resource outcomes. Same key and content reuses that
receipt; different content conflicts. Completed replay never removes a directory recreated later
at the old path. Before deletion, a durable `removing` marker distinguishes an unconfirmed Git
process window from a request that never reached removal:

- `pending`: an explicit same-key retry rechecks everything before continuing.
- `removing` after interruption: replay launches no second removal. If the path is absent, record
  `missing_after_interruption`; otherwise record `unknown` and retain the resource. A new key
  cannot bypass this unresolved hold while the path remains.
- `removed`, `retained`, `unknown`, `missing_after_interruption`: recorded outcomes, not commands
  to repeat. `unknown` gives `needs_attention`; no automatic process guessing or release exists.

The database/evidence and branch references are kept indefinitely by this policy. Backups preserve
committed WAL data; v1–v9 migrations are atomic and backed up. Existing approvals/delivery receipts
and old canonical digests are preserved. Development migrated isolated fixtures only.

These checks serialize cooperating Bridge operations in one state root. They do not lock external
editors or arbitrary same-user Git/filesystem operations; stop external writers before cleanup.
Worktrees and checks are not an OS sandbox. Real installed-host lifecycle and multi-harness
acceptance remain later milestones. Actual offline results are in [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md).
