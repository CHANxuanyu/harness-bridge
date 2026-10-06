"""Run the synthetic two-adapter P7 scenario in a new directory; no live option exists."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from qa.local.p7_fixture import FILES, digest, isolated_env, prepare, write_json


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


class Rehearsal:
    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        self.manifest = prepare(self.root)
        self.env = isolated_env(self.root)
        state = self.root / "state"
        state.mkdir()
        (state / "config.toml").write_text(
            "[execution]\nmax_parallel_per_project=2\n[live]\nenabled=false\n"
        )
        self.claim: list[str] = []
        self.tasks: dict[str, dict[str, Any]] = {}
        self.jobs: list[str] = []

    def cli(self, *args: str, error: str | None = None) -> dict[str, Any]:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness_bridge",
                "--state-dir",
                str(self.root / "state"),
                "--json",
                *args,
            ],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        value = json.loads(proc.stdout)
        if error:
            require(not value["ok"] and value["error"]["code"] == error, str(value))
        else:
            require(proc.returncode == 0 and value["ok"], str(value))
        return value

    def file(self, name: str, data: Any) -> str:
        path = self.root / (name + ".json")
        write_json(path, data)
        return str(path)

    def source_fingerprint(self) -> Any:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json,sys; from harness_bridge.workspace import checkout_fingerprint; "
                "print(json.dumps(checkout_fingerprint(sys.argv[1])))",
                str(self.root / "repo"),
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return json.loads(proc.stdout)

    def bind(self, claim: dict[str, Any]) -> None:
        self.claim = [
            "--advisor-binding",
            claim["binding_id"],
            "--advisor-epoch",
            str(claim["epoch"]),
        ]

    def dispatch(self, key: str, attempt: str) -> dict[str, Any]:
        name = "cc-stand-in" if key == "normalize" else "cx-stand-in"
        argv = [
            "run",
            self.tasks[key]["task_id"],
            "--mode",
            "mock",
            "--stub-binary",
            str(self.root / "bin" / name),
            "--background",
            "--idempotency-key",
            attempt,
        ]
        job = self.cli(*argv, *self.claim)
        self.jobs.append(job["job_id"])
        replay = self.cli(*argv, *self.claim)
        require(replay["job_id"] == job["job_id"] and replay["replayed"], "dispatch replay changed")
        return job

    def finish(self, job: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + 35
        cursor = 0
        while time.monotonic() < deadline:
            events = self.cli("events", job["task_id"], "--after", str(cursor), "--wait", "0.2")
            require(events["next_cursor"] >= cursor, "event cursor regressed")
            cursor = events["next_cursor"]
            status = self.cli("job", job["job_id"])
            if status["phase"] == "finished":
                require(status["executor_exit_confirmed"] is True, "executor exit unknown")
                require(status["executor_outcome"] == "succeeded", str(status))
                return status
        raise RuntimeError("worker did not finish before rehearsal deadline")

    def review(self, key: str, verdict: str) -> None:
        tid = self.tasks[key]["task_id"]
        evidence = self.cli("artifacts", tid)
        decision = {
            **evidence["review_template"],
            "verdict": verdict,
            "idempotency_key": key + "-" + verdict,
        }
        if verdict == "changes_requested":
            require(evidence["verification"]["status"] == "failed", "diagnosis unexpectedly passed")
            decision["findings"] = [
                {
                    "severity": "blocking",
                    "explanation": "Diagnosis-only attempt left the stub",
                    "requested_change": "Now implement all frozen normalization requirements",
                }
            ]
        else:
            require(evidence["verification"]["status"] == "passed", "cannot approve failed checks")
        self.cli("review", tid, "--file", self.file(key + "-review", decision), *self.claim)

    def execute(self) -> dict[str, Any]:
        repo = self.root / "repo"
        before = self.source_fingerprint()
        goal = self.cli(
            "goal", "create", "--file", str(self.root / "goal.json"), "--idempotency-key", "goal"
        )
        gid = goal["goal_id"]
        self.bind(goal["advisor_claim"])
        batch = self.cli(
            "goal",
            "plan",
            gid,
            "--file",
            str(self.root / "plan.json"),
            "--idempotency-key",
            "plan",
            *self.claim,
        )
        for child in batch["children"]:
            task = self.cli("child", "materialize", child["child_id"], *self.claim)
            self.tasks[child["key"]] = task
        worktrees = [t["worktree"] for t in self.tasks.values()]
        require(len(set(worktrees)) == 2 and str(repo) not in worktrees, "workspaces not isolated")
        require(
            all(t["base_sha"] == goal["base_sha"] for t in self.tasks.values()), "wrong baseline"
        )
        first = self.dispatch("normalize", "normalize-initial")
        second = self.dispatch("render", "render-initial")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            states = [self.cli("status", t["task_id"])["state"] for t in self.tasks.values()]
            if states == ["RUNNING", "RUNNING"]:
                break
            time.sleep(0.1)
        require(states == ["RUNNING", "RUNNING"], "two workers were not concurrently RUNNING")
        taken = self.cli(
            "goal",
            "takeover",
            gid,
            "--file",
            self.file(
                "takeover",
                {
                    "advisor": {"host": "zcode", "native_session_ref": "synthetic-advisor-b"},
                    "expected_epoch": 1,
                    "reason": "Synthetic reconnect while both workers are active",
                },
            ),
            "--idempotency-key",
            "takeover",
        )
        self.cli(
            "goal",
            "plan",
            gid,
            "--file",
            str(self.root / "plan.json"),
            "--idempotency-key",
            "plan",
            *self.claim,
            error="STALE_ADVISOR",
        )
        self.bind(taken["advisor_claim"])
        (self.root / "release").touch()
        initial_results = [self.finish(first), self.finish(second)]
        norm = Path(self.tasks["normalize"]["worktree"])
        render = Path(self.tasks["render"]["worktree"])
        require(
            (norm / "tagformat/render.py").read_text() == FILES["tagformat/render.py"],
            "normalizer changed the other child module",
        )
        require(
            (render / "tagnorm/normalize.py").read_text() == FILES["tagnorm/normalize.py"],
            "renderer changed the other child module",
        )
        self.review("normalize", "changes_requested")
        self.review("render", "approve")
        repaired = self.finish(self.dispatch("normalize", "normalize-repair"))
        self.review("normalize", "approve")
        checks = json.loads((self.root / "integration-checks.json").read_text())
        frozen = self.cli(
            "goal",
            "integrate",
            gid,
            "--file",
            self.file(
                "integration",
                {
                    "schema_version": "1.0",
                    "task_ids": [t["task_id"] for t in self.tasks.values()],
                    "verification": checks,
                },
            ),
            "--idempotency-key",
            "integration",
            *self.claim,
        )
        iid = frozen["integration_id"]
        self.cli("integration", "materialize", iid, *self.claim)
        self.cli("integration", "verify", iid, "--idempotency-key", "combined", *self.claim)
        candidate = self.cli("integration", "status", iid)
        self.cli(
            "integration",
            "review",
            iid,
            "--file",
            self.file(
                "integration-review",
                {
                    **candidate["review_template"],
                    "idempotency_key": "approve-combined",
                },
            ),
            *self.claim,
        )
        argv = [
            "goal",
            "deliver",
            gid,
            "--integration",
            iid,
            "--branch",
            "bridge/p7-result",
            "--idempotency-key",
            "delivery",
            *self.claim,
        ]
        delivery = self.cli(*argv)
        replay = self.cli(*argv)
        require(
            replay["delivery_id"] == delivery["delivery_id"] and replay["replayed"],
            "delivery replay changed",
        )
        status = self.cli("goal", "status", gid)
        require(status["state"] == "DELIVERED", "goal not delivered")
        require(status["budget"]["attempts"] == 3, "unexpected attempt count")
        require(status["budget"]["repairs"] == 1, "unexpected repair count")
        require(status["budget"]["reserved_turns"] == 30, "turn reservation changed")
        require(status["budget"]["reserved_wall_seconds"] == 1800, "wall reservation changed")
        require(self.source_fingerprint() == before, "source checkout changed")
        actual = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "rev-parse", "refs/heads/bridge/p7-result"],
            cwd=repo,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        require(actual == delivery["commit_sha"], "delivered commit differs from approval")
        for path, expected in self.manifest["files"].items():
            require(digest(self.root / path) == expected, "fixture material changed: " + path)
        cc = [json.loads(s) for s in (self.root / "cc-calls.jsonl").read_text().splitlines()]
        cx = [json.loads(s) for s in (self.root / "cx-calls.jsonl").read_text().splitlines()]
        require(len(cc) == 2 and len(cx) == 1, "stand-in call count differs")
        require(
            cc[0]["session_id"] == cc[1]["session_id"] and cc[0]["cwd"] == cc[1]["cwd"],
            "repair changed session or workspace",
        )
        require(
            not cc[0]["resumed"] and cc[1]["resumed"] and not cx[0]["resumed"],
            "wrong resume invocation",
        )
        return {
            "ok": True,
            "evidence_level": "offline-integration-simulated-executors",
            "inference_performed": False,
            "live_ready": False,
            "goal_id": gid,
            "two_workers_observed_running": True,
            "stale_advisor_refused": True,
            "advisor_epoch": 2,
            "tasks": self.tasks,
            "initial_jobs": initial_results,
            "repair_job": repaired,
            "budget": status["budget"],
            "delivery": delivery,
            "source_unchanged": True,
            "acceptance_and_packets_unchanged": True,
            "exact_session_resume": True,
            "stub_calls": {"claude-code": 2, "codex": 1},
        }

    def run(self) -> dict[str, Any]:
        try:
            result = self.execute()
        except BaseException:
            # Cancel only tasks in this newly created fixture. Preserve errors and evidence.
            outcomes = []
            for task in self.tasks.values():
                try:
                    outcomes.append(self.cli("cancel", task["task_id"]))
                except Exception as exc:
                    outcomes.append({"cleanup_error": type(exc).__name__})
            write_json(self.root / "failed-cleanup.json", outcomes)
            raise
        write_json(self.root / "result.json", result)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="new disposable directory (must not exist)")
    args = parser.parse_args()
    try:
        result = Rehearsal(args.root).run()
    except FileExistsError:
        parser.error("refusing to reuse an existing directory")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
