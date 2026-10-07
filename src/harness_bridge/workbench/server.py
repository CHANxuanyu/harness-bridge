"""Loopback HTTP + SSE server for the workbench window (stdlib only).

Only 127.0.0.1 is bound. Every request needs the per-launch token cookie (obtained once through
``/auth?token=…``) and a matching Host header; state-changing requests also need a JSON body, the
``X-RepoBridge`` header and, when the browser sends one, a same-origin ``Origin``. This keeps other
web pages and DNS-rebinding hosts from driving native session processes.
"""

from __future__ import annotations

import base64
import hmac
import json
import mimetypes
import queue
import re
import secrets
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from harness_bridge.errors import BridgeError
from harness_bridge.workbench.service import Workbench

STATIC_DIR = Path(__file__).with_name("static")
MAX_BODY = 1 << 20
_SESSION_PATH = re.compile(r"^/api/sessions/(ses_[0-9a-f]{12})(?:/([a-z/-]+))?$")
_PROJECT_PATH = re.compile(r"^/api/projects/(prj_[0-9a-f]{12})/([a-z-]+)$")
_STATUS = {
    "INVALID_INPUT": HTTPStatus.BAD_REQUEST,
    "USAGE_ERROR": HTTPStatus.BAD_REQUEST,
    "NOT_FOUND": HTTPStatus.NOT_FOUND,
    "STATE_CONFLICT": HTTPStatus.CONFLICT,
    "PREFLIGHT_FAILED": HTTPStatus.PRECONDITION_FAILED,
    "EXECUTOR_ERROR": HTTPStatus.BAD_GATEWAY,
}
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)


_LOCKED_PAGE = (
    "<!doctype html><meta charset=utf-8><title>RepoBridge</title>"
    "<body style='font:14px -apple-system,sans-serif;background:#0f1115;color:#d9dce3;"
    "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
    "<p>请从 RepoBridge App 打开此页面（启动链接只在本次运行中有效）。</p>"
).encode()


class WorkbenchServer:
    def __init__(
        self,
        workbench: Workbench,
        *,
        port: int = 0,
        token: str | None = None,
        static_dir: Path = STATIC_DIR,
    ) -> None:
        self.workbench = workbench
        self.token = token or secrets.token_urlsafe(32)
        self.static_dir = static_dir.resolve()
        self.closing = threading.Event()
        handler = _make_handler(self)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.httpd.daemon_threads = True
        self.port = int(self.httpd.server_address[1])
        self.cookie_name = f"rb_{self.port}"
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.origins = {f"http://{h}" for h in self.hosts}
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def auth_url(self) -> str:
        return f"{self.base_url}/auth?token={self.token}"

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self.closing.set()
        self.httpd.shutdown()
        self.httpd.server_close()


