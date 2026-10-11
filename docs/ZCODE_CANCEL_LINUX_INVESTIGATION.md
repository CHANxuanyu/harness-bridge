# Linux ZCode cancel failure — scoped investigation

2026-10-11. Scope: one test only,
`tests/integration/test_zcode_stub_flow.py::test_cancel_stops_both_transport_and_peer`.
Offline/synthetic, cloud Linux container, stub peer only (no real CLI, model or network).
This is not native/real-session acceptance and does not change any recorded suite result.

**Result: cause confirmed for this container.** At the failing assertion, the peer is a
**zombie awaiting reaping**: it has been reparented to the container's PID 1 (`process_api`),
which reaps orphans with a measured delay of about 1–2 s rather than immediately. It is not a live
leaked process and not PID reuse. The product's cancel did stop the whole group. The assertion,
test, gate markers and product code are unchanged, and the test still fails here.

## Inputs and conditions

| | |
|---|---|
| Exact input | `394b6e36a31833496dafdd37e3f2337e5dab7782` (tip of `codex/engineering-foundation-reverification`); tested code `560056f11858f9f02b01ee3966ba2aaf41d41c54` is its parent, differing only in docs |
| Checkout | new detached worktree at the exact SHA, `git status` clean, own venv via `uv sync --frozen` |
| Import path | `<worktree>/src/harness_bridge/__init__.py` (printed by the run; session prefix redacted in evidence) |
| Host | Linux 6.18.44 kernel, Python 3.11.17; PID 1 `comm` = `process_api` (state S, PPID 0) |
| Invoking markers | `CLAUDE_CODE_REMOTE`, `CLAUDE_CODE_REMOTE_SESSION_ID`, `CLAUDECODE` **set** (`CODEX_CLOUD` unset); **none removed** for these runs |
| Inside the test | all four absent: removed by the pre-existing autouse fixture `tests/conftest.py::isolated_env` (scrubs `CLAUDE*`/`CODEX*`/… prefixes), not by this investigation |
| Doubles / cleanup | stub peer `tests/helpers/zc_peer.py` via the `zc-stand-in` wrapper, `HBRIDGE_ZC_MODE=sleep`; the sentinel fixture (no real `claude`/`codex`/`zcode`) passed teardown in every run |

Runs: `pytest -p zc_observe -p no:cacheprovider -q --basetemp=<run dir> <test id>`. **Three
observed reproductions, all failed with the original `Failed: DID NOT RAISE ProcessLookupError`**
(pytest exit 1; 6.66 s, 5.81 s, 6.00 s). No full suite or baseline was re-run.

## Observation method

`qa/zcode_cancel/zc_observe.py` is a pytest plugin loaded with `-p`; it changes no test, fixture
or product code path. It samples every 10 ms, only for this test:

* processes the test creates: descendants of the pytest process, found through
  `/proc/<pid>/task/<tid>/children`, plus the peer PID the test itself reads from `rpc.jsonl`;
* after reparenting, the process that becomes their parent (here PID 1): `pid`, `comm`, `state`,
  `ppid` only.

Per process it records `pid`, `ppid`, `pgid`, `sid`, `state`, kernel `comm` (15 characters) and
`starttime` (clock ticks since boot, the start identity). It never reads `cmdline`, `environ` or
any other process. Snapshots are taken before/after `Bridge.cancel` (a pure observer wrapper that
returns the original result unchanged and adds a few milliseconds), at the failed assertion
(`pytest_exception_interact`, before fixture teardown), after teardown and 5 s later. Each
snapshot also probes `os.kill(pid, 0)` and `os.killpg(pgid, 0)`; signal 0 sends nothing.

Executed SHA-256 (scratch copies):
`zc_observe.py` `6e244e924f766ab0d0e9ab33781bb512e68740d00b70fd86b4ca6b116c4a3c8c`,
`reaper_probe.py` `240b4f89dde3a963f87f97e7430f87d9d4cd7a87b5c9bc4fee4fb50c06980ebd`,
`analyze.py` `92c5dfb4…` (printer only; not used for the conclusions). The committed copies differ only by ruff formatting,
one nested `if` combined into a single condition (same logic) and a rewritten printer in
`analyze.py`.

## Process tree (identical in all runs)

pytest → worker (`python -m harness_bridge.worker`, new session) → transport
(`python -m harness_bridge.zcode_transport`, process-group leader via `start_new_session`) → peer
(`zc-stand-in` → `python zc_peer.py`; child of the transport, same group, the PID the test checks).

## Evidence (times in ms from the start of the test call)

| Run | pytest / worker / transport / peer | peer start identity | transport gone & peer → Z | parent while Z | at failed assertion | peer reaped | zombie lifetime |
|---|---|---|---|---|---|---|---|
| 1 | 399 / 414 / 416 / 417 | 25706 | 978.3 | 1 (`process_api`) | t=1161.3: Z, PPID 1, PGID 416, same start, `kill0` no exception, `killpg0(416)` no exception | 2568.8 | 1590.5 |
| 2 | 441 / 456 / 458 / 459 | 29386 | 550.2 | 1 (`process_api`) | t=740.7: Z, PPID 1, PGID 458, same start, same probes | 1635.4 | 1085.1 |
| 3 | 468 / 483 / 485 / 486 | 29999 | 764.5 | 1 (`process_api`) | t=930.1: Z, PPID 1, PGID 485, same start, same probes | 2467.4 | 1702.9 |

