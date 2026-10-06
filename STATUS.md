# Status

- Milestone: **M2 (repair loop + basic recovery) complete**; M3 next.
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
- CLI: `doctor`, `create`, `run`, `status`, `list`, `artifacts`, `verify`, `review`,
  `recover`, `cancel`, `demo`.
- M2: changes_requested repair loop with attempt/repair budgets; crash windows fail closed
  (INTERRUPTED, no auto re-dispatch); explicit `recover --resolve retry|fail`; cancel only signals
  the runner's own process group; verification resumes after a crash without re-running the
  executor; candidate changes invalidate evidence until `verify` re-binds it.
- Demos: `success` and `bug-then-repair` both pass (fresh-process status read, user checkout
  unchanged, no model calls).

## Tests actually run
- `scripts/check.sh -q` on Linux / Python 3.11.17: ruff clean, mypy strict clean,
  **140 passed** (0 skipped; live tests excluded by marker, none exist yet). The full suite
  was run 5 times in a row green after fixing one timing assumption in a test.

## Blockers / constraints
- Repository is **public** although the plan expected private; push held until the user
  confirms (see HANDOFF.md). Remote push status: **not pushed**.
- Development model: `claude-opus-5-5` (session metadata). Budget remaining: unknown.

## Next
- M3: Claude CLI adapter (pure command builder, stream-json parser, classification,
  no-API preflight, docs-derived fixtures with provenance).
