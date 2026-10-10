# Engineering foundation V1 — delivery record and evidence

2026-10-10. Cloud Claude Code session, independent task branch. Evidence level: **offline /
synthetic** (stub CLIs, synthetic native histories, temporary sandbox roots, loopback HTTP, Linux
container). Not macOS, WKWebView, IME, clipboard, VoiceOver, official desktop or real-session
acceptance. The local 7825336 acceptance does not transfer to these commits.

## Identity

| | |
|---|---|
| Repository | `https://github.com/CHANxuanyu/harness-bridge` (public, unchanged) |
| Base | `92ed653eaa965ae5355ed3270555e22058888afc` = tip of `origin/codex/existing-session-integration` at start; differs from `78253365266eb5f47f0436dddf4b69522def917e` only in six Markdown files |
| Branch | `claude/engineering-foundation-v1` (new; no other branch rewritten, default branch untouched) |
| Commits | `ca85c33` M1+M2 code/tests · `b9b3de1` M3 code/tests/demo · docs/CI commit on top |
| **Tested code** | **`b9b3de15d23990fbcb7975336d6ea01148e4a593`** (clean worktree; import path verified) |
| HEAD | docs/CI-only commit on top of the tested code (see the PR); `.github/workflows/ci.yml` is in that commit and was not executed |

Frontend-owned files (`workbench/static/**`, `workbench/app.py`, `workbench/native_mac.py`) and
integrator-owned shared files (STATUS, HANDOFF, VALIDATION_MATRIX, DECISIONS, PROJECT_PLAN,
AGENTS) are unchanged: `git diff 92ed653 HEAD -- <those paths>` is empty. PR #3/#4 untouched.

## Audit (reuse points, gaps)

Reused: `HBRIDGE_STATE_DIR`/`--state-dir` and the historical default; the App single-instance lock
(`<state>/workbench/app.lock`, frontend-owned, unchanged); `--port 0`; `--claude-binary`,
`--codex-binary`, `--dev-app-dir`, `--dev-opener` for test launches; the stub harness
`tests/helpers/wb_stub.py`; the store's single receipt choke point `record_delivery`;
`server._run` as the single API dispatch; `build_release.py`/`verify_release.py` for candidates.
Gaps closed: no environment notion or alias protection; no build identity at runtime; no
structured, correlated, privacy-bounded diagnostics (HTTP `log_message` stays disabled because of
`/auth?token=…`; run `output.log`/`events.jsonl`/`stderr.log` contain raw text and are not
reused); no product events, summary or export; CI timeout below the measured suite time.
Pre-existing Linux findings (also at the base): strict mypy fails at `native_mac.py:27`
(platform narrowing) → fixed by mypy `platform = "darwin"`; 6 macOS-gated desktop tests and one
zcode cancel test fail on this container (below).

## Changed files

| File | Change |
|---|---|
| `src/harness_bridge/runtime_env.py` (new) | profiles, isolation checks, test-root lock, build identity, read-only schema probe, `describe` |
| `src/harness_bridge/observability/{__init__,schema,sink,recorder,report}.py` (new) | event dictionary/whitelist, bounded writer, recorder/op context/aliases, summary/trace/bundle |
| `src/harness_bridge/config.py` | `default_state_dir` delegates to the profile resolver (prod unchanged) |
| `src/harness_bridge/workbench/service.py` | profile guard before any I/O; fail-safe recorder; thin wrappers/hooks: start/stop, link/unlink, connect/ready/fatal/run end/turn end, send, delivery transitions (`_store_delivery`), desktop open/return |
| `src/harness_bridge/workbench/server.py` | `_run` opens one operation per API call (route family name only); discovery/history facts |
| `src/harness_bridge/workbench/store.py` | read-only `schema_revision()` |
| `src/harness_bridge/cli.py` | `hbridge env`, `hbridge diag summary|export|trace|config|events` |
| `scripts/repobridge_sandbox.py` (new) | `create`, `launch`, `demo` for isolated test instances |
| `pyproject.toml` | mypy `platform = "darwin"` |
| `.github/workflows/ci.yml` | manual only; runner choice, step timeouts, concurrency, pinned versions, identity, JUnit on failure |
| tests (new) | `tests/unit/test_runtime_env.py`, `test_observability.py`, `test_observability_report.py`, `tests/integration/test_engineering_foundation.py` |
| docs (new) | `ENGINEERING_FOUNDATION.md`, `OBSERVABILITY_EVENTS.md`, this file |