def _make_handler(server: WorkbenchServer) -> type[BaseHTTPRequestHandler]:
    wb = server.workbench

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "RepoBridge"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            return  # never log request lines: /auth carries the launch token

        # --- plumbing ---------------------------------------------------------------------

        def _send(
            self,
            status: int,
            body: bytes,
            content_type: str,
            extra: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _error(self, status: int, code: str, message: str, **details: Any) -> None:
            error: dict[str, Any] = {"code": code, "message": message}
            if details:
                error["details"] = details
            self._json(status, {"ok": False, "error": error})

        def _cookie_ok(self) -> bool:
            raw = self.headers.get("Cookie", "")
            for part in raw.split(";"):
                name, _, value = part.strip().partition("=")
                if name == server.cookie_name and hmac.compare_digest(
                    value.encode(), server.token.encode()
                ):
                    return True
            return False

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in server.hosts

        def _guard(self, mutating: bool) -> bool:
            if not self._host_ok():
                self._error(HTTPStatus.FORBIDDEN, "FORBIDDEN", "unexpected Host header")
                return False
            if not self._cookie_ok():
                if self.path.startswith("/api/"):
                    self._error(
                        HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "open RepoBridge from the App"
                    )
                else:
                    self._send(HTTPStatus.UNAUTHORIZED, _LOCKED_PAGE, "text/html; charset=utf-8")
                return False
            if mutating:
                origin = self.headers.get("Origin")
                if origin is not None and origin not in server.origins:
                    self._error(HTTPStatus.FORBIDDEN, "FORBIDDEN", "cross-origin request")
                    return False
                if self.headers.get("X-RepoBridge") != "1":
                    self._error(HTTPStatus.FORBIDDEN, "FORBIDDEN", "missing X-RepoBridge header")
                    return False
                ctype = self.headers.get("Content-Type", "")
                if not ctype.startswith("application/json"):
                    self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "INVALID_INPUT", "JSON only")
                    return False
            return True

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise BridgeError("INVALID_INPUT", "request body too large")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                value = json.loads(raw or b"{}")
            except ValueError:
                raise BridgeError("INVALID_INPUT", "malformed JSON") from None
            if not isinstance(value, dict):
                raise BridgeError("INVALID_INPUT", "JSON object expected")
            return value

        def _run(self, fn: Callable[[], Any]) -> None:
            try:
                result = fn()
            except BridgeError as err:
                self._json(
                    _STATUS.get(err.code, HTTPStatus.BAD_REQUEST),
                    {"ok": False, "error": err.to_dict()},
                )
                return
            except Exception as exc:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", type(exc).__name__)
                return
            self._json(HTTPStatus.OK, {"ok": True, "result": result})

        # --- routes -----------------------------------------------------------------------

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path == "/auth":
                self._auth(parse_qs(url.query).get("token", [""])[0])
                return
            if not self._guard(False):
                return
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = url.path
            if path == "/":
                self._static("index.html")
            elif path.startswith("/static/"):
                self._static(path[len("/static/") :])
            elif path == "/api/state":
                self._run(wb.snapshot)
            elif path == "/api/stream":
                self._stream()
            elif m := _SESSION_PATH.match(path):
                sid, action = m.group(1), m.group(2)
                if action is None:
                    self._run(lambda: wb.session_detail(sid))
                elif action == "output":
                    self._run(lambda: wb.output(sid))
                elif action == "activity":
                    after = int(query.get("after", "0") or 0)
                    self._run(lambda: wb.activity(sid, after))
                elif action == "changes":
                    self._run(lambda: wb.changes(sid))
                elif action == "diff":
                    self._run(lambda: wb.diff(sid, query.get("path", "")))
                else:
                    self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "unknown route")
            else:
                self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "unknown route")

        def do_POST(self) -> None:
            if not self._guard(True):
                return
            path = urlsplit(self.path).path
            try:
                body = self._body()
            except BridgeError as err:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": err.to_dict()})
                return
            if path == "/api/harnesses/refresh":
                self._run(lambda: [h.to_dict() for h in wb.harnesses(refresh=True).values()])
            elif path == "/api/projects":
                self._run(lambda: wb.add_project(_str(body, "path"), body.get("name")))
            elif path == "/api/sessions":
                self._run(
                    lambda: wb.create_session(
                        _str(body, "project_id"), _str(body, "harness"), title=body.get("title")
                    )
                )
            elif m := _PROJECT_PATH.match(path):
                pid, action = m.group(1), m.group(2)
                if action == "archive":
                    self._run(lambda: wb.archive_project(pid))
                else:
                    self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "unknown route")
            elif m := _SESSION_PATH.match(path):
                self._session_post(m.group(1), m.group(2) or "", body)
            else:
                self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "unknown route")

        def _session_post(self, sid: str, action: str, body: dict[str, Any]) -> None:
            if action == "input":
                self._run(lambda: wb.write_input(sid, _input_bytes(body)))
            elif action == "resize":
                self._run(lambda: wb.resize(sid, _int(body, "cols"), _int(body, "rows")))
            elif action == "start":
                self._run(lambda: wb.start_run(sid, _str(body, "kind")))
            elif action == "stop":
                self._run(lambda: wb.stop(sid))
            elif action == "rename":
                self._run(lambda: wb.rename_session(sid, _str(body, "title")))
            elif action == "archive":
                self._run(lambda: wb.archive_session(sid))
            elif action == "handoff/draft":
                self._run(
                    lambda: wb.handoff_draft(
                        sid, _str(body, "target"), str(body.get("progress") or "")
                    )
                )
            elif action == "handoff":
                self._run(
                    lambda: wb.create_handoff(
                        sid,
                        _str(body, "target"),
                        _str(body, "note"),
                        send_as_prompt=bool(body.get("send_as_prompt")),
                        title=body.get("title"),
                    )
                )
            else:
                self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "unknown route")

        def _auth(self, token: str) -> None:
            if not self._host_ok() or not hmac.compare_digest(
                token.encode(), server.token.encode()
            ):
                self._error(HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "invalid launch token")
                return
            cookie = f"{server.cookie_name}={server.token}; HttpOnly; SameSite=Strict; Path=/"
            self._send(
                HTTPStatus.SEE_OTHER,
                b"",
                "text/plain",
                {"Location": "/", "Set-Cookie": cookie},
            )

        def _static(self, rel: str) -> None:
            target = (server.static_dir / rel).resolve()
            if server.static_dir not in target.parents or not target.is_file():
                self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "no such file")
                return
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            extra = {"Content-Security-Policy": _CSP} if target.suffix == ".html" else None
            self._send(HTTPStatus.OK, target.read_bytes(), ctype, extra)

        def _stream(self) -> None:
            sub = wb.subscribe()
            self.close_connection = True
            try:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                self._event("state", wb.snapshot())
                for tail in wb.live_tails():
                    self._event("reset", tail)
                idle = 0
                while not server.closing.is_set() and not sub.overflowed:
                    try:
                        kind, data = sub.queue.get(timeout=1.0)
                    except queue.Empty:
                        idle += 1
                        if idle >= 15:
                            idle = 0
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                        continue
                    idle = 0
                    self._event(kind, data)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            finally:
                wb.unsubscribe(sub)

        def _event(self, kind: str, data: Any) -> None:
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            self.wfile.write(f"event: {kind}\ndata: {payload}\n\n".encode())
            self.wfile.flush()

    return Handler


def _str(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        raise BridgeError("INVALID_INPUT", f"{key} must be a string")
    return value


def _input_bytes(body: dict[str, Any]) -> bytes:
    if isinstance(body.get("b64"), str):
        try:
            return base64.b64decode(body["b64"], validate=True)
        except ValueError:
            raise BridgeError("INVALID_INPUT", "b64 is not valid base64") from None
    return _str(body, "data").encode("utf-8")


def _int(body: dict[str, Any], key: str) -> int:
    value = body.get(key)
    if type(value) is not int:
        raise BridgeError("INVALID_INPUT", f"{key} must be an integer")
    return value
