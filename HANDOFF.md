# Handoff

## Repo and revision
- Actual repository / visibility: `CHANxuanyu/harness-bridge` / still **public** at close-out
  (user authorized private; the cloud session had no tool to change visibility)
- Working branch: `claude/new-repo-plan-dn1eac`
- Last code revision: `aeea786`; branch head = docs-only commit on top (`git log -1`), fully
  re-verified (see STATUS.md and the final session message)
- Remote push verified: **no** — visibility could not be changed to private with the tools
  available to the cloud session, and pushing to a public repo was not authorized (STATUS.md →
  Remote). The branch was delivered as a self-contained git bundle.

## Current milestone
- Completed vertical slice: M1 create → run → verify → artifacts → review → SUCCEEDED; M2 repair
  loop + recovery/cancel/verify; M3 Claude adapter offline contract; M4 docs + clean rerun.
- In progress: nothing half-done in the tree.
- Not implemented: live run evidence (T3/T4), amend/cleanup/takeover commands, macOS
  verification, evaluation harness (see docs/BACKLOG.md).

## Verification actually executed
- `scripts/check.sh -q` (Linux container, Python 3.11.17, git 2.43.0, SQLite 3.45.1):
  184 passed, ruff/mypy clean at `aeea786`; final head re-verified, including from a bundle clone.
- `hbridge demo --scenario success|bug-then-repair`: demo_passed true.
- Expected failures and skipped tests: none skipped; the bug-then-repair demo's first attempt is
  *supposed* to fail verification (it is the scenario, not a defect).
- Validation levels reached: T0, T1, T2 (simulated executor / stub binary).
- Live Claude: NOT_RUN
- Live Codex→Claude: NOT_RUN

## Constraints still in force
- Development model: Opus 5.5 (`claude-opus-5-5`, from Claude Code Remote session metadata)
- No extra model API budget; no nested live harness in Cloud
- Runtime mode remains mock unless locally and explicitly authorized
- Development bonus remaining: unknown

## Known issues
- `--max-turns`: documented officially, not listed by local `--help` 2.1.291 (help is
  incomplete by design), never run locally → unknown / pending local confirmation. Live preflight
  holds until confirmed per flag (docs/LOCAL_HANDOFF.md §2 step 4); a run-time rejection stops
  the attempt. Fail-closed, no flag-dropping retries.
- Process-group tests needed an explicit "steady state" handshake: killing the runner before the
  fake executor wrote its first line makes the executor die of a broken pipe (legitimate, but a
  different path). Tests now wait for 2 live group members first.
- Git filters configured in the shared `.git/config` can run during snapshots (documented in
  SECURITY.md); ignored files are outside the observed scope.
- macOS behaviour (no `/proc`, `ps` fallbacks) is untested.

## Next bounded work package
- One concrete goal: reproduce the offline results on the local Mac and record platform rows in
  `docs/VALIDATION_MATRIX.md`.
- Files to inspect: `src/harness_bridge/runner.py` (ps fallbacks), `tests/unit/test_runner.py`,
  `tests/integration/test_recovery.py`.
- First reproduction/test command: `uv sync --frozen && scripts/check.sh`
- Acceptance criteria: same 184 tests pass on macOS or each failure is root-caused and fixed;
  both demos pass; matrix rows carry macOS platform/version.
- Things NOT to do: run real Claude/Codex inference without explicit authorization; add
  `--bare`/skip-permissions; weaken gates or convert failures into skips; copy Linux PASS to
  macOS rows.
- After that: T3 smoke per `docs/LOCAL_HANDOFF.md` §2, only with explicit authorization.
