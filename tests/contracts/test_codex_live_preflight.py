"""Native metadata is simulated; these tests never execute Codex or read real authentication."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from harness_bridge import codex_preflight as p
from harness_bridge.config import CODEX_PROVIDER_ENV, BridgeConfig, evaluate_live_gate
from harness_bridge.errors import BridgeError
from harness_bridge.models import parse_task_spec
from tests.conftest import Fixture
from tests.integration.test_codex_stub_flow import cx_spec, cx_stub  # noqa: F401
from tests.integration.test_coordination import setup_goal
from tests.integration.test_goal_planning import plan, submit


def native_config() -> dict[str, Any]:
    return {
        "account_type": "chatgpt",
        "config": {
            "model_provider": None,
            "apps": {"_default": None, "configured_app": {"enabled": True}},
            "mcp_servers": {"local_tools": {"command": "never-run", "enabled": True}},
        },
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("model_provider", "third-party"),
        ("model_providers", {"openai": {"base_url": "secret"}}),
        ("chatgpt_base_url", "https://elsewhere.invalid"),
        ("openai_base_url", "https://elsewhere.invalid"),
        ("profile", "custom"),
        ("hooks", {"Stop": []}),
        ("default_permissions", "danger"),
        ("model_catalog_json", "/other/models.json"),
    ],
)
def test_source_refuses_unreviewed_routes_without_echoing_values(key: str, value: Any) -> None:
    data = native_config()
    data["config"][key] = value
    with pytest.raises(BridgeError) as err:
        p.validate_source(data)
    assert "secret" not in err.value.message and "elsewhere" not in err.value.message


@pytest.mark.parametrize("kind", ["apiKey", "amazonBedrock", None])
def test_non_subscription_source_refused(kind: str | None) -> None:
    data = native_config()
    data["account_type"] = kind
    with pytest.raises(BridgeError):
        p.validate_source(data)


@pytest.mark.parametrize("name", CODEX_PROVIDER_ENV)
def test_codex_provider_environment_refused_by_name_only(name: str) -> None:
    gate = evaluate_live_gate(
        mode="live",
        allow_model_usage=True,
        config=BridgeConfig(live_enabled=True, hooks_and_permissions_reviewed=True),
        env={name: "private-value"},
        executor_kind="codex",
    )
    assert not gate.open and gate.api_env_present == [name]
    assert "private-value" not in json.dumps(gate.to_dict())


def install_metadata(
    monkeypatch: pytest.MonkeyPatch, *, ignore: str | None = None
) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        p.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 0, (p.SUPPORTED_VERSION + "\n").encode(), b""
        ),
    )

    def metadata(
        binary: str, cwd: str, env: dict[str, str], overrides: list[str]
    ) -> dict[str, Any]:
        calls.append(overrides)
        data = native_config()
        for text in overrides:
            key, value = text.split("=", 1)
            if key == ignore:
                continue
            dst = data["config"]
            bits = key.split(".")
            for bit in bits[:-1]:
                if dst.get(bit) is None:
                    dst[bit] = {}
                dst = dst[bit]
            dst[bits[-1]] = json.loads(value)
        return data

    monkeypatch.setattr(p, "metadata", metadata)
    return calls


@pytest.mark.parametrize(
    "ignored",
    [
        None,
        "features.multi_agent",
        "features.plugins",
        "mcp_servers.local_tools.enabled",
        "approval_policy",
        "sandbox_workspace_write.network_access",
        "sandbox_workspace_write.exclude_tmpdir_env_var",
        "sandbox_workspace_write.exclude_slash_tmp",
        "apps._default.enabled",
        "apps.configured_app.enabled",
    ],
)
def test_overrides_must_be_confirmed_by_native_effective_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ignored: str | None
) -> None:
    calls = install_metadata(monkeypatch, ignore=ignored)
    args = ("/stand-in", str(tmp_path), {"HOME": str(tmp_path)}, "synthetic-pin", "workspace-write")
    if ignored:
        with pytest.raises(BridgeError):
            p.prepare_live(*args)
    else:
        overrides, receipt = p.prepare_live(*args)
        assert receipt["inference_performed"] is False
        assert receipt["native_turn_ceiling"] == "unsupported"
        assert 'forced_login_method="chatgpt"' in overrides
        assert "mcp_servers.local_tools.enabled=false" in overrides
    assert len(calls) == 2


def test_null_turn_limit_is_codex_only_and_old_normalized_shape_is_stable(fx: Fixture) -> None:
    old = parse_task_spec(cx_spec(fx)).model_dump(mode="json")
    data = copy.deepcopy(old)
    data["limits"]["max_turns_per_attempt"] = None
    assert parse_task_spec(data).limits.max_turns_per_attempt is None
    assert parse_task_spec(old).model_dump(mode="json") == old
    for kind in ("fake", "claude-code"):
        data["executor"] = fx.spec()["executor"] if kind == "fake" else {"kind": kind}
        with pytest.raises(BridgeError):
            parse_task_spec(data)


@pytest.mark.parametrize("goal_turns", [None, 30])
def test_wall_only_child_never_misreports_or_evades_aggregate_turn_cap(
    fx: Fixture,
    cx_stub: Path,  # noqa: F811
    goal_turns: int | None,
) -> None:
    b, goal = setup_goal(fx, allowed_executors=["codex"], max_executor_turns=goal_turns)
    child = plan(fx, "cx")
    child["task"]["executor"] = cx_spec(fx)["executor"]
    child["task"]["limits"]["max_turns_per_attempt"] = None
    batch = submit(b, goal, child)
    tid = b.materialize(batch["children"][0]["child_id"])["task_id"]
    try:
        if goal_turns:
            with pytest.raises(BridgeError) as err:
                b.run(tid, executor_binary=str(cx_stub))
            assert err.value.code == "BUDGET_EXHAUSTED" and not b.store.list_attempts(tid)
        else:
            b.run(tid, executor_binary=str(cx_stub))
            budget = b.coordination.status(goal["goal_id"])["budget"]
            assert budget["reserved_turns"] is None and budget["turn_cap_unavailable_attempts"] == 1
            assert budget["attempts"] == 1 and budget["reserved_wall_seconds"] > 0
    finally:
        b.close()


def test_metadata_protocol_only_calls_read_methods_and_removes_email(tmp_path: Path) -> None:
    script = tmp_path / "metadata-stand-in"
    script.write_text(f"""#!{sys.executable}
