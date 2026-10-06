"""Cross-task resolution, total verification and delivery with simulated executors only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness_bridge.coordination import AdvisorClaim
from harness_bridge.errors import BridgeError
from harness_bridge.service import Bridge
from harness_bridge.workspace import checkout_fingerprint, git
from tests.conftest import Fixture
from tests.helpers.reviews import review_for
from tests.integration.test_coordination import setup_goal, takeover
from tests.integration.test_delivery import deliver
from tests.integration.test_dependency_baselines import approve, children
from tests.integration.test_goal_planning import control, plan, submit
from tests.integration.test_integration_candidates import materialize, request
from tests.integration.test_integration_checks import candidate, claim_args, command, decision


def conflict(fx: Fixture, **limits: Any) -> tuple[Bridge, dict[str, Any], dict[str, Any]]:
    b, g = setup_goal(fx, **limits)
    ids = children(b, g, plan(fx, "a"), plan(fx, "b"))
    a = approve(b, ids["a"], {"tagnorm/shared.txt": "a\n"})
    c = approve(b, ids["b"], {"tagnorm/shared.txt": "b\n", "tagnorm/pending.txt": "keep\n"})
    spec = request(fx, a, c)
    spec["verification"] = [
        command(
            "from pathlib import Path; assert Path('tagnorm/shared.txt').read_text() == 'a+b\\n'; "
            "assert Path('tagnorm/pending.txt').read_text() == 'keep\\n'"
        )
    ]
    record = materialize(b, b.integrations.freeze(g["goal_id"], spec, "first"))
    assert record["phase"] == "CONFLICT"
    return b, g, record


def repair_plan(fx: Fixture, source: dict[str, Any], key: str = "resolve") -> dict[str, Any]:
    return {
        **plan(fx, key),
        "integration_repair": {
            "integration_id": source["integration_id"],
            "reason": "combine both APIs and retain pending files",
        },
    }


def resolved_request(fx: Fixture, source: dict[str, Any], child: str, task: str) -> dict[str, Any]:
    return {
        **request(fx, *(i["task_id"] for i in source["inputs"]), task),
        "verification": source["verification"],
        "repair_child_id": child,
    }


def test_conflict_repair_packet_budget_exact_review_delivery_and_cleanup(fx: Fixture) -> None:
    b, g, original = conflict(fx)
    source = checkout_fingerprint(str(fx.repo))
    snapshots = [b.status(i["task_id"])["approved_snapshot"] for i in original["inputs"]]
    p = repair_plan(fx, original)
    batch = submit(b, g, p, key="repair")
    child = batch["children"][0]["child_id"]
    assert submit(b, g, p, key="repair") == {**batch, "replayed": True}
    assert b.coordination.status(g["goal_id"])["budget"]["attempts"] == 2
    task = b.materialize(child)["task_id"]
    root = Path(b.store.get_task(task).worktree_path)
    assert (root / "tagnorm/shared.txt").read_text() == "a\n"
    assert not (root / "tagnorm/pending.txt").exists()
    with b.store.transaction() as cur:
        context = b._child_context(cur, task)
    binding = context["integration_repair"]
    assert binding["source"]["result"] == original["result"]
    assert [i["task_id"] for i in binding["pending_inputs"]] == [original["inputs"][1]["task_id"]]
    b.run(task)
    (root / "tagnorm/shared.txt").write_text("a+b\n")
    (root / "tagnorm/pending.txt").write_text("keep\n")
    b.verify(task)
    b.review(task, review_for(b.artifacts(task), "approve", "resolved"))
    budget = b.coordination.status(g["goal_id"])["budget"]
    assert budget["attempts"] == 3 and budget["repairs"] == 1
    repaired = materialize(
        b,
        b.integrations.freeze(
            g["goal_id"], resolved_request(fx, original, child, task), "resolved"
        ),
    )
    assert repaired["phase"] == "CANDIDATE"
    for item in repaired["inputs"]:
        assert (
            git(
                [
                    "merge-base",
                    "--is-ancestor",
                    item["commit_sha"],
                    repaired["result"]["commit_sha"],
                ],
                cwd=fx.repo,
                check=False,
            ).returncode
            == 0
        )
    with pytest.raises(BridgeError):
        deliver(b, g, repaired["integration_id"])
    assert b.integration_checks.verify(repaired["integration_id"], "total")["status"] == "passed"
    b.integration_checks.review(repaired["integration_id"], decision(b, repaired["integration_id"]))
    receipt = deliver(b, g, repaired["integration_id"])
    assert receipt["tree_sha"] == repaired["result"]["tree_sha"]
    assert [b.status(i["task_id"])["approved_snapshot"] for i in original["inputs"]] == snapshots
    with b.store.transaction() as cur:
        assert b.integrations.get(cur, original["integration_id"])["result"] == original["result"]
    preview = b.cleanup.preview(g["goal_id"])
    cleaned = b.cleanup.apply(g["goal_id"], preview["request_template"], "cleanup")
    assert any(r["outcome"] == "removed" for r in cleaned["resources"])
    assert root.exists()  # approved working changes are retained, never force removed
    assert b.coordination.status(g["goal_id"])["state"] == "DELIVERED"
    assert checkout_fingerprint(str(fx.repo)) == source
    assert b.coordination.status(g["goal_id"])["budget"] == budget
    b.close()


def test_failed_total_check_repairs_in_new_workspace_and_can_iterate(fx: Fixture) -> None:
    b, g = setup_goal(fx, max_attempts=4, max_repairs=3)
    child = children(b, g, plan(fx, "a"))["a"]
    task = approve(b, child)
    spec = request(fx, task)
    spec["verification"] = [
        command("from pathlib import Path; assert Path('tagnorm/done').exists()")
    ]
    original = materialize(b, b.integrations.freeze(g["goal_id"], spec, "first"))
    for cycle in (1, 2):
        ident = original["integration_id"]
        run = b.integration_checks.verify(ident, "failed")
        assert run["status"] == "failed"
        with pytest.raises(BridgeError):
            deliver(b, g, ident)
        child = submit(b, g, repair_plan(fx, original, f"fix{cycle}"), key=f"fix{cycle}")[
            "children"
        ][0]["child_id"]
        assert (
            b.plans.status(child)["baseline"]["integration_repair"]["verification_run"]["run_id"]
            == run["run_id"]
        )
        task = approve(b, child, {"tagnorm/done": "ok"} if cycle == 2 else None)
        original = materialize(
            b,
            b.integrations.freeze(
                g["goal_id"], resolved_request(fx, original, child, task), f"resolved{cycle}"
            ),
        )
    ident = original["integration_id"]
    assert b.integration_checks.verify(ident, "passed")["status"] == "passed"
    b.integration_checks.review(ident, decision(b, ident))
    deliver(b, g, ident)
    assert b.coordination.status(g["goal_id"])["budget"]["repairs"] == 2
    b.close()


@pytest.mark.parametrize(
    "case", ["attempts", "repairs", "stale", "unknown", "cancelled", "membership", "foreign"]
)
def test_repair_creation_refuses_unsafe_or_unbudgeted_bindings(fx: Fixture, case: str) -> None:
    limits = (
        {"max_attempts": 2}
        if case == "attempts"
        else ({"max_repairs": 0} if case == "repairs" else {})
    )
    b, g, original = conflict(fx, **limits)
    if case == "stale":
        takeover(b, g)
    elif case == "unknown":
        with b.store.transaction() as cur:
            cur.execute(
                "UPDATE attempts SET exit_confirmed=NULL WHERE task_id=?",
                (original["inputs"][0]["task_id"],),
            )
    elif case == "cancelled":
        control(b, g, "cancel")
    elif case == "membership":
        submit(b, g, plan(fx, "extra"), key="extra")
    elif case == "foreign":
        original["integration_id"] = "missing"
    with pytest.raises(BridgeError):
        submit(b, g, repair_plan(fx, original), key="repair")
    with b.store.transaction() as cur:
        assert all(p["key"] != "resolve" for p in b.plans.list_in_transaction(cur, g["goal_id"]))
    b.close()


@pytest.mark.parametrize(
    "case", ["omit_original", "omit_repair_selector", "weaken_checks", "reorder", "unapproved"]
)
def test_resolution_never_bypasses_required_inputs_or_total_checks(fx: Fixture, case: str) -> None:
    b, g, original = conflict(fx)
    child = submit(b, g, repair_plan(fx, original), key="repair")["children"][0]["child_id"]
    task = b.materialize(child)["task_id"] if case == "unapproved" else approve(b, child)
    spec = resolved_request(fx, original, child, task)
    if case == "omit_original":
        spec["task_ids"].pop(0)
    elif case == "omit_repair_selector":
        spec.pop("repair_child_id")
    elif case == "weaken_checks":
        spec["verification"] = [command()]
    elif case == "reorder":
        spec["task_ids"] = list(reversed(spec["task_ids"]))
    with pytest.raises(BridgeError):
        b.integrations.freeze(g["goal_id"], spec, "bad")
    b.close()


def test_takeover_reopen_cli_planning_and_context_tampering(fx: Fixture) -> None:
    b, g, original = conflict(fx)
    file = fx.base / "repair.json"
    file.write_text(json.dumps({"schema_version": "1.0", "children": [repair_plan(fx, original)]}))
    _, batch = fx.cli(
        "goal",
        "plan",
        g["goal_id"],
        "--file",
        str(file),
        "--idempotency-key",
        "repair",
        *claim_args(b),
    )
    child = batch["children"][0]["child_id"]
    new_claim = AdvisorClaim.model_validate(takeover(b, g)["advisor_claim"])
    with pytest.raises(BridgeError):
        b.materialize(child)
    b.close()
    b = Bridge(fx.state_dir, advisor_claim=new_claim)
    task = b.materialize(child)["task_id"]
    ref = original["result"]["ref"]
    git(["update-ref", ref, g["base_sha"]], cwd=fx.repo)
    with pytest.raises(BridgeError):
        b.run(task)
    assert b.store.get_task(task).attempts_used == 0
    b.close()


def test_initial_repair_dispatch_cannot_bypass_goal_repair_budget(fx: Fixture) -> None:
    b, g, original = conflict(fx, max_attempts=5, max_repairs=1)
    child = submit(b, g, repair_plan(fx, original), key="repair")["children"][0]["child_id"]
    task = b.materialize(child)["task_id"]
    # An intervening ordinary repair consumes the shared budget; planning did not reserve it.
    with b.store.transaction() as cur:
        cur.execute(
            "UPDATE attempts SET kind='repair' WHERE task_id=?", (original["inputs"][0]["task_id"],)
        )
    with pytest.raises(BridgeError) as error:
        b.run(task)
    assert error.value.code == "BUDGET_EXHAUSTED" and b.store.get_task(task).attempts_used == 0
    b.close()


def test_later_child_composes_after_exact_repair_prefix(fx: Fixture) -> None:
    b, g, original = conflict(fx, max_attempts=4)
    child = submit(b, g, repair_plan(fx, original), key="repair")["children"][0]["child_id"]
    task = approve(b, child, {"tagnorm/shared.txt": "a+b\n", "tagnorm/pending.txt": "keep\n"})
    later = submit(b, g, plan(fx, "later"), key="later")["children"][0]["child_id"]
    extra = approve(b, later, {"tagnorm/later.txt": "later\n"})
    spec = resolved_request(fx, original, child, task)
    spec["task_ids"].append(extra)
    record = materialize(b, b.integrations.freeze(g["goal_id"], spec, "with-later"))
    assert record["phase"] == "CANDIDATE"
    assert (Path(record["workspace"]["path"]) / "tagnorm/later.txt").read_text() == "later\n"
    assert b.integration_checks.verify(record["integration_id"], "verify")["status"] == "passed"
    b.close()


def test_passed_candidate_needs_explicit_changes_request_before_repair(fx: Fixture) -> None:
    b, g, ident = candidate(fx, [command()])
    b.integration_checks.verify(ident, "passing")
    original = b.integrations.status(ident)
    p = repair_plan(fx, original)
    with pytest.raises(BridgeError):
        submit(b, g, p, key="repair")
    review = b.integration_checks.review(
        ident,
        decision(
            b,
            ident,
            verdict="changes_requested",
            findings=[{"severity": "major", "explanation": "total tests omit an API requirement"}],
        ),
    )
    child = submit(b, g, p, key="repair")["children"][0]["child_id"]
    assert b.plans.status(child)["baseline"]["integration_repair"]["review"] == {
        k: v for k, v in review.items() if k != "replayed"
    }
    b.close()
