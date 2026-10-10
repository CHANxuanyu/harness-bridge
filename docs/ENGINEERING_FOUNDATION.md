# Engineering foundation: environments, versions, diagnostics, offline checks

2026-10-10. Base `92ed653eaa965ae5355ed3270555e22058888afc` (`codex/existing-session-integration`;
code identical to the offline-accepted candidate `7825336`). Branch `claude/engineering-foundation-v1`.
Event dictionary and privacy boundary: [OBSERVABILITY_EVENTS.md](OBSERVABILITY_EVENTS.md).
Evidence: [ENGINEERING_FOUNDATION_RESULT.md](ENGINEERING_FOUNDATION_RESULT.md).

Nothing here changes the native-session contract: receipts, single writer, same-ID resume,
`sent`/`not_sent`/`unknown` semantics, drafts/attachments and the live/cloud gates are untouched.
The bridge still never calls a model API; no account, service, API key or paid dependency was added.

## 1. Environments (dev / test / prod)

dev/test/prod separate **runtime environments and promotion stages**, not long-lived branches.
Work continues on short feature branches, fixed commits and verifiable candidate artifacts.

`HBRIDGE_ENV` selects the profile (`src/harness_bridge/runtime_env.py`). Unset = `prod` with the
historical behaviour, so `repobridge`, `hbridge app`, `--state-dir` and `HBRIDGE_STATE_DIR` work
exactly as before and the current state directory is not moved, opened or upgraded by this change.

| | prod (default) | dev | test |
|---|---|---|---|
| State root | `--state-dir` › `HBRIDGE_STATE_DIR` › `$XDG_STATE_HOME/harness-bridge` (unchanged) | default `…/harness-bridge-dev`; may not resolve to or contain the prod root | must be inside `HBRIDGE_TEST_ROOT` (default `<root>/state`) |
| DB / logs / lock | `<state>/workbench.sqlite3`, `<state>/observability/`, `<state>/workbench/app.lock` | same layout under the dev root | same layout under the test root, plus `<root>/.hbridge-test-root.lock` |
| Port | `--port`, default 0 (any free loopback port) | same | same (each instance gets its own) |
| Native CLI HOME/history/login | the user's own | **shared with the user** unless HOME/CODEX_HOME/CLAUDE_CONFIG_DIR are overridden (reported as `native_env: shared|custom`) | HOME and every set CODEX_HOME/CLAUDE_CONFIG_DIR/XDG_* must be inside the root (`native_env: isolated`) |
| CLI binaries | PATH discovery or explicit | same | explicit stubs inside the root only; discovery forced off |
| Desktop apps / opener | /Applications, `/usr/bin/open` | same | lookup dir and opener inside the root only |
| Product events | off unless enabled | off unless enabled | off unless enabled (tests enable explicitly) |

Separating only SQLite is not isolation: in dev the native CLIs still read the developer's own
history and login. Use the test profile (or set the native home variables) for full separation.

Test-profile refusals happen **before** any directory is created or database opened
(`PREFLIGHT_FAILED`, reason `environment_refused`): missing/relative root; root that is `/`,
contains the real home, or overlaps the real prod/dev state, `~/.claude` or `~/.codex` (derived
from the password database, so an overridden HOME cannot hide them); state, HOME or a native home
variable outside the root (symlink and bind-mount aliases are resolved: realpath + inode);
binaries/app dirs/opener outside the root; a second instance on the same root (or a symlink
alias of it); a root nested inside another running test root. Two test instances on two roots
run side by side with separate state, logs, locks and ports. The existing App single-instance
lock (`<state>/workbench/app.lock`) is unchanged.

### Reproducible dev/test entry points

