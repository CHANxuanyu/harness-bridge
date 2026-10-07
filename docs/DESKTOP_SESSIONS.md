# Desktop session continuity

Desktop chat-list visibility is an explicit product requirement added on 2026-10-07.
The first implementation exposes exact native identities and a Claude handoff. Automatic
cross-host list synchronization is **not yet accepted**. A stored transcript, native open
acknowledgement and an observed desktop list entry are three different evidence levels.

## Operator interface

```sh
hbridge --state-dir /absolute/state --json desktop status TASK_ID
hbridge --state-dir /absolute/state --json desktop open TASK_ID \
  --idempotency-key desktop-first-open --advisor-binding ADVISOR_ID --advisor-epoch 1
```

The Advisor performs these actions for the user. Status does not invoke a native harness.
Open is explicit: it never follows automatically from worker completion, review or delivery.
It creates no Executor attempt and sends no prompt. The installed alpha.4 plugin now carries requested desktop visibility through delivery and
performs the supported follow-up itself. It does not open anything while the user has deferred
GUI work or report native acknowledgement as UI acceptance.

Only terminal tasks with confirmed exits and a valid native session binding are eligible.
Linked tasks also require a currently DELIVERED parent and its current Advisor claim; approval
of a child alone is insufficient. The original worktree must still exist. This avoids opening
a competing interactive owner while Bridge may need another repair. Cleanup should happen
after the user has finished inspecting that workspace.

The native binary comes from the integrity-checked invocation; session ID must be a canonical
UUID bound to the same task, attempt, executor, requested model, repository and worktree.
The first supported route is macOS with Claude Code 2.1.291. Other versions/platforms fail
closed pending validation. The command passes only `--desktop --resume UUID`, with no stdin,
prompt, model flags or permission override. It does not use API credentials.

The request is persisted before native handoff, independently of task state and delivery.
There is at most one native handoff request per task, even with different keys or concurrent
callers. Replays return the original receipt. A crash/timeout/nonmatching acknowledgement
retains `request_outcome_unknown`; it must be investigated before any manual retry. A known
launch failure is also retained rather than silently retried. CLI `ok` indicates a receipt
was returned; inspect its `status`. `native_open_requested` still has `desktop_visibility:
unverified`. This interface never changes a task's approval or budget based on a GUI result.

## Native capabilities and actual observations

| Host | Native capability | Current evidence |
| --- | --- | --- |
| Claude | Official CLI-to-desktop handoff for an existing stopped session | Local flags/version checked; command and guards pass simulated tests; actual handoff/UI NOT_RUN |
| Codex | Original exec session can be read through native metadata | Original session read/name succeeded; section/pin metadata operations did not expose it in the app list; sync explicitly unavailable |
| ZCode | Existing Advisor conversation remains in its own host | Not an implemented Executor; no cross-harness transcript copying |

Claude documents separate CLI/Desktop lists and an explicit handoff that retains the same
session. It refuses a session already active elsewhere. See the official
[desktop guide](https://code.claude.com/docs/en/desktop#coming-from-the-cli).
Desktop permissions differ from print-mode flags; continuing interactively is a separate
user action and is not governed by Bridge's old Executor attempt allowance.

Codex documents filtering noninteractive sessions in `thread/list`; native thread metadata
access does not prove the desktop's own list includes that source. See the official
[app-server reference](https://learn.chatgpt.com/docs/app-server). Do not mutate vendor storage
or change source classification to force a sidebar entry. A supported app-specific import or
visibility route still needs to be established before implementing Codex automatic sync.

On the validation Mac, the actual Claude and Codex delivered bindings pass the read-only CLI
check. The Mac was locked and the user explicitly deferred unlocking, so no Claude open was
attempted. Codex's temporary section and pin changes were undone; its descriptive Executor
title remains. No replacement conversation or new model turn was created.

## Remaining acceptance

After manual unlock, open the already delivered Claude session once, confirm its list entry,
original UUID, complete history and exact worktree. Sending a message is unnecessary. Confirm
receipt replay creates no duplicate. Establish and verify a supported Codex route. The alpha.4 Advisor follow-up is installed,
but it continues to report that unsupported route explicitly. Live display during execution and
bidirectional interactive takeover require separate ownership/capability work; neither is
implemented by this finished-session handoff.

Tests use synthetic rows/native acknowledgements, real SQLite/fresh CLI processes, racing
callers, invalid bindings, active states, stale Advisors and interruption. They never read
native credentials or launch native applications/models. Existing state schema remains 10.

## Alpha.4 native entrypoint evidence

The installed Codex and ZCode packages are alpha.4; all 16 cached files match source, their
connection checkers pass 36 command surfaces without opening selected state, and unrelated
plugins/connection are unchanged. Native Codex skills/list resolves the updated Skill for the
repository and Advisor chat cwd. This is metadata loading, not GUI refresh evidence.

A native read-only probe against Codex 0.160.0 found the existing Executor's source is `exec`.
For its exact worktree, default and explicit interactive lists return zero results; explicit
`sourceKinds: ["exec"]` returns the original session. This establishes native filtering and is
consistent with the desktop-list omission; it does not prove which query the GUI currently uses.
No resume, new thread, turn, source rewrite or import was used. The user is away from home and
has explicitly deferred GUI work until manual unlock.
