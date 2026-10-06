"""Artifact files: atomic writes, redacted bounded logs, manifests and size-limited summaries.

Files here are content/export views. The SQLite store remains the only state authority; a
manifest is written completely (temp file + atomic replace) before the task may become
reviewable.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from harness_bridge.policy import redact_bytes
from harness_bridge.runner import StreamCapture

SUMMARY_LIMIT_BYTES = 24 * 1024


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, obj: Any) -> bytes:
    data = (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    atomic_write_bytes(path, data)
    return data


def store_capture(path: Path, capture: StreamCapture) -> dict[str, Any]:
    """Persist a bounded stream capture after redaction. Returns its metadata."""
    data, redactions = redact_bytes(capture.render())
    atomic_write_bytes(path, data)
    meta = capture.meta()
    meta["file"] = path.name
    meta["redactions"] = redactions
    return meta


def store_bounded_file(src: Path, dest: Path, limit: int) -> dict[str, Any]:
    """Copy ``src`` to ``dest`` redacted and truncated to ``limit`` bytes (head kept)."""
    size = src.stat().st_size
    with src.open("rb") as fh:
        head = fh.read(limit)
    data, redactions = redact_bytes(head)
    if size > limit:
        data += f"\n[... truncated by hbridge: {size - limit} more bytes ...]\n".encode()
    atomic_write_bytes(dest, data)
    return {
        "file": dest.name,
        "original_bytes": size,
        "stored_bytes": len(data),
        "truncated": size > limit,
        "redactions": redactions,
    }


def tail_text(path: Path, max_bytes: int) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            data = fh.read()
    except OSError:
        return ""
    return data.decode("utf-8", "replace")


def fit_summary(summary: dict[str, Any], limit: int = SUMMARY_LIMIT_BYTES) -> dict[str, Any]:
    """Shrink a summary until it serializes under ``limit`` bytes; never drops verdict fields."""

    def size(obj: dict[str, Any]) -> int:
        return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    if size(summary) <= limit:
        return summary
    out: dict[str, Any] = json.loads(json.dumps(summary))
    out["summary_truncated"] = True
    for check in out.get("verification", {}).get("checks", []):
        for key in ("stdout_tail", "stderr_tail"):
            if isinstance(check.get(key), str):
                check[key] = check[key][-600:]
    if size(out) <= limit:
        return out
    changes = out.get("changes", {})
    if isinstance(changes.get("paths"), list):
        total = len(changes["paths"])
        changes["paths"] = changes["paths"][:20]
        changes["paths_omitted"] = max(0, total - 20)
    if size(out) <= limit:
        return out
    for check in out.get("verification", {}).get("checks", []):
        check.pop("stdout_tail", None)
        check.pop("stderr_tail", None)
    return out
