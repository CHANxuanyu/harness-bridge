# Observability: fault diagnostics, product events, operation records

Record schema version 2 (`src/harness_bridge/observability/schema.py`; `hbridge diag events` prints it).
v2 (review round EF4): `msg` aliases `(session ID, client message ID)`, matching the business
receipt identity; v1 aliased the client message ID alone. v1 lines remain readable (see Summary).
Everything is local. Nothing is uploaded, no remote endpoint exists, no SDK is used.

## Defaults and switches

| Stream | Default | Location | Size / retention |
|---|---|---|---|
| Fault diagnostics | **on**, level ≥ info | `<state>/observability/diagnostics/diag.jsonl` (+ `.1`…`.4`) | 1 MiB per file, 5 files (≈5 MiB), files older than 14 days pruned |
| Product events | **off** | `<state>/observability/product/events.jsonl` (+ `.1`, `.2`) | 1 MiB per file, 3 files, 30 days |
| Exports | only on `hbridge diag export` | `<state>/observability/exports/*.zip` or `--out` | never rotated, never overwritten |

Precedence: defaults < `<state>/observability/settings.json` (`hbridge diag config`) <
`HBRIDGE_DIAGNOSTICS` / `HBRIDGE_PRODUCT_EVENTS` (`0|1`). `HBRIDGE_DIAG_LEVEL` lowers/raises the
diagnostic level (debug adds frequent reads such as `/api/state` and terminal keystroke routes —
as route names only). A disabled recorder creates no directory. Directories are 0700, files 0600.
`alias.key` (32 random bytes) is per state directory and never exported.

## Record shape (whitelist)

```json
{"v":2,"ts":"2026-10-10T17:18:59.774Z","seq":7,"proc":"p_0bbbfef1","stream":"diag",
 "env":"test","ver":"0.1.0.dev2","sha":"92ed653eaa96","level":"info","component":"run",
 "event":"connect.start","op":"op_6fbdb726a364","session":"s_22099216e3","run":"r_7eb4c0e48d",
 "outcome":"spawned","duration_ms":7,
 "attrs":{"harness":"codex","kind":"resume","transport":"structured","linked":true}}
```

| Field | Meaning / allowed values |
|---|---|
| `v`, `ts`, `seq`, `proc` | schema version; UTC ms; per-process sequence; random per-process ID (`p_` + 8 hex) |
| `stream` | `diag` or `product` |
| `env`, `ver`, `sha` | `prod|dev|test`; package version; first 12 hex of the code SHA or `unknown` |
| `level`, `component`, `event` | closed sets from the dictionary below |
| `op` | operation ID `op_` + 12 hex, random per API/service operation — not a native `request_id` |
| `name` | route family (`session.send`, `history.discover`, …) — never the path or query |
| `project`/`session`/`run` | `HMAC-SHA256(alias.key, kind:local_id)[:10]` with prefix `p_`/`s_`/`r_` |
| `msg` | `m_` + the same HMAC over `session_id NUL client_id`: two sessions using one client ID stay distinct; no `msg` without a session |
| `outcome`, `duration_ms` | per-event enum; integer ms |
| `code`, `reason`, `error_type` | `BridgeError` code; stable reason from a closed list (else `other`); exception class name |
| `attrs` | per-event fields below, each typed (enum / bool / count / ms) |

Never recorded: request URL/query/headers/cookies/body, launch links, environment values,
prompts, conversation/tool text, attachment names or content, file paths (project/workdir/state),
native session IDs, the client message ID itself, error messages, stderr/PTY output, model
names. Enforcement is structural: undeclared fields are dropped, enum mismatches become `other`,
other invalid values are dropped; records over 2 KiB lose `attrs` (`truncated: true`). The export
re-validates every line. Tests plant a synthetic secret in URL/query, headers, cookie, body,
project path, attachment, native error text (with the native ID) and an exception message, then
scan logs, bundle and summary (JSON and CSV).

## Event dictionary

`product` = also written to the product stream when enabled. Every event is a diagnostic record.

| Event | product | level | outcomes | attrs | Trigger / meaning |
|---|---|---|---|---|---|
| `app.start` | — | info | — | env_source, native_env, code_source, code_dirty, schema, schema_expected, python, os, diagnostics, product_events, alias_stable | Workbench constructed (after reconcile) |
| `app.stop` | — | info | — | uptime_ms, live_runs, dropped, write_errors | `Workbench.close()` |
| `op.end` | — | info (warning on error; debug for frequent reads/keystrokes) | ok, error | http_status | every API call through `server._run` |
| `history.discover` | — | info | ok | harness, items, completeness, reasons, paged | scoped discovery returned |
| `history.read` | — | info (debug for complete conversation reads, warning if unavailable) | ok | source, page_state, items, reasons | preview / conversation page |
| `diag.dropped` | — | warning | — | dropped, write_errors | first successful write after losses |
| `session.link` | yes | info | created, relinked, duplicate, refused | harness | `link_session` result |
| `session.unlink` | yes | info | ok, refused | harness | `unlink_session` result |
| `connect.start` | yes | info | spawned, refused | harness, kind, transport, linked, step | `start_run` (explicit start or the auto-resume inside a send) |
| `connect.ready` | yes | info | — | harness, kind, transport | first structured ready / first terminal output of a run |
| `connect.fatal` | yes | warning | — | harness, cause, ready | bridge ended a connection (`native_identity_changed` / `native_protocol`) |
| `run.end` | yes | info (warning for failed/unconfirmed) | — | harness, transport, status, exit_class, ready, released_for, stop_requested | native process ended |
| `turn.end` | yes | info | — | harness | the current turn ended (native completion, interrupt or failed submit) — **not task success** |
| `message.submit` | yes | info | accepted, reused, refused | harness, attachments (count), linked | `send_message` returned or raised |
| `delivery.state` | yes | info (warning for unknown) | — | harness, from_state, to_state, evidence, latency_ms | a durable receipt's effective state changed |
| `desktop.open` | yes | info | requested, acknowledged, not_acknowledged, failed, refused | harness, released | official desktop open request |
| `desktop.return` | yes | info | — | harness, had_hold | user confirmed outside use ended |

