"""Workbench loopback server: auth cookie, Host/Origin/CSRF guards, routes and SSE.

Only the test-owned 127.0.0.1 server is reachable; every other connection still trips the
suite-wide network guard.
"""

from __future__ import annotations

import base64
import http.client
import json
import socket
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.cli import main as cli_main
from harness_bridge.workbench.harness import CLAUDE
from harness_bridge.workbench.server import WorkbenchServer
from tests.integration.test_workbench import WB, wait_for

# Captured at import, before the suite-wide guard patches socket.connect for each test.
_REAL_CONNECT = socket.socket.connect


@pytest.fixture
def loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    guarded_connect = socket.socket.connect

    def connect(self: socket.socket, address: Any) -> Any:
        if self.family == socket.AF_INET and address[0] == "127.0.0.1":
            return _REAL_CONNECT(self, address)
        return guarded_connect(self, address)

    def create_connection(address: Any, timeout: Any = None, *args: Any, **kw: Any) -> Any:
        if address[0] != "127.0.0.1":
            raise RuntimeError(f"network access attempted in tests: {address!r}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if isinstance(timeout, int | float):
            sock.settimeout(timeout)
        sock.connect(address)
        return sock

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)


class Client:
    def __init__(self, server: WorkbenchServer) -> None:
        self.server = server
        self.cookie: str | None = None

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        headers: dict[str, str] | None = None,
        cookie: bool = True,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        hdrs = {"Host": f"127.0.0.1:{self.server.port}"}
        if cookie and self.cookie:
            hdrs["Cookie"] = self.cookie
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
            hdrs["X-RepoBridge"] = "1"
        hdrs.update(headers or {})
        conn.request(method, path, body=data, headers=hdrs)
        res = conn.getresponse()
        payload = res.read()
        conn.close()
        return res.status, dict(res.getheaders()), payload

    def login(self) -> None:
        status, headers, _ = self.request("GET", f"/auth?token={self.server.token}", cookie=False)
        assert status == 303 and headers["Location"] == "/"
        cookie = headers["Set-Cookie"]
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
        self.cookie = cookie.split(";", 1)[0]

    def api(self, method: str, path: str, body: Any = None) -> Any:
        status, _, payload = self.request(method, path, body if method == "POST" else None)
        data = json.loads(payload)
        assert data["ok"], (status, data)
        return data["result"]


@pytest.fixture
def served(loopback: None, tmp_path: Path) -> Iterator[tuple[WB, Client]]:
    fx = WB(tmp_path)
    wb = fx.open()
    server = WorkbenchServer(wb)
    server.start()
    client = Client(server)
    try:
        yield fx, client
    finally:
        wb.close(timeout=5)
        server.close()


def test_auth_cookie_host_origin_and_csrf_guards(served: tuple[WB, Client]) -> None:
    _, client = served
    status, _, _ = client.request("GET", "/api/state")
    assert status == 401
    status, _, _ = client.request("GET", "/auth?token=wrong", cookie=False)
    assert status == 401
    client.login()
    status, _, body = client.request("GET", "/api/state")
    assert status == 200 and json.loads(body)["ok"]
    status, _, _ = client.request("GET", "/api/state", headers={"Host": "evil.example:80"})
    assert status == 403
    port = client.server.port
    status, _, _ = client.request(
        "POST", "/api/projects", {"path": "/tmp"}, headers={"Origin": "http://evil.example"}
    )
    assert status == 403
    status, _, _ = client.request(
        "POST", "/api/projects", {"path": "/tmp"}, headers={"X-RepoBridge": "0"}
    )
    assert status == 403
    status, _, _ = client.request(
        "POST", "/api/projects", {"path": "/tmp"}, headers={"Content-Type": "text/plain"}
    )
    assert status == 415
    status, headers, page = client.request("GET", "/")
    assert status == 200 and b"RepoBridge" in page
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    status, _, _ = client.request("GET", "/static/../server.py")
    assert status == 404
    status, _, js = client.request("GET", "/static/vendor/xterm/xterm.js")
    assert status == 200 and len(js) > 100_000
    assert client.server.httpd.server_address[0] == "127.0.0.1"
    assert f"127.0.0.1:{port}" in client.server.hosts


