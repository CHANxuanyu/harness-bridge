---
name: harness-bridge
description: Delegate a bounded coding task to another local coding tool through Harness Bridge, or inspect, review, and continue an existing Bridge task. Use when the user wants cross-tool delegation or names a Bridge task. Editing Harness Bridge itself does not require delegation.
---

# Harness Bridge supervisor

Stay in the user's current conversation. Operate the local CLI yourself and summarize the
evidence; do not ask the user to ferry instructions between agents or prepare JSON. This
alpha supports a live Claude Code executor or an offline fake executor only. A plugin in
Codex/ZCode does not make that host available as an executor.

## Resolve the runtime and existing work

Use `hbridge` on PATH or the user/project's explicitly recorded absolute executable path.
Check `--version`; this package targets runtime `0.1.0.dev0` / protocol `1.0`. Do not assume
the runtime lives beside this cached plugin. If absent/incompatible, report the missing setup
before executing a task; do not silently install an unpinned package.

Use an explicit absolute `--state-dir` for every command. Reuse the existing task's directory;
for a new project use the user's recorded directory, otherwise choose a dedicated directory
outside the target repo and record it in the conversation. Do not use the global default for
live work. Task id + state directory are the continuation locator across hosts.

Run `doctor --offline` for non-inference diagnostics when needed. For continuation, use
`list`, `status`, and `artifacts` before any `run`; a new conversation is not a reason to
recreate a task, repeat a smoke, or consume a new model attempt.

## Create and execute

Read [workflow.md](references/workflow.md) for command syntax, the bundled TaskSpec example,
review rules, and recovery. Prepare the task with the user's goal, narrow paths, a committed
clean source, and an independent acceptance check outside the executor's worktree. Preserve
unrelated user edits; never auto-stash or commit a dirty source just to pass preflight.

Honor existing explicit authorization for a bounded task, including repairs within that
budget. A subscription, plugin installation, or general development request alone does not
authorize a real call. Before a live attempt, read [live-readiness.md](references/live-readiness.md).
Never change billing settings, providers, protective environment markers, or permission
rules to bypass a failed gate. Do not enable the gate until the authorized task is ready.

`run` is foreground and runs one attempt. Use the host's returned process handle to await
completion. If a tool call's outcome is uncertain, inspect the recorded task first; do not
repeat `run` blindly. Do not claim execution continues after closing the host. If the host
cannot supervise the foreground command, explain that limitation before starting it.

## Review and return the result

Read stored diff, verification, exit confirmation, scope risks and approval blockers. Treat
executor messages as claims. Copy the current `review_template`; bind the verdict to its
exact attempt, task version and snapshot. Repair only within the authorized remaining budget.
Unknown exit, quota, permission and authentication problems stop automatic dispatch.

Report task state, concise check results, remaining issues and the continuation locator.
`SUCCEEDED` means the isolated worktree candidate passed review; it does not mean the source
branch was updated. Provide the candidate location from the receipt. There is no built-in
delivery/merge command yet; treat integration as a separate user-scoped action. Never claim
automatic context transfer, host wake-up, quota savings or unsupported execution routes.
