"""Read-only Git view of a session's working directory (status, diffstat, per-file diff).

Uses the bridge's safe git invocation (hooks/fsmonitor off, no external diff or textconv) and
``GIT_OPTIONAL_LOCKS=0`` so it never writes the user's index. Non-Git directories report so.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from harness_bridge.errors import BridgeError
from harness_bridge.workspace import git

MAX_FILES = 500
MAX_DIFF = 200_000

_XY = {
    "M": "modified",
    "T": "type changed",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "U": "unmerged",
}


def _text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def quick_branch(root: str) -> str | None:
    """Current branch from ``.git/HEAD`` without spawning git (cheap enough for every snapshot)."""
    dot_git = Path(root) / ".git"
    try:
        if dot_git.is_file():
            pointer = dot_git.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            git_dir = Path(root, pointer[len("gitdir:") :].strip())
        elif dot_git.is_dir():
            git_dir = dot_git
        else:
            return None
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/") :] or None
    if re.fullmatch(r"[0-9a-f]{40,64}", head):
        return f"detached {head[:7]}"
    return None


def repo_info(workdir: str) -> dict[str, Any] | None:
    top = git(["rev-parse", "--show-toplevel"], cwd=workdir, check=False, timeout=10)
    if top.returncode != 0:
        return None
    head = git(["rev-parse", "--verify", "--quiet", "HEAD"], cwd=workdir, check=False, timeout=10)
    branch = git(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=workdir, check=False)
    return {
        "toplevel": _text(top.stdout).strip(),
        "head": _text(head.stdout).strip() or None,
        "branch": _text(branch.stdout).strip() or None,
    }


def status(workdir: str) -> dict[str, Any]:
    try:
        info = repo_info(workdir)
    except BridgeError as exc:
        return {"git": False, "error": exc.message, "files": []}
    if info is None:
        return {"git": False, "error": None, "files": []}
    proc = git(
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=workdir,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        return {"git": True, **info, "error": _text(proc.stderr)[-400:], "files": []}
    entries = proc.stdout.split(b"\0")
    files: list[dict[str, Any]] = []
    i = 0
    while i < len(entries) and len(files) < MAX_FILES:
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = _text(entry[:2]), _text(entry[3:])
        item: dict[str, Any] = {"path": path, "index": xy[0], "worktree": xy[1]}
        if xy[0] in "RC":
            item["from"] = _text(entries[i]) if i < len(entries) else None
            i += 1
        if xy == "??":
            item["kind"] = "untracked"
        else:
            code = xy[0] if xy[0] != " " else xy[1]
            item["kind"] = _XY.get(code, "changed")
        files.append(item)
    stat = git(["diff", "HEAD", "--numstat", "-z"], cwd=workdir, check=False, timeout=30)
    numstat: dict[str, tuple[str, str]] = {}
    if stat.returncode == 0:
        for row in stat.stdout.split(b"\0"):
            parts = _text(row).split("\t")
            if len(parts) == 3 and parts[2]:
                numstat[parts[2]] = (parts[0], parts[1])
    for item in files:
        if item["path"] in numstat:
            item["added"], item["removed"] = numstat[item["path"]]
    return {
        "git": True,
        **info,
        "error": None,
        "files": files,
        "truncated": len(files) >= MAX_FILES,
    }


def diff(workdir: str, path: str) -> dict[str, Any]:
    if repo_info(workdir) is None:
        raise BridgeError("INVALID_INPUT", "working directory is not a git repository")
    tracked = git(["ls-files", "--error-unmatch", "--", path], cwd=workdir, check=False, timeout=10)
    if tracked.returncode == 0:
        proc = git(
            ["diff", "HEAD", "--no-ext-diff", "--no-textconv", "--", path],
            cwd=workdir,
            check=False,
            timeout=30,
        )
    else:
        proc = git(
            ["diff", "--no-index", "--no-ext-diff", "--no-textconv", "--", "/dev/null", path],
            cwd=workdir,
            check=False,
            timeout=30,
        )
    text = _text(proc.stdout)
    return {"path": path, "diff": text[:MAX_DIFF], "truncated": len(text) > MAX_DIFF}


def diffstat(workdir: str) -> str:
    if repo_info(workdir) is None:
        return ""
    proc = git(["diff", "HEAD", "--stat=100"], cwd=workdir, check=False, timeout=30)
    return _text(proc.stdout).strip()[-4000:]
