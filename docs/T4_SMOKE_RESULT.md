# T4 bounded smoke result — 2026-10-06

**T4 single-run smoke PASS，修复/resume 未验证。** The current local Codex session
initiated the real executor, read its evidence and actual diff, and submitted the
snapshot-bound review. A fresh CLI process confirmed **SUCCEEDED**.

## Identity and preflight

- Supervisor harness: **current Codex local session**; model **gpt-6-astra**, xhigh,
  evidenced by this session's local rollout `turn_context.model` / `effort` fields.
- Bridge: `096238e236a52a0cd04587453a7a5e588b84b088`, branch
  `local/glm-macos-validation`; clean checkout before this run, exactly the T3 result
  commit. Repository visibility settings were not changed; keep public. No push.
- Executor: requested = observed **claude-opus-5-5**; Claude Code **2.1.291**,
  `~/.local/bin/claude` resolving to `~/.local/share/claude/versions/2.1.291`.
  Non-inference auth status: logged in, `claude.ai`, `firstParty`, subscription `pro`.
- No API/provider environment variables or bridge-recognized cloud/nested markers.
  User/project/managed settings and MCP files checked absent; global MCP count zero;
  no applicable per-project MCP or permission entries for the new fixture/state.
  Program/version/config sources matched the latest T3 record; reused its
  `--max-turns` acceptance evidence. No new probe, empty prompt, or offline-suite rerun.
- No additional system approval or external human execution was needed. Existing
  Codex permission profile was used unchanged; no protection markers were removed.
  No Codex subagent, GLM, provider/model switch, recharge or extra-usage enabling.

## One new task and its evidence

- Regenerated the untouched stub with `qa/local/make_fixture.py` in a new directory
  outside the bridge repo, with a new independent state/database/worktree/session.
  Both stub checks failed as expected before dispatch. No T3 implementation copied.
- Task `tsk_d83baa476c444db6834c`; attempt `att_10ba0f91dd4c45ee8d41`;
  session `8d42c8f1-8161-43f0-a082-2a50111a55a3`.
- Unique create key; **one `hbridge run`, one executor spawn, one initial attempt,
  zero repairs/retries**. Limits unchanged: 1 attempt, 0 repairs, 10 turns, 600 s.
  Executor reported **8 turns**; bridge measured **23.249 s**. This is not a claim
  of one model request. Bridge foreground command exited 0; executor exit 0 and
  process-group exit confirmed; no timeout, lingering pipes or background kill.
- Protocol: 27 lines, result/session recognized, 0 malformed/dropped/oversized
  events; 3 unknown `rate_limit_event` events tolerated. Model pin satisfied.
- Required `repo-tests`: **7 tests, exit 0**. Required independent external
  `acceptance`: **9 cases, 0 failures, exit 0**. No verifier warnings.
- External acceptance SHA-256 BEFORE = AFTER:
  `45a43f71cbb01a94382f82f1e025fb38fe2569e26f417a59ace7f3efc5479900`.
- Full stored diff and current implementation reviewed: lowercase first, collapse
  non-`[a-z0-9]` runs, strip edge hyphens, preserve empty result. A non-str TypeError
  is compatible with the required str domain. Existing tests retained; four added.
  Only `slugkit/slugify.py` and `tests/test_slugify.py` changed (+20/−1 total).
  Supervisor did not implement/edit the function or change tests to assist it.
- Scope violations **0**; approval blockers **0**. Two Bash denials were inspected:
  a compound editing/test/status command and a direct external-acceptance command,
  both beyond the narrow Bash allowance. Permissions stayed unchanged; the bridge
  ran external acceptance independently. These denials did not block approval.
- `approve` used the artifacts review template, with the idempotency key inside
  review JSON, bound to snapshot
  `sha256:bb332f545e5be8ef351fe2dd3ad63dd928023508b70b98a6950142c8d9e24f09`.
  Review `rev_ab414d7ff130496ab7ec` accepted; separate `hbridge status` process
  confirmed **SUCCEEDED**, attempts used 1, repair cycles used 0.

## Retention, usage and limits

- Isolated state live gate **closed** (`enabled = false`); global live defaults
  and T3 retention directory untouched. Local diagnostics locator:
  current Codex workspace `work/t4-f42e719a1835/`; raw logs, DB, worktree and review
  remain outside this public repo. Only this result and required status docs commit.
- Procedural deviation: one initial read-only `hbridge --help` omitted
  `--state-dir`. Every subsequent hbridge command explicitly used the same new
  isolated state directory; no stateful command used the default directory.
- Executor-reported tokens: input 10, output 2,544, cache-read 104,352,
  cache-creation 15,804. CLI API-equivalent estimate **USD 0.1982224**, not a bill
  or subscription usage measurement. Subscription remaining **unknown**; current
  extra-usage setting **unknown**, unchanged. No model API was called by the bridge.
- Earlier 184-test/macOS demo/T3 results are prior evidence, not rerun here.
  This establishes one live Codex→bridge→Claude initial-run loop only; repair,
  resume, timeout enforcement, interrupted recovery and T5 remain unverified here.
