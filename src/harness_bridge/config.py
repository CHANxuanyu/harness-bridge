"""State directory, local config file and the explicit live-dispatch gate.

Real model dispatch requires ALL of:
  1. ``hbridge run --mode live --allow-model-usage`` on the command line;
  2. ``[live] enabled = true`` and ``hooks_and_permissions_reviewed = true`` in
     ``<state-dir>/config.toml`` (a local, deliberate opt-in after reviewing hooks/MCP/permissions);
  3. not a cloud agent environment and not nested inside another Claude Code session;
  4. no API-key / third-party provider variables in the environment (they can switch Claude Code
     from subscription to API billing); only variable *names* are reported.

These checks reduce accidental model usage; they are not a proof of billing isolation.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness_bridge.errors import BridgeError

# Variables whose presence means a live Claude run might bill an API account or route elsewhere.
API_PROVIDER_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_BEDROCK_BASE_URL",
    "ANTHROPIC_VERTEX_BASE_URL",
    "ANTHROPIC_FOUNDRY_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_API_KEY_HELPER",
    "AWS_BEARER_TOKEN_BEDROCK",
)
CLOUD_ENV_MARKERS = ("CLAUDE_CODE_REMOTE", "CLAUDE_CODE_REMOTE_SESSION_ID", "CODEX_CLOUD")
NESTED_ENV_MARKERS = ("CLAUDECODE",)


def default_state_dir(env: dict[str, str] | None = None) -> Path:
    env = dict(os.environ) if env is None else env
    if env.get("HBRIDGE_STATE_DIR"):
        return Path(env["HBRIDGE_STATE_DIR"]).expanduser()
    base = env.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base) / "harness-bridge"


@dataclass(frozen=True)
class BridgeConfig:
    live_enabled: bool = False
    claude_binary: str | None = None
    allow_unlisted_flags: tuple[str, ...] = ()
    hooks_and_permissions_reviewed: bool = False
    source: str = "defaults"
    raw: dict[str, Any] = field(default_factory=dict)


def load_config(state_dir: Path) -> BridgeConfig:
    path = state_dir / "config.toml"
    if not path.exists():
        return BridgeConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BridgeError("INVALID_INPUT", f"cannot parse {path}: {exc}") from None
    live = data.get("live", {})
    if not isinstance(live, dict):
        raise BridgeError("INVALID_INPUT", "[live] in config.toml must be a table")
    known = {"enabled", "claude_binary", "allow_unlisted_flags", "hooks_and_permissions_reviewed"}
    unknown = set(live) - known
    if unknown:
        raise BridgeError("INVALID_INPUT", f"unknown [live] keys in config.toml: {sorted(unknown)}")
    enabled = live.get("enabled", False)
    if not isinstance(enabled, bool):
        raise BridgeError("INVALID_INPUT", "[live] enabled must be true or false")
    binary = live.get("claude_binary")
    if binary is not None and (not isinstance(binary, str) or not os.path.isabs(binary)):
        raise BridgeError("INVALID_INPUT", "[live] claude_binary must be an absolute path")
    flags = live.get("allow_unlisted_flags", [])
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise BridgeError("INVALID_INPUT", "[live] allow_unlisted_flags must be a list of strings")
    reviewed = live.get("hooks_and_permissions_reviewed", False)
    if not isinstance(reviewed, bool):
        raise BridgeError("INVALID_INPUT", "[live] hooks_and_permissions_reviewed must be a bool")
    return BridgeConfig(
        live_enabled=enabled,
        hooks_and_permissions_reviewed=reviewed,
        claude_binary=binary,
        allow_unlisted_flags=tuple(flags),
        source=str(path),
        raw=data,
    )


def present(names: tuple[str, ...], env: dict[str, str]) -> list[str]:
    return [n for n in names if env.get(n)]


@dataclass(frozen=True)
class LiveGate:
    open: bool
    reasons: list[str]
    api_env_present: list[str]
    cloud_markers: list[str]
    nested_markers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "open": self.open,
            "closed_reasons": self.reasons,
            "api_or_provider_env_present": self.api_env_present,
            "cloud_environment_markers": self.cloud_markers,
            "nested_session_markers": self.nested_markers,
        }


def evaluate_live_gate(
    *, mode: str, allow_model_usage: bool, config: BridgeConfig, env: dict[str, str]
) -> LiveGate:
    reasons: list[str] = []
    if mode != "live":
        reasons.append("mode is not 'live'")
    if not allow_model_usage:
        reasons.append("--allow-model-usage was not given")
    if not config.live_enabled:
        reasons.append("[live] enabled = true is not set in the state-dir config.toml")
    if not config.hooks_and_permissions_reviewed:
        reasons.append(
            "[live] hooks_and_permissions_reviewed = true is not set: review Claude Code hooks, "
            "MCP servers and permission settings (user and project) before the first live run"
        )
    cloud = present(CLOUD_ENV_MARKERS, env)
    if cloud:
        reasons.append("cloud agent environment detected; live dispatch is never allowed here")
    nested = present(NESTED_ENV_MARKERS, env)
    if nested:
        reasons.append("running inside another Claude Code session (nested); refusing")
    api = present(API_PROVIDER_ENV, env)
    if api:
        reasons.append(
            "API-key / provider variables are set (" + ", ".join(api) + "); a live run could "
            "bill an API account instead of the subscription. Unset them in that shell yourself."
        )
    return LiveGate(not reasons, reasons, api, cloud, nested)
