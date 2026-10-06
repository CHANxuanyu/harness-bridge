# Status

_Last updated 2026-10-06 (multi-subscription product definition and local plugin alpha)._

## Current state

- **Experimental prototype (V0.1, milestones M0–M4).** The live path has now been exercised
  for real in bounded initial smokes and one controlled repair/resume task on 2026-10-06.
- **Verified so far**
  - T0–T2 offline suite (184 tests) and both demos: green on Linux (cloud) and macOS (local).
  - T3 live single-harness initial smoke: **PASS** — exactly 2 real invocations (one
    `--max-turns` flag-acceptance probe, one bridge-run slugify task), bridge verification
    passed including the external acceptance check, snapshot-bound approve → SUCCEEDED
    (`docs/LOCAL_SMOKE_HANDOFF.md`).
  - T4 single-run smoke: **PASS** — the local Codex session (supervisor model `gpt-6-astra`,
    evidenced by local turn-context metadata) performed create → run → artifacts → diff
    review → snapshot-bound approve → SUCCEEDED through the bridge, one initial attempt,
    zero repairs (`docs/T4_SMOKE_RESULT.md`).
  - Controlled live repair/resume: **PASS** — two real attempts (diagnosis-only initial
    against a seeded bug, then one repair), failed verification → changes_requested →
    matching `--resume` → passed verification → approve → SUCCEEDED. Session id and an
    unrepeated conversation mnemonic preserved; 10 repo tests + 9 external cases passed
    (`docs/LIVE_REPAIR_RESULT.md`).
  - Redacted stream logs from all three tasks are now offline parser regression samples
    (`tests/fixtures/claude_stream_live/`, provenance recorded; no model was invoked to
    build them).
- **Not verified (do not assume)**
  - real interruption recovery, live timeout/turn-limit enforcement,
    multi-task or long-task stability;
  - T5 comparative evaluation — in particular **whether delegating through the bridge is
    cheaper or better than using Opus directly is NOT established** by these smokes;
  - subscription quota remaining: **unknown** (usage figures are executor-reported; CLI cost
    numbers are API-equivalent estimates, not bills or subscription usage).
- **Standing constraints:** development model `claude-opus-5-5`; default runtime mode `mock`;
  the live gate (`--mode live --allow-model-usage` + local config opt-in + clean environment)
  unchanged; repository **public** by the user's explicit choice — do not change visibility,
  no license added yet.
- **Product direction:** developers with multiple coding-agent subscriptions; independent
  local runtime, shared task evidence, host-specific plugin entrypoints. The user confirmed
  this audience (ZCode/GLM + Claude Code + Codex). Final use and delivery boundaries are in
  `docs/PRODUCT_FORM.md`; the runtime still has only a Claude Code live executor.

## Implemented

| Area | State |
|---|---|
| TaskSpec / ReviewDecision contracts, versioned, strict | done, tested |
| SQLite store, CAS transitions + same-transaction events, idempotent create/review | done, tested |
| Bridge-owned worktree from pinned base SHA; dirty source refused; user checkout untouched | done, tested |
| Runner: own process group, concurrent drain, bounded capture, timeout, cancel, signals, confirmed-exit | done, tested (Linux, macOS) |
| Fake executor (11 scenarios) + adapter | done, tested |
| Independent verifier, snapshot fingerprint, manifest, scope/secret checks, redaction, approval gate | done, tested |
| Repair loop with attempt/repair budgets | done; offline tests + one controlled live repair/resume PASS |
| recover / cancel / verify; crash windows fail closed; no auto re-dispatch | done, tested (real crash injection + signals; Linux, macOS) |
| Claude Code adapter: command builder, stream parser, classification, resume binding, live gate + per-flag evidence preflight, run-time argument-rejection stop | done, offline contract + live smoke evidence (T3/T4) |
| Captured-live-redacted stream fixtures + parser regression tests (from the T3/T4 logs) | done |
| CLI: doctor, create, run, status, list, artifacts, verify, review, recover, cancel, demo | done |
| Offline demos `success`, `bug-then-repair` | pass |
| Manual offline CI workflow (`workflow_dispatch`) | written, never run |
| Codex / ZCode plugin source package, shared supervisor Skill, host catalogs | alpha; static/copy/CLI-contract checks pass; Codex catalog discovery pass; installed activation and ZCode loading NOT_RUN |

