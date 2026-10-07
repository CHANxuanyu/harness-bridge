# P7 closeout matrix — 2026-10-07

**P7 V01–V15 are accepted within the documented local scope.** The bounded native packet,
local distribution, original desktop-session visibility, full Codex GUI lifecycle and
post-restart original-history persistence are complete. No spent model allowance is reopened.
Current runtime **0.1.0.dev2**, plugin **0.1.0-alpha.6**, protocol 1.0, store revision 10,
Apache-2.0, local candidate only. Codex/ZCode are Advisor hosts; Claude Code/Codex are Executors.

The app update to 26.930.51102 was additionally qualified without a model call. Both recorded
app versions remain supported with embedded CLI 0.160.0; original-repository permissions and
final writeback are resolved.

## Acceptance against the project plan

“Passed” below applies to the stated evidence level and tested scope. Offline cases are real
local processes/Git/SQLite with simulated Executors, not new model runs. Historical results
are reused where code is unchanged. Detailed observations, including failures and permission
stops, remain in [P7_RESULT.md](P7_RESULT.md) and [VALIDATION_MATRIX.md](VALIDATION_MATRIX.md).

| ID | Current conclusion | Evidence and boundary |
| --- | --- | --- |
| V01 Advisor is an agent session | Passed in the existing Codex Advisor | This conversation inspected the repo, dispatched native children, reviewed exact diffs and delivered the approved integration. No model client in Bridge. Installed ZCode entrypoint is separately verified; no claim of a second native Advisor run. |
| V02 Correct directories/base | Passed, offline and native | Distinct owned child worktrees pinned to the same base; native returned bindings match task/cwd; original checkout/index/check scripts unchanged. |
| V03 Duplicate/stale operations | Passed, offline | Transaction/idempotency/Advisor-epoch regressions plus P7 simulated takeover and replay. Native delivery replay retained the same receipt/commit. No assertion of a live model race test. |
| V04 Concurrency/total budgets | Passed, offline and native | Last-slot/budget competitions and reservations tested offline; both native children observed RUNNING concurrently under the approved total envelope. |
| V05 Exact-session repair | Passed, native | P7 Codex repaired the original UUID/cwd and recalled the diagnostic mnemonic. Earlier [Claude repair](LIVE_REPAIR_RESULT.md) is reused. Wrong/missing IDs and budget resets are refused in adapter tests. |
| V06 Dependencies/isolation | Passed, offline; native isolation observed | Fixed approved dependency baselines and immutable snapshots covered by dependency/integration regressions. Native P7 children were independent roots, not a real model dependency chain. |
| V07 Failure/unknown exit | Passed within recorded process-observation limits | Original Codex cancellation **failed** and remains failed; correction, full regression and separately authorized native retest passed. Claude timeout and turn-stop observed. Unknown exits retain blocking. Sampling is not OS containment. |
| V08 Advisor close/takeover | Passed for actual Codex/ZCode GUI lifecycle with fake workers | Human-driven Codex full GUI quit/relaunch retained the same goal/job/worker/attempt; replay returned the same job, cancellation confirmed exit, then this Advisor reconnected with zero occupied slots. Prior ZCode GUI and Codex PTY evidence retained. [Detailed scope](P7_GUI_LIFECYCLE.md) excludes sleep/reboot/logout and backend termination. |
| V09 Evidence beats self-report | Passed, offline and native | Failed checks cannot be approved; changed evidence invalidates approval. Native input and combined checks ran independently of executor assertions before exact review. |
| V10 Conflicts/integration repair | Passed, offline | Existing P4 conflict, failed combined check, repair-child provenance and delivery-blocking cases are retained in the full regression. Native P7 integrated two nonconflicting inputs; no claim of a native conflict repair. |
| V11 Exact local delivery | Passed, offline and native | Delivered `73f485d437bc5bcf1796f6bd141e0b3d1be0033f` to isolated fixture branch `bridge/p7-result`; exact approved tree/replay and unchanged source verified. No merge into the user's checkout or remote push. |
| V12 One Advisor/two harnesses | Passed, native | Existing Advisor coordinated Claude implementation plus Codex diagnosis/repair, inspected both results and approved integrated delivery. |
| V13 Installation/discovery/retention | Passed for measured host interfaces | Isolated native plugin install/upgrade/remove/reinstall and runtime retention passed. Actual alpha.6 caches match 16 files each; 36-command connection checks and fresh Codex native Skill discovery pass. After restart, alpha.5 is present in this Advisor's supplied Skill catalog; pre-restart hot refresh is not claimed. |
| V14 Usage/permissions | Passed within accepted harness-specific contract | Codex attempts/wall/cancel budgeting explicitly approved; numeric old tasks stay refused. Stop receipts and explicit continuations retained. No provider/billing changes. Claude max-turns 1 returned native count 2; only the stop path is proven. |
| V15 Desktop chat lists | Passed for finished original sessions, including Codex restart persistence | Claude PTY handoff followed by actual page/sidebar/history/worktree inspection passed. Codex original page/sidebar visibility was explicitly confirmed by the human; the guarded official existing-thread URL and receipt replay succeeded. The human also confirmed original list/history persistence after restart. Native list API omission remains a separate observation. |

