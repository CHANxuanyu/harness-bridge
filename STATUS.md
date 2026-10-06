# Status

_Last updated 2026-10-06 (Claude Code Cloud session, final close-out)._

- **Milestone:** M0–M3 complete; M4 close-out complete (docs, clean-checkout rerun, manual CI).
  This is an **experimental prototype**, not a usable real bridge yet: the live path has never
  run.
- **Last code revision:** `aeea786` (flag-evidence correction). The final branch head adds
  documentation only; the full offline checks and both demos were re-run on that final head
  and from a clone of the exported bundle (results in the final session message).
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
| Claude Code adapter: command builder, stream parser, classification, resume binding, live gate + per-flag evidence preflight, run-time argument-rejection stop | done, **offline contract only** |
| CLI: doctor, create, run, status, list, artifacts, verify, review, recover, cancel, demo | done |
| Offline demos `success`, `bug-then-repair` | pass |
| Manual offline CI workflow (`workflow_dispatch`) | written, never run |

## Tests actually run
- `scripts/check.sh -q` → ruff clean, ruff format clean, mypy `--strict` clean,
  **184 passed, 0 skipped, 0 failed** at `aeea786` (live tests excluded by marker; none exist).
- Earlier: 169 passed from a fresh clone of `1cc850b`. During M2 the suite ran 5× consecutively green
  after one test timing assumption was fixed (the code was correct; see HANDOFF known issues).
- `hbridge demo --scenario success` and `--scenario bug-then-repair` → `demo_passed: true`.

## Findings worth knowing
- `--max-turns` evidence, kept separate: **official docs** declare it (CLI reference, checked
  2026-10-06, which also states `--help` does not list every flag); **local `--help`** of CLI
  2.1.291 does not list it; **local real verification**: none (no live run). Status on this
  installation: **unknown / pending local confirmation** — not unsupported, not supported. Live
  preflight holds dispatch until the flag is listed or confirmed per flag in `config.toml`; a
  run-time CLI rejection stops the attempt (`BLOCKED cli_rejected_argument`), never a retry
  without the flag.
- In this cloud session the live gate is closed for 6 independent reasons (cloud markers, nested
  session, `ANTHROPIC_BASE_URL` present, no config opt-in, no review flag, no
  `--allow-model-usage`) — as intended.

## Remote
- The user authorized switching the repository to private (2026-10-06). The GitHub tooling
  available to this cloud session (GitHub MCP server) has no repository-settings / visibility
  operation, so visibility could not be changed. As instructed, no other credential or route
  was used (no `gh` CLI with the ambient token, no raw API calls with `GITHUB_TOKEN`).
- Result: repository still **public**, branch **not pushed**. Delivered instead as a
  self-contained git bundle of the branch (SHA-256 reported with the file, outside the repo).

## Development model / budget
- `claude-opus-5-5` (configured and last-served model from Claude Code Remote session metadata).
- Development budget remaining: **unknown** (not observable; no spend figures claimed).

## Next
See `HANDOFF.md` → next bounded work package (local reproduction on macOS, then T3 smoke).
