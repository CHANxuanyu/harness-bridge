# Decisions (short ADR log)

Each entry: decision — reason. Newest last.

1. **Use the user-created repo `CHANxuanyu/harness-bridge` directly** on the platform-assigned
   branch `claude/new-repo-plan-dn1eac` — it was empty and created for this task; the plan says to
   follow a platform-specified branch name over `claude/harness-bridge-mvp`.
2. **Python 3.11 floor, dev env pinned to 3.11** (`.python-version`) — the cloud host has 3.11,
   3.12, 3.13; developing on the floor version catches accidental use of newer stdlib APIs.
3. **hatchling build backend, uv lockfile, PEP 735 `dev` dependency group** — standard and
   reproducible with `uv sync --frozen`.
4. **pydantic 2 as the only runtime dependency** — schema validation with `extra="forbid"`;
   everything else is stdlib (sqlite3, subprocess, selectors, argparse, tomllib).
5. **Fake executor ships inside the package** (`adapters/fake_executor.py`, stdlib only, launched
   by absolute path with `python -I -B`) — `hbridge demo` must work from an installed package,
   not only from the test tree. It is coupled to the `normalize_tags` fixture by design.
6. **Settled attempts go to AWAITING_REVIEW, uncertain ones to INTERRUPTED** — when the owned
   process group's exit is confirmed, outcomes `succeeded/failed/protocol_error/crashed/
   timed_out` are verified and shown to the supervisor (who can request a repair); only
   `succeeded` can pass the approval gate. Unconfirmed exit → INTERRUPTED (no auto retry);
   structured permission/quota errors → BLOCKED.
7. **Snapshot = temporary index** (`read-tree <base>` + `add -A` + `write-tree`) — captures
   committed, staged, unstaged and untracked non-ignored content in one tree without touching
   any real index. Fingerprint = sha256 over {base SHA, tree SHA, task_version, verifier digest}.
8. **Forbidden globs match case-insensitively, allowed globs case-sensitively** — conservative in
   both directions on case-insensitive file systems (macOS default).
9. **Review idempotency** — accepted and gate-rejected submissions are stored under their key
   (same key + same content → same receipt; different content → conflict). Stale or
   wrong-state submissions are refused without being stored.
10. **Layout under the state dir**: `bridge.sqlite3`, `worktrees/<task_id>` (branch
    `hbridge/<task_id>`), `artifacts/<task_id>/<attempt_id>/`, `tmp/`, optional `config.toml`.
11. **Verifier environment** inherits the caller's environment minus model/GitHub credentials,
    plus `PYTHONDONTWRITEBYTECODE=1` (bytecode caches would otherwise change the snapshot).
12. **`task_version` stays 1 in V0.1** — there is no amend command yet; reviews still have to
    carry it so a future amend cannot be approved against old evidence.
13. **Executor stdout is kept head 1/16 + tail 3/16 of `max_artifact_bytes`** (stderr half of
    that); all lines are still parsed, so truncating the stored log never hides the final result.
14. **Claude adapter contract tests use a stub executable** (`tests/helpers/cc_stub.py`) through
    `run --mode mock --stub-binary` — exercises the real runner/store/verifier wiring without a
    model. The stub must not be named `claude*` nor resolve to the real binary.
15. ~~Live preflight compares used flags with `claude --help` only~~ — superseded by 19.
16. **Live dispatch additionally requires `[live] hooks_and_permissions_reviewed = true`** —
    the plan requires reviewing hooks/MCP/permissions before the first real run; this makes it
    an explicit, recorded opt-in.
17. **Provider errors detected only from text are BLOCKED with `classification: heuristic`** and
    `reset_at: null`; structured signals (`permission_denials`, `error_max_budget_usd`) are
    `classification: structured`. Nothing is retried automatically either way.
18. **Resume only for a session id observed in this task's previous attempt with a matching
    binding** (executor kind, task, repo identity, worktree); a resume the output does not
    confirm → BLOCKED `resume_failed` (never silently a new session). `--strict-mcp-config` is
    on by default to keep MCP servers out of executor runs.
19. **Flag capability = three separate evidence sources** (supersedes 15): official CLI reference
    (documents `--max-turns`; states `--help` does not list every flag), local `--help`, and the
    user's per-flag local confirmation (`[live] allow_unlisted_flags`, exact names only). Help
    absence → "unknown / pending local confirmation", never "unsupported"; docs alone never
    unlock a flag, so the existing hold stays. A run-time CLI rejection → `BLOCKED
    cli_rejected_argument`; the bridge never drops a limit flag and retries.
20. **Remote**: the user authorized making the repo private; the cloud session's GitHub tools
    have no visibility operation, so the repo stayed public and the branch was not pushed (no
    alternative credentials used). Delivery = self-contained git bundle (not version-controlled).
