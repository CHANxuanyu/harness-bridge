"""Copied plugin resources + fresh CLI processes, simulated Executors only (not host activation)."""

from __future__ import annotations

import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.cli import _build_parser
from harness_bridge.coordination import GoalSpec
from harness_bridge.models import TaskSpec
from harness_bridge.planning import PlanBatch
from harness_bridge.workspace import checkout_fingerprint, git
from tests.conftest import Fixture
from tests.helpers.reviews import review_for

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "plugins/harness-bridge"


@pytest.fixture
def package(tmp_path: Path) -> Path:
    return Path(shutil.copytree(PACKAGE, tmp_path / "host-cache/plugin"))


@pytest.fixture
def runtime(tmp_path: Path) -> Path:
    file = tmp_path / "runtime with spaces"
    file.write_text(
        f"#!{sys.executable}\nfrom harness_bridge.cli import main\nraise SystemExit(main())\n"
    )
    file.chmod(0o700)
    return file


def load_checker(package: Path) -> Any:
    file = package / "skills/harness-bridge/scripts/check_connection.py"
    spec = importlib.util.spec_from_file_location("connection_probe", file)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(file: Path) -> Any:
    return json.loads(file.read_text())


def write(file: Path, value: Any) -> str:
    file.write_text(json.dumps(value))
    return str(file)


def check(package: Path, *args: str) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, str(package / "skills/harness-bridge/scripts/check_connection.py"), *args],
        cwd=package.parent,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def test_copied_manifests_references_examples_and_documented_commands(package: Path) -> None:
    versions = set()
    for name in ("plugin.json", ".codex-plugin/plugin.json", ".zcode-plugin/plugin.json"):
        manifest = read(package / name)
        versions.add(manifest["version"])
        assert manifest["name"] == "harness-bridge"
        if name != "plugin.json":
            assert (package / manifest["skills"] / "harness-bridge/SKILL.md").is_file()
    assert versions == {read(ROOT / "marketplace.json")["plugins"][0]["version"]}
    catalog = read(ROOT / ".agents/plugins/marketplace.json")["plugins"][0]
    assert (ROOT / catalog["source"]["path"]).resolve() == PACKAGE
    count = 0
    for file in package.rglob("*.md"):
        text = file.read_text()
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if "://" not in link:
                target = (file.parent / link.split("#")[0]).resolve()
                assert target.is_relative_to(package) and target.exists(), (file, link)
        for block in re.findall(r"```(?:sh|bash)\n(.*?)```", text, re.S):
            for command in block.replace("\\\n", " ").splitlines():
                argv = shlex.split(command)
                if argv and argv[0] == "hbridge":
                    _build_parser().parse_args(argv[1:])
                    count += 1
    assert count >= 20
    references = package / "skills/harness-bridge/references"
    GoalSpec.model_validate(read(references / "goal.example.json"))
    PlanBatch.model_validate(read(references / "plan.example.json"))
    TaskSpec.model_validate(read(references / "task.example.json"))


@pytest.mark.parametrize("existing", [False, True])
def test_checker_does_not_create_or_open_selected_state(
    package: Path, runtime: Path, tmp_path: Path, existing: bool
) -> None:
    state = tmp_path / "selected state"
    if existing:
        state.mkdir()
        (state / "bridge.sqlite3").write_bytes(b"old user database must not be opened")
        (state / "config.toml").write_text("not valid config")
    before = {p.name: p.read_bytes() for p in state.iterdir()} if existing else {}
    file = write(
        tmp_path / "connection.json",
        {"connection_version": 1, "runtime": str(runtime), "state_dir": str(state)},
    )
    code, report = check(package, "--connection", file)
    assert code == 0 and report["runtime_compatible"] is True
    assert report["state_inspected"] is False and report["inference_performed"] is False
    assert report["runtime"] == str(runtime) and report["state_dir"] == str(state)
    assert state.exists() is existing
    assert ({p.name: p.read_bytes() for p in state.iterdir()} if existing else {}) == before


