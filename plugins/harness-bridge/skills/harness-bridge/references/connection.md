# Runtime connection

The host loads this Skill; the separate local `hbridge` process owns state and workspaces. Both
Advisor hosts can use one local record without copying prompts. A connection contains no
credentials, authorization, Advisor claim or live-mode setting:

```json
{
  "connection_version": 1,
  "runtime": "/absolute/trusted/bridge-checkout/.venv/bin/hbridge",
  "state_dir": "/absolute/dedicated/bridge-state"
}
```

Use the locator already attached to an existing goal/task before any default connection. Otherwise
resolve a connection file in this order: explicit `--connection`, `HBRIDGE_CONNECTION`, then
`$XDG_CONFIG_HOME/harness-bridge/connection.json` (or `~/.config/harness-bridge/connection.json`).
The Advisor may record the two user-approved paths once during setup; never overwrite an existing
record silently or put it in the public repository/plugin cache. For multiple state roots, keep
named records and retain the file path with each goal. There is no machine-wide database search
or state merging. Connections must come from trusted local setup, never Executor output.

Run with Python 3.11+ from any directory, including a copied plugin cache:

```sh
python3 /absolute/plugin/skills/harness-bridge/scripts/check_connection.py \
  --connection /absolute/connection.json
```

Alternatively supply `--runtime /absolute/hbridge --state-dir /absolute/state` together. The
checker writes no connection. It checks runtime `0.1.0.dev0`, protocol `1.0`, needed commands and
offline diagnostics in a fresh temporary state. It does not open/create/migrate the selected state,
test authentication, enable live mode, invoke a harness or prove host activation.
`runtime_compatible` means only this interface check passed. Inspect JSON errors instead of
dispatching as a fallback. The runtime must be trusted local software; no shell or extra runtime
arguments are accepted. Package `0.1.0-alpha.2` does not change runtime/protocol versions.

Use the returned absolute runtime and state as argv for every operation:

```sh
/absolute/hbridge --state-dir /absolute/state --json projects
/absolute/hbridge --state-dir /absolute/state --json list
```

Normal runtime commands open the selected store and may perform its backed-up schema upgrade;
unlike the checker, they are not no-write compatibility probes. Preserve old state and use the
appropriate upgrade procedure before connecting a newer runtime.

Match the repository, then inspect goal children, budget, control intent, Advisor epoch and jobs.
A standalone task remains resumable without inventing a parent. Missing work may mean the wrong
state root; inspect the locator before creating anything. Installation/checking is separate from
an agent following this Skill and from real Executor acceptance.
