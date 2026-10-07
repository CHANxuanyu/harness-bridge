"""Verify a local candidate without extracting archives, installing or executing its code."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def safe_name(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return bool(parts) and not name.startswith("/") and ".." not in parts and "\\" not in name


def zip_files(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        require(len({m.filename for m in members}) == len(members), "duplicate ZIP member")
        for member in members:
            require(safe_name(member.filename), "unsafe ZIP member")
            require(not stat.S_ISLNK(member.external_attr >> 16), "symbolic ZIP member")
        return {m.filename: archive.read(m) for m in members if not m.is_dir()}


def verify(candidate: Path) -> dict[str, Any]:
    require(candidate.is_dir() and not candidate.is_symlink(), "expected candidate directory")
    files: dict[str, Path] = {}
    for path in candidate.rglob("*"):
        require(not path.is_symlink(), "symbolic candidate member")
        if path.is_file():
            files[path.relative_to(candidate).as_posix()] = path
    manifest = json.loads(files.pop("manifest.json").read_text())
    require(manifest["format_version"] == 1, "unsupported candidate format")
    require(manifest["scope"] == "local-candidate-only", "unexpected publication scope")
    require(manifest["published"] is False, "candidate marked published")
    require(manifest["source_dirty"] is False, "candidate has uncommitted source")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", manifest["source_revision"])), "invalid revision")
    require(set(files) == set(manifest["files_sha256"]), "candidate inventory mismatch")
    for name, path in files.items():
        require(
            hashlib.sha256(path.read_bytes()).hexdigest() == manifest["files_sha256"][name],
            "checksum mismatch: " + name,
        )
    required = {
        "INSTALL.md",
        "ACCEPTANCE.md",
        "VERIFY.py",
        "LICENSE",
        "NOTICE",
        "harness-bridge-source.tar.gz",
        "docs/P7_CLOSEOUT.md",
        "docs/P7_RESULT.md",
        "docs/LOCAL_RELEASE.md",
        "docs/DESKTOP_SESSIONS.md",
    }
    require(required <= files.keys(), "missing release material")
    source: dict[str, bytes] = {}
    with tarfile.open(files["harness-bridge-source.tar.gz"], "r:gz") as archive:
        require(
            archive.pax_headers.get("comment") == manifest["source_revision"],
            "source archive revision mismatch",
        )
        seen: set[str] = set()
        for member in archive:
            require(
                safe_name(member.name)
                and (
                    member.name.startswith("source/")
                    or (member.name == "source" and member.isdir())
                ),
                "unsafe source member",
            )
            require(member.name not in seen, "duplicate source member")
            seen.add(member.name)
            require(member.isfile() or member.isdir(), "linked or special source member")
            if member.isfile():
                stream = archive.extractfile(member)
                require(stream is not None, "unreadable source member")
                assert stream is not None
                source[member.name.removeprefix("source/")] = stream.read()
    for name in ("LICENSE", "NOTICE"):
        require(files[name].read_bytes() == source[name], "license/source mismatch")
    for packaged, original in (
        ("VERIFY.py", "scripts/verify_release.py"),
        ("INSTALL.md", "docs/LOCAL_RELEASE.md"),
    ):
        require(files[packaged].read_bytes() == source[original], "release/source mismatch")
    docs = {name for name in source if name.startswith("docs/")}
    require({name for name in files if name.startswith("docs/")} == docs, "docs inventory mismatch")
    for name in docs:
        require(files[name].read_bytes() == source[name], "docs/source mismatch: " + name)
    wheels = [name for name in files if name.endswith(".whl")]
    require(len(wheels) == 1, "expected one runtime wheel")
    wheel = zip_files(files[wheels[0]])
    modules = {
        name.removeprefix("src/"): data
        for name, data in source.items()
        if name.startswith("src/harness_bridge/")
    }
    require(
        {name for name in wheel if name.startswith("harness_bridge/")} == modules.keys(),
        "wheel module inventory mismatch",
    )
    for name, data in modules.items():
        require(wheel[name] == data, "wheel/source mismatch: " + name)
    metadata = [data for name, data in wheel.items() if name.endswith(".dist-info/METADATA")]
    require(len(metadata) == 1, "expected one wheel metadata record")
    info = BytesParser().parsebytes(metadata[0])
    require(
        info["Name"] == "harness-bridge" and info["Version"] == manifest["runtime_version"],
        "runtime metadata mismatch",
    )
    plugin_zip = f"harness-bridge-marketplace-{manifest['plugin_version']}.zip"
    plugin = zip_files(files[plugin_zip])
    require(set(plugin) == set(manifest["plugin_members"]), "plugin inventory mismatch")
    for name, data in plugin.items():
        require(data == source[name], "plugin/source mismatch: " + name)
    for name in ("plugin.json", ".codex-plugin/plugin.json", ".zcode-plugin/plugin.json"):
        require(
            json.loads(plugin["plugins/harness-bridge/" + name])["version"]
            == manifest["plugin_version"],
            "plugin metadata mismatch",
        )
    require(
        json.loads(plugin["marketplace.json"])["plugins"][0]["version"]
        == manifest["plugin_version"],
        "marketplace metadata mismatch",
    )
    return {
        "verified": True,
        "source_revision": manifest["source_revision"],
        "files_checked": len(files),
        "runtime_files_checked": len(modules),
        "plugin_members_checked": len(plugin),
        "model_or_install_invoked": False,
        "acceptance": "unchanged; see docs/P7_CLOSEOUT.md",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.candidate), indent=2))
    except (ValueError, KeyError, OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        parser.exit(1, f"candidate verification failed: {error}\n")
