# Local live dispatch readiness

This reference does not grant permission for a real call. Reuse explicit task authorization
already present in the conversation; do not ask again for attempts it covers. Record the
authorized target, executor, attempt/repair/turn/time bounds before dispatch.

1. Resolve the installed Claude executable. Use non-inference version/help/auth status to
   establish the selected binary and login method; record only non-sensitive status, never
   credentials/account identifiers. Login, if missing, is a user action.
2. Inspect the runtime's non-inference `doctor` receipt for gate blockers. Report environment
   variable names only. Never unset provider, cloud or nested-session markers to pass.
   In particular, launching this Claude executor from a nested Claude Code session is blocked.
3. Review applicable user/project/managed hooks, MCP and tool permissions. Keep strict MCP
   configuration and scoped tools; never `--bare`, `--dangerously-skip-permissions` or
   unrestricted Bash. Do not turn on extra usage or auto top-up; unknown billing settings
   remain unknown, not a promise of zero charges.
4. Require per-flag evidence for the installed binary. Help absence means unknown, not
   unsupported. Official docs alone cannot unlock an unlisted flag. Historical acceptance
   evidence must match the binary/version and explicit local confirmation; otherwise stop
   for a separately authorized probe. Never remove a rejected limit flag and retry.
5. Use a dedicated state directory outside the repo. In `STATE/config.toml`, prepare
   `[live] enabled = false`, `hooks_and_permissions_reviewed = true` only after the review,
   optional absolute `claude_binary`, and an exact `allow_unlisted_flags` list only for locally
   confirmed flags (default empty). This reference supplies no pre-approved flag list.
6. Prepare the clean pinned task, frozen external acceptance check and agreed limits.
   Run non-inference `doctor` with this explicit state directory; do not interpret unknown
   live capability as validation. Enable only this isolated live gate for the authorized
   attempt, and invoke `run --mode live --allow-model-usage` once.
7. With background dispatch, save the job handle and keep the authorized isolated gate open
   while the worker claims/rechecks it. Close it after confirmed completion or proven non-start,
   including errors; returning the launch receipt alone is not completion. Inspect job/task state
   on uncertain outcomes before another run. A covered repair may reopen it after review; a
   used-up budget cannot. Do not change the global default gate.

Permission/auth/quota errors stop dispatch. Inspect and report the actual cause; no automatic
quota waits, provider switching, limit weakening, or new model calls just to refresh a chat.

Codex additionally requires an explicit requested model and `limits.max_turns_per_attempt: null`
in a new task. The user must accept that the adapter cannot limit/count internal model turns;
attempt ceilings, mandatory wall deadlines and cancellation still apply. A parent goal with a
numeric total turn ceiling refuses such a child. Old numeric-turn tasks remain live-refused.
The current native preflight supports CLI 0.160.0, requires ChatGPT login and the default OpenAI
provider/endpoint, and validates effective per-invocation model and sandbox/approval controls.
External hook files/custom routing are refused. Plugins, auxiliary agents, MCP, web search and
notification commands are disabled for that execution; saved user configuration is not changed.
No credentials, account identifiers or raw config are retained. Requested model configuration is
evidence of the pin, not independently observed model identity or a guarantee of remaining quota.
ZCode execution is unimplemented. Installing an Advisor plugin does not authorize a live call.
