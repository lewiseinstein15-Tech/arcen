"""Durable manual-run checkpoints; ambiguous runs cannot resume automatically."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_harness_comparison import provider
from test_manual_campaign import budget, run, setup
from test_probe_execution import Boundary

from arcen.harness import HarnessError, probe_container
from arcen.harness import manual_campaign as module
from arcen.harness.campaign_journal import CampaignJournal, CampaignStopped
from arcen.harness.cli import _init, main


def plan(args):
    store, baseline, candidates, _, _, commit, _ = args
    journal = CampaignJournal(store, create=True)
    return journal, journal.plan(baseline, candidates, "inspect project", commit)


def test_full_run_journals_completed_reviews_and_never_moves_ref(tmp_path, monkeypatch):
    args = setup(tmp_path)
    store, _, candidates, _, _, _, reviews = args
    adopted = _init(str(store.root))
    journal, rec = plan(args)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    result = run(args, journal=journal, campaign_id=rec.id)
    assert result.stop_reason is None and len(calls) == 6
    saved = CampaignJournal(store).get(rec.id)
    assert saved.state == "completed" and saved.phase == "done" and saved.cursor == 2
    assert saved.candidates == candidates
    assert saved.reviews == tuple(item.review.id for item in result.completed)
    assert all(reviews.get(review).state == "pending" for review in saved.reviews)
    assert b"inspect project" not in journal.path.read_bytes()
    with pytest.raises(HarnessError, match="already started"):
        journal.claim(rec.id, args[1], candidates, "inspect project", args[5])
    from arcen.harness.lineage import HarnessLineage

    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_concurrent_claims_have_only_one_winner(tmp_path):
    args = setup(tmp_path)
    journal, rec = plan(args)

    def claim(_):
        try:
            journal.claim(rec.id, args[1], args[2], "inspect project", args[5])
            return True
        except HarnessError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))
    assert sum(results) == 1
    assert journal.get(rec.id).state == "running"


def test_plan_identity_and_stop_before_start(tmp_path, monkeypatch):
    args = setup(tmp_path)
    journal, rec = plan(args)
    with pytest.raises(HarnessError, match="mismatch"):
        journal.claim(rec.id, args[1], args[2], "changed task", args[5])
    assert journal.get(rec.id).state == "ready"
    stopped = journal.request_stop(rec.id)
    assert stopped.state == "stopped" and stopped.stop_requested
    monkeypatch.setattr(
        module, "snapshot_git_commit", lambda *a: pytest.fail("unexpected snapshot")
    )
    with pytest.raises(HarnessError):
        run(args, journal=journal, campaign_id=rec.id)


def test_stop_during_reference_stops_before_candidate(tmp_path, monkeypatch):
    args = setup(tmp_path)
    journal, rec = plan(args)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch, hook=lambda n: journal.request_stop(rec.id) if n == 1 else None)
    result = run(args, journal=journal, campaign_id=rec.id)
    assert result.stop_reason == "stopped" and len(calls) == 2 and not result.completed
    saved = journal.get(rec.id)
    assert saved.state == "stopped" and saved.phase == "reference" and saved.cursor == 0
    assert args[-1].list() == () and Boundary.instances[-1].closed


def test_stop_during_recording_preserves_pending_review(tmp_path, monkeypatch):
    args = setup(tmp_path)
    journal, rec = plan(args)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    orig = args[-1].request_from_comparison

    def recording(pair):
        result = orig(pair)
        journal.request_stop(rec.id)
        return result

    monkeypatch.setattr(args[-1], "request_from_comparison", recording)
    result = run(args, journal=journal, campaign_id=rec.id)
    assert result.stop_reason == "stopped" and len(result.completed) == 1 and len(calls) == 4
    saved = journal.get(rec.id)
    assert (
        saved.state == "stopped"
        and saved.cursor == 1
        and saved.reviews == (result.completed[0].review.id,)
    )
    assert args[-1].get(saved.reviews[0]).state == "pending"


def test_failed_run_is_terminal_and_prior_progress_is_saved(tmp_path, monkeypatch):
    args = setup(tmp_path)
    journal, rec = plan(args)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch, fail_at=5)
    result = run(args, journal=journal, campaign_id=rec.id)
    saved = journal.get(rec.id)
    assert result.stop_reason == "candidate_failed" and saved.state == "failed"
    assert saved.phase == "candidate" and saved.cursor == 1 and len(saved.reviews) == 1
    with pytest.raises(HarnessError):
        run(args, journal=journal, campaign_id=rec.id)


def test_crash_leaves_ambiguous_running_state_and_refuses_replay(tmp_path, monkeypatch):
    args = setup(tmp_path)
    journal, rec = plan(args)
    monkeypatch.setattr(
        module, "_run_bound_probe", lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    with pytest.raises(KeyboardInterrupt):
        run(args, journal=journal, campaign_id=rec.id)
    assert journal.get(rec.id).state == "running"
    with pytest.raises(HarnessError, match="already started"):
        journal.claim(rec.id, args[1], args[2], "inspect project", args[5])
    assert journal.request_stop(rec.id).stop_requested


def test_atomic_stage_transitions_and_stop_latching(tmp_path):
    args = setup(tmp_path)
    journal, rec = plan(args)
    journal.claim(rec.id, args[1], args[2], "inspect project", args[5])
    with pytest.raises(HarnessError):
        journal.advance(rec.id, "candidate", "judge")
    journal.advance(rec.id, "reference", "candidate")
    journal.request_stop(rec.id)
    with pytest.raises(CampaignStopped):
        journal.checkpoint(rec.id, "candidate", 0)
    assert journal.get(rec.id).state == "stopped"
    with pytest.raises(HarnessError):
        journal.advance(rec.id, "candidate", "judge")


def test_cli_status_and_stop_do_not_execute_or_adopt(tmp_path, capsys):
    args = setup(tmp_path)
    store = args[0]
    _init(str(store.root))
    journal, rec = plan(args)
    assert main(["--store", str(store.root), "campaign", "status", rec.id]) == 0
    assert "state=ready" in capsys.readouterr().out
    assert main(["--store", str(store.root), "campaign", "stop", rec.id]) == 0
    out = capsys.readouterr().out
    assert "state=stopped" in out and "no adoption" in out
    assert journal.get(rec.id).stop_requested


def test_tampering_and_database_symlinks_fail_closed(tmp_path):
    args = setup(tmp_path)
    journal, rec = plan(args)
    with sqlite3.connect(journal.path) as db:
        db.execute("UPDATE campaigns SET cursor=1 WHERE id=?", (rec.id,))
    with pytest.raises(HarnessError):
        journal.get(rec.id)
    with pytest.raises(HarnessError):
        journal.claim(rec.id, args[1], args[2], "inspect project", args[5])
    journal.path.unlink()
    victim = tmp_path / "victim"
    victim.write_text("safe")
    journal.path.symlink_to(victim)
    for create in (True, False):
        with pytest.raises(HarnessError):
            CampaignJournal(args[0], create=create)
    assert victim.read_text() == "safe"


def test_mismatched_or_incomplete_journal_settings_fail_before_snapshot(tmp_path, monkeypatch):
    args = setup(tmp_path)
    journal, rec = plan(args)
    monkeypatch.setattr(module, "snapshot_git_commit", lambda *a: pytest.fail("snapshot"))
    with pytest.raises(HarnessError):
        run(args, journal=journal)
    with pytest.raises(HarnessError):
        run(args, campaign_id=rec.id)
    assert journal.get(rec.id).state == "ready"
    assert budget().snapshot().trials == 0


def test_schema_corruption_rejected_without_repair(tmp_path):
    args = setup(tmp_path)
    journal, _ = plan(args)
    with sqlite3.connect(journal.path) as db:
        db.execute("ALTER TABLE campaigns ADD COLUMN foreign_data TEXT")
    for create in (True, False):
        with pytest.raises(HarnessError, match="schema"):
            CampaignJournal(args[0], create=create)


def test_real_docker_journaled_campaign_when_explicitly_enabled(tmp_path, monkeypatch):
    import os

    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires real Docker and sandbox image")
    pytest.importorskip("docker")
    args = setup(tmp_path)
    journal, rec = plan(args)
    provider(monkeypatch)
    result = run(args, journal=journal, campaign_id=rec.id)
    assert result.stop_reason is None and len(result.completed) == 2
    assert journal.get(rec.id).state == "completed"


def durable(store):
    from arcen.harness.durable_budget import DurableBudget

    return DurableBudget.create(
        store, max_trials=3, max_model_calls=6, max_judge_calls=2, admission_seconds=120
    )


def test_bound_plan_rejects_other_budget_before_git_docker_or_provider(tmp_path, monkeypatch):
    args = setup(tmp_path)
    journal = CampaignJournal(args[0], create=True)
    expected, wrong = durable(args[0]), durable(args[0])
    rec = journal.plan(args[1], args[2], "inspect project", args[5], budget=expected)
    assert rec.budget_id == expected.id
    monkeypatch.setattr(module, "snapshot_git_commit", lambda *a: pytest.fail("unexpected git"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("unexpected Docker")
    )
    with pytest.raises(HarnessError, match="mismatch"):
        run(args, budget=wrong, journal=journal, campaign_id=rec.id)
    with pytest.raises(HarnessError, match="mismatch"):
        run(args, budget=budget(), journal=journal, campaign_id=rec.id)
    assert journal.get(rec.id).state == "ready"
    assert expected.snapshot().trials == wrong.snapshot().trials == 0


def test_bound_plan_executes_only_with_the_bound_budget(tmp_path, monkeypatch):
    args = setup(tmp_path)
    journal = CampaignJournal(args[0], create=True)
    cap = durable(args[0])
    rec = journal.plan(args[1], args[2], "inspect project", args[5], budget=cap)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    result = run(args, budget=cap, journal=journal, campaign_id=rec.id)
    assert result.stop_reason is None and len(calls) == 6
    assert CampaignJournal(args[0]).get(rec.id).budget_id == cap.id
    assert cap.snapshot().trials == 3


def test_v1_read_only_compatibility_migration_and_old_instance_safety(tmp_path):
    args = setup(tmp_path)
    journal, legacy = plan(args)
    with sqlite3.connect(journal.path) as db:
        db.execute("DROP TRIGGER campaign_budget_guard")
        db.execute("ALTER TABLE campaigns DROP COLUMN budget_id")
        db.execute("PRAGMA user_version=1")
    old = CampaignJournal(args[0])
    assert old.get(legacy.id).budget_id is None
    with sqlite3.connect(journal.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
    upgraded = CampaignJournal(args[0], create=True)
    assert upgraded.get(legacy.id).budget_id is None
    with sqlite3.connect(journal.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    cap = durable(args[0])
    new = upgraded.plan(args[1], args[2], "inspect project", args[5], budget=cap)
    assert old.get(new.id).budget_id == cap.id
    with pytest.raises(HarnessError, match="mismatch"):
        old.claim(new.id, args[1], args[2], "inspect project", args[5])
    assert upgraded.get(new.id).state == "ready"
    old.claim(legacy.id, args[1], args[2], "inspect project", args[5])
    assert upgraded.get(legacy.id).state == "running"


def test_budget_binding_requires_same_store_live_budget_and_well_formed_record(tmp_path):
    args = setup(tmp_path)
    journal = CampaignJournal(args[0], create=True)
    from arcen.harness.store import HarnessStore

    other = durable(HarnessStore(tmp_path / "other"))
    with pytest.raises(HarnessError, match="same store"):
        journal.plan(args[1], args[2], "inspect project", args[5], budget=other)
    cap = durable(args[0])
    rec = journal.plan(args[1], args[2], "inspect project", args[5], budget=cap)
    with sqlite3.connect(journal.path) as db:
        db.execute("UPDATE campaigns SET budget_id='not-an-id' WHERE id=?", (rec.id,))
    with pytest.raises(HarnessError, match="invalid campaign record"):
        journal.get(rec.id)
    cap.stop()
    with pytest.raises(HarnessError, match="budget closed"):
        journal.plan(args[1], args[2], "inspect project", args[5], budget=cap)


def test_bound_plan_claim_race_has_one_winner(tmp_path):
    args = setup(tmp_path)
    journal = CampaignJournal(args[0], create=True)
    cap = durable(args[0])
    rec = journal.plan(args[1], args[2], "inspect project", args[5], budget=cap)

    def claim(_):
        try:
            journal.claim(rec.id, args[1], args[2], "inspect project", args[5], budget=cap)
            return True
        except HarnessError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(claim, range(8))) == 1
    assert journal.get(rec.id).budget_id == cap.id


def test_old_database_client_cannot_claim_bound_plan_without_new_guard(tmp_path):
    args = setup(tmp_path)
    journal = CampaignJournal(args[0], create=True)
    cap = durable(args[0])
    rec = journal.plan(args[1], args[2], "inspect project", args[5], budget=cap)
    with (
        sqlite3.connect(journal.path) as db,
        pytest.raises(sqlite3.OperationalError, match="arcen_campaign_budget"),
    ):
        db.execute(
            "UPDATE campaigns SET state='running',phase='reference' WHERE id=? AND state='ready'",
            (rec.id,),
        )
    assert journal.get(rec.id).state == "ready"
    journal.claim(rec.id, args[1], args[2], "inspect project", args[5], budget=cap)
    assert journal.get(rec.id).state == "running"


def test_guard_schema_tampering_rejected(tmp_path):
    args = setup(tmp_path)
    journal = CampaignJournal(args[0], create=True)
    with sqlite3.connect(journal.path) as db:
        db.execute("DROP TRIGGER campaign_budget_guard")
        db.execute(
            "CREATE TRIGGER campaign_budget_guard BEFORE UPDATE ON campaigns BEGIN SELECT 1; END"
        )
    with pytest.raises(HarnessError, match="schema"):
        CampaignJournal(args[0])