```sh
# Inspect what a start would use (read-only; never creates/upgrades a database):
uv run --frozen hbridge env --json
HBRIDGE_ENV=dev uv run --frozen hbridge env --json

# dev: separate RepoBridge state, real CLIs/logins (explicit user action as before):
HBRIDGE_ENV=dev uv run --frozen repobridge

# test: sandbox root with stub CLIs, synthetic history, fake Applications, recording opener.
uv run --frozen python scripts/repobridge_sandbox.py create /tmp/rb-test-a
uv run --frozen python scripts/repobridge_sandbox.py launch /tmp/rb-test-a      # prints launch URL
uv run --frozen python scripts/repobridge_sandbox.py demo                       # end-to-end demo
```

`launch` runs the unchanged App entry (`--no-open --state-dir … --claude-binary … --codex-binary …
--dev-app-dir … --dev-opener …`) with an allowlisted environment (PATH, locale, TMPDIR plus the
sandbox variables). No real token, API/provider variable, HOME or cloud/nested marker is
inherited; the product gates themselves are unchanged for prod/dev.

## 2. Version identity

Every Workbench start records (diagnostics `app.start`) and `hbridge env` prints: environment and
its source, package version, exact git SHA of the imported code and dirty flag (`code_source:
git-checkout`), Python, OS family, actual and expected workbench schema revision and the
observability settings. An installed wheel has no checkout: SHA and dirty are `unknown`/`null`,
never guessed; the candidate's `manifest.json` (`source_revision`) is then the identity. These
fields are not added to `/api/state` or the conversation UI.

### Candidate artifacts (existing scripts, scope checked)

`scripts/build_release.py` / `scripts/verify_release.py` remain the only candidate path. They
build from a clean commit: runtime wheel (whole `harness_bridge` package incl. `workbench/` and its
static files), the Advisor plugin marketplace zip, docs and a `git archive` source tarball; the
verifier checks the source revision, checksums and wheel/source equality. Their acceptance text
still points at the P7 plugin/runtime closeout. They are **not** a macOS `.app` build, signing or
installer; desktop packaging is not claimed here. No release, tag, publish or install was run.

## 3. Promotion dev → test → prod (manual) and rollback limits

1. **dev**: feature branch; `scripts/check.sh` green on the exact commit; `hbridge env` shows
   `code_dirty: false`.
2. **test**: the same SHA passes the offline suite and `scripts/repobridge_sandbox.py demo`
   (synthetic only); a candidate built with `build_release.py` verifies with `verify_release.py`;
   the integrator records SHA, counts and duration. Native IME/clipboard/VoiceOver/official desktop
   and real sessions remain separate, explicitly authorized acceptance on macOS.
3. **prod**: the user decides to run that SHA/candidate against the real state directory.
   Before a schema-changing candidate, the user copies the state directory while the App is
   closed (`workbench.sqlite3` with `-wal`/`-shm`).

Rollback: code can be rolled back to an earlier SHA/candidate, **the database cannot**. Workbench
migrations are additive and run on open; an older binary refuses a newer `schema_revision`
(`workbench schema revision N is not supported`). Restoring data means restoring the user's own
copy. Nothing here migrates, rolls back or edits a real database automatically; this change adds
no schema revision (still 4) and stores diagnostics outside SQLite.

## 4. Diagnostics, product events and operation records

Three things, kept apart (details in [OBSERVABILITY_EVENTS.md](OBSERVABILITY_EVENTS.md)):

* **Fault diagnostics** `<state>/observability/diagnostics/diag*.jsonl` — on by default, local.
* **Product events** `<state>/observability/product/events*.jsonl` — **off by default**.
* **Operation correlation** — every API call gets `op_…`; service events (connect, delivery
  transitions, run end) carry the same `op` or link through local run/message aliases.
  `hbridge diag trace --op/--msg/--run/--session` reconstructs one operation.

```sh
hbridge diag config [--diagnostics on|off] [--product-events on|off]   # settings.json, 0600
hbridge diag summary [--format json|csv] [--since …Z] [--until …Z] [--env prod|dev|test|all]
hbridge diag export [--out new.zip]          # explicit, local only, never uploaded
hbridge diag trace --op op_…                  # or --msg m_… / --run r_… / --session s_…
hbridge diag events                           # event dictionary
```

