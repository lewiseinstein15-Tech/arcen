"""Interactive portability CLI; provider and Docker mocked in these tests."""

from __future__ import annotations

import pytest
from test_harness_comparison import provider
from test_harness_portability import IMAGES
from test_manual_cli import setup, tty
from test_probe_execution import Boundary

from arcen.harness import portability as portability_module
from arcen.harness import probe_container
from arcen.harness.campaign_journal import CampaignJournal
from arcen.harness.cli import main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.lineage import HarnessLineage


@pytest.fixture(autouse=True)
def mocked_image_preflight(monkeypatch):
    monkeypatch.setattr(portability_module, "_require_local_images", lambda _: None)


def fixture(tmp_path, capsys):
    store, adopted, baseline, candidate, task, config, repo, campaign, _, _ = setup(
        tmp_path, capsys
    )
    commit = CampaignJournal(store).get(campaign).commit
    cap = DurableBudget.create(
        store, max_trials=4, max_model_calls=8, max_judge_calls=2, admission_seconds=120
    )
    args = [
        "--store",
        str(store.root),
        "portability",
        "run",
        "--baseline",
        baseline,
        "--candidate",
        candidate,
        "--task-file",
        str(task),
        "--image-a",
        IMAGES[0],
        "--image-b",
        IMAGES[1],
        "--config",
        str(config),
        "--repo",
        str(repo),
        "--commit",
        commit,
        "--budget",
        cap.id,
    ]
    return store, adopted, candidate, cap, args


def test_interactive_two_profile_flow_never_adopts(tmp_path, monkeypatch, capsys):
    store, adopted, candidate, cap, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    answers = iter([f"PORTABILITY {candidate}", "TIE", "TIE"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Portability result: compared" in out
    assert "Profile A: tie" in out and "Profile B: tie" in out
    assert "no refs moved" in out and "no adoption authorized" in out
    assert len(calls) == 8 and cap.snapshot().trials == 4
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    assert not (store.root / "reviews.sqlite3").exists()


def test_cancellation_and_invalid_image_prevent_execution(tmp_path, monkeypatch, capsys):
    _, _, _, cap, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls = provider(monkeypatch)
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("docker")
    )
    monkeypatch.setattr("builtins.input", lambda _: "CANCEL")
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    args[args.index("--image-a") + 1] = "image:latest"
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("confirmation"))
    assert main(args) == 1 and "two distinct local Docker image IDs" in capsys.readouterr().err
    assert not calls and cap.snapshot().trials == cap.snapshot().model_calls == 0


def test_noninteractive_and_insufficient_budget_fail_before_confirmation(
    tmp_path, monkeypatch, capsys
):
    store, _, _, _, args = fixture(tmp_path, capsys)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(args) == 1 and "interactive terminal" in capsys.readouterr().err
    tty(monkeypatch)
    cap = DurableBudget.create(
        store, max_trials=2, max_model_calls=8, max_judge_calls=2, admission_seconds=120
    )
    args[args.index("--budget") + 1] = cap.id
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("confirmation"))
    assert main(args) == 1 and "at least four trial" in capsys.readouterr().err
    assert cap.snapshot().trials == cap.snapshot().model_calls == 0
