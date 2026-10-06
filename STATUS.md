# Status

- Milestone: **M1 (minimal vertical slice) complete**; M2 in progress.
- Validation level reached: T0 (lint/types/schema), T1 (unit), T2 (offline integration with a
  simulated executor). T3/T4/T5: **NOT_RUN**.

## Implemented and tested (offline)
- TaskSpec/ReviewDecision contracts (pydantic, `extra="forbid"`, versioned).
- SQLite store with CAS transitions + same-transaction events; idempotent create.
- Bridge-owned git worktree from a pinned base SHA; dirty source checkout refused.
- Generic runner: own process group, concurrent drain, bounded capture, timeout/TERM/KILL,
  confirmed-exit flag.
- Fake executor (real subprocess, 11 scenarios) + adapter; independent verifier; artifact
  manifest bound to a snapshot fingerprint; scope/secret checks; approval gate.
- CLI: `doctor`, `create`, `run`, `status`, `list`, `artifacts`, `review`, `demo`.
- Demos: `success` and `bug-then-repair` both pass (fresh-process status read, user checkout
  unchanged, no model calls).

## Tests actually run
- `scripts/check.sh -q` on Linux / Python 3.11.17: ruff clean, mypy strict clean,
  **124 passed** (0 skipped, live tests excluded by marker; there are none yet).

## Blockers / constraints
- Repository is **public** although the plan expected private; push held until the user
  confirms (see HANDOFF.md). Remote push status: **not pushed**.
- Development model: `claude-opus-5-5` (session metadata). Budget remaining: unknown.

## Next
- M2: `verify`, `recover`, `cancel`; tests R02–R06; repair limit; bug-then-repair as a test.
