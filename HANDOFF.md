# Handoff

## Repo and revision
- Actual repository / visibility: `CHANxuanyu/harness-bridge` / **public** at session start
  (plan expected private; visibility is the user's decision)
- Working branch: `claude/new-repo-plan-dn1eac`
- Last verified code revision: `1cc850b` (fresh clone, frozen install, full offline suite, demos)
- Latest local commit: the docs-only commit after `1cc850b` (`git log -1`)
- Remote push verified: **no** — held pending the user's visibility decision (see STATUS.md)

## Current milestone
- Completed vertical slice: M1 create → run → verify → artifacts → review → SUCCEEDED; M2 repair
  loop + recovery/cancel/verify; M3 Claude adapter offline contract; M4 docs + clean rerun.
- In progress: nothing half-done in the tree.
- Not implemented: live run evidence (T3/T4), amend/cleanup/takeover commands, macOS
  verification, evaluation harness (see docs/BACKLOG.md).

## Verification actually executed
- `scripts/check.sh -q` (Linux container, Python 3.11.17, git 2.43.0, SQLite 3.45.1):
  169 passed, ruff/mypy clean; repeated from a fresh clone of `1cc850b`.
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
- `--max-turns` is not listed by `claude --help` 2.1.291 → live preflight fails by design until
  verified locally (docs/LOCAL_HANDOFF.md §2 step 4). Fail-closed.
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
- Acceptance criteria: same 169 tests pass on macOS or each failure is root-caused and fixed;
  both demos pass; matrix rows carry macOS platform/version.
- Things NOT to do: run real Claude/Codex inference without explicit authorization; add
  `--bare`/skip-permissions; weaken gates or convert failures into skips; copy Linux PASS to
  macOS rows.
- After that: T3 smoke per `docs/LOCAL_HANDOFF.md` §2, only with explicit authorization.
