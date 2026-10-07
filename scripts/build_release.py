"""Build an unpublished local candidate. Never upload, install or invoke a model."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

try:
    from .verify_release import verify
except ImportError:  # Direct invocation from a checkout.
    from verify_release import verify


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", *args], cwd=root, text=True
    ).strip()


def build(root: Path, output: Path) -> None:
    root = root.resolve()
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("output must be an absolute, new directory")
    output = output.resolve()
    if output.is_relative_to(root):
        raise ValueError("candidate output must be outside the checkout")
    bundle = output.parent / (output.name + ".zip")
    if bundle.exists() or bundle.is_symlink():
        raise ValueError("candidate bundle already exists")
    revision = git(root, "rev-parse", "HEAD")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("commit or preserve checkout changes before building a candidate")
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    plugin = root / "plugins/harness-bridge"
    version = json.loads((plugin / "plugin.json").read_text())["version"]
    for manifest in (".codex-plugin/plugin.json", ".zcode-plugin/plugin.json"):
        if json.loads((plugin / manifest).read_text())["version"] != version:
            raise ValueError("plugin manifest versions differ")
    catalog = json.loads((root / "marketplace.json").read_text())
    if catalog["plugins"][0]["version"] != version:
        raise ValueError("marketplace and plugin versions differ")
    # Explicit inventory prevents accidentally shipping local state, bytecode or credentials.
    inventory = [
        "plugin.json",
        ".codex-plugin/plugin.json",
        ".zcode-plugin/plugin.json",
        "README.md",
        "LICENSE",
        "NOTICE",
        "skills/harness-bridge/SKILL.md",
        "skills/harness-bridge/references/connection.md",
        "skills/harness-bridge/references/live-readiness.md",
        "skills/harness-bridge/references/workflow.md",
        "skills/harness-bridge/scripts/check_connection.py",
        "skills/harness-bridge/references/delivery.md",
        "skills/harness-bridge/references/desktop.md",
        "skills/harness-bridge/references/goal.example.json",
        "skills/harness-bridge/references/task.example.json",
        "skills/harness-bridge/references/plan.example.json",
    ]
    paths = [root / "marketplace.json", root / ".agents/plugins/marketplace.json"]
    paths += [plugin / name for name in inventory]
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError("missing or symbolic package member: " + str(path.relative_to(root)))
    output.mkdir(parents=True)
    subprocess.run(
        ["uv", "build", "--offline", "--wheel", "--out-dir", str(output)],
        cwd=root,
        check=True,
    )
    archive = output / f"harness-bridge-marketplace-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(paths):
            member = zipfile.ZipInfo(str(path.relative_to(root)), (2026, 1, 1, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o100644 << 16
            z.writestr(member, path.read_bytes())
    for name in ("LICENSE", "NOTICE"):
        shutil.copyfile(root / name, output / name)
    shutil.copyfile(root / "docs/LOCAL_RELEASE.md", output / "INSTALL.md")
    # Preserve relative documentation links, including historical evidence referenced by P7.
    for name in git(root, "ls-files", "-z", "--", "docs").split("\0"):
        if not name:
            continue
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("missing or symbolic documentation member: " + name)
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (output / "ACCEPTANCE.md").write_text(
        "# Candidate acceptance\n\n"
        "See the [V01–V15 closeout matrix](docs/P7_CLOSEOUT.md), "
        "[native evidence](docs/P7_RESULT.md) and "
        "[desktop boundary](docs/DESKTOP_SESSIONS.md).\n\n"
        "This is a local candidate; consult the matrix for remaining host acceptance.\n"
    )
    shutil.copyfile(root / "scripts/verify_release.py", output / "VERIFY.py")
    subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "archive",
            "--format=tar.gz",
            "--prefix=source/",
            "--output=" + str(output / "harness-bridge-source.tar.gz"),
            revision,
        ],
        cwd=root,
        check=True,
    )
    if git(root, "rev-parse", "HEAD") != revision or git(
        root, "status", "--porcelain", "--untracked-files=all"
    ):
        raise ValueError("checkout changed during build; candidate is incomplete")
    hashes = {
        p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "format_version": 1,
        "scope": "local-candidate-only",
        "published": False,
        "acceptance": "see ACCEPTANCE.md",
        "runtime_version": project["version"],
        "plugin_version": version,
        "license": "Apache-2.0",
        "source_revision": revision,
        "source_dirty": False,
        "files_sha256": hashes,
        "plugin_members": [str(p.relative_to(root)) for p in sorted(paths)],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verified = verify(output)
    # Exclusive creation avoids replacing an earlier candidate, including a competing build.
    with zipfile.ZipFile(bundle, "x", zipfile.ZIP_DEFLATED) as archive_zip:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive_zip.write(path, output.name + "/" + path.relative_to(output).as_posix())
    print(
        json.dumps(
            {
                "output": str(output),
                "bundle": str(bundle),
                "verification": verified,
                "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.out)
