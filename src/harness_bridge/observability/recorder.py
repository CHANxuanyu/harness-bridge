"""Per-state-directory recorder: operation correlation, keyed aliases and the two local streams.

* ``diag`` (fault diagnostics) — on by default; records at or above ``HBRIDGE_DIAG_LEVEL``
  (default ``info``).
* ``product`` (product events) — off by default; only events marked ``product`` in the
  dictionary, only when ``product_events`` is enabled in settings or ``HBRIDGE_PRODUCT_EVENTS=1``.

Local identifiers (project/session/run/message client IDs) are replaced by
``HMAC-SHA256(alias.key, kind:id)[:10]``. The key is random per state directory, 0600, and is
never exported, so aliases correlate records on this machine without being a cross-user ID.
An operation ID (``op_…``) is random per HTTP/service operation and is distinct from native
protocol request IDs. ``record`` never raises and never blocks the caller.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import hmac
import itertools
import json
import os
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from harness_bridge import __version__
from harness_bridge.observability import schema
from harness_bridge.observability.sink import JsonlSink

DIR = "observability"
DEFAULTS = {"diagnostics": True, "product_events": False}
ENV_SWITCHES = {"diagnostics": "HBRIDGE_DIAGNOSTICS", "product_events": "HBRIDGE_PRODUCT_EVENTS"}
LIMITS = {
    "diag": {"max_bytes": 1 << 20, "max_files": 5, "max_age_seconds": 14 * 86400},
    "product": {"max_bytes": 1 << 20, "max_files": 3, "max_age_seconds": 30 * 86400},
}
STREAM_PATHS = {"diag": ("diagnostics", "diag"), "product": ("product", "events")}

_current_op: contextvars.ContextVar[str | None] = contextvars.ContextVar("rb_op", default=None)


def current_op() -> str | None:
    return _current_op.get()


def new_op_id() -> str:
    return "op_" + secrets.token_hex(6)


def timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _switch(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("1", "true", "on", "yes"):
        return True
    if lowered in ("0", "false", "off", "no"):
        return False
    return None


def load_settings(state_dir: Path, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Defaults < settings.json < environment switches. Unreadable file → safe defaults."""
    settings: dict[str, Any] = dict(DEFAULTS)
    sources = dict.fromkeys(DEFAULTS, "default")
    path = state_dir / DIR / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        for key in DEFAULTS:
            if isinstance(data.get(key), bool):
                settings[key], sources[key] = data[key], "settings"
    for key, var in ENV_SWITCHES.items():
        value = _switch((env or {}).get(var))
        if value is not None:
            settings[key], sources[key] = value, "environment"
    settings["sources"] = sources
    return settings


def save_settings(state_dir: Path, **changes: bool) -> dict[str, Any]:
    """Explicit user action (``hbridge diag config``): write settings.json atomically, 0600."""
    root = state_dir / DIR
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = {k: v for k, v in load_settings(state_dir).items() if k in DEFAULTS}
    current.update({k: bool(v) for k, v in changes.items() if k in DEFAULTS})
    tmp = root / "settings.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(current, handle)
    os.replace(tmp, root / "settings.json")
    return current


class _Bounded(OrderedDict[str, Any]):
    def __init__(self, limit: int = 2000) -> None:
        super().__init__()
        self.limit = limit

    def put(self, key: str, value: Any) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.limit:
            self.popitem(last=False)


@dataclass
class OpHandle:
    op: str
    outcome: str = "ok"
    code: str | None = None
    reason: str | None = None
    error_type: str | None = None
    http_status: int | None = None

    def fail(self, exc: BaseException, http_status: int | None = None) -> None:
        self.outcome = "error"
        self.http_status = http_status
        fields = error_fields(exc)
        self.code, self.reason, self.error_type = (
            fields.get("code"),
            fields.get("reason"),
            fields.get("error_type"),
        )


def error_fields(exc: BaseException) -> dict[str, Any]:
    """Stable code/reason/type only. The message and details are never recorded."""
    from harness_bridge.errors import BridgeError

    out: dict[str, Any] = {"error_type": type(exc).__name__}
    if isinstance(exc, BridgeError):
        out["code"] = exc.code
        reason = exc.details.get("reason") if isinstance(exc.details, dict) else None
        if reason is None and isinstance(exc.details, dict) and exc.details.get("needs_release"):
            reason = "needs_release"
        out["reason"] = reason
    else:
        out["code"] = "INTERNAL_ERROR"
    return out


