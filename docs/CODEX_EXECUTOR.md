# Codex Executor: budget and capability contract

Updated 2026-10-07 for runtime 0.1.0.dev1. The user explicitly authorized per-harness budget
semantics for **new** tasks. This replaces P5's unconditional live refusal; it does not rewrite
frozen tasks or authorize model usage. P7 native execution results are in [P7_RESULT.md](P7_RESULT.md).

The Advisor remains an existing agent session. Bridge creates the child's worktree, selects cwd,
launches the native CLI and records results; it never calls a model API. Only the explicit
`--mode live --allow-model-usage` route with reviewed local opt-in can run a real Executor.

## Explicit new-task contract

```json
{
  "executor": {
    "kind": "codex",
    "requested_model": "an-explicit-supported-model",
    "sandbox": "workspace-write",
    "resume_on_repair": true
  },
  "limits": {
    "max_attempts": 2,
    "max_repair_cycles": 1,
    "wall_timeout_seconds": 180,
    "max_turns_per_attempt": null
  }
}
```

These are portions of a TaskSpec, not a complete runnable specification. Explicit null means
**native internal-turn hard ceiling unsupported**. Bridge enforces attempt/repair counts,
wall deadlines and owned-process cancellation. It does not limit/count Codex's internal model
steps, infer them from JSONL `turn.completed`, or describe this budget as equivalent to Claude's
native turn cap. A parent numeric turn budget refuses such a child before dispatch; an unbounded
turn aggregate reports `reserved_turns: null`, never zero. Attempt/wall reservations still apply.

Omitted/numeric turn limits retain their old defaults and canonical representation. Those frozen
Codex tasks remain live refused before an attempt is reserved. Claude/fake tasks cannot use null.
There is no task conversion or database migration: schema remains 10. Only `read-only` and
`workspace-write` sandboxes are accepted. Live requires an explicit requested model; observed
model identity remains unknown unless the native stream establishes it.

## Native model-free preflight

The supported version is **codex-cli 0.160.0**. A configured absolute `[live] codex_binary` or
PATH selects the binary. Before reservation, `codex_preflight.py` performs version and native
app-server metadata reads (`account/read` with refresh disabled, `config/read` for child cwd).
It starts no thread or turn and never reads credential files itself. It retains only safe
provenance summaries; raw account/config values are not written to artifacts.

The gate refuses API/provider environment markers, non-ChatGPT account type, custom provider/
endpoint configuration, unreviewed external hooks and unsupported native versions/configuration.
Per-invocation overrides require ChatGPT login, the default OpenAI provider, requested model,
never approvals and the selected sandbox. Auxiliary subagents, plugins, hooks, memories, MCP,
apps, notification commands and web search are restricted; workspace network/extra writable
roots are disabled. A second native configuration read must confirm the effective restrictions.
User profiles are not rewritten and existing nested/cloud markers are never removed.

This is configuration provenance, not a billing receipt. Remaining subscription quota, actual
charges and actual model identity remain unknown. A unsupported configuration stops before
reservation, with no silent provider switch or automatic retry.

| Capability | Runtime policy and evidence |
| --- | --- |
| Structured normal completion | Strict one-thread/start/completion and exit 0; independent checks still required |
| Native initial/resume argv | Initial and exact UUID resume help/parse probes passed without inference |
| Exact-session repair | Same task/repo/worktree/executor/requested pin; returned UUID must match; P7 real result separately recorded |
| Turn hard limit | Unsupported for this route; explicit null opt-in, old numeric contracts refused |
| Account/provider/config | Current native read-only preflight passed; default OpenAI + ChatGPT, per-call restrictions |
| Wall/cancel/known exit | Shared runner contracts; native fault evidence is separately recorded in P7 |
| Model identity/cost/quota | Unknown; no inference from requested pin or prose |

## Invocation and evidence handling

Prompt, parent context and review feedback go through stdin. `cwd` and `--cd` both point at the
bridge-owned worktree. The builder requests the selected sandbox and `approval_policy="never"`;
it never adds writable roots, chooses `--last`/`--all`, forks a session, creates another worktree,
turns on a different provider, clears nested-session markers or bypasses approvals/sandbox.
The base environment is preserved. Its names, not values, enter the invocation receipt.
No `--max-turns` flag is invented for Codex; receipts explicitly expose the missing enforcement.

The parser retains event metadata and a bounded redacted agent summary. It omits reasoning,
commands/output, file bodies and MCP payloads from parsed receipts; existing bounded/redacted raw
log artifacts remain under the common artifact policy. Unknown, malformed, oversized, dropped,
truncated, duplicated or out-of-order lifecycle evidence cannot produce successful completion.
Process cancellation, timeout and unconfirmed exit dominate any claimed success. A wrong resume
UUID is not saved as a new trusted binding. Explicit resume opt-out starts a fresh session; the
bridge never silently downgrades an attempted resume after the executor refuses it.

Token counts are executor-reported invocation data. Cost, subscription remaining, actual model
and internal turn count stay unknown. Neither executor prose nor `turn.completed` substitutes for
bridge verification or exact Advisor approval. Approval/delivery and aggregate budgets remain the
existing shared contracts, including current Advisor checks on background replay.

## Validation and references

P5's 48 Codex adapter contracts and 20 stub integration cases remain the offline base.
P7 adds native-metadata stand-ins, environment/refusal guards and mixed budget accounting tests.
Tests never read real auth, access the network or launch an actual Codex binary. Manual metadata
observations are separate from those tests. See [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md).

Official references checked with installed native help/schema on 2026-10-07:
[non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode),
[CLI reference](https://learn.chatgpt.com/docs/cli/reference),
[configuration](https://learn.chatgpt.com/docs/config-file/config-reference).
Native behavior is version-specific; unsupported future versions fail closed until reviewed.
