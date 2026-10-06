"""Exact local delivery with isolated Git repositories and simulated executors."""

from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from harness_bridge.coordination import AdvisorClaim
from harness_bridge.errors import BridgeError
from harness_bridge.service import Bridge
from harness_bridge.workspace import checkout_fingerprint, git
from tests.conftest import Fixture
from tests.integration.test_coordination import goal_spec, takeover
from tests.integration.test_goal_planning import control, plan, submit
from tests.integration.test_integration_checks import candidate, claim_args, command, decision


def approved(fx: Fixture) -> tuple[Bridge, dict[str, Any], str]:
    b, goal, ident = candidate(fx, [command()])
    b.integration_checks.verify(ident, "verify")
    b.integration_checks.review(ident, decision(b, ident))
    return b, goal, ident


def request(ident: str, branch: str = "delivered/result") -> dict[str, str]:
    return {"integration_id": ident, "branch": branch}


def deliver(b: Bridge, g: dict[str, Any], ident: str, key: str = "deliver") -> dict[str, Any]:
    return b.deliveries.deliver(g["goal_id"], request(ident), key)


def crash(fx: Fixture, b: Bridge, g: dict[str, Any], ident: str, point: str) -> dict[str, Any]:
    code, _ = fx.cli(
        "goal",
        "deliver",
        g["goal_id"],
        "--integration",
        ident,
        "--branch",
        "delivered/result",
        "--idempotency-key",
        "deliver",
        *claim_args(b),
        check_ok=None,
        env={**os.environ, "HBRIDGE_TEST_FAULT": point},
    )
    assert code == 70
    result = b.coordination.status(g["goal_id"])["delivery"]
    assert result["status"] == "pending"
    return result["receipt"]


def test_exact_delivery_preserves_dirty_advanced_source_and_records_base_difference(
    fx: Fixture,
) -> None:
    b, g, ident = approved(fx)
    assert b.coordination.status(g["goal_id"])["state"] == "READY_TO_DELIVER"
    expected = b.integrations.status(ident)["result"]
    (fx.repo / "later.txt").write_text("source advanced")
    git(["add", "--", "later.txt"], cwd=fx.repo)
    git(["commit", "-qm", "new user commit"], cwd=fx.repo)
    (fx.repo / "keep.txt").write_text("user staged content")
    git(["add", "--", "keep.txt"], cwd=fx.repo)
    (fx.repo / "keep.txt").write_text("user unstaged content")
    (fx.repo / "untracked.txt").write_text("user untracked content")
    before = checkout_fingerprint(str(fx.repo))
    budget = b.coordination.status(g["goal_id"])["budget"]
    receipt = deliver(b, g, ident)
    assert receipt["status"] == "delivered" and not receipt["recovered_publication"]
    assert receipt["commit_sha"] == expected["commit_sha"]
    assert receipt["tree_sha"] == expected["tree_sha"]
    observed = receipt["source_at_preparation"]
    assert observed["head_differs_from_base"] and observed["has_uncommitted_changes"]
    assert observed["base_only_commits"] == 0 and observed["source_only_commits"] == 1
    assert receipt["observed"]["ref_status"] == "matching"
    assert (
        git(["rev-parse", "delivered/result^{tree}"], cwd=fx.repo).stdout.decode().strip()
        == expected["tree_sha"]
    )
    assert git(
        ["cat-file", "-e", "delivered/result:later.txt"], cwd=fx.repo, check=False
    ).returncode
    assert checkout_fingerprint(str(fx.repo)) == before
    assert (fx.repo / "keep.txt").read_text() == "user unstaged content"
    status = b.coordination.status(g["goal_id"])
    assert status["state"] == "DELIVERED" and status["budget"] == budget
    assert deliver(b, g, ident) == {**receipt, "replayed": True}
    assert b.deliveries.status(receipt["delivery_id"])["observed"]["ref_status"] == "matching"
    with pytest.raises(BridgeError) as conflict:
        b.deliveries.deliver(g["goal_id"], request(ident, "different"), "deliver")
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    # Terminal goals cannot silently grow new work or reinterpret the delivery.
    for action in (
        lambda: submit(b, g, plan(fx, "extra"), key="extra"),
        lambda: b.integration_checks.verify(ident, "again"),
        lambda: control(b, g, "cancel"),
        lambda: b.deliveries.abort(receipt["delivery_id"], "cannot erase delivery"),
    ):
        with pytest.raises(BridgeError):
            action()
    b.close()