No dependency, lockfile, schema revision (still 4), receipt, writer or resume logic changed.

## Test evidence (this Linux container, Python 3.11.17, uv 0.11.32, 4 CPUs)

The container exports cloud/nested agent markers; as on a GitHub runner (which has none), they
were removed from the **pytest process** environment only (`env -u CLAUDE_CODE_REMOTE -u
CLAUDE_CODE_REMOTE_SESSION_ID -u CLAUDECODE`). Product gates are unchanged. The sandbox builds its
instance environment from an allowlist, so it never inherits them either.

| Run | Code | Result | Time |
|---|---|---|---|
| Baseline full suite (`pytest -m "not live"`) | `92ed653` (separate worktree) | **1000 passed, 7 failed** | 308.32 s |
| Final `scripts/check.sh -q --durations=15` | **`b9b3de1`** clean worktree | ruff ✓, format ✓ (204 files), strict mypy ✓ (65 files); **1027 passed, 7 failed**, 0 skipped | 339.24 s (5m39s); script 344 s |
| New tests only | `b9b3de1` | **27 passed** (unit 17, integration 10 — includes the demo) | ~27 s |
| 6 desktop tests + new tests with the darwin capability gate simulated in a wrapper process | base / `b9b3de1` | 6/6 base; **16/16** branch | 2.9 s / 19.2 s |
| `hbridge demo` success, bug-then-repair; `scripts/repobridge_sandbox.py demo` | `b9b3de1` | exit 0 / 0 / 0 | 7 s total |

The 7 failures are identical at base and final: 6 tests whose desktop path is gated to macOS
(`目前只在 macOS 上提供`) and `test_zcode_stub_flow.py::test_cancel_stops_both_transport_and_peer`
(fails consistently in this container; the stopped child remains signalable, consistent with no
zombie reaping). Not skipped, not modified. 1034 tests total = 1007 at base + 27 new.

Behavioural acceptance mapped to tests (`tests/integration/test_engineering_foundation.py` unless
noted):

* Demo (link synthetic outside Codex session → submit → `unknown` → second send refused
  `delivery_unknown` → exact native clientId proof → `sent` → stop → export → summary): one run,
  one native `turn/start`, attachment and native ID retained; trace shows
  `None→queued→sending→unknown→sent`; bundle has exactly 5 members.
* Two test instances isolated; same root, symlink alias of a root, state outside root, foreign
  HOME refused; refused start creates nothing; lock released on close.
* Synthetic secret in URL/query (`/auth?…&probe=`, history `q=`/`token=`, conversation, delivery),
  headers, cookie, body text, project path, attachment name/content, native error text containing
  the native thread ID, a 500 exception message: absent from logs, bundle, summary JSON and CSV
  (also native ID, sandbox path, launch token, client ID, local session ID).
* Diagnostics disabled (`HBRIDGE_DIAGNOSTICS=0`: no directory created) and failing (directory
  replaced by a file) give the same receipts, text, attachments, run count and `turn/start` count
  as the reference; recorder construction failure does not block start.
* Replayed old `unknown` receipt after `sent`, three history re-reads and a restart add no
  transition; summary: sent 1, unknown 0, unknown_later_confirmed_sent 1, refused submissions 1,
  `task_completion: not_observable`.
* Rotation (size bound, count, age pruning, 0600/0700), torn tail line, three concurrent writer
  processes (1,200 lines, 0 corrupt, per-writer order kept), ENOSPC with drop report, busy lock +
  full queue (submits return < 0.5 s), closed sink (`tests/unit/test_observability.py`).
* Desktop open (darwin gate simulated, recording opener) and return recorded; continuation
  `not_observable`.
* Loopback only (repository network guard + connect audit); no socket/HTTP imports in the new
  modules; SQLite tables and `schema_revision` 4 unchanged, no new event kinds in SQLite.
* CLI: `hbridge env`, `diag summary` (JSON/CSV, env filter), `export` (0600, refuses overwrite),
  `trace --msg`, `config` (env switch precedence), `events`; diag commands never create
  `bridge.sqlite3`.

## Shortest reproduction

