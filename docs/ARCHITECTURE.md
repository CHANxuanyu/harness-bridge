# Architecture

The product relationship is **one Advisor → one or more Executors across harnesses**.
The existing term `supervisor` means Advisor. The Advisor inspects the repo, decomposes work,
dispatches task prompts and reviews/integrates results; the deterministic Bridge prepares
workspaces and manages execution/evidence. Plugins expose this capability to the Advisor.
See [PRODUCT_FORM.md](PRODUCT_FORM.md) for the target role and multi-executor contract.

The implementation below is the current **single-child-task** building block. Parent-goal
coordination, dependencies, aggregate budgets and integrated-result review are not implemented.
Several flat task records do not provide that coordination.

```text
External Advisor / supervisor (user's current coding-agent session, or a person)
  │  writes TaskSpec / ReviewDecision files, calls `hbridge` in a shell
  ▼
hbridge CLI (cli.py) ── JSON receipts on stdout, diagnostics on stderr
  ▼
Bridge core (service.py) — deterministic, never calls a model API
  ├─ models.py        versioned contracts (pydantic, extra="forbid")
  ├─ store.py         SQLite: tasks, attempts, events, verification_runs, reviews (single authority)
  ├─ state.py         state machine + attempt outcome classes
  ├─ workspace.py     source checks, bridge-owned worktree, temp-index snapshots, diffs
  ├─ runner.py        foreground subprocess runner (own process group, drain, limits, signals)
  ├─ verification.py  frozen acceptance commands via the same runner
  ├─ policy.py        path globs, secret paths, symlink escape, redaction
  ├─ artifacts.py     atomic files, bounded/redacted logs, ≤24 KiB summaries
  ├─ config.py        state dir, config.toml, live gate
  └─ adapters/
       ├─ base.py            ExecutorAdapter protocol, TaskPacket, process-level classification
       ├─ fake.py            adapter for the offline fake executor
       ├─ fake_executor.py   standalone fake executor process (stdlib only)
       └─ claude_code.py     Claude Code CLI adapter (offline + bounded live initial/repair evidence)
```

## One attempt, end to end

1. `create`: validate the TaskSpec, refuse a dirty source checkout, resolve `base_ref` to a SHA,
   freeze the normalized spec (+ digests) in SQLite, create worktree
   `<state>/worktrees/<task_id>` on branch `hbridge/<task_id>` → `READY`.
   The adapter receives this path and launches the executor with it as cwd; the executor
   does not need to choose a folder or create a worktree. Generic environment bootstrap
   is not implemented.
2. `run`: CAS `READY → STARTING` and insert the attempt (launch token, invocation digest, runner
   identity) in one transaction. Build the invocation (pure). Spawn in a new session/process
   group; on spawn, CAS `STARTING → RUNNING` with pid/pgid. Drain and parse output; enforce the
   wall timeout; honour cancel requests and runner signals.
3. Classify the attempt from **bridge observations first** (spawn failure, unconfirmed exit,
   cancel, interrupt, timeout), then from the adapter's protocol view (final result, errors).
4. Settled outcomes → `VERIFYING`: snapshot (fingerprint), run frozen verifiers, snapshot again
   (any change invalidates the run), scope/secret checks, bounded redacted diff, manifest written
   atomically → `AWAITING_REVIEW`.
5. `review`: must bind to the current attempt, task_version and snapshot digest; the candidate is
   re-snapshotted. `approve` passes only if every gate holds → `SUCCEEDED`.
   `changes_requested` → `READY` with findings for the next attempt (or `FAILED` when the budget
   is spent). `blocked` → `BLOCKED`.

## Why foreground

The runner is the only party that can prove it owns the executor's process group. A crash of the
runner therefore leaves the task in `STARTING/RUNNING/VERIFYING`; `recover` turns that into
`INTERRUPTED (outcome unknown)` without signalling anything and without re-dispatching. There is
no daemon in V0.1; a shell `&` is not treated as a reliable detached worker.

## Exactly-once is not claimed

Spawning a process and committing a SQLite transaction cannot be one atomic step. The design
records `STARTING` + a launch token before spawning and the pid after; a crash in between is
reported as unknown and blocks automatic retries (tested with real crash injection).

## Evidence separation

`bridge_observed` (exit status, process facts, verifier results, snapshot) and
`executor_reported` (claims, summary, usage as reported) are separate manifest sections. Only
`bridge_observed` feeds the approval gate.