@pytest.mark.parametrize(
    "change", ["candidate", "log", "new_integration", "takeover", "negative", "termination"]
)
def test_stale_or_superseded_approval_cannot_deliver(fx: Fixture, change: str) -> None:
    b, g, ident = approved(fx)
    status = b.integrations.status(ident)
    if change == "candidate":
        (Path(status["workspace"]["path"]) / "late.txt").write_text("unapproved")
    elif change == "log":
        run = status["verification_run"]
        (b.integration_checks.directory(run) / "acceptance.stdout.log").write_text("tampered")
    elif change == "new_integration":
        spec = {
            "schema_version": "1.0",
            "task_ids": [i["task_id"] for i in status["inputs"]],
            "verification": status["verification"],
        }
        b.integrations.freeze(g["goal_id"], spec, "new-selection")
    elif change == "takeover":
        b.advisor_claim = AdvisorClaim.model_validate(takeover(b, g)["advisor_claim"])
    elif change == "negative":
        b.integration_checks.review(
            ident,
            decision(
                b,
                ident,
                "blocked",
                verdict="blocked",
                findings=[{"severity": "major", "explanation": "Needs another decision"}],
            ),
        )
    else:
        control(b, g, "cancel")
    assert b.coordination.status(g["goal_id"])["state"] != "READY_TO_DELIVER"
    with pytest.raises(BridgeError):
        deliver(b, g, ident)
    with b.store.transaction() as cur:
        assert cur.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 0
    assert git(
        ["show-ref", "--verify", "--quiet", "refs/heads/delivered/result"], cwd=fx.repo, check=False
    ).returncode
    b.close()


@pytest.mark.parametrize(
    "existing",
    ["different", "identical", "symbolic", "dangling", "case_alias", "invalid", "unborn_checkout"],
)
def test_existing_or_selected_branch_is_never_overwritten(fx: Fixture, existing: str) -> None:
    b, g, ident = approved(fx)
    branch = "delivered/result"
    if existing in ("different", "identical", "case_alias"):
        sha = (
            b.integrations.status(ident)["result"]["commit_sha"]
            if existing == "identical"
            else g["base_sha"]
        )
        git(
            [
                "update-ref",
                "refs/heads/" + (branch.upper() if existing == "case_alias" else branch),
                sha,
            ],
            cwd=fx.repo,
        )
    elif existing in ("symbolic", "dangling"):
        target = "refs/heads/main" if existing == "symbolic" else "refs/heads/missing"
        git(["symbolic-ref", f"refs/heads/{branch}", target], cwd=fx.repo)
    elif existing == "invalid":
        branch = "bad..branch"
    else:
        root = fx.base / "other-worktree"
        git(["worktree", "add", "--detach", "--", str(root), g["base_sha"]], cwd=fx.repo)
        git(["symbolic-ref", "HEAD", f"refs/heads/{branch}"], cwd=root)
        (root / "keep.txt").write_text("user checkout selected an unborn branch")
    before = git(
        ["for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)"], cwd=fx.repo
    ).stdout
    with pytest.raises(BridgeError):
        b.deliveries.deliver(g["goal_id"], request(ident, branch), "deliver")
    assert (
        git(["for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)"], cwd=fx.repo).stdout
        == before
    )
    with b.store.transaction() as cur:
        assert cur.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 0
    if existing == "unborn_checkout":
        assert (
            fx.base / "other-worktree/keep.txt"
        ).read_text() == "user checkout selected an unborn branch"
    b.close()


@pytest.mark.parametrize(
    "point",
    ["after_delivery_reserved", "before_delivery_refs_created", "after_delivery_refs_created"],
)
def test_actual_crash_retry_adopts_only_atomic_exact_ref_pair(fx: Fixture, point: str) -> None:
    b, g, ident = approved(fx)
    prepared = crash(fx, b, g, ident, point)
    status = b.deliveries.status(prepared["delivery_id"])
    assert status["status"] == "prepared"
    published = point == "after_delivery_refs_created"
    assert status["observed"]["ref_status"] == ("matching" if published else "absent")
    if published:
        # Publication was authorized before the crash. Later workspace edits cannot
        # rewrite the immutable branch, nor prevent recording that historical fact.
        root = Path(b.integrations.status(ident)["workspace"]["path"])
        (root / "later.txt").write_text("later workspace edit")
        with pytest.raises(BridgeError):
            b.deliveries.abort(prepared["delivery_id"], "already published")
    done = deliver(b, g, ident)
    assert done["delivery_id"] == prepared["delivery_id"] and done["replayed"]
    assert done["recovered_publication"] is published
    assert done["observed"]["ref_status"] == "matching"
    assert b.coordination.status(g["goal_id"])["state"] == "DELIVERED"
    events = b.coordination.status(g["goal_id"])["recent_events"]
    assert sum(e["type"] == "goal_delivered" for e in events) == 1
    b.close()


