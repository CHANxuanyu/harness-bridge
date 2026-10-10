"""Read-side tools: summary (JSON/CSV), operation trace and the local diagnostics bundle.

All readers re-validate every line through the schema whitelist, skip and count malformed lines,
remove exact duplicates (same process + sequence) and de-duplicate state transitions, so a
replayed receipt or a history re-read cannot inflate a metric. Unknown values stay unknown: no
missing latency is filled with zero and no ``unknown`` delivery is counted as sent.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness_bridge.observability import schema
from harness_bridge.observability.recorder import DIR, STREAM_PATHS, load_settings, timestamp
from harness_bridge.observability.sink import read

SUMMARY_SCHEMA = "repobridge.summary.v1"
BUNDLE_FORMAT = "repobridge.diagnostics-bundle.v1"
FINAL_ORDER = ("sent", "not_sent", "unknown", "sending", "queued")  # receipt states
NOT_OBSERVABLE = "not_observable"
EXCLUDED_FROM_BUNDLE = [
    "workbench.sqlite3 and bridge.sqlite3 (real state databases)",
    "run directories: PTY output, stderr, native event logs, conversation.json",
    "attachments and handoff notes",
    "native CLI homes, transcripts, auth/login files",
    "product event records (only the aggregate summary is included)",
    "alias.key (alias secret) and settings.json",
    "clipboard, environment variable values, absolute paths, URLs, headers, hostnames",
]


def load(state_dir: Path, stream: str, stats: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Validated records of one stream, exact duplicates removed, in (ts, proc, seq) order."""
    stats = stats if stats is not None else {}
    sub, stem = STREAM_PATHS[stream]
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    raw_stats: dict[str, int] = {}
    for raw in read(state_dir / DIR / sub, stem, raw_stats):
        record = schema.clean(raw)
        if record is None or record.get("stream") != stream:
            stats["invalid"] = stats.get("invalid", 0) + 1
            continue
        key = (record.get("proc"), record.get("seq"))
        if key in seen:
            stats["duplicates"] = stats.get("duplicates", 0) + 1
            continue
        seen.add(key)
        out.append(record)
    stats["lines"] = stats.get("lines", 0) + raw_stats.get("lines", 0)
    stats["corrupt"] = stats.get("corrupt", 0) + raw_stats.get("corrupt", 0)
    out.sort(key=lambda r: (r["ts"], str(r.get("proc")), r.get("seq", 0)))
    return out


def _window(
    records: Iterable[dict[str, Any]],
    envs: set[str] | None,
    since: str | None,
    until: str | None,
    stats: dict[str, int],
) -> list[dict[str, Any]]:
    out = []
    for record in records:
        if envs is not None and record.get("env") not in envs:
            stats["excluded_other_env"] = stats.get("excluded_other_env", 0) + 1
            continue
        if (since and record["ts"] < since) or (until and record["ts"] > until):
            stats["excluded_outside_window"] = stats.get("excluded_outside_window", 0) + 1
            continue
        out.append(record)
    return out


def _attrs(record: Mapping[str, Any]) -> dict[str, Any]:
    value = record.get("attrs")
    return value if isinstance(value, dict) else {}


def _latency(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "p50": None, "p90": None, "max": None}
    ordered = sorted(values)

    def pick(q: float) -> int:
        return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]

    return {"n": len(ordered), "p50": pick(0.5), "p90": pick(0.9), "max": ordered[-1]}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _dedupe(records: list[dict[str, Any]], key: Any) -> tuple[list[dict[str, Any]], int]:
    seen: set[Any] = set()
    out, dropped = [], 0
    for record in records:
        k = key(record)
        if k in seen:
            dropped += 1
            continue
        seen.add(k)
        out.append(record)
    return out, dropped


