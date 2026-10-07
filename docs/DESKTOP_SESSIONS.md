# Desktop session continuity

Runtime **0.1.0.dev2**, plugin **0.1.0-alpha.6**. This opens a finished Executor's existing
conversation without a prompt or new task. Native history, native open acknowledgement and
observed desktop visibility are separate evidence. Running-session display and bidirectional
interactive takeover are not part of this handoff.

## Commands and ownership

```sh
hbridge --state-dir /absolute/state --json desktop status TASK_ID
hbridge --state-dir /absolute/state --json desktop open TASK_ID --idempotency-key desktop-first-open --advisor-binding ADVISOR_ID --advisor-epoch 1
```

The Advisor performs the requested follow-up before cleanup. Status invokes no native harness.
Open requires a terminal task, confirmed exits, a canonical UUID bound to the same task,
attempt, executor, requested model, repo and original worktree, plus an intact invocation.
Linked goals must be DELIVERED with the current Advisor claim. Preserve the worktree during
inspection. A later interactive message is a separate user action outside the old attempt.

Requests are durable before launch. Repeated or different keys return the receipt without
opening again. Interrupted/unknown results do not retry automatically. Native acknowledgement
still reports `desktop_visibility: unverified`; record UI evidence separately. No approval,
Executor budget or frozen task is changed. Raw native output is not persisted.

## Supported native routes

| Executor | Validated route | Actual evidence |
| --- | --- | --- |
| Claude Code | macOS, CLI 2.1.291; `--desktop --resume UUID` on a bounded PTY without input | Original UUID/sidebar/history/worktree verified by computer use |
| Codex | macOS apps 26.930.31730 / 26.930.51102, embedded CLI 0.160.0; `codex://threads/UUID` | Original page/sidebar confirmed by the human; subsequent runtime URL and replay acknowledged |
| ZCode | Advisor using the shared runtime | Not an implemented Executor |

Claude rejects redirected input/output before opening. Dev2 supplies terminal descriptors,
writes no input, bounds duration/output and reaps its launcher on timeout or observation
failure. The matching acknowledgement is required. The stopped session retains its identity:
[Claude desktop documentation](https://code.claude.com/docs/en/desktop#coming-from-the-cli).

Codex's original executable must belong to the validated app; app identity/version/URL
registration and CLI version are checked. The runtime directs the official existing-thread
URL to that exact app, with no prompt/new-chat/fork/turn request. See the official
[existing-chat link reference](https://learn.chatgpt.com/docs/reference/commands).
LaunchServices acceptance is not UI proof. Native default list filters can omit an exec
session visible in the actual sidebar. Human observation must be labeled as such; never
bypass a computer-use refusal to inspect Codex itself or rewrite vendor storage/source.

## Narrow recovery for the dev1 pipe defect

Dev1 used DEVNULL/captured output, which pinned Claude 2.1.291 unconditionally rejects before
opening. The initial exit-1/unknown receipt remains in history. Its cause was established from
the local launcher implementation, not inferred from exit 1 in general.

Only when status reports `legacy_pipe_retry_available: true`, inspect that receipt and use
one fresh key with `--retry-legacy-pipe`. Current ownership/binding/version guards still apply;
the new request records its transport and superseded key. Concurrent callers launch once.
Missing-exit, timeout, success and newer PTY/URL requests never qualify. No events are reset.

## Observations after unlock — 2026-10-07

Claude's corrected request opened UUID `347cb6dd-57aa-4157-9860-d67a2cd5e1b1`. Computer use
observed the original prompt, Read/Edit/denied-command history and final reply; Show in Finder
selected the exact original worktree. Title: **Harness Bridge · P7 Claude Executor · 已交付**.
Replaying left one sidebar item. The original failed pipe request remains recorded.

Native Codex navigation opened UUID `01a11375-1bfc-7ba3-a351-8d206887423c`, titled
**Harness Bridge · P7 Codex Executor · 已交付**. The human replied “页面和左侧列表都能看到”.
The list API still omitted it. Runtime URL dispatch/replay then passed after a version-prefix
preflight correction (`codex-cli`, not `codex`). After full GUI quit/relaunch, the human confirmed “仍在列表，原历史也能打开”.
The independent fake-worker lifecycle also passed; see [GUI evidence](P7_GUI_LIFECYCLE.md). No new Executor attempt/model message was sent.

Actual alpha.5 caches match all 16 files in both hosts; 36-command checks resolve dev2 through
the unchanged connection. Unrelated plugins are unchanged. Private receipts are retained in
the takeover chat's `work/p7-desktop-unlocked/` and `work/p7-plugin-alpha5/`. Store revision
stays 10. Tests use isolated synthetic apps/launchers, never native credentials or real models.

## App update compatibility closure

The host updated from 26.930.31730 to 26.930.51102 during the accepted GUI restart. Native CLI
stayed 0.160.0, and the human confirmed the original list/history. A restricted system-open
probe returned LaunchServices -10827 despite the executable being present; the exact same URL
command then returned exit 0 in an explicitly approved system context. This is native-open
acknowledgement, separate from the human UI evidence. Existing Bridge receipts were untouched.
Both exact app versions now pass the version gate; arbitrary future versions remain refused.
Alpha.6 updates both installed Advisor references. No new task, turn or model call was made.