@pytest.mark.parametrize("published", [False, True])
def test_takeover_fences_old_delivery_and_can_record_already_published_history(
    fx: Fixture, published: bool
) -> None:
    b, g, ident = approved(fx)
    receipt = crash(
        fx, b, g, ident, "after_delivery_refs_created" if published else "after_delivery_reserved"
    )
    claim = takeover(b, g)["advisor_claim"]
    with pytest.raises(BridgeError) as stale:
        deliver(b, g, ident)
    assert stale.value.code == "STALE_ADVISOR"
    b.advisor_claim = AdvisorClaim.model_validate(claim)
    if published:
        assert deliver(b, g, ident)["status"] == "delivered"
    else:
        with pytest.raises(BridgeError):
            deliver(b, g, ident)
        aborted = b.deliveries.abort(receipt["delivery_id"], "re-approve under current Advisor")
        assert aborted["status"] == "aborted"
        assert b.deliveries.abort(receipt["delivery_id"], "re-approve under current Advisor")[
            "replayed"
        ]
        assert deliver(b, g, ident)["status"] == "aborted"
        b.integration_checks.review(ident, decision(b, ident, "new-advisor"))
        assert deliver(b, g, ident, key="new-intent")["status"] == "delivered"
    b.close()


@pytest.mark.parametrize(
    "change", ["delete_branch", "move_branch", "symbolic_branch", "delete_proof"]
)
def test_completed_receipt_replay_never_recreates_or_resets_refs(fx: Fixture, change: str) -> None:
    b, g, ident = approved(fx)
    receipt = deliver(b, g, ident)
    ref = "refs/heads/delivered/result"
    if change == "delete_branch":
        git(["update-ref", "-d", ref], cwd=fx.repo)
    elif change == "move_branch":
        git(["update-ref", ref, g["base_sha"]], cwd=fx.repo)
    elif change == "symbolic_branch":
        git(["symbolic-ref", ref, "refs/heads/missing"], cwd=fx.repo)
    else:
        git(["update-ref", "-d", receipt["proof_ref"]], cwd=fx.repo)
    before = git(
        ["for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)"], cwd=fx.repo
    ).stdout
    replay = deliver(b, g, ident)
    assert replay["status"] == "delivered" and replay["observed"]["ref_status"] == "changed"
    assert b.coordination.status(g["goal_id"])["state"] == "NEEDS_ATTENTION"
    assert (
        git(["for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)"], cwd=fx.repo).stdout
        == before
    )
    with pytest.raises(BridgeError):
        deliver(b, g, ident, key="new-name-does-not-reopen-goal")
    b.close()


def test_external_branch_race_does_not_leave_partial_proof_and_can_abort(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, g, ident = approved(fx)
    intercepted = False

    def competing(args: list[str], **kwargs: Any) -> Any:
        nonlocal intercepted
        if args == ["update-ref", "--stdin"] and not intercepted:
            intercepted = True
            git(["update-ref", "refs/heads/delivered/result", g["base_sha"]], cwd=fx.repo)
        return git(args, **kwargs)

    monkeypatch.setattr("harness_bridge.delivery.git", competing)
    with pytest.raises(BridgeError):
        deliver(b, g, ident)
    pending = b.coordination.status(g["goal_id"])["delivery"]["receipt"]
    assert b.deliveries.status(pending["delivery_id"])["observed"]["proof"] is None
    b.deliveries.abort(pending["delivery_id"], "user branch won the race")
    assert (
        git(["rev-parse", "delivered/result"], cwd=fx.repo).stdout.decode().strip() == g["base_sha"]
    )
    assert (
        b.deliveries.deliver(g["goal_id"], request(ident, "delivered/second"), "second")["status"]
        == "delivered"
    )
    b.close()


def test_same_key_delivery_race_has_one_intent_publication_and_completion(fx: Fixture) -> None:
    b, g, ident = approved(fx)
    barrier = Barrier(2)
    claim = b.advisor_claim

    def compete(_: int) -> dict[str, Any]:
        peer = Bridge(fx.state_dir, advisor_claim=claim)
        try:
            barrier.wait(timeout=10)
            return deliver(peer, g, ident)
        finally:
            peer.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(compete, [0, 1]))
    assert results[0]["delivery_id"] == results[1]["delivery_id"]
    assert sorted(r["replayed"] for r in results) == [False, True]
    events = b.coordination.status(g["goal_id"])["recent_events"]
    assert sum(e["type"] == "delivery_prepared" for e in events) == 1
    assert sum(e["type"] == "goal_delivered" for e in events) == 1
    b.close()


