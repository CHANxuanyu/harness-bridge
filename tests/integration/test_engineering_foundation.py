"""Engineering foundation acceptance: test-profile isolation, diagnostics, product events, export.

Offline/synthetic only: sandbox roots with stub CLIs (tests/helpers/wb_stub.py), synthetic native
histories, loopback HTTP. No real HOME/auth, CLI, desktop app, model or network. The desktop test
simulates the macOS capability gate (platform="darwin") and only records the opener's argv.
"""

from __future__ import annotations

import fcntl
import functools
import json
import os
import plistlib
import socket
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import pytest
from scripts.repobridge_sandbox import (
    MARKER,
    Client,
    Sandbox,
    add_late_proof,
    create,
    demo,
    scan_for_leaks,
    seed_codex,
    wait_for,
)

from harness_bridge import cli, runtime_env
from harness_bridge.errors import BridgeError
from harness_bridge.observability import report
from harness_bridge.workbench import app as app_module
from harness_bridge.workbench import desktop_apps
from harness_bridge.workbench import server as server_module
from harness_bridge.workbench import service as service_module
from harness_bridge.workbench.harness import CODEX, WorkbenchConfig
from harness_bridge.workbench.server import WorkbenchServer
from harness_bridge.workbench.service import Workbench
from tests.integration.test_workbench_server import loopback  # noqa: F401
from tests.unit.test_runtime_env import legacy_prod_state, snapshot

SRC = Path(__file__).resolve().parents[2] / "src" / "harness_bridge"
BASE_TABLES = {
    "meta",
    "projects",
    "sessions",
    "runs",
    "events",
    "handoffs",
    "native_links",
    "sqlite_sequence",
}


def open_wb(box: Sandbox, **env: str) -> Workbench:
    config = WorkbenchConfig(
        binaries=box.binaries(),
        discover=False,
        app_dirs=(str(box.apps),),
        opener=str(box.bin / "open"),
    )
    return Workbench(box.state, config=config, base_env=box.env(**env), stop_grace=1.0)


def turn_starts(box: Sandbox) -> int:
    log = box.stub_home / "codex-rpc.log"
    if not log.exists():
        return 0
    return sum(
        json.loads(line).get("method") == "turn/start" for line in log.read_text().splitlines()
    )


def diag(box: Sandbox) -> list[dict[str, Any]]:
    return report.load(box.state, "diag")


def product(box: Sandbox) -> list[dict[str, Any]]:
    return report.load(box.state, "product")


def link(wb: Workbench, box: Sandbox, native: str) -> str:
    pid = wb.add_project(str(box.repo))["project_id"]
    found = wb.native_history.discover(pid, CODEX)["items"]
    candidate = next(c for c in found if c["native_session_id"] == native)
    return str(wb.link_session(candidate["candidate_id"])["session"]["session"]["session_id"])


def unknown_then_proof(box: Sandbox, **env: str) -> dict[str, Any]:
    """Link → one ambiguous send → exact client-ID proof; returns the business outcome only."""
    native = seed_codex(box)
    wb = open_wb(box, WB_STUB_TURN_DELIVERY="exit", **env)
    try:
        sid = link(wb, box, native)
        wb.start_run(sid, "resume", confirm_external=True)
        wait_for(lambda: wb._live.get(sid) is not None and wb._live[sid].phase == "waiting")
        attachment = wb.add_attachment(sid, name="a.txt", data=b"synthetic")
        wb.send_message(sid, "one message", client_id="c-1", attachments=[attachment["id"]])
        wait_for(lambda: sid not in wb._live)
        first = wb.message_delivery(sid, "c-1")
        with pytest.raises(BridgeError) as blocked:
            wb.send_message(sid, "another", client_id="c-2")
        add_late_proof(box, native, "c-1", "one message")
        wb.conversation(sid, refresh=True)
        final = wb.message_delivery(sid, "c-1")
        run = wb.store.list_runs(sid)[-1]
        return {
            "first": first["delivery"]["state"],
            "blocked": blocked.value.details["reason"],
            "final": final["delivery"]["state"],
            "text": final["text"],
            "attachments": [a["name"] for a in final["attachments"]],
            "runs": len(wb.store.list_runs(sid)),
            "run_status": run["status"],
            "native_unchanged": wb.store.get_session(sid)["native_session_id"] == native,
            "turn_starts": turn_starts(box),
            "sid": sid,
            "run_id": run["run_id"],
            "original": first,
        }
    finally:
        wb.close(timeout=5)