```sh
git fetch origin claude/engineering-foundation-v1 && git checkout b9b3de15d23990fbcb7975336d6ea01148e4a593
uv sync --frozen
uv run --frozen python scripts/repobridge_sandbox.py demo            # prints the JSON report, exit 0
uv run --frozen pytest -q tests/unit/test_runtime_env.py tests/unit/test_observability.py \
  tests/unit/test_observability_report.py tests/integration/test_engineering_foundation.py
scripts/check.sh -q                                                  # full offline check
```

If reusing another virtualenv: `PYTHONPATH=/absolute/path/to/this/checkout/src` and confirm with
`python -c "import harness_bridge; print(harness_bridge.__file__)"`.

## Sanitized samples (from the demo at `b9b3de1`)

```json
{"v":1,"ts":"2026-10-10T17:41:04.780Z","seq":15,"proc":"p_cc96ac4a","env":"test","ver":"0.1.0.dev2","sha":"b9b3de15d239","level":"warning","component":"delivery","event":"delivery.state","op":"op_31b9324de657","session":"s_894caa1957","run":"r_c3a0b380a4","msg":"m_a144fd0ac8","reason":"native_process_exited","stream":"diag","attrs":{"harness":"codex","from_state":"sending","to_state":"unknown","evidence":"native_protocol","latency_ms":26}}
{"v":1,"ts":"2026-10-10T17:41:04.814Z","seq":19,"proc":"p_cc96ac4a","env":"test","ver":"0.1.0.dev2","sha":"b9b3de15d239","level":"warning","component":"http","event":"op.end","op":"op_00d2f4868b1c","name":"session.send","session":"s_894caa1957","outcome":"error","duration_ms":0,"code":"STATE_CONFLICT","reason":"delivery_unknown","error_type":"BridgeError","stream":"diag","attrs":{"http_status":409}}
{"v":1,"ts":"2026-10-10T17:41:04.898Z","seq":20,"proc":"p_cc96ac4a","env":"test","ver":"0.1.0.dev2","sha":"b9b3de15d239","level":"info","component":"delivery","event":"delivery.state","op":"op_11095b0ebeb6","session":"s_894caa1957","run":"r_c3a0b380a4","msg":"m_a144fd0ac8","stream":"diag","attrs":{"harness":"codex","from_state":"unknown","to_state":"sent","evidence":"native_history_client_id","latency_ms":145}}
```

The `unknown→sent` record carries the operation that observed the proof (the refresh); it joins
the original send through the same message alias (`hbridge diag trace --msg m_…`).

Summary CSV excerpt: `meta,contains_test_data,True` · `product,link.completed,1` ·
`product,connect.ready_latency_ms.p50,69` · `product,delivery.submitted,1` ·
`product,delivery.final_state.sent,1` · `product,delivery.final_state.unknown,0` ·
`product,delivery.unknown_later_confirmed_sent,1` · `product,task_completion,not_observable`.

## Not verified / limits

* macOS host, native window, WKWebView, IME, clipboard, VoiceOver, official desktop clients
  (desktop path exercised only with a simulated darwin gate and a recording opener).
* Real Claude Code/Codex sessions, real state directories, real HOME/auth: never touched.
* GitHub Actions: workflow parsed locally, **not run** (no paid pipeline triggered); macOS runner
  timing is an estimate from the maintainer's Mac (16m47s) and this container (5m39s).
* `build_info` SHA for an installed wheel is `unknown` by design; candidate identity then comes
  from `manifest.json`. No desktop app packaging exists or is claimed.
* Product metrics only cover what the bridge observes; native-internal model calls, tokens and cost
  are `unknown`; Claude Code has no durable receipt (`no_receipt`).
* A batch that fails after partially writing can count a few written lines as dropped
  (conservative counter, never duplicates or reorders).
* Budget: this platform exposes no reliable usage/dollar figure to the session, so spend could
  not be measured; one baseline and two full-suite runs were made (plus focused runs).

## Integration notes for Codex

Suggested DECISIONS lines: (1) environments are runtime profiles (`HBRIDGE_ENV`), prod default
unchanged; (2) diagnostics are whitelist-structured JSONL outside SQLite, product events opt-in;
(3) mypy targets darwin. Suggested VALIDATION_MATRIX rows: test-profile isolation; secret-marker
non-leakage; sink failure parity; duplicate/late receipt counting; summary/export; loopback-only.
Consolidate STATUS/HANDOFF from this file; re-run on macOS before any acceptance claim.
