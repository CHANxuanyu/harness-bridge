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
