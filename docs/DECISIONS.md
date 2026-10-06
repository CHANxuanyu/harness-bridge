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