def test_other_goal_unknown_execution_blocks_ready_and_delivery(fx: Fixture) -> None:
    b, g, ident = approved(fx)
    old_claim = b.advisor_claim
    other = b.coordination.create(goal_spec(fx), "other")
    b.advisor_claim = AdvisorClaim.model_validate(other["advisor_claim"])
    task = b.create(fx.spec(), "other", goal_id=other["goal_id"])["task_id"]
    b.run(task)
    # Synthetic historical uncertainty; the actual fake child has already exited.
    with b.store.transaction() as cur:
        cur.execute("UPDATE attempts SET exit_confirmed=NULL WHERE task_id=?", (task,))
    b.advisor_claim = old_claim
    assert b.coordination.status(g["goal_id"])["state"] == "NEEDS_ATTENTION"
    with pytest.raises(BridgeError, match="no active or unknown"):
        deliver(b, g, ident)
    b.close()


def test_v8_upgrade_keeps_approval_and_cli_delivers_without_new_checks(fx: Fixture) -> None:
    b, g, ident = approved(fx)
    args = claim_args(b)
    before = b.integrations.status(ident)
    db = b.store.db_path
    b.close()
    with sqlite3.connect(db) as old:
        old.execute("DROP TABLE cleanup_requests")
        old.execute("DROP TABLE deliveries")
        old.execute("UPDATE meta SET value='8' WHERE key='schema_revision'")
    b = fx.bridge()
    assert b.integrations.status(ident) == before
    assert b.coordination.status(g["goal_id"])["state"] == "READY_TO_DELIVER"
    b.close()
    _, receipt = fx.cli(
        "goal",
        "deliver",
        g["goal_id"],
        "--integration",
        ident,
        "--branch",
        "delivered/result",
        "--idempotency-key",
        "deliver",
        *args,
    )
    assert receipt["status"] == "delivered"
    _, receipt = fx.cli("delivery", "status", receipt["delivery_id"])
    assert receipt["observed"]["ref_status"] == "matching"
    _, goal = fx.cli("goal", "status", g["goal_id"])
    assert goal["state"] == "DELIVERED"


@pytest.mark.parametrize("verify", [False, True])
def test_unverified_or_failed_total_acceptance_cannot_deliver(fx: Fixture, verify: bool) -> None:
    b, g, ident = candidate(fx, [command("raise SystemExit(1)")])
    if verify:
        assert b.integration_checks.verify(ident, "failed")["status"] == "failed"
    with pytest.raises(BridgeError) as refused:
        deliver(b, g, ident)
    assert refused.value.code == "APPROVAL_GATE_FAILED"
    assert b.coordination.status(g["goal_id"])["delivery"]["receipt"] is None
    b.close()


def test_pending_abort_cli_preserves_refs_and_dangling_proof_blocks_abort(fx: Fixture) -> None:
    b, g, ident = approved(fx)
    receipt = crash(fx, b, g, ident, "after_delivery_reserved")
    git(["symbolic-ref", receipt["proof_ref"], "refs/heads/missing"], cwd=fx.repo)
    _, error = fx.cli(
        "delivery",
        "abort",
        receipt["delivery_id"],
        "--reason",
        "abort",
        *claim_args(b),
        check_ok=False,
    )
    assert error["error"]["code"] == "DELIVERY_CONFLICT"
    assert b.deliveries.status(receipt["delivery_id"])["status"] == "prepared"
    # Remove only this test's injected symbolic ref; the bridge itself never removes it.
    git(["symbolic-ref", "--delete", receipt["proof_ref"]], cwd=fx.repo)
    _, aborted = fx.cli(
        "delivery", "abort", receipt["delivery_id"], "--reason", "abort", *claim_args(b)
    )
    assert aborted["status"] == "aborted"
    assert b.coordination.status(g["goal_id"])["state"] == "READY_TO_DELIVER"
    b.close()


def test_receipt_views_fail_closed_when_historical_review_metadata_is_missing(fx: Fixture) -> None:
    b, g, ident = approved(fx)
    receipt = deliver(b, g, ident)
    with b.store.transaction() as cur:
        cur.execute("DELETE FROM integration_reviews WHERE review_id=?", (receipt["review_id"],))
    assert b.deliveries.status(receipt["delivery_id"])["observed"]["ref_status"] == "unavailable"
    assert deliver(b, g, ident)["observed"]["ref_status"] == "unavailable"
    assert b.coordination.status(g["goal_id"])["state"] == "NEEDS_ATTENTION"
    b.close()
