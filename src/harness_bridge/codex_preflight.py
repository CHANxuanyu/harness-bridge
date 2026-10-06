"""Model-free metadata preflight; never read credentials or persist raw config/account data."""

from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, cast

from harness_bridge.errors import BridgeError

SUPPORTED_VERSION = "codex-cli 0.160.0"


def refusal(reason: str) -> BridgeError:
    return BridgeError("PREFLIGHT_FAILED", "Codex preflight: " + reason)


def metadata(binary: str, cwd: str, env: dict[str, str], overrides: list[str]) -> dict[str, Any]:
    argv = [binary, "app-server", "--stdio"]
    for value in overrides:
        argv += ["--config", value]
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        raise refusal("native metadata process could not start") from None
    messages: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=64)
    assert process.stdout is not None and process.stdin is not None

    def reader() -> None:
        assert process.stdout is not None
        try:
            for _ in range(64):
                line = process.stdout.readline(1024 * 1024 + 1)
                if not line or len(line) > 1024 * 1024:
                    break
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    break
                messages.put_nowait(obj)
        except (OSError, ValueError, queue.Full):
            pass
        try:
            messages.put_nowait(None)
        except queue.Full:
            pass

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20

    def send(value: dict[str, Any]) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(value).encode() + b"\n")
        process.stdin.flush()

    def call(ident: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
        send({"id": ident, "method": method, "params": params})
        while time.monotonic() < deadline:
            obj = messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if obj is None:
                raise refusal("metadata stream ended without a response")
            if obj.get("id") == ident:
                if "error" in obj or not isinstance(obj.get("result"), dict):
                    raise refusal("native metadata request failed: " + method)
                return cast(dict[str, Any], obj["result"])
        raise refusal("metadata deadline exceeded")

    try:
        call(
            1,
            "initialize",
            {
                "clientInfo": {"name": "hbridge_preflight", "version": "0.1.0"},
                "capabilities": {"explicitGatewayOauth": True},
            },
        )
        send({"method": "initialized", "params": {}})
        account = call(2, "account/read", {"refreshToken": False}).get("account")
        config = call(3, "config/read", {"cwd": cwd, "includeLayers": False}).get("config")
        if not isinstance(account, dict) or not isinstance(config, dict):
            raise refusal("missing account or effective configuration")
        # Email and raw account data never leave this function.
        return {"account_type": account.get("type"), "config": config}
    except (OSError, queue.Empty):
        raise refusal("native metadata unavailable or timed out") from None
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        thread.join(timeout=1)
        process.stdout.close()


def validate_source(data: dict[str, Any]) -> dict[str, Any]:
    c = data["config"]
    if data.get("account_type") != "chatgpt":
        raise refusal("requires existing ChatGPT login; no API/provider fallback")
    if c.get("model_provider") not in (None, "openai") or c.get("model_providers"):
        raise refusal("custom model provider configuration is unsupported")
    for name in (
        "openai_base_url",
        "profile",
        "oss_provider",
        "hooks",
        "default_permissions",
        "model_catalog_json",
    ):
        if c.get(name):
            raise refusal("unsupported effective configuration field: " + name)
    if c.get("chatgpt_base_url") not in (
        None,
        "https://chatgpt.com/backend-api",
        "https://chatgpt.com/backend-api/",
    ):
        raise refusal("custom ChatGPT endpoint is unsupported")
    mcp = c.get("mcp_servers") or {}
    if not isinstance(mcp, dict) or any(not isinstance(v, dict) for v in mcp.values()):
        raise refusal("invalid MCP configuration")
    apps = c.get("apps") or {}
    if not isinstance(apps, dict) or any(
        not isinstance(v, dict) and not (k == "_default" and v is None) for k, v in apps.items()
    ):
        raise refusal("invalid app configuration")
    return cast(dict[str, Any], c)


def prepare_live(
    binary: str, cwd: str, env: dict[str, str], model: str | None, sandbox: str
) -> tuple[list[str], dict[str, Any]]:
    if not model:
        raise refusal("live execution requires an explicit model pin")
    try:
        version = (
            subprocess.run(
                [binary, "--version"],
                cwd=cwd,
                env=env,
                capture_output=True,
                timeout=10,
                check=True,
            )
            .stdout.decode()
            .strip()
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise refusal("could not establish native CLI version") from None
    if version != SUPPORTED_VERSION:
        raise refusal("native version has not been validated; expected " + SUPPORTED_VERSION)
    # Do not silently disable user enforcement hooks. External hook files require separate review.
    codex_home = Path(env.get("CODEX_HOME") or str(Path(env.get("HOME", "~")) / ".codex"))
    if not codex_home.is_absolute():
        raise refusal("HOME or CODEX_HOME must identify an absolute native profile")
    for file in (codex_home / "hooks.json", Path(cwd) / ".codex/hooks.json"):
        if file.exists():
            raise refusal("external hook file requires unsupported configuration review")
    original = validate_source(metadata(binary, cwd, env, []))
    overrides = [
        'forced_login_method="chatgpt"',
        'approval_policy="never"',
        'model_provider="openai"',
        f"model={json.dumps(model)}",
        f"sandbox_mode={json.dumps(sandbox)}",
        "sandbox_workspace_write.network_access=false",
        "sandbox_workspace_write.writable_roots=[]",
        "sandbox_workspace_write.exclude_tmpdir_env_var=true",
        "sandbox_workspace_write.exclude_slash_tmp=true",
        "features.multi_agent=false",
        "features.plugins=false",
        "features.hooks=false",
        "features.memories=false",
        'web_search="disabled"',
        "apps._default.enabled=false",
        "notify=[]",
    ]
    servers = sorted((original.get("mcp_servers") or {}).keys())
    for name in servers:
        # This CLI parses dotted override paths literally, not as quoted TOML key syntax.
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise refusal("MCP server name cannot be safely addressed by this CLI")
        overrides.append("mcp_servers." + name + ".enabled=false")
    for name in sorted((original.get("apps") or {}).keys()):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise refusal("app name cannot be safely addressed by this CLI")
        overrides.append("apps." + name + ".enabled=false")
    effective = validate_source(metadata(binary, cwd, env, overrides))
    required = {
        "forced_login_method": "chatgpt",
        "approval_policy": "never",
        "model_provider": "openai",
        "model": model,
        "sandbox_mode": sandbox,
        "web_search": "disabled",
    }
    if effective.get("notify"):
        raise refusal("native notification command remains enabled")
    if any(effective.get(k) != v for k, v in required.items()):
        raise refusal("native configuration did not enforce requested model/permissions")
    features = effective.get("features") or {}
    if any(features.get(k) is not False for k in ("multi_agent", "plugins", "hooks", "memories")):
        raise refusal("native configuration did not restrict auxiliary execution")
    if any(v.get("enabled") is not False for v in (effective.get("mcp_servers") or {}).values()):
        raise refusal("an MCP server remains enabled")
    workspace = effective.get("sandbox_workspace_write") or {}
    if workspace.get("network_access") is not False or workspace.get("writable_roots"):
        raise refusal("unexpected network access or extra writable roots")
    if any(workspace.get(k) is not True for k in ("exclude_tmpdir_env_var", "exclude_slash_tmp")):
        raise refusal("temporary-directory write exclusions were not applied")
    apps = effective.get("apps") or {}
    if (apps.get("_default") or {}).get("enabled") is not False or any(
        (v or {}).get("enabled") is not False for v in apps.values()
    ):
        raise refusal("an app remains enabled")
    return overrides, {
        "native_version": version,
        "auth_type": "chatgpt",
        "provider": "openai",
        "requested_model": model,
        "sandbox": sandbox,
        "approval_policy": "never",
        "native_turn_ceiling": "unsupported",
        "budget_policy": "attempts_and_wall_time",
        "disabled_mcp_servers": len(servers),
        "plugins_hooks_subagents_disabled": True,
        "inference_performed": False,
    }