@pytest.mark.usefixtures("loopback")
def test_demo_unknown_exact_proof_sent_stop_export_and_summary(tmp_path: Path) -> None:
    result = demo(tmp_path / "sandbox")
    assert result["passed"], result
    steps = result["steps"]
    assert steps["after_submit"] == "unknown" and steps["after_exact_proof"] == "sent"
    assert steps["second_send_refused"] == "delivery_unknown"
    assert steps["runs"] == 1 and steps["native_turn_start_calls"] == 1
    assert steps["attachment_retained"] and steps["native_id_unchanged"]
    trace = [e for e in result["send_trace_events"] if e.startswith("diag:delivery.state")]
    assert trace == [
        "diag:delivery.state(None->queued)",
        "diag:delivery.state(queued->sending)",
        "diag:delivery.state(sending->unknown)",
        "diag:delivery.state(unknown->sent)",
    ]
    with zipfile.ZipFile(result["bundle"]["bundle"]) as bundle:
        names = set(bundle.namelist())
        manifest = json.loads(bundle.read("manifest.json"))
        environment = json.loads(bundle.read("environment.json"))
    assert names == {
        "manifest.json",
        "environment.json",
        "diagnostics.jsonl",
        "summary.json",
        "summary.csv",
    }
    assert manifest["uploaded"] is False and manifest["contains_test_data"] is True
    assert {f["name"] for f in manifest["files"]} == names - {"manifest.json"}
    assert environment["env"] == "test" and environment["schema_revision"] == 4
    assert environment["code_sha"] == "unknown" or len(environment["code_sha"]) == 40
    assert result["summary_link"]["completed"] == 1
    assert result["summary_delivery"]["final_state"]["sent"] == 1
    assert result["summary_delivery"]["unknown_later_confirmed_sent"] == 1


def test_two_test_instances_are_isolated_and_path_conflicts_refused(tmp_path: Path) -> None:
    a, b = create(tmp_path / "a"), create(tmp_path / "b")
    wa, wb = open_wb(a), open_wb(b)
    try:
        wa.add_project(str(a.repo))
        assert [p["root_path"] for p in wb.store.list_projects()] == []
        assert wa.store.path.parent == a.state and wb.store.path.parent == b.state
        with pytest.raises(BridgeError, match="using this test root"):
            open_wb(a)
        alias = tmp_path / "alias"
        alias.symlink_to(a.root)
        with pytest.raises(BridgeError, match="using this test root"):
            open_wb(Sandbox(alias))
        cross = tmp_path / "c-state"
        for state in (a.state, cross):
            with pytest.raises(BridgeError, match="inside the test root"):
                Workbench(state, config=WorkbenchConfig(binaries=b.binaries()), base_env=b.env())
        assert not cross.exists()
        wrong_home = b.env(HOME=str(a.home))
        with pytest.raises(BridgeError, match="HOME"):
            Workbench(b.state, config=WorkbenchConfig(), base_env=wrong_home)
        assert turn_starts(a) == turn_starts(b) == 0  # no CLI was started by any of this
    finally:
        wa.close()
        wb.close()
    open_wb(a).close()  # released on close
    assert {r["event"] for r in diag(a)} >= {"app.start", "app.stop"}
    assert all(r["env"] == "test" for r in diag(a) + diag(b))