@pytest.mark.parametrize("source", ["xdg", "home", "env", "explicit", "paths"])
def test_connection_resolution_precedence(
    package: Path, runtime: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    module = load_checker(package)
    home, config = tmp_path / "home", tmp_path / "config"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    default = home / ".config"
    if source != "home":
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
        default = config
    file = default / "harness-bridge/connection.json"
    file.parent.mkdir(parents=True)
    state = tmp_path / source
    write(file, {"connection_version": 1, "runtime": str(runtime), "state_dir": str(state)})
    args = {"connection": None, "runtime": None, "state_dir": None}
    if source == "env":
        monkeypatch.setenv("HBRIDGE_CONNECTION", str(file))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "wrong"))
    elif source in ("explicit", "paths"):
        monkeypatch.setenv("HBRIDGE_CONNECTION", str(tmp_path / "wrong.json"))
        if source == "explicit":
            args["connection"] = str(file)
        else:
            args.update(runtime=str(runtime), state_dir=str(state))
    parsed = module.argparse.Namespace(**args)
    assert module.connection(parsed) == (runtime, state)


@pytest.mark.parametrize(
    "change",
    [
        {"connection_version": True},
        {"connection_version": 2},
        {"extra": "no"},
        {"runtime": "relative"},
        {"runtime": "/missing/hbridge"},
        {"runtime": None},
        {"state_dir": "relative"},
        {"state_dir": 1},
        {"state_dir": "\0"},
    ],
)
def test_invalid_connection_refused_before_probe(
    package: Path, runtime: Path, tmp_path: Path, change: dict[str, Any]
) -> None:
    file = write(
        tmp_path / "connection.json",
        {
            "connection_version": 1,
            "runtime": str(runtime),
            "state_dir": str(tmp_path / "state"),
            **change,
        },
    )
    code, result = check(package, "--connection", file)
    assert code == 2 and result["ok"] is False
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("failure", ["version", "command", "option", "doctor", "json", "list"])
def test_incompatible_runtime_never_reports_connection(
    package: Path, runtime: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    module = load_checker(package)
    calls = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert str(tmp_path / "user-state") not in argv
        assert Path(kwargs["env"]["HOME"]).is_relative_to(Path(kwargs["cwd"]))
        code = 0
        if argv[-1] == "--version":
            out = "hbridge obsolete" if failure == "version" else "hbridge 0.1.0.dev1"
        elif argv[-1] == "--help":
            code = 2 if failure == "command" and "goal" in argv else 0
            out = (
                ""
                if failure == "option"
                else "--background --idempotency-key --after --wait --integration --branch"
            )
        else:
            assert argv[-2:] == ["doctor", "--offline"]
            out = json.dumps(
                {
                    "ok": True,
                    "bridge_version": "0.1.0.dev1",
                    "schema_version": "1.0",
                    "offline": True,
                    "inference_performed": failure == "doctor",
                }
            )
            if failure == "json":
                out = "private-output-not-JSON"
            if failure == "list":
                out = "[]"
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr="private-value")

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises((module.ConnectionError, ValueError)):
        module.probe(runtime, tmp_path / "user-state")
    assert all(a[-1] in ("--version", "--help", "--offline") for a in calls)


