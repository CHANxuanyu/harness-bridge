# Validation matrix

Evidence levels (see `docs/TESTING.md`):
T0 static/schema · T1 unit · T2 offline integration with a **simulated** executor (real
subprocess, real git, real SQLite, real verifier) · T3 live single harness (real Claude CLI) ·
T4 live dual harness (Codex/Astra → bridge → Claude) · T5 comparative evaluation.

All results below were produced on: Linux 6.18 x86_64 container, Python 3.11.17, git 2.43.0,
SQLite 3.45.1 (Claude Code Cloud session, 2026-10-06), code revision `aeea786` (184 tests),
re-run on the final docs-only head and from a clone of the exported bundle. macOS is the target platform but is
**not yet verified**. "PASS" means the listed tests passed on that platform; it says nothing
about real model behaviour.

| ID | Feature | Status | Evidence | Test / command | Result | Remaining uncertainty |
|---|---|---|---|---|---|---|
| C01 | Offline success loop (real edit, verifier, approve) | implemented | T2 | `test_c01_success_flow_end_to_end`, `hbridge demo --scenario success` | PASS | simulated executor only |
| C02 | Fail → changes_requested → new attempt → pass | implemented | T2 | `test_c02_bug_then_repair`, `hbridge demo --scenario bug-then-repair` | PASS | simulated executor only |
| C03 | Executor claims pass, verifier fails → approve refused | implemented | T2 | `test_c03_executor_false_success_claim_cannot_be_approved`, `test_tampered_repository_tests_do_not_fool_external_acceptance` | PASS | — |
| C04 | Idempotent create / conflicting key | implemented | T1/T2 | `test_c04_create_idempotency`, `test_r01_cli_flow_across_fresh_processes` | PASS | — |
| C05 | Repeated run does not spawn | implemented | T2 | `test_c05_repeated_run_does_not_spawn` | PASS | — |
| C06 | Malformed output / missing final result | implemented | T1/T2 | `test_c06_malformed_output_is_protocol_error_not_success`, `tests/unit/test_fake_adapter.py` | PASS | fake wire protocol only |
| C07 | Timeout / crash / non-zero exit | implemented | T1/T2 | `test_c07_*`, `tests/unit/test_runner.py` (group kill, TERM-ignoring child, escaped process) | PASS (Linux) | macOS process-group behaviour unverified |
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
| R06 | Cancel owned group; never signal unproven PIDs | implemented | T2 | `test_r06_cancel_stops_owned_process_group`, `test_sigterm_to_runner_interrupts_with_known_outcome`, `test_hard_killed_runner_never_signals_unproven_processes` | PASS (Linux) | Codex tool-session teardown behaviour must be checked locally |
| R07 | Candidate change invalidates evidence/approve | implemented | T2 | `test_r07_candidate_change_after_evidence_invalidates_review`, `test_verify_rebinds_evidence_after_candidate_change` | PASS | — |
| — | Crash during verification resumes without executor | implemented | T2 | `test_crash_during_verification_resumes_without_rerunning_executor` | PASS | — |
| A01 | Claude command construction (pure, exact model, bounded turns, explicit resume, stdin prompt) | implemented | T1 | `test_a01_*` in `tests/contracts/test_claude_adapter.py` | PASS | flags verified against `--help` text only, not behaviour |
| A02 | Docs-derived / synthetic Claude stream fixtures parse + classify; provenance recorded | implemented | T1 (synthetic) | `test_a02_*`, `tests/fixtures/claude_stream/PROVENANCE.json` | PASS | real CLI stream schema unverified (no captured-live fixtures) |
| A03 | Unknown event types / missing usage → tolerated, usage null | implemented | T1 | `test_a03_unknown_events_and_missing_usage`, `test_unknown_events_are_tolerated` | PASS | — |
| A04 | Permission / quota / provider errors → BLOCKED, no retry, no invented reset | implemented | T1/T2 | `test_a04_*` (Claude, structured vs heuristic), `test_a04_permission_and_quota_errors_block` (fake) | PASS | real Claude error shapes unverified |
| A05 | Huge stdout/stderr drained and bounded | implemented | T1/T2 | `test_large_interleaved_output_does_not_deadlock`, `test_noisy_executor_output_is_bounded` | PASS | — |
| A06 | Chunk boundaries / partial UTF-8 | implemented | T1/T2 | `test_lines_survive_arbitrary_chunk_boundaries_with_utf8`, `test_stub_flow_with_resume_on_repair` (stub trickles 1 byte/write) | PASS | — |
| S01 | `../`, absolute, prefix confusion, symlink escape | implemented | T1/T2 | `tests/unit/test_policy.py`, `test_show_artifact_is_restricted_to_known_names` | PASS | not a sandbox |
| S02 | Credential-looking text redacted | implemented | T1/T2 | `test_redaction_of_fake_credentials`, `test_c08_*` | PASS | regex-based; novel token formats may pass through |
| S03 | Verifier config / manifest tampering detected | implemented | T2 | `test_s03_tampered_verifier_config_is_detected`, `test_tampered_manifest_file_is_detected` | PASS | not tamper-proof against a same-UID attacker |
| S04 | API/provider env, cloud/nested markers, unreviewed hooks, unlisted flags → no live dispatch | implemented | T1/T2 | `test_s04_*`, `test_live_gate_refuses_in_cloud_even_when_configured`, `test_live_code_path_with_stub_binary_is_not_a_real_run` | PASS | misuse prevention, not billing isolation |
| — | Claude adapter through full pipeline with a stub binary (resume on repair, resume mismatch, model mismatch risk) | implemented | T2 (stub) | `tests/integration/test_claude_stub_flow.py` | PASS | stub replays synthetic streams; not Claude |
| — | `--max-turns` capability evidence (docs vs local help vs local confirmation) | implemented | docs + captured help text | `test_help_absence_is_not_treated_as_unsupported`, `test_documentation_alone_never_marks_a_flag_usable`, `test_confirmation_is_per_flag_and_forbidden_flags_stay_forbidden`, `test_no_global_preflight_bypass_in_config`, `test_doctor_reports_flag_evidence_not_unsupported` | docs: declared; local help 2.1.291: not listed; local verification: none → **unknown (pending)** | needs a local check; never inferred from docs alone |
| — | CLI rejects an argument at run time → stop, no retry without it | implemented | T1/T2 (stub) | `test_cli_rejecting_a_flag_stops_the_attempt`, `test_cli_rejection_of_max_turns_stops_and_is_never_retried_without_it` | PASS | real CLI error text unverified (commander-style assumed) |
| T3 | Real Claude CLI single-harness run | not run | — | — | **NOT_RUN** | requires local, explicitly authorized run |
| T4 | Real Codex/Astra → Claude loop | not run | — | — | **NOT_RUN** | requires local, explicitly authorized run |
| T5 | Comparative evaluation | not run | — | — | **NOT_RUN** | format only (`docs/EVALUATION_PLAN.md`) |
