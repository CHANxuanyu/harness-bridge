# ZCode native preflight findings

_2026-10-07; installed ZCode 0.16.9. Native live dispatch remains unavailable._

This extends the earlier capability-only probe. The unchanged installed bundle SHA256 is
`fad4c35c4c36ec210d8a06d3fa0e77de23c8545e2eb6ff90aea1eb38d1e6275f`.
No prompt, model-connectivity test or model generation endpoint was invoked. Private scripts,
receipts and UI observations are in the takeover chat's `work/p8-native-contract/`.

## Native observations and implementation consequences

| Evidence | Finding | Consequence |
|---|---|---|
| Account/model settings UI, read-only | Flash can be offered through Start Plan separately from individual/team Coding Plan | Add explicit Z.ai/BigModel Start Plan provider IDs; do not infer worker authentication or billing from UI |
| MCP settings UI, read-only | Host/plugin MCP entries exist even with an empty manually installed list | Empty user list is not proof that MCP is disabled |
| Installed protocol implementation | Empty `mcpServers` supplies no runtime override; runtime MCP construction also merges plugin/official servers | Do not treat an empty request array as effective MCP isolation |
| Installed protocol implementation | Dynamic-workflow/off-peak booleans combine with host preferences; runtime-preference compatibility fallback enables automatic input resolution | Request fields alone are insufficient; effective configuration remains a live prerequisite |
| Isolated native session/create | Server requests `session/requestRuntimePreferences` with `scope: runtime-materialization` before returning the snapshot | Client now handles exactly one bound initialization callback with search enhancements, memory and automatic input resolution disabled |
| Same native create/read | Requested `plan`; returned mode and permission mode `build`, current model null, available models0, idle/no pending work | Preserve the mismatch; do not send a task or silently accept build mode |
| Native session/usage | modelRequestCount0, modelErrorCount0, totalTokens0 | No model inference occurred in the blank-session probe |
| Reopened isolated server + same session/resume | Native error -32004 (`sessionUnavailable`) before any callback/snapshot | Empty-session persistence/resume is not qualified; do not generalize this to histories after real work |

The blank session used a new isolated HOME/config/data/workspace, no real credentials, explicit
built-in provider config and a missing isolated personal provider file. It requested immediate
persistence, disabled title generation, allowed only Read and sent no task. Creation/read/usage
finished with process exit0 and empty stderr. The separate resume failure was then terminated by
the bounded probe (exit143, empty stderr); it was not clean native completion. Both records remain.
No vendor history was edited/deleted. The UI was returned to the original workspace without
changing settings or sending a chat message. Public evidence omits account identifiers, quota,
expiry, private conversation contents and local paths.
The mode mismatch is an adapter-qualification finding, not a claim of a vendor defect. The
reported independent-plan-state capability may use a different representation; do not equate it
with verified tool restrictions or adjust the guard without further evidence.

The [selected native fields](../tests/fixtures/zcode_protocol/native_blank_projection.json) are
redacted and narrower than a raw snapshot. Tests confirm that no-model and permission mismatch
states remain refused. A second test injects a synthetic exact model into those fields to isolate
the permission check; it is explicitly not captured native model evidence.

## Current client boundary

The offline client requires a canonical callback session ID, initialization scope, one callback,
matching resumed ID or matching subsequent created ID. It returns only bounded preferences;
it does not answer tool approval, user-execution preferences, auth/header requests or arbitrary
server calls. Duplicate/wrong-scope/wrong-ID callbacks and missing initialization fail before
`session/send`. This proves the simulated transport behavior, not native effective permissions.

`doctor --offline` now advertises `protocol_profile_revision: 2` for ZCode. The revision distinguishes
Start Plan/initialization support from older source sharing runtime version0.1.0.dev2. Advisor
templates require that capability; a version string alone is not enough.

Remaining native work: a supported way to use the existing authenticated account while isolating
configuration, effective permissions/tool/plugin/hook verification, exact model/send event
correlation, real same-session repair/stop and desktop history. The P7 allowance is closed.
Prepare a concrete bounded packet before requesting any new model usage. Do not enable live
on the strength of these blank-session or UI observations.
