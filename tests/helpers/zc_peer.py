"""Synthetic ZCode 0.16.9-shaped stdio peer. No harness, credentials or network."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

from cc_stub import BUGGY, CORRECT

MODE = os.environ.get("HBRIDGE_ZC_MODE", "success")
WORKSPACE = os.getcwd()
MODEL = {
    "providerId": os.environ.get("HBRIDGE_ZC_PROVIDER", "account:zai-individual-coding-plan"),
    "modelId": "GLM-5.3-Flash",
}
SID = "sess_" + str(uuid.uuid4())
REVISION = 1
READS = 0


def write(obj: object) -> None:
    data = (json.dumps(obj) + "\n").encode()
    if os.environ.get("HBRIDGE_ZC_TRICKLE"):
        for b in data:
            sys.stdout.buffer.write(bytes([b]))
            sys.stdout.buffer.flush()
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


def snapshot() -> dict[str, object]:
    selected = dict(MODEL)
    if MODE == "model" or (MODE == "final-model" and READS > 1):
        selected["modelId"] = "GLM-5.3"
    cwd = "/wrong-worktree" if MODE == "workspace" else WORKSPACE
    mode = "yolo" if MODE == "permission" else "edit"
    result: dict[str, object] = {
        "protocol": {"name": "ZCode Protocol", "version": 1},
        "session": {
            "sessionId": SID,
            "workspace": {"workspacePath": cwd, "workspaceKey": cwd},
            "status": "idle",
        },
        "settings": {
            "model": {"current": selected},
            "mode": {"current": mode},
            "permission": {"mode": mode},
        },
        "runtime": {
            "stateRevision": 0 if MODE == "stale-final" and READS > 1 else REVISION,
            "pendingRequestIds": [],
            **(
                {"activeTurnId": "turn_busy"}
                if MODE == "busy" or (MODE == "final-busy" and READS > 1)
                else {}
            ),
        },
        "messages": [{"role": "assistant", "content": "PRIVATE_NATIVE_HISTORY_NOT_FOR_RECEIPTS"}],
        "projection": {},
    }
    if MODE == "bad-runtime":
        result["runtime"] = []
    if MODE == "bad-projection":
        result["projection"] = []
    return result


def update(reason: str, revision: int) -> dict[str, object]:
    return {
        "method": "state.updated",
        "params": {
            "scope": "session",
            "type": "state.updated",
            "sessionId": "sess_" + str(uuid.uuid4()) if MODE == "wrong-turn" else SID,
            "workspace": {
                "workspacePath": "/elsewhere" if MODE == "wrong-turn-workspace" else WORKSPACE,
                "workspaceKey": WORKSPACE,
            },
            "revision": revision,
            "reason": reason,
            "patch": {},
        },
    }


def main() -> None:
    global SID, REVISION, READS
    assert sys.argv[1:] == ["app-server", "--cwd", WORKSPACE, "--surface", "desktop"]
    write({"method": "startup/storageState", "params": {"phase": "ready"}})
    for line in sys.stdin:
        request = json.loads(line)
        method, params, ident = request["method"], request["params"], request["id"]
        log = os.environ.get("HBRIDGE_ZC_LOG")
        if log:
            with open(log, "a") as f:
                f.write(json.dumps({"pid": os.getpid(), "cwd": WORKSPACE, **request}) + "\n")
        result: dict[str, object]
        if method == "runtime/capabilities":
            result = {"independentPlanState": True}
        elif method in ("session/create", "session/resume"):
            assert params["toolAllowlist"] == ["Read", "Edit", "Write", "Glob", "Grep"]
            assert params["mcpServers"] == []
            assert (
                params["offPeakToolEnabled"] is False and params["dynamicWorkflowEnabled"] is False
            )
            if method == "session/resume":
                assert "model" not in params and "mode" not in params
                if MODE != "resume-mismatch":
                    SID = params["sessionId"]
            else:
                assert params["mode"] == "edit" and params["model"] == MODEL
                assert params["titleGenerationEnabled"] is False
            if MODE != "missing-preferences":
                callback = {
                    "id": "host-preferences",
                    "method": "session/requestRuntimePreferences",
                    "params": {
                        "sessionId": "latest" if MODE == "bad-preference-session" else SID,
                        "scope": "user-execution"
                        if MODE == "bad-preference-scope"
                        else "runtime-materialization",
                    },
                }
                write(callback)
                response = json.loads(sys.stdin.readline())
                assert response == {
                    "id": "host-preferences",
                    "result": {
                        "nativeSearchEnhancementsEnabled": False,
                        "memoryEnabled": False,
                        "askUserQuestionAutoResolutionEnabled": False,
                        "modelContextBudgetStrategy": "preflight-v1",
                    },
                }
                if MODE == "duplicate-preferences":
                    write(callback)
                if MODE == "preference-binding-mismatch":
                    SID = "sess_" + str(uuid.uuid4())
            result = snapshot()
        elif method == "session/read":
            READS += 1
            result = snapshot()
        elif method == "session/send":
            assert params["modelSelection"] == MODEL
            assert params["sessionId"] == SID and params["expectedRevision"] == REVISION
            assert params["inputId"] == params["queryId"]
            if MODE == "request-permission":
                write({"id": "native-approval", "method": "permission/request", "params": {}})
                continue
            if MODE == "rpc-error":
                write({"id": ident, "error": {"code": -32031, "message": "PRIVATE_ERROR"}})
                continue
            REVISION += 1
            if MODE != "missing-start":
                write(update("prompt_started", REVISION))
            write(
                {
                    "id": ident,
                    "result": {"accepted": True, "sessionId": SID, "stateRevision": REVISION},
                }
            )
            if MODE == "sleep":
                time.sleep(30)
            if MODE == "truncated":
                return
            if MODE == "malformed":
                print('{"bad":', flush=True)
                return
            if MODE == "oversized":
                print("x" * (1024 * 1024 + 1), flush=True)
                return
            edit = os.environ.get("HBRIDGE_ZC_EDIT", "correct")
            Path("tagnorm/normalize.py").write_text(BUGGY if edit == "buggy" else CORRECT)
            REVISION += 1
            terminal = update("prompt_failed" if MODE == "failed" else "prompt_completed", REVISION)
            write(terminal)
            if MODE == "duplicate":
                write(terminal)
            continue
        else:
            raise AssertionError("Unexpected method: " + method)
        write({"id": ident + 90 if MODE == "wrong-id" else ident, "result": result})
    # Deliberate extra post-completion event tests the EOF drain.
    if MODE == "after-final":
        write(update("prompt_completed", REVISION + 1))
    if MODE == "exit-error":
        print("PRIVATE_STDERR", file=sys.stderr, flush=True)
        sys.exit(3)


if __name__ == "__main__":
    main()
