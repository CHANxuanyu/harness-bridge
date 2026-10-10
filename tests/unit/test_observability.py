"""Observability units: whitelist schema, recorder defaults, bounded sink failure behaviour."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.errors import BridgeError
from harness_bridge.observability import Observability, schema
from harness_bridge.observability import sink as sink_module
from harness_bridge.observability.recorder import load_settings, save_settings
from harness_bridge.observability.sink import JsonlSink, files, read

SECRET = "SYNTHETICSECRET7F3A"


def lines(directory: Path, stem: str) -> list[dict[str, Any]]:
    return list(read(directory, stem))


def test_schema_never_lets_free_text_through() -> None:
    hostile: dict[str, Any] = {
        "v": 1,
        "ts": "2026-10-10T00:00:00.000Z",
        "stream": "diag",
        "level": "info",
        "event": "delivery.state",
        "component": SECRET,
        "op": f"op_{SECRET}",
        "name": f"/api/sessions?token={SECRET}",
        "session": SECRET,
        "code": f"STATE_CONFLICT {SECRET}",
        "reason": f"native_timeout {SECRET}",
        "error_type": f"Boom: {SECRET}",
        "message": SECRET,
        "path": f"/Users/x/{SECRET}",
        "outcome": SECRET,
        "attrs": {
            "harness": SECRET,
            "from_state": SECRET,
            "to_state": "sent",
            "latency_ms": SECRET,
            "prompt": SECRET,
            SECRET: 1,
        },
    }
    cleaned = schema.clean(hostile)
    assert cleaned is not None
    text = json.dumps(cleaned)
    assert SECRET not in text and "/Users" not in text and "token" not in text
    assert cleaned["attrs"] == {"harness": "other", "from_state": "other", "to_state": "sent"}
    assert cleaned["code"] == "other" and cleaned["reason"] == "other"
    assert "message" not in cleaned and "path" not in cleaned and "session" not in cleaned
    assert schema.clean({**hostile, "event": "not.an.event"}) is None


def test_recorder_defaults_aliases_and_settings(tmp_path: Path) -> None:
    obs = Observability(tmp_path, env_name="test", env={})
    assert obs.diagnostics_enabled and not obs.product_enabled
    key = tmp_path / "observability" / "alias.key"
    assert key.stat().st_mode & 0o777 == 0o600
    a1 = obs.alias("s", "ses_000000000001")
    assert a1 and a1.startswith("s_") and "ses_" not in a1
    again = Observability(tmp_path, env_name="test", env={})
    assert again.alias("s", "ses_000000000001") == a1
    other = Observability(tmp_path / "other", env_name="test", env={})
    assert other.alias("s", "ses_000000000001") != a1
    for o in (obs, again, other):
        o.close()
    off = tmp_path / "off"
    disabled = Observability(off, env={"HBRIDGE_DIAGNOSTICS": "0"})
    disabled.record("app.start", python="3.11")
    disabled.close()
    assert not off.exists()
    save_settings(tmp_path, product_events=True)
    assert load_settings(tmp_path)["product_events"] is True
    assert load_settings(tmp_path, {"HBRIDGE_PRODUCT_EVENTS": "0"})["product_events"] is False
    (tmp_path / "observability" / "settings.json").write_text("{broken")
    assert load_settings(tmp_path)["product_events"] is False


def test_record_writes_only_whitelisted_correlated_lines(tmp_path: Path) -> None:
    obs = Observability(tmp_path, env_name="test", env={"HBRIDGE_PRODUCT_EVENTS": "1"})
    sid = "ses_000000000001"
    with obs.operation("session.send", session=sid) as op:
        obs.note_message(sid, "client-1")
        obs.record("message.submit", session=sid, msg="client-1", outcome="accepted")
    obs.record("delivery.state", session=sid, msg="client-1", to_state="sent", latency_ms=5)
    obs.record("op.end", name="state", level="debug")  # below the default level
    obs.record("no.such.event")
    assert obs.flush()
    obs.close()
    diag = lines(tmp_path / "observability" / "diagnostics", "diag")
    product = lines(tmp_path / "observability" / "product", "events")
    assert [r["event"] for r in diag] == ["message.submit", "op.end", "delivery.state"]
    assert [r["event"] for r in product] == ["message.submit", "delivery.state"]
    assert {r["op"] for r in diag} == {op.op}  # late delivery joined via message alias
    assert all("client-1" not in json.dumps(r) for r in diag + product)
    assert all(r["v"] == 2 for r in diag + product)
    assert obs.invalid == 1


def test_message_identity_is_session_scoped_and_first_submit_wins(tmp_path: Path) -> None:
    obs = Observability(tmp_path, env_name="test", env={})
    a, b = "ses_00000000000a", "ses_00000000000b"
    assert obs.message_alias(a, "same") != obs.message_alias(b, "same")
    assert obs.message_alias(None, "same") is None
    with obs.operation("session.send") as first:
        obs.note_message(a, "same")
    time.sleep(0.3)
    with obs.operation("session.send"):
        obs.note_message(a, "same")  # reused submit: keeps the first start and operation
        obs.note_message(b, "same")
    latency_a = obs.message_latency(a, "same")
    latency_b = obs.message_latency(b, "same")
    assert latency_a is not None and latency_b is not None
    assert latency_a >= 300 > latency_b
    obs.record("delivery.state", session=a, msg="same", to_state="sent")
    assert obs.flush()
    obs.close()
    rows = lines(tmp_path / "observability" / "diagnostics", "diag")
    assert rows[-1]["op"] == first.op


def test_sink_rotation_retention_and_permissions(tmp_path: Path) -> None:
    directory = tmp_path / "d"
    sink = JsonlSink(directory, "x", max_bytes=400, max_files=3, max_age_seconds=3600)
    for i in range(200):
        sink.submit(json.dumps({"i": i}) + "\n")
    assert sink.flush()
    sink.close()
    names = [p.name for p in files(directory, "x")]
    assert names == ["x.2.jsonl", "x.1.jsonl", "x.jsonl"]
    assert all(p.stat().st_size <= 400 for p in files(directory, "x"))
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in files(directory, "x"))
    assert directory.stat().st_mode & 0o777 == 0o700
    kept = [r["i"] for r in read(directory, "x")]
    assert kept == list(range(kept[0], 200)) and kept[0] > 0  # oldest rotated away, no gaps
    old = directory / "x.2.jsonl"
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    (directory / "x.9.jsonl").write_text("{}\n")  # beyond max_files
    again = JsonlSink(directory, "x", max_bytes=400, max_files=3, max_age_seconds=3600)
    again.submit('{"i": 200}\n')
    assert again.flush()
    again.close()
    assert not old.exists() and not (directory / "x.9.jsonl").exists()


def test_torn_tail_is_isolated_and_counted(tmp_path: Path) -> None:
    directory = tmp_path / "d"
    directory.mkdir()
    (directory / "x.jsonl").write_text('{"i": 1}\n{"i": 2, "trunc')
    sink = JsonlSink(directory, "x")
    sink.submit('{"i": 3}\n')
    assert sink.flush()
    sink.close()
    stats: dict[str, int] = {}
    assert [r["i"] for r in read(directory, "x", stats)] == [1, 3]
    assert stats == {"lines": 3, "corrupt": 1}


def test_concurrent_writers_in_separate_processes(tmp_path: Path) -> None:
    directory = tmp_path / "d"
    script = (
        "import sys, json\n"
        "from pathlib import Path\n"
        "from harness_bridge.observability.sink import JsonlSink\n"
        "s = JsonlSink(Path(sys.argv[1]), 'x', max_bytes=20000, max_files=50)\n"
        "for i in range(400):\n"
        "    s.submit(json.dumps({'w': sys.argv[2], 'i': i, 'pad': 'p' * 40}) + '\\n')\n"
        "    s.flush(0.001) if i % 50 == 0 else None\n"
        "assert s.flush(10)\n"
        "s.close()\n"
        "print(json.dumps(s.stats))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(sink_module.__file__).resolve().parents[2])}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(directory), name],
            stdout=subprocess.PIPE,
            env=env,
            text=True,
        )
        for name in ("a", "b", "c")
    ]
    stats = [json.loads(p.communicate(timeout=60)[0]) for p in procs]
    assert all(p.returncode == 0 for p in procs)
    read_stats: dict[str, int] = {}
    rows = list(read(directory, "x", read_stats))
    assert read_stats["corrupt"] == 0
    assert len(rows) == sum(s["written"] for s in stats) == 1200
    for name in ("a", "b", "c"):
        assert [r["i"] for r in rows if r["w"] == name] == list(range(400))


def test_failures_drop_count_and_never_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file where the directory should be: every write fails (like a read-only target).
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    sink = JsonlSink(blocked / "d", "x", retry_after=0.05)
    started = time.monotonic()
    for _ in range(50):
        sink.submit("{}\n")
    assert time.monotonic() - started < 0.5
    assert sink.flush(5)
    sink.close()
    assert sink.stats["written"] == 0 and sink.stats["dropped_error"] == 50
    assert sink.stats["write_errors"] >= 1

    # Disk full mid-write, then recovery: the next line reports what was lost.
    directory = tmp_path / "full"
    real_write = os.write
    failing = {"on": True}

    def write(fd: int, data: Any) -> int:
        if failing["on"]:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(fd, data)

    monkeypatch.setattr(sink_module.os, "write", write)
    obs = Observability(directory, env_name="test", env={})
    obs.sinks["diag"].retry_after = 0.0
    obs.record("app.start", python="3.11")
    assert obs.flush()
    failing["on"] = False
    obs.record("app.stop", live_runs=0)
    assert obs.flush()
    obs.close()
    rows = lines(directory / "observability" / "diagnostics", "diag")
    assert [r["event"] for r in rows] == ["diag.dropped", "app.stop"]
    assert rows[0]["attrs"] == {"dropped": 1, "write_errors": 1}

    # Lock held elsewhere and a tiny queue: submits return immediately and count drops.
    directory = tmp_path / "busy"
    directory.mkdir()
    holder = os.open(directory / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    sink = JsonlSink(directory, "x", queue_size=1, lock_timeout=0.2, retry_after=0.05)
    started = time.monotonic()
    results = [sink.submit("{}\n") for _ in range(200)]
    assert time.monotonic() - started < 0.5
    assert not all(results) and sink.stats["dropped_full"] > 0
    fcntl.flock(holder, fcntl.LOCK_UN)
    os.close(holder)
    sink.close(timeout=1)
    assert sink.submit("{}\n") is False and sink.stats["dropped_closed"] >= 1


def test_error_fields_keep_codes_not_messages() -> None:
    from harness_bridge.observability.recorder import error_fields

    err = BridgeError(
        "STATE_CONFLICT",
        f"text {SECRET}",
        details={"reason": "delivery_unknown", "client_id": SECRET},
    )
    assert error_fields(err) == {
        "error_type": "BridgeError",
        "code": "STATE_CONFLICT",
        "reason": "delivery_unknown",
    }
    assert SECRET not in json.dumps(error_fields(RuntimeError(SECRET)))
