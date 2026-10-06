# Status

_Last updated 2026-10-06 (Claude Code Cloud session)._

- **Milestone:** M0–M3 complete; M4 close-out complete (docs, clean-checkout rerun, manual CI).
  This is an **experimental prototype**, not a usable real bridge yet: the live path has never
  run.
- **Last verified code revision:** `1cc850b` — fresh `git clone` + `uv sync --frozen` +
  `scripts/check.sh` + both demos, Linux, Python 3.11.17. Later commits are docs only.
- **Validation levels reached:** T0, T1, T2 (offline, simulated executor / stub binary).
  **T3 live Claude: NOT_RUN. T4 live Codex→Claude: NOT_RUN. T5: NOT_RUN.**

## Implemented
| Area | State |
|---|---|
| TaskSpec / ReviewDecision contracts, versioned, strict | done, tested |
| SQLite store, CAS transitions + same-transaction events, idempotent create/review | done, tested |
| Bridge-owned worktree from pinned base SHA; dirty source refused; user checkout untouched | done, tested |
| Runner: own process group, concurrent drain, bounded capture, timeout, cancel, signals, confirmed-exit | done, tested (Linux) |
| Fake executor (11 scenarios) + adapter | done, tested |
| Independent verifier, snapshot fingerprint, manifest, scope/secret checks, redaction, approval gate | done, tested |
| Repair loop with attempt/repair budgets | done, tested |
| recover / cancel / verify; crash windows fail closed; no auto re-dispatch | done, tested (real crash injection + signals) |
| Claude Code adapter: command builder, stream parser, classification, resume binding, live gate + `--help` preflight | done, **offline contract only** |
| CLI: doctor, create, run, status, list, artifacts, verify, review, recover, cancel, demo | done |
| Offline demos `success`, `bug-then-repair` | pass |
| Manual offline CI workflow (`workflow_dispatch`) | written, never run |

## Tests actually run
- `scripts/check.sh -q` → ruff clean, ruff format clean, mypy `--strict` clean,
  **169 passed, 0 skipped, 0 failed** (live tests excluded by marker; none exist).
- Same result from a fresh clone of `1cc850b`. During M2 the suite ran 5× consecutively green
  after one test timing assumption was fixed (the code was correct; see HANDOFF known issues).
- `hbridge demo --scenario success` and `--scenario bug-then-repair` → `demo_passed: true`.

## Findings worth knowing
- Installed Claude CLI **2.1.291 does not list `--max-turns` in `--help`**; live preflight
  refuses until it is verified locally and allowed in `config.toml`.
- In this cloud session the live gate is closed for 6 independent reasons (cloud markers, nested
  session, `ANTHROPIC_BASE_URL` present, no config opt-in, no review flag, no
  `--allow-model-usage`) — as intended.

## Remote
- Repository `CHANxuanyu/harness-bridge` is **public** (GitHub API, session start); the plan
  expected private. Pushing was **held** pending the user's decision. Remote push status:
  **not pushed** (see the final session message for any later change).

## Development model / budget
- `claude-opus-5-5` (configured and last-served model from Claude Code Remote session metadata).
- Development budget remaining: **unknown** (not observable; no spend figures claimed).

## Next
See `HANDOFF.md` → next bounded work package (local reproduction on macOS, then T3 smoke).
