"""Bounded offline protocol client; the outer runner owns deadlines and process groups.

This module cannot select native mode. It talks only to an explicitly supplied stand-in.
Native request shapes are based on installed ZCode 0.16.9; live permission/account semantics
remain unqualified. Raw snapshots, messages, reasoning and credentials never reach receipts.
"""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
from collections import deque
from typing import Any

from harness_bridge.adapters.zcode import session_id
from harness_bridge.models import ZCodeExecutorSpec

MAX_LINE = 1024 * 1024
MAX_TOTAL = 8 * MAX_LINE


class Refused(Exception):
    def __init__(self, category: str = "protocol_error") -> None:
        self.category = category


def emit(kind: str, **values: Any) -> None:
    print(json.dumps({"type": "zcode." + kind, **values}), flush=True)


class Peer:
    def __init__(self, executable: str, workspace: str) -> None:
        resolved = os.path.realpath(executable)
        if (
            not os.path.isabs(executable)
            or os.path.basename(resolved)
            .lower()
            .startswith(("zcode", "claude", "codex", "node", "bun"))
            or not os.access(resolved, os.X_OK)
        ):
            raise Refused()
        self.proc = subprocess.Popen(
            [resolved, "app-server", "--cwd", workspace, "--surface", "desktop"],
            cwd=workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Remain in the outer runner's owned group; never detach the protocol child.
        )
        assert self.proc.stdout and self.proc.stderr and self.proc.stdin
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ, "stdout")
        self.selector.register(self.proc.stderr, selectors.EVENT_READ, "stderr")
        self.buffer = b""
        self.total = 0
        self.messages: deque[dict[str, Any]] = deque()
        self.notifications: deque[dict[str, Any]] = deque()
        self.serial = 0

    def receive(self) -> dict[str, Any]:
        while not self.messages:
            if not self.selector.get_map():
                raise Refused()
            for key, _ in self.selector.select(0.2):
                data = os.read(key.fd, 65536)
                if not data:
                    self.selector.unregister(key.fileobj)
                    if key.data == "stdout" and self.buffer:
                        raise Refused()
                    continue
                self.total += len(data)
                if self.total > MAX_TOTAL:
                    raise Refused()
                if key.data == "stderr":
                    continue  # Drain bounded diagnostics; do not copy secrets or arbitrary prose.
                self.buffer += data
                while b"\n" in self.buffer:
                    line, self.buffer = self.buffer.split(b"\n", 1)
                    if len(line) > MAX_LINE or len(self.messages) >= 2048:
                        raise Refused()
                    try:
                        msg = json.loads(line)
                    except (ValueError, UnicodeError):
                        raise Refused() from None
                    if not isinstance(msg, dict):
                        raise Refused()
                    self.messages.append(msg)
                if len(self.buffer) > MAX_LINE:
                    raise Refused()
        return self.messages.popleft()

    def notification(self, msg: dict[str, Any]) -> None:
        if "id" in msg:  # Never grant a server-initiated permission/auth request.
            raise Refused("permission_denied" if "method" in msg else "protocol_error")
        method = msg.get("method")
        if method == "startup/storageState":
            if not isinstance(msg.get("params"), dict):
                raise Refused()
            return
        if method != "state.updated" or not isinstance(msg.get("params"), dict):
            raise Refused()
        if len(self.notifications) >= 2048:
            raise Refused()
        self.notifications.append(msg["params"])

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.serial += 1
        assert self.proc.stdin
        self.proc.stdin.write(
            json.dumps({"id": self.serial, "method": method, "params": params}).encode() + b"\n"
        )
        self.proc.stdin.flush()
        while True:
            msg = self.receive()
            if "id" not in msg or "method" in msg:
                self.notification(msg)
                continue
            if type(msg["id"]) is not int or msg["id"] != self.serial:
                raise Refused()
            if "error" in msg:
                raise Refused("native_error")
            if not isinstance(msg.get("result"), dict):
                raise Refused()
            return dict(msg["result"])

    def update(self) -> dict[str, Any]:
        while not self.notifications:
            self.notification(self.receive())
        return self.notifications.popleft()

    def finish(self) -> None:
        assert self.proc.stdin
        self.proc.stdin.close()
        # Drain to EOF, rejecting any extra lifecycle/response instead of losing duplicates.
        try:
            extra = self.receive()
        except Refused:
            if self.selector.get_map() or self.buffer or self.messages or self.notifications:
                raise
        else:
            del extra
            raise Refused()
        if self.proc.wait(timeout=3) != 0:
            raise Refused("native_error")

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
        self.selector.close()
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if stream and not stream.closed:
                stream.close()


