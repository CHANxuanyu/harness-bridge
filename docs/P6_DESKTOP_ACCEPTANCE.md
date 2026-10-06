# P6 installed entrypoints and shared connection acceptance

Continuation of [the alpha.2 package slice](P6_ENTRYPOINT_RESULT.md), baseline `ebac4a7`.
Runtime, plugin alpha.2 source, protocol 1.0 and store revision 10 are unchanged.

## Result and evidence boundary

**P6 model-free installation/connection acceptance passes.** Both installed packages resolve the
same default connection; the native Codex skill loader and actual ZCode settings discover the
enabled Advisor Skill. The existing package/CLI workflow evidence covers goal takeover and
review/repair/delivery. A new real Codex tool PTY exit check below adds bounded reconnection evidence.

This is not full V1 or real cross-harness acceptance. No new Advisor conversation, agent message,
Executor model call, subscription probe or live-gate opt-in was made. In particular, a fresh
native skills-catalog response does not prove that an already-running desktop window hot-reloaded
its in-memory catalog. GUI app quit/logout/reboot and real Executor behavior remain P7 acceptance.

## Actual Codex profile

The bundled CLI's native plugin commands registered the local checkout and installed alpha.2 in
the user's actual Codex profile. `plugin list --json` reports installed/enabled; all 34 preexisting
plugin records remain unchanged. The installed cache's 13 package files hash equal to source.
ZCode's existing installed alpha.2 cache also has the same 13 files; no upgrade/reinstall was needed.

The computer-use tool refused access to the Codex app for safety reasons. No alternative GUI
automation, app restart or security workaround was attempted. The supported control-daemon version
query found no control socket; no daemon was installed/started and no remote control was enabled.

Instead, the bundled CLI generated its local JSON protocol schemas. A short-lived native app-server
stdio process using the actual profile received only `initialize`, the `initialized` notification,
and `skills/list`. No thread/turn creation method was sent. It was shut down after the response.
For both the repository and the current chat working directory, the loader reports:

- skill: `harness-bridge:harness-bridge`
- plugin: `harness-bridge@harness-bridge-local`
- enabled: `true`
- source: the actual user's alpha.2 plugin cache
- Harness Bridge parsing errors: none

This is native loader evidence in the actual profile, not a screenshot or an assertion about the
currently running desktop process. Earlier ZCode UI evidence shows installed alpha.2 and the Skill
detail's enabled status; see the prior slice.

## Shared first-use setup

After confirming that neither the default connection nor the proposed new shared state existed,
created `~/.config/harness-bridge/connection.json` exclusively (no overwrite), mode 0600. It records
the trusted source checkout's `.venv/bin/hbridge` and a dedicated state directory under the user's
Documents/Codex workspace. It contains only connection version and these two paths.

Both **actual installed caches** ran `check_connection.py` with no path arguments and resolved this
same default. Each passed all 34 help surfaces and offline protocol diagnostics. Neither probe
created the selected state. A subsequent explicit normal `projects` read initialized this new store;
it contains zero projects, and offline diagnostics confirm `live_enabled: false`. Historical smoke/
repair databases were neither opened nor migrated. The default connection does not silently import
those records; their explicit locators still take precedence for continuation.

This enables the first-use flow without asking the human to shuttle paths between Advisor hosts.
It does not select an Executor, create a goal, or authorize a model call on installation.

## Actual Codex tool PTY exit and reconnection

This was a new manual offline acceptance check, not another run of the previous test suites.
An isolated fixture repository, external checker and state were created in the takeover chat's
`work/p6-desktop/lifecycle/`, separate from the new empty everyday state. The fake `hang` executor
had a 120-second wall ceiling, one attempt and zero repair allowance.

1. A command in the actual Codex tool PTY created one task, dispatched one background mock job,
   observed `RUNNING`/`claimed`, and exited successfully. The tool reported exit code 0.
2. A fresh command observed that the launcher process no longer existed. The installed Codex and
   ZCode connection checkers both resolved the fixture's explicit connection to the same state.
3. Reading the saved job showed it was still `RUNNING`/`claimed`; task events were readable by cursor.
4. Runtime cancellation returned the job to `finished`, task `CANCELLED`, with
   `executor_exit_confirmed: true`. Exactly one attempt remained and the source fingerprint matched.

The check proves survival of this actual tool PTY's normal exit and reconnection through installed
connection resources. It is not GUI application termination, a machine restart, or execution from
a ZCode agent/terminal. Cancellation used the recorded task; no guessed-PID termination was used.
The fixture is stopped, with evidence retained outside the source repository.

## Validation and remaining work

No runtime/package source changed. The prior 24 affected package/CLI checks (19.96s), Skill validator
and P5/P4 regression evidence remain applicable; they were not rerun solely for this session.
This round adds actual-profile install/native-loader checks, default connection checks in both
caches, and one native tool PTY lifecycle check. No new all-suite pass count is claimed.

P7 still needs bounded real Advisor/Executor behavior, two real executor harnesses, lifecycle/error
acceptance and distribution decisions. Codex live remains unavailable due to the recorded capability
gaps. The exhausted repair allowance is not renewed. GUI hot refresh is unobserved, and full app
termination is untested. No push, PR, visibility change, API credentials or billing change occurred.

Redacted summaries are committed here; local plugin receipts, native catalog response, connection
results and lifecycle records remain in the takeover chat's `work/p6-desktop/`.
