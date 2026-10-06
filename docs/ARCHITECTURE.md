# Architecture

The product relationship is **one Advisor → one or more Executors across harnesses**.
The existing term `supervisor` means Advisor. The Advisor inspects the repo, decomposes work,
dispatches task prompts and reviews/integrates results; the deterministic Bridge prepares
workspaces and manages execution/evidence. Plugins expose this capability to the Advisor.
Both roles are agent sessions. The Advisor is the current external session, not a model
service created by Bridge. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the target session,
workspace, coordination and delivery contracts; [PRODUCT_FORM.md](PRODUCT_FORM.md) is a summary.

The execution path below remains the foreground task core. The first P1 coordination slice
now adds project/goal registration, child links, Advisor takeover epochs, aggregate attempt/repair
budgets and one shared project slot. See [COORDINATION.md](COORDINATION.md) for the implemented
contract and migration. Dependency plans, full goal control, workers and integrated review are
still pending; this is not complete V1 coordination.

```text
External Advisor / supervisor (user's current coding-agent session)
  │  writes TaskSpec / ReviewDecision files, calls `hbridge` in a shell
  ▼
hbridge CLI (cli.py) ── JSON receipts on stdout, diagnostics on stderr
  ▼
Bridge core (service.py) — deterministic, never calls a model API
  ├─ models.py        versioned contracts (pydantic, extra="forbid")
  ├─ coordination.py  goal/session contracts, project registration, epoch/budget guards
  ├─ store.py         SQLite single authority; migration 1→2 with a restorable backup
  ├─ migrations.py    additive project/goal/child/takeover/event tables
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

## Current V0.1 foreground runner

The runner is the only party that can prove it owns the executor's process group. A crash of the
runner therefore leaves the task in `STARTING/RUNNING/VERIFYING`; `recover` turns that into
`INTERRUPTED (outcome unknown)` without signalling anything and without re-dispatching. There is
no daemon in V0.1; a shell `&` is not treated as a reliable detached worker.
The V1 plan includes a managed worker acceptance milestone; it is not implemented by adding
an Advisor/Executor role label. Human CLI diagnostics remain possible without turning the
human into the product's Advisor session.

## Exactly-once is not claimed

Spawning a process and committing a SQLite transaction cannot be one atomic step. The design
records `STARTING` + a launch token before spawning and the pid after; a crash in between is
reported as unknown and blocks automatic retries (tested with real crash injection).

## Evidence separation

`bridge_observed` (exit status, process facts, verifier results, snapshot) and
`executor_reported` (claims, summary, usage as reported) are separate manifest sections. Only
`bridge_observed` feeds the approval gate.
