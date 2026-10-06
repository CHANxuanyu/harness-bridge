# Supervisor entrypoint

You are the supervisor in the user's current conversation. You prepare bounded work, use
the local Bridge runtime, and review evidence. Operate the tools yourself; the user should
not carry instructions or JSON between coding agents.

The maintained workflow is the packaged
[Harness Bridge Skill](../plugins/harness-bridge/skills/harness-bridge/SKILL.md).
Read it, then its linked workflow reference before operating a task. Read live readiness
only when preparing an explicitly authorized real attempt. These files are self-contained
when the plugin is copied to a host cache.

The [plugin installation guide](../plugins/harness-bridge/README.md) explains the separate
runtime and host entrypoints. No plugin is required to invoke the CLI directly; use the
same workflow and an explicit state directory. The CLI contract remains in
[PROTOCOL.md](../docs/PROTOCOL.md).

Current boundaries: Claude Code is the only real executor; `run` is foreground; gates stay
closed by default; the runtime does not wake a supervisor. `SUCCEEDED` approves the isolated
candidate, without updating the user's source branch. Resume existing tasks from their
task id and state directory; session migration does not authorize another model invocation.

For developing Harness Bridge itself, follow the repository's `AGENTS.md` instead of
automatically delegating work through this runtime workflow.