@pytest.mark.usefixtures("loopback")
def test_secret_markers_never_reach_logs_bundle_or_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    box = create(tmp_path / "sandbox")
    native = seed_codex(box, title=f"title {MARKER}")
    wb = open_wb(box, WB_STUB_CODEX_WRITER_BUSY="1", HBRIDGE_PRODUCT_EVENTS="1")
    server = WorkbenchServer(wb)
    server.start()
    try:
        api = Client(server.port, server.token)
        pid = api.api("POST", "/api/projects", {"path": str(box.repo), "name": MARKER})[
            "project_id"
        ]
        bad = api.api("POST", "/api/projects", {"path": f"/nonexistent/{MARKER}"}, ok=False)
        assert not bad["ok"]
        api.api("GET", f"/api/history?project_id={pid}&harness=codex&q={MARKER}")
        found = api.api("GET", f"/api/history?project_id={pid}&harness=codex&token={MARKER}")
        cid = next(c for c in found["items"] if c["native_session_id"] == native)["candidate_id"]
        sid = api.api("POST", "/api/sessions/link", {"candidate_id": cid})["session"]["session"][
            "session_id"
        ]
        api.api(
            "POST",
            f"/api/sessions/{sid}/attachments",
            {"name": f"{MARKER}.txt", "data": "U1lOVEhFVElDU0VDUkVUN0YzQQ=="},
        )
        # The native writer refuses resume with an error text that names the native thread ID.
        api.api(
            "POST",
            f"/api/sessions/{sid}/send",
            {"text": f"prompt {MARKER}", "client_id": "secret-client", "confirm_external": True},
            ok=False,
        )
        wait_for(lambda: sid not in wb._live and wb.store.list_runs(sid))
        assert native in (wb.store.list_runs(sid)[-1]["failure"] or "")  # the raw text exists
        conflict = api.api(
            "POST",
            f"/api/sessions/{sid}/send",
            {"text": f"changed {MARKER}", "client_id": "secret-client"},
            ok=False,
        )
        assert conflict["error"]["details"]["reason"] == "client_id_conflict"
        api.api("GET", f"/api/sessions/{sid}/conversation?refresh=1&x={MARKER}")
        api.api("GET", f"/api/sessions/{sid}/delivery?client_id={MARKER}", ok=False)

        def boom(*_a: Any, **_k: Any) -> None:
            raise RuntimeError(f"boom {MARKER} {native} {box.root}")

        monkeypatch.setattr(wb, "rename_session", boom)
        status, _, _ = api.request("POST", f"/api/sessions/{sid}/rename", {"title": MARKER})
        assert status == 500
    finally:
        server.close()
        wb.close(timeout=5)
    bundle = report.export_bundle(box.state, tmp_path / "b.zip", envs={"test"}, profile={})
    summary = report.summarize(box.state, envs={"test"})
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    (tmp_path / "summary.csv").write_text(report.to_csv(summary))
    leaks = scan_for_leaks(
        [
            box.state / "observability",
            Path(bundle["bundle"]),
            tmp_path / "summary.json",
            tmp_path / "summary.csv",
        ],
        {
            "marker": MARKER,
            "native": native,
            "root": str(box.root),
            "token": server.token,
            "client": "secret-client",
            "session_id": sid,
        },
    )
    assert leaks == {}
    records = diag(box)
    failures = [r for r in records if r["event"] == "op.end" and r.get("outcome") == "error"]
    assert {r.get("name") for r in failures} >= {"project.add", "session.send", "session.rename"}
    assert any(r.get("error_type") == "RuntimeError" for r in failures)
    assert any(r["event"] == "message.submit" and r.get("outcome") == "refused" for r in records)