import json,sys
for line in sys.stdin:
 r=json.loads(line)
 if "id" not in r: continue
 method=r["method"]
 assert method in ["initialize", "account/read", "config/read"]
 if method=="account/read":
  assert r["params"]["refreshToken"] is False
  result={{"account":{{"type":"chatgpt","email":"private@example.invalid"}}}}
 elif method=="config/read": result={{"config":{{"model_provider":None}}}}
 else: result={{}}
 print(json.dumps({{"id":r["id"],"result":result}}),flush=True)
""")
    script.chmod(0o700)
    data = p.metadata(str(script), str(tmp_path), {}, [])
    assert data == {"account_type": "chatgpt", "config": {"model_provider": None}}


@pytest.mark.parametrize("key,value", [("mcp_servers", {"broken": None}), ("apps", {"broken": 1})])
def test_malformed_auxiliary_configuration_fails_closed(key: str, value: Any) -> None:
    data = native_config()
    data["config"][key] = value
    with pytest.raises(BridgeError):
        p.validate_source(data)


@pytest.mark.parametrize("env", [{}, {"HOME": "relative"}, {"CODEX_HOME": "relative"}])
def test_ambiguous_profile_path_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    calls = install_metadata(monkeypatch)
    with pytest.raises(BridgeError):
        p.prepare_live("/stand-in", str(tmp_path), env, "synthetic-pin", "workspace-write")
    assert calls == []


@pytest.mark.parametrize(
    "background,refused",
    [(False, False), (False, True), (True, False), (True, True), (True, "env"), (True, "changed")],
)
def test_codex_live_service_preflight_precedes_reservation_and_overrides_reach_process(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch, background: bool, refused: bool | str
) -> None:
    """The selected 'live' executable is explicitly a Python stand-in, never real Codex."""
    import os

    from harness_bridge.service import Bridge

    wrapper = fx.base / "metadata-checked-stand-in"
    helper = Path(__file__).parents[1] / "helpers/cx_stub.py"
    wrapper.write_text(f"""#!{sys.executable}
