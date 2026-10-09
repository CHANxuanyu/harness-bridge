# Existing-session backend acceptance — 2026-10-09

This is the earlier backend-only acceptance record. The fixed integrated-version evidence and
remaining frontend findings are in [EXISTING_SESSIONS_INTEGRATION.md](EXISTING_SESSIONS_INTEGRATION.md).
Neither record claims real outside-created-session or real official-desktop acceptance.

## Delivered

- Exact common base: `ef75a625577c1848e1079dd6d487a5cdc3afa166` (code `2f26d23`). Independent
  worktree `/Users/chan/Downloads/repobridge-backend`, branch `codex/existing-session-backend`.
- Contract first, committed and pushed as `c20679e3d7e0915756a4901ab1b80a5ef91123c3`; then backend
  implementation continued without asking for a new approval. Final contract:
  [EXISTING_SESSIONS_API.md](EXISTING_SESSIONS_API.md).
- Project-scoped discovery/search, preview, unique association, original-ID native resume,
  bounded/delta history, desktop-return integration, removal/relink and explicit failure states.
  `native_history.py` contains the scoped readers/paging; existing server/service/store/protocol
  modules retain their responsibilities. No frontend file or desktop-shell edit.
- Schema 3→4 adds one `native_links` table because the existing session row has no native storage
  environment identity or durable unique association. No existing row data is rewritten. The
  3→4 migration is transactional and idempotent on reopen; old schema-3 binaries cannot open a
  migrated test store. The user's real store was never opened or migrated.

## Evidence

`tests/integration/test_existing_sessions.py` seeds native-shaped Claude JSONL and Codex indexed
threads **before** RepoBridge registers a session. These are isolated synthetic fixtures, not the
App-created W6–W8 acceptance threads. Stub CLIs and fake app bundles exercise real subprocesses,
SQLite and a test-only HTTP server on port 0. No real credentials, accounts or model endpoint.

102 related tests passed in 70.35 seconds: 21 new external-session cases and 81 existing workbench
regressions. A final focused external-session rerun after the external-hold wording correction passed all 21
cases in 20.11 seconds.
Ruff check and format passed (185 files); strict mypy passed (59 source files). The full baseline
942-test check at `2f26d23` is retained; it was not repeated or claimed as a test of this new commit.

Affected regression command from this backend checkout:

```sh
PYTHONPATH=src python -m pytest -q \
  tests/integration/test_existing_sessions.py \
  tests/integration/test_workbench.py \
  tests/integration/test_workbench_server.py \
  tests/integration/test_workbench_conversation.py \
  tests/integration/test_workbench_settings.py \
  tests/unit/test_workbench_units.py \
  tests/unit/test_workbench_conversation_units.py \
  tests/unit/test_workbench_controls.py
ruff check .
ruff format --check .
PYTHONPATH=src mypy src/harness_bridge
```

This machine reused the existing frontend `.venv/bin/python`, `ruff` and `mypy` read-only because
the offline uv cache lacked the locked mypy package. `PYTHONPATH=src` selected the new backend
sources; no frontend environment/dependency file changed. Temporary test state and homes are under
pytest's temporary directories. Tests require process inspection and loopback access; sandboxed
failures on those operations are not product failures.

Read-only schema check: the installed Codex binary generated its protocol JSON schema into an
isolated temporary directory with empty HOME/CODEX_HOME. `ThreadListParams` confirms exact cwd
filtering, title search, cursor/order and `useStateDbOnly` (no JSONL metadata scan/repair). This was
schema generation only, not a native-history/account test and not a model call.

Review-driven fixes covered by the tests: link-only sessions can open in a supported desktop
without fabricated observed turns; wrong Codex resume IDs fail; removed associations cannot race
writer admission; per-session resume/desktop actions serialize; closed stdin is reported as an
ended process; history-read process exit must be confirmed; live paging preserves the envelope;
Codex native pages retain chronological order; relink renews the external-writer hold.

## Remaining acceptance

1. Opus adds the discovery/preview/link flow and consumes the exact API/state fields. Codex integrates
   frontend commits in an integration checkout and runs the UI checks with isolated state.
2. Choose one explicitly scoped project and a Claude/Codex native sample created outside RepoBridge.
   Record harness, exact native ID and initial known history without scanning unrelated projects.
3. Discover/preview/link/read and verify the same ID in the official client. These scoped read-only
   steps need no new model allowance; they have not been performed on the user's private history.
4. For actual continuation, obtain a new bounded real-turn allowance: native resume → one explicit
   user message → official desktop continuation → return/refresh → same-ID resume. Record every
   turn/exit and stop on native writer/auth/permission/quota errors. The prior allowance remains
   exhausted (Claude 6/6, Codex 6/6); it was not renewed or reused.

Discovery is intentionally partial: local exact-project scope only, native index visibility and
bounded readers. Unknown provenance is not labelled desktop, cloud histories are not imported,
external occupancy is not assumed idle, and unsupported native listing never falls back to a global
scan. The contract lists limits and machine-readable states. No default-branch merge or release.