@pytest.mark.parametrize("mode", ["disabled", "broken"])
def test_disabled_or_failing_sinks_do_not_change_business_results(
    tmp_path: Path, mode: str
) -> None:
    reference = unknown_then_proof(create(tmp_path / "ref"), HBRIDGE_PRODUCT_EVENTS="1")
    box = create(tmp_path / mode)
    if mode == "disabled":
        outcome = unknown_then_proof(box, HBRIDGE_DIAGNOSTICS="0", HBRIDGE_PRODUCT_EVENTS="0")
        assert not (box.state / "observability").exists()
    else:
        open_wb(box, HBRIDGE_DIAGNOSTICS="0", HBRIDGE_PRODUCT_EVENTS="0").close()  # claim
        (box.state / "observability").write_text("a file where the directory should be")
        outcome = unknown_then_proof(box, HBRIDGE_PRODUCT_EVENTS="1")
        assert (box.state / "observability").is_file()
    strip = ("sid", "run_id", "original")
    assert {k: v for k, v in outcome.items() if k not in strip} == {
        k: v for k, v in reference.items() if k not in strip
    }
    assert outcome["first"] == "unknown" and outcome["final"] == "sent"
    assert outcome["runs"] == 1 and outcome["turn_starts"] == 1


def test_duplicate_late_and_restart_events_do_not_inflate_counts(tmp_path: Path) -> None:
    box = create(tmp_path / "sandbox")
    outcome = unknown_then_proof(box, HBRIDGE_PRODUCT_EVENTS="1")
    wb = open_wb(box, HBRIDGE_PRODUCT_EVENTS="1")
    try:
        sid = outcome["sid"]
        # A racing old exit record cannot downgrade sent, so no transition is observed.
        wb._store_delivery(sid, outcome["run_id"], outcome["original"], evidence="native_protocol")
        for _ in range(3):
            wb.conversation(sid, refresh=True)
        assert wb.message_delivery(sid, "c-1")["delivery"]["state"] == "sent"
        # A refused connect attempt is attributed to a step with its stable reason.
        with pytest.raises(BridgeError):
            wb.start_run(sid, "new")
    finally:
        wb.close(timeout=5)
    transitions = [
        (r["attrs"].get("from_state"), r["attrs"]["to_state"])
        for r in product(box)
        if r["event"] == "delivery.state"
    ]
    assert transitions == [
        (None, "queued"),
        ("queued", "sending"),
        ("sending", "unknown"),
        ("unknown", "sent"),
    ]
    refused = [r for r in diag(box) if r["event"] == "connect.start" and r["outcome"] == "refused"]
    assert refused and refused[-1]["attrs"]["step"] == "request"
    assert refused[-1]["reason"] == "resume_required"
    summary = report.summarize(box.state, envs={"test"})["product"]
    assert summary["delivery"]["final_state"]["sent"] == 1
    assert summary["delivery"]["final_state"]["unknown"] == 0
    assert summary["delivery"]["unknown_later_confirmed_sent"] == 1
    assert summary["delivery"]["refused_submissions"] == 1
    assert summary["task_completion"] == "not_observable"
    assert summary["connect"]["spawned"] == 1 and summary["connect"]["ready"] == 1
    assert summary["connect"]["refused_by_step"] == {"request": 1}