def product_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_event[record["event"]].append(record)
    removed = 0

    def ident(record: Mapping[str, Any]) -> Any:
        return record.get("op") or (record.get("proc"), record.get("seq"))

    links, n = _dedupe(by_event["session.link"], lambda r: (ident(r), r.get("outcome")))
    removed += n
    link_counts = Counter(r.get("outcome") for r in links)
    completed = link_counts["created"] + link_counts["relinked"]
    link = {
        "attempts": completed + link_counts["refused"],
        "completed": completed,
        "created": link_counts["created"],
        "relinked": link_counts["relinked"],
        "refused": link_counts["refused"],
        "duplicate_already_linked": link_counts["duplicate"],
        "completion_rate": _rate(completed, completed + link_counts["refused"]),
        "denominator": "created + relinked + refused (duplicates excluded)",
        "refused_by_reason": dict(
            Counter(
                str(r.get("reason") or r.get("code"))
                for r in links
                if r.get("outcome") == "refused"
            )
        ),
    }

    starts, n = _dedupe(
        by_event["connect.start"],
        lambda r: r.get("run") if r.get("outcome") == "spawned" and r.get("run") else ident(r),
    )
    removed += n
    readies, n = _dedupe(by_event["connect.ready"], lambda r: r.get("run") or ident(r))
    removed += n
    ends, n = _dedupe(by_event["run.end"], lambda r: r.get("run") or ident(r))
    removed += n
    fatals, n = _dedupe(by_event["connect.fatal"], lambda r: r.get("run") or ident(r))
    removed += n
    spawned = {r.get("run") for r in starts if r.get("outcome") == "spawned" and r.get("run")}
    ready_runs = {r.get("run") for r in readies}
    ended = {r.get("run"): r for r in ends}
    refused = [r for r in starts if r.get("outcome") == "refused"]
    lost = [run for run in spawned if run not in ready_runs and run in ended]
    pending = [run for run in spawned if run not in ready_runs and run not in ended]
    ready_ms = [r["duration_ms"] for r in readies if isinstance(r.get("duration_ms"), int)]
    connect = {
        "attempts": len(starts),
        "spawned": len(spawned),
        "refused_before_spawn": len(refused),
        "refused_by_step": dict(Counter(str(_attrs(r).get("step")) for r in refused)),
        "refused_by_reason": dict(Counter(str(r.get("reason") or r.get("code")) for r in refused)),
        "ready": len(ready_runs & spawned) if spawned else len(ready_runs),
        "ended_before_ready": len(lost),
        "no_outcome_in_window": len(pending),
        "fatal_by_cause": dict(Counter(str(_attrs(r).get("cause")) for r in fatals)),
        "ready_rate": _rate(len(ready_runs & spawned), len(spawned)),
        "denominator": "spawned runs (refusals are reported by step, not in the rate)",
        "ready_latency_ms": {**_latency(ready_ms), "missing": len(readies) - len(ready_ms)},
        "run_end_status": dict(Counter(str(_attrs(r).get("status")) for r in ends)),
    }

    submits, n = _dedupe(by_event["message.submit"], lambda r: (r.get("msg"), r.get("outcome")))
    removed += n
    transitions, n = _dedupe(
        by_event["delivery.state"], lambda r: (r.get("msg"), _attrs(r).get("to_state"))
    )
    removed += n
    accepted: dict[str, dict[str, Any]] = {
        str(r["msg"]): r for r in submits if r.get("outcome") == "accepted" and r.get("msg")
    }
    states: dict[str, list[str]] = defaultdict(list)
    sent_latency: dict[str, int | None] = {}
    for record in transitions:
        msg, to = record.get("msg"), _attrs(record).get("to_state")
        if not msg or not isinstance(to, str):
            continue
        states[msg].append(to)
        if to == "sent":
            value = _attrs(record).get("latency_ms")
            sent_latency[msg] = value if isinstance(value, int) else None
    final: Counter[str] = Counter()
    per_harness: dict[str, Counter[str]] = defaultdict(Counter)
    unknown_then_sent = 0
    for msg, submit in accepted.items():
        seen = states.get(msg, [])
        if "sent" in seen:
            state = "sent"  # receipts never downgrade once sent
            if "unknown" in seen:
                unknown_then_sent += 1
        elif seen:
            # Not sent: the latest receipt state wins (queued → sending → not_sent/unknown).
            state = seen[-1] if seen[-1] in FINAL_ORDER else "other"
        else:
            state = "no_receipt"
        final[state] += 1
        per_harness[str(_attrs(submit).get("harness"))][state] += 1
    latencies = [v for m, v in sent_latency.items() if m in accepted and v is not None]
    sent_total = final["sent"]
    delivery = {
        "submitted": len(accepted),
        "denominator": "distinct accepted submissions (client message aliases)",
        "final_state": {
            "sent": final["sent"],
            "not_sent": final["not_sent"],
            "unknown": final["unknown"],
            "in_flight": final["queued"] + final["sending"],
            "no_receipt": final["no_receipt"],
            "other": final["other"],
        },
        "final_state_by_harness": {k: dict(v) for k, v in per_harness.items()},
        "unknown_later_confirmed_sent": unknown_then_sent,
        "reused_submissions": sum(1 for r in submits if r.get("outcome") == "reused"),
        "refused_submissions": sum(1 for r in submits if r.get("outcome") == "refused"),
        "sent_confirmation_latency_ms": {
            **_latency(latencies),
            "missing": sent_total - len(latencies),
            "missing_note": "confirmed after restart or without an in-process submit time",
        },
        "transitions_without_submit_in_window": len(set(states) - set(accepted)),
        "notes": [
            "sent = the native CLI accepted the message; it is not task success",
            "no_receipt: harness without a durable receipt (Claude Code) or receipt outside window",
        ],
    }
    opens, n = _dedupe(by_event["desktop.open"], ident)
    removed += n
    returns, n = _dedupe(by_event["desktop.return"], ident)
    removed += n
    desktop = {
        "open_requests": dict(Counter(str(r.get("outcome")) for r in opens)),
        "return_confirmations": len(returns),
        "end_to_end_continuation": NOT_OBSERVABLE,
        "note": "an open request or a user's return confirmation does not prove the "
        "conversation continued successfully in the desktop client",
    }
    return {
        "link": link,
        "connect": connect,
        "delivery": delivery,
        "desktop": desktop,
        "turns_ended_observed": len(by_event["turn.end"]),
        "task_completion": NOT_OBSERVABLE,
        "model_usage": {
            "model_calls": "unknown",
            "tokens": "unknown",
            "cost": "unknown",
            "reason": "native CLI internals are not observable by the bridge",
        },
        "transition_duplicates_removed": removed,
    }


