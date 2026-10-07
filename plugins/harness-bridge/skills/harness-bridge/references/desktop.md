# Existing Executor conversations in desktop apps

Use this workflow when the user wants Executor chats visible in their native desktop lists,
including as a delivery follow-up to an earlier request. Operate the trusted runtime yourself;
do not ask the user to transfer prompts, pick workspaces or create replacement conversations.

Query each relevant child using the same connection/state as its goal:

```sh
hbridge --state-dir /absolute/state --json desktop status TASK_ID
```

Keep the returned task, native session ID and original worktree together. Status invokes no
harness and grants no model allowance. Do not infer execution failure from a missing sidebar
item, or infer sidebar visibility from the presence of a transcript.

## Claude desktop handoff

For a requested handoff, inspect `can_request_open`, `blockers` and `last_request`. The current
route is macOS with Claude Code 2.1.291, a terminal child and a delivered parent goal, confirmed
Executor exits, and the current Advisor claim. Running/review/repairable tasks remain in Bridge.

If the desktop is available and these conditions hold, perform the existing-session handoff:

```sh
hbridge --state-dir /absolute/state --json --advisor-binding BINDING --advisor-epoch 1 \
  desktop open TASK_ID --idempotency-key desktop-first-open
```

Reuse that request on reconnection. Bridge records it before opening and never repeats it,
even under a different key. Inspect the receipt's `status`, not just CLI `ok`:

- `native_open_requested`: native CLI acknowledged the same-session handoff; desktop list
  visibility is still unverified. Inspect the host's list, history and workspace with its
  available native tools. Record what was actually observed; do not send a message as a test.
- `request_outcome_unknown`: inspect the existing receipt/session before further action. Do
  not delete its event, bypass the CLI or launch another session to retry.
- `native_launch_failed`: report the retained launch failure; the current runtime does not
  provide a retry-reset operation.

If the screen is locked, GUI access is unavailable, or the user deferred opening, keep this
step pending and continue independent work. Never bypass that boundary. Preserve the original
worktree until the user has finished inspecting it. Continuing interactively is a separate
user action; the old Bridge attempt budget does not govern a manually continued desktop chat.

## Codex and other hosts

Codex currently returns `native_history_only` and `codex_desktop_list_sync_unverified`.
CLI Executor sessions have source `exec`; native default/interactive lists can omit them.
Readability, successful title changes and section/pin acknowledgements do not establish
desktop visibility. Report this remaining limitation with the existing session/workspace,
without rewriting vendor storage/source classification, forking, creating a replacement
chat or sending a turn. ZCode is an Advisor host, not a supported Executor.

Report code delivery and desktop visibility separately. This workflow adds no background
watcher, automatic model call, UI bypass, new billing mode or permission expansion.
