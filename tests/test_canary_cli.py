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