def diagnostics_overview(records: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [r for r in records if r.get("level") in ("warning", "error")]
    dropped = sum(_attrs(r).get("dropped", 0) for r in records if r["event"] == "diag.dropped")
    return {
        "records": len(records),
        "by_level": dict(Counter(str(r.get("level")) for r in records)),
        "by_event": dict(Counter(r["event"] for r in records)),
        "error_codes": dict(Counter(str(r.get("code")) for r in errors if r.get("code"))),
        "failed_operations": dict(
            Counter(
                str(r.get("name"))
                for r in records
                if r["event"] == "op.end" and r.get("outcome") == "error"
            )
        ),
        "dropped_reported": dropped,
        "processes": len({r.get("proc") for r in records}),
        "code_versions": sorted({f"{r.get('ver')}+{r.get('sha')}" for r in records}),
    }


def summarize(
    state_dir: Path,
    *,
    envs: set[str] | None,
    since: str | None = None,
    until: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    stats: dict[str, dict[str, int]] = {"diag": {}, "product": {}}
    diag = _window(load(state_dir, "diag", stats["diag"]), envs, since, until, stats["diag"])
    product = _window(
        load(state_dir, "product", stats["product"]), envs, since, until, stats["product"]
    )
    settings = load_settings(state_dir, env)
    observed = [r["ts"] for r in diag + product]
    included_envs = sorted({str(r.get("env")) for r in diag + product})
    out: dict[str, Any] = {
        "schema": SUMMARY_SCHEMA,
        "generated_at": timestamp(),
        "window": {
            "requested_since": since,
            "requested_until": until,
            "first_record": min(observed) if observed else None,
            "last_record": max(observed) if observed else None,
        },
        "env_filter": sorted(envs) if envs is not None else "all",
        "envs_included": included_envs,
        "contains_test_data": "test" in included_envs,
        "samples": {
            "diagnostic_records": len(diag),
            "product_records": len(product),
            "read_stats": stats,
        },
        "product_events_enabled": settings["product_events"],
        "diagnostics_enabled": settings["diagnostics"],
        "diagnostics": diagnostics_overview(diag),
    }
    if product:
        out["product"] = product_summary(product)
    else:
        out["product"] = {
            "status": "unavailable",
            "reason": "product_events_disabled"
            if not settings["product_events"]
            else "no_product_events_in_window",
            "note": "metrics are absent, not zero",
        }
    return out


def to_csv(summary: Mapping[str, Any]) -> str:
    """Long-form rows: section, metric, value. Nested values are flattened with dots."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["section", "metric", "value"])

    def walk(section: str, prefix: str, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, inner in value.items():
                walk(section, f"{prefix}.{key}" if prefix else str(key), inner)
        elif isinstance(value, list):
            writer.writerow([section, prefix, ";".join(str(v) for v in value)])
        else:
            writer.writerow([section, prefix, "" if value is None else value])

    for key in ("schema", "generated_at", "env_filter", "envs_included", "contains_test_data"):
        walk("meta", key, summary.get(key))
    walk("meta", "window", summary.get("window"))
    walk("samples", "", summary.get("samples"))
    walk("diagnostics", "", summary.get("diagnostics"))
    walk("product", "", summary.get("product"))
    return buffer.getvalue()


def trace(
    state_dir: Path,
    *,
    op: str | None = None,
    session: str | None = None,
    run: str | None = None,
    msg: str | None = None,
) -> dict[str, Any]:
    """Records of one operation (or alias) plus those linked to it through run/message aliases."""
    records = load(state_dir, "diag") + load(state_dir, "product")
    keys = {("op", op), ("session", session), ("run", run), ("msg", msg)} - {
        ("op", None),
        ("session", None),
        ("run", None),
        ("msg", None),
    }
    if not keys:
        raise ValueError("give --op, --session, --run or --msg")
    matched = [r for r in records if any(r.get(k) == v for k, v in keys)]
    linked = {("run", r["run"]) for r in matched if r.get("run")}
    linked |= {("msg", r["msg"]) for r in matched if r.get("msg")}
    linked |= {("op", r["op"]) for r in matched if r.get("op")}
    expanded = [r for r in records if r in matched or any(r.get(k) == v for k, v in linked)]
    expanded.sort(key=lambda r: (r["ts"], str(r.get("proc")), r.get("seq", 0)))
    return {"query": {k: v for k, v in keys}, "records": expanded, "count": len(expanded)}


def _environment(state_dir: Path, profile: Mapping[str, Any], obs_stats: Any) -> dict[str, Any]:
    from harness_bridge.runtime_env import build_info, schema_revision
    from harness_bridge.workbench.store import SCHEMA_REVISION

    build = build_info()
    settings = load_settings(state_dir)
    return {
        "package_version": build["version"],
        "code_sha": build["code_sha"],
        "code_dirty": build["code_dirty"],
        "code_source": build["code_source"],
        "python": build["python"],
        "os": build["os"],
        "env": profile.get("env"),
        "env_source": profile.get("env_source"),
        "native_env": profile.get("native_env"),
        "schema_revision": schema_revision(state_dir / "workbench.sqlite3"),
        "schema_expected": SCHEMA_REVISION,
        "diagnostics_enabled": settings["diagnostics"],
        "product_events_enabled": settings["product_events"],
        "observability_stats": obs_stats,
    }


def export_bundle(
    state_dir: Path,
    out: Path | None,
    *,
    envs: set[str] | None,
    profile: Mapping[str, Any],
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Explicit user action. Writes one local zip (0600); never uploads anything."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if out is None:
        out = state_dir / DIR / "exports" / f"repobridge-diagnostics-{stamp}.zip"
    out = out.expanduser()
    if out.exists() or out.is_symlink():
        raise FileExistsError("bundle path already exists; choose a new path")
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    stats: dict[str, int] = {}
    diag = _window(load(state_dir, "diag", stats), envs, since, until, stats)
    summary = summarize(state_dir, envs=envs, since=since, until=until)
    members: dict[str, bytes] = {
        "environment.json": json.dumps(
            _environment(state_dir, profile, {"diag_read": stats}), indent=2
        ).encode(),
        "diagnostics.jsonl": "".join(
            json.dumps(r, ensure_ascii=True, separators=(",", ":")) + "\n" for r in diag
        ).encode(),
        "summary.json": json.dumps(summary, indent=2).encode(),
        "summary.csv": to_csv(summary).encode(),
    }
    manifest = {
        "format": BUNDLE_FORMAT,
        "created_at": timestamp(),
        "uploaded": False,
        "record_schema_version": schema.SCHEMA_VERSION,
        "redaction": "whitelist schema: only enums, counts, durations, stable codes and keyed "
        "local aliases; every record re-validated during export",
        "files": [
            {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in members.items()
        ],
        "diagnostic_records": len(diag),
        "contains_test_data": summary["contains_test_data"],
        "excluded": EXCLUDED_FROM_BUNDLE,
    }
    members["manifest.json"] = json.dumps(manifest, indent=2).encode()
    tmp = out.with_name(out.name + ".partial")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle, zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ("manifest.json", *[n for n in members if n != "manifest.json"]):
                info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                info.external_attr = 0o100600 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, members[name])
        try:
            os.link(tmp, out)  # exclusive: never replaces an existing bundle
        except FileExistsError:
            raise
        except OSError:
            if out.exists():
                raise FileExistsError("bundle path already exists") from None
            os.rename(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return {
        "bundle": str(out),
        "files": [f["name"] for f in manifest["files"]] + ["manifest.json"],
        "diagnostic_records": len(diag),
        "contains_test_data": summary["contains_test_data"],
        "bundle_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "uploaded": False,
    }