class Observability:
    def __init__(
        self,
        state_dir: Path,
        *,
        env_name: str = "prod",
        env: Mapping[str, str] | None = None,
        limits: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        from harness_bridge.runtime_env import build_info, short_sha

        self.state_dir = state_dir
        self.root = state_dir / DIR
        self.settings = load_settings(state_dir, env)
        self.env_name = env_name if env_name in schema.ENVS else "prod"
        level = ((env or {}).get("HBRIDGE_DIAG_LEVEL") or "info").strip().lower()
        self.min_rank = schema.LEVEL_RANK.get(level, schema.LEVEL_RANK["info"])
        self.build = build_info()
        self.sha = short_sha(self.build)
        self.proc = "p_" + secrets.token_hex(4)
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self._msg_ops = _Bounded()
        self._msg_t0 = _Bounded()
        self._run_ops = _Bounded()
        self._run_t0 = _Bounded()
        self._ready: _Bounded = _Bounded()
        self.invalid = 0
        self.started = time.monotonic()
        self.sinks: dict[str, JsonlSink] = {}
        any_enabled = self.settings["diagnostics"] or self.settings["product_events"]
        self._key, self.alias_stable = self._load_key() if any_enabled else (b"", False)
        merged = {k: {**LIMITS[k], **dict((limits or {}).get(k, {}))} for k in LIMITS}
        for stream, enabled in (
            ("diag", self.settings["diagnostics"]),
            ("product", self.settings["product_events"]),
        ):
            if enabled:
                sub, stem = STREAM_PATHS[stream]
                self.sinks[stream] = JsonlSink(
                    self.root / sub,
                    stem,
                    drop_record=functools.partial(self._drop_line, stream),
                    **merged[stream],
                )

    @property
    def diagnostics_enabled(self) -> bool:
        return "diag" in self.sinks

    @property
    def product_enabled(self) -> bool:
        return "product" in self.sinks

    # --- aliases -------------------------------------------------------------------------------

    def _load_key(self) -> tuple[bytes, bool]:
        path = self.root / "alias.key"
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                text = path.read_text(encoding="ascii").strip()
                if len(text) == 64:
                    return bytes.fromhex(text), True
                raise ValueError("bad alias key") from None
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                key = secrets.token_hex(32)
                handle.write(key)
            return bytes.fromhex(key), True
        except (OSError, ValueError):
            # Read-only or damaged: aliases still hide IDs, but are not stable across restarts.
            return secrets.token_bytes(32), False

    def alias(self, kind: str, raw: Any) -> str | None:
        if not isinstance(raw, str) or not raw or kind not in ("p", "s", "r", "m"):
            return None
        digest = hmac.new(self._key, f"{kind}:{raw}".encode(), sha256).hexdigest()
        return f"{kind}_{digest[:10]}"

    # --- bookkeeping for correlation and latency -------------------------------------------------

    def note_message(self, client_id: str) -> None:
        try:
            alias = self.alias("m", client_id)
            if alias is None:
                return
            with self._lock:
                self._msg_t0.put(alias, time.monotonic())
                op = _current_op.get()
                if op:
                    self._msg_ops.put(alias, op)
        except Exception:
            self.invalid += 1

    def message_latency(self, client_id: str) -> float | None:
        alias = self.alias("m", client_id)
        with self._lock:
            t0 = self._msg_t0.get(alias) if alias else None
        return None if t0 is None else (time.monotonic() - t0) * 1000

    def note_run(self, run_id: str) -> None:
        try:
            alias = self.alias("r", run_id)
            if alias is None:
                return
            with self._lock:
                self._run_t0.put(alias, time.monotonic())
                op = _current_op.get()
                if op:
                    self._run_ops.put(alias, op)
        except Exception:
            self.invalid += 1

    def run_elapsed(self, run_id: str) -> float | None:
        alias = self.alias("r", run_id)
        with self._lock:
            t0 = self._run_t0.get(alias) if alias else None
        return None if t0 is None else (time.monotonic() - t0) * 1000

    def first_ready(self, run_id: str) -> bool:
        alias = self.alias("r", run_id)
        if alias is None:
            return False
        with self._lock:
            if alias in self._ready:
                return False
            self._ready.put(alias, True)
            return True

    def was_ready(self, run_id: str) -> bool:
        alias = self.alias("r", run_id)
        with self._lock:
            return bool(alias and alias in self._ready)

    # --- records --------------------------------------------------------------------------------

    def record(
        self,
        event: str,
        *,
        level: str | None = None,
        op: str | None = None,
        name: str | None = None,
        project: str | None = None,
        session: str | None = None,
        run: str | None = None,
        msg: str | None = None,
        outcome: str | None = None,
        duration_ms: float | None = None,
        code: str | None = None,
        reason: str | None = None,
        error_type: str | None = None,
        **attrs: Any,
    ) -> None:
        try:
            spec = schema.EVENTS.get(event)
            if spec is None:
                self.invalid += 1
                return
            level = level if level in schema.LEVEL_RANK else spec.level
            assert level is not None
            targets = []
            if "diag" in self.sinks and schema.LEVEL_RANK[level] >= self.min_rank:
                targets.append("diag")
            if "product" in self.sinks and spec.product:
                targets.append("product")
            if not targets:
                return
            run_alias, msg_alias = self.alias("r", run), self.alias("m", msg)
            op = op or _current_op.get()
            if op is None:
                with self._lock:
                    op = (self._msg_ops.get(msg_alias) if msg_alias else None) or (
                        self._run_ops.get(run_alias) if run_alias else None
                    )
            base = {
                "v": schema.SCHEMA_VERSION,
                "ts": timestamp(),
                "seq": next(self._seq),
                "proc": self.proc,
                "env": self.env_name,
                "ver": __version__,
                "sha": self.sha,
                "level": level,
                "component": spec.component,
                "event": event,
                "op": op,
                "name": name,
                "project": self.alias("p", project),
                "session": self.alias("s", session),
                "run": run_alias,
                "msg": msg_alias,
                "outcome": outcome,
                "duration_ms": duration_ms,
                "code": code,
                "reason": reason,
                "error_type": error_type,
                "attrs": attrs,
            }
            for stream in targets:
                line = self._line({**base, "stream": stream})
                if line is None:
                    self.invalid += 1
                else:
                    self.sinks[stream].submit(line)
        except Exception:
            self.invalid += 1

    @staticmethod
    def _line(record: Mapping[str, Any]) -> str | None:
        cleaned = schema.clean(record)
        if cleaned is None:
            return None
        text = json.dumps(cleaned, ensure_ascii=True, separators=(",", ":"))
        if len(text) >= schema.MAX_RECORD_BYTES:
            cleaned.pop("attrs", None)
            cleaned["truncated"] = True
            text = json.dumps(cleaned, ensure_ascii=True, separators=(",", ":"))
            if len(text) >= schema.MAX_RECORD_BYTES:
                return None
        return text + "\n"

    def _drop_line(self, stream: str, counts: Mapping[str, int]) -> str | None:
        if stream != "diag":
            return None
        return self._line(
            {
                "v": schema.SCHEMA_VERSION,
                "ts": timestamp(),
                "seq": next(self._seq),
                "proc": self.proc,
                "stream": "diag",
                "env": self.env_name,
                "ver": __version__,
                "sha": self.sha,
                "level": "warning",
                "component": "diag",
                "event": "diag.dropped",
                "attrs": dict(counts),
            }
        )

    @contextlib.contextmanager
    def operation(
        self, name: str, *, session: str | None = None, level: str = "info"
    ) -> Iterator[OpHandle]:
        handle = OpHandle(new_op_id())
        token = _current_op.set(handle.op)
        started = time.monotonic()
        try:
            yield handle
        except BaseException as exc:
            handle.fail(exc)
            raise
        finally:
            _current_op.reset(token)
            failed = handle.outcome != "ok"
            self.record(
                "op.end",
                level="warning" if failed else level,
                op=handle.op,
                name=name,
                session=session,
                outcome=handle.outcome,
                duration_ms=(time.monotonic() - started) * 1000,
                code=handle.code,
                reason=handle.reason,
                error_type=handle.error_type,
                http_status=handle.http_status,
            )

    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {"invalid": self.invalid}
        for stream, sink in self.sinks.items():
            out[stream] = dict(sink.stats)
        return out

    def dropped(self) -> int:
        return sum(s.dropped() for s in self.sinks.values()) + self.invalid

    def write_errors(self) -> int:
        return sum(s.stats["write_errors"] for s in self.sinks.values())

    def flush(self, timeout: float = 2.0) -> bool:
        return all(s.flush(timeout) for s in self.sinks.values())

    def close(self, timeout: float = 2.0) -> None:
        for sink in self.sinks.values():
            sink.close(timeout)
