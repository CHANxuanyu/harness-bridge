# Harness Bridge local plugin alpha

This package lets the current coding agent supervise tasks through the separate `hbridge`
CLI. It supplies a shared Skill with Codex and ZCode manifests. It contains no model client,
MCP server, auto-run hook, background service, or executor plugin.

The current live execution route is **this host → local Bridge → Claude Code**. Calling
Codex or ZCode as an executor is not implemented. An agent running inside Claude Code must
respect the nested-session gate; it can inspect evidence, but must not strip markers to
launch another Claude session.

## Development installation

1. In the Harness Bridge source checkout, install its locked Python environment with
   `uv sync --frozen`. The runtime entrypoint is the absolute path to `.venv/bin/hbridge`
   in that checkout. The plugin's cached directory is **not** the runtime checkout.
   The runtime is `0.1.0.dev0`, protocol `1.0`; this plugin is `0.1.0-alpha.1`.
2. Choose an absolute state directory outside the target repository and plugin cache.
   Reuse the same directory from each host that should see the same tasks. Keep validation
   state separate from everyday tasks; live gates default closed.
3. For Codex, the source checkout includes `.agents/plugins/marketplace.json`. The documented
   way to register a local source is `codex plugin marketplace add /absolute/path/to/checkout`.
   Then select Harness Bridge from that local source in the host's plugin manager.
4. For ZCode, add the checkout root (which contains `marketplace.json`) through
   Settings → Plugins → Create → Add marketplace, then install Harness Bridge.
5. Give the host the runtime executable and state directory once. Start with a request to
   inspect the runtime offline or list existing tasks. Loading the plugin does not authorize
   model usage. Use the host's normal reload/new-session behavior after installation.

These are developer setup instructions, **not a verified one-click installer**. No published
Python package or official marketplace listing is assumed. This change does not edit global
host configuration or install itself. Host activation and live invocation through an installed
plugin are separate acceptance steps; see the repository's product and validation records.

The package can be copied to a host cache without references escaping to the source checkout.
Runtime location is discovered independently through PATH or an explicitly supplied path.

## Use

- “Use Harness Bridge to inspect this project's existing tasks.”
- “Delegate this bounded change to Claude Code and review the result; allow one repair.”
- “Continue reviewing Bridge task TASK_ID from STATE_DIR.”

The host prepares the task/review files and operates the CLI. A completed task currently means
the isolated candidate was approved; the plugin must report its location and must not claim
the source branch was updated. A dedicated delivery operation is still backlog work.

Package formats checked against
[OpenAI](https://developers.openai.com/plugins/build/plugins) and
[ZCode](https://zcode.z.ai/en/docs/plugin) documentation on 2026-10-06.