Environment switches (override settings): `HBRIDGE_DIAGNOSTICS=0|1`, `HBRIDGE_PRODUCT_EVENTS=0|1`,
`HBRIDGE_DIAG_LEVEL=debug|info|warning|error`. Summary/export default to the current
`HBRIDGE_ENV` and report records of other environments as excluded, so test data is never mixed
into usage numbers. The raw HTTP request log stays disabled (`/auth?token=…`).

Failure behaviour: `record()` never raises or blocks; a bounded queue (1,000) feeds one writer
thread; full queue, closed recorder, unwritable/read-only/full disk and a busy lock drop records
and count them (`diag.dropped` is written on recovery). Business outcomes, receipts and run counts
are identical with diagnostics enabled, disabled or failing (tested).

## 5. Offline checks and CI

* `scripts/check.sh` unchanged: ruff, format, strict mypy, `pytest -m "not live"`.
* `pyproject.toml`: mypy `platform = "darwin"` (product platform). Before this, strict mypy failed
  on Linux at `workbench/native_mac.py:27` (unreachable under Linux platform narrowing) — also on
  the untouched base.
* `.github/workflows/ci.yml` stays **manual** (`workflow_dispatch`), read-only token, no secrets,
  frozen lockfile. Added: runner choice (`macos-14` default, `ubuntu-24.04`), per-step timeouts
  (install 10, lint 5, types 5, tests 35, demos 5; job 60) from measured durations (16m47s Mac,
  5m08s Linux container), concurrency group with cancel-in-progress, pinned
  `actions/checkout@v4.2.2` and uv `0.11.32`, `persist-credentials: false`, build identity step,
  per-stage failure, `--durations=25`, JUnit report kept 7 days on failure, sandbox demo.
  Not run from here (no paid pipeline triggered); the YAML was parsed locally.
* Known Linux results at the base: 6 desktop tests fail because the desktop handoff is gated to
  macOS (`目前只在 macOS 上提供`), and in this cloud container
  `test_zcode_stub_flow.py::test_cancel_stops_both_transport_and_peer` fails (a stopped child is
  still signalable; consistent with container init not reaping). They are reported, not skipped.

Enabling PR checks later (suggestion only; not applied, no branch-protection/billing change):

```yaml
on:
  workflow_dispatch: {...}
  pull_request:
    branches: [codex/existing-session-integration]
    paths: ["src/**", "tests/**", "scripts/**", "pyproject.toml", "uv.lock", ".github/workflows/**"]
```

keep `permissions: contents: read`, no secrets, `macos-14`, and the concurrency group.

## 6. LangSmith / OpenTelemetry (not integrated)

Not connected now. Pricing checked 2026-10-10 (langchain.com/pricing): Developer is one free
seat with 5,000 base traces/month; Plus is $39 per seat/month plus usage. LangSmith accepts
non-LangChain applications through OpenTelemetry (docs.langchain.com/langsmith/trace-with-opentelemetry),
so it is not LangChain-only. It would still only see what RepoBridge observes: the official CLIs'
internal model calls, tokens and cost stay `unknown` and their auth/billing path is not changed.

Future mapping if the user opts in (no exporter skeleton is shipped):

| RepoBridge field | OpenTelemetry |
|---|---|
| `op` | one span per operation (`trace_id` new per op, `span_id` = op) |
| `name`, `component` | span name / `code.namespace` |
| `duration_ms`, `ts` | span start/end |
| `outcome`, `code`, `reason` | `status`, `error.type`, attribute `repobridge.reason` |
| `session`/`run`/`msg` aliases | attributes `repobridge.session`, `.run`, `.message` (still aliases) |
| `connect.*`, `delivery.state`, `run.end` | child spans or span events linked by run/message alias |
| `env`, `ver`, `sha` | resource attributes `deployment.environment`, `service.version`, `vcs.revision` |

An exporter would read the same whitelisted records, require explicit opt-in and endpoint
configuration by the user, and never send record types that are not in the dictionary.
