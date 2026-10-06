# qa/local — disposable live-validation materials

These files prepare fixtures; **running the generator invokes no model**. Actual authorized
T3/T4 initial smokes and controlled repair/resume have now passed on this Mac. Their evidence
is in `docs/LOCAL_SMOKE_HANDOFF.md`, `docs/T4_SMOKE_RESULT.md` and
`docs/LIVE_REPAIR_RESULT.md`; do not confuse fixture preparation with executing those tests.

| File | Purpose |
|---|---|
| `make_fixture.py` | Generates a disposable `slugkit.slugify` repository, external acceptance script and validated initial-smoke TaskSpec. |
| `task-live-smoke.example.json` | Example only; regenerate actual absolute paths. |

The external acceptance script lives outside the candidate repository. Its required checks
cannot be satisfied simply by modifying repository tests. Never target Harness Bridge itself
with these smoke tasks or reuse an earlier task's completed implementation as a fresh fixture.

## Isolated command pattern

Complete `docs/LOCAL_HANDOFF.md` §2 and obtain the bounded per-run authorization first.
Use a fresh root and an explicit isolated state directory for every hbridge command:

```bash
uv run --frozen python qa/local/make_fixture.py <FRESH_ROOT>/fixture
uv run --frozen hbridge --state-dir <FRESH_ROOT>/state --json doctor
uv run --frozen hbridge --state-dir <FRESH_ROOT>/state --json create \
  --task <FRESH_ROOT>/fixture/task-live-smoke.json --idempotency-key <UNIQUE_KEY>
# Only with the isolated config opt-in and explicit model-use authorization:
uv run --frozen hbridge --state-dir <FRESH_ROOT>/state --json run <TASK_ID> \
  --mode live --allow-model-usage
uv run --frozen hbridge --state-dir <FRESH_ROOT>/state --json artifacts <TASK_ID>
```

The generator's preset is **one initial attempt, zero repairs**, 10 turns and 600 seconds.
It does not enable live or execute a model. For an expressly authorized controlled repair,
prepare a separate TaskSpec before create with 2 attempts / 1 repair and the staged requirements
recorded in `docs/LIVE_REPAIR_RESULT.md`; do not amend a task or weaken checks mid-run.

Executor remains Claude Code / `claude-opus-5-5`; permitted Bash is scoped to
`Bash(python3 -B -m unittest:*)`. The bridge runs external acceptance independently.
CLI 2.1.291 and its `--max-turns` acceptance were verified on 2026-10-06; reuse that evidence
only for the unchanged installation, as described in the current preflight.

After every attempt, close the isolated live gate. Review actual diff, verified snapshot,
model/session, exit status and independent checks before approving. Never publish raw logs,
credentials, databases or worktrees here; never add permission-bypass flags or broaden shell access.
