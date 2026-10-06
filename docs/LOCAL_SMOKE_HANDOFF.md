# Local macOS smoke handoff (2026-10-06)

One page. What actually ran on this Mac, what did not, and what the next
person needs for the T3 live smoke. Companion materials: `qa/local/README.md`.

## Revision and platform

- Code SHA: `fcbd21a232759f7b3f2dd2ad22acef69e646fe6d` — identical to the cloud
  delivery baseline; no source changes this round (`qa/local/` and docs only).
- Branch: `local/glm-macos-validation`, cut from `claude/new-repo-plan-dn1eac`
  (local HEAD == `origin/claude/new-repo-plan-dn1eac`; the branch **is
  pushed** — earlier "not pushed / bundle delivery" notes are obsolete).
- Platform: macOS 26.6.2 (Build 25G83), arm64 (Mac mini, Apple Silicon);
  uv 0.12.13; git 2.50.1 (Apple Git-155); SQLite 3.51.0 (CLI) / 3.53.1
  (Python `sqlite3` module); CPython 3.11.16 fetched by uv into the project
  venv (`uv.lock` untouched). Repository visibility remains **public** by the
  user's explicit choice — do not change it.

## Checks actually executed here (macOS PASS, not copied from Linux)

| Command | Exit | Result |
|---|---|---|
| `uv sync --frozen` | 0 | clean venv, 17 packages from lock |
| `scripts/check.sh` | 0 | ruff + ruff format + mypy `--strict` clean; **184 passed, 0 skipped, 0 failed** (62 s) |
| `uv run --frozen hbridge doctor --offline --json` | 0 | `ok: true`; live gate closed; no API/provider env names |
| `uv run --frozen hbridge demo --scenario success` | 0 | `demo_passed: true`, SUCCEEDED |
| `uv run --frozen hbridge demo --scenario bug-then-repair` | 0 | `demo_passed: true`; attempt-1 verification failure is the scenario; approve probe rejected (exit 3) |
| `uv run --frozen pytest tests/unit/test_runner.py tests/integration/test_recovery.py -v` | 0 | 28 passed (21.8 s) |

macOS risks from `docs/LOCAL_HANDOFF.md` — all exercised on this machine:

- Process groups / TERM→KILL escalation / zombies: PASS. macOS has no `/proc`,
  so the `ps -A -o pid=,pgid=,stat=` and `ps -o lstart=` fallbacks are the code
  paths the tests actually ran (`group_alive`, start-time identity).
- Recovery / crash windows: PASS (`test_r02_*`, SIGTERM interrupt, hard-kill
  never signals unproven PIDs).
- SQLite concurrency: PASS (`test_r05_two_runners_race_for_one_task`).
- Worktrees + case-insensitive APFS: PASS (both demos create bridge-owned
  worktrees in per-demo temp state dirs; forbidden-glob policy tests pass).
  Default state dir `~/.local/state/harness-bridge` stays empty after demos.

Failures found: **none**. Nothing was skipped, weakened or marked expected.

## Not executed this round

- No `claude`/`codex` inference, no live run (T3/T4/T5 remain NOT_RUN).
- **No `claude` CLI is installed on this machine at all**, so even the
  permitted `claude --version` / `--help` checks were not possible. The
  `--max-turns` flag evidence remains **unknown / pending local confirmation**.

## T3 materials (prepared, validated offline)

- Generator: `qa/local/make_fixture.py` — creates a disposable single-function
  fixture (`slugkit.slugify`), an external acceptance script **outside** the
  repo, and a TaskSpec (validated against the bridge's `TaskSpec` schema:
  PASS). Stub code fails both checks (exit 1), so the gates are real.
- Example TaskSpec: `qa/local/task-live-smoke.example.json`; runbook and
  preconditions: `qa/local/README.md`.
- Presets baked in: executor `claude-code` / `claude-opus-5-5`,
  `max_attempts = 1`, `max_repair_cycles = 0`, `max_turns_per_attempt = 10`,
  `wall_timeout_seconds = 600`, Bash auto-approval scoped to
  `Bash(python3 -B -m unittest:*)`.

## Still to confirm before the first real call

1. Install `claude`, log in yourself (subscription flow); the bridge never
   handles credentials.
