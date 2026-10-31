"""Read-only classification of unsigned recorded outcomes, not adoption."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

import litellm
import pytest
from test_evidence_composition import completed

from arcen.harness import HarnessError, probe_container
from arcen.harness.cli import main
from arcen.harness.contrast_suggestions import suggest_recorded_wins
from arcen.harness.lineage import HarnessLineage
from arcen.harness.review import ReviewLedger
from arcen.harness.task_bank import TaskBank


def set_winner(ledger, review_id, winner, confidence):
    with sqlite3.connect(ledger.path) as db:
        db.execute(
            "UPDATE reviews SET winner=?,confidence=? WHERE id=?", (winner, confidence, review_id)
        )


def test_candidate_win_is_advisory_only_and_never_writes_or_calls_provider(
    tmp_path, monkeypatch, capsys
):
    store, adopted, baseline, task, journal, ledger, record, calls, _ = completed(
        tmp_path, monkeypatch
    )
    set_winner(ledger, record.reviews[0], "candidate", 0.1)
    set_winner(ledger, record.reviews[1], "tie", 1.0)
    before_objects = {path.name for path in store.objects.iterdir()}
    before_review, before_campaign = ledger.path.read_bytes(), journal.path.read_bytes()
    monkeypatch.setattr(litellm, "completion", lambda **_: pytest.fail("provider called"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("Docker")
    )
    report = suggest_recorded_wins(store, record.id, task)
    assert [item.category for item in report.items] == ["candidate-win", "tie"]
    assert report.items[0].review.id == record.reviews[0]
    assert report.items[0].changed_paths == ("prompts/draft.md",)
    args = ["--store", str(store.root), "campaign", "suggest", record.id, "--task-id", task]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Unsigned local summaries" in out and "no candidates selected or created" in out
    assert "1;" in out and "category: candidate-win" in out and "category: tie" in out
    assert all(review_id in out for review_id in record.reviews)
    assert "No provider calls, Docker, trial, approval, adoption or ref changes" in out
    assert {path.name for path in store.objects.iterdir()} == before_objects
    assert (
        ledger.path.read_bytes() == before_review and journal.path.read_bytes() == before_campaign
    )
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    assert len(calls) == 6 and report.campaign.baseline == baseline


def test_reference_win_and_rejected_candidate_are_never_suggested(tmp_path, monkeypatch):
    store, _, _, task, _, ledger, record, _, _ = completed(tmp_path, monkeypatch)
    set_winner(ledger, record.reviews[0], "reference", 0.99)
    set_winner(ledger, record.reviews[1], "candidate", 0.99)
    ledger.resolve(record.reviews[1], "rejected", "reviewer", saw_diff=True)
    result = suggest_recorded_wins(store, record.id, task)
    assert [item.category for item in result.items] == ["reference-win", "rejected"]


def test_all_candidate_wins_are_shown_without_ranking_by_confidence(tmp_path, monkeypatch):
    store, _, _, task, _, ledger, record, _, _ = completed(tmp_path, monkeypatch)
    set_winner(ledger, record.reviews[0], "candidate", 0.0)
    set_winner(ledger, record.reviews[1], "candidate", 1.0)
    result = suggest_recorded_wins(store, record.id, task)
    assert [item.review.id for item in result.items] == list(record.reviews)
    assert [item.category for item in result.items] == ["candidate-win", "candidate-win"]


def test_wrong_task_incomplete_campaign_and_invalid_workspace_fail_closed(tmp_path, monkeypatch):
    store, _, _, task, journal, ledger, record, _, _ = completed(tmp_path, monkeypatch)
    other = TaskBank(store).add("other", "another task").digest
    with pytest.raises(HarnessError, match="task does not match"):
        suggest_recorded_wins(store, record.id, other)
    ready = journal.plan(record.baseline, record.candidates, "inspect project", record.commit)
    with pytest.raises(HarnessError, match="completed campaign"):
        suggest_recorded_wins(store, ready.id, task)
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE reviews SET workspace=? WHERE id=?", ("0" * 64, record.reviews[1]))
    with pytest.raises(HarnessError, match="share a recorded workspace"):
        suggest_recorded_wins(store, record.id, task)


def test_changed_review_during_read_refused_before_any_output(tmp_path, monkeypatch, capsys):
    store, _, _, task, _, _ledger, record, _, _ = completed(tmp_path, monkeypatch)
    capsys.readouterr()
    original = ReviewLedger.get
    seen = 0

    def mutate_on_recheck(self, review_id):
        nonlocal seen
        seen += 1
        value = original(self, review_id)
        return replace(value, judge_confidence=0.123) if seen == 3 else value

    monkeypatch.setattr(ReviewLedger, "get", mutate_on_recheck)
    args = ["--store", str(store.root), "campaign", "suggest", record.id, "--task-id", task]
    assert main(args) == 1
    captured = capsys.readouterr()
    assert "changed during suggestion" in captured.err and "Suggested for" not in captured.out


def test_mismatched_commit_and_missing_task_object_are_refused(tmp_path, monkeypatch):
    store, _, _, task, _, ledger, record, _, _ = completed(tmp_path, monkeypatch)
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE reviews SET commit_id=? WHERE id=?", ("1" * 40, record.reviews[0]))
    with pytest.raises(HarnessError, match="metadata does not match"):
        suggest_recorded_wins(store, record.id, task)
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE reviews SET commit_id=? WHERE id=?", (record.commit, record.reviews[0]))
    store._path(task).unlink()
    with pytest.raises(HarnessError):
        suggest_recorded_wins(store, record.id, task)
