# Testing

```bash
scripts/check.sh            # ruff check, ruff format --check, mypy --strict, pytest -m "not live"
uv run python scripts/demo_offline.py
```

## Levels (report them separately)
| Level | Meaning | Status |
|---|---|---|
| T0 | lint, types, schema validation, command construction | run |
| T1 | unit tests: policy, state machine, store, runner, adapters | run |
| T2 | offline integration: real subprocesses (fake executor or stub binary), real temporary git repos, real verifier commands, real SQLite, separate CLI processes, injected crashes, real signals | run — **simulated executor; not a live E2E** |
| T3 | local real Claude CLI with the user's subscription | initial smoke PASS (2026-10-06) |
| T4 | real Codex/Astra → bridge → Claude → review | initial smoke + one controlled repair/resume PASS (2026-10-06); not production certification |
| T5 | comparative evaluation | NOT_RUN (format only) |

Workbench levels (plan v2.0): **T2-W** uses `tests/helpers/wb_stub.py` as stub `claude`/`codex`
executables (interactive tty, hooks via `--settings`, Codex notify, OSC 9; since W6 also the
structured protocols: Claude `-p` stream-json with the SDK control protocol, `claude --desktop
--resume`, `codex app-server` JSON-RPC, and native-style history files) with real PTYs,
subprocesses, git, SQLite and a test-owned 127.0.0.1 server. Desktop-app tests use fake `.app`
bundles in a temporary folder and a recording opener (`WorkbenchConfig.app_dirs` / `opener`), never
LaunchServices or the real apps. **UI-offline** drives the same UI with
stub CLIs. **T3-W/T4-W** (real native sessions in the App) need the user's machine outside an
agent session; see `docs/WORKBENCH.md`.

## Isolation in every test (`tests/conftest.py`)
- temporary `HOME`, `XDG_STATE_HOME`, isolated git config with a test identity;
- `ANTHROPIC_*`, `CLAUDE*`, `CODEX*`, `OPENAI_*`, `GIT_*`, `HBRIDGE_*`, GitHub tokens removed;
- sentinel `claude`/`codex` executables first on `PATH`; any invocation fails the test;
- process-level network guard (socket connect outside AF_UNIX raises). It covers the test
  process only, not child processes; it is not an OS firewall. The code under test makes no
  network calls by design. `test_workbench_server.py` re-allows only 127.0.0.1 for its own server.

## Fixture provenance
`tests/fixtures/claude_stream/*.jsonl` are **synthetic** or **docs-derived**
(`PROVENANCE.json`); `claude_help_2.1.291.txt` is captured `claude --help` text (no inference).
A parser passing on them proves only that it handles these samples. Real streams must be
captured locally, redacted and added as `captured-live` with the CLI version, never overwriting
the synthetic set. The captured-live-redacted samples now include the T3/T4 initial
smokes and a controlled repair/resume pair; provenance is in
`tests/fixtures/claude_stream_live/PROVENANCE.json`. Offline replay checks parsing/session
consistency only; actual live evidence is in `docs/LIVE_REPAIR_RESULT.md`.

## Live tests
`tests/live/` is excluded by default (`-m "not live"`) and currently contains no tests. A future
live test must require the `live` marker, the runtime live gate and an explicit per-run user
authorization; it must never auto-enable because a key or login is present.

## What is deliberately not done
No coverage-percentage target, no large fuzz/mutation campaigns. Timing-sensitive tests use
explicit handshakes (wait for state / process-group membership), small timeouts with margin.