2. Shell free of `ANTHROPIC_*` / Bedrock / Vertex / Foundry variables; check
   extra-usage settings in the account UI.
3. Review hooks / MCP / permission settings that `claude -p` will load.
4. Confirm `--max-turns` on this installation per `docs/LOCAL_HANDOFF.md`
   §2 step 4, then allow it per flag in the state-dir `config.toml` together
   with `enabled = true` and `hooks_and_permissions_reviewed = true`.
5. Only then: `hbridge create` → `hbridge run <TASK_ID> --mode live
   --allow-model-usage` → `hbridge artifacts` (exact commands in
   `qa/local/README.md`).

**This round invoked no Claude/Codex model and performed no live dispatch of
any kind.**

---

## T3 execution record (2026-10-06, later the same day)

**Real model invocations: exactly 2 (A + B). No retries. Resume/repair/T4 not exercised.**

### Pre-flight (no inference)
- `claude` 2.1.291 (Claude Code), official native install (`~/.local/bin/claude`).
- `claude auth status`: loggedIn, `authMethod: claude.ai`, `apiProvider: firstParty`
  (subscription; account identifiers redacted).
- `--max-turns` absent from local `--help`; `hbridge doctor --json` marked it the only
  `pending_local_confirmation` flag. No user/project/managed settings files, no MCP config,
  no provider env vars; global bridge state dir untouched.

### A — CLI flag-acceptance probe (1 real call, 60 s cap, used ~seconds)
`claude -p "Reply with exactly: OK" --model claude-opus-5-5 --max-turns 1 --output-format
stream-json --verbose --permission-mode plan --strict-mcp-config` → exit 0, result exactly
`OK`, subtype success, num_turns 1, session id present. **`--max-turns` accepted by this
installation (parse-level evidence — not an enforcement proof).** Consumed real quota.

### B — one bridge-run live task (1 real call)
- Fresh one-shot fixture via `qa/local/make_fixture.py`; isolated state dir with
  `[live] enabled=true, hooks_and_permissions_reviewed=true, allow_unlisted_flags=["--max-turns"]`
  (that directory only; gate switched off after the run; global state dir never live-enabled).
- `hbridge create` → task READY; `hbridge run --mode live --allow-model-usage` → exit 0,
  `evidence_level: live-executor`.
- Attempt: initial, outcome succeeded, exit confirmed, **19.7 s** wall, **7 of 10 turns**,
  requested = observed model `claude-opus-5-5`, model_pin satisfied, session recognized.
- Bridge verification **passed**: `repo-tests` and **external acceptance** both exit 0;
  acceptance script SHA-256 identical before and after the run.
- Change: 2 files in scope (`slugkit/slugify.py` +5/−1, `tests/test_slugify.py` +9),
  0 scope violations. Diff reviewed by the operator before approving.
- `executor_reported.api_key_source: none` (subscription). Permission scoping worked:
  2 Bash denials when the executor tried to run the out-of-repo acceptance script itself.
- Review approve bound to the snapshot digest → **SUCCEEDED**, confirmed by a fresh process.

### Usage and billing
- Executor-reported for B: input 12 / output 1781 / cache-read 127 763 / cache-creation
  14 686 tokens; CLI cost estimate ≈ USD 0.18 (**API-equivalent estimate, not a bill, not
  subscription usage**). Probe A usage negligible (2 input tokens class).
- **Subscription quota remaining: unknown** (not observable; no estimates claimed).

### Hygiene
- Raw stream logs, artifacts JSON, review file, run DB and the worktree live in a state
  directory **outside this repository** (a `~/hbridge-t3-live/`-style scratch dir) and are
  **not committed**; this file carries only the redacted summary above.
- Live gate in the test state dir: `enabled = false` after the run (diagnostics kept).
- Matrix rows updated: T3 (initial smoke PASS), `--max-turns` (accepted locally, parse-level),
  A02 (real stream parsed once). Not marked: resume, repair, T4.
- Later the same day: the T4 single-run smoke passed too (`docs/T4_SMOKE_RESULT.md`), and
  field-level redacted stream logs from **both** runs were frozen as offline parser
  regression samples in `tests/fixtures/claude_stream_live/` (provenance in that directory;
  identifiers replaced with fictional ones, no conversation or thinking content, raw logs
  never committed).
