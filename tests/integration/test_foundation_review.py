"""Independent PR #5 regression: actual entry lifecycle, marker gate and sink fault parity.

Only test-owned state, loopback sockets and explicit stub harnesses; no platform override.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import queue
import socket
import threading
import zipfile
from pathlib import Path
from typing import Any

import pytest
from scripts.repobridge_sandbox import create

from harness_bridge import config, runtime_env
from harness_bridge.errors import BridgeError
from harness_bridge.observability import sink as sink_module
from harness_bridge.workbench import app as app_module
from harness_bridge.workbench import server as server_module
from harness_bridge.workbench import service as service_module
from harness_bridge.workbench.harness import CLAUDE, CODEX
from tests.integration.test_engineering_foundation import (
    ENTRIES,
    app_argv,
    open_wb,
    turn_starts,
    unknown_then_proof,
    use_env,
)
from tests.integration.test_workbench_server import loopback  # noqa: F401


@pytest.mark.parametrize("entry", list(ENTRIES))
@pytest.mark.parametrize("failure_at", ["thread_start", "after_start", "serve"])
def test_actual_entries_release_bound_http_on_startup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str, failure_at: str
) -> None:
    """A bound listener must close even if start fails before cleanup registration."""
    box = create(tmp_path / "box")
    use_env(monkeypatch, box.env())
    servers: list[Any] = []
    real_server = server_module.WorkbenchServer
    original_thread_start = threading.Thread.start

    class FaultServer(real_server):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            servers.append(self)

        def start(self) -> None:
            if failure_at == "thread_start":
                with monkeypatch.context() as patch:

                    def fail_target(thread: threading.Thread) -> None:
                        if getattr(thread, "_target", None) == self.httpd.serve_forever:
                            raise RuntimeError("synthetic HTTP thread start failure")
                        original_thread_start(thread)

                    patch.setattr(threading.Thread, "start", fail_target)
                    super().start()
            else:
                super().start()
                if failure_at == "after_start":
                    raise RuntimeError("synthetic HTTP after start failure")

    def fail_serve(*_args: Any) -> None:
        raise RuntimeError("synthetic HTTP serve failure")

    monkeypatch.setattr(server_module, "WorkbenchServer", FaultServer)
    monkeypatch.setattr(app_module, "_serve", fail_serve)
    try:
        with pytest.raises(RuntimeError, match="synthetic HTTP"):
            ENTRIES[entry](app_argv(box, box.state))
        assert len(servers) == 1
        server = servers[0]
        assert server.httpd.socket.fileno() == -1, "bound HTTP socket leaked after startup failure"
        assert server._thread is None or not server._thread.is_alive()
        assert not server.workbench._notifier.is_alive(), "Workbench notification thread leaked"
        runtime_env.TestRootLock(box.root).release()
        fd = os.open(box.state / "workbench/app.lock", os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        # Rebind the same port: verify actual resource release, not just a close callback.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", server.port))
        monkeypatch.setattr(server_module, "WorkbenchServer", real_server)
        monkeypatch.setattr(app_module, "_serve", lambda *_args: None)
        assert ENTRIES[entry](app_argv(box, box.state)) == 0
        assert turn_starts(box) == 0
    finally:
        # Also clean up the known failing revision, so regression evidence leaves no listener.
        for server in servers:
            if server._thread is not None and server._thread.is_alive():
                server.httpd.shutdown()
                server._thread.join(3)
            server.httpd.server_close()


@pytest.mark.parametrize("marker", [*config.CLOUD_ENV_MARKERS, *config.NESTED_ENV_MARKERS])
@pytest.mark.parametrize("harness", [CLAUDE, CODEX])
def test_every_inherited_marker_refuses_actual_start_and_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marker: str, harness: str
) -> None:
    monkeypatch.setenv(marker, "1")
    box = create(tmp_path / "box")
    assert box.env()[marker] == "1"
    wb = open_wb(box)
    try:
        project = wb.add_project(str(box.repo))
        sid = wb.create_session(
            project["project_id"], harness, start=False, view_mode="conversation"
        )["session_id"]
        with pytest.raises(BridgeError) as start:
            wb.start_run(sid, "new")
        with pytest.raises(BridgeError) as send:
            wb.send_message(sid, "synthetic gate message", client_id="gate")
        assert start.value.code == send.value.code == "PREFLIGHT_FAILED"
        assert wb.store.list_runs(sid) == []
        assert sid not in wb._live
        assert not (box.stub_home / "codex-rpc.log").exists()
        assert not (box.stub_home / "claude-controls.log").exists()
    finally:
        wb.close()


@pytest.mark.parametrize("failure", ["initialize", "queue_full", "write"])
def test_diagnostic_failures_preserve_delivery_and_run_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    reference = unknown_then_proof(create(tmp_path / "reference"))
    real_observability = service_module.Observability
    sinks: list[Any] = []

    def instrument(state: Path, *, env_name: str, env: dict[str, str]) -> Any:
        if failure == "initialize" and env.get("HBRIDGE_DIAGNOSTICS") != "0":
            raise OSError("synthetic recorder initialization failure")
        obs = real_observability(state, env_name=env_name, env=env)
        sinks.extend(obs.sinks.values())
        if failure == "queue_full":
            # Exercise the real bounded submit path; force put_nowait to report saturation.
            def full(_line: str) -> None:
                raise queue.Full

            for sink in obs.sinks.values():
                monkeypatch.setattr(sink._queue, "put_nowait", full)
        return obs

    def write_failure(_sink: Any, _data: bytes, _size: int) -> None:
        raise OSError(errno.ENOSPC, "synthetic full diagnostic disk")

    with monkeypatch.context() as patch:
        patch.setattr(service_module, "Observability", instrument)
        if failure == "write":
            patch.setattr(sink_module.JsonlSink, "_append", write_failure)
        actual = unknown_then_proof(create(tmp_path / failure))
    ignored = {"sid", "run_id", "original"}
    assert {k: v for k, v in actual.items() if k not in ignored} == {
        k: v for k, v in reference.items() if k not in ignored
    }
    assert actual["first"] == "unknown" and actual["final"] == "sent"
    assert actual["run_status"] == "failed" and actual["turn_starts"] == actual["runs"] == 1
    if failure == "queue_full":
        assert sum(s.stats["dropped_full"] for s in sinks) > 0
    elif failure == "write":
        assert sum(s.stats["write_errors"] for s in sinks) > 0


@pytest.mark.usefixtures("loopback")
def test_http_same_client_id_has_independent_alias_operations_latency_and_export(
    tmp_path: Path,
) -> None:
    from scripts.repobridge_sandbox import Client, scan_for_leaks, seed_codex, wait_for

    from harness_bridge.observability import report
    from tests.integration.test_engineering_foundation import link

    box = create(tmp_path / "http")
    native_a, native_b = seed_codex(box, title="A"), seed_codex(box, title="B")
    wb = open_wb(box, HBRIDGE_PRODUCT_EVENTS="1")
    server = server_module.WorkbenchServer(wb)
    server.start()
    text, cid = "synthetic-private-body-ef4", "synthetic-private-client-ef4"
    try:
        api = Client(server.port, server.token)
        sid_a, sid_b = link(wb, box, native_a), link(wb, box, native_b)
        path_a, path_b = f"/api/sessions/{sid_a}", f"/api/sessions/{sid_b}"
        api.api(
            "POST", path_a + "/send", {"text": text, "client_id": cid, "confirm_external": True}
        )
        wait_for(lambda: wb.message_delivery(sid_a, cid)["delivery"]["state"] == "sent")
        wait_for(lambda: sid_a in wb._live and wb._live[sid_a].phase == "waiting")
        before_a = wb.obs.message_latency(sid_a, cid)
        api.api("POST", path_a + "/stop", {})
        wait_for(lambda: sid_a not in wb._live)
        wb.base_env["WB_STUB_TURN_DELIVERY"] = "exit"
        api.api(
            "POST", path_b + "/send", {"text": text, "client_id": cid, "confirm_external": True}
        )
        wait_for(
            lambda: (
                sid_b not in wb._live
                and wb.message_delivery(sid_b, cid)["delivery"]["state"] == "unknown"
            )
        )
        before_b = wb.obs.message_latency(sid_b, cid)
        for path in (path_a, path_b):
            assert api.api("POST", path + "/send", {"text": text, "client_id": cid})["reused"]
            for _ in range(2):
                api.api("GET", path + "/conversation?refresh=1")
        assert before_a is not None and wb.obs.message_latency(sid_a, cid) >= before_a
        assert before_b is not None and wb.obs.message_latency(sid_b, cid) >= before_b
        assert wb.message_delivery(sid_a, cid)["delivery"]["state"] == "sent"
        assert wb.message_delivery(sid_b, cid)["delivery"]["state"] == "unknown"
        assert wb.store.list_runs(sid_b)[-1]["status"] == "failed"
        alias_a, alias_b = wb.obs.message_alias(sid_a, cid), wb.obs.message_alias(sid_b, cid)
        assert alias_a != alias_b
    finally:
        wb.close()
        server.close()
    summary = report.summarize(box.state, envs={"test"})
    delivery = summary["product"]["delivery"]
    assert (
        delivery["submitted"],
        delivery["final_state"]["sent"],
        delivery["final_state"]["unknown"],
    ) == (2, 1, 1)
    assert delivery["unknown_later_confirmed_sent"] == 0
    assert delivery["reused_submissions"] == 2 and turn_starts(box) == 2
    assert summary["product"]["task_completion"] == "not_observable"
    assert set(summary["samples"]["record_versions"]) == {"2"}
    rows = report.load(box.state, "diag")
    for alias, other in ((alias_a, alias_b), (alias_b, alias_a)):
        own = [r for r in rows if r.get("msg") == alias]
        submit = next(
            r for r in own if r["event"] == "message.submit" and r.get("outcome") == "accepted"
        )
        transitions = [r for r in own if r["event"] == "delivery.state"]
        assert transitions and all(r["op"] == submit["op"] for r in transitions)
        traced = report.trace(box.state, msg=alias)["records"]
        assert all(r.get("msg") != other for r in traced)
        assert any(r["event"] == "op.end" and r["op"] == submit["op"] for r in traced)
    bundle = report.export_bundle(box.state, tmp_path / "local.zip", envs={"test"}, profile={})
    assert bundle["uploaded"] is False
    with zipfile.ZipFile(bundle["bundle"]) as archive:
        exported = json.loads(archive.read("summary.json"))
        assert exported["product"]["delivery"] == delivery
        assert all(
            json.loads(line)["v"] == 2 for line in archive.read("diagnostics.jsonl").splitlines()
        )
    assert (
        scan_for_leaks(
            [box.state / "observability", Path(bundle["bundle"])],
            {
                "body": text,
                "client": cid,
                "root": str(box.root),
                "auth": server.token,
                "a": sid_a,
                "b": sid_b,
                "native_a": native_a,
                "native_b": native_b,
            },
        )
        == {}
    )