## Tests actually executed (chronological, by environment)

- **Linux cloud container** (Python 3.11.17, git 2.43.0, SQLite 3.45.1), 2026-10-06:
  `scripts/check.sh` → 184 passed at `aeea786`; earlier 169 at `1cc850b`; both demos pass.
- **macOS local** (26.6.2 arm64, CPython 3.11.16 via uv, git 2.50.1, SQLite 3.53.1/3.51.0),
  2026-10-06, `fcbd21a`: `scripts/check.sh` → **184 passed / 0 skipped / 0 failed**; targeted
  `test_runner.py` + `test_recovery.py -v` → 28 passed; doctor and both demos pass.
- **Live smokes, same day:** T3 (2 real calls) and T4 (1 real executor attempt) as recorded
  in `docs/LOCAL_SMOKE_HANDOFF.md` and `docs/T4_SMOKE_RESULT.md`.
- **Offline consolidation at `470f5b0`:** 8 new parser regression tests; full check was
  reported clean (192 tests), corroborated at takeover by 192 cached nodeids and no cached failures.
- **Controlled repair/resume, this round at `470f5b0`:** exactly 2 real executor attempts,
  one repair; final independent verification and approval passed. No new smoke/probe/demo.
- **Affected offline checks after this round’s additions:** `scripts/check.sh
  tests/contracts/test_claude_adapter_live.py
  tests/integration/test_cli.py::test_doctor_offline_is_non_inference
  tests/integration/test_claude_stub_flow.py::test_doctor_reports_flag_evidence_not_unsupported`
  → 12 passed; ruff, format and mypy clean. Two new regression cases are included.
  The earlier 192-test full suite was not repeated; no claim of a new 194-test full-suite run.
- **Plugin alpha checks (no model):** skill-creator validator passed; copied package has
  internally resolving references and matching manifests/catalogs; bundled task validates
  against the runtime model; 16 documented command forms parse without dispatch. Codex
  0.160.0 recognized the temporarily registered catalog and version; source removed after
  inspection, no plugin installed. See `docs/PLUGIN_ALPHA_RESULT.md`.

## Findings worth knowing

- `--max-turns`: official docs declare it; `--help` of CLI 2.1.291 does not list it; on this
  installation the CLI **accepted** the flag in a real minimal call (2026-10-06). That is
  parse-level evidence, **not** proof that the turn limit is enforced in every scenario. The
  live preflight consumed per-flag confirmation from the isolated test state dir only; a
  run-time CLI rejection still stops the attempt, never a retry without the flag.
- The two Bash permission denials in each initial smoke show the scoped tool allowance
  intercepting out-of-scope commands. Permission rules are one layer — **not** OS-level
  sandbox isolation, and not executor failures.
- Process-group tests need the explicit "steady state" handshake (see HANDOFF known issues).
- Git filters configured in the shared `.git/config` can run during snapshots (SECURITY.md).

## History (cloud delivery, 2026-10-06 — superseded)

- The bridge was developed in a Claude Code Cloud session through `aeea786` (code) plus a
  docs-only head `fcbd21a`; the offline suite and demos were verified there and from a clone
  of an exported bundle. The user authorized making the repository private, but the cloud
  session's GitHub tooling had no visibility operation, so the branch was delivered as a
  self-contained git bundle and not pushed.
- **Superseded the same day:** the user chose to keep the repository **public**; branches are
  pushed (`claude/new-repo-plan-dn1eac` == `fcbd21a`; `local/glm-macos-validation` carries all
  later work). Clone via `gh repo clone CHANxuanyu/harness-bridge`. Do not change visibility.

## Next

Product work now follows `docs/PRODUCT_FORM.md`: installed-host entrypoint/continuation
acceptance, delivery of approved changes back to a project, lifecycle robustness, then a
second execution adapter and distributable installation. Plugin activation/offline setup
checks do not need another model call. Do not claim the prototype is the final product.

Real interruption/timeout validation and T5 evaluation (`docs/EVALUATION_PLAN.md`) still
need explicit bounded authorization before any real call. The prior repair allowance is used.
Controlled repair/resume is complete for one bounded task; do not rerun it merely to hand off.
Engineering backlog (no model needed): `docs/BACKLOG.md`.
