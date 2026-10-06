# Backlog (not implemented; short entries only)

Completed in 2026-10-06 rounds (kept for reference, do not redo): captured-redacted live
stream fixtures (`tests/fixtures/claude_stream_live/`), local `--max-turns` acceptance
evidence, macOS verification (process groups, `ps` fallbacks, SQLite locking, worktrees),
T3/T4 bounded live smokes — see `docs/VALIDATION_MATRIX.md`.

Open:

- Live repair / `--resume` verification (one controlled repair; session-id preservation) —
  needs explicit user authorization.
- Live interruption / timeout behaviour with a real executor (offline tests exist; live
  behaviour unverified) — needs explicit user authorization.
- Evaluation harness implementing `docs/EVALUATION_PLAN.md` (T5) — the only place where
  "cheaper/better than direct Opus" can be answered — needs explicit user authorization.
- Verify Codex tool-session teardown: does killing the tool session kill the foreground runner,
  and does the runner's signal handler get a chance to stop its group?
- `amend` command (task_version > 1) with explicit re-approval rules.
- Explicit `cleanup` command for bridge-owned worktrees/branches (ownership-checked, dirty-safe).
- Optional observation of ignored files (e.g. `git status --ignored`) as a risk signal.
- Linux child-subreaper for stronger orphan tracking.
- Supervisor takeover record (stop executor, confirm exit, record takeover).
