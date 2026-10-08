# Development rules for this repository

These rules are for anyone (human, Codex, Claude Code) **developing Harness Bridge itself**.
They are not runtime instructions for a supervisor or executor that uses the bridge on another
repository; those live in `examples/supervisor-instructions.md`. Any agent may edit this
project's code directly when asked to.

## Before you change code

1. Read `STATUS.md` and `HANDOFF.md`. `docs/PROJECT_PLAN.md` is the current product scope and
   implementation/acceptance plan; proposed capabilities there are not implemented contracts.
   Since 2026-10-07 (plan v2.0) the product is the **RepoBridge desktop workbench** for native
   Codex/Claude Code sessions (`src/harness_bridge/workbench/`). The Advisor/Executor kernel stays
   available but is not the first-version path. Read `docs/CLOUD_EXECUTION_PLAN.md` only for a
   specific historical V0.1 requirement.
2. Run the offline checks: `scripts/check.sh` (ruff, mypy, pytest without live tests).

## Hard rules

- The bridge never calls a model API itself. No model SDKs, vector stores or agent frameworks as
  dependencies. The workbench's local server is stdlib-only; its window uses the optional `desktop`
  extra (pywebview) and the vendored xterm.js under `workbench/static/vendor` (MIT).
- Default runtime mode is `mock`. Never weaken the live gate (`hbridge run --mode live
  --allow-model-usage` + local config opt-in + no API/provider env + not a cloud/nested
  session). Never add `--bare` or `--dangerously-skip-permissions` to executor invocations.
- The workbench starts native **interactive** CLIs only on an explicit user action, never adds
  `-p`, `--bare`, `--dangerously-skip-permissions` or `--dangerously-bypass-approvals-and-sandbox`,
  never reads/stores login tokens, strips API/provider env vars (reporting names only), and refuses
  real sessions when the App itself runs inside another agent session or a cloud agent environment.
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
