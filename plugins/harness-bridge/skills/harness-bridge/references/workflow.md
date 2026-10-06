# CLI workflow (runtime 0.1.0.dev0, protocol 1.0)

In examples below, `hbridge` means the resolved runtime executable. Replace `STATE`, `TASK_ID`
and file paths with observed values; quote paths as needed. Pass arguments as an argv list
when the host supports it. Store task/review files outside the target repo and plugin cache.

## Discover and create

```text
hbridge --state-dir STATE --json doctor --offline
hbridge --state-dir STATE --json list --limit 20
hbridge --state-dir STATE --json status TASK_ID
hbridge --state-dir STATE --json create --task TASK_JSON --idempotency-key UNIQUE_KEY
```

Start from [task.example.json](task.example.json), replacing the goal, paths, exact base ref,
allowed files, verifier commands and limits for the real task. The example is fake/offline
and its fake executor is specifically coupled to the `tagnorm` demo shape, not an arbitrary
repository implementation. It is a schema example, not a ready-to-run user task.

For authorized live work, change executor to `kind: "claude-code"`, `scenario: null`,
`requested_model: "claude-opus-5-5"`, `resume_on_repair: true`, `strict_mcp_config: true`,
`permission_mode: "acceptEdits"`; set `allowed_tools` to the minimum needed, including only
scoped Bash patterns matching the chosen checks (for example `Bash(python3 -B -m unittest:*)`).
Apply the live readiness reference before running. The limits must fit the user's authorization;
the example's two attempts / one repair are not automatic permission to spend them.

`create` resolves the base to a commit and creates an isolated worktree. Same idempotency key
+ same request returns the same task; changed input requires a different task decision, not
reuse of that key. Repository tests can be modified by the executor: keep a required external
acceptance check outside the repo, and preserve its contents/hash across attempts.

## Run once, then inspect

```text
hbridge --state-dir STATE --json run TASK_ID --mode mock
hbridge --state-dir STATE --json run TASK_ID --mode live --allow-model-usage
hbridge --state-dir STATE --json artifacts TASK_ID
hbridge --state-dir STATE --json artifacts TASK_ID --show diff
hbridge --state-dir STATE --json artifacts TASK_ID --show check:acceptance:stderr
```

Choose only the applicable run command, not both. Live use requires all gates; mock use of
the Claude adapter requires a test stub and is not a live run. State `AWAITING_REVIEW` can
include failed/timed-out attempts; check actual outcomes. The artifacts summary is bounded;
request needed individual artifacts and inspect the candidate code to finish the review.

## Snapshot-bound review

Copy `review_template` from the latest summary. Keep schema/task/attempt/version/snapshot
fields intact. Set `verdict`, `findings`, `reviewer_label`, and a fresh `idempotency_key`.

- `approve`: only when the actual change meets requirements and the approval gate passes.
- `changes_requested`: include specific findings and needed fixes, then run the same task
  only if the remaining repair/attempt budget and existing authorization cover it.
- `blocked`: include the concrete external issue; do not turn it into an automatic retry.

A finding has `severity` (`blocking`, `major`, `minor`, `info`), `explanation` (required),
and optional `location`, `requirement`, `requested_change` strings. The last two verdicts
require at least one finding.

```text
hbridge --state-dir STATE --json review TASK_ID --file REVIEW_JSON
hbridge --state-dir STATE --json status TASK_ID
```

If the candidate changed after verification, use `verify TASK_ID` and review the new snapshot.
Do not change files while the executor is running or relax frozen acceptance checks to pass.

## Recovery and stopping

`recover TASK_ID` inspects/reconciles stored state without dispatching another executor.
`cancel TASK_ID` requests termination of the bridge-owned execution. Read their receipts.

`BLOCKED` / `INTERRUPTED` are not permission to restart: inspect `state_details`. A resolve
decision uses `recover TASK_ID --resolve retry|fail`. Only retry after addressing the cause
and confirming authorization/budget. An unknown executor exit requires investigation and
the user's explicit acknowledgement before `--acknowledge-unknown`; never infer it from time.

Exhausted budget → stop and report; do not create a new task to evade it. A changed host still
uses the same state directory and task. Re-read status before final delivery. Retain evidence
and candidate worktree until the user-scoped integration/cleanup is complete.
