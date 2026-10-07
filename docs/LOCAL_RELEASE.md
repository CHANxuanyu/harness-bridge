# Local candidate: installation and retention

Runtime **0.1.0.dev1**, Advisor plugin **0.1.0-alpha.3**, protocol 1.0, store revision 10.
Apache-2.0; see LICENSE and NOTICE. The user authorized a local candidate only on 2026-10-07.
No package index upload, public marketplace listing, Git tag, release or push is included.
Read the accompanying `ACCEPTANCE.md` for measured capabilities and remaining limitations.
P7 is not fully accepted: native cancellation revalidation and Claude turn-cap testing remain open.

## Product form

Use an existing Codex or ZCode conversation as the Advisor. Install the thin Advisor plugin
in each desired host and connect both to one separately installed local runtime/state directory.
The Advisor reads the project, plans bounded work and reviews results. Bridge creates isolated
worktrees, starts the selected Executor in the right folder, records evidence, accepts feedback
and delivers an approved integrated result to a new local Git branch. The source checkout is
not automatically merged. The plugin contains no model client or permanent model service.

## Install the runtime

Python 3.11+ and Git are required. Choose persistent directories outside plugin caches and
source repositories. Example paths are placeholders, not defaults to overwrite:

```sh
uv venv /absolute/path/to/bridge-runtime
uv pip install --python /absolute/path/to/bridge-runtime/bin/python /absolute/path/to/harness_bridge-0.1.0.dev1-py3-none-any.whl
/absolute/path/to/bridge-runtime/bin/hbridge --version
```

Only Pydantic and its dependencies are installed at runtime. Initial installation can need the
ordinary package registry; it does not call a model. The local wheel does not bundle dependencies,
Python, Git, Claude Code or Codex. Existing native subscriptions/logins are used only after an
explicitly authorized live dispatch; never copy credentials into connection files.

## Install host entrypoints

Extract the marketplace ZIP to a persistent source folder. It includes both host catalogs.
Do not move it while the host uses it as a local marketplace.

Codex CLI 0.160.0:

```sh
codex plugin marketplace add /absolute/path/to/extracted-marketplace --json
codex plugin add harness-bridge@harness-bridge-local --json
codex plugin list --json
```

ZCode 0.16.9: add that same source folder in Plugins / Add marketplace and install Harness
Bridge. Its bundled CLI also supports `plugins marketplace add`, `plugins install`,
`plugins update`, `plugins list` and `plugins uninstall`. Resolve the CLI from the installed
application rather than assuming a globally installed executable. On the validated Mac it is
`node /Applications/ZCode.app/Contents/Resources/glm/zcode.cjs`.

Create an owner-readable connection file at `~/.config/harness-bridge/connection.json`:

```json
{
  "connection_version": 1,
  "runtime": "/absolute/path/to/bridge-runtime/bin/hbridge",
  "state_dir": "/absolute/path/to/persistent-bridge-state"
}
```

Use the same trusted connection in both hosts. The packaged `check_connection.py` checks
version and command compatibility using temporary state, without opening the selected task
store. An explicit connection path or `HBRIDGE_CONNECTION` can override the default.
Historical task locators take precedence; do not silently merge or move old databases.

Start with “Use Harness Bridge to inspect this project's existing goals and jobs.” Loading
or refreshing the Skill is not authorization to execute a model. A currently open conversation
may need its host's supported refresh/reopen flow before discovering an updated Skill.

## Where Executor conversations are recorded

Executors run through native CLI sessions in their assigned Bridge worktrees. Native transcript
storage may therefore be indexed under that child directory, not the source repository. Bridge
`status`/`artifacts` reports the task worktree and observed session ID without launching a model.
Claude's locally verified CLI supports `--resume <session-id>` to reopen a known conversation;
opening/resuming in a host and sending a new message are separate actions. This candidate does
not promise automatic appearance in any desktop conversation sidebar, and does not create a
model turn merely to make such an item appear.

## Upgrade, remove and restore

Stop or confirm exit of active jobs before replacing the runtime. Keep the state directory,
its artifact/worktree directories, and source repository Git objects/retained refs together.
Back up the complete idle state and repositories; copying SQLite alone is insufficient.

Install the new wheel into the same environment, update the extracted marketplace source,
then use Codex `plugin add` again or ZCode `plugins update`. Run the connection check and
read existing goal/task status; do not redispatch just to validate an upgrade.

Codex `plugin remove harness-bridge@harness-bridge-local --json` and ZCode
`plugins uninstall harness-bridge@harness-bridge-local --force --json` remove the entrypoint
from the chosen profile. ZCode requires the explicit confirmation flag in a noninteractive
shell. Uninstalling the entrypoint or runtime preserves the separate connection/state data.
Reinstalling and using the same connection restores access to the same records. Removing a
marketplace is a separate optional host operation; neither operation deletes task evidence.

Native isolated-profile acceptance verified alpha.1 → alpha.3 upgrade, uninstall and reinstall
in both hosts. A clean runtime verified dev0 → dev1 upgrade, uninstall and reinstall while
preserving one completed fake task, its goal, single attempt and retained approval.

## Supported evidence and limits

| Surface | Validated boundary |
| --- | --- |
| macOS, Python 3.11, Git | Local core and process ownership/cancellation; recorded offline suite |
| Codex CLI 0.160.0 Advisor plugin | Native install/upgrade/remove/reinstall and Skill catalog; tool PTY reconnect |
| ZCode 0.16.9 Advisor plugin | Native install/upgrade/remove/reinstall; Skill UI and actual full app quit/relaunch with a fake worker |
| Claude Code CLI 2.1.291 Executor | Prior real initial/repair evidence; P7 native limits/results in ACCEPTANCE.md |
| Codex CLI 0.160.0 Executor | New tasks can explicitly choose attempts/wall/cancel budget; native metadata preflight checked; P7 real evidence in ACCEPTANCE.md |
| ZCode Executor | Not implemented |
| Linux | Earlier offline core evidence; current native host distribution/live acceptance not certified |
| Windows, logout, sleep/reboot, remote hosts | Not certified |

Codex internal model-turn hard limits are unsupported in this supported route; its reported
`turn.completed` is not a count of internal model calls. Numeric-turn frozen tasks remain live
refused. Actual model identity, subscription balance and actual charges remain unknown unless
an authoritative native receipt establishes them. This candidate makes no cost/quality claim.

## Rebuild locally

From the checkout with the build backend cached, run:

```sh
python3 scripts/build_release.py --out /absolute/path/to/new-candidate-directory
```

The fresh-only builder creates a wheel, an explicitly inventoried marketplace ZIP, installation
and acceptance notes, license/notice and SHA-256 manifest. It records source revision/dirty
state and never installs, publishes, dispatches a model, or upgrades acceptance status.
