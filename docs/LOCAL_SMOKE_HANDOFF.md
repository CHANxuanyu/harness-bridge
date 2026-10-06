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
