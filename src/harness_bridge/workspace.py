"""Git operations: source checks, bridge-owned worktrees, candidate snapshots and diffs.

Rules for every git command the bridge runs:

* argv lists only (never ``shell=True``), ``--`` / ``--end-of-options`` before user-controlled
  values, NUL-separated machine output;
* hooks disabled (``core.hooksPath=/dev/null``), fsmonitor off, no external diff, no textconv;
* the user's checkout (branch, index, tracked and untracked files) is never modified. The bridge
  only adds a task branch + worktree registration to the repository's shared metadata.

Snapshots use a *temporary* index file seeded from the fixed base commit, then ``git add -A`` of
the worktree, so staged, unstaged, committed-since-base and untracked (non-ignored) changes are
captured together without touching the executor's own index. Files ignored by ``.gitignore`` are
outside the observed scope and this is stated in every manifest.

A worktree isolates files and branches; it shares Git metadata with the main repository and is
not a permission sandbox.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness_bridge.errors import BridgeError
from harness_bridge.models import canonical_json, sha256_digest

ZERO_SHA = "0" * 40
GIT_SAFE_CONFIG = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.quotePath=false",
    "-c",
    "color.ui=false",
    "-c",
    "gc.auto=0",
    "-c",
    "maintenance.auto=false",
    "-c",
    "advice.detachedHead=false",
)
_STRIP_GIT_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
    "GIT_EXTERNAL_DIFF",
    "GIT_DIFF_OPTS",
)
FINGERPRINT_ALGO = "hbridge-fingerprint-v1"


def git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_GIT_ENV}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["LC_ALL"] = "C"
    if extra:
        env.update(extra)
    return env


def git(
    args: list[str],
    *,
    cwd: str | Path,
    env_extra: dict[str, str] | None = None,
    check: bool = True,
    input_bytes: bytes | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[bytes]:
    argv = ["git", *GIT_SAFE_CONFIG, *args]
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            env=git_env(env_extra),
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise BridgeError("REPO_ERROR", "git executable not found on PATH") from None
    except subprocess.TimeoutExpired:
        raise BridgeError("REPO_ERROR", f"git {args[0]} timed out after {timeout}s") from None
    if check and proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip()[-800:]
        raise BridgeError("REPO_ERROR", f"git {args[0]} failed: {msg}")
    return proc


def _out(proc: subprocess.CompletedProcess[bytes]) -> str:
    return proc.stdout.decode("utf-8", "surrogateescape").strip()


# --- source repository -------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceRepo:
    path: str
    identity: str
    base_sha: str


def inspect_source_repo(path: str, base_ref: str) -> SourceRepo:
    p = Path(path)
    if not p.is_dir():
        raise BridgeError("REPO_ERROR", f"repo.path {path!r} is not a directory")
    top = git(["rev-parse", "--show-toplevel"], cwd=p, check=False)
    if top.returncode != 0:
        raise BridgeError("REPO_ERROR", f"repo.path {path!r} is not inside a git repository")
    if os.path.realpath(_out(top)) != os.path.realpath(path):
        raise BridgeError(
            "INVALID_INPUT", "repo.path must be the top-level directory of the repository"
        )
    if git(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], cwd=p, check=False).returncode:
        raise BridgeError(
            "REPO_ERROR", "repository has no commits yet; create an initial commit first"
        )
    resolved = git(
        ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{base_ref}^{{commit}}"],
        cwd=p,
        check=False,
    )
    if resolved.returncode != 0:
        raise BridgeError("REPO_ERROR", f"base_ref {base_ref!r} does not resolve to a commit")
    common = _out(git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=p))
    status = source_status(path)
    if status:
        raise BridgeError(
            "SOURCE_REPO_DIRTY",
            "source checkout has uncommitted or untracked changes; the task would be based on "
            "the committed base only and would not include them. Commit or stash them yourself "
            "(the bridge never stashes, commits, cleans or resets your checkout).",
            details={"changed_entries": len(status)},
        )
    return SourceRepo(path=path, identity=os.path.realpath(common), base_sha=_out(resolved))


def source_status(path: str) -> list[str]:
    proc = git(
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ],
        cwd=path,
    )
    return [e for e in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if e]


def checkout_fingerprint(path: str) -> dict[str, Any]:
    """Observable state of the user's checkout, for proving the bridge did not modify it."""
    head = _out(git(["rev-parse", "HEAD"], cwd=path))
    branch = git(["symbolic-ref", "-q", "HEAD"], cwd=path, check=False)
    index = git(["ls-files", "-s", "-z"], cwd=path)
    status = source_status(path)
    return {
        "head": head,
        "branch": _out(branch) if branch.returncode == 0 else None,
        "index_digest": "sha256:" + hashlib.sha256(index.stdout).hexdigest(),
        "status": status,
    }


