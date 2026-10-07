# Decisions (short ADR log)

Each entry: decision — reason. Newest last.

1. **Use the user-created repo `CHANxuanyu/harness-bridge` directly** on the platform-assigned
   branch `claude/new-repo-plan-dn1eac` — it was empty and created for this task; the plan says to
   follow a platform-specified branch name over `claude/harness-bridge-mvp`.
2. **Python 3.11 floor, dev env pinned to 3.11** (`.python-version`) — the cloud host has 3.11,
   3.12, 3.13; developing on the floor version catches accidental use of newer stdlib APIs.
3. **hatchling build backend, uv lockfile, PEP 735 `dev` dependency group** — standard and
   reproducible with `uv sync --frozen`.
4. **pydantic 2 as the only runtime dependency** — schema validation with `extra="forbid"`;
   everything else is stdlib (sqlite3, subprocess, selectors, argparse, tomllib).
5. **Fake executor ships inside the package** (`adapters/fake_executor.py`, stdlib only, launched
   by absolute path with `python -I -B`) — `hbridge demo` must work from an installed package,
   not only from the test tree. It is coupled to the `normalize_tags` fixture by design.
6. **Settled attempts go to AWAITING_REVIEW, uncertain ones to INTERRUPTED** — when the owned
   process group's exit is confirmed, outcomes `succeeded/failed/protocol_error/crashed/
   timed_out` are verified and shown to the supervisor (who can request a repair); only
   `succeeded` can pass the approval gate. Unconfirmed exit → INTERRUPTED (no auto retry);
   structured permission/quota errors → BLOCKED.
7. **Snapshot = temporary index** (`read-tree <base>` + `add -A` + `write-tree`) — captures
   committed, staged, unstaged and untracked non-ignored content in one tree without touching
   any real index. Fingerprint = sha256 over {base SHA, tree SHA, task_version, verifier digest}.
8. **Forbidden globs match case-insensitively, allowed globs case-sensitively** — conservative in
   both directions on case-insensitive file systems (macOS default).
9. **Review idempotency** — accepted and gate-rejected submissions are stored under their key
   (same key + same content → same receipt; different content → conflict). Stale or
   wrong-state submissions are refused without being stored.
10. **Layout under the state dir**: `bridge.sqlite3`, `worktrees/<task_id>` (branch
    `hbridge/<task_id>`), `artifacts/<task_id>/<attempt_id>/`, `tmp/`, optional `config.toml`.
11. **Verifier environment** inherits the caller's environment minus model/GitHub credentials,
    plus `PYTHONDONTWRITEBYTECODE=1` (bytecode caches would otherwise change the snapshot).
12. **`task_version` stays 1 in V0.1** — there is no amend command yet; reviews still have to
    carry it so a future amend cannot be approved against old evidence.
13. **Executor stdout is kept head 1/16 + tail 3/16 of `max_artifact_bytes`** (stderr half of
    that); all lines are still parsed, so truncating the stored log never hides the final result.
14. **Claude adapter contract tests use a stub executable** (`tests/helpers/cc_stub.py`) through
    `run --mode mock --stub-binary` — exercises the real runner/store/verifier wiring without a
    model. The stub must not be named `claude*` nor resolve to the real binary.
15. ~~Live preflight compares used flags with `claude --help` only~~ — superseded by 19.
16. **Live dispatch additionally requires `[live] hooks_and_permissions_reviewed = true`** —
    the plan requires reviewing hooks/MCP/permissions before the first real run; this makes it
    an explicit, recorded opt-in.
17. **Provider errors detected only from text are BLOCKED with `classification: heuristic`** and
    `reset_at: null`; structured signals (`permission_denials`, `error_max_budget_usd`) are
    `classification: structured`. Nothing is retried automatically either way.
18. **Resume only for a session id observed in this task's previous attempt with a matching
    binding** (executor kind, task, repo identity, worktree); a resume the output does not
    confirm → BLOCKED `resume_failed` (never silently a new session). `--strict-mcp-config` is
    on by default to keep MCP servers out of executor runs.
19. **Flag capability = three separate evidence sources** (supersedes 15): official CLI reference
    (documents `--max-turns`; states `--help` does not list every flag), local `--help`, and the
    user's per-flag local confirmation (`[live] allow_unlisted_flags`, exact names only). Help
    absence → "unknown / pending local confirmation", never "unsupported"; docs alone never
    unlock a flag, so the existing hold stays. A run-time CLI rejection → `BLOCKED
    cli_rejected_argument`; the bridge never drops a limit flag and retries.
20. **Remote**: the user authorized making the repo private; the cloud session's GitHub tools
    have no visibility operation, so the repo stayed public and the branch was not pushed (no
    alternative credentials used). Delivery = self-contained git bundle (not version-controlled).
21. **T3 smoke fixture (qa/local, 2026-10-06)**: the first live smoke targets a disposable
    one-shot repo (`slugkit.slugify`) generated per run by `qa/local/make_fixture.py`, with the
    acceptance script stored *outside* the fixture and presets `max_attempts = 1`,
    `max_repair_cycles = 0`, `max_turns_per_attempt = 10`, `wall_timeout_seconds = 600`, and a
    scoped `Bash(python3 -B -m unittest:*)` matching the repo-tests argv — never a task against
    Harness Bridge itself.

22. **Controlled repair evidence (2026-10-06):** freeze a two-phase TaskSpec (diagnosis only, then
    review-directed repair) against a seeded defect; keep verifiers unchanged; prove matching
    session and conversation recall. Label this a controlled workflow, not a spontaneous failure.
23. **Doctor evidence scope:** report historical project validation separately from installed-host
    live readiness. A non-inference doctor never upgrades live readiness to supported based on
    past smoke success elsewhere; Linux/macOS process support cites offline validation.
24. **Product audience and form (2026-10-06):** user confirmed developers with multiple coding-agent
    subscriptions (ZCode/GLM, Claude Code, Codex); use an independent local runtime with host
    plugin entrypoints, not a permanent dependency on one supervisor brand. `docs/PRODUCT_FORM.md`.
25. **Thin plugin alpha:** one self-contained Skill, per-host manifests/catalogs, existing CLI;
    no new MCP/state machine/worker or model calls merely to package the workflow. Static
    compatibility, host discovery, installed activation and live execution are separate evidence.
26. **Review success is not delivery:** current `SUCCEEDED` approves an isolated candidate;
    explicit export/apply and delivery recording are required product work, not an implied merge.
27. **Advisor + Executors is the primary product relationship (user clarification):** one main
    agent inspects/plans/dispatches/reviews/integrates, with one or more cross-harness execution
    sessions. Bridge owns workspace preparation and execution context, not planning intelligence.
    `supervisor` maps to Advisor; parent/child/dependency/global-budget semantics are pending,
    not new fields in the existing strict TaskSpec. Plugin packaging is subordinate to this model.
28. **Unified plan (P0):** `docs/PROJECT_PLAN.md` is the product/engineering/acceptance baseline;
    Advisor and Executor are both agent sessions, and Bridge never creates a planning model.
    V1 targets bounded one-to-two execution, managed workers and integrated local-branch
    delivery. These are working implementation defaults, not newly completed capabilities.
29. **Dependency materialization and mutation guards:** hold a child coordination record until
    dependency snapshots are fixed, then create its immutable execution spec/worktree. All
    mutating entrypoints for goal-linked tasks must enforce active Advisor epoch and aggregate
    constraints; the old task CLI cannot be a bypass. Pending implementation in P1–P3.

30. **P1 first slice:** link ready independent tasks to goals without changing TaskSpec 1.0;
    defer unmaterialized child plans/DAGs and full goal control, explicitly retaining P1 in-progress.
31. **Advisor fencing:** binding ID + epoch checks occur before preparation and in each linked
    mutation transaction; accepted attempt observations may finish after takeover. Read/cancel
    remain available; bindings are cooperation metadata, not same-user authentication.
32. **Initial aggregate guard:** charge all reserved attempts except confirmed spawn failures;
    serialize goal-linked execution across one project's goals in one state root, retaining
    unknown-exit slots even after cancellation. Managed workers/time/turn accounting remain P3.
33. **Storage revision 2:** additive coordination tables; take a SQLite backup including WAL
    under the writer lock before migrating, commit schema/version atomically, refuse unknown
    revisions and preserve historical standalone tasks without inventing goal events.

34. **Immutable child plans (P1 completion):** separate TaskDefinition from repository/base,
    validate a same-goal DAG atomically and materialize only explicitly requested independent
    roots. Dependencies wait for preserved approved baselines; never substitute original HEAD.
35. **Goal controls:** pause only new reservations; cancel/fail permanently prevent new work
    and request owned-process cancellation. Terminal goal projections require all tasks terminal
    and all attempt exits confirmed. Emergency cancel does not require the active Advisor.
36. **Materialization recovery:** task creation, goal ownership and child association commit
    together under a stable key; preparation is recoverable without another task. A concurrent
    goal cancellation keeps the task cancelled and records any successfully prepared workspace.
37. **Schema revision 3:** chain additive migrations from v1/v2 in one transaction, with one
    WAL-aware pre-upgrade snapshot and owner-only backup creation; late failures roll back every
    migration stage. TaskSpec/ReviewDecision wire contracts and canonical digests stay 1.0.

38. **P2 retained approvals:** pin the verified tree as a deterministic unsigned commit and
    bind it to the accepted review in SQLite; Git/DB crash gaps may leave unclaimed refs,
    adopted only on an exact retry. Never read later parent worktree contents as dependency input.
39. **Fixed dependency composition:** merge retained commits in stable child-key order,
    preserving ancestry; pin the result before TaskSpec creation. Persist conflicts without a
    task/workspace. Missing refs or configured external merge drivers fail closed, no fallback.
40. **P2 presence preflight is a partial milestone:** explicit immutable file/directory/tool
    requirements and ownership checks run before planned-child reservation, consume no attempt
    on failure and execute no located tools. Controlled setup commands/resources remain pending.
41. **Schema revision 4 compatibility:** additive retained-record tables; preserve old child-plan
    canonical JSON by omitting absent environment configuration. Old approvals require explicit,
    unchanged-candidate retention; no state migration invents an approved snapshot.

42. **Explicit finite preparation (P2):** immutable child-plan argv/cwd/deadlines/outputs;
    `child prepare` is separately idempotent and bounded, never auto-run by dispatch/recovery.
    Preparation records and executor attempts remain separate; preparation does not spend model
    budgets and successful evidence must match the current candidate before every child run.
43. **Preparation stop proof:** PREPARING occupies the project slot; accepted observations may
    finish after takeover. Cancel is rechecked transactionally before completion. Crashes and
    unconfirmed exits retain reservations even after logical failure/cancellation; no auto retry.
44. **Resource claims:** explicit names are exclusive across all projects in one state root,
    retained through execution/review and reclaimed only for terminal confirmed-stopped owners.
    Declared output/cache metadata is an inventory, not a complete audit of ignored/external files;
    no persistent service management, automatic allocation or cross-state locks are promised.
45. **Preparation environment:** isolated HOME/XDG, small inherited env, redacted bounded logs,
    no credential copying; direct harness commands rejected. Reviewed scripts remain trusted code,
    so this is not an OS/billing sandbox. Existing live executor gates are unchanged.
46. **Schema revision 5:** additive preparation/claim tables with atomic backed-up migration;
    omit absent preparation from canonical old plans so existing replay digests stay stable.

47. **P3 single-attempt workers:** persist background key/attempt/packet together under existing
    guards, then spawn a detached local Python worker; claim once transactionally and reuse the
    foreground execution/evidence path. No automatic queue, scheduling or worker restart.
48. **Unclaimed versus claimed recovery:** atomically fencing a never-claimed reservation proves
    non-execution even with a delayed worker. After claim, unknown exits retain goal budget/slot;
    a recovered worker record never substitutes for process-exit evidence.
49. **Dispatch and observation:** background keys are required and replay the original attempt;
    task event cursors and bounded waits are read-only. Query timeout never restarts a worker.
    Accepted work survives Advisor takeover; fresh reservations still require the current epoch.
50. **Worker readiness/gates:** persist no environment values; reconstruct/digest-check invocation,
    recheck preparation and local live gate before execution. Proven non-started repairs preserve
    feedback and can reuse the last actually observed compatible session, without inventing one.
51. **Schema revision 6 and scope:** additive worker records with atomic backed-up v1–v5 upgrades;
    offline launcher-detachment evidence is not GUI-host/logout/reboot survival. P3 two-slot
    concurrency and aggregate time/turn reservation are deliberately still unimplemented.

52. **P3 explicit parallel admission:** `[execution] max_parallel_per_project` defaults to 1,
    accepts only integer 1/2 and is reloaded under each reservation lock; goals in the same
    repo/state share it. Lowering the cap stops new reservations, not accepted work. No queue.
53. **Conservative scopes:** parallel tasks need disjoint literal roots before glob wildcards,
    case/Unicode normalized; ignore forbidden-set narrowing and refuse unknown overlap. This
    describes write intent, not OS isolation. Competing candidates remain serial.
54. **Setup and verifier slots:** preparation is project-exclusive because trusted scripts lack
    a complete effect scope. Manual/recovered verifier entrypoints use capacity/scope guards;
    already VERIFYING keeps its slot. Every unresolved historical execution retains capacity.
55. **Cumulative goal ceilings:** optional immutable total executor-seconds/turn limits reserve
    full per-attempt ceilings transactionally; success/failure/cancel/unknown retain them. Only
    confirmed non-start refunds. Requested turns are not billing/usage/enforcement evidence.
56. **No separate budget database:** immutable attempts plus validated TaskSpecs are the ledger,
    with decimal seconds arithmetic; schema remains 6. Omit absent new goal fields from canonical
    JSON to preserve prior digests/replay. No silent total cap is added to historical goals.
57. **P3 local acceptance boundary:** two fake workers, race-safe admission and simulated host
    session teardown meet the local core checks; installed-host cleanup, logout/reboot and real
    multi-harness/turn-limit acceptance remain later gates. Proceed to P4 without new live spend.

58. **P4 separate freeze/materialize:** durable input/order/check records precede Git work; every
    current planned/linked child is required, dependency order explicit and unknown exits refused.
    No implicit selection, scope amendment or refresh of accepted input versions.
59. **P4 deterministic candidates:** compose retained approved commits from the fixed goal base;
    preserve partial refs on conflict. Private refs/worktree branches are not delivery branches.
60. **P4 crash ownership:** Git work is serialized under the SQLite writer lock; retry adopts only
    the identical pin and unchanged owned worktree. Existing candidates are never reset/recreated
    by replay; source edits, foreign branches, symlink targets and unresolved resources survive.
61. **P4 persistence/boundary:** schema 7 adds integrations with v1–v6 backup/rollback. Frozen
    verification is metadata until the next slice implements checks/review/delivery; no new model
    spend or real-state migration. Conflict-repair binding and cleanup remain explicit later work.

62. **P4 verification admission:** explicit frozen foreground checks are project-exclusive across
    goal-linked work, even with cap two; ten runs per integration, no Executor budget consumption.
63. **P4 uncertain checker exits:** commit an uncertain launch window before spawn; recovery never
    signals/reexecutes and only releases proven-exited checkpoints after owner death. Unknown holds
    remain exclusive and prevent goal terminal projection; acknowledgements are not exit evidence.
64. **P4 exact review:** approval binds current Advisor epoch, current run, unchanged composed
    candidate and digested manifest/logs; takeover/new checks/evidence changes invalidate current
    approval. Negative decisions record findings without dispatch; rejected approvals are durable.
65. **P4 evidence/environment:** checks reuse finite process-group execution and bounded redaction
    with isolated preparation environment; scripts remain trusted code, not sandboxed. Manual
    candidate edits cannot be blessed by verification; approved inputs must be reintegrated.
66. **P4 check persistence/boundary:** schema 8 preserves old candidates through backed-up v1–v7
    upgrade; integration approval does not select READY_TO_DELIVER or create a delivery branch.
    Conflict-repair binding, exact delivery and safe cleanup remain. No new real call/state migration.

67. **P4 current selection:** latest frozen integration supersedes previous readiness; never fall
    back to an older passing candidate while newer work is unapproved. Current exact approval and
    idle project project READY_TO_DELIVER; child success never does.
68. **P4 branch publication:** persist a frozen delivery intent, then create the requested local
    branch and private proof ref atomically with Git create-only/no-deref operations. Existing
    branches, even matching unowned ones, symbolic refs, case aliases and selected unborn branches
    are refused; no checkout/source edits/push/PR or rebase.
69. **P4 retry/history:** a matching ref pair plus retained bindings permits crash finalization;
    completed replay only observes, never recreates/reset refs. Historical publication can be
    confirmed after takeover without applying later workspace changes to the delivered commit.
70. **P4 terminal scope:** pending/completed delivery fences new goal mutations; current Advisor
    may abandon an unproved prepared intent without deleting any refs. Completed goals need a new
    goal for new work; missing/changed delivery evidence needs attention rather than reopening.
71. **P4 delivery persistence:** schema 9 adds intents/receipts and goal/branch uniqueness, with
    backed-up v1–v8 upgrade/rollback. Local delivery spends no Executor budget; conflict-repair
    binding and cleanup remain. No real user-state migration or model/remote publication calls.

72. **P4 repair provenance:** a single repair plan binds the latest conflict/failed candidate and all pending inputs in an immutable child baseline; normal task dispatch counts every repair-child execution against both goal attempt and repair ceilings.
73. **P4 explicit resolution:** new integrations select an approved repair child resolving an exact ordered input prefix, preserve all required inputs and original total checks, and create new ancestry/verification/review rather than mutating old approvals.
74. **P4 retention:** explicit post-delivery cleanup only non-force-removes selected clean owned worktrees after raw file/registration/epoch/activity checks; all branches, pins, evidence, caches and working edits remain, including approved uncommitted changes.
75. **P4 cleanup interruptions:** persist per-resource launch markers; uncertain removal is never reissued, and new keys cannot bypass an unresolved resource. Schema 10 adds backed-up atomic v1–v9 cleanup receipts without rewriting existing digests or migrating actual user state.

76. **P5 native contracts:** a discriminated Codex executor contract has its own sandbox/model options; legacy fake/Claude normalized JSON remains unchanged and schema revision stays 10.
77. **P5 evidence ceiling:** Codex exec JSONL turn completion does not prove internal model-step limits, actual model, subscription or effective permissions; live dispatch is refused before reservation in both service and adapter, with no override or invented limit flag.
78. **P5 common lifecycle:** Codex stubs reuse managed worktrees/workers/checks/review/budgets; exact canonical UUID resume requires the same task/repo/worktree/executor/requested model. Unknown/lost/ambiguous stream evidence never promotes success or rebinds a mismatched session.

79. **P6 shared connection:** plugins consume trusted runtime/state path records outside their caches; explicit locators precede defaults, with no credentials, implicit state merging or model authorization in connection metadata.
80. **P6 model-free compatibility:** bundled standard-library probes use temporary home/state for help/version/offline doctor; they never open the selected database. Native isolated installation, desktop discovery and real agent behavior are separate evidence levels.
81. **P6 Advisor workflow:** the existing host session operates goals, epochs, child workspaces, durable jobs, review and exact local delivery; installation neither starts an agent turn nor renews a live allowance. Background gate closure waits for confirmed completion/non-start.
82. **P6 first-use state:** both hosts reuse one owner-readable default connection and a dedicated new empty shared store; old task locators take precedence and historical validation databases are never silently imported or migrated during setup.
83. **P6 acceptance boundary:** actual native catalog loading and tool PTY exit/reconnection count as model-free entrypoint evidence; they do not prove current GUI hot refresh, full app termination, real agent instruction-following or dual-harness execution.
84. **P7 reproducibility:** a fresh-only synthetic packet and mock-only two-adapter rehearsal exercise the frozen acceptance scenario without reusing user state; scripted review, requested/reserved ceilings and simulated Advisor takeover are never promoted to native live evidence or authorization.

85. **P7 budget decision (explicit user approval):** only new Codex tasks can opt into null native turn ceilings and attempts/wall/cancel budgeting; numeric frozen tasks remain refused, and numeric goal-turn budgets cannot admit an uncapped child.
86. **P7 native provenance:** use version-pinned native account/config metadata, enforce ChatGPT/default OpenAI routing and per-invocation restrictions, then verify effective config without persisting raw account/config or reading credentials directly.
87. **P7 worker reconstruction:** repeat Codex configuration validation after claim and compare the complete invocation digest; propagate Codex environment guards to workers. Confirmed non-starts preserve attempt history and never become native execution evidence.
88. **P7 licensing/distribution (explicit user approval):** Apache-2.0, local candidate only; separate runtime and task state from host caches, inventory packaged files, and do not publish/tag/push.
89. **P7 native stop:** a denied extra Claude self-check triggers the packet's permission stop even though independent checks and exact code review pass. Preserve spent budget/evidence and require explicit resume before further native calls.

90. **P7 continuation:** explicit human resume reuses the original goal/session and remaining allowance; successful exact repair/integration/delivery consumes no invented extra allowance. Preserve the earlier stop and non-start receipts.
91. **P7 cancellation evidence:** a native CLI/group exit does not prove a separately grouped tool exited. The observed survivor makes the native case fail despite its old receipt; cleanup evidence does not retroactively turn the case into a pass.
92. **P7 descendant observation:** sample ancestry without command/environment values, pin observed birth identities, revalidate before individual detached-child signals, and hold uncertainty on inspection failure or known survivors. Sampling is not OS containment and does not prove absence of unobserved fast-reparenting descendants.
93. **P7 history surface:** native CLI transcripts are bound to child worktrees; desktop conversation-list synchronization is not promised or used as execution evidence. Never spend a model turn merely to populate a UI history item.

94. **P7 final bounded allowance:** explicit continuation accepts the already-proposed +1 Codex / 90s expansion; after the final two executions, 8 executions / 975 reserved seconds are spent. Retain prior stops/failures and native turn-count discrepancies; no automatic retry or renewed allowance.
95. **Desktop continuity requirement:** preserve native UUID/worktree; same-session visibility is a product requirement, separate from execution success. First slice is explicit Claude handoff after terminal/delivered state, with durable once-only receipt and Advisor fencing. Native acknowledgement never means verified UI visibility; Codex source/list limitations remain open, with no vendor-history edits or artificial model turns.

96. **P7 alpha.4 Advisor continuity:** preserve a user's desktop-visibility request through delivery and perform supported follow-up before cleanup; compatibility probing requires desktop commands/Advisor flags without opening selected state. Native list-source filtering is diagnostic evidence, never permission to rewrite vendor history or invent replacement conversations.
97. **P7 distribution closeout:** build the complete local candidate from one clean commit, include linked documentation/source plus a model-free standalone consistency verifier, and map V01–V15 to evidence levels; packaging success never converts deferred UI or unresolved Codex synchronization into acceptance.

98. **Desktop native acceptance:** Claude requires an input-free bounded PTY; preserve legacy pipe failures with a one-shot explicit recovery only for the pinned pre-handoff exit-1 case. Codex uses a canonical existing-thread URL with app/binary/version guards. Native acknowledgements, tool-observed Claude UI and human-observed Codex UI remain distinct evidence.
