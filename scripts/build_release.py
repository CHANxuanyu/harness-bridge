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


def build(root: Path, output: Path) -> None:
    root = root.resolve()
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("output must be an absolute, new directory")
    output = output.resolve()
    if output.is_relative_to(root):
        raise ValueError("candidate output must be outside the checkout")
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    plugin = root / "plugins/harness-bridge"
    version = json.loads((plugin / "plugin.json").read_text())["version"]
    for manifest in (".codex-plugin/plugin.json", ".zcode-plugin/plugin.json"):
        if json.loads((plugin / manifest).read_text())["version"] != version:
            raise ValueError("plugin manifest versions differ")
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
    shutil.copyfile(root / "docs/P7_RESULT.md", output / "ACCEPTANCE.md")
    shutil.copyfile(root / "docs/DESKTOP_SESSIONS.md", output / "DESKTOP_SESSIONS.md")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root))
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.iterdir())
        if p.is_file()
    }
    manifest = {
        "scope": "local-candidate-only",
        "published": False,
        "acceptance": "see ACCEPTANCE.md",
        "runtime_version": project["version"],
        "plugin_version": version,
        "license": "Apache-2.0",
        "source_revision": revision,
        "source_dirty": dirty,
        "files_sha256": hashes,
        "plugin_members": [str(p.relative_to(root)) for p in sorted(paths)],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), **manifest}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.out)
