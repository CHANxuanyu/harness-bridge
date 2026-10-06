# Protocol and CLI contract (schema 1.0)

All external input is validated; unknown fields are rejected; `schema_version` must be `"1.0"`.

## TaskSpec

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `"1.0"` | other values are rejected explicitly |
| `goal` | string 1..20000 | |
| `repo.path` | absolute path | must be the repository top level with ≥1 commit and a clean status |
| `repo.base_ref` | ref | resolved to a commit SHA at create time; never follows a moving HEAD |
| `requirements` | list[str] | passed to the executor |
| `allowed_paths` | globs (≥1) | case-sensitive |
| `forbidden_paths` | globs | case-insensitive; default `.github/**`, `.env`, `.env.*`, `**/.env`, `**/.env.*`; wins over allowed |
| `verification[]` | `{id, argv[], cwd=".", timeout_seconds, required=true, trust}` | `trust` ∈ `external-acceptance`, `repository-tests`; ≥1 required; argv only, no shell |
| `limits` | `max_attempts` 3 (1..10), `max_repair_cycles` 2 (≤ max_attempts−1), `wall_timeout_seconds` 900, `max_turns_per_attempt` 20, `max_artifact_bytes` 10 MiB, `kill_grace_seconds` 5 | conservative project defaults, not vendor guarantees |
| `executor.kind` | `fake` \| `claude-code` | |
| `executor.requested_model` | string \| null | default `claude-opus-5-5` (exact pin) |
| `executor.scenario` | fake only | `success`, `bug-then-repair`, `hang`, `crash`, `malformed-output`, `permission-denied`, `budget-exhausted`, `scope-violation`, `false-success-report`, `noisy`, `tamper-tests` |
| `executor.permission_mode` | `acceptEdits` (default), `manual`, `dontAsk`, `plan` | `bypassPermissions`/`auto` rejected |
| `executor.allowed_tools` | list | unrestricted `Bash` / `Bash(*)` rejected |
| `executor.resume_on_repair` | bool (true) | |
| `executor.strict_mcp_config` | bool (true) | adds `--strict-mcp-config` |

Core-generated: `task_id`, `task_version` (always 1 in V0.1), `created_at`, normalized spec
digest, verifier digest, repo identity (git common dir), base SHA. `create` takes an
idempotency key: same key + same normalized request → same task; different request → conflict.

### Glob semantics
POSIX `/` only, anchored at the repo root. `*` and `?` stay within one segment; `**` must be a
whole segment and matches zero or more segments. `src/**` matches everything under `src/` but
not `src2/…`. Use `**/name` to match at any depth.

## ReviewDecision

`{schema_version, task_id, attempt_id, task_version, snapshot_digest, verdict, findings[],
reviewer_label, idempotency_key}`; `verdict` ∈ `approve`, `changes_requested`, `blocked`
(the latter two need ≥1 finding). Copy the first five fields from `artifacts → review_template`.
`reviewer_label` is declarative metadata, not authentication.

Rules: wrong attempt / version / snapshot → `STALE_REVIEW`; a candidate changed since the
manifest → `STALE_REVIEW` (run `verify`); same key + same content → same receipt
(`duplicate: true`); same key + different content → `IDEMPOTENCY_CONFLICT`. Gate-rejected
approvals are stored and replay as the same rejection.

## Approval gate (all required for SUCCEEDED)
executor outcome `succeeded` with confirmed exit; manifest present, complete and matching its
recorded digest; no scope violations; verification status `passed` with every required check
`passed` on an unchanged snapshot; verifier digest unchanged; current candidate fingerprint ==
reviewed snapshot; state `AWAITING_REVIEW`.

## Snapshot fingerprint
`sha256(canonical_json({algo: "hbridge-fingerprint-v1", base_sha, tree_sha, task_version,
verifier_digest}))` where `tree_sha` is the git tree of the whole candidate (committed, staged,
unstaged, untracked non-ignored) built in a temporary index.

## States
`CREATED, READY, STARTING, RUNNING, VERIFYING, AWAITING_REVIEW, SUCCEEDED, FAILED, BLOCKED,
INTERRUPTED, CANCELLED` — transitions in `src/harness_bridge/state.py`.
Attempt outcomes: `succeeded, failed, protocol_error, crashed, timed_out, blocked, cancelled,
interrupted, outcome_unknown, spawn_failed`.

## Fake executor wire protocol (`hbridge-fake/1`)
JSON lines: `start{session_id, model}`, `progress`, `child{pid}`,
`result{status: success|error, summary, tests_reported, error{category, message, reset_at}}`.

## Claude Code stream (`--output-format stream-json`), as assumed from docs
`system/init{session_id, model, permissionMode, apiKeySource, tools, mcp_servers}`,
`assistant`/`user` messages (content not stored), `result{subtype, is_error, result,
num_turns, total_cost_usd, usage, permission_denials, session_id}`. Unverified against a real
run; see `tests/fixtures/claude_stream/PROVENANCE.json`.

## CLI
Global: `--state-dir DIR` (default `$HBRIDGE_STATE_DIR` or `$XDG_STATE_HOME/harness-bridge` or
`~/.local/state/harness-bridge`), `--json`.

```text
hbridge doctor [--offline]
hbridge create --task FILE|- --idempotency-key KEY
hbridge run TASK_ID [--mode mock|live] [--allow-model-usage] [--stub-binary ABS_PATH]
hbridge status TASK_ID
hbridge list [--limit N]
hbridge artifacts TASK_ID [--attempt N] [--show manifest|diff|stdout|stderr|check:<id>:stdout|stderr]
hbridge verify TASK_ID
hbridge review TASK_ID --file FILE|-
hbridge recover TASK_ID [--resolve retry|fail] [--acknowledge-unknown]
hbridge cancel TASK_ID [--wait SECONDS] [--acknowledge-unknown]
hbridge demo --scenario success|bug-then-repair [--workdir DIR] [--cleanup]
```

With `--json`, stdout is one object: `{"ok": true, ...}` or
`{"ok": false, "error": {code, message, retryable, task_id?, attempt_id?, details?}}`.

| Exit | Codes |
|---|---|
| 0 | success |
| 1 | `INTERNAL_ERROR` |
| 2 | `USAGE_ERROR`, `INVALID_INPUT` |
| 3 | `STATE_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `STALE_REVIEW`, `APPROVAL_GATE_FAILED`, `BUDGET_EXHAUSTED` |
| 4 | `LIVE_GATE_CLOSED`, `PREFLIGHT_FAILED` |
| 5 | `NOT_FOUND` |
| 6 | `SOURCE_REPO_DIRTY`, `REPO_ERROR`, `WORKSPACE_ERROR`, `PATH_POLICY_VIOLATION` |
| 7 | `INTEGRITY_ERROR` |
| 8 | `EXECUTOR_ERROR`, `VERIFICATION_ERROR` |
| 9 | `CANNOT_CONFIRM_EXIT` |

## Local config (`<state-dir>/config.toml`)
```toml
[live]
enabled = false                         # deliberate local opt-in
hooks_and_permissions_reviewed = false  # set after reviewing hooks / MCP / permissions
claude_binary = "/absolute/path/to/claude"   # optional; default: `claude` on PATH
allow_unlisted_flags = []               # e.g. ["--max-turns"] after verifying it locally
```
