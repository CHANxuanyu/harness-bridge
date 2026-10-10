"""Event dictionary and whitelist validation for diagnostic and product records.

A record is built only from fields declared here. Every value is a bool, a bounded number, a
member of a closed enumeration, a stable error code, or a keyed alias computed by the recorder.
Free text cannot pass: an undeclared field is dropped and an invalid value becomes ``"other"``
(enumerations) or is dropped. This is the privacy boundary; redaction regexes are not relied on.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from harness_bridge.errors import _CODES

SCHEMA_VERSION = 1
MAX_RECORD_BYTES = 2048
MAX_LIST = 8
MAX_MS = 100_000_000  # ~27 h
MAX_COUNT = 1_000_000_000

LEVELS = ("debug", "info", "warning", "error")
LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}
ENVS = frozenset({"prod", "dev", "test"})
HARNESS = frozenset({"claude-code", "codex"})
DELIVERY_STATES = frozenset({"queued", "sending", "sent", "not_sent", "unknown"})

# Stable machine reasons used by the workbench (BridgeError.details["reason"], delivery reasons,
# discovery completeness reasons). Anything else is recorded as "other".
REASONS = frozenset(
    {
        "candidate_expired",
        "client_id_conflict",
        "connection_ended",
        "connection_unavailable",
        "cursor_expired",
        "delivery_unknown",
        "directory_missing",
        "directory_unreadable",
        "environment_changed",
        "environment_refused",
        "external_confirmation_required",
        "history_snapshot_limit",
        "invalid_cursor_combination",
        "invalid_filter",
        "invalid_limit",
        "invalid_native_metadata",
        "local_only",
        "local_writer_busy",
        "malformed_native_record",
        "message_not_found",
        "native_capability_unsupported",
        "native_exit_unconfirmed",
        "native_file_limit",
        "native_history_invalid",
        "native_history_missing",
        "native_identity_changed",
        "native_index_only",
        "native_page_limit",
        "native_process_exited",
        "native_protocol_unsupported",
        "native_read_failed",
        "native_request_failed",
        "native_request_rejected",
        "native_timeout",
        "native_transport_error",
        "native_writer_busy",
        "needs_release",
        "project_archived",
        "resume_required",
        "scan_limit",
        "symlink_skipped",
        "unlinked",
        "unsupported_source",
    }
)
ERROR_CODES = frozenset(_CODES)

# Operation names (one per HTTP route family; never the raw path or query).
OP_NAMES = frozenset(
    {
        "state",
        "stream",
        "history.discover",
        "history.preview",
        "session.detail",
        "session.output",
        "session.activity",
        "session.delivery",
        "session.changes",
        "session.diff",
        "session.conversation",
        "session.files",
        "prefs.set",
        "native.title",
        "native.appearance",
        "native.pick_folder",
        "native.open_url",
        "native.pick_files",
        "catalog.refresh",
        "dev.snapshot",
        "dev.reload",
        "dev.resize",
        "harnesses.refresh",
        "project.add",
        "project.archive",
        "project.reveal",
        "session.create",
        "session.link",
        "session.input",
        "session.resize",
        "session.start",
        "session.send",
        "session.settings",
        "session.attachments",
        "session.interrupt",
        "session.permission",
        "session.view",
        "session.desktop_open",
        "session.desktop_return",
        "session.stop",
        "session.rename",
        "session.archive",
        "session.unlink",
        "session.unarchive",
        "session.handoff_draft",
        "session.handoff",
        "unknown",
    }
)

_ALIAS = re.compile(r"[psrm]_[0-9a-f]{10}")
_OP = re.compile(r"op_[0-9a-f]{12}")
_PROC = re.compile(r"p_[0-9a-f]{8}")
_VERSION = re.compile(r"[0-9A-Za-z.+-]{1,32}")
_SHA = re.compile(r"[0-9a-f]{12}|unknown")
_ERROR_TYPE = re.compile(r"[A-Z][A-Za-z0-9_]{0,47}")
_TS = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z")

Validator = Callable[[Any], Any]
_DROP = object()


def enum(*values: str) -> Validator:
    allowed = frozenset(values)
    return lambda v: v if isinstance(v, str) and v in allowed else "other"


def enum_of(allowed: frozenset[str]) -> Validator:
    return lambda v: v if isinstance(v, str) and v in allowed else "other"


def optional_enum(*values: str) -> Validator:
    inner = enum(*values)
    return lambda v: None if v is None else inner(v)


def count(v: Any) -> Any:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= MAX_COUNT:
        return _DROP
    return v


def ms(v: Any) -> Any:
    if isinstance(v, bool) or not isinstance(v, int | float) or v != v or v < 0:
        return _DROP
    return min(round(v), MAX_MS)


def boolean(v: Any) -> Any:
    return v if isinstance(v, bool) or v is None else _DROP


def code(v: Any) -> Any:
    return v if isinstance(v, str) and v in ERROR_CODES else "other"


def reason(v: Any) -> Any:
    if v is None:
        return None
    return v if isinstance(v, str) and v in REASONS else "other"


def reasons(v: Any) -> Any:
    if not isinstance(v, list | tuple):
        return _DROP
    return sorted({reason(x) for x in v[:MAX_LIST]} - {None})


def pattern(rx: re.Pattern[str]) -> Validator:
    return lambda v: v if isinstance(v, str) and rx.fullmatch(v) else _DROP


def delivery_state(v: Any) -> Any:
    if v is None:
        return None
    return v if isinstance(v, str) and v in DELIVERY_STATES else "other"


@dataclass(frozen=True)
class EventSpec:
    component: str
    level: str
    product: bool
    description: str
    outcomes: tuple[str, ...] = ()
    attrs: Mapping[str, Validator] = field(default_factory=dict)


_HARNESS = enum_of(HARNESS)
_KIND = enum("new", "resume")
_TRANSPORT = enum("pty", "structured")

EVENTS: dict[str, EventSpec] = {
    # --- diagnostics only -------------------------------------------------------------------
    "app.start": EventSpec(
        "app",
        "info",
        False,
        "Workbench constructed: environment, build identity, schema and observability settings.",
        attrs={
            "env_source": enum("explicit", "default"),
            "native_env": enum("shared", "isolated", "custom"),
            "code_source": enum("git-checkout", "installed"),
            "code_dirty": boolean,
            "schema": count,
            "schema_expected": count,
            "python": pattern(_VERSION),
            "os": enum("Darwin", "Linux", "Windows"),
            "diagnostics": boolean,
            "product_events": boolean,
            "alias_stable": boolean,
        },
    ),
    "app.stop": EventSpec(
        "app",
        "info",
        False,
        "Workbench closing: uptime, live runs stopped, observability drop counters.",
        attrs={
            "uptime_ms": ms,
            "live_runs": count,
            "dropped": count,
            "write_errors": count,
        },
    ),
    "op.end": EventSpec(
        "http",
        "info",
        False,
        "One HTTP/service operation finished (route family name, outcome, duration, error code).",
        outcomes=("ok", "error"),
        attrs={"http_status": count},
    ),
    "history.discover": EventSpec(
        "history",
        "info",
        False,
        "Scoped native discovery returned (counts and completeness reasons only).",
        outcomes=("ok", "error"),
        attrs={
            "harness": _HARNESS,
            "items": count,
            "completeness": enum("complete", "partial"),
            "reasons": reasons,
            "paged": boolean,
        },
    ),
    "history.read": EventSpec(
        "history",
        "info",
        False,
        "Preview or conversation history page read (page state, counts, completeness reasons).",
        outcomes=("ok", "error"),
        attrs={
            "source": enum("preview", "conversation"),
            "page_state": enum("ready", "empty", "partial", "unavailable"),
            "items": count,
            "reasons": reasons,
        },
    ),
    "diag.dropped": EventSpec(
        "diag",
        "warning",
        False,
        "Records that could not be written earlier (queue full, write error, invalid record).",
        attrs={"dropped": count, "write_errors": count},
    ),
    # --- diagnostics and (when enabled) product events --------------------------------------
    "session.link": EventSpec(
        "link",
        "info",
        True,
        "Link an outside-created native session. created/relinked = completed association.",
        outcomes=("created", "relinked", "duplicate", "refused"),
        attrs={"harness": _HARNESS},
    ),
    "session.unlink": EventSpec(
        "link",
        "info",
        True,
        "Remove an association (native history preserved).",
        outcomes=("ok", "refused"),
        attrs={"harness": _HARNESS},
    ),
    "connect.start": EventSpec(
        "run",
        "info",
        True,
        "Explicit connect/resume request: spawned, or refused at a named step before/at spawn.",
        outcomes=("spawned", "refused"),
        attrs={
            "harness": _HARNESS,
            "kind": _KIND,
            "transport": _TRANSPORT,
            "linked": boolean,
            "step": enum(
                "request",
                "link_check",
                "external_confirmation",
                "preflight",
                "directory",
                "admission",
                "spawn",
            ),
        },
    ),
    "connect.ready": EventSpec(
        "run",
        "info",
        True,
        "The native connection first became usable (structured ready / first terminal output).",
        attrs={"harness": _HARNESS, "kind": _KIND, "transport": _TRANSPORT},
    ),
    "connect.fatal": EventSpec(
        "run",
        "warning",
        True,
        "The bridge ended a connection because of a native protocol/identity failure.",
        attrs={
            "harness": _HARNESS,
            "cause": enum("native_identity_changed", "native_protocol"),
            "ready": boolean,
        },
    ),
    "run.end": EventSpec(
        "run",
        "info",
        True,
        "A native process run ended (status and exit class; never stderr or failure text).",
        attrs={
            "harness": _HARNESS,
            "transport": _TRANSPORT,
            "status": enum("exited", "failed", "stopped", "interrupted", "unconfirmed"),
            "exit_class": enum("zero", "nonzero", "signal", "unknown"),
            "ready": boolean,
            "released_for": optional_enum("desktop", "view"),
            "stop_requested": boolean,
        },
    ),
    "turn.end": EventSpec(
        "run",
        "info",
        True,
        "The current turn ended (native completion, interrupt or failed submit). Not task success.",
        attrs={"harness": _HARNESS},
    ),
    "message.submit": EventSpec(
        "delivery",
        "info",
        True,
        "A conversation send request: accepted by the bridge, reused (same client id) or refused.",
        outcomes=("accepted", "reused", "refused"),
        attrs={"harness": _HARNESS, "attachments": count, "linked": boolean},
    ),
    "delivery.state": EventSpec(
        "delivery",
        "info",
        True,
        "A durable delivery receipt changed state. sent = native CLI accepted, not task success.",
        attrs={
            "harness": _HARNESS,
            "from_state": delivery_state,
            "to_state": delivery_state,
            "evidence": enum("native_protocol", "native_history_client_id", "connection_ended"),
            "latency_ms": ms,
        },
    ),
    "desktop.open": EventSpec(
        "desktop",
        "info",
        True,
        "Official desktop open requested. Not proof that the conversation continued there.",
        outcomes=("requested", "acknowledged", "not_acknowledged", "failed", "refused"),
        attrs={"harness": _HARNESS, "released": boolean},
    ),
    "desktop.return": EventSpec(
        "desktop",
        "info",
        True,
        "User confirmed outside use ended. Not proof of end-to-end continuation.",
        attrs={"harness": _HARNESS, "had_hold": boolean},
    ),
}

COMPONENTS = frozenset(spec.component for spec in EVENTS.values())

# Top-level fields any record may carry, beyond event-specific ``attrs``.
COMMON: dict[str, Validator] = {
    "op": pattern(_OP),
    "name": enum_of(OP_NAMES),
    "session": pattern(_ALIAS),
    "run": pattern(_ALIAS),
    "msg": pattern(_ALIAS),
    "project": pattern(_ALIAS),
    "duration_ms": ms,
    "code": code,
    "reason": reason,
    "error_type": pattern(_ERROR_TYPE),
}
# Filled by the recorder only.
ENVELOPE: dict[str, Validator] = {
    "v": lambda v: v if v == SCHEMA_VERSION else _DROP,
    "ts": pattern(_TS),
    "seq": count,
    "proc": pattern(_PROC),
    "stream": enum("diag", "product"),
    "env": enum_of(ENVS),
    "ver": pattern(_VERSION),
    "sha": pattern(_SHA),
    "level": enum_of(frozenset(LEVELS)),
    "component": enum_of(COMPONENTS),
    "event": enum_of(frozenset(EVENTS)),
    "outcome": lambda v: v if isinstance(v, str) else _DROP,  # checked per event below
    "truncated": boolean,
}


def clean(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Whitelist one record. Returns None when it cannot be a valid record at all."""
    event = record.get("event")
    spec = EVENTS.get(event) if isinstance(event, str) else None
    if spec is None:
        return None
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key == "attrs":
            continue
        check = ENVELOPE.get(key) or COMMON.get(key)
        if check is None or value is None:
            continue
        cleaned = check(value)
        if cleaned is not _DROP:
            out[key] = cleaned
    if "outcome" in out and out["outcome"] not in (spec.outcomes or ()):
        out["outcome"] = "other"
    raw_attrs = record.get("attrs")
    attrs: dict[str, Any] = {}
    if isinstance(raw_attrs, Mapping):
        for key, value in raw_attrs.items():
            check = spec.attrs.get(key) if isinstance(key, str) else None
            if check is None:
                continue
            cleaned = check(value)
            if cleaned is not _DROP:
                attrs[key] = cleaned
    if attrs:
        out["attrs"] = attrs
    for required in ("v", "ts", "stream", "event", "level"):
        if required not in out:
            return None
    return out


def describe_events() -> list[dict[str, Any]]:
    """Machine-readable event dictionary (``hbridge diag events``)."""
    return [
        {
            "event": name,
            "component": spec.component,
            "level": spec.level,
            "product_event": spec.product,
            "outcomes": list(spec.outcomes),
            "attrs": sorted(spec.attrs),
            "description": spec.description,
        }
        for name, spec in EVENTS.items()
    ]
