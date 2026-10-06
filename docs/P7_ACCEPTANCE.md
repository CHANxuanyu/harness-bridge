# P7 historical offline rehearsal and original preparation

**Current native/distribution result: [P7_RESULT.md](P7_RESULT.md).** The capability refusal and
future budget below describe the earlier preparation milestone, before the user approved
per-harness budgeting and the later seven-execution packet. They are preserved as history.

Prepared 2026-10-07. This extends the canonical [project plan](PROJECT_PLAN.md); it does not
change the product scope or authorize a model call. **P7 live acceptance is NOT_RUN.**

## Runnable preparation

From the repository root, with the existing development environment:

```bash
.venv/bin/python -m qa.local.p7_fixture /absolute/path/to/new-packet
.venv/bin/python -m qa.local.p7_rehearsal /absolute/path/to/different-new-rehearsal
```

Each command requires a new directory, refusing existing empty directories and symlinks too.
Preparation creates a disposable Git repository, two validated child plans, frozen external
checks, a hash manifest and two synthetic stand-ins. It does not open a task store or an auth
profile. The rehearsal prepares its own fresh packet, isolated HOME and explicit state, with
two execution slots and live disabled. It invokes only its generated stand-ins through explicit
mock CLI commands; it accepts no live flag, executor path, existing state or model override.
The runtime, installed plugin caches, default connection and historical tasks are untouched.

`result.json` is the detailed local receipt; failure preserves evidence and attempts to cancel
only this rehearsal's tasks, writing `failed-cleanup.json`. An unknown cancellation must be
inspected, never reported as confirmed. All successful worker receipts require confirmed exits.
The checks are trusted local scripts, not an OS security boundary against same-user tampering.

## Scenario and fixed limits

The fixture is a tag formatter with two independent modules:

| Child | Adapter | Writable file | Acceptance |
| --- | --- | --- | --- |
| Normalize | Claude Code shaped stand-in | `tagnorm/normalize.py` | Strip/lowercase/deduplicate nonempty strings, preserve first occurrence and input |
| Render | Codex shaped stand-in | `tagformat/render.py` | Bracket each string, join with comma/space, preserve order/input, handle empty list |

Both children start from the same pinned source commit in separate Bridge-owned worktrees.
The normalization task explicitly stages its first attempt as diagnosis-only; its mandatory
checks therefore fail. Requirements and acceptance remain fixed across repair. This is a
controlled failure, not evidence that a real model spontaneously failed.

The rehearsal checks this sequence through fresh CLI processes:

1. Register one goal, freeze two children and materialize their workspaces.
2. Start two background stand-ins and observe both RUNNING before releasing either.
3. Replay the same dispatch keys without creating jobs/attempts; simulate a second existing
   Advisor taking over while both jobs run. Refuse the old Advisor's plan write.
4. Reconnect, read incremental events and confirm both exits. The normalizer failed external
   verification; the renderer passed. Each worktree still contains the other module's original stub.
5. Send frozen-requirement feedback and resume the normalizer's exact session in its original cwd.
   Independently verify and approve both children.
6. Compose a separate candidate, run combined normalization/render acceptance, approve its exact
   snapshot, and deliver a new local branch. Replayed delivery returns the same receipt.
7. Check unchanged source checkout, matching delivery commit, unchanged packet/check hashes,
   exactly two Claude-shaped invocations and one Codex-shaped invocation, and confirmed worker exits.

| Ceiling | Frozen value |
| --- | --- |
| Goal executions / repairs | 3 / 1 |
| Normalizer executions / repairs | 2 / 1 |
| Renderer executions / repairs | 1 / 0 |
| Per execution declared turns / wall time | 10 / 600 seconds |
| Goal reserved turns / cumulative wall time | 30 / 1800 seconds |
| Concurrent children | 2, disjoint write scopes |

Declared and reserved ceilings are accounting evidence here, **not native Codex turn-enforcement
evidence**. Synthetic model pins and Advisor session references are conspicuously synthetic.
No generated packet is approved for live use. Do not rename a real harness binary as a stand-in.

## Codex capability audit

Reused the installed CLI **0.160.0** help observations and the local JSON schemas already generated
in P6. No new native inference/parse probe, auth/config read, login, thread or turn was started.
The generated `TurnStartParams` describes cwd, model, approval/sandbox and input fields without
an explicit internal model-step ceiling. `ThreadGoalSetParams.tokenBudget` concerns goal tokens;
it does not establish a per-attempt model-step limit. These observations are version-specific,
not a universal assertion that no Codex interface can ever enforce one.

Current official references checked on 2026-10-07:

- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) documents
  `forced_login_method` and hooks. A configured ChatGPT login restriction is a candidate control,
  not proof of this execution's subscription routing, effective provider or reviewed hooks/MCP.
- [Developer commands](https://learn.chatgpt.com/docs/developer-commands) describes native execution
  and session resumption. The inspected command reference did not establish a hard internal-turn cap.
- [Follow a goal](https://learn.chatgpt.com/use-cases/follow-goals) describes persistent goal work;
  this is not evidence that the bridge's per-attempt turn ceiling is enforced.

All four gaps in [CODEX_EXECUTOR.md](CODEX_EXECUTOR.md) remain open: enforceable model-turn
ceilings, subscription/provider provenance, effective hooks/MCP/permission configuration, and
native repair/workspace binding. The unconditional live refusal stays in place before reservation.
Prompt instructions, wall deadlines, token budgets and one JSONL `turn.completed` are not substitutes.

## Future bounded live packet — not an authorization

Only after Codex's capability gates can be satisfied should the Advisor prepare a **new** fixture,
pin supported actual models/versions and the current Advisor session, review effective auth/provider
and permission configuration, and present a concrete per-run proposal. Proposed scope is the same
two-child scenario: **at most 3 Executor executions (2 initial + 1 normalization repair)**, the
limits above, existing subscriptions, no billing-source change or automatic retry. Prior two-attempt
repair authorization is exhausted and does not cover this proposal.

The Advisor must inspect actual diffs and evidence before approval; the rehearsal's scripted
approvals only apply to its freshly generated synthetic fixture. Stop on unsupported capabilities,
quota/auth/permission errors, wrong session/workspace/model evidence, unknown exits or exhausted
limits. Close the isolated live gate after confirmed completion/non-start. Never drop a required
flag, switch providers, widen permissions, make an extra attempt or consume shared-default state.

This single scenario does not prove every P7 criterion. The remaining acceptance is explicit:

| Item | Evidence still required |
| --- | --- |
| V01 / V12 actual Advisor + two real executor harnesses | Authorized native end-to-end run after Codex capability work |
| V05 native repair for Codex | Separate bounded scenario; this packet repairs the Claude child |
| V06 dependency snapshots | Existing offline tests remain valid; these children are independent |
| V07 interruption/timeout/limit exhaustion | Separate native fault/limit cases with their own explicit ceilings |
| V08 full host shutdown | Real application termination/reconnect; simulated claims are not native chat handoff |
| V10 integration conflict | Separate conflict/repair scenario; this packet deliberately uses disjoint modules |
| V13 distribution lifecycle | Clean install/update/uninstall retaining tasks, supported-host/version matrix |
| Release | License and publication scope resolved before any external release |

See [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md) for this slice's actual results. No new full-suite,
live readiness, quality/cost comparison, public release or push is implied by an offline pass.