def test_desktop_open_and_return_are_recorded_but_not_continuation_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        desktop_apps, "capability", functools.partial(desktop_apps.capability, platform="darwin")
    )
    box = create(tmp_path / "sandbox")
    contents = box.apps / "Codex.app" / "Contents"
    contents.mkdir(parents=True)
    info = {
        "CFBundleIdentifier": "com.openai.codex",
        "CFBundleShortVersionString": "1.0-stub",
        "CFBundleURLTypes": [{"CFBundleURLSchemes": ["codex"]}],
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    native = seed_codex(box)
    wb = open_wb(box, HBRIDGE_PRODUCT_EVENTS="1")
    try:
        sid = link(wb, box, native)
        result = wb.open_in_desktop(sid, release=True)
        assert result["status"] == "requested"
        assert box.opened.read_text().split()[-1] == f"codex://threads/{native}"
        wb.desktop_return(sid)
    finally:
        wb.close(timeout=5)
    events = {r["event"]: r for r in product(box)}
    assert events["desktop.open"]["outcome"] == "requested"
    assert events["desktop.return"]["attrs"]["had_hold"] is True
    desktop = report.summarize(box.state, envs={"test"})["product"]["desktop"]
    assert desktop["open_requests"] == {"requested": 1}
    assert desktop["return_confirmations"] == 1
    assert desktop["end_to_end_continuation"] == "not_observable"


@pytest.mark.usefixtures("loopback")
def test_no_outbound_network_and_no_schema_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for path in [SRC / "runtime_env.py", *(SRC / "observability").glob("*.py")]:
        text = path.read_text()
        for forbidden in (
            "import socket",
            "urllib",
            "http.client",
            "import requests",
            "import http",
        ):
            assert forbidden not in text, (path.name, forbidden)
    seen: list[Any] = []
    original = socket.socket.connect

    def audit(self: socket.socket, address: Any) -> Any:
        seen.append(address)
        return original(self, address)

    monkeypatch.setattr(socket.socket, "connect", audit)
    result = demo(tmp_path / "second")
    assert result["passed"]
    assert seen and all(
        isinstance(a, tuple) and a[0] in ("127.0.0.1", "::1", "localhost") for a in seen
    )
    db = sqlite3.connect(Path(result["sandbox"]) / "state" / "workbench.sqlite3")
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    revision = db.execute("SELECT value FROM meta WHERE key='schema_revision'").fetchone()[0]
    kinds = {r[0] for r in db.execute("SELECT DISTINCT kind FROM events")}
    db.close()
    assert tables == BASE_TABLES and revision == "4"
    assert not any(k.startswith(("diag", "obs", "product")) for k in kinds)


def test_cli_env_summary_export_trace_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    box = create(tmp_path / "sandbox")
    unknown_then_proof(box, HBRIDGE_PRODUCT_EVENTS="1")
    for key, value in box.env().items():
        monkeypatch.setenv(key, value)
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(key, raising=False)  # outer values would be refused (outside root)

    def run(*argv: str) -> tuple[int, Any]:
        code = cli.main([*argv, "--json"])
        out = capsys.readouterr().out
        return code, json.loads(out)

    code, env = run("env")
    assert code == 0 and env["env"] == "test" and env["isolation"] == "ok", env.get("refusal")
    assert env["schema_revision"] == 4 and env["native_env"] == "isolated"
    code, summary = run("diag", "summary")
    assert code == 0 and summary["contains_test_data"] is True
    assert summary["product"]["delivery"]["final_state"]["sent"] == 1
    code, other = run("diag", "summary", "--env", "prod")
    assert other["product"]["status"] == "unavailable"
    assert cli.main(["diag", "summary", "--format", "csv"]) == 0
    assert capsys.readouterr().out.startswith("section,metric,value")
    target = tmp_path / "out.zip"
    code, exported = run("diag", "export", "--out", str(target))
    assert (
        code == 0 and Path(exported["bundle"]) == target and target.stat().st_mode & 0o777 == 0o600
    )
    code, again = run("diag", "export", "--out", str(target))
    assert code == 2 and again["error"]["code"] == "USAGE_ERROR"
    msg = next(r["msg"] for r in diag(box) if r["event"] == "message.submit")
    code, traced = run("diag", "trace", "--msg", msg)
    events = [r["event"] for r in traced["records"]]
    assert code == 0 and {"delivery.state", "connect.start", "run.end"} <= set(events)
    monkeypatch.setenv("HBRIDGE_PRODUCT_EVENTS", "1")
    code, config = run("diag", "config", "--product-events", "off")
    assert code == 0 and config["changed"] == ["product_events"]
    assert config["settings"]["product_events"] is True  # the environment switch wins
    monkeypatch.delenv("HBRIDGE_PRODUCT_EVENTS")
    code, config = run("diag", "config")
    assert config["settings"]["product_events"] is False
    code, events = run("diag", "events")
    assert {"delivery.state", "session.link", "connect.start"} <= {
        e["event"] for e in events["events"]
    }
    assert not (box.state / "bridge.sqlite3").exists()  # diag commands never open task state


def test_recorder_construction_failure_does_not_block_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = service_module.Observability

    def flaky(state_dir: Path, *, env_name: str, env: dict[str, str]) -> Any:
        if env.get("HBRIDGE_DIAGNOSTICS") != "0":
            raise OSError("synthetic recorder failure")
        return real(state_dir, env_name=env_name, env=env)

    monkeypatch.setattr(service_module, "Observability", flaky)
    box = create(tmp_path / "sandbox")
    wb = open_wb(box)
    try:
        assert wb.obs.sinks == {} and wb.add_project(str(box.repo))["created"]
    finally:
        wb.close()
    assert not (box.state / "observability").exists()


ENTRIES = {
    "repobridge": lambda argv: app_module.main(argv),
    "hbridge app": lambda argv: cli.main(["app", *argv]),
}


def app_argv(box: Sandbox, state: Path) -> list[str]:
    return [
        "--no-open",
        "--port",
        "0",
        "--state-dir",
        str(state),
        "--claude-binary",
        str(box.bin / "claude"),
        "--codex-binary",
        str(box.bin / "codex"),
        "--dev-app-dir",
        str(box.apps),
        "--dev-opener",
        str(box.bin / "open"),
    ]


def use_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key in (
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
        "HBRIDGE_STATE_DIR",
        "HBRIDGE_ENV",
        "HBRIDGE_TEST_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("entry", list(ENTRIES))
def test_app_entries_refuse_before_any_directory_lock_or_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entry: str,
) -> None:
    def never(*_a: Any, **_k: Any) -> None:
        raise AssertionError("startup went past the environment preflight")

    monkeypatch.setattr(server_module, "WorkbenchServer", never)
    monkeypatch.setattr(service_module, "Workbench", never)
    start = ENTRIES[entry]
    box = create(tmp_path / "sandbox")
    use_env(monkeypatch, box.env())
    outside = tmp_path / "outside-state"
    assert start(app_argv(box, outside)) == 4
    assert not outside.exists()
    # A custom prod directory reused through inherited HBRIDGE_STATE_DIR, --state-dir or alias.
    custom = legacy_prod_state(tmp_path / "custom-prod")
    alias = tmp_path / "alias"
    alias.symlink_to(custom)
    before = snapshot(custom)
    use_env(monkeypatch, {"HBRIDGE_ENV": "dev", "HBRIDGE_STATE_DIR": str(custom)})
    assert start(["--no-open", "--port", "0"]) == 4
    use_env(monkeypatch, {"HBRIDGE_ENV": "dev"})
    for state in (custom, alias):
        assert start(["--no-open", "--port", "0", "--state-dir", str(state)]) == 4
    assert snapshot(custom) == before and not (custom / "workbench" / "app.lock").exists()
    # A legal configuration whose test root is held by another running instance.
    use_env(monkeypatch, box.env())
    held = runtime_env.TestRootLock(box.root)
    fresh = box.root / "state-2"
    try:
        assert start(app_argv(box, fresh)) == 4
    finally:
        held.release()
    assert not fresh.exists()
    assert list(box.state.iterdir()) == []  # the sandbox's own state was never touched
    assert capsys.readouterr().err.count("RepoBridge did not start") == 5
    assert turn_starts(box) == 0


@pytest.mark.parametrize("entry", list(ENTRIES))
def test_app_entries_start_cleanly_and_release_everything_after_a_midway_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    start = ENTRIES[entry]
    box = create(tmp_path / "sandbox")
    use_env(monkeypatch, box.env())
    served: list[str] = []
    monkeypatch.setattr(app_module, "_wait_for_signal", lambda: served.append("served"))
    assert start(app_argv(box, box.state)) == 0
    assert served == ["served"] and runtime_env.state_owner(box.state) == "test"
    runtime_env.TestRootLock(box.root).release()  # released after a clean stop

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("synthetic bind failure")

    monkeypatch.setattr(server_module, "WorkbenchServer", boom)
    with pytest.raises(OSError, match="synthetic bind failure"):
        start(app_argv(box, box.state))
    runtime_env.TestRootLock(box.root).release()  # test-root lock released
    fd = os.open(box.state / "workbench" / "app.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # App single-instance lock released
    finally:
        os.close(fd)
    assert [r["event"] for r in diag(box)].count("app.stop") == 2  # Workbench closed each time
    assert turn_starts(box) == 0


def test_same_client_id_in_two_sessions_stays_separate_end_to_end(tmp_path: Path) -> None:
    box = create(tmp_path / "sandbox")
    native_a, native_b = seed_codex(box, title="A"), seed_codex(box, title="B")
    wb = open_wb(box, HBRIDGE_PRODUCT_EVENTS="1")
    try:
        sid_a, sid_b = link(wb, box, native_a), link(wb, box, native_b)
        wb.send_message(sid_a, "same text", client_id="same-id", confirm_external=True)
        wait_for(lambda: wb.message_delivery(sid_a, "same-id")["delivery"]["state"] == "sent")
        wait_for(lambda: wb._live.get(sid_a) is not None and wb._live[sid_a].phase == "waiting")
        wb.stop(sid_a)
        wait_for(lambda: sid_a not in wb._live)
    finally:
        wb.close(timeout=5)
    wb = open_wb(box, WB_STUB_TURN_DELIVERY="exit", HBRIDGE_PRODUCT_EVENTS="1")
    try:
        wb.send_message(sid_b, "same text", client_id="same-id", confirm_external=True)
        wait_for(lambda: wb.message_delivery(sid_b, "same-id")["delivery"]["state"] == "unknown")
        wait_for(lambda: sid_b not in wb._live)
        assert wb.send_message(sid_b, "same text", client_id="same-id")["reused"]
        for _ in range(2):
            for sid in (sid_a, sid_b):
                wb.conversation(sid, refresh=True)
        assert wb.message_delivery(sid_a, "same-id")["delivery"]["state"] == "sent"
        assert wb.message_delivery(sid_b, "same-id")["delivery"]["state"] == "unknown"
    finally:
        wb.close(timeout=5)
    assert turn_starts(box) == 2
    records = product(box)
    submits = [r for r in records if r["event"] == "message.submit"]
    assert len({r["msg"] for r in submits}) == 2
    assert all(r["v"] == 2 for r in records)
    delivery = report.summarize(box.state, envs={"test"})["product"]["delivery"]
    assert delivery["submitted"] == 2
    assert delivery["final_state"]["sent"] == 1 and delivery["final_state"]["unknown"] == 1
    assert delivery["unknown_later_confirmed_sent"] == 0
    assert delivery["reused_submissions"] == 1


@pytest.mark.parametrize("marker", ["CLAUDE_CODE_REMOTE", "CLAUDECODE"])
def test_cloud_and_nested_markers_still_refuse_native_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    """Deterministic stub fixture: with a marker present, no run, resume or turn starts."""
    monkeypatch.setenv(marker, "1")
    box = create(tmp_path / "sandbox")
    assert box.env()[marker] == "1"  # the sandbox inherits gate markers
    native = seed_codex(box)
    wb = open_wb(box)
    try:
        sid = link(wb, box, native)
        with pytest.raises(BridgeError) as started:
            wb.start_run(sid, "resume", confirm_external=True)
        with pytest.raises(BridgeError) as sent:
            wb.send_message(sid, "hello", client_id="gate", confirm_external=True)
        assert started.value.code == sent.value.code == "PREFLIGHT_FAILED"
        assert wb.store.list_runs(sid) == []
    finally:
        wb.close(timeout=5)
    log = box.stub_home / "codex-rpc.log"
    methods = (
        [json.loads(x)["method"] for x in log.read_text().splitlines()] if log.exists() else []
    )
    assert "thread/resume" not in methods and "turn/start" not in methods
    refused = [r for r in diag(box) if r["event"] == "connect.start"]
    assert len(refused) == 2
    assert all(r["outcome"] == "refused" and r["attrs"]["step"] == "preflight" for r in refused)
