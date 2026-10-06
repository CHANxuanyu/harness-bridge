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