# --- worktrees -------------------------------------------------------------------------------


def create_worktree(repo_path: str, worktree: Path, branch: str, base_sha: str) -> None:
    if worktree.exists():
        if verify_worktree(worktree, base_sha, branch, repo_path):
            return
        raise BridgeError("WORKSPACE_ERROR", f"worktree path {worktree} exists and is not ours")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git(
        ["worktree", "add", "--quiet", "-b", branch, "--", str(worktree), base_sha],
        cwd=repo_path,
    )


def verify_worktree(worktree: Path, base_sha: str, branch: str, repo_path: str) -> bool:
    if not worktree.is_dir():
        return False
    proc = git(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=worktree, check=False
    )
    src = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=repo_path)
    if proc.returncode != 0 or os.path.realpath(_out(proc)) != os.path.realpath(_out(src)):
        return False
    ref = git(["symbolic-ref", "-q", "HEAD"], cwd=worktree, check=False)
    return ref.returncode == 0 and _out(ref) == f"refs/heads/{branch}"


# --- snapshots -------------------------------------------------------------------------------


@dataclass
class Change:
    path: str
    status: str  # A, M, D, R, C, T
    old_path: str | None
    old_mode: str
    new_mode: str
    old_blob: str
    new_blob: str
    score: int | None = None
    size: int | None = None
    binary: bool = False
    lines_added: int | None = None
    lines_deleted: int | None = None
    symlink_target: str | None = None

    @property
    def entry_type(self) -> str:
        mode = self.new_mode if self.status != "D" else self.old_mode
        return {
            "120000": "symlink",
            "160000": "gitlink",
            "100755": "executable",
            "100644": "file",
        }.get(mode, f"mode:{mode}")

    def touched_paths(self) -> list[str]:
        return [p for p in (self.old_path, self.path) if p]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "old_path": self.old_path,
            "status": self.status,
            "old_mode": self.old_mode,
            "new_mode": self.new_mode,
            "entry_type": self.entry_type,
            "new_blob": None if self.new_blob == ZERO_SHA else self.new_blob,
            "size": self.size,
            "binary": self.binary,
            "lines_added": self.lines_added,
            "lines_deleted": self.lines_deleted,
        }


@dataclass
class Snapshot:
    base_sha: str
    tree_sha: str
    changes: list[Change] = field(default_factory=list)

    def fingerprint(self, *, task_version: int, verifier_digest: str) -> str:
        return sha256_digest(
            {
                "algo": FINGERPRINT_ALGO,
                "base_sha": self.base_sha,
                "tree_sha": self.tree_sha,
                "task_version": task_version,
                "verifier_digest": verifier_digest,
            }
        )


def _split_z(data: bytes) -> list[str]:
    return data.decode("utf-8", "surrogateescape").split("\0")


def _parse_raw(data: bytes) -> list[Change]:
    tokens = _split_z(data)
    changes: list[Change] = []
    i = 0
    while i < len(tokens):
        head = tokens[i]
        if not head:
            i += 1
            continue
        if not head.startswith(":"):
            raise BridgeError("REPO_ERROR", f"unexpected diff-tree output token {head[:40]!r}")
        old_mode, new_mode, old_blob, new_blob, status_full = head[1:].split(" ")
        status = status_full[0]
        score = int(status_full[1:]) if len(status_full) > 1 else None
        if status in ("R", "C"):
            old_path, path = tokens[i + 1], tokens[i + 2]
            i += 3
        else:
            old_path, path = None, tokens[i + 1]
            i += 2
        changes.append(
            Change(path, status, old_path, old_mode, new_mode, old_blob, new_blob, score)
        )
    return changes


