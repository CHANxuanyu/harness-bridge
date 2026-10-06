# Integrated verification and Advisor review — second P4 slice

Implemented 2026-10-06. After [freezing and materializing](INTEGRATION.md) the approved child
versions, the current Advisor explicitly runs the frozen total-goal checks and reviews that exact
candidate. Passing checks alone is not approval. Integration approval is not delivery: goal status
still reports `delivery: not_implemented`; branch delivery and `READY_TO_DELIVER` selection remain
future P4 work. Neither checking nor reviewing dispatches an Executor.

## Explicit commands

```sh
hbridge --state-dir /absolute/state --json \
  --advisor-binding adv_CURRENT --advisor-epoch 1 \
  integration verify integration_ID --idempotency-key acceptance-v1

hbridge --state-dir /absolute/state --json integration status integration_ID

hbridge --state-dir /absolute/state --json \
  --advisor-binding adv_CURRENT --advisor-epoch 1 \
  integration review integration_ID --file review.json

hbridge --state-dir /absolute/state --json integration cancel integration_ID

hbridge --state-dir /absolute/state --json \
  --advisor-binding adv_CURRENT --advisor-epoch 1 \
  integration recover integration_ID
```

`verify` is foreground finite work. Commands run sequentially from the frozen IntegrationSpec;
Executor output never supplies commands. The record and project hold are committed before launch.
Same-key replay returns the existing run, including running/failed/interrupted results, without
execution. Replay still requires the current Advisor and a goal that is not terminating; status
remains readable independently. A new key explicitly runs the entire frozen suite again, only after the project is idle
and every old checker exit is confirmed. There is no automatic or partial check retry. Maximum ten
verification runs per integration is separate from Executor attempt/repair/time/turn ceilings;
checks consume none of those Executor reservations. Each frozen command retains its timeout
(maximum 3,600 seconds); each integration has at most 50 commands.

Checks use the existing process-group runner, bounded redacted capture (64 KiB head/tail budget per
stream, plus truncation marker), one-second kill grace and confirmed group-exit observation.
A required failure, timeout, invalid cwd, spawn failure or remaining background process cannot
pass. An optional failure can be a warning, but even an optional unknown exit holds the project and
prevents approval. Logs/manifest failures cannot produce approval evidence.

The environment follows the preparation whitelist: separate HOME/XDG directories, PATH, locale
and temporary-directory settings, without inherited provider/auth variables or user harness config.
Obvious direct harness executables and credential argv are refused before freezing, and checked
again at launch for older frozen records. These remain **trusted local
commands, not an OS sandbox**: scripts, PATH tools, Git filters and external files are the user's
responsibility; the bridge does not prove arbitrary script behavior or prevent all network access.
The trust labels distinguish external acceptance from repository-owned tests; neither is a model's
self-report.

## Candidate and evidence binding

Before dispatch and after confirmed exit, the bridge checks the frozen goal membership, retained
input refs, repository identity, candidate pin, expected HEAD/branch and owned worktree. A fresh-index
snapshot detects tracked/untracked changes (including assume-unchanged edits). Existing ignored-file
limitations remain. Checks may produce ignored build artifacts, but cannot change the observed
composed candidate and then have that changed tree approved. A changed candidate is `invalidated`;
newly approved child versions and a new integration are needed. Manual candidate edits cannot be
blessed by repeating verification. Conflict-repair task binding remains a later slice.

The run fingerprint binds integration/goal/request, ordered approved inputs, candidate commit/tree
and the complete frozen verification configuration. Each check records argv, cwd, trust, required
flag, outcome, exit confirmation and redacted stream metadata/digests. The manifest binds the run,
candidate, pre/post fingerprints, check results and warnings. Review re-reads these bounded evidence
files and verifies their digests. Changed/missing files, changed candidate or changed required inputs
refuse approval, even when the recorded command exit was zero. Evidence lives at
`<state>/artifacts/integrations/<integration_id>/<run_id>/manifest.json` and
`<check-id>.stdout.log` / `<check-id>.stderr.log` alongside it. The status receipt gives the owned
candidate path and fixed base SHA; the Advisor inspects its code/diff with ordinary local file/Git
tools before submitting a decision. An integration-specific diff viewer is not added here.

