"""Local distribution checks use synthetic wheels, isolated Git and no model/network."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import pytest
from scripts.build_release import build
from scripts.verify_release import verify


@pytest.fixture
def release_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "release source with spaces"
    root.mkdir()
    project = Path(__file__).resolve().parents[2]
    for name in ("plugins", ".agents", "scripts"):
        shutil.copytree(project / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("marketplace.json", "LICENSE", "NOTICE"):
        shutil.copyfile(project / name, root / name)
    (root / "pyproject.toml").write_text('[project]\nversion = "0.1.0.dev1"\n')
    source = root / "src/harness_bridge"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text('"""Synthetic release module."""\n')
    docs = root / "docs"
    docs.mkdir()
    for name in ("LOCAL_RELEASE.md", "P7_CLOSEOUT.md", "P7_RESULT.md", "DESKTOP_SESSIONS.md"):
        (docs / name).write_text("# Synthetic documentation\n")
    (root / ".gitignore").write_text("private-state/\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "--", "."], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(root),
            "commit",
            "-qm",
            "synthetic release",
        ],
        check=True,
    )
    # A state directory must never leak into the archived committed source.
    (root / "private-state").mkdir()
    (root / "private-state/keep").write_text("private fixture")
    native_run = subprocess.run

    def synthetic_build(argv: list[str], **kwargs: Any) -> Any:
        if argv[:2] != ["uv", "build"]:
            return native_run(argv, **kwargs)
        assert "--offline" in argv and kwargs["cwd"] == root
        output = Path(argv[argv.index("--out-dir") + 1])
        with zipfile.ZipFile(output / "harness_bridge-0.1.0.dev1-py3-none-any.whl", "w") as wheel:
            wheel.write(source / "__init__.py", "harness_bridge/__init__.py")
            wheel.writestr(
                "harness_bridge-0.1.0.dev1.dist-info/METADATA",
                "Name: harness-bridge\nVersion: 0.1.0.dev1\n",
            )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", synthetic_build)
    return root


def test_complete_candidate_can_verify_without_checkout_or_runtime(
    release_repo: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "candidate with spaces"
    build(release_repo, output)
    receipt = verify(output)
    assert receipt["runtime_files_checked"] == 1
    assert receipt["plugin_members_checked"] == 18
    assert receipt["model_or_install_invoked"] is False
    with tarfile.open(output / "harness-bridge-source.tar.gz") as archive:
        assert not any("private-state" in name for name in archive.getnames())
    # Move the deliverable and remove the source checkout; the verifier is self-contained.
    moved = tmp_path / "relocated candidate"
    output.rename(moved)
    shutil.rmtree(release_repo)
    completed = subprocess.run(
        [sys.executable, str(moved / "VERIFY.py"), str(moved)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(completed.stdout) == receipt
    with zipfile.ZipFile(tmp_path / "candidate with spaces.zip") as bundle:
        for path in moved.rglob("*"):
            if path.is_file():
                assert (
                    bundle.read("candidate with spaces/" + path.relative_to(moved).as_posix())
                    == path.read_bytes()
                )


@pytest.mark.parametrize("change", ["tracked", "untracked"])
def test_dirty_source_refuses_before_output(
    release_repo: Path,
    tmp_path: Path,
    change: str,
) -> None:
    target = release_repo / ("NOTICE" if change == "tracked" else "untracked")
    target.write_text("not committed")
    output = tmp_path / "candidate"
    with pytest.raises(ValueError, match="checkout changes"):
        build(release_repo, output)
    assert not output.exists()


@pytest.mark.parametrize("collision", ["directory", "bundle", "in-checkout"])
def test_fresh_only_output_preserves_existing_files(
    release_repo: Path,
    tmp_path: Path,
    collision: str,
) -> None:
    output = (release_repo if collision == "in-checkout" else tmp_path) / "candidate"
    if collision == "directory":
        output.mkdir()
        protected = output / "keep"
        protected.write_bytes(b"keep")
    elif collision == "bundle":
        protected = tmp_path / "candidate.zip"
        protected.write_bytes(b"keep")
    else:
        protected = release_repo / "private-state/keep"
    before = protected.read_bytes()
    with pytest.raises(ValueError):
        build(release_repo, output)
    assert protected.read_bytes() == before


@pytest.mark.parametrize("damage", ["changed", "missing", "extra", "symlink"])
def test_verification_refuses_damaged_candidate(
    release_repo: Path,
    tmp_path: Path,
    damage: str,
) -> None:
    output = tmp_path / "candidate"
    build(release_repo, output)
    if damage == "changed":
        (output / "INSTALL.md").write_text("wrong")
    elif damage == "missing":
        (output / "NOTICE").unlink()
    elif damage == "extra":
        (output / "unexpected").write_text("not inventoried")
    else:
        (output / "INSTALL.md").unlink()
        (output / "INSTALL.md").symlink_to(release_repo / "docs/LOCAL_RELEASE.md")
    with pytest.raises(ValueError):
        verify(output)


def test_checksums_alone_cannot_hide_wheel_source_disagreement(
    release_repo: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "candidate"
    build(release_repo, output)
    wheel_path = next(output.glob("*.whl"))
    with zipfile.ZipFile(wheel_path) as wheel:
        members = {name: wheel.read(name) for name in wheel.namelist()}
    members["harness_bridge/__init__.py"] = b"unexpected runtime\n"
    with zipfile.ZipFile(wheel_path, "w") as wheel:
        for name, data in members.items():
            wheel.writestr(name, data)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files_sha256"][wheel_path.name] = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="wheel/source mismatch"):
        verify(output)


def test_source_change_during_build_prevents_complete_manifest_and_bundle(
    release_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = subprocess.run

    def changed(argv: list[str], **kwargs: Any) -> Any:
        result = previous(argv, **kwargs)
        if argv[:2] == ["uv", "build"]:
            (release_repo / "NOTICE").write_text("concurrent edit")
        return result

    monkeypatch.setattr(subprocess, "run", changed)
    output = tmp_path / "candidate"
    with pytest.raises(ValueError, match="changed during build"):
        build(release_repo, output)
    assert not (output / "manifest.json").exists()
    assert not (tmp_path / "candidate.zip").exists()
