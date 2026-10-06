# Local handoff

Three separate things — none of them happens automatically:
1. **continue developing** the bridge (offline; no model usage needed);
2. **first real Claude CLI test** (T3; needs your explicit authorization of a small model use);
3. **first real Codex/Astra → Claude loop** (T4; after T3).

## Where the code is
> **Local update (2026-10-06):** the repository stays **public** by the user's explicit choice
> (do not change visibility), and the branch **is pushed** —
> `origin/claude/new-repo-plan-dn1eac` == `fcbd21a232759f7b3f2dd2ad22acef69e646fe6d`. The
> private/bundle instructions below are historical; a plain
> `gh repo clone CHANxuanyu/harness-bridge` now works. The offline suite and both demos were
> reproduced on macOS at that SHA (see `docs/LOCAL_SMOKE_HANDOFF.md`); T3 fixture materials
> are ready under `qa/local/`.

- Repository: `CHANxuanyu/harness-bridge` — still **public** at cloud close-out and the branch
  was **not pushed** (the cloud session had no tool to change visibility). Make it private
  yourself (GitHub → Settings → General → Danger Zone → Change visibility), then push the branch
  from the bundle:
  ```bash
  git clone -b claude/new-repo-plan-dn1eac harness-bridge.bundle harness-bridge
  cd harness-bridge && git remote set-url origin https://github.com/CHANxuanyu/harness-bridge.git
  git push -u origin claude/new-repo-plan-dn1eac
  ```
- Branch: `claude/new-repo-plan-dn1eac`
- Last code revision: `aeea786`; the branch head adds docs only and was itself re-verified
  (offline suite + both demos, also from a clone of the exported bundle).

## 1. Reproduce the offline results locally
```bash
gh repo clone CHANxuanyu/harness-bridge      # or: git clone harness-bridge.bundle harness-bridge
cd harness-bridge
git switch claude/new-repo-plan-dn1eac
uv sync --frozen                             # uv fetches Python 3.11 if it is missing
uv run ruff check .
uv run mypy src/harness_bridge
uv run pytest -m "not live"                  # expected: 184 passed
uv run hbridge doctor --offline --json
uv run hbridge demo --scenario success
uv run hbridge demo --scenario bug-then-repair
```

### macOS differences to verify (cloud only ran Linux)
- process groups / `killpg`, TERM→KILL escalation and zombie handling (no `/proc`; the code
  falls back to `ps -A -o pid=,pgid=,stat=` and `ps -o lstart=`): run
  `uv run pytest tests/unit/test_runner.py tests/integration/test_recovery.py -v`;
- worktree creation under `~/.local/state/harness-bridge/worktrees`, path case sensitivity
  (default APFS is case-insensitive; forbidden globs already match case-insensitively);
- SQLite WAL locking with two concurrent `hbridge run` processes (`test_r05_*`);
- install from a clean shell (`uv sync --frozen`).
Record results in `docs/VALIDATION_MATRIX.md` with platform/version; do not copy Linux PASS.

## 2. First real Claude CLI run (T3) — only after you explicitly authorize it
Do this in a **small disposable fixture repo** (e.g. `uv run hbridge demo --scenario success
--workdir /tmp/hb-fixture` creates one at `/tmp/hb-fixture/fixture-repo`; its task spec in
`/tmp/hb-fixture/task.json` can be copied and changed to the claude-code executor).

Checklist, all by you in your own terminal:
1. `claude --version`; log in with the official subscription flow yourself (the bridge never
   logs in, reads tokens or copies credentials).
2. In that shell, make sure no `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
   `ANTHROPIC_BASE_URL`, Bedrock/Vertex/Foundry variables are set
   (`uv run hbridge doctor --json` lists their *names*). Check extra-usage / auto top-up in
   your account UI. If unknown, do not claim "no extra cost".
3. Review hooks, MCP servers and permissions that `claude -p` will load: `~/.claude/settings.json`,
   the fixture's `.claude/` (if any), managed settings. The adapter adds `--strict-mcp-config`
   by default and never adds `--bare` (which would ignore subscription login).
4. `--max-turns` evidence so far: the official CLI reference documents it and says `--help` does
   not list every flag; local `--help` (2.1.291) does not list it; no local run has confirmed it.
   Status: unknown / pending confirmation on your machine. A possibly non-inference parse check
   (itself unverified): `claude -p --max-turns 1 --output-format stream-json --verbose < /dev/null`
   — "unknown option" means this installation rejects it (do not allow it; the bridge would stop
   the attempt anyway and never retries without the limit); a "no input/prompt" error suggests it
   parses. Only after you see that, confirm it per flag in `config.toml` (below).
5. Create `~/.local/state/harness-bridge/config.toml` (or under your `--state-dir`):
   ```toml
   [live]
   enabled = true
   hooks_and_permissions_reviewed = true
   allow_unlisted_flags = ["--max-turns"]   # exact names only, after step 4 confirmed it
   ```
6. TaskSpec for the first run: `"executor": {"kind": "claude-code", "requested_model":
   "claude-opus-5-5", "allowed_tools": ["Read", "Edit", "Write", "Glob", "Grep",
   "Bash(python3 -B -m unittest:*)"]}`, `"limits": {"max_attempts": 1, "max_repair_cycles": 0,
   "wall_timeout_seconds": 600, "max_turns_per_attempt": 10}`.
7. Run:
   ```bash
   uv run hbridge --json create --task task-live.json --idempotency-key live-smoke-1
   uv run hbridge --json run TASK_ID --mode live --allow-model-usage
   uv run hbridge --json artifacts TASK_ID
   ```
   Check: `observed_model` / `model_pin`, `session_id`, `executor_reported.api_key_source`
   (should not indicate an API key), usage fields, exit/permission behaviour.
8. Save `artifacts/<task>/<attempt>/executor.stdout.log` (already redacted) as a
   `captured-live` fixture under `tests/fixtures/claude_stream_live/` with CLI version and date
   in a new provenance file. Do not overwrite the synthetic set. Then update the parser if the
   real schema differs and raise the matrix row to T3 only with that evidence.
9. Separately, test one controlled repair with `--resume` (max_attempts 2) and record whether
   the session id is preserved.

Never: `--dangerously-skip-permissions`, disabling nested-session protection, unrestricted Bash,
long multi-retry runs, or waiting for quota resets automatically.

## 3. First Codex/Astra → bridge → Claude loop (T4)
Paste `examples/supervisor-instructions.md` into the Codex session. Astra writes the TaskSpec,
calls `hbridge`, reads `artifacts`, submits reviews. The bridge does not call OpenAI. If Codex's
sandbox cannot start the local `claude` or cannot wait for a foreground `run`, run the same
`hbridge` command yourself in another terminal and record it as **manual handoff** (not proof of
an automatic Codex launch chain). Mark T4 only after one normal and one repair task, with model,
CLI and configuration sources recorded.

## Continuing development
Read `AGENTS.md`, `STATUS.md`, `HANDOFF.md`, `docs/VALIDATION_MATRIX.md`; run
`scripts/check.sh`; take the next bounded work package from `HANDOFF.md`. Cloud-session upload
permission does not extend to future remote operations — push per your local decision.
