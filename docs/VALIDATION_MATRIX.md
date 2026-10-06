# Validation matrix

Evidence levels (see `docs/TESTING.md`):
T0 static/schema · T1 unit · T2 offline integration with a **simulated** executor (real
subprocess, real git, real SQLite, real verifier) · T3 live single harness (real Claude CLI) ·
T4 live dual harness (Codex/Astra → bridge → Claude) · T5 comparative evaluation.

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
