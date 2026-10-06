"""Non-inference diagnostics: no login, no model endpoint, no secret values.

Reports capabilities as supported / unsupported / unknown together with the evidence source.
"""

from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from harness_bridge import SCHEMA_VERSION, __version__
from harness_bridge.adapters.claude_code import (
    ClaudeCodeAdapter,
    ClaudeSettings,
    flag_evidence,
    help_flags,
)
from harness_bridge.adapters.codex import CodexAdapter, CodexSettings
from harness_bridge.config import (
    API_PROVIDER_ENV,
    CLOUD_ENV_MARKERS,
    NESTED_ENV_MARKERS,
    evaluate_live_gate,
    load_config,
    present,
)
from harness_bridge.errors import BridgeError
from harness_bridge.models import DEFAULT_MODEL


def _claude_flag_check(
    binary: str, env: dict[str, str], confirmed: tuple[str, ...]
) -> dict[str, Any]:
    """Per-flag evidence: official docs, local ``claude --help``, local confirmation (no inference).

    A flag missing from --help is reported as unknown/pending, never as unsupported: the official
    CLI reference states that --help does not list every flag.
    """
    adapter = ClaudeCodeAdapter(
        ClaudeSettings(DEFAULT_MODEL, 20, "acceptEdits", ("Read", "Edit"), True)
    )
    try:
        listed, version = help_flags(binary, env)
    except BridgeError as exc:
        return {"status": "unknown", "error": exc.message}
    evidence = flag_evidence(
        adapter.flags_used(resume=True), listed_flags=listed, confirmed=confirmed
    )
    pending = [f for f, e in evidence.items() if not e["usable_for_live"]]
    return {
        "status": "pending_local_confirmation" if pending else "all_listed_or_confirmed",
        "cli_version": version,
        "pending_local_confirmation": pending,
        "flag_evidence": evidence,
        "note": "help-text and documentation evidence only; flag behaviour, auth and stream "
        "schema stay unverified until a local, authorized live run",
    }


def _version(argv: list[str]) -> str | None:
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = proc.stdout.decode("utf-8", "replace").strip().splitlines()
    return text[0][:200] if proc.returncode == 0 and text else None


def _state_dir_writable(state_dir: Path) -> bool:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        probe = state_dir / ".doctor-probe"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def run_doctor(state_dir: Path, *, offline: bool) -> dict[str, Any]:
    env = dict(os.environ)
    try:
        config = load_config(state_dir)
        config_error = None
    except BridgeError as exc:
        config = None
        config_error = exc.message
    git_path = shutil.which("git")
    claude_path = (config.claude_binary if config and config.claude_binary else None) or (
        shutil.which("claude")
    )
    gate = (
        evaluate_live_gate(mode="live", allow_model_usage=False, config=config, env=env)
        if config
        else None
    )
    capabilities = [
        {
            "name": "fake_executor_offline_flow",
            "status": "supported",
            "evidence": "offline integration tests + demos (simulated executor, T2)",
        },
        {
            "name": "claude_code_adapter_offline_contract",
            "status": "supported",
            "evidence": "synthetic/docs-derived stream fixtures + stub binary (not a real CLI run)",
        },
        {
            "name": "claude_code_live_dispatch",
            "status": "unknown",
            "evidence": "Project records bounded live smokes and a controlled repair/resume "
            "in docs/VALIDATION_MATRIX.md; doctor does not validate live dispatch "
            "on the current configuration",
        },
        {
            "name": "codex_executor_adapter",
            "status": "gated_wall_time_only",
            "evidence": CodexAdapter(CodexSettings()).describe_capabilities(),
        },
        {
            "name": "codex_supervisor_loop",
            "status": "unknown",
            "evidence": "Project records local Codex -> bridge -> Claude initial and repair "
            "loops in docs/VALIDATION_MATRIX.md; doctor does not run a supervisor loop",
        },
        {
            "name": "process_group_management",
            "status": "supported"
            if sys.platform.startswith("linux") or sys.platform == "darwin"
            else "unknown",
            "evidence": "Offline process-group and recovery tests recorded on Linux and macOS "
            "(docs/VALIDATION_MATRIX.md); doctor does not run signal or timeout tests"
            if sys.platform.startswith("linux") or sys.platform == "darwin"
            else "no recorded process-group validation for this platform",
        },
    ]
    claude_check = (
        _claude_flag_check(claude_path, env, config.allow_unlisted_flags if config else ())
        if claude_path and not offline
        else {"status": "skipped", "reason": "offline" if offline else "claude not found"}
    )
    return {
        "bridge_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "inference_performed": False,
        "offline": offline,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "sqlite": sqlite3.sqlite_version,
        },
        "tools": {
            "git": {
                "path": git_path,
                "version": None if offline or not git_path else _version([git_path, "--version"]),
            },
            "claude": {
                "path": claude_path,
                "version": None
                if offline or not claude_path
                else _version([claude_path, "--version"]),
                "note": "presence/version only; never invoked for inference by doctor",
            },
        },
        "state_dir": {"path": str(state_dir), "writable": _state_dir_writable(state_dir)},
        "config": {
            "source": config.source if config else None,
            "live_enabled": config.live_enabled if config else None,
            "error": config_error,
        },
        "environment": {
            "api_or_provider_env_present": present(API_PROVIDER_ENV, env),
            "cloud_environment_markers": present(CLOUD_ENV_MARKERS, env),
            "nested_session_markers": present(NESTED_ENV_MARKERS, env),
            "note": "variable names only; values are never read into output",
        },
        "live_gate_preview": gate.to_dict() if gate else None,
        "claude_cli_flag_check": claude_check,
        "capabilities": capabilities,
    }
