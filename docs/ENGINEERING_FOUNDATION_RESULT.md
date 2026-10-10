# Engineering foundation V1 — delivery record and evidence

2026-10-10. Cloud Claude Code session, independent task branch, draft PR #5. Evidence level:
**offline / synthetic** (stub CLIs, synthetic native histories, temporary sandbox roots,
loopback HTTP, Linux container). Not macOS, WKWebView, IME, clipboard, VoiceOver, official desktop
or real-session acceptance (all NOT_RUN). The local native acceptance of the fixed candidate
`78253365266eb5f47f0436dddf4b69522def917e` does not transfer to any commit on this branch.

## Identity

| | |
|---|---|
| Repository | `https://github.com/CHANxuanyu/harness-bridge` (public, unchanged) |
| Base | `92ed653eaa965ae5355ed3270555e22058888afc` = tip of `codex/existing-session-integration` at start (differs from `7825336` only in six Markdown files) |
| Branch / PR | `claude/engineering-foundation-v1` → draft PR #5 (base `codex/existing-session-integration`) |
| Round 1 commits | `ca85c33` M1+M2 · `b9b3de1` M3 (round-1 tested code) · `0092165` CI/docs (reviewed HEAD) |
| Round 2 fix commit | **`3186dbca86b64866b0ede02d10be201442ae1863`** — EF1–EF4 + gate test (code and tests) |
| **Tested code (round 2)** | **`3186dbca86b64866b0ede02d10be201442ae1863`** (clean detached worktree, `uv sync --frozen`, import path printed as the worktree's `src/`) |
| Final HEAD | the docs-only commit on top of `3186dbc` (see PR #5); differences after testing: `docs/ENGINEERING_FOUNDATION*.md`, `docs/OBSERVABILITY_EVENTS.md` only |

Frontend-owned files: only `workbench/app.py` changed, in round 2, for the EF3 preflight and
startup cleanup the PM authorized for this round. `workbench/static/**` and
`workbench/native_mac.py` are untouched, and no window or input code changed. Integrator-owned
shared files (STATUS, HANDOFF, VALIDATION_MATRIX, DECISIONS, PROJECT_PLAN, AGENTS) are unchanged.
PR #3/#4 untouched; no merge, tag, release, install, real credentials, real database or running
instance was touched.

## Round 2 — review findings and fixes (`3186dbc`)

| Finding | Fix | Evidence (tests) |
|---|---|---|
| **EF1 P1** dev reused a custom prod path via `HBRIDGE_STATE_DIR` | Ownership marker `environment.json`: dev/test accept only absent, empty or same-marked state; unmarked existing state is refused (inherited variable, `--state-dir`, alias); prod writes no marker and refuses dev/test-marked state; checks read-only, marker is the first write | `test_runtime_env.py::test_dev_and_test_refuse_an_existing_unmarked_state_directory` (synthetic legacy DB `schema_revision=4`, full byte+mtime snapshot unchanged), `::test_new_dev_and_test_directories_are_claimed_and_owners_kept_apart`; app entries below |
| **EF2 P2** nested roots refused in one start order only | Directory `flock`s: exclusive on root, shared on possible-root parents; no lock files | `::test_root_locks_refuse_nesting_in_both_orders_and_aliases` (parent→child, child→parent, same, alias, sibling, stale old lock file), `::test_concurrent_starts_never_hold_nested_or_identical_roots` (8× parent/child race, 8× same-root race, one sibling pair; separate processes), `::test_killed_holder_releases_its_root` (SIGKILL) |
| **EF3 P2** `app.run` created state dir and `app.lock` before refusing | Preflight + test-root lock in `app.run` before any write; refusal printed, exit 4; lock handed to Workbench; ExitStack releases lock file, Workbench and root lock on midway failure | `test_engineering_foundation.py::test_app_entries_refuse_before_any_directory_lock_or_database[repobridge|hbridge app]` (outside-root state, inherited/explicit/alias legacy prod with snapshot, held root; sentinels prove Workbench/server never constructed; 5 refusals each), `::test_app_entries_start_cleanly_and_release_everything_after_a_midway_failure[…]` (clean start/stop through the real entry; synthetic bind failure → root lock, App lock and Workbench released) |
| **EF4 P2** same client_id in two sessions merged | Message alias = HMAC(session, client ID); op link and latency start keyed the same, first submit wins; summary keys `(session, msg)`; records v2, v1 re-keyed and flagged | `test_observability.py::test_message_identity_is_session_scoped_and_first_submit_wins`, `test_observability_report.py::test_same_client_id_in_two_sessions_counts_twice`, `::test_v1_records_are_rekeyed_by_session_and_flagged`, `test_engineering_foundation.py::test_same_client_id_in_two_sessions_stays_separate_end_to_end` (stub: A sent, B unknown, reuse, 2× history re-read → submitted 2, sent 1, unknown 1, unknown_later_confirmed_sent 0; business receipts stay A sent / B unknown) |
| Item 4: product gate with markers | Sandbox now inherits cloud/nested markers; stub fixture with a marker present | `::test_cloud_and_nested_markers_still_refuse_native_starts[CLAUDE_CODE_REMOTE|CLAUDECODE]`: start and send → `PREFLIGHT_FAILED`, no run, no `thread/resume`, no `turn/start`, `connect.start` refused at step `preflight`; sandbox demo with markers present exits 3 |

Observation (not changed, out of scope): read-only native discovery (`thread/list`) is not behind
the start/send gate; this matches the existing design (no model call, no resume, no send).

## Test evidence

Host for every run: this Linux container (4 CPUs), Python 3.11.17, uv 0.11.32. The container
exports three cloud/nested agent markers (`CLAUDE_CODE_REMOTE`, `CLAUDE_CODE_REMOTE_SESSION_ID`,
`CLAUDECODE`). **Full-suite runs below were made with exactly those three removed from the pytest
process environment** (`env -u …`); the product gate is unchanged and is tested with markers
present (above). These runs are offline/synthetic, not macOS.

| Run | Code / condition | Result | Time |
|---|---|---|---|
| Baseline | `92ed653`, separate worktree, `pytest -m "not live" -q`, markers removed (`check.sh` would stop earlier: strict mypy fails on Linux at base, `native_mac.py:27`) | 1000 passed, **7 failed**, exit 1 | 308.32 s |
| Round 1 final | `b9b3de1`, clean worktree, `scripts/check.sh -q`, markers removed | ruff ✓, format ✓, mypy ✓; 1027 passed, **7 failed**; **check.sh exit 1** | 339.24 s |
| **Round 2 final** | **`3186dbc`**, clean worktree, `scripts/check.sh -q -rf --durations=10`, markers removed | ruff ✓, format ✓ (207 files), strict mypy ✓ (65 files, darwin target); **1041 passed, 7 failed**, 0 skipped; **check.sh exit 1** | 364.42 s (script 371 s) |
| Round 2 focused regression | working tree = `3186dbc` code: 4 new test files + workbench, delivery, existing-session, server, conversation, settings, CLI, bootstrap, unit suites | 138 passed, 6 failed (the 6 macOS-gated tests) | 107 s |
| Desktop tests with the darwin capability gate simulated in a wrapper process (tests unmodified) | `3186dbc`: the 6 desktop tests + `test_engineering_foundation.py` | **23/23 passed** (round 1: base 6/6, `b9b3de1` 16/16) | 24.5 s |
| Demos | `3186dbc`: `hbridge demo` success / bug-then-repair; sandbox demo markers removed; sandbox demo markers present | exit 0 / 0 / 0 / **3** (`PREFLIGHT_FAILED`, expected) | — |

Totals: 1048 tests at `3186dbc` = 1007 at base + 41 new (unit 24, integration 17).

The **same 7 failures** at base, `b9b3de1` and `3186dbc` (not skipped, not modified):

| Test | Failure | Attribution |
|---|---|---|
| `tests/integration/test_existing_sessions.py::test_paging_refresh_and_desktop_roundtrip_retains_identity[claude-code]` | `BridgeError: 目前只在 macOS 上提供` raised by `open_in_desktop` | desktop handoff gated to `sys.platform == "darwin"` |
| `…::test_paging_refresh_and_desktop_roundtrip_retains_identity[codex]` | same | same |
| `tests/integration/test_workbench_conversation.py::test_open_in_claude_desktop_releases_first_and_holds_until_return` | `assert … '还没有对话' in '目前只在 macOS 上提供'` | same |
| `…::test_open_in_codex_uses_the_existing_thread_link` | `BridgeError: 目前只在 macOS 上提供` | same |
| `…::test_desktop_unavailable_reasons_and_cli_desktop_command` | `assert '没有在' in '目前只在 macOS 上提供'` | same |
| `tests/integration/test_workbench_server.py::test_conversation_routes_stream_events_and_validation` | `assert (412 == 412 and '没有在' in '目前只在 macOS 上提供')` | same |
| `tests/integration/test_zcode_stub_flow.py::test_cancel_stops_both_transport_and_peer` | `Failed: DID NOT RAISE ProcessLookupError` after a confirmed cancel | **cause pending verification** (reproduced 3× at base here; a zombie-reaping hypothesis is unconfirmed) |

The six desktop tests pass when only the platform default of the capability gate is set to
darwin in a wrapper process, which supports the attribution but is not macOS evidence.

Typing: `pyproject.toml` sets mypy `platform = "darwin"`, a target-platform choice. Strict mypy
therefore checks the macOS branches on any host and **does not type-check Linux-only paths**.

CI: `.github/workflows/ci.yml` **NOT_RUN** (no remote pipeline triggered; YAML parsed locally).

## Reproduction

```sh
git fetch origin claude/engineering-foundation-v1
git checkout 3186dbca86b64866b0ede02d10be201442ae1863
uv sync --frozen
uv run --frozen pytest -q tests/unit/test_runtime_env.py tests/unit/test_observability.py \
  tests/unit/test_observability_report.py tests/integration/test_engineering_foundation.py
uv run --frozen python scripts/repobridge_sandbox.py demo   # outside an agent/cloud session
scripts/check.sh -q                                         # on Linux: exits 1 with the 7 above
```

Inside an agent or cloud session the demo and the workbench suites are refused by the product
gate unless the markers are removed for that run; state that condition with any result. When
reusing another virtualenv, set `PYTHONPATH=/absolute/path/to/checkout/src` and confirm with
`python -c "import harness_bridge; print(harness_bridge.__file__)"`.

## Sanitized samples (round 2 demo, code `3186dbc`, record schema v2; worktree had docs-only edits)

```json
{"v":2,"ts":"2026-10-10T19:10:39.958Z","seq":15,"proc":"p_4d76d771","env":"test","ver":"0.1.0.dev2","sha":"3186dbca86b6","level":"warning","component":"delivery","event":"delivery.state","op":"op_6905f7605db5","session":"s_304d933bd4","run":"r_78f918f1ac","msg":"m_c9a67baf83","reason":"native_process_exited","stream":"diag","attrs":{"harness":"codex","from_state":"sending","to_state":"unknown","evidence":"native_protocol","latency_ms":18}}
{"v":2,"ts":"2026-10-10T19:10:40.000Z","seq":19,"proc":"p_4d76d771","env":"test","ver":"0.1.0.dev2","sha":"3186dbca86b6","level":"warning","component":"http","event":"op.end","op":"op_ceeda5023f5c","name":"session.send","session":"s_304d933bd4","outcome":"error","duration_ms":0,"code":"STATE_CONFLICT","reason":"delivery_unknown","error_type":"BridgeError","stream":"diag","attrs":{"http_status":409}}
{"v":2,"ts":"2026-10-10T19:10:40.068Z","seq":20,"proc":"p_4d76d771","env":"test","ver":"0.1.0.dev2","sha":"3186dbca86b6","level":"info","component":"delivery","event":"delivery.state","op":"op_32446a6018d8","session":"s_304d933bd4","run":"r_78f918f1ac","msg":"m_c9a67baf83","stream":"diag","attrs":{"harness":"codex","from_state":"unknown","to_state":"sent","evidence":"native_history_client_id","latency_ms":128}}
```

The `unknown` and `sent` records share `m_c9a67baf83` = HMAC(session, client ID); the
refused second send in the same session has its own alias. `hbridge diag trace --msg m_…`
joins the send operation, the refresh that observed the exact native client-ID proof and the run.

## Round 1 summary (kept for reference)

M1 environments and build identity; M2 whitelisted local diagnostics with operation correlation;
M3 opt-in product events, summary, trace, local bundle, sandbox demo; M4 manual CI bounds and
docs. Round-1 evidence (`b9b3de1`): 27 new tests; demo; secret-marker scans of logs, bundle and
summary; disabled/failing sink parity; duplicate/late receipts; loopback-only; schema unchanged.
Those checks are re-run at `3186dbc` as part of the 41 new tests above.

## Not verified / limits

* macOS host, native window, WKWebView, IME, clipboard, VoiceOver, official desktop clients:
  NOT_RUN. `flock` on directory descriptors (EF2) is verified on Linux only.
* Real Claude Code/Codex sessions, real state directories, real HOME/auth: NOT_RUN / untouched.
* GitHub Actions workflow: NOT_RUN.
* Product metrics cover only what the bridge observes; native-internal model calls, tokens and
  cost are `unknown`; Claude Code has no durable receipt (`no_receipt`).
* v1 diagnostic lines written by round-1 builds keep their client-only `msg` alias; summaries
  re-key them by session and flag them, but their latency/op link cannot be repaired.
* Budget: the platform exposes no reliable usage figure to the session; spend not measured.
  Round 2 ran one focused regression and one full check (no repeat of the baseline).

## Integration notes for Codex

Re-verify on macOS from `3186dbc` (or the final HEAD; only docs differ). Suggested DECISIONS
lines: environments are runtime profiles with a state ownership marker (prod unchanged, unmarked
state refused for dev/test); test roots use directory `flock`s; diagnostics are whitelisted JSONL
outside SQLite with session-scoped message aliases (record v2); product events opt-in; mypy
targets darwin. Suggested VALIDATION_MATRIX rows: unmarked prod state refusal (inherited, explicit,
alias); nested roots both orders + race; app-entry preflight (no writes on refusal, cleanup on
midway failure); same client ID across sessions; gate refusal with markers; secret-marker
non-leakage; sink failure parity; summary/export; loopback-only.
