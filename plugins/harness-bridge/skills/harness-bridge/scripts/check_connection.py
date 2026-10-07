"""Probe a trusted Bridge runtime without opening selected state or invoking a harness."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

VERSION = "0.1.0.dev1"
PROTOCOL = "1.0"
COMMANDS = (
    ("projects",),
    ("list",),
    ("create",),
    ("goal", "create"),
    ("goal", "status"),
    ("goal", "takeover"),
    ("goal", "control"),
    ("goal", "plan"),
    ("goal", "integrate"),
    ("goal", "deliver"),
    ("goal", "cleanup"),
    ("child", "status"),
    ("child", "materialize"),
    ("child", "prepare"),
    ("child", "preflight"),
    ("run",),
    ("job",),
    ("events",),
    ("status",),
    ("desktop", "status"),
    ("desktop", "open"),
    ("artifacts",),
    ("review",),
    ("verify",),
    ("recover",),
    ("cancel",),
    ("retain-approved",),
    ("integration", "materialize"),
    ("integration", "status"),
    ("integration", "verify"),
    ("integration", "review"),
    ("integration", "cancel"),
    ("integration", "recover"),
    ("delivery", "status"),
    ("delivery", "abort"),
    ("cleanup",),
)


class ConnectionError(Exception):
    pass


def absolute(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value or "\0" in value or not Path(value).is_absolute():
        raise ConnectionError(f"{name} must be an absolute path")
    return Path(value)


def connection(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.runtime is not None or args.state_dir is not None:
        if args.connection is not None or args.runtime is None or args.state_dir is None:
            raise ConnectionError("use a connection file OR both runtime and state_dir")
        value = {"runtime": args.runtime, "state_dir": args.state_dir}
    else:
        default = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        filename = (
            args.connection
            or os.environ.get("HBRIDGE_CONNECTION")
            or str(default / "harness-bridge" / "connection.json")
        )
        path = absolute(filename, "connection")
        if path.stat().st_size > 16384:
            raise ConnectionError("connection file exceeds 16 KiB")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {
            "connection_version",
            "runtime",
            "state_dir",
        }:
            raise ConnectionError("invalid connection fields")
        if type(value["connection_version"]) is not int or value["connection_version"] != 1:
            raise ConnectionError("unsupported connection_version")
    runtime, state = (
        absolute(value["runtime"], "runtime"),
        absolute(value["state_dir"], "state_dir"),
    )
    if not runtime.is_file() or not os.access(runtime, os.X_OK):
        raise ConnectionError("runtime is missing or not executable")
    if state.exists() and not state.is_dir():
        raise ConnectionError("state_dir is not a directory")
    return runtime, state


def probe(runtime: Path, state: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="hbridge-connection-") as scratch:
        root = Path(scratch)
        home = root / "home"
        home.mkdir()
        # Retain protective cloud/provider/nested markers. Finite probes never dispatch.
        env = dict(os.environ)
        env.update(
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_STATE_HOME": str(home / ".state"),
                "CODEX_HOME": str(home / ".codex"),
                "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            }
        )

        def call(*argv: str) -> str:
            result = subprocess.run(
                [str(runtime), "--state-dir", str(root / "probe-state"), *argv],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode:
                # Never echo arbitrary runtime output/config/exception details.
                raise ConnectionError(f"runtime probe failed: {' '.join(argv)}")
            return result.stdout

        if call("--version").strip() != f"hbridge {VERSION}":
            raise ConnectionError(f"runtime version must be {VERSION}")
        for command in COMMANDS:
            help_text = call(*command, "--help")
            required = {
                ("run",): ("--background", "--idempotency-key"),
                ("events",): ("--after", "--wait"),
                ("goal", "deliver"): ("--integration", "--branch"),
                ("desktop", "open"): ("--idempotency-key", "--advisor-binding", "--advisor-epoch"),
            }.get(command, ())
            if any(flag not in help_text for flag in required):
                raise ConnectionError(f"runtime lacks required options: {' '.join(command)}")
        report = json.loads(call("--json", "doctor", "--offline"))
        if not isinstance(report, dict):
            raise ConnectionError("offline diagnostic contract mismatch")
        if (
            report.get("ok") is not True
            or report.get("schema_version") != PROTOCOL
            or report.get("bridge_version") != VERSION
            or report.get("offline") is not True
            or report.get("inference_performed") is not False
        ):
            raise ConnectionError("offline diagnostic contract mismatch")
    return {
        "ok": True,
        "runtime_compatible": True,
        "runtime": str(runtime),
        "state_dir": str(state),
        "state_inspected": False,
        "inference_performed": False,
        "protocol": PROTOCOL,
        "commands_checked": len(COMMANDS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection")
    parser.add_argument("--runtime")
    parser.add_argument("--state-dir")
    args = parser.parse_args()
    try:
        result = probe(*connection(args))
    except ConnectionError as exc:
        result = {"ok": False, "error": str(exc)}
    except (OSError, ValueError, RecursionError, subprocess.SubprocessError):
        result = {"ok": False, "error": "connection unreadable or runtime probe unavailable"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