def test_session_flow_over_http_and_sse(served: tuple[WB, Client]) -> None:
    fx, client = served
    client.login()
    project = client.api("POST", "/api/projects", {"path": str(fx.repo)})
    session = client.api(
        "POST", "/api/sessions", {"project_id": project["project_id"], "harness": CLAUDE}
    )
    sid = session["session_id"]

    conn = http.client.HTTPConnection("127.0.0.1", client.server.port, timeout=10)
    assert client.cookie is not None
    conn.request(
        "GET",
        "/api/stream",
        headers={"Host": f"127.0.0.1:{client.server.port}", "Cookie": client.cookie},
    )
    res = conn.getresponse()
    assert res.status == 200 and res.getheader("Content-Type", "").startswith("text/event-stream")
    seen: dict[str, list[Any]] = {}
    output = bytearray()

    def pump(until: Any, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        event = None
        while time.monotonic() < deadline:
            line = res.fp.readline().decode().rstrip("\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event:
                data = json.loads(line[6:])
                seen.setdefault(event, []).append(data)
                if event in ("output", "reset") and data.get("session_id") == sid:
                    output.extend(base64.b64decode(data["data"]))
                if until():
                    return
        raise AssertionError(f"stream condition not reached; saw {list(seen)}")

    pump(lambda: b"stub claude ready" in output)
    assert seen["state"][0]["projects"][0]["sessions"][0]["session_id"] == sid
    client.api("POST", f"/api/sessions/{sid}/resize", {"cols": 90, "rows": 25})
    client.api("POST", f"/api/sessions/{sid}/input", {"data": "hello\r"})
    pump(lambda: b"assistant: hello" in output)
    client.api("POST", f"/api/sessions/{sid}/input", {"b64": base64.b64encode(b"size\r").decode()})
    pump(lambda: output.count(b"[winch 90x25]") >= 2)
    pump(lambda: any(a["payload"].get("event") == "Stop" for a in seen.get("activity", [])))
    activity = client.api("GET", f"/api/sessions/{sid}/activity")
    assert any(e["payload"].get("event") == "UserPromptSubmit" for e in activity)
    tail = client.api("GET", f"/api/sessions/{sid}/output")
    assert tail["live"] and b"assistant: hello" in base64.b64decode(tail["data"])

    status, _, body = client.request(
        "POST", "/api/sessions", {"project_id": project["project_id"], "harness": "codex"}
    )
    error = json.loads(body)["error"]
    assert status == 409 and error["details"]["busy_session_id"] == sid

    client.api("POST", f"/api/sessions/{sid}/stop", {})
    wait_for(lambda: client.api("GET", f"/api/sessions/{sid}")["runs"][-1]["status"] == "stopped")
    detail = client.api("GET", f"/api/sessions/{sid}")
    assert detail["runs"][-1]["argv"][1] == "--session-id"
    status, _, body = client.request("POST", f"/api/sessions/{sid}/input", {"data": "x"})
    assert status == 409
    draft = client.api("POST", f"/api/sessions/{sid}/handoff/draft", {"target": "codex"})
    assert draft["note"].startswith("# 会话交接说明")
    status, _, _ = client.request("GET", f"/api/sessions/{sid}/diff?path=../../etc/passwd")
    assert status == 400
    conn.close()


def test_cli_exposes_app_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["app", "--help"]) == 0
    assert "--no-open" in capsys.readouterr().out


def test_prefs_native_and_dev_routes(served: tuple[WB, Client]) -> None:
    _, client = served
    client.login()
    state = client.api("GET", "/api/state")
    assert state["prefs"]["appearance"] == "system" and state["prefs"]["inspector_open"] is False
    assert state["native"] == [] and state["dev"] is False
    client.api("POST", "/api/prefs", {"appearance": "dark", "inspector_width": 480})
    status, _, body = client.request("POST", "/api/prefs", {"appearance": "neon"})
    assert status == 400 and "appearance" in json.loads(body)["error"]["message"]
    status, _, _ = client.request("POST", "/api/prefs", {"unknown_key": 1})
    assert status == 400
    assert client.api("GET", "/api/state")["prefs"]["appearance"] == "dark"
    # Without a native window, native calls are refused and dev routes do not exist.
    status, _, _ = client.request("POST", "/api/native/title", {"title": "x"})
    assert status == 404
    for route in ("/api/dev/snapshot", "/api/dev/reload", "/api/dev/resize"):
        status, _, _ = client.request("POST", route, {"name": "x"})
        assert status == 404
    # With hooks attached (as the pywebview window does), calls reach them; input is validated.
    calls: list[tuple[str, object]] = []
    wb = client.server.workbench
    wb.native = {
        "title": lambda t: calls.append(("title", t)),
        "appearance": lambda m: calls.append(("appearance", m)),
        "pick_folder": lambda: "/picked",
    }
    client.api("POST", "/api/native/title", {"title": "修复 — demo"})
    client.api("POST", "/api/native/appearance", {"mode": "light"})
    assert client.api("POST", "/api/native/pick-folder", {}) == "/picked"
    status, _, _ = client.request("POST", "/api/native/appearance", {"mode": "sepia"})
    assert status == 400
    assert calls == [("title", "修复 — demo"), ("appearance", "light")]
    assert client.api("GET", "/api/state")["native"] == ["appearance", "pick_folder", "title"]


def test_create_unstarted_archive_and_project_branch(served: tuple[WB, Client]) -> None:
    fx, client = served
    client.login()
    project = client.api("POST", "/api/projects", {"path": str(fx.repo)})
    session = client.api(
        "POST",
        "/api/sessions",
        {"project_id": project["project_id"], "harness": CLAUDE, "title": "later", "start": False},
    )
    sid = session["session_id"]
    state = client.api("GET", "/api/state")
    proj = state["projects"][0]
    assert proj["branch"] == "main" and proj["exists"] is True
    view = proj["sessions"][0]
    assert view["status"] == "new" and view["phase"] is None and view["archived"] == 0
    client.api("POST", f"/api/sessions/{sid}/archive", {})
    view = client.api("GET", "/api/state")["projects"][0]["sessions"][0]
    assert view["archived"] == 1, "archived sessions stay in the snapshot, flagged"
    client.api("POST", f"/api/sessions/{sid}/unarchive", {})
    assert client.api("GET", "/api/state")["projects"][0]["sessions"][0]["archived"] == 0


def test_conversation_routes_stream_events_and_validation(served: tuple[WB, Client]) -> None:
    fx, client = served
    client.login()
    project = client.api("POST", "/api/projects", {"path": str(fx.repo)})
    session = client.api(
        "POST",
        "/api/sessions",
        {"project_id": project["project_id"], "harness": CLAUDE, "view_mode": "conversation"},
    )
    sid = session["session_id"]
    assert session["view_mode"] == "conversation"
    conn = http.client.HTTPConnection("127.0.0.1", client.server.port, timeout=10)
    assert client.cookie is not None
    conn.request(
        "GET",
        "/api/stream",
        headers={"Host": f"127.0.0.1:{client.server.port}", "Cookie": client.cookie},
    )
    res = conn.getresponse()
    conv_events: list[dict[str, Any]] = []

    def pump(until: Any, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        event = None
        while time.monotonic() < deadline:
            line = res.fp.readline().decode().rstrip("\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event == "conv":
                conv_events.append(json.loads(line[6:]))
                if until():
                    return
        raise AssertionError("conv events not seen")

    client.api("POST", f"/api/sessions/{sid}/send", {"text": "hello", "client_id": "c-1"})
    pump(lambda: any(e.get("op") == "delta" for e in conv_events))
    pump(lambda: any(e.get("op") == "turn" and e["turn"] is None for e in conv_events))
    assert all(e["session_id"] == sid for e in conv_events)
    conv = client.api("GET", f"/api/sessions/{sid}/conversation")
    assert conv["live"] and [i["id"] for i in conv["items"] if i["type"] == "user"] == ["user:c-1"]

    client.api("POST", f"/api/sessions/{sid}/send", {"text": "edit h.txt"})
    perm = wait_for(
        lambda: [
            i
            for i in client.api("GET", f"/api/sessions/{sid}/conversation")["items"]
            if i["type"] == "permission" and i["status"] == "pending"
        ]
    )[0]
    status, _, body = client.request(
        "POST",
        f"/api/sessions/{sid}/permission",
        {"request_id": perm["request_id"], "decision": "allow", "answers": {"q": {"x": 1}}},
    )
    assert status == 400
    client.api(
        "POST",
        f"/api/sessions/{sid}/permission",
        {"request_id": perm["request_id"], "decision": "allow"},
    )
    wait_for(lambda: (fx.repo / "h.txt").exists())
    status, _, body = client.request("POST", f"/api/sessions/{sid}/view", {"view_mode": "sideways"})
    assert status == 400
    status, _, body = client.request("POST", f"/api/sessions/{sid}/desktop/open", {})
    assert status == 412 and "没有在" in json.loads(body)["error"]["message"]
    status, _, body = client.request("POST", f"/api/sessions/{sid}/send", {"text": "  "})
    assert status == 400
    conn.close()


def test_open_link_route_accepts_only_web_links(served: tuple[WB, Client]) -> None:
    _, client = served
    client.login()
    for url in ("javascript:alert(1)", "file:///etc/passwd", "codex://threads/x", "https://a b"):
        status, _, _ = client.request("POST", "/api/native/open-url", {"url": url})
        assert status == 400, url
    # A valid link still needs the native window (absent in tests): nothing is opened.
    status, _, _ = client.request("POST", "/api/native/open-url", {"url": "https://example.com/x"})
    assert status == 404


def test_settings_attachment_file_and_catalog_routes(served: tuple[WB, Client]) -> None:
    fx, client = served
    client.login()
    project = client.api("POST", "/api/projects", {"path": str(fx.repo)})
    session = client.api(
        "POST",
        "/api/sessions",
        {"project_id": project["project_id"], "harness": CLAUDE, "view_mode": "conversation"},
    )
    sid = session["session_id"]
    wait_for(lambda: client.api("GET", "/api/state")["catalogs"][CLAUDE]["status"] == "ok")
    view = client.api("POST", f"/api/sessions/{sid}/settings", {"model": "stub-sonnet"})
    assert view["chosen"] == {"model": "stub-sonnet"}
    status, _, _ = client.request("POST", f"/api/sessions/{sid}/settings", {"model": 3})
    assert status == 400
    status, _, body = client.request("POST", f"/api/sessions/{sid}/settings", {"effort": "max"})
    assert status == 400 and "思考强度" in json.loads(body)["error"]["message"]

    data = base64.b64encode(b"hello file\n").decode()
    att = client.api("POST", f"/api/sessions/{sid}/attachments", {"name": "a.txt", "data": data})
    assert att["kind"] == "file" and att["name"] == "a.txt" and "path" not in att
    status, _, _ = client.request(
        "POST", f"/api/sessions/{sid}/attachments", {"name": "a.txt", "data": "%%%"}
    )
    assert status == 400
    # Uploads may exceed the normal 1 MB body limit; other routes may not.
    big = base64.b64encode(b"x" * (2 << 20)).decode()
    att = client.api("POST", f"/api/sessions/{sid}/attachments", {"name": "b.log", "data": big})
    assert att["size"] == 2 << 20
    try:
        status, _, _ = client.request("POST", f"/api/sessions/{sid}/rename", {"title": big})
    except (ConnectionResetError, BrokenPipeError):
        status = 400  # refused before the body was read
    assert status == 400

    files = client.api("GET", f"/api/sessions/{sid}/files?q=read")
    assert files[0]["path"] == "README.md"
    assert client.api("POST", "/api/catalog/codex/refresh", {}) == {"probing": True}
    status, _, _ = client.request("POST", "/api/catalog/other/refresh", {})
    assert status == 404
    status, _, _ = client.request(
        "POST", f"/api/sessions/{sid}/send", {"text": "x", "attachments": "nope"}
    )
    assert status == 400
    wait_for(lambda: client.api("GET", "/api/state")["catalogs"]["codex"]["status"] == "ok")
