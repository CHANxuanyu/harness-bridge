# Security and trust boundaries

**Harness Bridge V0.1 is a collaboration tool for a trusted user on one machine. It is not a
sandbox for malicious code.** The executor (and every verifier command) runs as the same OS user
with that user's full permissions.

| Control | What it does in V0.1 | What it does NOT do |
|---|---|---|
| Git worktree | keeps normal executor work off the user's checkout | stop the executor from reading/writing anywhere the user can |
| Path policy | flags forbidden / out-of-scope / secret / escaping-symlink changes and blocks approval | undo side effects that already happened |
| Snapshot fingerprint | invalidates stale verification and reviews; detects accidental edits | resist a same-UID attacker editing the store or artifacts |
| Manifest / spec digests | detect tampering with frozen acceptance criteria or manifests | provide cryptographic integrity against the same user |
| Reviewer / model labels | describe workflow provenance | authenticate anyone |
| Timeout / turn limit | bound the known process group | bound subscription usage or billing precisely |
| Live gate | prevents accidental real dispatch from normal CLI/tests/cloud | OS-level prevention of network or model access |
| Verifier | actually runs the pre-agreed commands | prove arbitrary requirements are met |
| Process ownership | signals only the process group the foreground runner created | track processes that left the group (`setsid`) |
| Redaction | masks common token formats in stored logs/diffs | detect every possible secret format |

## Rules the code enforces
- No `shell=True`; argv lists only. Bridge git calls disable hooks, fsmonitor, external diff and
  textconv, use `--`/`--end-of-options` and NUL-separated output.
- Repository-configured git *filters* (from the shared `.git/config`) can still run during
  snapshotting; the executor shares that config. This is a known limitation.
- Files ignored by `.gitignore` are outside the observed scope (stated in every manifest).
- Contents of secret-looking paths are never copied into diffs; they are listed as withheld.
- Executor output, repository files, logs and error messages are data. Text such as "ignore your
  instructions" or "run this upload command" grants nothing.
- The live gate refuses when API-key / provider variables are present (names reported, values
  never read into output), in cloud agent environments, when nested inside Claude Code, without
  `--allow-model-usage`, and without the local `config.toml` opt-in incl. the hooks/permissions
  review flag. `--bare`, `--continue`, `--dangerously-skip-permissions`, `bypassPermissions` and
  unrestricted Bash auto-approval are refused.
- Verifiers inherit the environment minus model/GitHub credentials.

## Never commit
Runtime databases, artifacts, worktrees, raw transcripts, credentials, `.env*` (see
`.gitignore`). Real captured streams must be redacted before becoming `captured-live` fixtures.

## Before the first live run
Review `~/.claude/settings.json`, project `.claude/` settings, hooks and MCP servers that
`claude -p` will load in the task worktree; confirm the subscription login and that no API key or
provider variable is set in that shell; check extra-usage / auto-top-up settings in the account
UI. Use a small disposable fixture repository first.