def _parse_numstat(data: bytes) -> dict[str, tuple[int | None, int | None, bool]]:
    tokens = _split_z(data)
    out: dict[str, tuple[int | None, int | None, bool]] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok:
            i += 1
            continue
        added, deleted, rest = tok.split("\t", 2)
        if rest == "":  # rename/copy: paths follow as separate tokens
            path = tokens[i + 2]
            i += 3
        else:
            path = rest
            i += 1
        binary = added == "-" and deleted == "-"
        out[path] = (
            None if binary else int(added),
            None if binary else int(deleted),
            binary,
        )
    return out


def take_snapshot(worktree: Path, base_sha: str, scratch_dir: Path) -> Snapshot:
    """Capture the full candidate state of ``worktree`` relative to ``base_sha``."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    fd, index_path = tempfile.mkstemp(prefix="snapshot-index-", dir=str(scratch_dir))
    os.close(fd)
    os.unlink(index_path)  # git must create the index itself
    env = {"GIT_INDEX_FILE": index_path}
    try:
        git(["read-tree", base_sha], cwd=worktree, env_extra=env)
        git(["add", "-A", "--", "."], cwd=worktree, env_extra=env)
        tree = _out(git(["write-tree"], cwd=worktree, env_extra=env))
    finally:
        for suffix in ("", ".lock"):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(index_path + suffix)
    diff_opts = ["-r", "-z", "-M", "--no-ext-diff", "--no-textconv"]
    raw = git(["diff-tree", *diff_opts, "--raw", "--no-abbrev", base_sha, tree], cwd=worktree)
    changes = _parse_raw(raw.stdout)
    numstat = _parse_numstat(
        git(["diff-tree", *diff_opts, "--numstat", base_sha, tree], cwd=worktree).stdout
    )
    blobs = [c.new_blob for c in changes if c.new_blob != ZERO_SHA and c.new_mode != "160000"]
    sizes: dict[str, int] = {}
    if blobs:
        batch = git(
            ["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
            cwd=worktree,
            input_bytes=("\n".join(blobs) + "\n").encode(),
        )
        for line in batch.stdout.decode().splitlines():
            parts = line.split(" ")
            if len(parts) == 3 and parts[1] == "blob":
                sizes[parts[0]] = int(parts[2])
    for c in changes:
        stats = numstat.get(c.path)
        if stats:
            c.lines_added, c.lines_deleted, c.binary = stats
        c.size = sizes.get(c.new_blob)
        if c.new_mode == "120000" and c.new_blob != ZERO_SHA:
            target = git(["cat-file", "blob", c.new_blob], cwd=worktree).stdout
            c.symlink_target = target.decode("utf-8", "surrogateescape")
    return Snapshot(base_sha=base_sha, tree_sha=tree, changes=changes)


def write_diff(
    worktree: Path, base_sha: str, tree_sha: str, paths: list[str], dest: Path
) -> dict[str, Any]:
    """Write the textual patch for ``paths`` (binary files summarized, never inlined)."""
    if not paths:
        dest.write_bytes(b"")
        return {"bytes": 0}
    args = ["diff-tree", "-r", "-p", "-M", "--no-ext-diff", "--no-textconv", "--no-color"]
    args += [base_sha, tree_sha, "--", *paths]
    with dest.open("wb") as fh:
        proc = subprocess.run(
            ["git", *GIT_SAFE_CONFIG, *args],
            cwd=str(worktree),
            env=git_env({"GIT_LITERAL_PATHSPECS": "1"}),
            stdout=fh,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
    if proc.returncode != 0:
        raise BridgeError("REPO_ERROR", "git diff-tree -p failed")
    return {"bytes": dest.stat().st_size}


def snapshot_summary(snapshot: Snapshot) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for c in snapshot.changes:
        counts[c.status] = counts.get(c.status, 0) + 1
    return {
        "total": len(snapshot.changes),
        "by_status": dict(sorted(counts.items())),
        "lines_added": sum(c.lines_added or 0 for c in snapshot.changes),
        "lines_deleted": sum(c.lines_deleted or 0 for c in snapshot.changes),
        "binary_files": sum(1 for c in snapshot.changes if c.binary),
    }


def snapshot_digest_material(snapshot: Snapshot) -> str:
    return canonical_json([c.to_dict() for c in snapshot.changes])
