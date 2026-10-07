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

The runtime provides a bounded PTY for Claude's terminal-only launcher without writing input.
Reuse that request on reconnection. Bridge records it before opening and normally never repeats
it, even under a different key. Inspect the receipt's `status`, not just CLI `ok`:

- `native_open_requested`: native CLI acknowledged the same-session handoff; desktop list
  visibility is still unverified. Inspect the host's list, history and workspace with its
  available native tools. Record what was actually observed; do not send a message as a test.
- `request_outcome_unknown`: inspect the existing receipt/session before further action. Do
  not delete its event, bypass the CLI or launch another session to retry.
- `native_launch_failed`: report the retained launch failure; the current runtime does not
  provide a retry-reset operation.

The only explicit retry exception is `legacy_pipe_retry_available: true`: dev1's pinned
Claude 2.1.291 launcher returned exit 1 because the old transport redirected stdin/stdout,
which it rejects before opening. After inspecting that exact receipt, use a fresh key and
`--retry-legacy-pipe` once. The old failure stays recorded. This flag cannot retry missing-exit,
timeout, acknowledged or newer PTY requests, and is never a general unknown-outcome reset.

If the screen is locked, GUI access is unavailable, or the user deferred opening, keep this
step pending and continue independent work. Never bypass that boundary. Preserve the original
worktree until the user has finished inspecting it. Continuing interactively is a separate
user action; the old Bridge attempt budget does not govern a manually continued desktop chat.

## Codex and other hosts

For Codex, `existing_thread_deep_link` uses the same `desktop open` command and ownership/
terminal/delivery guards. On the validated Mac, runtime dev2 checks the installed app identity,
version, URL registration and original embedded CLI, then asks that app to open
`codex://threads/EXACT_UUID`. It passes no prompt, new-chat path, fork or turn request.
Supported desktop versions: ChatGPT/Codex 26.930.31730 and 26.930.51102, both with embedded
CLI 0.160.0. Other installations
remain blocked pending validation. See the official [existing-chat link reference](https://learn.chatgpt.com/docs/reference/commands).

Default native lists can omit `exec` sessions even when the desktop shows them. Do not infer
failure from that filter or success from a native open receipt alone. Verify the original
page/list/history/worktree using available UI access; a user's explicit visual confirmation
is separate human-observed evidence if tools cannot inspect that host. Never bypass a tool's
UI access refusal. Do not rewrite vendor storage/source classification or send a test turn.
ZCode is an Advisor host, not a supported Executor; it can invoke the same runtime handoff.

Report code delivery and desktop visibility separately. This workflow adds no background
watcher, automatic model call, UI bypass, new billing mode or permission expansion.
