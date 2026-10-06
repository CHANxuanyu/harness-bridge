# P6 Advisor entrypoints — package and offline connection slice

Date: 2026-10-06. Baseline `bbe0132`, local branch `local/glm-macos-validation`.
Package: `0.1.0-alpha.2`; runtime `0.1.0.dev0`, protocol `1.0`, database revision 10 unchanged.

This slice's remaining-work section is historical. Subsequent actual-profile installation,
shared first-use setup and native tool reconnection are recorded in
[P6_DESKTOP_ACCEPTANCE.md](P6_DESKTOP_ACCEPTANCE.md).

## Implemented

The shared Codex/ZCode Skill now covers project discovery, goal creation/takeover with Advisor
epoch fencing, immutable child plans, owned workspace materialization/preparation, durable
background jobs and cursor waits, evidence review, bounded repair, integrated acceptance,
exact local-branch delivery and explicit cleanup. Legacy standalone tasks remain supported.
Self-contained goal/plan examples and references survive copying to a host cache. The three
manifests and ZCode marketplace entry carry the same new package version.

A trusted local connection record carries only runtime/state paths. Resolution is explicit file,
`HBRIDGE_CONNECTION`, then XDG/home config default; an existing task locator takes precedence in
the Skill. Multiple state roots remain explicit, not merged or searched globally. No credential,
Advisor claim, model permission or live-gate setting is stored in the connection.

The bundled standard-library `check_connection.py` accepts a connection file or two absolute paths.
It probes the trusted runtime version, 34 command help surfaces and protocol/offline diagnostics
in a temporary state/home. It never opens, creates or migrates the selected task store. It writes
no connection or host settings. Ordinary project/task reads may open/migrate a store; documentation
distinguishes those operations from this compatibility probe. Missing/incompatible connections fail
without dispatching or echoing arbitrary runtime error output. No runtime dependency was added.

## Checks actually run

- Pre-edit focused baseline: model + CLI tests, **24 passed**, 11.19s, lint/format/mypy clean.
- New copied-package/connection/CLI workflow suite initially had **22 passed, 2 failed**, 25.48s.
  Both failures were test assumptions: portable manifest uses implicit skill discovery rather than
  a `skills` field; Bridge has explicit `close()`, not a context manager. Fixed those assertions/
  teardown; no runtime behavior was relaxed.
- Final `scripts/check.sh tests/integration/test_plugin_entrypoint.py`: **24 passed**, 19.96s;
  ruff/format clean (125 files), strict mypy clean (37 runtime source files).
- Skill Creator `quick_validate.py`: **Skill is valid** (existing local PyYAML environment).
- Connection checks cover missing/incompatible fields, boolean version rejection, absolute paths,
  configuration precedence, incompatible runtime/help/protocol/diagnostics and state nonmutation.
  Both a nonexistent state and deliberately unreadable-as-SQLite old state remain untouched.
- A copied package's examples drive separate real CLI processes through goal/child creation,
  fake background failure, job replay, event waits, project rediscovery, declared Advisor takeover,
  stale-writer refusal, one fake repair, child review, integrated checks/review and exact delivery.
  Exactly one task and two fake attempts remain; the source checkout fingerprint is unchanged.
  Cleanup is preview only. This simulates Advisor metadata; it is not two actual host agent turns.
- All fenced `hbridge` shell examples parse with the current CLI; copied relative references and
  JSON examples validate. No full 666-case suite was claimed or rerun: previous P5 full 642 and
  final affected 68 remain historical evidence, with these 24 new affected checks added separately.

## Native host observations (no model inference)

Codex CLI 0.160.0 ran with a separate empty HOME/CODEX_HOME under the takeover chat's
`work/p6-entrypoints/codex-profile`, never the user's active profile/auth. Its supported install
verb is `plugin add`; an exploratory `plugin install --help` was rejected and corrected.

1. `plugin marketplace add <local checkout>` succeeded.
2. `plugin add harness-bridge@harness-bridge-local --json` installed **0.1.0-alpha.2**.
3. `plugin list --json` reported **installed: true, enabled: true**.
4. All **13 cached package files** byte-hashed equal to source. The checker ran from that native
   installed cache and passed all 34 help probes; the selected state directory still did not exist.

This proves native CLI installation/cache wiring in an isolated profile. It does not prove that
the current desktop chat loaded/refreshed the Skill or followed its instructions.

ZCode native UI was inspected in the existing harness-bridge workspace. After the user explicitly
confirmed adding/installing this local package at the computer-use boundary, the local checkout
was added as a marketplace and **0.1.0-alpha.2 installed**. Settings → Skills lists Harness Bridge;
its detail reports **enabled**. The UI reports its cache at
`~/.zcode/cli/plugins/cache/harness-bridge-local/harness-bridge/0.1.0-alpha.2`.
All 13 cached files match source; the checker run from this installed cache passed all 34 command
probes using the same connection record as the isolated Codex package, without creating/opening
the selected state. No Try now action, agent prompt, conversation creation or model call occurred.
This verifies actual ZCode installation and Skill discovery, not agent behavior after loading it.

## Remaining acceptance

P6 is **partial**, not complete: the user's actual Codex desktop catalog and host behavior/lifecycle
acceptance remain. ZCode actual installation/Skill discovery and isolated native Codex installation
now pass. No current conversation restart or new model turn is needed just to
inspect installed metadata. End-to-end agent behavior and real Executor work require their own
bounded acceptance. No new model calls were made; the old live repair allowance remains exhausted.
Codex live is still unavailable and ZCode execution unimplemented. There was no remote push,
public publication, visibility change, actual user-state migration or global live-gate change.

Raw native receipts and cached-package hash/check report remain outside the public repository in
the takeover chat's `work/p6-entrypoints/`. This record contains only redacted outcomes.
