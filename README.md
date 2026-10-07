# Harness Bridge

> **Experimental local candidate:** runtime 0.1.0.dev1, Advisor plugin alpha.4, Apache-2.0.
> Real Claude/Codex parallel work, exact-session repair and integrated local delivery passed.
> The corrected Codex cancellation retest and Claude native turn-stop also passed.
> P7 remains open for desktop-list synchronization and full Codex GUI lifecycle acceptance.
> See the [V01–V15 acceptance matrix](docs/P7_CLOSEOUT.md) and [native evidence](docs/P7_RESULT.md).

Harness Bridge aims to provide **one Advisor with one or more Executors across coding
harnesses**: the Advisor inspects the repo, delegates tasks, reviews results and coordinates
integration. The Bridge prepares each executor's workspace and records execution/evidence.
The current implementation includes the task execution/review core and a first goal/session
coordination core: child plans/ownership, Advisor takeover, goal pause/cancel, aggregate attempt
limits, fixed approved dependency baselines, workspace readiness checks and state-root project
discovery. Explicit bounded environment setup, managed background attempts and up to two scoped
concurrent executors with goal ceiling reservations are supported, along with integrated acceptance,
exact Advisor review, budgeted integration repair children, explicit local branch delivery and
conservative worktree cleanup. It is a
deterministic local CLI (`hbridge`). **It never calls a model API itself.** The supervisor is
whoever runs the CLI (the Advisor, e.g. the user's existing Codex session); the executor is Claude Code
(live, gated, local only), a bundled fake executor (offline), or the Codex adapter
with explicit per-harness budget semantics and native configuration preflight. Codex has no
internal-turn ceiling; new live tasks must explicitly select attempts/wall-time/cancel limits.

```text
Advisor (an existing Codex or ZCode conversation)
   │  installed Skill → hbridge goals / jobs / review / delivery
   ▼
Harness Bridge  ── SQLite state + events ── bridge-owned git worktree
   │                                         independent verifier commands
   ▼                                         evidence manifest + approval gate
Executor sessions: Claude Code | Codex (live, explicitly gated) | fake (offline)
```

## Product and user entrypoints

The target user already subscribes to multiple coding agents (for example ZCode/GLM,
Claude Code and Codex). The intended product is an independent local runtime with plugins
in the user's existing hosts: delegate, review, repair, and continue without carrying
instructions between conversations. See the [product definition](docs/PRODUCT_FORM.md).

The Advisor is itself the user's existing agent **session**; Executors are separate agent
sessions bound to child tasks. The [project plan](docs/PROJECT_PLAN.md) is the canonical V1
scope, session/workspace contract, implementation sequence and acceptance checklist. It
distinguishes existing V0.1 code from proposed coordination and delivery capabilities.

A [local Advisor plugin alpha.4](plugins/harness-bridge/README.md) packages one shared Skill
for Codex/ZCode. Both actual host installations share the same runtime/state connection.
Native clean install, upgrade, uninstall and reinstall preserve task data. ZCode full app quit
and relaunch retained a fake worker; Codex tool PTY reconnection was verified earlier. Full
Codex GUI shutdown and universal host survival are not claimed. See [local installation and
support boundaries](docs/LOCAL_RELEASE.md) and [P7 evidence](docs/P7_RESULT.md).

The [goal coordination reference](docs/COORDINATION.md) documents the implemented
`goal create/status/takeover`, `projects` and `create --goal` commands. Linked tasks require
the current Advisor binding/epoch on mutations; original standalone tasks remain compatible.
The [planning/control reference](docs/PLANNING.md) covers `goal plan/control` and
`child status/materialize`. The [execution context reference](docs/EXECUTION_CONTEXT.md) covers
fixed dependency versions, `retain-approved` and `child preflight`. The [preparation reference](docs/PREPARATION.md)
covers `child prepare`, cancellation/recovery and shared-resource claims. P1/P2 local cores are
implemented. The [background worker reference](docs/WORKERS.md) covers durable dispatch,
`job`, incremental `events`, cancellation and recovery. The [concurrency reference](docs/CONCURRENCY.md)
covers explicit two-slot admission, scope checks and goal wall-time/turn reservations. P3 local core
is implemented. The [integration reference](docs/INTEGRATION.md) covers the first P4 slice:
frozen approved inputs, owned candidate workspaces and durable conflict/crash handling. Total-goal
checks and exact Advisor approval are covered by the [verification/review reference](docs/INTEGRATION_CHECKS.md).
The [local delivery reference](docs/DELIVERY.md) covers exact branch delivery, crash recovery and
READY_TO_DELIVER/DELIVERED projections. [Integration repairs](docs/INTEGRATION_REPAIRS.md) bind
conflict/failed-check children to retained inputs and existing budgets; [cleanup](docs/CLEANUP.md)
removes only selected clean owned worktrees after delivery, retaining refs/evidence and user changes.
P4 local core, P5 Codex offline adapter and P6 model-free installed wiring are implemented;
P7 bounded native collaboration, repair, delivery, cancellation retest and turn-stop passed.
Desktop synchronization remains open: Claude handoff is implemented but awaits UI acceptance;
Codex's supported desktop-list route is still unresolved. See [desktop continuity](docs/DESKTOP_SESSIONS.md).
See [Codex capability boundary](docs/CODEX_EXECUTOR.md). Approval alone
does not deliver a goal.

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

## Live Claude Code mode (bounded smoke and repair verified)

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
auto-retry interrupted work or merge delivered results into the user's checkout, and makes no claim that two models are
better or cheaper than one (see [`docs/EVALUATION_PLAN.md`](docs/EVALUATION_PLAN.md)).

## Project documents
`STATUS.md` (current state) · `HANDOFF.md` (next work package) ·
`docs/VALIDATION_MATRIX.md` · `docs/ARCHITECTURE.md` · `docs/TESTING.md` ·
`docs/DECISIONS.md` · `docs/ENVIRONMENT.md` · `docs/LOCAL_HANDOFF.md` · `docs/BACKLOG.md` ·
`docs/PROJECT_PLAN.md` · `docs/PRODUCT_FORM.md` · `docs/PLUGIN_ALPHA_RESULT.md` ·
`docs/CLOUD_EXECUTION_PLAN.md` (original requirements).

Licensed under [Apache-2.0](LICENSE). Only a local release candidate is authorized; no remote
push, package upload or marketplace publication is implied.
