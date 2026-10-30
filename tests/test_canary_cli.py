"""Interactive canary CLI with a mocked provider and Docker boundary."""

from __future__ import annotations

import sys

import pytest
from test_harness_comparison import provider
from test_manual_cli import setup, tty
from test_probe_execution import Boundary

from arcen.harness import probe_container
from arcen.harness.cli import main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.lineage import HarnessLineage


def args(store, baseline, candidate, config, repo, commit, budget):
    return [
        "--store",
        str(store.root),
        "canary",
        "run",
        "--baseline",
        baseline,
        "--candidate",
        candidate,
        "--config",
        str(config),
        "--repo",
        str(repo),
        "--commit",
        commit,
        "--budget",
        budget.id,
    ]


def fixture(tmp_path, capsys):
    store, adopted, baseline, candidate, _, config, repo, campaign_id, _, _ = setup(
        tmp_path, capsys
    )
    from arcen.harness.campaign_journal import CampaignJournal

    commit = CampaignJournal(store).get(campaign_id).commit
    budget = DurableBudget.create(
        store, max_trials=4, max_model_calls=16, max_judge_calls=0, admission_seconds=120
    )
    return (
        store,
        adopted,
        baseline,
        candidate,
        budget,
        args(store, baseline, candidate, config, repo, commit, budget),
    )


def test_list_is_public_and_does_not_need_store(tmp_path, capsys):
    assert main(["--store", str(tmp_path / "missing"), "canary", "list"]) == 0
    out = capsys.readouterr().out
    assert "exact-number" in out and "sha256-abc" in out and "not a safety" in out
    assert not (tmp_path / "missing").exists()


def test_run_requires_tty_and_confirmation_before_git_model_or_docker(
    tmp_path, monkeypatch, capsys
):
    store, _, _, _, budget, arguments = fixture(tmp_path, capsys)
    calls = provider(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(arguments) == 1 and "interactive terminal" in capsys.readouterr().err
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    monkeypatch.setattr(
        "arcen.harness.canary.snapshot_git_commit", lambda *a: pytest.fail("unexpected git")
    )
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("unexpected Docker")
    )
    assert main(arguments) == 1 and "cancelled" in capsys.readouterr().err
    assert not calls and budget.snapshot().trials == 0
    assert not (store.root / "reviews.sqlite3").exists()


def test_run_displays_evidence_without_adopting(tmp_path, monkeypatch, capsys):
    store, adopted, _, candidate, budget, arguments = fixture(tmp_path, capsys)
    tty(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda prompt: f"CANARY {candidate}")
    assert main(arguments) == 0
    out = capsys.readouterr().out
    assert "NOT a security proof" in out and "Canary result: passed" in out
    assert "exact-number: baseline=passed; candidate=passed" in out
    assert "sha256-abc: baseline=passed; candidate=passed" in out
    assert "No refs moved" in out and len(calls) == 8
    assert budget.snapshot().trials == 4
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_invalid_commit_refused_before_confirmation(tmp_path, monkeypatch, capsys):
    _, _, _, _, budget, arguments = fixture(tmp_path, capsys)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected prompt"))
    arguments[arguments.index("--commit") + 1] = "HEAD"
    assert main(arguments) == 1 and "full lowercase" in capsys.readouterr().err
    assert budget.snapshot().trials == 0


def paired_review(store, baseline, candidate, commit, workspace):
    """Fabricated local evidence for tests only; it is not authenticated."""
    from arcen.harness.comparison import ReviewedComparison
    from arcen.harness.judge import Judgment
    from arcen.harness.probe_execution import ReviewedProbeResult
    from arcen.harness.review import ReviewLedger

    events = ({"type": "run.done", "status": "ok"},)
    reference = ReviewedProbeResult(baseline, baseline, commit, workspace, "ok", events)
    trial = ReviewedProbeResult(baseline, candidate, commit, workspace, "ok", events)
    return ReviewLedger(store, create=True).request_from_comparison(
        ReviewedComparison(reference, trial, Judgment("candidate", 0.9, "test"))
    )


def test_paired_advisory_matches_workspace_and_does_not_change_review_or_refs(
    tmp_path, monkeypatch, capsys
):
    from arcen.harness.probe_workspace import snapshot_git_commit
    from arcen.harness.review import ReviewLedger

    store, adopted, baseline, candidate, budget, arguments = fixture(tmp_path, capsys)
    repo = arguments[arguments.index("--repo") + 1]
    commit = arguments[arguments.index("--commit") + 1]
    digest = snapshot_git_commit(repo, commit).sha256
    record = paired_review(store, baseline, candidate, commit, digest)
    before = ReviewLedger(store).get(record.id)
    tty(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: f"CANARY {candidate}")
    assert main([*arguments, "--review", record.id]) == 0
    out = capsys.readouterr().out
    assert "Advisory: needs_human; basis: comparison_prefers_candidate" in out
    assert "not authenticated" in out and "No refs moved" in out and len(calls) == 8
    assert ReviewLedger(store).get(record.id) == before
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    assert budget.snapshot().trials == 4


def test_mismatched_workspace_refuses_before_any_trial(tmp_path, monkeypatch, capsys):
    store, _, baseline, candidate, budget, arguments = fixture(tmp_path, capsys)
    commit = arguments[arguments.index("--commit") + 1]
    record = paired_review(store, baseline, candidate, commit, "e" * 64)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: f"CANARY {candidate}")
    calls = provider(monkeypatch)
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("unexpected Docker")
    )
    assert main([*arguments, "--review", record.id]) == 1
    assert "workspace does not match" in capsys.readouterr().err
    assert not calls and budget.snapshot().trials == 0


def test_review_changed_during_canary_cannot_produce_advisory(tmp_path, monkeypatch, capsys):
    from arcen.harness.probe_workspace import snapshot_git_commit
    from arcen.harness.review import ReviewLedger

    store, _, baseline, candidate, _, arguments = fixture(tmp_path, capsys)
    repo = arguments[arguments.index("--repo") + 1]
    commit = arguments[arguments.index("--commit") + 1]
    record = paired_review(
        store, baseline, candidate, commit, snapshot_git_commit(repo, commit).sha256
    )
    tty(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)

    def mutate(n):
        if n == 1:
            ReviewLedger(store).resolve(record.id, "rejected", "local", saw_diff=True)

    provider(monkeypatch, hook=mutate)
    monkeypatch.setattr("builtins.input", lambda _: f"CANARY {candidate}")
    assert main([*arguments, "--review", record.id]) == 1
    output = capsys.readouterr()
    assert "review changed" in output.err and "Advisory:" not in output.out