`integration status` preserves the frozen `verification` array and adds `verification_run`,
`review`, `approval_current`, `approval_blockers`, and `review_template`. The template supplies the
exact current run/fingerprint; the Advisor must inspect the candidate and evidence and choose a new
idempotency key and decision. It is not a generated judgment.

IntegrationReview 1.0 is strict JSON:

```json
{
  "schema_version": "1.0",
  "integration_id": "integration_ID",
  "verification_run_id": "ivr_CURRENT",
  "snapshot_digest": "EXACT_FINGERPRINT_FROM_STATUS",
  "verdict": "approve",
  "findings": [],
  "reviewer_label": "current-advisor",
  "idempotency_key": "review-v1"
}
```

Verdicts are `approve`, `changes_requested`, or `blocked`. Negative decisions require findings;
approval cannot contain blocking/major findings. All decisions require a completed run with
confirmed exits and its exact ID/fingerprint. Approval additionally requires passed verification
and intact evidence. A failed approval gate records a durable rejected receipt before returning
`APPROVAL_GATE_FAILED`; same-key replay returns that same rejection. Changing a decision under an
existing key is `IDEMPOTENCY_CONFLICT`.

Accepted decisions set the integration phase to `APPROVED`, `CHANGES_REQUESTED`, or `BLOCKED`.
Negative decisions do not dispatch repair or spend Executor budget. Approval belongs to the current
Advisor binding/epoch and exact verification run. A new run clears the current review; takeover,
goal termination, changed inputs/workspace/logs invalidate `approval_current`. Historical receipt
replay never restores current approval. `phase: APPROVED` is historical state; consumers must use
`approval_current` and its blockers to assess present validity. The goal remains ACTIVE or
NEEDS_ATTENTION, rather than claiming overall delivery is complete.

## Cancellation, crash recovery and exclusive admission

An integration checker is project-exclusive across goal-linked work in one state root, including
when two Executor slots are configured. Child dispatch, preparation, manual reverify and resumed
verification use the shared admission guard. Admission also refuses an already active/unknown child.
Standalone legacy tasks and independent state directories retain the previously documented limits;
this is not a machine-wide scheduler or filesystem isolation.

Emergency `integration cancel` needs no Advisor claim; it sets a durable flag. The owning runner
observes that flag (or CLI signal/goal cancel/fail), stops its own process group and records whether
exit was confirmed. Goal termination remains pending while any integration checker is running or
has an unknown exit, exposed through `pending_stop_integrations`. Unknown exits retain the exclusive
project hold; cancel acknowledgement alone does not release it.

Recovery requires the current Advisor (including on a stopping goal). A living owner is reported
without interference; uncertain owner liveness refuses recovery. Once the owner is provably dead:

- A persisted checkpoint with confirmed exit and no active process becomes `interrupted` and releases
  the hold. This includes a reservation before the launch window or a completed check checkpoint.
- The launch window is persisted **before** spawning. Any uncertain window or recorded active process
  becomes `unknown` and keeps the hold, even if the process appears gone later. Recovery never sends
  signals to guessed/reused PIDs, reruns commands or infers an unobserved successful result.

There is no manual acknowledgement-based release or automated rescue for an unknown checker yet.
Evidence and workspaces stay retained. Resolving unknown ownership safely belongs to later audited
recovery/retention work. An interrupted completed-check checkpoint is not enough for approval:
explicit verification with a new key is required to collect a full current run.

## Persistence and evidence level

Schema 8 adds `integration_verifications` and `integration_reviews`, reusing backed-up atomic
v1–v7 migrations. Prior candidate records, pins, contracts and replay digests are preserved. This
milestone uses isolated fixture state; no real user/live state was migrated.

Offline tests cover total-goal mismatch despite individually approved children, success/review,
required and optional failures, stale/tampered evidence, takeover, duplicate request races,
confirmed cancellation, unknown holds, actual crash injection before/after spawn/checkpoint,
project exclusion, bounded isolated logs, local check limits, CLI round trips and v7 upgrade.
Real harness interruption/parallelism and installed-host lifecycle remain unverified; no new live
allowance was used. Full run counts and limitations are in [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md).