import os,sys
assert sys.argv[1:3] == ['--config', 'forced_login_method="chatgpt"']
os.execv({sys.executable!r}, [{sys.executable!r}, {str(helper)!r}] + sys.argv[3:])
""")
    wrapper.chmod(0o700)
    fx.state_dir.mkdir()
    (fx.state_dir / "config.toml").write_text(
        "[live]\nenabled=true\nhooks_and_permissions_reviewed=true\n"
        + "codex_binary="
        + json.dumps(str(wrapper))
        + "\n"
    )
    bridge = Bridge(fx.state_dir, env=dict(os.environ))
    data = cx_spec(fx)
    data["limits"]["max_turns_per_attempt"] = None
    task = bridge.create(data, "wall-only")["task_id"]

    preflight_counts = []
    monkeypatch.setattr(bridge.jobs, "launch", lambda job: None)

    def preflight(binary: str, cwd: str, env: dict[str, str], model: str, sandbox: str) -> Any:
        assert binary == str(wrapper) and cwd == bridge.store.get_task(task).worktree_path
        assert model == "synthetic-pin" and sandbox == "workspace-write"
        attempts = bridge.store.list_attempts(task)
        preflight_counts.append(len(attempts))
        assert all(a.pid is None for a in attempts)
        if refused is True and (not background or attempts):
            raise p.refusal("synthetic metadata refusal")
        if refused == "changed" and attempts:
            return ['model="changed-after-reservation"'], {"synthetic": True}
        return ['forced_login_method="chatgpt"'], {"inference_performed": False, "synthetic": True}

    monkeypatch.setattr(p, "prepare_live", preflight)
    try:
        if refused and not background:
            with pytest.raises(BridgeError) as err:
                bridge.run(task, mode="live", allow_model_usage=True)
            assert err.value.code == "PREFLIGHT_FAILED" and not bridge.store.list_attempts(task)
            assert bridge.status(task)["state"] == "READY"
        else:
            result = bridge.run(
                task,
                mode="live",
                allow_model_usage=True,
                background=background,
                idempotency_key="worker" if background else None,
            )
            if background:
                if refused == "env":
                    bridge.env["OPENAI_API_KEY"] = "synthetic-never-sent"
                assert bridge.jobs.execute(result["job_id"]) is (not refused)
                if refused:
                    assert bridge.jobs.status(result["job_id"])["error_code"] == (
                        "LIVE_GATE_CLOSED"
                        if refused == "env"
                        else "INTEGRITY_ERROR"
                        if refused == "changed"
                        else "PREFLIGHT_FAILED"
                    )
                    assert bridge.store.list_attempts(task)[0].pid is None
                    return
                assert preflight_counts == [0, 1]
            else:
                assert preflight_counts == [0]
                assert result["executor_outcome"] == "succeeded"
            assert bridge.artifacts(task)["verification"]["status"] == "passed"
            attempt = bridge.store.list_attempts(task)[0]
            assert attempt.invocation["argv"][1:3] == ["--config", 'forced_login_method="chatgpt"']
            assert any('"synthetic":true' in note for note in attempt.invocation["notes"])
    finally:
        bridge.close()