The final native ledger is **8 executions (Claude 4 / Codex 4), 1 repair, 975 reserved wall
seconds**; observed native duration 145.629s is not billed usage. One additional reservation
is proven not to have started. All gates are closed. Nothing in this matrix grants a retry.

## Final desktop/lifecycle closure

| Item | Completion evidence |
| --- | --- |
| Claude desktop | Corrected PTY handoff; same UUID/worktree, prompt/read/edit/denied-command/final history, one sidebar item and receipt replay verified. Original failure retained. |
| Codex desktop | Official existing-thread URL preserves the UUID; page/sidebar confirmed by the human before restart, original list/history confirmed again after restart. No prompt/fork/new-chat request. |
| Codex full GUI lifecycle | Actual main GUI absence/replacement observed; one existing fake attempt survived, dispatch replay did not duplicate it, cancellation confirmed exit and source preservation. This Advisor reconnected and confirmed zero occupied slots. |

No planned P7 acceptance item remains open in this measured scope. This does not certify
arbitrary versions/hosts, backend termination, sleep, OS restart or live-session interactive takeover.

Keep the delivered fixture state, original worktrees and native histories intact as retained acceptance
evidence. Do not clean them without a separate retention decision. The installed
Advisor follow-up already preserves the user's desktop request and reports unavailable paths.
See [DESKTOP_SESSIONS.md](DESKTOP_SESSIONS.md) for command/ownership guards. Running-session
display and interactive takeover are not implemented by the finished-session handoff.

## Local distribution closure

The builder now creates the complete candidate directly from a clean committed checkout:
runtime wheel, explicit plugin inventory, source archive, complete tracked docs, standalone
verifier and transport ZIP. It refuses output collisions and source changes during building.
The verifier checks checksums and source/wheel/plugin/document agreement without installation
or native execution. See [LOCAL_RELEASE.md](LOCAL_RELEASE.md) for installation, verification,
upgrade/removal retention, supported versions and reconstruction limits.

This closes the earlier packaging gap where the source archive and transport ZIP were added
by a temporary chat script and copied acceptance notes had missing relative document links.
The README reflects the completed bounded checks and current dev2/alpha.6 versions. The
packaging operation itself does not change runtime state or grant native execution allowance.

## Evidence locator

Raw local records are intentionally outside the public repository, under the takeover chat's
`work/` directory. They are retained and are not part of the release archive:

- `p7-live-20261007/final-bounded-acceptance.json` — final ledger and closed gates.
- `p7-live-20261007/dual-recovered/delivery-result.json` — exact native integration/delivery.
- `p7-live-20261007/codex-cancel-retest/result.json` and `claude-turn-limit/result.json`
  under the same packet root — fresh authorized fault evidence, separate from the old failure.
- `p7-host-lifecycle/` and `p6-desktop/` — measured ZCode GUI and Codex PTY behavior.
- `p7-codex-gui-lifecycle/` — Codex GUI absence/relaunch, same-job replay, confirmed cleanup,
  Advisor reconnection and explicit human post-restart history confirmation.
- `p7-distribution/` — independent runtime retention and candidate consistency receipts.
- `p7-plugin-alpha6/` — current native cache, connection and fresh Skill discovery checks.
- `p7-finalization/app-update-compatible-confirmed.json` — same original-thread URL opens
  successfully on app 26.930.51102 with approved system execution; earlier restricted failures retained.
- `p7-desktop-unlocked/result.json` — native handoff receipts and observed desktop evidence.
- `p7-codex-list-probe.json` — read-only exec/default-list diagnostic, no thread/turn creation.

Evidence files contain local paths and may include native output. Do not publish the private
records automatically; the reviewed summaries above are the public-facing evidence.
