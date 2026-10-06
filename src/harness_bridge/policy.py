"""Path policy, secret-path detection and redaction.

Glob semantics (documented in docs/PROTOCOL.md):

* Patterns are matched against the repository-relative POSIX path of a changed entry, anchored at
  the repository root. ``/`` is the only separator; backslashes are rejected.
* ``*`` matches any run of characters within one path segment, ``?`` one character within a
  segment. ``**`` must be a whole segment and matches zero or more segments (``src/**`` matches
  everything below ``src/``; ``**/.env`` matches ``.env`` at any depth).
* ``allowed_paths`` match case-sensitively; ``forbidden_paths`` match case-insensitively, so a
  forbidden rule cannot be bypassed by case changes on case-insensitive file systems.
  Forbidden rules take precedence over allowed rules.

These checks evaluate what the bridge observed; they cannot undo side effects an executor already
caused, and they are not a sandbox.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

_SEGMENT_FORBIDDEN = re.compile(r"[\x00\\]")


def validate_relative_path(path: str) -> str:
    """Reject absolute paths, '..' segments, empty segments, NUL and backslashes."""
    if not path:
        raise ValueError("empty path")
    if _SEGMENT_FORBIDDEN.search(path):
        raise ValueError(f"path {path!r} contains NUL or backslash")
    if path.startswith("/"):
        raise ValueError(f"path {path!r} must be relative")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"path {path!r} has empty, '.' or '..' segments")
    return path


def _translate_segment(seg: str) -> str:
    out = []
    for ch in seg:
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


@lru_cache(maxsize=512)
def _compile(pattern: str, ignore_case: bool) -> re.Pattern[str]:
    if not pattern:
        raise ValueError("empty glob pattern")
    if _SEGMENT_FORBIDDEN.search(pattern):
        raise ValueError(f"glob {pattern!r} contains NUL or backslash")
    if pattern.startswith("/"):
        raise ValueError(f"glob {pattern!r} must be relative to the repository root")
    parts = pattern.split("/")
    regex = ""
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part in ("", ".", ".."):
            raise ValueError(f"glob {pattern!r} has empty, '.' or '..' segments")
        if part == "**":
            regex += ".*" if last else "(?:[^/]+/)*"
            continue
        if "**" in part:
            raise ValueError(f"glob {pattern!r}: '**' must be a whole path segment")
        regex += _translate_segment(part) + ("" if last else "/")
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(r"\A" + regex + r"\Z", flags)


def compile_glob(pattern: str, *, ignore_case: bool = False) -> re.Pattern[str]:
    return _compile(pattern, ignore_case)


def glob_match(pattern: str, path: str, *, ignore_case: bool = False) -> bool:
    return compile_glob(pattern, ignore_case=ignore_case).match(path) is not None


# Basename patterns that indicate credential material. Matched case-insensitively at any depth.
_SECRET_BASENAMES = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.*",
    "*.token",
    "secrets.*",
    ".credentials.json",
)


def is_secret_path(path: str) -> bool:
    base = posixpath.basename(path)
    if base == ".env.example":
        return False
    return any(glob_match(p, base, ignore_case=True) for p in _SECRET_BASENAMES)


@dataclass(frozen=True)
class Violation:
    path: str
    rule: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "rule": self.rule, "detail": self.detail}


class PathPolicy:
    def __init__(self, allowed: Sequence[str], forbidden: Sequence[str]) -> None:
        self.allowed = list(allowed)
        self.forbidden = list(forbidden)
        for p in self.allowed:
            compile_glob(p)
        for p in self.forbidden:
            compile_glob(p, ignore_case=True)

    def check_path(self, path: str) -> list[Violation]:
        try:
            validate_relative_path(path)
        except ValueError as exc:
            return [Violation(path, "invalid_path", str(exc))]
        out: list[Violation] = []
        hits = [p for p in self.forbidden if glob_match(p, path, ignore_case=True)]
        if hits:
            out.append(Violation(path, "forbidden_path", f"matches forbidden pattern {hits[0]!r}"))
        elif not any(glob_match(p, path) for p in self.allowed):
            out.append(Violation(path, "outside_allowed_paths", "matches no allowed pattern"))
        if is_secret_path(path):
            out.append(Violation(path, "secret_path", "credential-like file; content withheld"))
        return out

    def check_paths(self, paths: Iterable[str]) -> list[Violation]:
        out: list[Violation] = []
        for p in paths:
            out.extend(self.check_path(p))
        return out


def symlink_escapes(link_path: str, target: str) -> bool:
    """True if a symlink at ``link_path`` (repo-relative) points outside the repository."""
    if not target or target.startswith("/") or "\x00" in target:
        return True
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(link_path), target))
    return joined == ".." or joined.startswith("../") or joined.startswith("/")


# --- redaction -------------------------------------------------------------------------------

_REDACTIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
        ),
    ),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{20,}=*")),
)
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:api[_-]?key|token|secret|password|passwd))(\s*[:=]\s*)(['\"]?)"
    r"([^\s'\"]{8,})"
)


def redact_text(text: str) -> tuple[str, int]:
    """Replace credential-looking substrings. Returns (redacted_text, replacement_count)."""
    count = 0
    for kind, pattern in _REDACTIONS:
        text, n = pattern.subn(f"[REDACTED:{kind}]", text)
        count += n

    def _assign(m: re.Match[str]) -> str:
        if m.group(4).startswith("[REDACTED"):
            return m.group(0)
        return f"{m.group(1)}{m.group(2)}{m.group(3)}[REDACTED:assignment]"

    text, n = _ASSIGNMENT.subn(_assign, text)
    count += n
    return text, count


def redact_bytes(data: bytes) -> tuple[bytes, int]:
    text, n = redact_text(data.decode("utf-8", errors="replace"))
    return text.encode("utf-8"), n
