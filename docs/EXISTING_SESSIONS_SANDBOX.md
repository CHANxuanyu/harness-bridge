# Launch the isolated existing-session verification environment

These machine-specific commands launch the **tested integration source**, not the installed
RepoBridge. The launcher is retained in the local QA evidence directory; it does not exist on a
fresh clone. It reuses repository synthetic fixtures and explicit fake `claude`/`codex` executables,
creates a new `/private/tmp/repobridge-recheck-*` directory, clears inherited environment except
PATH/language/source path, and sets separate HOME/CODEX_HOME/Claude config/Git config/state. It
listens only on loopback with port 0. No real native histories, credentials or model calls are used.

```sh
cd /Users/chan/Downloads/repobridge-integration
export PYTHONPATH=/Users/chan/Downloads/repobridge-integration/src
HB_QA_PY=/Users/chan/Downloads/harness-bridge/.claude/worktrees/repobridge-product-direction-8e26f9/.venv/bin/python
HB_QA_DIR=/Users/chan/Documents/Codex/2026-10-06/harness-bridge-agent-local-glm-macos/repobridge-qa-0253b2f
"$HB_QA_PY" "$HB_QA_DIR/sandbox.py" --scenario normal --native
```

Requires the existing development virtualenv (including pywebview) shown above. It is read-only;
no install or dependency change is needed. Source under test is
`a0381264eed8c120ac7be3787d71d7ff76f8ee7b`; later documentation-only integration commits have the same
code. Before a later revalidation, record `git rev-parse HEAD` and check the source tree, rather than
assuming the moving branch still matches this receipt.

The new window/project is named **隔离复验项目**. It contains ordinary Codex/Claude sessions and
pre-existing synthetic native histories (Claude 151 user items, Codex 55 turns) discoverable with
“添加已有会话”. Adding/linking starts nothing. Confirm “外部已结束” only for this synthetic fixture;
then explicitly sending reaches the stub, never an account. Fake desktop apps only exercise the
launch/hold/return protocol and do not prove official-desktop continuation.

For the fault scenarios, close this isolated window and use one of these in the same shell. Each
command creates a fresh independent fixture. They do not consume or renew any real turn budget.

```sh
# Link the outside Codex candidate, confirm outside ended, attach a file and send.
# Writer refusal happens on native resume: not_sent, retain text/attachment once.
"$HB_QA_PY" "$HB_QA_DIR/sandbox.py" --scenario busy --native

# Ordinary or linked Codex: stub exits after accepting the turn/start request, before replying.
# The result must be unknown, with editable draft and no recovery/re-send action.
"$HB_QA_PY" "$HB_QA_DIR/sandbox.py" --scenario unknown --native

# Open Add Existing, choose Codex: explicit unsupported versus ordinary read failure.
"$HB_QA_PY" "$HB_QA_DIR/sandbox.py" --scenario unsupported --native
"$HB_QA_PY" "$HB_QA_DIR/sandbox.py" --scenario readfail --native
```

The terminal prints the new fixture directory and loopback address. Omit `--native` for an HTTP-only
server; Ctrl-C closes that owned server and its stubs. The native window uses the normal close
confirmation; close only that test window. The launcher stores its local authorization URL in
`<fixture>/runtime.json` with mode 0600. Do not publish that file or use the live app's URL/state.
To view an HTTP-only fixture in the default browser, substitute the exact printed fixture path:

```sh
"$HB_QA_PY" - /private/tmp/repobridge-recheck-PRINTED_SUFFIX <<'PY'
import json, pathlib, sys, webbrowser
root = pathlib.Path(sys.argv[1]).resolve()
assert root.parent == pathlib.Path('/private/tmp') and root.name.startswith('repobridge-recheck-')
assert (root / 'fixture.json').is_file()
webbrowser.open(json.loads((root / 'runtime.json').read_text())['url'])
PY
```

For a persistence check, stop the old instance before reopening the **same** printed fixture:

```sh
"$HB_QA_PY" "$HB_QA_DIR/sandbox.py" --root /private/tmp/repobridge-recheck-PRINTED_SUFFIX --scenario normal --native
```

Do not open two writers against the same fixture. `--root` refuses directories not made by this
launcher. It keeps native IDs, synthetic history and SQLite receipts. Switching to `normal` only
removes the injected CLI failure; it does not erase an unknown receipt or authorize a resend.
Refresh results reads only. Add exact-clientId native evidence only to the designated **synthetic**
fixture when reproducing settlement; never edit a real vendor history file.

Browser probes are retained as `busy.cjs`, `unknown_continue.cjs`, `late.cjs`, `network.cjs`,
`classify.cjs`, `query-order.cjs`, plus `common.cjs`. They encode particular fixture states and
ordering (some consume prior result JSON), so are evidence/reproduction source, not a general
one-command reusable test suite. `native_probe.py` is likewise tied to this run's synthetic root.
The commands above use `sandbox.py`, which creates fresh safe fixtures without those dependencies.
The long model label in layout evidence was supplied by a temporary copy of the stub catalog;
fresh fixtures otherwise display the default short stub model label.

For the repository's repeatable offline checks, use the same absolute source root:

```sh
cd /Users/chan/Downloads/repobridge-integration
export PYTHONPATH=/Users/chan/Downloads/repobridge-integration/src
HB_QA_BIN=/Users/chan/Downloads/harness-bridge/.claude/worktrees/repobridge-product-direction-8e26f9/.venv/bin
"$HB_QA_BIN/ruff" check .
"$HB_QA_BIN/ruff" format --check .
"$HB_QA_BIN/mypy" src/harness_bridge
"$HB_QA_BIN/python" -m pytest -m 'not live' -q --durations=8
```

These are the four checks in `scripts/check.sh`, using existing binaries directly to avoid changing
another worktree's environment. The recorded run was 994 passed / 983.79s. Do not re-run after a
pure documentation addition unless code changed or new evidence requires it.