def snapshot(
    value: dict[str, Any], workspace: str, settings: ZCodeExecutorSpec, expected: str | None
) -> tuple[str, int]:
    try:
        sid = session_id(value["session"]["sessionId"])
        if sid is None or (expected is not None and sid != expected):
            raise Refused("resume_failed")
        if (
            value["protocol"] != {"name": "ZCode Protocol", "version": 1}
            or type(value["protocol"]["version"]) is not int
        ):
            raise Refused()
        w = value["session"]["workspace"]
        if w != {"workspaceKey": workspace, "workspacePath": workspace}:
            raise Refused("workspace_mismatch")
        s = value["settings"]
        if s["model"]["current"] != {
            "providerId": settings.provider_id,
            "modelId": settings.requested_model,
        }:
            raise Refused("model_mismatch")
        if (
            s["mode"]["current"] != settings.permission_mode
            or s["permission"]["mode"] != settings.permission_mode
        ):
            raise Refused("permission_denied")
        runtime = value["runtime"]
        if (
            runtime.get("activeTurnId") is not None
            or not isinstance(runtime["pendingRequestIds"], list)
            or runtime["pendingRequestIds"]
            or value["session"]["status"] not in ("idle", "completed")
        ):
            raise Refused("session_busy")
        if value.get("projection", {}).get("lastError"):
            raise Refused("native_error")
        revision = runtime["stateRevision"]
        if type(revision) is not int or revision < 0:
            raise Refused()
        return sid, revision
    except (KeyError, TypeError, AttributeError):
        raise Refused() from None


def execute(peer: Peer, data: dict[str, Any], settings: ZCodeExecutorSpec) -> None:
    workspace = data["workspace"]
    w = {"workspaceKey": workspace, "workspacePath": workspace}
    capabilities = peer.call("runtime/capabilities", {})
    if (
        set(capabilities) != {"independentPlanState"}
        or capabilities["independentPlanState"] is not True
    ):
        raise Refused()
    params: dict[str, Any] = {
        "workspace": w,
        "mcpServers": [],
        "toolAllowlist": settings.allowed_tools,
        "offPeakToolEnabled": False,
        "dynamicWorkflowEnabled": False,
    }
    resume = data["resume"]
    if resume is not None:
        if session_id(resume) is None:
            raise Refused("resume_failed")
        params["sessionId"] = resume
        result = peer.call("session/resume", params)
    else:
        params.update(
            mode=settings.permission_mode,
            model={"providerId": settings.provider_id, "modelId": settings.requested_model},
            persistence="immediate",
            titleGenerationEnabled=False,
        )
        result = peer.call("session/create", params)
    sid, revision = snapshot(result, workspace, settings, resume)
    if peer.notifications:
        raise Refused()  # Unqualified initialization side effects must not silently disappear.
    result = peer.call("session/read", {"sessionId": sid})
    _, revision = snapshot(result, workspace, settings, sid)
    if peer.notifications:
        raise Refused()
    emit(
        "session",
        session_id=sid,
        model=settings.requested_model,
        provider=settings.provider_id,
        workspace=workspace,
        permission_mode=settings.permission_mode,
    )
    accepted = peer.call(
        "session/send",
        {
            "sessionId": sid,
            "inputId": data["input_id"],
            "queryId": data["input_id"],
            "content": data["prompt"],
            "expectedRevision": revision,
            "modelSelection": {
                "providerId": settings.provider_id,
                "modelId": settings.requested_model,
            },
        },
    )
    started = accepted.get("stateRevision")
    if (
        accepted.get("accepted") is not True
        or accepted.get("sessionId") != sid
        or type(started) is not int
        or started <= revision
    ):
        raise Refused()
    phase = "accepted"
    while True:
        update = peer.update()
        if (
            update.get("sessionId") != sid
            or update.get("workspace") != w
            or update.get("type") != "state.updated"
            or update.get("scope") != "session"
        ):
            raise Refused()
        rev = update.get("revision")
        if type(rev) is not int:
            raise Refused()
        reason = update.get("reason")
        if phase == "accepted" and reason == "prompt_started" and rev == started:
            phase = "running"
            emit("started", session_id=sid)
        elif phase == "running" and reason == "prompt_completed" and rev > started:
            break
        elif reason == "prompt_failed":
            raise Refused("native_error")
        else:
            raise Refused()
    final = peer.call("session/read", {"sessionId": sid})
    _, final_revision = snapshot(final, workspace, settings, sid)
    if final_revision < rev or peer.notifications:
        raise Refused()
    # EOF closes this dedicated protocol connection; do not call session/close (deletes history).
    peer.finish()
    emit("completed", session_id=sid)


def main() -> int:
    peer: Peer | None = None
    try:
        raw = sys.stdin.buffer.read(MAX_LINE + 1)
        if len(raw) > MAX_LINE:
            raise Refused()
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("mode") != "mock" or data.get("version") != 1:
            raise Refused()
        settings = ZCodeExecutorSpec.model_validate(data["settings"])
        if (
            data["workspace"] != os.getcwd()
            or not isinstance(data["prompt"], str)
            or not isinstance(data["input_id"], str)
        ):
            raise Refused("workspace_mismatch")
        peer = Peer(data["stub"], data["workspace"])
        execute(peer, data, settings)
        return 0
    except Refused as exc:
        emit("error", category=exc.category)
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
        emit("error", category="protocol_error")
    finally:
        if peer:
            peer.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
