# Backlog (not implemented; short entries only)

- Capture redacted real `claude -p --output-format stream-json` samples locally → `captured-live`
  fixtures; adjust parser if the real schema differs.
- Verify `--max-turns` on the installed CLI (2.1.291 does not list it in `--help`).
- Verify macOS: process groups, `ps`-based liveness, cancel, worktree paths, SQLite locking.
- Verify Codex tool-session teardown: does killing the tool session kill the foreground runner,
  and does the runner's signal handler get a chance to stop its group?
- `amend` command (task_version > 1) with explicit re-approval rules.
- Explicit `cleanup` command for bridge-owned worktrees/branches (ownership-checked, dirty-safe).
- Optional observation of ignored files (e.g. `git status --ignored`) as a risk signal.
- Linux child-subreaper for stronger orphan tracking.
- Supervisor takeover record (stop executor, confirm exit, record takeover).
- Evaluation harness implementing `docs/EVALUATION_PLAN.md` (after T3/T4 exist).
