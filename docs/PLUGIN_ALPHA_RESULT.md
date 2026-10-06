# Local plugin alpha: package and discovery evidence

Date: 2026-10-06. Runtime baseline `94f7c4d`, runtime version `0.1.0.dev0`, protocol `1.0`.
Plugin version `0.1.0-alpha.1`. macOS, Codex CLI `0.160.0`.

## Scope

One shared supervisor Skill, bundled workflow/live-readiness/task example, portable manifest,
Codex compatibility manifest, ZCode manifest, and host-specific marketplace catalogs.
No runtime Python implementation change. No model calls, executor dispatch, renewed live
authorization, or repetition of the earlier complete test suites/demos.

## Executed checks

| Check | Actual result | Limit |
|---|---|---|
| skill-creator `quick_validate.py` | PASS | metadata/Markdown check, not behavioral evaluation |
| Copy complete plugin into isolated temporary cache directory | PASS | 3 relative Markdown links resolve inside copy; skill paths exist; no reference depends on source checkout |
| Manifests and catalogs | PASS | 3 manifests agree on identity/version; both catalogs locate the same package |
| Bundled example through actual `TaskSpec` model | PASS | defaults fake; 2 attempts / 1 repair; required external acceptance; not executed |
| Documented live-executor conversion through `TaskSpec` | PASS | schema only; no gate enabled or executor started |
| 16 documented command shapes through actual CLI parser | PASS | command/option contracts only; no service dispatch or state creation |
| Codex marketplace registration and available-plugin discovery | PASS | recognizes name, version, path and available policy; not installed or enabled |
| ZCode native loading | NOT_RUN | manifests based on official format; no ZCode UI interaction performed |
| Installed-host Skill trigger and end-to-end delegation | NOT_RUN | catalog discovery does not prove workflow behavior |

The skill validator ran in a disposable uv environment with pinned `PyYAML==6.0.3`; no runtime
dependency or project lockfile changed. The package check used the project's Python 3.11
environment and real schema/parser code. Local check script/report are in the takeover chat's
`work/product-form/` directory, outside this public repository. The first checker run needed
macOS temporary-path canonicalization (`/var` vs `/private/var`); the corrected check passed.

## Codex discovery sequence

Running from the source checkout alone returned no available entry in this installed CLI.
The source was not already registered. Explicit local registration was required for this
non-inference discovery check:

```text
codex plugin marketplace add <checkout> --json
codex plugin list --marketplace harness-bridge-local --available --json
codex plugin marketplace remove harness-bridge-local --json
```

Registration returned `alreadyAdded: false`. Discovery returned:

```json
{
  "pluginId": "harness-bridge@harness-bridge-local",
  "version": "0.1.0-alpha.1",
  "installed": false,
  "enabled": false,
  "installPolicy": "AVAILABLE",
  "authPolicy": "ON_INSTALL"
}
```

Removal succeeded; subsequent marketplace inspection confirmed the temporary source absent.
No plugin installation or global live-gate change occurred. This validates the actual local
catalog parser rather than treating JSON syntax checks as host support.

## Remaining product work

`docs/PRODUCT_FORM.md` is the working use/distribution contract. Installed activation,
runtime/state discovery, cross-host continuation experience, approved-change delivery,
host-independent execution, and additional executor adapters remain separate work. The plugin
does not make the existing runtime production-ready or promise arbitrary subscription routing.
