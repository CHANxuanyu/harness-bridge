# ZCode Executor — P8 offline slice

_2026-10-07. This is an offline protocol implementation, not a qualified native Executor._

The [primary route](ROUTING_PROFILE.md) uses the existing Codex Astra conversation as Advisor,
Claude Code Opus 5.5 for difficult tasks, and ZCode GLM 5.3 Flash for bounded simple tasks.
This slice adds `executor.kind = "zcode"` to standalone tasks and goal child plans, with managed
worktrees, background jobs, exact-session repair, existing verification/review and goal budgets.
Only an explicitly supplied **simulated protocol executable** may run. Foreground and background
`--mode live` refuse before reserving an attempt, even with local opt-in and `--allow-model-usage`.

## Frozen task settings

The new executor object is separate from Claude/Codex options:

```json
{
  "kind": "zcode",
  "requested_model": "GLM-5.3-Flash",
  "provider_id": "account:zai-individual-coding-plan",
  "permission_mode": "edit",
  "allowed_tools": ["Read", "Edit", "Write", "Glob", "Grep"],
  "resume_on_repair": true
}
```

`provider_id` is required: the accepted account-provider names are Z.ai/BigModel
individual/team Coding Plan **or Start Plan** providers (`account:zai-start-plan` and
`account:bigmodel-start-plan`). These are distinct choices; no automatic fallback. Choosing a string does **not** prove account entitlement,
subscription charging, or model availability. No account is selected or changed in native ZCode.
Only the exact Flash model is admitted; non-Flash, FlashX, generic/custom providers, yolo,
shell tools and foreign harness options are rejected. Permission mode may be `edit` or `plan`;
the native enforcement of these options is still unqualified.

Task limits must explicitly set `max_turns_per_attempt: null`. Attempts, repair count, wall timeout
and cancellation still apply. A numeric goal turn ceiling refuses an uncapped ZCode child before
attempt reservation. No internal turn ceiling, measured model usage or cost is inferred.
Existing frozen Claude/Codex/fake tasks keep their normalized representation and behavior;
there is no state migration or change to the installed alpha.6 plugin in this slice.

## Protocol boundary

The runner launches a small bidirectional stdio client. Its stand-in child stays in the runner's
owned process group. The task prompt and frozen settings are passed over stdin, not command-line
arguments. Outer runner deadlines, cancellation and descendant/exit checks remain authoritative.
These are process observations, not OS sandboxing or proof of native tool containment.

Installed ZCode 0.16.9 schema symbols inform this narrow sequence:

1. Request `runtime/capabilities`.
2. Create a session with exact workspace/model and explicit controls, or resume the frozen
   `sess_UUID`. Resuming does not overwrite persisted model/mode.
   Handle exactly one `session/requestRuntimePreferences` callback for initialization only,
   disabling memory, search enhancements and automatic input resolution. Bind its session ID
   to the resumed ID or following created snapshot; all other server requests remain refused.
3. Validate the returned snapshot, then read it again. Session ID, workspace path/key, provider,
   exact model, permission mode, idle state and absence of pending/active work must match.
4. Send the task with exact model selection, attempt input/query ID and expected state revision.
5. Require accepted reply, one matching `prompt_started`, then a later `prompt_completed` for
   the bound session/workspace. The started event may precede the send acknowledgement.
6. Re-read and verify final identity/idle state/revision. Close stdin, drain to EOF, reject extra
   events and require child exit zero before emitting completion to the Bridge.

The installed implementation's `session/close` deletes session history; this client never calls
it. It also does not call `session/setModel`, edit global settings, import history, or create a
replacement conversation to make a desktop item appear.

Only compact normalized session/start/completion/error events reach Bridge receipts. Raw native
snapshots, prior messages, reasoning and error prose are not forwarded. Input, line, total-output
and queue sizes are bounded. Invalid JSON/shapes, unrelated responses or events, duplicate or
missing lifecycle events, model/identity changes and server permission requests fail closed.
Permission requests are never automatically granted. A passing file verifier cannot approve
a failed protocol attempt. Unknown process exit never becomes successful completion.

## Evidence and remaining native qualification

The [model-free probe receipt](ZCODE_PROTOCOL_PROBE.json) confirms only newline request/reply
framing and `runtime/capabilities` on the installed application. It used an isolated HOME/data
directory and explicit built-in config, did not create a session or send a prompt, and ended
with exit zero and empty stderr. Earlier missing-config and Unix-socket-path failures are retained.
The initial capability probe did not test session methods. Subsequent
[native preflight findings](ZCODE_NATIVE_PREFLIGHT.md) add isolated create/read/zero-usage evidence,
a requested-plan/observed-build mismatch and failed empty-session resume. They do not qualify
model dispatch, effective permissions or histories after real work. The offline profile is now
revision2; use the doctor capability revision, not only the unchanged runtime version string.

The [fixture provenance](../tests/fixtures/zcode_protocol/PROVENANCE.json) identifies the separate
synthetic peer used for all adapter/integration checks. It exercises real Bridge state, Git
worktrees, managed processes, external checks and review with simulated protocol behavior.
See the [validation matrix](VALIDATION_MATRIX.md) for exact results and limitations.

Before native dispatch can be enabled, P8 still needs:

- Account-specific model availability and subscription provenance without reading/storing secrets.
- Effective tool permissions, hooks, MCP and inherited configuration isolation.
- Native create/read/send event correlation, exact-model observation and same-session resume.
- Native bounded stop, confirmed descendants/exit, original history and desktop continuity.
- Native route acceptance and a concrete newly authorized bounded acceptance packet. Advisor
  templates are prepared in source plugin alpha.7; superseding an unapproved child remains open.

No new model calls are authorized by this slice. The old P7 allowance remains closed, and the P7
release candidate stays pinned to source `113b0a7`. Source development here does not replace that
candidate, release a new package or update host installations.