In every run:
* the peer was in state Z with PPID 1 both when `cancel` returned and at the failed assertion;
* the peer never re-entered R/S/D after cancel;
* the worker was reaped by pytest;
* 5 s after teardown, both `kill(peer, 0)` and `killpg(transport_pgid, 0)` raised
  `ProcessLookupError`;
* the start identity never changed (no reuse event).

Full per-run data: `qa/zcode_cancel/evidence/run{1,2,3}-observe.json` and `-pytest.log`.

### Container reaping behaviour (controlled probe, own processes only)

`qa/zcode_cancel/reaper_probe.py`: parent P forks C, C forks G and exits, P reaps C, and G exits
0.2 s later.
* **Orphan case:** G is reparented to PID 1, is in state Z with `kill(G, 0)` not raising, and is
  reaped by PID 1 after **1.47, 1.67, 1.72, 1.79, 1.85 and 1.91 s** (six runs).
* **Subreaper control** (`PR_SET_CHILD_SUBREAPER` on P): G is reparented to P and stays Z with
  `kill(G, 0)` not raising. Immediately after P's `waitpid`, the probe raises
  `ProcessLookupError`.

Evidence: `probe-orphan.json`, `probe-orphan-x5.jsonl`, `probe-subreaper.json`.

## Classification

| Candidate cause | Verdict | Basis |
|---|---|---|
| Zombie awaiting reaping | **Confirmed** | state Z, PPID 1, unchanged start identity at the assertion; disappears without any further signal once PID 1 reaps (1.09–1.70 s here; 1.47–1.91 s in the probe) |
| Live leaked process | Ruled out for these runs | the peer was never R/S/D after cancel; the group held no non-zombie member, so `group_alive` correctly returned False; the peer was gone within 2.6 s with no extra signal |
| PID reuse | Ruled out | `starttime` identical at every sample until the entry vanished |
| Insufficient evidence | No longer | three consistent observed runs plus the controlled probe |

Mechanism: the cancel signals the whole group. The transport (the peer's parent) exits without
having waited for the peer, so the exiting peer is orphaned. With no subreaper in the chain it is
reparented to PID 1. This container's PID 1 reaps orphans periodically, about 1–2 s later.
`group_alive(pgid)` first uses `killpg(pgid, 0)`, which succeeds while any member exists,
zombies included. It then scans `/proc` and returns True only for non-zombie members, so it is
False here. `os.kill(pid, 0)` succeeds for any entry still in the process table, zombies included,
so `ProcessLookupError` appears only after reaping. This source difference shows why a zombie
*could* explain the failure. The process snapshots above are what establish that it does in this
container.

On the maintainer's Mac the same test passes (independent macOS receipt), consistent with an init
that reaps orphans promptly. GitHub-hosted runners were not tested (NOT_RUN).

## Impact

* Product: none observed. Product liveness checks treat zombies as stopped: `runner.group_alive`,
  `runner` identity checks (`os.kill` followed by `_is_zombie`), and the workbench `group_members`
  and `alive_with_birth`. Cancellation stopped every group member. The zombie is cleaned up by the
  container's init.
* Tests: only this test asserts immediate `ProcessLookupError` for an orphaned grandchild.
  - `test_desktop.py::test_handoff_transport_bounds_output_and_stops_its_launcher` checks a direct
    child that its caller waits for.
  - `tests/unit/test_runner.py` already treats state Z as not alive.
* Recorded results stay as they are. Cloud Linux suite: 1041 passed / 7 failed / exit 1. The six
  desktop failures remain attributed to the Darwin capability gate. This test remains a failure in
  this container until the test owner or CI environment changes; it is not relabelled as passing.

## Follow-up suggestions (nothing implemented)

1. **CI environment**: for container-based Linux runs, use an init that reaps promptly
   (`docker run --init`, tini, dumb-init), or run on hosted VM runners whose PID 1 reaps
   immediately (expected, not verified here). Record this test as sensitive to init reaping
   latency in this cloud container.
2. **Test owner decision** (each changes the assertion; not done here):
   - (a) wait a bounded time (for example up to 5 s) for `ProcessLookupError`, keeping the check
     strict;
   - (b) accept "gone, or zombie with the same start identity" as stopped, matching the product's
     own liveness semantics.
3. **Optional product hardening** (only if deterministic reaping becomes a requirement): on Linux
   the worker could set `PR_SET_CHILD_SUBREAPER` and reap orphaned group members after cancel.
   This is Linux-only, changes process-tree ownership and is out of the current scope.

Status: **cause confirmed; Linux item remains a known test-environment failure** pending a CI or
test-owner decision. No product defect found, so there is no fix branch. Spend: unknown (no
reliable usage data).

## Reproduce

```sh
git checkout 394b6e36a31833496dafdd37e3f2337e5dab7782   # or this investigation branch
uv sync --frozen
ZC_OBS_OUT=/tmp/zc/observe.json PYTHONPATH=qa/zcode_cancel uv run --frozen pytest \
  -p zc_observe -p no:cacheprovider -q --basetemp=/tmp/zc/tmp \
  tests/integration/test_zcode_stub_flow.py::test_cancel_stops_both_transport_and_peer
uv run --frozen python qa/zcode_cancel/analyze.py /tmp/zc/observe.json
python3 -I qa/zcode_cancel/reaper_probe.py orphan      # container reaping latency
python3 -I qa/zcode_cancel/reaper_probe.py subreaper   # control
```
