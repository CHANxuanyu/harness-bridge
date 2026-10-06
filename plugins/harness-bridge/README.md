# Harness Bridge Advisor plugin alpha

The user's existing coding-agent conversation is the **Advisor**. This shared Skill connects
Codex/ZCode to the separate `hbridge` runtime for project discovery, goals, isolated Executor
workspaces, background jobs, review/repair and local result-branch delivery. It contains no model
client, MCP server, auto-run hook or Executor harness.

Claude Code supports the gated live route. New Codex tasks can explicitly select an
attempt/wall-time/cancel budget with native configuration preflight; see the bundled
[live readiness](skills/harness-bridge/references/live-readiness.md) and runtime acceptance notes.
ZCode execution is unimplemented. A Claude Advisor must respect the nested-session gate;
it may inspect evidence, but must not strip markers to launch another Claude session.

## Development installation

1. In the Bridge checkout, install its locked environment with `uv sync --frozen`. Record the
   absolute `.venv/bin/hbridge` path. The plugin cache is not the runtime checkout. Runtime is
   `0.1.0.dev1`, protocol `1.0`; this plugin is `0.1.0-alpha.3`.
2. Choose an absolute state directory outside the target repository/plugin cache. Reuse that
   directory across Advisor hosts. Keep validation state separate; live gates default closed.
3. For Codex, register the checkout's `.agents/plugins/marketplace.json` using
   `codex plugin marketplace add /absolute/path/to/checkout`. CLI 0.160.0 exposes
   `codex plugin add harness-bridge@harness-bridge-local --json` (the verb is `add`, not `install`).
   Check current host help and verify with `codex plugin list --json`. Installation is distinct
   from whether an already-open desktop conversation has refreshed its Skill catalog.
4. For ZCode, add the checkout root containing `marketplace.json` through its plugin market's
   Add marketplace UI, then install Harness Bridge. Inspect installed version and Plugin skills.
   Keep the marketplace entry version aligned with the package for updates.
5. Record trusted runtime/state paths once using [connection.md](skills/harness-bridge/references/connection.md).
   Run its bundled checker first; it never opens the selected state or calls a model. Both hosts
   reuse this connection and discover projects through Bridge. Loading a plugin grants no model
   allowance. Do not start a new agent conversation merely to test installation.

These are developer setup instructions, not a one-click distribution. No published Python package
or official marketplace listing is assumed. Installation affects the chosen host profile; the
package never installs itself. See the repository's P6 validation record for actual evidence.

The package can be copied to a host cache; every Skill reference stays inside it. Runtime/state
locations are resolved independently from trusted local connection metadata.

## Use

- “Use Harness Bridge to inspect this project's existing goals and jobs.”
- “Delegate this bounded change to Claude Code and review the result; allow one repair.”
- “Continue this Bridge goal in the current conversation and inspect the existing job first.”

The Advisor prepares files and operates the CLI. Bridge creates/binds workspaces and returns
receipts. Child success is approval of an isolated candidate. Goal delivery requires total-goal
checks and exact integrated review, then creates a new local branch. No push, PR, source-checkout
merge, automatic wake-up or automatic conversation transfer is implied.

Package formats checked against [OpenAI](https://developers.openai.com/plugins/build/plugins)
and [ZCode](https://zcode.z.ai/en/docs/plugin) documentation on 2026-10-06.