`connect.start` refusal `step`: `request`, `link_check` (unlinked/environment changed/identity/
unsupported source/archived), `external_confirmation`, `preflight`, `directory`, `admission`
(local writer busy), `spawn` (process could not start). `handshake` failures appear as a spawned
run that ends without `connect.ready` (`run.end` with `ready: false`) or as `connect.fatal`.

`delivery.state.evidence`: `native_protocol` (live protocol callback), `native_history_client_id`
(native history item with the **exact** client message ID), `connection_ended` (queued →
`not_sent`, sending → `unknown` after the run ended). Only effective changes are recorded: the
store refuses to downgrade `sent`, and a refused write or a repeated read produces no event.

## Success definitions and what cannot be observed

* Association completed = `session.link` `created` or `relinked`. `duplicate` (already linked) is
  reported separately and excluded from the rate.
* Connect/resume ready = spawned run with `connect.ready`. Refusals are counted per step.
* `sent` = the native CLI accepted the message. It is **not** task success; Bridge cannot observe
  task completion (`task_completion: not_observable`). `turn.end` counts are shown separately.
* `unknown` stays unknown until exact native client-ID proof arrives; it is never counted as sent
  or zero. Claude Code has no durable receipt: its submissions appear as `no_receipt`.
* Desktop: an open request (even `acknowledged`) and a user's return confirmation are recorded,
  but end-to-end continuation is `not_observable`.
* Model calls, tokens and cost inside the official CLIs: `unknown` (never estimated).

## Summary semantics (`hbridge diag summary`)

JSON (`repobridge.summary.v1`) or long-form CSV (`section,metric,value`). Contains: requested
window and first/last record time; environment filter, environments included and
`contains_test_data`; sample counts and read statistics (lines, corrupt, invalid, exact
duplicates, excluded by env/window); a diagnostics overview (levels, events, error codes, failed
operation names, dropped records, code versions); product metrics with explicit denominators:

* `link`: attempts, completed, refused (+ reasons), duplicate, completion_rate.
* `connect`: attempts, spawned, refused_before_spawn by step/reason, ready, ended_before_ready,
  no_outcome_in_window, fatal by cause, ready_rate, ready latency (n/p50/p90/max/missing).
* `delivery`: distinct accepted submissions (denominator), final state per message (`sent`,
  `not_sent`, `unknown`, `in_flight`, `no_receipt`), by harness, unknown later confirmed sent,
  reused/refused submissions, sent confirmation latency with `missing` (no in-process submit
  time, e.g. confirmed after restart — not filled with zero).
* `desktop`, `turns_ended_observed`, `task_completion`, `model_usage` as above.

De-duplication: exact duplicate lines (same `proc`+`seq`) are removed; then per event —
link/desktop by operation, connect/ready/run end by run alias, submissions by
`(session, msg)` and outcome, delivery by `(session, msg)` and target state. A repeated
(reused) submit keeps the first submission's start time and operation, so it neither adds a
submission nor resets the confirmation latency. `samples.record_versions` counts v1/v2 lines;
v1 messages are re-keyed by `(session, msg)` and reported as `delivery.v1_records` with a note
that their latency/operation link may have been shared across sessions reusing a client ID. When product events are disabled the
product section is `{"status":"unavailable","reason":"product_events_disabled"}` — absent, not 0.

## Diagnostics bundle (`hbridge diag export`)

One local zip (0600, exclusive create) with `manifest.json` (files, sizes, SHA-256, record schema and versions present,
`uploaded: false`, `contains_test_data`, exclusion list), `environment.json` (version, SHA, dirty,
Python, OS family, env, native_env, schema revisions, settings, read statistics — no paths,
hostnames or user names), `diagnostics.jsonl` (re-validated diagnostic records in the window),
`summary.json`, `summary.csv`. Not included: state databases, run directories (PTY output,
stderr, native event logs, conversation snapshots), attachments, handoff notes, native homes or
transcripts, auth files, raw product events, `alias.key`, settings, clipboard, environment values.
The user inspects the zip and decides whether to share it.

## Rotation, corruption, concurrency

Writers append whole lines under an exclusive `flock` on `<dir>/.lock` (bounded wait 1 s, then the
batch is dropped and counted), so several processes on one state directory interleave whole
records; a batch is split at rotation boundaries so files stay ≤ the size limit. A torn last
line (crash/ENOSPC mid-write) is isolated by starting the next batch on a new line. Readers skip
and count malformed, oversize (16 KiB) or non-object lines. Rotated files beyond the count and
files past the retention age are removed on the first write of a process.
