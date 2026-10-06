# Backlog (not implemented; short entries only)

Completed in 2026-10-06 rounds (kept for reference, do not redo): captured-redacted live
stream fixtures (`tests/fixtures/claude_stream_live/`), local `--max-turns` acceptance
evidence, macOS verification (process groups, `ps` fallbacks, SQLite locking, worktrees),
T3/T4 bounded live smokes and one controlled live repair/resume (same session and context,
2 attempts / 1 repair) — see `docs/VALIDATION_MATRIX.md` and `docs/LIVE_REPAIR_RESULT.md`.

Open:

- User-defined core: one Advisor with one or more cross-harness Executors. Add parent goal /
  child task ownership, Advisor takeover, dependencies and pinned dependent baselines, bounded
  concurrency and aggregate budgets. Reuse existing per-task worktrees/attempts; no new model
  planner inside Bridge. Validate child isolation, correctly attributed feedback and integrated
  goal acceptance offline before claiming multi-executor behavior.
- Explicit project environment preparation for fresh worktrees (dependencies, tests, approved
  non-versioned resources); record failures without assuming the source's runtime state copied.
- Product acceptance follows `docs/PRODUCT_FORM.md` (multi-subscription developers;
  independent runtime with host plugins). Local plugin alpha packaging is complete; it is
  not yet the installed end-to-end experience.
- Codex / ZCode installed-host activation and offline entrypoint checks; persistent runtime
  and project/state discovery so another conversation finds the same task without manual
  instruction transfer. Then separately authorized live entrypoint acceptance.
- Delivery of the approved candidate: export/apply the exact reviewed snapshot, detect source
  changes/conflicts, preserve user edits and record delivery separately from `SUCCEEDED`.
- Host-independent worker lifecycle if promising work continues after the host closes;
  stop at review when no active supervisor, with no hidden model calls or automatic wake-up claim.
- Codex executor adapter as the next execution direction; separately establish a usable
  ZCode execution interface. Host plugin compatibility does not imply executor compatibility.
- Developer installation → guided compatible runtime/plugin setup, update, uninstall with
  state retained; choose a license before distributable release. No package publication yet.
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
