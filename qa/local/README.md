# qa/local — materials for the first real Claude CLI run (T3)

**Evidence level of everything in this directory: prepared materials only.**
No model was invoked while preparing them, and no `claude`/`codex` inference
has ever been run through the bridge. These files do not extend the test
suite; `scripts/check.sh` does not run them.

## What is here

| File | Purpose |
|---|---|
| `make_fixture.py` | Creates a disposable single-function fixture repo (`slugkit.slugify`), an **external** acceptance script (stored outside the repo), and a validated TaskSpec for the claude-code executor. |
| `task-live-smoke.example.json` | Read-only example of the generated TaskSpec (placeholder paths). Regenerate; do not hand-edit. |

The task targets a one-shot fixture project only — never Harness Bridge itself.
The external acceptance check (`trust: external-acceptance`) lives outside the
fixture repo, so the executor cannot pass by editing repository tests. Its
cases are independent of the repo tests and cover separators, edge hyphens,
empty results and non-ASCII input.

## Commands (when and only when the T3 checklist is confirmed)

```bash
# from the bridge repository checkout
uv run --frozen python qa/local/make_fixture.py /tmp/hb-live-smoke

uv run --frozen hbridge --json create \
  --task /tmp/hb-live-smoke/task-live-smoke.json --idempotency-key live-smoke-1

uv run --frozen hbridge --json run <TASK_ID> --mode live --allow-model-usage

uv run --frozen hbridge --json artifacts <TASK_ID>
```

Preset limits (already in the generated TaskSpec): `max_attempts = 1`,
`max_repair_cycles = 0`, `max_turns_per_attempt = 10`,
`wall_timeout_seconds = 600`. Executor: `claude-code`, model
`claude-opus-5-5`. Bash auto-approval is scoped to exactly the repo-tests
command (`Bash(python3 -B -m unittest:*)`).

## Conditions still to confirm before any real call

All of `docs/LOCAL_HANDOFF.md` §2, in particular:

1. `claude` CLI installed and logged in via the official subscription flow by
   the user. Status at preparation time (2026-10-06, this machine): **not
   installed** — `claude --version` could not even be attempted.
2. No `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` /
   Bedrock / Vertex / Foundry variables in that shell (`hbridge doctor --json`
   lists names only). Extra-usage / auto top-up status checked in the account
   UI; if unknown, do not claim "no extra cost".
3. Hooks, MCP servers and permissions that `claude -p` will load reviewed
   (`~/.claude/settings.json`, project `.claude/`, managed settings).
4. `--max-turns` flag evidence: still **unknown / pending local confirmation**
   (docs declare it; local `--help` of 2.1.291 did not list it; no local run).
   Confirm per `docs/LOCAL_HANDOFF.md` §2 step 4, then opt in per flag in the
   state-dir `config.toml` (`allow_unlisted_flags = ["--max-turns"]`).
5. `[live] enabled = true` and `hooks_and_permissions_reviewed = true` in the
   state-dir `config.toml` — the live gate stays closed without them, by
   design.

## Never

- `--bare`, `--dangerously-skip-permissions`, unrestricted Bash permissions.
- Store tokens, credentials, real session logs or run databases in this
  repository. Everything here must stay public-repo-safe.
- Treat a mock-mode run as live evidence, or reuse a generated fixture for a
  second live run without regenerating it.
