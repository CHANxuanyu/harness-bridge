# Validation matrix

Evidence levels (see `docs/TESTING.md`):
T0 static/schema · T1 unit · T2 offline integration with a **simulated** executor (real
subprocess, real git, real SQLite, real verifier) · T3 live single harness (real Claude CLI) ·
T4 live dual harness (Codex/Astra → bridge → Claude) · T5 comparative evaluation.

## Desktop continuation after unlock — 2026-10-07

Runtime **0.1.0.dev2**, plugin **0.1.0-alpha.5**. Claude's original session is visible in its
sidebar with the same UUID, full prompt/tool/final history and original worktree (verified
through Claude and Finder accessibility). The human explicitly confirmed the original Codex
page and sidebar item after native navigation. Its list API still omits the exec session:
list-source filtering is not a reliable proxy for actual GUI visibility.

Real acceptance exposed a Bridge defect: dev1 redirected Claude desktop-launcher streams;
2.1.291 rejects that before opening. Preserve the initial exit-1/unknown receipt. The correction
uses a bounded PTY with no input; one explicit, narrowly qualified legacy-pipe retry retains the
old record. Native acknowledgement and GUI checks then passed, and receipt replay did not
reopen. Missing exits, success, timeout and newer transports never qualify for that recovery.

Codex uses the official existing-thread URL in the validated macOS app (26.930.31730,
CLI 0.160.0), checking identity/URL registration and the original embedded executable. The
first version probe refused because the implementation expected `codex` instead of the observed
`codex-cli` version prefix; no request was reserved. Corrected the pin and independent fixture;
the native URL request and replay then succeeded. No prompt/new/fork route or model turn.
Official route: [existing-chat links](https://learn.chatgpt.com/docs/reference/commands).

Checks: pre-edit desktop baseline **26 / 8.21s**; PTY/CLI **41 / 23.87s**; expanded desktop/
Codex/CLI/plugin **73 / 52.42s**; dev2 plugin compatibility **26 / 24.44s**; corrected Codex
version pin **6 / 2.56s**. Lint/format 146 files and strict mypy 40 runtime files pass.
A mistyped test path collected zero tests before the corrected command. No failed test was
removed/skipped. Prior full 732 remains reused; this is affected coverage, not another full run.

Actual Codex/ZCode alpha.5 upgrades retain the connection and all 34/15 unrelated plugins.
All 16 files per cache match, both 36-command checks pass, and Skill validation passes.
No new Executor attempt/model message, provider/billing change or remote publication.
Private receipts: takeover chat `work/p7-desktop-unlocked/result.json` and `work/p7-plugin-alpha5/`.

**Remaining:** full Codex GUI quit/relaunch with a bounded fake job, plus checking the original
Codex chat after that restart. Do not close this app through a refused automation route. The
human performs the actual quit/reopen; a prepared observer records process identity and job
continuity. Preserve all real task histories/worktrees. All native model allowances stay spent.

**P7 distribution closeout (2026-10-07, baseline `4b0767d`):** required pre-edit checks reused
the plugin compatibility surface: 26 passed / 17.47s. New distribution checks **12 passed /
2.81s**; lint/format 144 Python files and mypy 40 runtime files pass. Tests build synthetic
wheels in isolated Git fixtures, verify a relocated candidate after removing its source,
compare the transport ZIP, preserve ignored state, refuse dirty/concurrently changed source
and existing destinations, and reject corruption, missing/extra/linked files and a rehashed
wheel that differs from its source. No network, auth or native Executor invocation.
Initial run: 6 passed / 6 failed because the verifier rejected Git's root directory entry
`source` (tarfile strips its trailing slash). Corrected only that exact directory allowance;
path traversal and linked/special entries remain refused. No tests removed/skipped.
Runtime/plugin execution code is unchanged; prior 732 full plus desktop/plugin affected
coverage is reused. A clean committed real candidate is built/verified separately by the
same repository tooling, with its receipt kept outside the public repo. This is distribution
consistency evidence, not desktop-list or full Codex GUI acceptance. See [P7_CLOSEOUT.md](P7_CLOSEOUT.md).

**P7 alpha.4 entrypoint continuation (2026-10-07, baseline `5aaaa47`):** plugin suite **26
passed / 17.22s**, 2 new old-runtime/missing-Advisor-option refusals, lint/format 142 files,
mypy 40 runtime files, Skill Creator validator pass. No new core/full-suite run. Actual native
Codex/ZCode updates and enabled metadata pass; 16 matching files per cache, 36-command checks,
unchanged shared connection and 34/15 unrelated plugin entries. Native Codex skills/list loads
alpha.4 for repo and chat cwd. Read-only thread/list proves the existing Executor appears under
explicit exec filtering but not default/interactive filtering. This is no-model native metadata
evidence, not desktop GUI synchronization. User deferred GUI until returning home and unlocking.

**Latest P7 bounded completion (2026-10-07, real cases on `113b538`):** explicitly authorized
Codex cancellation retest passed, 11.694s, six sampled descendants exited and independent fixture
survivor check empty. Claude native `error_max_turns` passed, 4.442s: configured 1, reported 2,
one assistant Read, no Write, no permission/quota error. Final 8 executions (4 each), 1 repair,
975 reserved seconds, 145.629 observed native seconds; all gates closed. Original failed
cancellation is retained. No further model allowance. This completes the bounded native packet,
not full Codex GUI shutdown or newly requested desktop-list acceptance.

**Desktop continuation:** 26 new synthetic cases plus CLI/coordination regression **55 passed /
37.69s**. Lint/format 141 files and mypy 40 runtime files pass. First affected run: 26 pass / 2
fixture failures (CLI envelope and synthetic allowed-executor list); corrected desktop run 23 /
5.92s before adding three concurrency/Advisor cases. Read-only native task binding checks pass.
Actual Claude handoff/UI still NOT_RUN because the user deferred unlocking; Codex native
read/name succeeds but section/pin probes still do not appear in the list API. Temporary
organization changes undone. No model/auth call in desktop tests; baseline full 732 reused.

**The continuation below is historical and superseded only by the fresh cases above.**

**P7 continuation (2026-10-07, baseline `695503c`):** exact native Codex repair returned the
same UUID, worktree and recalled mnemonic; independent input/combined checks, exact approval,
local fixture delivery and replay passed. Source/acceptance scripts remained unchanged.
Codex cancellation is **FAILED**, despite the old receipt saying CANCELLED/confirmed: a secondary
OS audit found its separately grouped tool alive. Known survivor was terminated and absence
checked. Claude's already-started timeout fired at 15.576s; tool start observed, finish absent.
No further real calls followed discovery. Six executions (3 each) / one repair / 825 reserved
seconds; all gates closed. Claude turn-limit and fixed native cancellation remain NOT_RUN.

Runner correction baseline: 70 passed / 4.23s. Affected runner/adapter cases: 80 passed / 9.23s,
including 10 new cases for detached closed-pipe children, TERM escalation, uncertain observation
and PID identity reuse. Final shared regression: **732 passed / 922.88s**, zero failures/skips.
Lint/format 138 files and strict mypy 39 runtime files pass; source/tests remained unchanged
during the full run. Native cancellation cannot be promoted from these synthetic results.
Prior 707 full plus affected 722-case coverage remains historical.

Native metadata/parse checks, real ZCode GUI quit/relaunch with a fake worker, native plugin
install/update/remove/reinstall and independent runtime retention all pass. Actual alpha.3
caches/checkers and fresh Codex skills/list pass; historical/shared stores are unchanged.
Full Codex GUI quit and automatic desktop history synchronization remain unverified.
See [P7_RESULT.md](P7_RESULT.md) for retained failures, accounting and evidence boundaries.

**Historical preparation and earlier milestones follow.**

**P7 preparation (macOS, 2026-10-07, baseline `c5ca50c`):** before changes, the affected Codex-stub
and plugin suites passed **44 / 44**, 38.80s. New fresh-directory packet/rehearsal suite finishes
**8 passed / 0 failed / 0 skipped**, 13.91s; lint/format (131 files) and strict mypy (37 runtime
files) pass. Initial new-suite run was **7 passed / 1 failed**, 7.04s: the generated Codex completion
omitted `cached_input_tokens`, so the existing strict approval gate correctly refused its otherwise
passing implementation. Fixed the synthetic envelope, not the adapter/gate. An intermediate run
passed 8 / 14.00s; final run follows isolated Git observation and explicit aggregate-accounting checks.

A separate standalone `qa.local.p7_rehearsal` invocation passes outside pytest in the takeover
chat's `work/p7-rehearsal-20261007/`. It observes two RUNNING stand-ins, active-job Advisor takeover,
stale-epoch refusal, same-key dispatch replay, exact Claude-shaped repair session/cwd, combined
external verification and local delivery replay. **3 attempts / 1 repair**, 30 reserved turns / 1800s;
all three jobs confirm exits, source unchanged and packet/check hashes unchanged. Evidence is
**T0/T2 synthetic/offline**, not a real Advisor handoff or native dual-executor run. No new full-suite
claim, model/auth call, core/package edit, shared-state migration or push. Reused native schemas plus
current official documentation did not close Codex's live capability gaps. See
[P7_ACCEPTANCE.md](P7_ACCEPTANCE.md) for reproducible commands, stop rules and remaining acceptance.

**P6 installed-entrypoint continuation (baseline `ebac4a7`, runtime/package unchanged):** native
Codex actual-profile installation/enabled status passes, retaining all 34 prior plugins. Native
`skills/list` in a fresh local app-server resolves the enabled Skill for repo/chat cwd, without
thread/turn creation. Existing actual ZCode installation/Skill UI evidence is retained. Both actual
caches match 13 source files and default-connection diagnostics pass (34 command surfaces each).
An explicit normal read initialized a new empty shared store, live disabled; historical databases
were not opened/migrated. An actual Codex tool PTY exit left one fake job running; fresh reconnection,
event reads and cancellation pass with confirmed exit, one attempt, unchanged source. No prior suite
repeat or new all-suite count. GUI access to Codex was refused; no workaround, desktop hot-refresh
claim or full app-termination claim. P6 no-model wiring passes; real behavior remains P7. Details:
[P6_DESKTOP_ACCEPTANCE.md](P6_DESKTOP_ACCEPTANCE.md).

**P6 entrypoint slice (macOS, 2026-10-06):** plugin alpha.2 adds shared connection resolution and
the goal/child/worker/review/integration/delivery workflow. Baseline focused checks: **24 passed**,
11.19s. New affected suite: **24 passed**, 19.96s; lint/format clean (125 files), strict mypy clean
(37 runtime files). Its first run had 22 pass/2 test-assumption failures, corrected before the final
run. Copied resources and separate CLI processes prove an offline fake failure/takeover/repair/
delivery sequence with one task/two attempts and unchanged source. Native Codex CLI 0.160.0 installed
and enabled alpha.2 in isolated HOME/CODEX_HOME; all 13 cached files match and the cache's 34-command
connection check passes without opening selected state. Skill validator passes. After explicit user
confirmation, actual ZCode installation and Skill enabled discovery also pass; its 13 cached files
and same connection check pass. Actual Codex desktop discovery and real host behavior are NOT_RUN.
No new model calls or active user-state
migration; no new full-suite claim. See [P6_ENTRYPOINT_RESULT.md](P6_ENTRYPOINT_RESULT.md).

All results below were produced on: Linux 6.18 x86_64 container, Python 3.11.17, git 2.43.0,
SQLite 3.45.1 (Claude Code Cloud session, 2026-10-06), code revision `aeea786` (184 tests),
re-run on the final docs-only head and from a clone of the exported bundle. macOS results are
recorded in the dedicated paragraph below. "PASS" means the listed tests passed on that
platform; it says nothing about real model behaviour.

**macOS offline reproduction (2026-10-06, local Mac mini, macOS 26.6.2 arm64, CPython 3.11.16
via uv, git 2.50.1, SQLite 3.53.1/3.51.0, revision `fcbd21a` — no source changes):**
`uv sync --frozen`, `scripts/check.sh` (ruff + mypy strict clean, **184 passed / 0 skipped /
0 failed**), `hbridge doctor --offline --json`, both demos (`demo_passed: true`), and the
targeted `pytest tests/unit/test_runner.py tests/integration/test_recovery.py -v` run
(28 passed) — the process-group tests ran the `ps` fallbacks, since macOS has no `/proc`.
Live rows: T3 was executed on 2026-10-06 (see the T3 row and `docs/LOCAL_SMOKE_HANDOFF.md`);
T4 initial smoke and later controlled repair/resume passed the same day
(`docs/T4_SMOKE_RESULT.md`, `docs/LIVE_REPAIR_RESULT.md`); T5 remains
NOT_RUN. No macOS result below is copied from Linux.

| ID | Feature | Status | Evidence | Test / command | Result | Remaining uncertainty |
|---|---|---|---|---|---|---|
| C01 | Offline success loop (real edit, verifier, approve) | implemented | T2 | `test_c01_success_flow_end_to_end`, `hbridge demo --scenario success` | PASS | simulated executor only |
| C02 | Fail → changes_requested → new attempt → pass | implemented | T2 | `test_c02_bug_then_repair`, `hbridge demo --scenario bug-then-repair` | PASS | simulated executor only |
| C03 | Executor claims pass, verifier fails → approve refused | implemented | T2 | `test_c03_executor_false_success_claim_cannot_be_approved`, `test_tampered_repository_tests_do_not_fool_external_acceptance` | PASS | — |
| C04 | Idempotent create / conflicting key | implemented | T1/T2 | `test_c04_create_idempotency`, `test_r01_cli_flow_across_fresh_processes` | PASS | — |
| C05 | Repeated run does not spawn | implemented | T2 | `test_c05_repeated_run_does_not_spawn` | PASS | — |
| C06 | Malformed output / missing final result | implemented | T1/T2 | `test_c06_malformed_output_is_protocol_error_not_success`, `tests/unit/test_fake_adapter.py` | PASS | fake wire protocol only |
| C07 | Timeout / crash / non-zero exit | implemented | T1/T2 | `test_c07_*`, `tests/unit/test_runner.py` (group kill, TERM-ignoring child, escaped process) | PASS (Linux, macOS) | — |
| C08 | Forbidden / untracked / secret files | implemented | T2 | `test_c08_scope_violation_and_secret_handling` | PASS | ignored files are outside observed scope by design |
| C09 | Stale review (snapshot/attempt/version) | implemented | T2 | `test_c09_stale_reviews_are_rejected` | PASS | — |
| C10 | Verifier timeout / not runnable ≠ pass | implemented | T2 | `test_c10_verifier_timeout_is_not_a_pass`, `test_verifier_that_cannot_start_is_error_not_pass` | PASS | — |
| C11 | No real binary by default; live gate | implemented | T2 | `test_c11_live_gate_closed_by_default`, `test_live_mode_refused_without_all_gates`, sentinel `claude`/`codex` on PATH in every test | PASS | gate is misuse prevention, not billing isolation |
| C12 | User checkout untouched; dirty source refused | implemented | T2 | `test_c01_*` (checkout fingerprint), `test_c12_dirty_source_checkout_is_refused` | PASS | — |
| R01 | State survives process restart | implemented | T1/T2 | `test_reopen_reads_same_state`, `test_r01_cli_flow_across_fresh_processes`, demos | PASS | — |
| R02 | Crash in STARTING window → no auto re-dispatch | implemented | T2 | `test_r02_crash_after_dispatch_record_is_not_redispatched`, `test_r02_crash_after_spawn_before_record` (real `os._exit` in the runner) | PASS | — |
| R03 | Repair budget enforced | implemented | T2 | `test_r03_repair_budget_is_enforced`, `test_blocked_task_retry_and_budget` | PASS | — |
| R04 | Duplicate review/event not re-applied | implemented | T1/T2 | `test_r04_duplicate_review_does_not_advance_twice`, `test_event_dedupe_key_prevents_replay`, `test_rejected_approve_is_replayed_as_the_same_rejection` | PASS | — |
| R05 | Two processes race one task | implemented | T2 | `test_r05_two_runners_race_for_one_task` | PASS | single host only |
| R06 | Cancel owned group; never signal unproven PIDs | implemented | T2 | `test_r06_cancel_stops_owned_process_group`, `test_sigterm_to_runner_interrupts_with_known_outcome`, `test_hard_killed_runner_never_signals_unproven_processes` | PASS (Linux, macOS) | Codex tool-session teardown behaviour must be checked locally |
| R07 | Candidate change invalidates evidence/approve | implemented | T2 | `test_r07_candidate_change_after_evidence_invalidates_review`, `test_verify_rebinds_evidence_after_candidate_change` | PASS | — |
| — | Crash during verification resumes without executor | implemented | T2 | `test_crash_during_verification_resumes_without_rerunning_executor` | PASS | — |
| A01 | Claude command construction (pure, exact model, bounded turns, explicit resume, stdin prompt) | implemented | T1 | `test_a01_*` in `tests/contracts/test_claude_adapter.py` | PASS | flags verified against `--help` text only, not behaviour |
| A02 | Docs-derived / synthetic Claude stream fixtures parse + classify; provenance recorded | implemented | T1 (synthetic) + T3/T4 (captured-live-redacted) | `test_a02_*`, `tests/fixtures/claude_stream/PROVENANCE.json`; `tests/contracts/test_claude_adapter_live.py` + `tests/fixtures/claude_stream_live/PROVENANCE.json` | PASS | captured-live-redacted samples from both live smokes (2026-10-06) parse and classify as the runs were recorded; they do not prove turn-limit enforcement or resume behaviour |
| A03 | Unknown event types / missing usage → tolerated, usage null | implemented | T1 | `test_a03_unknown_events_and_missing_usage`, `test_unknown_events_are_tolerated` | PASS | — |
| A04 | Permission / quota / provider errors → BLOCKED, no retry, no invented reset | implemented | T1/T2 | `test_a04_*` (Claude, structured vs heuristic), `test_a04_permission_and_quota_errors_block` (fake) | PASS | real Claude error shapes unverified |
| A05 | Huge stdout/stderr drained and bounded | implemented | T1/T2 | `test_large_interleaved_output_does_not_deadlock`, `test_noisy_executor_output_is_bounded` | PASS | — |
| A06 | Chunk boundaries / partial UTF-8 | implemented | T1/T2 | `test_lines_survive_arbitrary_chunk_boundaries_with_utf8`, `test_stub_flow_with_resume_on_repair` (stub trickles 1 byte/write) | PASS | — |
| S01 | `../`, absolute, prefix confusion, symlink escape | implemented | T1/T2 | `tests/unit/test_policy.py`, `test_show_artifact_is_restricted_to_known_names` | PASS | not a sandbox |
| S02 | Credential-looking text redacted | implemented | T1/T2 | `test_redaction_of_fake_credentials`, `test_c08_*` | PASS | regex-based; novel token formats may pass through |
| S03 | Verifier config / manifest tampering detected | implemented | T2 | `test_s03_tampered_verifier_config_is_detected`, `test_tampered_manifest_file_is_detected` | PASS | not tamper-proof against a same-UID attacker |
| S04 | API/provider env, cloud/nested markers, unreviewed hooks, unlisted flags → no live dispatch | implemented | T1/T2 | `test_s04_*`, `test_live_gate_refuses_in_cloud_even_when_configured`, `test_live_code_path_with_stub_binary_is_not_a_real_run` | PASS | misuse prevention, not billing isolation |
| — | Claude adapter through full pipeline with a stub binary (resume on repair, resume mismatch, model mismatch risk) | implemented | T2 (stub) | `tests/integration/test_claude_stub_flow.py` | PASS | stub replays synthetic streams; not Claude |
| — | `--max-turns` capability evidence (docs vs local help vs local confirmation) | implemented | docs + captured help text | `test_help_absence_is_not_treated_as_unsupported`, `test_documentation_alone_never_marks_a_flag_usable`, `test_confirmation_is_per_flag_and_forbidden_flags_stay_forbidden`, `test_no_global_preflight_bypass_in_config`, `test_doctor_reports_flag_evidence_not_unsupported`; local probe 2026-10-06 | docs: declared; local help 2.1.291: not listed; local probe: **accepted (parse-level)** → confirmed locally for this installation | enforcement beyond argument acceptance still unproven; never inferred from docs alone |
| — | CLI rejects an argument at run time → stop, no retry without it | implemented | T1/T2 (stub) | `test_cli_rejecting_a_flag_stops_the_attempt`, `test_cli_rejection_of_max_turns_stops_and_is_never_retried_without_it` | PASS | real CLI error text unverified (commander-style assumed) |
| T3 | Real Claude CLI single-harness run (initial smoke) | passed (initial smoke only) | T3 (live) | 2026-10-06, macOS: one CLI flag-acceptance probe + one bridge-run task (one-shot slugify fixture, isolated state dir; 1 attempt / 0 repair cycles / 10-turn cap, 7 used; 600 s wall, 19.7 s) with CLI 2.1.291, requested=observed model claude-opus-5-5; bridge verification passed incl. external acceptance (script hash unchanged before/after); approve → SUCCEEDED, state re-read by a fresh process | **PASS (macOS, live, single run)** | resume/repair not exercised; one run only; `--max-turns` acceptance ≠ enforcement proof; usage executor-reported, subscription remaining unknown |
| T4 | Real Codex/Astra → Claude loop | passed (initial smoke only) | T4 (live) | 2026-10-06, current local Codex gpt-6-astra (turn-context evidence) → bridge 096238e → Claude CLI 2.1.291 / claude-opus-5-5; one fresh task, one run/spawn/attempt, 0 repair, 8/10 turns, 23.249 s; 7 repo tests + 9 external cases pass; acceptance hash unchanged; diff reviewed, snapshot-bound approve, fresh CLI confirms SUCCEEDED; gate closed; docs/T4_SMOKE_RESULT.md | **T4 single-run smoke PASS** | repair/resume not verified; subscription remaining unknown; initial read-only --help omitted state-dir (all later commands explicit); no external human execution |
| T4-R | Controlled real repair / session resume | passed (one bounded task) | T4 live | 2026-10-06, bridge `470f5b0`, local Codex/Astra → Claude 2.1.291 / Opus 5.5; diagnosis-only initial against seeded defect → failed verification → changes_requested → matching `--resume` → 10 repo tests + 9 external cases pass → approve → SUCCEEDED; 2 attempts / 1 repair; session and unrepeated mnemonic preserved; external acceptance unchanged; `docs/LIVE_REPAIR_RESULT.md` | **PASS** | deliberate staged scenario, not spontaneous model failure; one task; no live interruption/timeout or turn-limit enforcement evidence |
| T5 | Comparative evaluation | not run | — | — | **NOT_RUN** | format only (`docs/EVALUATION_PLAN.md`) |
| P01 | Local Codex/ZCode plugin package and CLI contract | alpha | static package + actual runtime schema/parser | 2026-10-06: Skill validator; copied-package links and 3 manifests/2 catalogs; bundled TaskSpec; 16 CLI command forms; `docs/PLUGIN_ALPHA_RESULT.md` | PASS (no dispatch/model) | not installed-host activation or behavior |
| P02 | Codex local marketplace discovery | alpha | actual CLI 0.160.0, non-inference | temporarily register source → list available plugin/version → remove source | PASS | installed=false, enabled=false; Skill trigger NOT_RUN |
| P03 | ZCode local plugin activation | prototype format only | official docs | — | NOT_RUN | manifest/catalog checks do not prove native loading |

The initial-smoke rows above retain their historical scope: neither initial smoke exercised
repair. T4-R supplies the later live repair evidence. At the earlier repair consolidation: 12 offline
parser/doctor tests passed (including 2 new repair-stream regressions), with lint/format/types
clean; the previous full 192-test run was not repeated.

2026-10-06 Advisor/Executor clarification: documentation was checked against the current
workspace creation, adapter cwd and runner spawn paths; runtime and plugin package unchanged.
No tests or model calls were repeated for this clarification. Parent/child coordination,
multi-executor dependencies/aggregate budgets and integrated-goal acceptance remain
**NOT_IMPLEMENTED / NOT_RUN**; existing per-task evidence must not be extended to those claims.

Planning P0 (2026-10-06): `docs/PROJECT_PLAN.md` consolidates the current baseline and the
proposed V1 contracts. Documentation cross-references, milestone/acceptance IDs and
requirement coverage were reviewed. No runtime or plugin behavior changed; no model calls
or runtime tests were repeated. V01–V14 are planned acceptance criteria, not new PASS rows.


## P1 first coordination slice — 2026-10-06

`docs/COORDINATION.md` described this first subset; at that milestone P1 remained in progress.
The completion slice below supersedes its remaining-control/plan limitations.

| Scope | Evidence | Result | Limit |
|---|---|---|---|
| Goal/child ownership and project discovery | `test_goal_two_children_and_takeover_preserve_workspaces`, `test_cli_goal_claim_and_project_discovery`, child repo/base/executor rejection | PASS, offline | Explicit state root; ready independent children only; no installed-host discovery or DAG |
| Old Advisor and legacy entrypoints | 10 guard cases; dispatch-preparation and review-snapshot takeover races; idempotent takeover/create replay | PASS, offline | Logical same-user fencing; native session metadata is declarative |
| Competing takeovers | two independent SQLite connections compete for one epoch; one accepted event | PASS, offline | No cross-host coordination |
| Aggregate attempt/repair limits | two independent connections prepare dispatch concurrently; only one fake subprocess gets last attempt; zero repair ceiling; confirmed spawn-failure refund | PASS, offline | Initial counters and serial slot, not the full P3 worker/time/turn budget design |
| Unknown exit and accepted work after takeover | real CLI crash in STARTING; cancel retains slot even for another goal; already accepted fake attempt completes after ownership change | PASS, offline | No live executor or host-teardown validation; unknown slot release not implemented |
| Revision 1→2 upgrade | 5 tests: committed WAL snapshot, reopen, injected rollback/retry, unknown revision refusal, concurrent upgrade, backup failure (several assertions share a test) | PASS, offline | No production/user state directory migrated; backup is DB-only |
| Shared-core regression | `scripts/check.sh`: ruff + format (78 files), strict mypy (24 source files), **223 passed**, 74.68s | PASS, macOS | Offline simulated/stub executors; no new real calls |

New checks: 24 coordination cases and 5 migration cases (29 total). The full suite includes
194 existing cases, including the two earlier repair-stream additions. It is the first new
full-suite evidence since the historical 192-test report, justified by shared-core code changes.
Do not generalize these rows to P1 completion, all V01–V14 criteria, background survival,
two simultaneous executors, integrated goal acceptance, Codex execution or installed plugins.


## P1 local coordination completion — 2026-10-06

| Scope | Evidence | Result | Boundary |
|---|---|---|---|
| Goal pause/resume and late dispatch | paused attempts consume no slot/budget; running fake continues on pause; stale pause replay does not reapply; pause injected during invocation preparation is checked transactionally | PASS, offline | Foreground runner, single slot |
| Goal cancel/fail | cancel unstarted plans/tasks; block new work and terminal-intent reversal; stop an active fake process group; unknown exit remains NEEDS_ATTENTION even after task failure resolution | PASS, offline | No new real harness or orphan-release evidence |
| Immutable plans and DAGs | 23-case planning/control suite includes batch replay/conflict, duplicate/self/cyclic/missing/foreign dependencies, stale Advisor rejection, child status and CLI paths | PASS, offline | No amendment/delete API |
| Explicit root materialization | no workspace at planning time; concurrent materializers produce one task/workspace; interrupted preparation reuses task; cancel/preparation race preserves ownership | PASS, offline | Independent roots only; dependent children wait for P2 fixed approved baselines |
| Migration to revision 3 | 8 migration cases total; new 1→3/2→3 late-failure rollback and v2 goal/binding/real-task preservation checks; backups verified as old revision | PASS, offline | Isolated fixtures, no real user state migrated |
| Shared-core regression | `scripts/check.sh`: **249 passed**, 85.27s; ruff/format 81 files, strict mypy 25 source files | PASS, macOS | Fake/stub executor processes, no new model calls |

This round added 26 cases (23 planning/control, 3 migration); affected 55-case checks also
passed. P1's local coordination acceptance is complete. P2–P7, including dependency execution,
environment preparation, managed concurrency, integrated delivery and installed-host discovery,
remain incomplete. Goal success/delivery cannot be inferred from these results.

## P2 fixed dependencies and presence preflight — 2026-10-06

| Scope | Evidence | Result | Boundary |
|---|---|---|---|
| Exact retained approvals | Parent files changed after approval and Git GC; successor gets the approved content; task status exposes review/attempt/fingerprint/commit | PASS, offline | Git-visible content only; private refs are not delivery branches |
| Chains and multiple dependencies | Real Git diamond with an ancestor file updated in a descendant and disjoint sibling changes; restart/materialization replay | PASS, offline | Clean merge is not integrated acceptance |
| Conflicts and concurrent requests | Persistent `BASELINE_CONFLICT`, no extra task/worktree; two materializers get the same pinned base/task; source checkout content unchanged | PASS, offline | Automatic conflict resolution/plan supersession pending |
| Retention integrity and crash gap | Missing pins, tampered records, stale Advisor, legacy create/base bypass, rollback after Git pin then exact retry, custom merge driver never invoked | PASS, offline | Same-user logical guards, not hostile-process isolation; unclaimed ref cleanup deferred |
| Older approvals and revision 4 | Explicit retention accepts only unchanged candidate/evidence; CLI replay; v3 materialized plan/replay preserved; final-stage migration rollback from v1/v2/v3 | PASS, offline | No real user state migrated; existing WAL/backup tests retained |
| Assigned context | Successor invocation gets its own cwd plus goal/child/base/dependency attribution; same context reaches JSON and rendered prompt | PASS, fake adapter/prompt contract | No new real cross-harness context acceptance |
| Non-executing readiness | Missing file/directory/tool/verifier cwd/verifier executable, symlink escape, wrong branch, late filesystem change all refuse dispatch without an attempt; explicit local fix unblocks same task; located probe binary never runs | PASS, offline | Presence/ownership only; no install, version/service/auth check or preparation lifecycle |

Affected baseline before edits: 31 planning/migration checks passed. After edits: **60 affected
checks passed**, 62.25s, with ruff/format/mypy clean. This slice adds 29 cases: 15 dependency,
13 readiness and one additional migration revision case. Earlier dependency-unavailable assertions
were updated to require approved content in successors; missing historical-snapshot refusal is
covered separately. No tests skipped/deleted and no live calls, probes, auth or user-state migration.

P2 remains incomplete: controlled setup commands and artifact/cache/shared-resource lifecycle
are still required. P3–P7 and goal delivery remain incomplete. See `EXECUTION_CONTEXT.md`.

Final shared-core regression for this slice: `scripts/check.sh` → **278 passed / 0 skipped /
0 failed**, 157.26s on macOS, Python 3.11.16; ruff/format clean (87 files), strict mypy clean
(27 source files). Required because approval retention, store migration and planned-child
run paths changed. Historical live smokes/repair were not rerun.

## P2 explicit preparation completion — 2026-10-06

| Scope | Evidence | Result | Boundary |
|---|---|---|---|
| Explicit bounded preparation | Separate durable run/key, CLI replay, finite retry allowance; no executor attempt charged; successful setup then fake executor | PASS, offline | Trusted finite commands, not arbitrary-code sandboxing |
| Failure/readiness gates | Failed step, timeout, missing executable/cwd/output, changed candidate; remaining steps not run; deleted output or changed source invalidates readiness | PASS, offline | Output inventory does not hash all ignored cache contents |
| Cancellation and crashes | Real local setup subprocess stopped by task/goal cancel or runner SIGTERM; late cancellation at completion; injected CLI death before/after spawn, conservative recovery | PASS, offline real subprocess/fault injection | No real coding harness or host teardown evidence; unknown exits stay reserved |
| Shared resources | Concurrent same-key requests reserve one run; conflicting owner consumes no run; terminal confirmed owner reclaimed; conflicts also cross projects, including unknown terminal owner | PASS, offline | One explicit state root, logical declared keys; no OS port allocation/cross-state locking |
| Ownership / confidentiality | Accepted work finishes after takeover; stale Advisor cannot start more; HOME/environment isolation, redacted bounded logs, invalid/model-command plans refused | PASS, offline | Scripts/wrappers remain trusted; direct-command checks do not prove arbitrary scripts cannot invoke models |
| Revision 5 | Final-stage rollback from v1/v2/v3/v4, v4 environment-plan digest/identity/replay preserved; existing migration snapshots/rollback tests retained | PASS, isolated fixtures | No real user state migrated |
| Preparation before repair | Additional Claude-adapter **stub** test: preparation → failed verification → feedback → stale preparation blocks dispatch → explicit reprepare → same `--resume` session and feedback → passed verification/approval | PASS, offline synthetic stub | Fake executor does not emulate resume; this is not another real repair authorization/run |

Executed: pre-edit affected baseline **22 passed** (8.68s); preparation/readiness/planning/
migration checks **72 passed** (50.58s); full shared-core `scripts/check.sh` **307 passed /
0 skipped / 0 failed** (163.10s), ruff/format and strict mypy clean (28 source files).
One additional repair/session regression was added after full-suite collection and passed
via exact-test `scripts/check.sh` (4.95s), including lint/format/types. Current coverage is
**308 distinct cases, all successfully executed across those runs**, not a single 308-case
full-suite claim. This milestone adds 30 cases (29 preparation + one migration revision).

The added session test initially used the generic fake executor, which intentionally creates
new synthetic sessions. It now uses the existing Claude adapter stub and retains the same-session
assertion, additionally verifying the actual `--resume` argv and feedback/context stdin.
No assertion was removed or weakened to report success. No new real model, auth/network calls,
smokes, live repair or actual user-state migration occurred.

P2 local core is complete for finite, explicitly configured preparation, as defined in
`PREPARATION.md`. Persistent service hosting, cross-state resource coordination and audited
release of unknown reservations remain outside this completion claim. P3–P7 are unfinished.

## P3 durable background attempts and task observation — 2026-10-06

| Scope | Evidence | Result | Boundary |
|---|---|---|---|
| Detached attempt lifecycle | Launching CLI exits or loses its receipt after spawning; a separate worker finishes verification/review; original job can be replayed and queried | PASS, offline macOS | Simulated CLI launcher, not GUI-host/logout/reboot or real-model survival |
| Durable dispatch/claim races | Concurrent same-key requests return one job; different children race against aggregate budget; two worker processes claim one attempt at most once | PASS, offline | One project slot; no queue or two-executor concurrency claim |
| Cancellation and wall timeout | Detached fake hang process plus child, explicit cancel or deadline, confirmed group exit; independent query timeout does not stop/redispatch | PASS, offline | Only owned groups signalled; no live timeout claim |
| Unclaimed crash window | Launcher crashes after transaction before worker; recovery/cancel fences the reservation and delayed worker cannot execute; uncertain launcher retained | PASS, offline | Only proven non-start refunds goal ledger; task attempt ceiling remains conservative |
| Claimed worker death | Crash immediately after claim and SIGKILL after fake executor steady state; recovery retains unknown exit/budget/slot even after logical failure/cancel | PASS, offline | No guessed PID signals, automatic retry or acknowledgement-based release |
| Verifier-only recovery | Crash after confirmed executor exit/VERIFYING commit; explicit recovery runs frozen checks and marks recovered job; executor count remains one | PASS, offline | Existing verifier lifecycle contract; recovered job is not exit proof |
| Advisor/prepare/gate boundaries | Stale Advisor refused; accepted worker completes after takeover; late preparation change prevents invocation; live-route gate closure checked with configured non-model stub | PASS, offline | Stub exercise of live code path is not a real harness run or new spend authorization |
| Repair continuity | Detached Claude stub initial/repair keeps cwd/session/feedback; an intervening proven non-start preserves feedback and resumes last observed compatible session | PASS, offline stub | Unknown or actually executed intervening attempts cannot be skipped |
| Incremental observation | Paginated task cursors with no duplicates/mutation, bounded wait wake/timeout, invalid/oversized cursor and nonfinite wait rejection | PASS, offline | Task-scoped only; goal-wide stream still pending |
| Revision 6 | v5 prepared task/Advisor/records preserved through upgrade; reconstructed v2/v3/v4 preserved; final-stage failure rollback from v1–v5 | PASS, isolated fixtures | No actual user/live state migrated |

Before edits: 50 affected coordination/recovery/migration checks passed in 37.11s. The first
worker set passed 23 checks in 21.19s. The expanded full run recorded 338 passed / 1 failed:
an added test attempted to inject a Claude-stub invocation mismatch by changing the fake-Python
setting, which does not affect Claude argv. The fixture now changes an actual invocation input
(environment-name set); it asserts no stub invocation, preserved feedback and later bound resume.
After that correction and two input/recovery-boundary cases, all 32 worker checks passed in 28.39s.
No test was deleted or skipped, and no actual model binary/auth/network call was used.

Final shared-core `scripts/check.sh`: **341 passed / 0 failed / 0 skipped**, 199.87s on macOS;
ruff/format clean (94 files), strict mypy clean (30 source files). This milestone adds 33 cases
relative to the previous 308: 32 worker/observation cases and one additional migration revision.
P3 remains partial: two-executor concurrency, overlap guards, aggregate time/turn reservations
and complete host lifecycle acceptance remain outstanding. P4–P7 and integrated delivery remain
incomplete. No new live calls, real auth reads, network requests or user-state migrations.

## P3 local concurrency and cumulative ceilings (2026-10-06, macOS)

This extends the worker milestone above; its pending concurrency/ceiling work is now implemented.
Before source changes, the affected coordination/migration baseline passed **35 cases**, 18.15s.
New targeted checks passed during implementation. An intermediate full regression passed **394
cases**, 227.91s. Final review added a conservative fix and a synthetic historical case: multiple
unknown executions on the same task must retain multiple slots, not collapse to one occupied task.
The final shared-core `scripts/check.sh` passed **395 / 0 failed / 0 skipped**, **226.17s**;
ruff/format clean (98 files), strict mypy clean (31 source files).

This milestone adds **54 cases** relative to 341: 29 in `tests/unit/test_dispatch.py` and 25 in
`tests/integration/test_parallel_budget.py`. Evidence is T0/T1/T2; all executors are fake/stub.

| Contract | Executed evidence |
|---|---|
| Default one / explicit two project slots | Two detached fake workers concurrently RUNNING in distinct worktrees/process groups; third refused; one cancellation leaves the other running and admits the third |
| Shared project capacity | Separate goals share slots/scope checks while retaining independent goal budgets; cap reload applies to existing Bridge objects and lowering it does not kill accepted work |
| Conservative scope proof | Equal/ancestor, broad/wildcard, case and Unicode aliases refused; disjoint roots admitted; unit corpus cross-checks the existing path matcher |
| Atomic reservation | Concurrent requests race for wall-time, turns or slots; only one reservation is accepted when only one fits |
| Cumulative ceilings | Foreground initial/background repair keep full requested limits after completion/approval; confirmed non-start refunds, unknown exit retains; fractional seconds boundary passes |
| Ownership and replay | Stale Advisor, pause, changed creation key content and same-key replay cannot bypass reservations; old GoalSpec digests and replay remain valid |
| Integrity | Historical TaskSpec edits cannot silently shrink previous reservation totals |
| Preparation / verifier protection | Preparation is project-exclusive; unknown setup holds survive logical failure; manual/recovered verification cannot bypass capacity or scope checks |
| Unknown executions | Claimed-worker crash retains budget/slot; same unresolved worktree cannot use another slot; each synthetic historical unknown execution retains a separate slot |
| Simulated host exit | An owned Python host launches the background CLI, then its process session is terminated; detached fake worker remains queryable and cancellable; replay returns its existing job |

Database revision remains 6; no migration is required or performed. Tests use isolated state,
HOME/provider paths, blocked network and real-binary sentinels. No real model, real auth/network
call, real user-state migration, actual desktop host termination or live configuration change.
Existing live smoke/repair evidence was not repeated and its spent authorization was not renewed.

The local P3 worker/concurrency/ceiling core is complete within `docs/CONCURRENCY.md`'s scope.
Simulated host process-session teardown does **not** establish installed Codex/ZCode cleanup,
logout/sleep/reboot survival, vendor turn-limit enforcement or real concurrent harness behavior.
P4 integrated delivery, P5 second executor, P6 installed entrypoints and P7 complete acceptance
remain outstanding. Child success still does not mean the goal has been delivered.


## P4 frozen integration candidates (2026-10-06, macOS)

Affected pre-edit checks: `scripts/check.sh tests/integration/test_dependency_baselines.py
 tests/unit/test_migrations.py` → **26 passed**, 33.27s; lint/format/types clean. Tests ran in an
isolated local checkout at the P3 commit, using the existing installed Python dependencies with
PYTHONPATH directed to that checkout. No package download, model invocation or live-state migration.

The first expanded affected run passed **59/60**, 88.64s. The new CLI test incorrectly expected
an invented nested `data` envelope; the existing CLI returns `ok` plus top-level receipt fields.
The test was corrected to assert that actual established contract, without changing CLI output,
deleting or skipping any test. Additional workspace-ownership/process-crash checks were then added.
All **40 new integration/contract cases passed**, 66.72s, with lint/format/types clean.

| Contract | Executed evidence |
|---|---|
| Fixed inputs and source safety | Two separately approved fake-executor tasks form a separate candidate; late child edits/GC/source commits/dirty source do not change frozen input trees or user files |
| Complete Git result | Candidate preserves additions, deletion, rename, binary bytes and executable mode; dependency successor edits survive without reapplying the parent |
| Conflict evidence | Conflict persists once with incoming task ID, prior applied IDs and a pinned last clean commit; no candidate worktree or fabricated approval, original approval records unchanged |
| Required input closure | Unmaterialized, unapproved, omitted, foreign and unknown-exit attempt/preparation inputs refused; later plan additions invalidate old materialization without silently refreshing evidence |
| Ownership / idempotency | Current Advisor required for freeze/replay/materialize; read-only inspection survives takeover; two concurrent freeze/materialize callers produce one record/event/worktree |
| Git/DB interruption | Injected rollback and actual subprocess `os._exit(70)` after Git materialization leave FROZEN; explicit retry adopts identical commit and unchanged owned workspace |
| User edits and foreign resources | Dirty/moved-HEAD/foreign/missing candidate replay never resets/recreates; symlink destinations and occupied branches refused; relocated repo identity refused |
| Immutable evidence | Missing approval/candidate pins, altered record/spec and changed same-key check configuration fail closed |
| No execution inference | Materialization never runs the frozen verifier or an Executor; custom merge-driver marker is not invoked; attempt/time/turn reservations unchanged |
| Compatibility | Revision 6 upgrade preserves approved task, real fake-worker job and goal budget; v1–v6 all-stage rollback, WAL backup and older materialized/prepared fixtures covered |

Schema revision 7 adds integration records only. The new cases are T1/T2 offline evidence, including
synthetic unknown-exit records and real local Git/SQLite/process operations. There is no real harness
call, actual user/live database upgrade, source checkout delivery or installed-host acceptance.
Total-goal verification, final integration review, conflict-repair task binding, exact local delivery
and ownership-safe cleanup remain unimplemented. P4 is partial; see `docs/INTEGRATION.md`.

A restricted-environment full run was **interrupted** after 202 passes and 2 failures (228.99s).
Both failures were existing `wait_steady` assertions: macOS `ps` was denied by the session sandbox,
so the test could not see its owned fake process group. A direct own-process `ps` probe reproduced
`operation not permitted`. Only the pytest PID verified to belong to this isolated checkout was
interrupted. The full suite was then rerun with local process visibility; no tests were skipped,
no live gate was changed, and isolated HOME/auth sentinels remained active.

Final review also strengthened candidate ownership checks: a fresh temporary Git index compares
the actual tracked/non-ignored tree, so `assume-unchanged` cannot hide a user edit during crash
adoption or replay. Two regressions cover these cases. The targeted 8-case run first hit one test
expectation-map omission for the new `hidden` case (7 passed, 1 fixture KeyError); the mapping was
corrected before the final full run. No production check was relaxed.


Final complete offline run with process visibility: `scripts/check.sh` → **438 passed / 0 failed /
0 skipped**, **277.87s**; ruff/format clean (101 files), strict mypy clean (32 source files).
This milestone adds **43 cases** relative to 395: 42 integration/contract cases plus the sixth
historical migration rollback case. The final run includes the corrected CLI/hidden-edit fixtures,
fresh-index ownership protection, existing cancellation/recovery/parallel-worker tests and all
historical migration preservation checks. No additional source edits followed this passing run.


## P4 integrated verification and Advisor review (2026-10-06, macOS)

Pre-edit bounded baseline on candidate composition/conflict/replay/ownership/crash: **5 passed,
49 deselected**, 16.79s, lint/format/mypy clean. The `-k` selection also filtered the supplied
migration file; this was not a separate migration baseline. After schema 8 changes, migration
checks passed **13/13**, 0.61s.

New integration acceptance run: **18 passed, 3 failed**, 79.73s. Failures were fixture assumptions:
a SUCCEEDED child refuses reverify before admission (so it could not test the new hold), and the
store exposes transactions rather than a public `.conn` property. Corrected to use a same-project
second goal's AWAITING_REVIEW child and the transaction interface. Expanded run: **24 passed,
1 failed**, 108.45s. Heavy Git-backed status polling repeatedly held the SQLite writer lock and
starved the checker reservation; the fixture now polls the small durable launch record. Both
cancel variants then passed **2/2**, 7.75s. No tests were removed/skipped or timeout policies weakened.

Coverage adds 25 offline integration cases and 10 contract cases, plus the v7 migration rollback
case: total-goal interface mismatch despite approved children, exact successful review/replay,
required failure/timeout/missing executable/cwd/mutation, optional warnings versus unknown exits,
log/manifest/input/candidate tampering, takeover/new-run staleness, duplicate verify/review races,
actual crashes at reservation/before spawn/after spawn/after confirmed checkpoint, same-project
exclusion, cancellation/goal terminal gating, migration/CLI, evidence storage failure, environment
isolation/capture bounds and the separate ten-run check ceiling. Direct harness/credential argv is
refused before freeze and rechecked at launch for older frozen records. Strict decision contracts
reject missing bindings, inconsistent findings and unknown fields.

The final admission/strict-contract subset passed **11/11**, 2.96s (24 deselected), with
lint/format/types clean. No tests invoke a real harness.

The implementation uses real local Git/SQLite/finite checker processes and simulated Executors.
Process lifecycle checks run with local process visibility because the macOS execution sandbox
blocks `ps`; the existing isolated HOME/auth sentinels and network guard remain enabled. No real
harness, provider auth, network request, live config or user-state migration was used. The test
network guard covers the Python test process, not an OS-wide subprocess firewall.

Final shared-core `scripts/check.sh` → **474 passed / 0 failed / 0 skipped**, 374.63s.
Ruff and format are clean (105 files), strict mypy clean (33 source files). This adds **36 cases**
relative to the prior 438: 25 integration, 10 strict contracts and one migration revision. Full
regression was required by shared verifier, admission, termination and store changes; no live
smoke was repeated. Source/tests were unchanged during that final run.

P4 remains partial: conflict-repair task binding, exact delivery branch and ownership-safe cleanup
are unimplemented. `APPROVED` is integration history plus a
separate current-validity check, not `READY_TO_DELIVER`/`DELIVERED`. Installed-host and live
multi-harness lifecycle acceptance are still later work. See `INTEGRATION_CHECKS.md`.


## P4 exact local delivery (2026-10-06, macOS)

Affected pre-edit approval/evidence/takeover baseline: **6 passed, 19 deselected**, 27.32s,
ruff/format/types clean. Prior 474-case regression was not repeated solely for handoff. After the
schema 9 change, historical migration checks passed **14/14**, 0.55s.

First new delivery/contract run: **32 passed, 7 failed**, 118.79s. The new refusal paths correctly
stopped ref mutation, but `DELIVERY_CONFLICT` was missing from the central error-code registry,
producing ValueError instead of the intended structured BridgeError. A one-case diagnostic
confirmed this (1 failed, 26 deselected, 6.89s). Registered the stable exit-3/nonretryable code;
kept every refusal case. Added bare internal-namespace rejection and missing-proof/metadata,
unverified/failed-check and CLI-abort cases. Final expanded delivery/contract subset: **44 passed**,
131.96s, ruff/format/types clean (108 files, 34 source files). No tests skipped or acceptance weakened.

New coverage: 31 offline integration cases, 13 input-contract cases, plus one migration revision.
Includes exact commit/tree delivery, preservation of advanced/dirty/staged/untracked source work,
source/base difference receipts, readiness invalidation by code/evidence/selection/Advisor changes,
unverified/failed total acceptance refusal, existing identical/different/case-alias/symbolic/dangling
and selected unborn branch refusal, three real CLI crash windows, atomic external ref race, same-key
concurrent dispatch, takeover before/after publication, explicit abort without ref deletion,
completed replay after changed/missing refs, retained review loss, other-goal unknown execution,
v8 approval preservation and CLI round trips. No real user state was migrated.

Full shared-core `scripts/check.sh` collected all 519 cases: **518 passed, 1 failed**, 509.18s.
The only failure was the old diamond-dependency assertion expecting the literal `not_implemented`;
the new return value correctly reports structured `not_ready`. Updated only that assertion to also
require goal ACTIVE, preserving the rule that approved child dependencies do not imply delivery.
Exact-test `scripts/check.sh` then **1 passed**, 5.92s; ruff/format clean (109 files), strict mypy
clean (34 source files). The full run used the already-collected old assertion; runtime source was
unchanged throughout and after this full run. No broad rerun was needed for the corrected return-shape
assertion. **All 519 current cases have passed across these runs**, not a claimed single green
519-case full run. This milestone adds **45 cases** relative to 474: 31 integration, 13 contracts,
one migration revision. No failed test was deleted or skipped.

Evidence remains T0/T1/T2: isolated HOME/auth sentinels,
local Git/SQLite/checker processes and simulated Executors only. Process tests run with local
process visibility because the macOS execution sandbox blocks `ps`; the existing test network guard
is process-level, not an OS subprocess firewall. No real harness/model/auth/network call or remote
push occurred. Conflict-repair task binding and ownership-safe cleanup remain P4 work; installed
host lifecycle and real multi-harness acceptance remain later milestones. See `DELIVERY.md`.


## P4 completion: integration repairs and conservative cleanup (2026-10-06, macOS)

Relevant candidate/dependency/delivery baseline: **88 passed**, 235.64s, ruff/format/types clean
(109 files, 34 source files before edits). No old live smoke or full suite was repeated solely for
handoff. This milestone adds optional repair-plan/source binding and explicit integration resolution,
shared repair-child budget accounting, strict cleanup previews/receipts and schema 10 migration.

Development checks retained all refusal cases. First repair run: **2 passed, 1 failed**, 33.72s;
a fixture incorrectly accessed Store.conn instead of its transaction API. Next: **14 passed,
1 failed**, 78.83s; a fixture used Fixture.root instead of Fixture.base. Corrected those fixture
accesses. The expanded run reached **22 passed, 1 failed**, 124.51s: cleanup preview used the
materialization path helper, which raised on a symlink before it could report per-resource retention.
Kept the refusal and moved it into cleanup's explicit ownership/eligibility observation.

Further cleanup iterations: **14 passed, 1 failed**, 80.65s (a child CLI rejected a stale preview
while retention checks were being tightened), then a single-case failure at 5.64s and a diagnostic
single-case failure at 5.81s. The stricter Git metadata check identified ordinary Git-created
ORIG_HEAD and an empty per-worktree refs directory. The corrected rule validates ORIG_HEAD ancestry
against the preserved branch and permits only empty refs directories; nonempty worktree refs,
unreachable prior commits and unfinished Git operations retain the workspace. No force flag,
Git reset, evidence deletion, removed/skipped failure or expanded Executor permission was used.

Coverage includes conflict → budgeted repair → new candidate → original total verification → new
exact review → delivery → cleanup; failed total-check repair iterations; explicit negative review;
later normal tasks after an exact repair prefix; source/candidate/approval immutability; required-input
and frozen-check retention; stale Advisor/reopen/CLI and altered pin refusal; initial repair budget
admission and accounting. Cleanup coverage includes preview/apply/replay, dirty/ignored/empty/hidden/
staged/symlink/foreign/locked resources, clean committed tasks, source/evidence/ref preservation,
known-exit and delivery guards, three actual CLI crash windows, changed previews and v9 receipt
migration. Contract coverage preserves old canonical digests and rejects unbound or destructive inputs.

Only isolated local Git/SQLite/checker/fake Executor processes run, with isolated HOME, auth
sentinels and the existing Python-process network guard. Process tests require local process
visibility because the macOS tool sandbox blocks ps; this is not an OS-wide subprocess firewall.
No real harness/model/auth/network call, live configuration change or actual user-state migration.
No remote push or visibility change. P4 means the local core; P5–P7 and installed-host/real
multi-harness acceptance remain outstanding. See INTEGRATION_REPAIRS.md and CLEANUP.md.

The next cleanup run reached **20 passed, 1 failed**, 119.05s: a clean committed task still had
Git's COMMIT_EDITMSG. Cleanup now permits that file only when its bytes equal the current retained
commit message, preserving different drafts. The three focused end-to-end cases then passed;
a new normalization contract assertion failed (3 passed, 1 failed, 19.88s) because its expected
raw input omitted long-existing model defaults. Corrected the expected legacy normalized TaskDefinition
and VerificationCommand shape, not the production normalization rule. Final strict contracts plus
v1–v9 migration/rollback checks: **27 passed**, 1.06s; lint/format clean (116 files), strict mypy clean
(36 source files). All failures/refusals remain represented; the final shared regression follows.

Final frozen-source shared-core `scripts/check.sh`: **574 passed / 0 failed / 0 skipped**, 769.51s
(12m49s). Ruff and format clean (116 files); strict mypy clean (36 source files). All source/test
files stayed unchanged during and after this run (hash consistency checked before commit).
This adds **55 cases** relative to 519: **18** repair integration, **24** cleanup integration,
**12** strict contracts and **1** migration revision. This is one full green run, not a union of
partial runs. No further broad testing was needed after its success; only status/handoff/validation
documentation was finalized. P4 local core is complete with the explicit conservative retention
policy; installed host lifecycle and real cross-harness acceptance remain later gates.

## P5 Codex offline adapter (2026-10-06, macOS)

Affected pre-edit Claude contract/stub baseline: **44 passed**, 8.50s, with lint/format/types
clean (116 files, 36 source files). No prior full suite or paid smoke was rerun for handoff.
This slice adds **68 cases**: 48 Codex contracts and 20 integration cases using a non-model stand-in.

The first expanded affected run had **121 passed, 3 failed**, 21.08s. Two contract fixtures assigned
nonexistent `cancelled`/`interrupted` attributes instead of ProcessOutcome.stop_reason; corrected
to use the real field and dataclass replacement (which rejects nonexistent fields). A third
fixture incorrectly requested a review_template on a BLOCKED task; that task correctly has no
review template. It now checks BLOCKED/no-template while failed verifiable attempts still test
rejected approvals. No production refusal was weakened, and no failing case was removed/skipped.
The corrected affected run: **124 passed**, 25.78s, lint/format/types clean. Additional binding,
resume opt-out and background-repair cases then completed **20 integration cases**, 20.60s.

Coverage: native options without Claude defaults; stdin/workspace binding; process-exit dominance;
unknown/malformed/oversized/missing/duplicate/out-of-order events; usage nullability; quota/auth/
permission/argument refusal; explicit UUID resume/mismatch; binding to task/repo/worktree/kind/model;
foreground and worker repair; background replay, stale Advisor refusal and shared goal ceiling;
wall deadline/cancel with confirmed exit; missing/real-named/symlink stub rejection; doctor gaps;
fully opted-in foreground/background live refusal before attempt reservation or binary execution.

Fixtures use documented event envelopes with synthetic IDs, text and usage. They are not captured
live Codex data. Official references and local CLI 0.160.0 help/version observations are recorded
in CODEX_EXECUTOR.md. Those three non-inference host checks used empty temporary HOME/CODEX_HOME;
no user auth/config was inspected. Tests used isolated HOME, harness sentinels and the Python
network guard. No real model/Executor run, actual user-state migration, live-config change,
remote push or visibility change. Official documentation was read over the web outside tests.
Schema remains 10. Native Codex turn enforcement, subscription/config provenance and resume remain
unverified, with live dispatch unavailable in code; this is P5 offline evidence, not P7 acceptance.

Shared full `scripts/check.sh`: **642 passed / 0 failed / 0 skipped**, 839.69s (13m59s).
Ruff/format clean (120 files), strict mypy clean (37 source files). All 106 source/test/script/
lock inputs were hash-checked unchanged throughout that run.

Review during that run reproduced two additional Codex-only edges using synthetic in-memory
inputs: a mismatched resume ID could remain bound when timeout/interruption won outcome priority,
and oversized integers/deeply nested JSON could raise ValueError/RecursionError out of parsing.
After the full run finished, corrected only `adapters/codex.py` and strengthened the existing
contract cases: process evidence still wins, but never trusts a mismatched resume ID; pathological
JSON becomes malformed protocol evidence. No shared orchestration code changed after the full run.
Final affected `scripts/check.sh` on both Codex suites: **68 passed / 0 failed / 0 skipped**,
20.87s, lint/format clean (121 files), strict mypy clean (37 source files). Existing case count
remains 642; this records a full regression followed by a targeted final correction, not a claimed
single full green run on the corrected adapter. No further broad rerun was needed.

Final desktop session selection rejects a later executed attempt with missing identity, rather than silently opening an older session. Affected desktop rerun: **26 passed / 6.98s**; no additional full run.
