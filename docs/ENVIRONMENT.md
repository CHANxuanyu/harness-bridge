# Development environment record

Recorded 2026-10-06 during the Claude Code Cloud session. Secret values are never written here;
environment variables are reported as present/absent only.

## Cloud development host

| Item | Value | How confirmed |
|---|---|---|
| OS | Ubuntu 24.04.5 LTS, Linux 6.18 x86_64 (container) | `/etc/os-release`, `uname -a` |
| PID 1 | `process_api` (not a classic init; orphaned zombies may not be reaped promptly) | `ps -p 1` |
| System Python | 3.13.16 (`/usr/bin/python3`); 3.11 and 3.12 also installed | `python3 --version`, `ls /usr/bin/python3*` |
| Project Python | **3.11.17** (pinned by `.python-version`, the declared floor `>=3.11`) | `uv run python --version` |
| uv | 0.11.32 | `uv --version` |
| Git | 2.43.0 | `git --version` |
| SQLite (Python `sqlite3` module) | 3.45.1 | `sqlite3.sqlite_version` |
| pydantic | 2.13.5 | `uv pip list` |
| pytest / ruff / mypy | 9.1.1 / 0.16.10 / 2.4.0 | `uv pip list` |
| `claude` binary | present, `2.1.291 (Claude Code)`; used **only** for `--help`/`--version` text, never for inference | `claude --version` |
| `codex` binary | absent | `which codex` |
| `sqlite3` CLI | absent (not needed) | `which sqlite3` |

## Network and GitHub

- Outbound HTTPS goes through the cloud agent proxy. PyPI was reachable for `uv sync`.
- The tests themselves make no network requests (process-level guard in `tests/conftest.py`).
- Working remote: `https://github.com/CHANxuanyu/harness-bridge` (no credentials embedded in the
  URL). It was created by the user before this session and was empty (no refs) at start.
- Repository visibility at session start: **public** (GitHub API `private: false`). The execution
  plan asks for private by default; changing visibility is the user's decision and was not done
  by the agent. Pushing was held for the user's decision (STATUS.md → Remote).
- Close-out: the user then authorized switching to private, but the GitHub MCP tools available to
  this session expose no repository-settings/visibility operation. No other route was used
  (`gh`, raw API with the ambient token). Repo stays public; branch not pushed; bundle delivered.
- Fresh-clone verification: `git clone` of the local repo at `1cc850b`, `uv sync --frozen`,
  `scripts/check.sh` → 169 passed; both demos passed.
- Working branch: `claude/new-repo-plan-dn1eac` (assigned by the cloud platform).
- `GITHUB_TOKEN` / `GH_TOKEN`: present (values not read or logged).

## Model / harness-relevant environment (presence only)

| Variable | Status |
|---|---|
| `ANTHROPIC_API_KEY` | absent |
| `ANTHROPIC_AUTH_TOKEN` | absent |
| `ANTHROPIC_BASE_URL` | present (cloud platform routing) |
| `CLAUDE_CODE_REMOTE` | present → bridge treats this host as a cloud environment and refuses live dispatch |
| `CLAUDECODE` | present → nested Claude Code session detected; live dispatch refused |
| `CLAUDE_CODE_USE_BEDROCK` / `CLAUDE_CODE_USE_VERTEX` | absent |
| `OPENAI_API_KEY` | absent |

## Development model

- Configured model: `claude-opus-5-5`; last served model: `claude-opus-5-5`.
- Source: Claude Code Remote session metadata (`get_session`: `configured_model`,
  `session_context.model`, `external_metadata.last_served_model`), not model self-report.
- Fast mode / agent teams: not enabled. No parallel cloud tasks were started.

## Budget

- `development_budget_remaining: unknown` — the session metadata exposes a rate-limit status
  (`allowed`, promotional bucket) but no balance in USD. No spend figure is claimed.
