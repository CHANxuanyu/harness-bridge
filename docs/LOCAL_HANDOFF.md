# Local operation and continuation

Current evidence and next work are in `STATUS.md`, `HANDOFF.md` and
`docs/VALIDATION_MATRIX.md`. This runbook supersedes the cloud-era private-repository,
bundle-only delivery and mandatory first-run reproduction instructions.

## 1. Continue from the actual local state

- Repository stays **public**, by the user's explicit choice. Do not change visibility.
- Working branch: `local/glm-macos-validation`. Remote was directly confirmed at `470f5b0`
  on 2026-10-06; later local work is not automatically pushed. Inspect Git before acting.
- Read `AGENTS.md`, `STATUS.md`, `HANDOFF.md` and the latest result record. Preserve existing
  changes. Session migration is not a reason to redesign, rerun finished tests/demos, launch
  another model, or have the user carry instructions between agents.
- Baseline evidence: full offline checks on Linux/macOS, captured-live parser regressions,
  T3/T4 initial smokes and one controlled repair/resume. Reuse these records; run checks
  relevant to new changes or unresolved failures.
- Prefer CLI and direct local file operations. Use available computer-use tools only when
  UI interaction is needed. A GUI permission issue does not prevent CLI work.

## 2. Preflight for an explicitly authorized live run

Each real run needs explicit local user authorization with bounded attempts/repair/turns/time.
An existing subscription or a general request to continue development does not auto-enable live.
The agent can perform the authorized local actions directly; a separate user terminal is not
required when this session's tools support them.

1. Confirm the intended installed `claude` path/version and non-inference `claude auth status`.
   Record only logged-in state, auth method, provider and subscription type. Never copy/read
   OAuth tokens or print account identifiers. Login itself belongs to the user if needed.
2. Check the bridge-recognized API/provider, cloud and nested-session environment **names**.
   Never unset protective markers or replace provider settings just to pass the gate.
3. Review applicable user/project/managed settings, hooks, MCP and permissions. Keep strict
   MCP config and scoped tools. Do not change extra usage or auto top-up. If their existing
   status is unknown, report unknown rather than claiming no cost.
4. Reuse the existing T3 `--max-turns` parse-acceptance evidence only when installation and
   binary are unchanged (CLI 2.1.291; binary hash in `docs/LIVE_REPAIR_RESULT.md`). Its help
   does not list the flag. A changed installation needs fresh evidence; no silent paid probe.
   Parse acceptance does not prove enforcement. `--resume` is listed by this CLI's help.
5. Generate a fresh disposable fixture outside this public repo with `qa/local/make_fixture.py`.
   Use a new isolated state directory for **every** operational command via `--state-dir`.
   Never live-enable the global default directory.
6. In that isolated `config.toml`, keep `enabled = false` during preparation. The exact
   confirmed flag allowlist is `allow_unlisted_flags = ["--max-turns"]`; set
   `hooks_and_permissions_reviewed = true` only after the preceding review.
   Run `hbridge --state-dir STATE --json doctor` (no inference). Its live capability status
   stays unknown: doctor cannot certify live execution on the current configuration.
7. Pin the TaskSpec to `claude-code` / `claude-opus-5-5`, scoped tools and agreed limits.
   Confirm baseline verification detects the seeded/stub failure and freeze the external
   acceptance script hash. Only then enable this isolated gate for the authorized dispatch.
8. Create and run through the bridge, preserving receipts. `run` takes both `--mode live`
   and `--allow-model-usage`. Record a start marker before dispatch; do not retry an unknown
   tool outcome. Inspect stored task/attempt state first.
9. After each executor attempt, close the isolated live gate. Inspect exit confirmation,
   model/session, verification, actual diff, scope and acceptance integrity. Use the current
   artifacts review template for a snapshot-bound decision. Never substitute executor claims
   for independent verification. Re-read status in a fresh CLI process.

No `--bare`, `--dangerously-skip-permissions`, unrestricted Bash, automatic quota waits,
provider switches or unbounded retries. A permission/usage/auth/unknown-exit problem is a stop
condition for the affected dispatch, not an invitation to weaken protection.

## 3. Controlled repair/resume (already verified once)

The completed run is recorded in `docs/LIVE_REPAIR_RESULT.md`. Do not repeat it for handoff.
For a separately authorized follow-up, the observed procedure was:

- Seed a missing-edge-trim defect in the fresh fixture source **before task creation**.
- Freeze one TaskSpec with 2 attempts / 1 repair, 10 turns / 600 seconds per attempt and
  `resume_on_repair = true`. Requirements explicitly stage initial diagnosis-only, then
  review-directed repair; required verifiers remain unchanged throughout.
- Initial diagnosis makes no edits; verification fails and approval stays blocked.
- Submit `changes_requested` with the real failure and required regressions.
- The second run must have kind repair, explicit `--resume` with the first observed session,
  matching output session and task/repo/worktree binding. Do not silently accept a new session.
- Inspect the repaired diff, preserved existing tests, independent verification and acceptance
  hash, then approve the exact verified snapshot. Confirm final state and attempt counts.

This is a deliberately staged workflow, not evidence that the model naturally failed a task.
Real interruption/recovery, timeout/turn-limit enforcement and T5 remain separate unverified work.

## 4. Retain and publish evidence carefully

Keep raw streams, DBs, candidate worktrees and review files outside the public repository.
Only field-level redacted samples and bounded result summaries belong in Git. Preserve event
order/counts and consistent fictional ids; never publish conversation/thinking/tool-input content.
Update status, handoff and validation matrix with what actually ran; commit one logical milestone.
Push only within the user's current authorization; never change visibility.