def test_cached_workflow_takeover_repair_integration_and_delivery(
    package: Path, fx: Fixture
) -> None:
    references = package / "skills/harness-bridge/references"
    goal = read(references / "goal.example.json")
    goal["repo"] = fx.spec()["repo"]
    file = write(fx.base / "goal.json", goal)
    _, created = fx.cli("goal", "create", "--file", file, "--idempotency-key", "goal")
    gid = created["goal_id"]
    claim = ["--advisor-binding", created["advisor_claim"]["binding_id"], "--advisor-epoch", "1"]
    before = checkout_fingerprint(str(fx.repo))
    batch = read(references / "plan.example.json")
    batch["children"][0]["task"]["verification"] = fx.spec()["verification"]
    file = write(fx.base / "plan.json", batch)
    _, planned = fx.cli("goal", "plan", gid, "--file", file, "--idempotency-key", "plan", *claim)
    child = planned["children"][0]["child_id"]
    _, task = fx.cli("child", "materialize", child, *claim)
    tid = task["task_id"]
    fx.cli("child", "preflight", child)

    def dispatch(key: str) -> dict[str, Any]:
        _, job = fx.cli("run", tid, "--background", "--idempotency-key", key, *claim)
        _, replay = fx.cli("run", tid, "--background", "--idempotency-key", key, *claim)
        assert replay["job_id"] == job["job_id"] and replay["replayed"]
        cursor, deadline = 0, time.monotonic() + 30
        while time.monotonic() < deadline:
            _, events = fx.cli("events", tid, "--after", str(cursor), "--wait", "1")
            assert events["next_cursor"] >= cursor
            cursor = events["next_cursor"]
            _, status = fx.cli("job", job["job_id"])
            if status["phase"] == "finished":
                assert status["executor_exit_confirmed"] is True
                return status
        raise AssertionError("worker did not finish")

    first = dispatch("initial")
    _, evidence = fx.cli("artifacts", tid)
    assert evidence["verification"]["status"] == "failed"
    fx.cli("artifacts", tid, "--show", "diff")
    _, projects = fx.cli("projects")
    assert projects["projects"][0]["goal_ids"] == [gid]
    takeover = write(
        fx.base / "takeover.json",
        {
            "advisor": {"host": "zcode", "native_session_ref": None},
            "expected_epoch": 1,
            "reason": "Offline fixture: another existing Advisor continues the same goal",
        },
    )
    _, taken = fx.cli("goal", "takeover", gid, "--file", takeover, "--idempotency-key", "takeover")
    review = write(fx.base / "repair.json", review_for(evidence, "changes_requested", "repair"))
    _, stale = fx.cli("review", tid, "--file", review, *claim, check_ok=False)
    assert stale["error"]["code"] == "STALE_ADVISOR"
    claim = ["--advisor-binding", taken["advisor_claim"]["binding_id"], "--advisor-epoch", "2"]
    fx.cli("review", tid, "--file", review, *claim)
    second = dispatch("repair")
    assert second["attempt_id"] != first["attempt_id"]
    _, evidence = fx.cli("artifacts", tid)
    assert evidence["verification"]["status"] == "passed"
    review = write(fx.base / "approve.json", review_for(evidence, "approve", "approve"))
    fx.cli("review", tid, "--file", review, *claim)
    file = write(
        fx.base / "integration.json",
        {
            "schema_version": "1.0",
            "task_ids": [tid],
            "verification": fx.spec()["verification"],
        },
    )
    _, integration = fx.cli(
        "goal", "integrate", gid, "--file", file, "--idempotency-key", "integrate", *claim
    )
    iid = integration["integration_id"]
    fx.cli("integration", "materialize", iid, *claim)
    fx.cli("integration", "verify", iid, "--idempotency-key", "acceptance", *claim)
    _, candidate = fx.cli("integration", "status", iid)
    review = write(
        fx.base / "integration-review.json",
        {
            **candidate["review_template"],
            "idempotency_key": "integrated-review",
        },
    )
    fx.cli("integration", "review", iid, "--file", review, *claim)
    _, delivered = fx.cli(
        "goal",
        "deliver",
        gid,
        "--integration",
        iid,
        "--branch",
        "bridge/result",
        "--idempotency-key",
        "delivery",
        *claim,
    )
    fx.cli("delivery", "status", delivered["delivery_id"])
    _, status = fx.cli("goal", "status", gid)
    assert status["state"] == "DELIVERED"
    assert (
        git(["rev-parse", "bridge/result"], cwd=fx.repo).stdout.decode().strip()
        == delivered["commit_sha"]
    )
    assert checkout_fingerprint(str(fx.repo)) == before
    fx.cli("goal", "cleanup", gid)  # preview only
    bridge = fx.bridge()
    try:
        assert len(bridge.store.list_tasks()) == 1
        assert len(bridge.store.list_attempts(tid)) == 2
    finally:
        bridge.close()
