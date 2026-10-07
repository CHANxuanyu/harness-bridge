# Optional Astra / Opus / Flash team

Use this profile when the user selects it. The current Codex conversation is the Advisor;
its model preference is Astra, verified in the host separately from Bridge metadata. Do not
open another planning conversation or change the host model implicitly. The Bridge adds no
model call to classify tasks.

| Task | Executor selection | Advisor records |
|---|---|---|
| Unknown root cause, architectural/compatibility choices, concurrency, multiple coupled modules | `claude-code`, exact `claude-opus-5-5` | Concrete uncertainty, affected contracts and acceptance |
| Fixed interface, limited scope, existing pattern, directly checkable output | `zcode`, exact `GLM-5.3-Flash` | Why bounded, fixed dependency and independent check |
| Not yet separable or testable | Investigate/split in the Advisor first | Missing evidence or decision |

These are user preferences, not measured cost/quality rankings. Tests and documentation can be
complex; file type or line count alone does not determine routing. Opus/Flash return evidence;
the Advisor retains review and integration authority.

## Prepare the plan

Adapt [goal.primary.example.json](goal.primary.example.json) and
[plan.primary.example.json](plan.primary.example.json). The example has a complex core child and
a simple dependent CLI child. Replace goals, paths, trusted acceptance programs and budgets with
the actual repository requirements. Keep the exact model pins; choose the provider only from
current account evidence, not from the example's BigModel Start Plan value. Put routing rationale
in existing `requirements`; do not add unsupported task fields.

The goal has a null total-turn ceiling because Flash lacks verified internal-turn limits. Claude
keeps its per-attempt turn ceiling; both children retain attempt/repair/wall limits. Example
ceilings are not authorization. Freeze the actual approved budget and retain spent attempts
across every routing decision. Never rewrite existing numeric-turn tasks.

ZCode is **offline-only**: check `doctor --offline` for `zcode_executor_adapter` with
`protocol_profile_revision: 2` before submitting these templates. The shipped alpha.6 runtime candidate may lack that capability even when its
version string matches newer source. Missing capability means unavailable. A supported mock
profile needs an explicit non-model protocol stand-in, not the native ZCode executable. Do not
dispatch a live probe, test-model button, or replacement chat to bypass the qualification gap.
Read [live-readiness.md](live-readiness.md) before any separately authorized native work.

For independent tasks, remove a dependency only when the repo and acceptance prove independence;
up to two concurrent executions still require configured capacity and disjoint declared scopes.
Otherwise materialization waits for the approved predecessor and uses its retained snapshot.
Follow [workflow.md](workflow.md) for commands. The user does not choose folders or carry prompts.

## Feedback and explicit escalation

Inspect job outcome, actual diff, external checks, native session binding, confirmed exit and
remaining goal budget. A targeted repair reuses the same task/worktree and original compatible
session; it never changes that task's model/provider.

Before any plan is frozen, the Advisor may change a proposed Flash assignment to Opus based on
new complexity. After a **correctly approved** Flash child, extra work can be a new Opus child
depending on that approved child, with a fresh session/worktree and the same goal budget. Record
the source child/task/snapshot, reason, remaining work and acceptance in the new requirements.
Do not pass a ZCode session ID to Claude or let both write the same workspace.

**An unapproved failed Flash child currently cannot be replaced/superseded in-place.** Every goal
child is required for integration; the dependency mechanism accepts approved snapshots only.
Retain its diff/logs and report that limitation. Do not approve failed checks, omit the old child
from integration, edit SQLite, silently copy its unreviewed work, or create a replacement goal
to reset budget. Task supersession with reviewed partial-work transfer still needs a runtime
contract and offline acceptance. An integration-repair child is for failed integration of approved
inputs; it is not a bypass for an unapproved Executor child.

Return blockers and current IDs when this unsupported transition is needed. Otherwise continue
through [delivery.md](delivery.md): total-goal checks and exact integration approval are mandatory.
