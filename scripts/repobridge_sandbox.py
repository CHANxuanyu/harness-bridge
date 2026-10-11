"""Isolated RepoBridge test instances (stub CLIs) and the offline engineering-foundation demo.

  uv run --frozen python scripts/repobridge_sandbox.py create DIR        # new sandbox root
  uv run --frozen python scripts/repobridge_sandbox.py launch DIR        # App, --no-open
  uv run --frozen python scripts/repobridge_sandbox.py demo [--root DIR] # end-to-end demo

A sandbox root holds everything one ``HBRIDGE_ENV=test`` instance uses: state, the native CLIs'
HOME/CODEX_HOME/CLAUDE_CONFIG_DIR, stub ``claude``/``codex`` (copied from tests/helpers/wb_stub.py),
a fake Applications folder and a recording opener. The environment is built from an allowlist
(PATH, locale, TMPDIR), so no real token, API/provider variable or HOME reaches the instance.
The cloud/nested agent markers are inherited unchanged, so the product gate refuses native
starts inside an agent or cloud session exactly as it does for any other instance; run the demo
from a normal terminal (or state explicitly that the markers were removed for that run).
Nothing here starts a real CLI, opens a desktop app, calls a model or leaves loopback.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
STUB = REPO / "tests" / "helpers" / "wb_stub.py"
PASS_THROUGH = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SYSTEMROOT")
# Synthetic secret marker planted in URL/query, headers, body text, paths and native errors.
MARKER = "SYNTHETICSECRET7F3A"


@dataclass(frozen=True)
class Sandbox:
    root: Path

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def home(self) -> Path:
        return self.root / "home"

    @property
    def stub_home(self) -> Path:
        return self.root / "stub-home"

    @property
    def bin(self) -> Path:
        return self.root / "bin"

    @property
    def apps(self) -> Path:
        return self.root / "Applications"

    @property
    def repo(self) -> Path:
        return self.root / f"project-{MARKER}"

    @property
    def opened(self) -> Path:
        return self.root / "opened.log"

    def binaries(self) -> dict[str, str]:
        return {"claude-code": str(self.bin / "claude"), "codex": str(self.bin / "codex")}

    def env(self, **extra: str) -> dict[str, str]:
        from harness_bridge.config import CLOUD_ENV_MARKERS, NESTED_ENV_MARKERS

        keep = (*PASS_THROUGH, *CLOUD_ENV_MARKERS, *NESTED_ENV_MARKERS)  # gate markers stay
        env = {k: os.environ[k] for k in keep if os.environ.get(k)}
        env.update(
            HBRIDGE_ENV="test",
            HBRIDGE_TEST_ROOT=str(self.root),
            HBRIDGE_STATE_DIR=str(self.state),
            HOME=str(self.home),
            CODEX_HOME=str(self.root / "codex-home"),
            CLAUDE_CONFIG_DIR=str(self.stub_home / "claude-config"),
            WB_STUB_HOME=str(self.stub_home),
            GIT_CONFIG_NOSYSTEM="1",
        )
        env.update(extra)
        return env


def create(root: Path) -> Sandbox:
    root = root.expanduser().absolute()
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"sandbox root must be new or empty: {root}")
    box = Sandbox(Path(os.path.realpath(root)) if root.exists() else root)
    for path in (box.root, box.state, box.home, box.stub_home, box.bin, box.apps, box.repo):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    (box.root / "codex-home").mkdir(mode=0o700, exist_ok=True)
    shutil.copyfile(STUB, box.bin / "wb_stub.py")
    for name in ("claude", "codex"):
        wrapper = box.bin / name
        wrapper.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" -I "{box.bin / "wb_stub.py"}" {name} "$@"\n'
        )
        wrapper.chmod(0o755)
    opener = box.bin / "open"
    opener.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{box.opened}"\n')
    opener.chmod(0o755)
    git = ["git", "-c", "user.name=Sandbox", "-c", "user.email=sandbox@example.invalid"]
    run_env = box.env()
    subprocess.run([*git, "init", "-q"], cwd=box.repo, check=True, env=run_env)
    (box.repo / "README.md").write_text("synthetic sandbox project\n")
    subprocess.run([*git, "add", "."], cwd=box.repo, check=True, env=run_env)
    subprocess.run([*git, "commit", "-qm", "init"], cwd=box.repo, check=True, env=run_env)
    return box


def launch_argv(box: Sandbox, port: int = 0) -> list[str]:
    return [
        sys.executable,
        "-c",
        "from harness_bridge.workbench.app import main; raise SystemExit(main())",
        "--no-open",
        "--port",
        str(port),
        "--state-dir",
        str(box.state),
        "--claude-binary",
        str(box.bin / "claude"),
        "--codex-binary",
        str(box.bin / "codex"),
        "--dev-app-dir",
        str(box.apps),
        "--dev-opener",
        str(box.bin / "open"),
    ]


def seed_codex(box: Sandbox, title: str = "Outside session") -> str:
    """A native-shaped Codex thread written directly, never through RepoBridge."""
    native = str(uuid.uuid4())
    codex = box.stub_home / "codex"
    codex.mkdir(parents=True, exist_ok=True)
    (codex / native).write_text("external\n")
    turns = [
        {
            "id": "outside-0",
            "status": "completed",
            "items": [
                {
                    "id": "u-0",
                    "type": "userMessage",
                    "content": [{"type": "text", "text": "outside 0"}],
                }
            ],
        }
    ]
    (codex / f"{native}.turns.json").write_text(json.dumps(turns))
    index = box.stub_home / "external-index.json"
    rows = json.loads(index.read_text()) if index.exists() else []
    rows.append(
        {
            "id": native,
            "cwd": str(box.repo),
            "source": "cli",
            "name": title,
            "updatedAt": 1791504000,
            "ephemeral": False,
        }
    )
    index.write_text(json.dumps(rows))
    return native


def add_late_proof(box: Sandbox, native: str, client_id: str, text: str) -> None:
    """Simulate late native persistence carrying the exact client message ID."""
    path = box.stub_home / "codex" / f"{native}.turns.json"
    rows = json.loads(path.read_text())
    rows.append(
        {
            "id": "late",
            "status": "completed",
            "items": [
                {
                    "type": "userMessage",
                    "id": "late",
                    "clientId": client_id,
                    "content": [{"type": "text", "text": text}],
                }
            ],
        }
    )
    path.write_text(json.dumps(rows))


class Client:
    """Loopback client for the workbench API (cookie auth like the window)."""

    def __init__(self, port: int, token: str) -> None:
        self.port = port
        self.cookie = ""
        status, headers, _ = self.request("GET", f"/auth?token={token}&probe={MARKER}")
        if status != 303:
            raise RuntimeError("login failed")
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]

    def request(
        self, method: str, path: str, body: Any = None
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {
            "Host": f"127.0.0.1:{self.port}",
            "X-Synthetic-Secret": MARKER,
            "User-Agent": f"sandbox-{MARKER}",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie + f"; extra={MARKER}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            headers["X-RepoBridge"] = "1"
        conn.request(method, path, body=data, headers=headers)
        res = conn.getresponse()
        payload = res.read()
        conn.close()
        return res.status, dict(res.getheaders()), payload

    def api(self, method: str, path: str, body: Any = None, *, ok: bool = True) -> Any:
        _, _, payload = self.request(method, path, body if method == "POST" else None)
        data = json.loads(payload)
        if ok and not data.get("ok"):
            raise RuntimeError(f"{method} {path.split('?')[0]} failed: {data['error']['code']}")
        return data.get("result") if ok else data


def wait_for(predicate: Callable[[], Any], timeout: float = 20.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise RuntimeError("condition not reached in time")


def scan_for_leaks(paths: list[Path], needles: dict[str, str]) -> dict[str, list[str]]:
    """Which needle (by label) occurs in which file; zip members are scanned individually."""
    found: dict[str, list[str]] = {label: [] for label in needles}

    def check(name: str, data: bytes) -> None:
        text = data.decode("utf-8", "replace")
        for label, needle in needles.items():
            if needle and needle in text:
                found[label].append(name)

    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    check(str(child), child.read_bytes())
        elif path.suffix == ".zip":
            with zipfile.ZipFile(path) as bundle:
                for member in bundle.namelist():
                    check(f"{path.name}:{member}", bundle.read(member))
        elif path.is_file():
            check(str(path), path.read_bytes())
    return {label: hits for label, hits in found.items() if hits}


def demo(root: Path | None = None, *, keep: bool = False) -> dict[str, Any]:
    """Link → unknown → exact client-ID proof → sent → stop → export + summary."""
    sys.path.insert(0, str(REPO / "src"))
    scratch = Path(tempfile.mkdtemp(prefix="rb-demo-")) if root is None else None
    try:
        return _demo(scratch, root, keep)
    except BaseException:
        if scratch is not None and not keep:
            shutil.rmtree(scratch, ignore_errors=True)
        raise


def _demo(scratch: Path | None, root: Path | None, keep: bool) -> dict[str, Any]:
    from harness_bridge.observability import report
    from harness_bridge.workbench.harness import WorkbenchConfig
    from harness_bridge.workbench.server import WorkbenchServer
    from harness_bridge.workbench.service import Workbench

    box = create(root or (scratch / "sandbox"))  # type: ignore[operator]
    native = seed_codex(box)
    env = box.env(WB_STUB_TURN_DELIVERY="exit", HBRIDGE_PRODUCT_EVENTS="1")
    config = WorkbenchConfig(
        binaries=box.binaries(),
        discover=False,
        app_dirs=(str(box.apps),),
        opener=str(box.bin / "open"),
    )
    wb = Workbench(box.state, config=config, base_env=env, stop_grace=1.0)
    server = WorkbenchServer(wb)
    server.start()
    steps: dict[str, Any] = {}
    client_id = "demo-unknown-1"
    text = f"synthetic prompt {MARKER}"
    try:
        api = Client(server.port, server.token)
        project = api.api("POST", "/api/projects", {"path": str(box.repo)})
        pid = project["project_id"]
        found = api.api("GET", f"/api/history?project_id={pid}&harness=codex&q=&marker={MARKER}")
        candidate = next(c for c in found["items"] if c["native_session_id"] == native)
        linked = api.api("POST", "/api/sessions/link", {"candidate_id": candidate["candidate_id"]})
        sid = linked["session"]["session"]["session_id"]
        steps["linked"] = {"created": linked["created"], "session_id": sid}
        api.api("POST", f"/api/sessions/{sid}/start", {"kind": "resume", "confirm_external": True})
        wait_for(
            lambda: (
                api.api("GET", f"/api/sessions/{sid}/conversation").get("live")
                and wb._live.get(sid) is not None
                and wb._live[sid].phase == "waiting"
            )
        )
        attachment = api.api(
            "POST",
            f"/api/sessions/{sid}/attachments",
            {"name": f"notes-{MARKER}.txt", "data": "U1lOVEhFVElDU0VDUkVUN0YzQQ=="},
        )
        api.api(
            "POST",
            f"/api/sessions/{sid}/send",
            {"text": text, "client_id": client_id, "attachments": [attachment["id"]]},
        )
        wait_for(lambda: sid not in wb._live)
        receipt = api.api("GET", f"/api/sessions/{sid}/delivery?client_id={client_id}")
        steps["after_submit"] = receipt["delivery"]["state"]
        blocked = api.api(
            "POST",
            f"/api/sessions/{sid}/send",
            {"text": "another", "client_id": "demo-blocked"},
            ok=False,
        )
        steps["second_send_refused"] = blocked["error"]["details"]["reason"]
        add_late_proof(box, native, client_id, text)
        api.api("GET", f"/api/sessions/{sid}/conversation?refresh=1")
        receipt = api.api("GET", f"/api/sessions/{sid}/delivery?client_id={client_id}")
        steps["after_exact_proof"] = receipt["delivery"]["state"]
        steps["attachment_retained"] = receipt["attachments"][0]["id"] == attachment["id"]
        steps["runs"] = len(wb.store.list_runs(sid))
        steps["native_id_unchanged"] = wb.store.get_session(sid)["native_session_id"] == native
        api.api("POST", f"/api/sessions/{sid}/stop", {})
    finally:
        server.close()
        wb.close(timeout=5)
    rpc = box.stub_home / "codex-rpc.log"
    turn_starts = (
        [line for line in rpc.read_text().splitlines() if '"method": "turn/start"' in line]
        if rpc.exists()
        else []
    )
    steps["native_turn_start_calls"] = len(turn_starts)
    bundle = report.export_bundle(
        box.state, None, envs={"test"}, profile={"env": "test", "env_source": "explicit"}
    )
    summary = report.summarize(box.state, envs={"test"})
    summary_path = box.root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    (box.root / "summary.csv").write_text(report.to_csv(summary))
    records = report.load(box.state, "diag")
    send_ops = [r["op"] for r in records if r.get("name") == "session.send" and r.get("op")]
    trace = report.trace(box.state, op=send_ops[0]) if send_ops else {"records": []}
    leaks = scan_for_leaks(
        [box.state / "observability", Path(bundle["bundle"]), summary_path],
        {
            "marker": MARKER,
            "native_session_id": native,
            "sandbox_path": str(box.root),
            "client_id": client_id,
            "launch_token": server.token,
        },
    )
    result = {
        "sandbox": str(box.root),
        "steps": steps,
        "bundle": bundle,
        "summary_delivery": summary["product"].get("delivery"),
        "summary_link": summary["product"].get("link"),
        "contains_test_data": summary["contains_test_data"],
        "send_trace_events": [
            f"{r['stream']}:{r['event']}"
            + (
                f"({r['attrs'].get('from_state')}->{r['attrs'].get('to_state')})"
                if r["event"] == "delivery.state"
                else ""
            )
            for r in trace["records"]
        ],
        "leaks": leaks,
        "passed": steps.get("after_submit") == "unknown"
        and steps.get("after_exact_proof") == "sent"
        and steps.get("native_turn_start_calls") == 1
        and steps.get("runs") == 1
        and not leaks,
    }
    if scratch is not None and not keep:
        result["sandbox"] += " (removed)"
        shutil.rmtree(scratch, ignore_errors=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create")
    p.add_argument("root", type=Path)
    p = sub.add_parser("launch")
    p.add_argument("root", type=Path)
    p.add_argument("--port", type=int, default=0)
    p = sub.add_parser("demo")
    p.add_argument("--root", type=Path, default=None, help="new/empty directory to keep")
    p.add_argument("--keep", action="store_true", help="keep the temporary sandbox")
    args = parser.parse_args(argv)
    if args.command == "create":
        box = create(args.root)
        print(json.dumps({"root": str(box.root), "env": box.env()}, indent=2))
        return 0
    if args.command == "launch":
        box = Sandbox(Path(os.path.realpath(args.root)))
        if not (box.bin / "wb_stub.py").is_file():
            raise SystemExit("not a sandbox root (run `create` first)")
        env = box.env()
        env["PYTHONPATH"] = str(REPO / "src")
        with contextlib.suppress(KeyboardInterrupt):
            return subprocess.call(launch_argv(box, args.port), env=env)
        return 130
    try:
        result = demo(args.root, keep=args.keep)
    except RuntimeError as exc:
        # e.g. PREFLIGHT_FAILED: an inherited cloud/nested agent marker keeps the gate closed.
        print(f"demo did not complete: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
