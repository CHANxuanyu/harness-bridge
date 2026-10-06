# Harness Bridge

> **Experimental prototype (V0.1, milestone M3/M4).** Not production-ready.
>
> **Validation level:** offline only — unit tests and offline integration tests with a
> *simulated* executor (a real subprocess, real git repositories, real verifier commands, real
> SQLite). **No real Claude Code or Codex run has ever gone through this bridge** (T3/T4:
> NOT_RUN). The Claude Code adapter exists and is contract-tested against synthetic /
> docs-derived streams and a stub binary only.

Harness Bridge turns "delegate a coding task to another agent harness, collect evidence,
request repairs, recover from interruptions" into a recorded, testable local protocol. It is a
deterministic local CLI (`hbridge`). **It never calls a model API itself.** The supervisor is
whoever runs the CLI (e.g. the user's existing Codex/Astra session); the executor is Claude Code
(live, gated, local only) or a bundled fake executor (offline).

```text
supervisor (Codex/Astra or a person)
   │  hbridge create / run / artifacts / review          (JSON receipts)
   ▼
Harness Bridge  ── SQLite state + events ── bridge-owned git worktree
   │                                         independent verifier commands
   ▼                                         evidence manifest + approval gate
executor: fake subprocess (offline)  |  claude -p … (live, explicitly gated, NOT_RUN)
```

## Quick start (offline, no model, no network needed after install)

Requires Python ≥ 3.11 (developed on 3.11.17), git, and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --frozen
uv run hbridge doctor --offline
uv run hbridge demo --scenario success
uv run hbridge demo --scenario bug-then-repair
scripts/check.sh          # ruff, ruff format --check, mypy --strict, pytest (live tests excluded)
```

`bug-then-repair` shows the core loop: the fake executor writes a buggy implementation and
*claims* the tests pass; the bridge's own verifiers fail it; an `approve` is refused by the
gate; the scripted supervisor requests changes; the second attempt passes; approve →
`SUCCEEDED`; a fresh CLI process reads the final state; the user's checkout is unchanged.

## Using it on your own repository (mock executor)

```bash
hbridge --json create --task task.json --idempotency-key my-task-1   # see examples/
hbridge --json run TASK_ID --mode mock
hbridge --json artifacts TASK_ID            # summary + review_template
hbridge --json review TASK_ID --file review.json
hbridge --json status TASK_ID
```

Other commands: `verify`, `recover [--resolve retry|fail]`, `cancel`, `list`. Full contract in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md); supervisor playbook in
[`examples/supervisor-instructions.md`](examples/supervisor-instructions.md).

## Live Claude Code mode (not yet verified)

`hbridge run TASK_ID --mode live --allow-model-usage` dispatches `claude -p --output-format
stream-json --verbose --model claude-opus-5-5 --max-turns N ...` only when **all** of these
hold: local `config.toml` opt-in (`[live] enabled = true`, `hooks_and_permissions_reviewed =
true`), no API-key/provider variables in the environment, not a cloud agent session, not nested
inside Claude Code, and every flag used is either listed by the installed `claude --help` or
confirmed by you per flag in `config.toml`. Flag evidence is kept in three separate sources:
the official CLI reference (which documents `--max-turns` and states that `--help` does not
list every flag), the local `--help` output (2.1.291 does not list `--max-turns`), and your
local confirmation. A flag missing from `--help` is therefore **unknown, pending local
confirmation — not unsupported**; documentation alone does not unlock it. If the CLI rejects a
flag at run time, the attempt stops as `BLOCKED` and the bridge never retries without the
limit. Follow [`docs/LOCAL_HANDOFF.md`](docs/LOCAL_HANDOFF.md) before the first live run.

## What it is not
Not a sandbox (same-UID executor; see [`docs/SECURITY.md`](docs/SECURITY.md)), not a model
client, not a daemon, not a scheduler, not a SaaS. It does not wake a supervisor up, does not
auto-retry interrupted work, does not merge anything, and makes no claim that two models are
better or cheaper than one (see [`docs/EVALUATION_PLAN.md`](docs/EVALUATION_PLAN.md)).

## Project documents
`STATUS.md` (current state) · `HANDOFF.md` (next work package) ·
`docs/VALIDATION_MATRIX.md` · `docs/ARCHITECTURE.md` · `docs/TESTING.md` ·
`docs/DECISIONS.md` · `docs/ENVIRONMENT.md` · `docs/LOCAL_HANDOFF.md` · `docs/BACKLOG.md` ·
`docs/CLOUD_EXECUTION_PLAN.md` (original requirements).

No license has been chosen yet (public repository, all rights reserved by the author until a
license is added).
