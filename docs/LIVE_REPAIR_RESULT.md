# Controlled live repair / resume — 2026-10-06

**PASS for one controlled two-attempt task.** A local Codex supervisor requested changes
after a real Claude diagnosis, then the bridge resumed the same Claude session, collected
passing independent verification and accepted a snapshot-bound approval. Fresh CLI status:
**SUCCEEDED, attempts_used 2, repair_cycles_used 1**.

## Scope and identity

- User explicitly authorized this run: at most two executor attempts (initial + one repair),
  using the existing subscription, without enabling extra usage. No additional probes,
  retries, subagents or model/provider switches were started.
- Bridge revision throughout both attempts: `470f5b0686098b5e290aeb42d997b11617087bbe`,
  `local/glm-macos-validation`; clean bridge checkout at dispatch time.
- Supervisor: this local Codex session, `gpt-6-astra`, xhigh, confirmed from local
  `turn_context` metadata. All dispatch and review commands were executed here, with no
  manual terminal handoff or other agent relaying instructions.
- Executor: Claude Code 2.1.291, requested = observed `claude-opus-5-5` in both attempts.
  Binary SHA-256 matched the earlier T3/T4 preflight:
  `9a1d2ed6bb4421e8fc80c892c0413f293be3ee50ae3d7dda1a7622197a056690`.
- Non-inference auth status: logged in via `claude.ai`, `firstParty`, subscription `pro`.
  No API/provider, cloud or nested-session markers; applicable settings/MCP sources
  absent and global MCP count zero. No login, system permission or billing setting changed.
- Existing same-binary T3 `--max-turns` acceptance evidence reused; no fresh paid flag probe.
  Preflight listed/confirmed every needed flag including `--resume`.

## Controlled scenario (not a spontaneous model failure)

A fresh disposable fixture was generated outside the bridge repo. Before creating the task,
the supervisor seeded this known defect in its source repository:

```python
def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower())
```

The missing edge trim makes `"!!!"` return `"-"` and surrounding spaces leave edge hyphens.
Both the unchanged repository tests and independent external acceptance failed before dispatch.
The frozen TaskSpec explicitly required diagnosis only, no edits, on attempt 1; implementation
and added regression tests were reserved for attempt 2 after review feedback. This deterministically
exercises failed verification -> changes_requested -> repair without hoping for a model mistake.

Limits: 2 attempts, 1 repair, 10 turns and 600 seconds **per attempt**, 10 MiB artifacts,
5-second kill grace. Scoped Bash allowance remained `Bash(python3 -B -m unittest:*)`.
No `--bare`, permission bypass, unrestricted shell or changed verifier was used.

## Observed sequence

| Step | Bridge/executor evidence |
|---|---|
| Initial diagnosis | 6 reported turns, 14.464 s; exit 0 and group exit confirmed; no file edits; correctly diagnosed missing trim; repo-tests failed (1 of 3), external acceptance failed (2 of 9) |
| Approval gate | Not approvable: both required checks failed; executor success was not treated as task success |
| Review | Snapshot-bound `changes_requested` accepted; state became READY; feedback supplied the defect and requested regressions |
| Resumed repair | Recorded argv ends with `--resume <initial-session-id>`; init/result and stored attempt session ids match the initial session; task/repo/worktree binding preserved |
| Context continuity | First attempt chose the mnemonic **dangling hyphens**; second recalled it. It was not repeated in the TaskSpec or review feedback and was never written to a fixture file |
| Repair result | 4 reported turns, 17.072 s; exit 0 and group exit confirmed; 10 repository tests and 9 external cases passed |
| Final review | Full diff reviewed, zero scope violations / blockers; snapshot-bound approve accepted; fresh CLI process confirmed SUCCEEDED |

Task: `tsk_a84890fccec74abdb71f`.
Initial attempt: `att_6cdde6c191224855afd8`; repair: `att_00179b69a52e4eaab271`.
Exactly two `executor_spawned` events; no retry or extra executor invocation.

The repair added `.strip("-")` plus a non-str TypeError check, which is compatible with the
specified str input domain. All three existing tests remained; seven regressions were added.
Only `slugkit/slugify.py` and `tests/test_slugify.py` changed (+30/-1). The supervisor did not
edit the candidate between attempts or implement the repair. The source checkout stayed clean
at its original pinned SHA.

External acceptance SHA-256 was unchanged before and after both attempts:
`45a43f71cbb01a94382f82f1e025fb38fe2569e26f417a59ace7f3efc5479900`.
Final approved snapshot:
`sha256:8b790c111f7f468313bb69495f336c2d12451fab4804e05ef79823eef04b5fa0`.

No permission denials, malformed/dropped/oversized events, timeout, held-open pipes or
unconfirmed exits. Streams had 16 and 14 events; unknown `rate_limit_event` events were tolerated.

## Retention and limits

- Isolated live gate closed after **each** attempt; default, T3 and prior T4 gates remained closed.
- Local retention: this chat's `work/repair-resume-20261006/` contains TaskSpec, preflight,
  DB, worktree, raw logs, receipts and review rationale; all outside the public repository.
- Published samples are only field-level redactions in `tests/fixtures/claude_stream_live/`,
  preserving event counts/order and one shared fictional session id; see `PROVENANCE.json`.
  Offline regression covers successful matching resume and rejection of an unrelated session.
- Executor-reported usage per invocation: input 8 / output 1,031 / cache-read 79,839 /
  cache-creation 14,356; then input 4 / output 1,648 / cache-read 50,154 / cache-creation 3,163.
  Reported API-equivalent estimates: USD 0.1514678 and 0.2197786. These are not bills,
  subscription balances, or a proven additive measure for resumed sessions.
  Subscription remaining and existing extra-usage setting remain unknown; neither was changed.
- Earlier 192-test full suite and demos were not rerun. Only affected offline parser/doctor
  checks plus lint/format/types were run for this milestone; see STATUS.md for exact results.
- Still unverified: real interruption/recovery, real timeout/turn-limit enforcement,
  long or concurrent tasks, other versions/installations, and T5 comparative economics/quality.
  One controlled repair does not establish production readiness.
