# Handoff

## Repo and revision
- Actual repository / visibility: CHANxuanyu/harness-bridge / **public** (plan expected private)
- Working branch: claude/new-repo-plan-dn1eac
- Last verified code revision: M2 commit on this branch (see `git log`)
- Remote push verified: no (held pending the user's visibility decision)

## Current milestone
- Completed: M1 vertical slice and M2 repair/recovery (see docs/VALIDATION_MATRIX.md).
- In progress: M3 Claude CLI adapter (offline contract only).

## Verification actually executed
- `scripts/check.sh -q` → 140 passed, ruff + mypy clean (Linux, Python 3.11.17).
- `hbridge demo --scenario success|bug-then-repair` → demo_passed true.
- Live Claude: NOT_RUN. Live Codex→Claude: NOT_RUN.

## Constraints still in force
- Development model: Opus 5.5 (`claude-opus-5-5`, from session metadata)
- No extra model API budget; no nested live harness in Cloud
- Runtime mode remains mock unless locally and explicitly authorized
- Development bonus remaining: unknown

## Next bounded work package
- Goal: M3 Claude adapter offline contract.
- First command: `scripts/check.sh -q`
- Do NOT: auto-retry interrupted attempts, signal processes the runner does not own.
