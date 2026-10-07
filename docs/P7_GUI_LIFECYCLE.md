# P7 Codex GUI lifecycle acceptance — 2026-10-07

**Passed: actual main-GUI quit/relaunch, same fake job, idempotent reconnection, confirmed cleanup,
and human-observed original Executor history persistence.** No native Executor or model was called.

## Method and boundary

The human performed the quit/reopen after the computer-use tool had refused control of Codex
itself. No alternative UI automation, process kill or programmatic GUI restart was used.
A detached Python observer read exact app executable/PID/birth markers and Bridge records. It
could cancel only the owned fake fixture through Bridge. Its window was bounded to 840 seconds;
the fake task had one attempt, zero repairs and its own 900-second wall timeout. This fake budget
is separate from the spent native allowance; it added no live permission or attempt.

Fixture setup used a fresh isolated repo, goal, child worktree and state with live disabled.
One background fake `hang` execution reached RUNNING before the host quit. The observer required
an actual sample with no main GUI process, followed by a distinct new process identity, and
reopened Bridge through fresh database connections. It never considered a changed PID alone a pass.

## Recorded sequence (UTC)

| Observation | Result |
| --- | --- |
| 13:00:37.883 fixture ready | One fake attempt RUNNING; original main GUI PID 88573, original worker PID 54508 |
| 13:02:39.231 GUI absent | No main GUI process; same goal/job/attempt and worker still RUNNING, one attempt |
| 13:02:40.372 GUI reopened | Main GUI PID 56002 with a new birth marker; same worker and attempt still RUNNING |
| Fresh-connection replay | Returned the original job with replayed=true; no new attempt |
| 13:02:40.702 cleanup complete | Task CANCELLED, worker no longer alive, executor exit confirmed, one attempt, source unchanged |
| Advisor after restart | Reconnected to the same goal/job; zero occupied slots and confirmed terminal task |
| Fixture goal closure | CANCELLED after completed observation; records/worktree retained |
| Original Codex Executor history | Human explicitly confirmed “仍在列表，原历史也能打开” after reopening |

The original Executor UUID is `01a11375-1bfc-7ba3-a351-8d206887423c`, titled
**Harness Bridge · P7 Codex Executor · 已交付**. Its visibility evidence is human observation,
not an invented screenshot or inference from the native list API. No new conversation was created.
Installed alpha.5 also appears in the resumed Advisor's supplied Skill catalog.

## Retained evidence and limits

Private receipts are in the takeover chat's `work/p7-codex-gui-lifecycle/`: `ready.json`,
`result.json`, `advisor-reconnected.json`, `fixture-closed.json`, and
`desktop-persistence-human.json`. The bounded observer source is retained next to that directory.
Do not rerun the launcher against that existing root. No broad/core tests were repeated because
this final observation changed no runtime code. The previous affected checks and full regression
remain separately labeled in [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md).

The boundary is the tested macOS Codex main GUI lifecycle with a fake worker. The running
app before quit was 26.930.31730; after restart the installed app was 26.930.51102 (build 13100),
with the same CLI 0.160.0. The original history survived that update.
It is not evidence of backend-process termination, logout, sleep, OS reboot, arbitrary host
versions or live-model survival across every failure. Existing stale-Advisor and takeover
semantics are covered separately by offline integration tests. The native packet remains
8 executions / 1 repair / 975 reserved seconds with all gates closed.
