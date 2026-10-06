# Codex executor: offline adapter and capability boundary

Implemented 2026-10-06 as P5's offline core. Codex is selectable in TaskSpec and child plans,
uses the existing worktree/worker/check/review pipeline and emits the same bridge receipts.
**Actual Codex dispatch is unavailable.** The adapter rejects live mode before reserving an
attempt or invoking a binary, even with all ordinary live opt-ins set. This is not a new paid
validation authorization and does not certify subscription routing.

## User-facing contract

The Advisor is still the user's existing agent session. It can plan a `codex` child, materialize
its fixed baseline, send feedback and review evidence through the same CLI as a Claude child.
Bridge selects the folder and creates the worktree; the Executor does not choose either.
The only executable Codex route currently requires `--mode mock --stub-binary /absolute/stand-in`.
The stand-in is trusted local test code, not a security sandbox or a way to run a real renamed CLI.
Neither the plugin nor the Advisor may describe this as a working real Codex Executor yet.

The `executor` portion of a TaskSpec is:

```json
{
  "kind": "codex",
  "requested_model": null,
  "sandbox": "workspace-write",
  "resume_on_repair": true
}
```

`requested_model` may be a nonempty explicit model identifier; null means no pin is requested,
not a default Claude model. Only `read-only` and `workspace-write` are accepted for sandbox.
Claude-specific permission/tool/MCP options and fake scenarios are rejected. A parent GoalSpec
must explicitly include `codex` in `allowed_executors`; its default remains `fake`.
Existing fake/Claude TaskSpec and plan JSON keep the same canonical shape and digests. Database
revision remains 10; this slice adds no schema migration or user-state conversion.

## Evidence and limitations

Official references checked on 2026-10-06:

- [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode): JSONL thread/turn/item
  envelopes and reported token counts.
- [CLI reference](https://learn.chatgpt.com/docs/cli/reference): stdin prompt and explicit exec
  session resume, model and workspace options.
- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference):
  `approval_policy="never"` is the non-interactive policy. It does not disable sandboxing.

Local non-inference observation: the installed binary reported **codex-cli 0.160.0**. Only
`--version`, `exec --help`, and `exec resume --help` ran, with a temporary empty HOME/CODEX_HOME,
temporary cwd and a minimal environment. No auth file, user configuration, model, login or session
was opened. Help lists JSONL, model, sandbox, working directory and stdin options on `exec`, and
an explicit session ID plus stdin on `exec resume`. Parent exec options are placed before the
resume subcommand in the proposed argv. **This arrangement has stub evidence, not native execution
or native parse-probe evidence.** No extra native probe was run to demonstrate it.

| Capability | Evidence now | Runtime policy |
| --- | --- | --- |
| Structured normal completion | Docs-derived envelopes, synthetic values, stub pipeline | Accept only one bound thread/start/completion and exit 0; then independent checks |
| Exact-session repair | Explicit UUID argv; foreground and worker stub repair | Same task/repo/worktree/executor/requested model; returned UUID must match |
| Refusals/errors | Synthetic failure/stderr cases | Stop, no automatic retry; text hints labeled heuristic, reset unknown |
| Wall deadline/cancel/known exit | Existing runner and real local stub processes | Keep existing owned-process and reservation rules |
| Model-step/turn ceiling | Not established by docs/help observations | Live refused; never invent a flag or substitute prompt/wall time |
| Actual model identity | Not established by the documented exec envelope | Observed model null, requested pin unknown |
| Subscription/auth/provider provenance | Not checked | Live refused; no API/provider fallback |
| Effective hooks, MCP, rules and permissions | No reviewed live configuration | Live refused; no ignore-config/rules or bypass flags |
| Native recovery/workspace behavior | No live Codex evidence | Live refused; mismatched stub resume blocks |

The absence of a ceiling in the checked material means **unknown**, not a universal claim that
Codex cannot support bounded operation. A `turn.completed` envelope represents this exec turn;
it is not proof of how many internal model steps ran. Goal accounting still reserves requested
ceilings for stub attempts. Native enforcement needs a supported, auditable mechanism before the
live gate can be opened; another subscription-consuming smoke alone cannot solve that gap.

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

## Verification and next boundary

`tests/contracts/test_codex_adapter.py` contains 48 contract cases and
`tests/integration/test_codex_stub_flow.py` contains 20 integration cases. Fixtures explicitly
record docs-derived/synthetic provenance; no captured-live Codex stream is claimed. The stand-in
performs real local edits, and real bridge verifiers independently detect/fix the seeded bug.
Isolated HOME/auth sentinels and the existing Python network guard apply. See
[VALIDATION_MATRIX.md](VALIDATION_MATRIX.md) for exact completed runs and development failures.

The next work can proceed without model usage: reconcile a supported bounded Codex execution
mechanism and its configuration/auth evidence, and update/install-check the P6 Advisor entrypoints
against the goal/child/worker workflow. Installed-host behavior and P7 one-Advisor/two-real-Executors
acceptance remain separate. P5 offline completion is not completion of V1.
