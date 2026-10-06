# Development rules for this repository

These rules are for anyone (human, Codex, Claude Code) **developing Harness Bridge itself**.
They are not runtime instructions for a supervisor or executor that uses the bridge on another
repository; those live in `examples/supervisor-instructions.md`. Any agent may edit this
project's code directly when asked to.

## Before you change code

1. Read `STATUS.md` and `HANDOFF.md`. Read `docs/CLOUD_EXECUTION_PLAN.md` only when you need the
   original requirement for a specific feature.
2. Run the offline checks: `scripts/check.sh` (ruff, mypy, pytest without live tests).

## Hard rules

- The bridge never calls a model API itself. No model SDKs, vector stores, agent frameworks or
  web stacks as dependencies.
- Default runtime mode is `mock`. Never weaken the live gate (`hbridge run --mode live
  --allow-model-usage` + local config opt-in + no API/provider env + not a cloud/nested
  session). Never add `--bare` or `--dangerously-skip-permissions` to executor invocations.
- Tests must not make network requests, read real `~/.claude`/`~/.codex` auth data, or spawn a
  real `claude`/`codex` binary. `tests/live` is excluded by default and needs explicit, local,
  per-run authorization from the user.
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
