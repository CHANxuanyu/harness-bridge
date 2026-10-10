# Development rules for this repository

These rules are for anyone (human, Codex, Claude Code) **developing Harness Bridge itself**.
They are not runtime instructions for a supervisor or executor that uses the bridge on another
repository; those live in `examples/supervisor-instructions.md`. Follow the file ownership below when developing this project.

## Before you change code

1. Read `STATUS.md` and `HANDOFF.md`. `docs/PROJECT_PLAN.md` is the current product scope and
   implementation/acceptance plan; proposed capabilities there are not implemented contracts.
   Since 2026-10-07 (plan v2.0) the product is the **RepoBridge desktop workbench** for native
   Codex/Claude Code sessions (`src/harness_bridge/workbench/`). The Advisor/Executor kernel stays
   available but is not the first-version path. Read `docs/CLOUD_EXECUTION_PLAN.md` only for a
   specific historical V0.1 requirement.
2. Run the offline checks: `scripts/check.sh` (ruff, mypy, pytest without live tests).
   If reusing a virtualenv installed from another worktree, set an absolute `PYTHONPATH` to the
   intended checkout's `src`; detached test workers change cwd, so a relative path can test a
   different checkout and invalidate invocation fingerprints.

## Hard rules

- The bridge never calls a model API itself. No model SDKs, vector stores or agent frameworks as
  dependencies. The workbench's local server is stdlib-only; its window uses the optional `desktop`
  extra (pywebview) and the vendored xterm.js under `workbench/static/vendor` (MIT).
- Default runtime mode is `mock`. Never weaken the live gate (`hbridge run --mode live
  --allow-model-usage` + local config opt-in + no API/provider env + not a cloud/nested
  session). Never add `--bare` or `--dangerously-skip-permissions` to executor invocations.
- The workbench starts native CLIs only on an explicit user action. Terminal view: the interactive
  CLI. Conversation view: only the harness's own structured protocol — Claude Code
  `-p --input-format stream-json --output-format stream-json --permission-prompt-tool stdio`
  (the SDK control protocol, permission answers from the user) and `codex app-server`. Never add
  `--bare`, `--dangerously-skip-permissions`, `--dangerously-bypass-approvals-and-sandbox`,
  `bypassPermissions` or Codex full access (`never` + `danger-full-access`). Model, effort and
  permission mode are passed only when the user explicitly chose them in the App, only with the
  harness's own requests/flags (Claude: `set_model`, `apply_flag_settings` `effortLevel`,
  `set_permission_mode`, or `--model/--effort/--permission-mode` for the terminal; Codex:
  `thread/start`/`thread/resume`/`turn/start` parameters, or `-m/-c/-a/-s`), validated against the
  catalog the CLI itself reported (never a hard-coded list), and shown as in force only after the
  harness reports it back; a refused choice stays refused (no silent substitute, no send with
  another model). Never send a message or answer a permission/question the user did not; never
  read/store login tokens or answer an auth-token refresh; strip API/provider env vars (reporting
  names only); refuse real sessions when the App itself runs inside another agent session or a
  cloud agent environment.
- The conversation view is built only from native structured messages and native history (Codex
  `thread/turns/list`, the Claude Code session transcript). Never parse terminal output into chat.
  Changing view releases the connection at an idle point and reconnects with the native resume;
  never two writers, never a silent fork. Official desktop continuation uses only
  `claude --desktop --resume <id>` and `codex://threads/<id>`; never edit vendor storage.
- Tests must not make network requests (loopback to a test-owned server is allowed), read real
  `~/.claude`/`~/.codex` auth data, or spawn a real `claude`/`codex` binary (use stub harnesses).
  `tests/live` is excluded by default and needs explicit, local, per-run authorization from the user.
- Do not delete failing tests, convert them to skips, widen path policies or turn `unknown`
  into `passed` to get green. Report what actually ran.
- Label evidence honestly: synthetic fixture, docs-derived fixture, offline integration
  (simulated executor), live single-harness (T3), live dual-harness (T4) are different levels.
- Bridge-run git commands use argv lists (never `shell=True`), `--` before paths, NUL-separated
  output, hooks disabled, no external diff / textconv.
- Never print or persist secret values; report env vars as present/absent.

## Workflow

- Small vertical slices; each milestone ends with tests run, `STATUS.md` + `HANDOFF.md` +
  `docs/VALIDATION_MATRIX.md` updated, and one logical commit.
- Record non-obvious implementation choices as one line in `docs/DECISIONS.md`.
- Commits are authored by the repository owner (Xuanyu CHAN); agents do not add themselves as
  authors or co-authors.

## Frontend/backend ownership (2026-10-09)

- Codex implements backend and integration directly: Python except `workbench/app.py` and
  `workbench/native_mac.py`, native protocols, storage/migrations, HTTP routes, backend tests,
  scripts/dependencies and AGENTS.md.
- Opus owns `workbench/static/**`, those two desktop-shell files, screenshots and new UI-only
  `tests/**/test_workbench_ui_*.py`. Coordinate native-hook/API changes before editing owner files.
- Codex is sole writer of STATUS.md, HANDOFF.md, docs/VALIDATION_MATRIX.md, docs/DECISIONS.md and
  docs/PROJECT_PLAN.md. Opus records progress/requests in commits and its PR; Codex consolidates
  at integration. Do not concurrently edit different sections of these shared files.
- Start backend work from common handoff ef75a625 in its independent worktree; frontend remains
  in its existing worktree. No force switches, cleanup or implicit default-branch merge.
- Existing-session contract: docs/EXISTING_SESSIONS_API.md. Frontend requests are inputs until
  agreed there. Use temporary state, never upgrade the user's running database. The prior
  W6–W8 real-turn allowance is exhausted; no implicit renewal.
