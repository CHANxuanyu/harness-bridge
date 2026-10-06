"""Offline demos driven by a scripted supervisor through *separate CLI processes*.

Each step runs ``python -m harness_bridge ...`` as a new process and parses its JSON receipt, so
the final status read proves state lives in SQLite, not in memory. The executor is the fake
subprocess; no model is invoked. Evidence level: offline integration (simulated executor).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from harness_bridge.demo_fixture import create_fixture_repo, make_task_spec, write_acceptance_script
from harness_bridge.workspace import checkout_fingerprint

DEMO_SCENARIOS = ("success", "bug-then-repair")


class DemoStepError(Exception):
    pass


class _Cli:
    def __init__(self, state_dir: Path, python: str) -> None:
        self.base = [python, "-m", "harness_bridge", "--state-dir", str(state_dir), "--json"]
        self.steps: list[dict[str, Any]] = []

    def call(self, label: str, *args: str, expect_ok: bool = True) -> dict[str, Any]:
        proc = subprocess.run(
            [*self.base, *args], capture_output=True, text=True, timeout=600, check=False
        )
        try:
            payload: dict[str, Any] = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise DemoStepError(
                f"step {label!r}: non-JSON output (exit {proc.returncode}): "
                f"{proc.stdout[-500:]} {proc.stderr[-500:]}"
            ) from None
        step = {
            "step": label,
            "command": ["hbridge", *args],
            "exit_code": proc.returncode,
            "ok": payload.get("ok"),
        }
        if not payload.get("ok"):
            step["error_code"] = payload.get("error", {}).get("code")
        self.steps.append(step)
        if payload.get("ok") is not expect_ok:
            raise DemoStepError(f"step {label!r}: unexpected result {json.dumps(payload)[:2000]}")
        return payload


def _write_json(path: Path, obj: Any) -> str:
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return str(path)


def run_demo(
    scenario: str, *, workdir: Path | None = None, cleanup: bool = False, python: str | None = None
) -> dict[str, Any]:
    if scenario not in DEMO_SCENARIOS:
        raise ValueError(f"scenario must be one of {DEMO_SCENARIOS}")
    py = python or sys.executable
    base = workdir or Path(tempfile.mkdtemp(prefix=f"hbridge-demo-{scenario}-"))
    base.mkdir(parents=True, exist_ok=True)
    base = base.resolve()
    state_dir = base / "state"
    repo = create_fixture_repo(base / "fixture-repo")
    acceptance = write_acceptance_script(base / "acceptance" / "check_normalize.py")
    before = checkout_fingerprint(str(repo))
    task_file = _write_json(
        base / "task.json", make_task_spec(repo, acceptance, scenario, python=py)
    )
    cli = _Cli(state_dir, py)
    report: dict[str, Any] = {
        "scenario": scenario,
        "evidence_level": "offline integration (simulated executor); no model was invoked",
        "workdir": str(base),
    }
    try:
        created = cli.call(
            "create", "create", "--task", task_file, "--idempotency-key", f"demo-{scenario}"
        )
        task_id = created["task_id"]
        report["task_id"] = task_id
        timeline: list[dict[str, Any]] = []
        for round_no in range(1, 4):
            run = cli.call(f"run #{round_no}", "run", task_id, "--mode", "mock")
            summary = cli.call(f"artifacts #{round_no}", "artifacts", task_id)
            gate = summary["approval_gate"]
            verification = summary.get("verification", {})
            timeline.append(
                {
                    "attempt": run["attempt_seq"],
                    "executor_outcome": run["executor_outcome"],
                    "executor_claimed_tests": summary.get("executor_reported", {}).get(
                        "tests_reported"
                    ),
                    "bridge_verification": verification.get("status"),
                    "checks": {c["id"]: c["status"] for c in verification.get("checks", [])},
                    "approvable": gate["approvable"],
                }
            )
            template = summary["review_template"]
            if gate["approvable"]:
                approve = {
                    **template,
                    "verdict": "approve",
                    "findings": [],
                    "reviewer_label": "scripted-demo-supervisor",
                    "idempotency_key": f"approve-{run['attempt_id']}",
                }
                cli.call(
                    "review approve",
                    "review",
                    task_id,
                    "--file",
                    _write_json(base / f"review-{round_no}-approve.json", approve),
                )
                break
            # Gate probe: an approve on failing evidence must be rejected by the bridge.
            probe = {
                **template,
                "verdict": "approve",
                "findings": [],
                "reviewer_label": "scripted-demo-supervisor",
                "idempotency_key": f"probe-{run['attempt_id']}",
            }
            rejected = cli.call(
                "gate probe (approve must be rejected)",
                "review",
                task_id,
                "--file",
                _write_json(base / f"review-{round_no}-probe.json", probe),
                expect_ok=False,
            )
            timeline[-1]["approve_probe_rejected_with"] = rejected["error"]["code"]
            failing = [c for c in verification.get("checks", []) if c["status"] != "passed"]
            findings = [
                {
                    "severity": "blocking",
                    "location": "tagnorm/normalize.py",
                    "requirement": "Preserve the order of first occurrences",
                    "explanation": f"bridge check {c['id']!r} {c['status']}: "
                    + (c.get("stdout_tail") or c.get("stderr_tail") or "")[-400:],
                    "requested_change": "Make all required checks pass without editing tests",
                }
                for c in failing
            ] or [{"severity": "blocking", "explanation": "; ".join(gate["blockers"])}]
            changes = {
                **template,
                "verdict": "changes_requested",
                "findings": findings,
                "reviewer_label": "scripted-demo-supervisor",
                "idempotency_key": f"changes-{run['attempt_id']}",
            }
            cli.call(
                "review changes_requested",
                "review",
                task_id,
                "--file",
                _write_json(base / f"review-{round_no}-changes.json", changes),
            )
        final = cli.call("status (fresh process)", "status", task_id)
        report["timeline"] = timeline
        report["final_state"] = final["state"]
        after = checkout_fingerprint(str(repo))
        attempts = final["attempts"]
        checks = {
            "final_state_succeeded": final["state"] == "SUCCEEDED",
            "state_read_by_fresh_process": True,
            "source_checkout_unchanged": before == after,
            "all_attempts_simulated": all(
                a["evidence_level"] == "offline-simulated" for a in attempts
            ),
            "no_model_calls_recorded": all(
                (a.get("usage") or {}).get("model_calls_made_by_test") == 0 for a in attempts
            ),
        }
        if scenario == "bug-then-repair":
            checks["first_attempt_failed_bridge_verification"] = (
                bool(timeline) and timeline[0]["bridge_verification"] == "failed"
            )
            checks["first_attempt_executor_claimed_pass"] = (
                bool(timeline) and timeline[0]["executor_claimed_tests"] == "passed"
            )
            checks["approve_on_failing_evidence_rejected"] = (
                bool(timeline)
                and timeline[0].get("approve_probe_rejected_with") == "APPROVAL_GATE_FAILED"
            )
            checks["repaired_in_second_attempt"] = (
                len(timeline) == 2 and timeline[1]["bridge_verification"] == "passed"
            )
        else:
            checks["single_attempt"] = len(attempts) == 1
        report["checks"] = checks
        report["demo_passed"] = all(checks.values())
    except DemoStepError as exc:
        report["demo_passed"] = False
        report["error"] = str(exc)
    report["steps"] = cli.steps
    if cleanup:
        shutil.rmtree(base, ignore_errors=True)
        report["workdir"] = None
    return report
