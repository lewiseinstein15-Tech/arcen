"""Single-terminal manual workflow; provider and Docker mocked in unit tests."""

from __future__ import annotations

import difflib
import json
import sys

import pytest
from test_harness_comparison import provider
from test_probe_execution import Boundary
from test_probe_model import SECRET
from test_probe_workspace import repository

from arcen.harness import probe_container
from arcen.harness.campaign_journal import CampaignJournal
from arcen.harness.cli import _existing, _init, main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.lineage import HarnessLineage
from arcen.harness.manual_cli import _read_text
from arcen.harness.resolver import HarnessError
from arcen.harness.review import ReviewLedger


def output_id(capsys, prefix):
    text = capsys.readouterr().out
    line = next(line for line in text.splitlines() if line.startswith(prefix))
    return line[len(prefix) :].split()[0]


def setup(tmp_path, capsys):
    root = tmp_path / "store"
    adopted = _init(str(root))
    assert main(["--store", str(root), "pin-baseline", "fixed:custom:mock-model"]) == 0
    baseline = output_id(capsys, "Unadopted pinned baseline: ")
    store, _ = _existing(str(root))
    manifest = store.get_manifest(baseline)
    path = "prompts/draft.md"
    original = store.get_blob(manifest.components[path]).decode()
    edited = original + "\nCheck the objective.\n"
    patch = "".join(
        difflib.unified_diff(
            original.splitlines(True),
            edited.splitlines(True),
            fromfile="a/" + path,
            tofile="b/" + path,
        )
    )
    patch_file = tmp_path / "candidate.patch"
    patch_file.write_text(patch)
    assert main(["--store", str(root), "import-patch", baseline, path, str(patch_file)]) == 0
    candidate = output_id(capsys, "Unadopted candidate: ")
    task_file = tmp_path / "task.txt"
    task_file.write_text("inspect project")
    repo, commit = repository(tmp_path)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"provider:\n  name: custom\n  base_url: https://provider.example/v1\n  api_key: {SECRET}\n  model: mock-model\n"
    )
    assert (
        main(
            [
                "--store",
                str(root),
                "budget",
                "create",
                "--trials",
                "2",
                "--model-calls",
                "4",
                "--judge-calls",
                "1",
                "--seconds",
                "120",
            ]
        )
        == 0
    )
    budget_id = output_id(capsys, "Budget: ")
    assert (
        main(
            [
                "--store",
                str(root),
                "campaign",
                "plan",
                "--baseline",
                baseline,
                "--candidate",
                candidate,
                "--task-file",
                str(task_file),
                "--commit",
                commit,
            ]
        )
        == 0
    )
    campaign_id = output_id(capsys, "Campaign plan: ")
    run_args = [
        "--store",
        str(root),
        "campaign",
        "run",
        campaign_id,
        "--task-file",
        str(task_file),
        "--config",
        str(config_file),
        "--repo",
        str(repo),
        "--budget",
        budget_id,
    ]
    return (
        store,
        adopted,
        baseline,
        candidate,
        task_file,
        config_file,
        repo,
        campaign_id,
        budget_id,
        run_args,
    )


def tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)


def test_manual_cli_complete_flow_with_explicit_confirmation_and_human_judge(
    tmp_path, monkeypatch, capsys
):
    store, adopted, baseline, candidate, _, _, _, campaign_id, budget_id, run_args = setup(
        tmp_path, capsys
    )
    tty(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    answers = iter([f"RUN {campaign_id}", "TIE"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(run_args) == 0
    text = capsys.readouterr().out
    assert "sanitized diff" in text and "Blinded evidence" in text and "Pending review:" in text
    assert "No adoption occurred" in text and SECRET not in text
    assert len(calls) == 4 and all(bound.closed for bound in Boundary.instances[-2:])
    assert CampaignJournal(store).get(campaign_id).state == "completed"
    assert DurableBudget(store, budget_id).snapshot().model_calls == 4
    reviews = ReviewLedger(store).list()
    assert (
        len(reviews) == 1 and reviews[0].state == "pending" and reviews[0].candidate_id == candidate
    )
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    assert baseline != adopted


def test_cancel_before_run_has_no_model_git_or_review_side_effect(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, _, _, campaign_id, budget_id, run_args = setup(tmp_path, capsys)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    monkeypatch.setattr(
        "arcen.harness.manual_campaign.snapshot_git_commit", lambda *_: pytest.fail("git called")
    )
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("docker called")
    )
    assert main(run_args) == 1
    assert "cancelled" in capsys.readouterr().err
    assert CampaignJournal(store).get(campaign_id).state == "ready"
    assert DurableBudget(store, budget_id).snapshot().model_calls == 0
    assert not (store.root / "reviews.sqlite3").exists()


def test_noninteractive_run_refused_before_read_or_execution(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, _, _, campaign_id, budget_id, run_args = setup(tmp_path, capsys)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(run_args) == 1
    assert "interactive terminal" in capsys.readouterr().err
    assert CampaignJournal(store).get(campaign_id).state == "ready"
    assert DurableBudget(store, budget_id).snapshot().trials == 0


def test_task_change_and_bad_config_refused_before_confirmation(tmp_path, monkeypatch, capsys):
    store, _, _, _, task, config, _, campaign_id, budget_id, run_args = setup(tmp_path, capsys)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected prompt"))
    task.write_text("changed task")
    assert main(run_args) == 1 and "does not match" in capsys.readouterr().err
    task.write_text("inspect project")
    config.write_text("- not a config mapping")
    assert main(run_args) == 1 and "invalid campaign configuration" in capsys.readouterr().err
    assert CampaignJournal(store).get(campaign_id).state == "ready"
    assert DurableBudget(store, budget_id).snapshot().trials == 0


def test_judge_cancel_stops_without_review_or_adoption(tmp_path, monkeypatch, capsys):
    store, adopted, _, _, _, _, _, campaign_id, _, run_args = setup(tmp_path, capsys)
    tty(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch)
    answers = iter([f"RUN {campaign_id}", "CANCEL"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(run_args) == 1
    assert "judge_failed" in capsys.readouterr().out
    assert CampaignJournal(store).get(campaign_id).state == "failed"
    assert ReviewLedger(store).list() == ()
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_patch_and_files_are_bounded_and_symlinks_rejected(tmp_path, capsys):
    root = tmp_path / "store"
    _init(str(root))
    assert main(["--store", str(root), "pin-baseline", "provider-configured"]) == 1
    assert "fixed" in capsys.readouterr().err
    f = tmp_path / "plain"
    f.write_text("hello")
    link = tmp_path / "link"
    link.symlink_to(f)
    with pytest.raises(HarnessError):
        _read_text(str(link), 50)
    with pytest.raises(HarnessError):
        _read_text(str(f), 2)
    assert f.read_text() == "hello"


def test_budget_and_plan_invalid_without_provider_calls(tmp_path, capsys):
    root = tmp_path / "store"
    _init(str(root))
    assert (
        main(
            [
                "--store",
                str(root),
                "budget",
                "create",
                "--trials",
                "0",
                "--model-calls",
                "4",
                "--judge-calls",
                "1",
                "--seconds",
                "10",
            ]
        )
        == 1
    )
    assert "invalid" in capsys.readouterr().err
    assert not (root / "budgets.sqlite3").exists()


def test_human_judge_never_receives_candidate_or_secret_identifier(tmp_path, monkeypatch, capsys):
    _, _, baseline, candidate, _, _, _, campaign_id, _, run_args = setup(tmp_path, capsys)
    tty(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch)
    seen = []

    def answer(prompt):
        if prompt.startswith("Type RUN"):
            return f"RUN {campaign_id}"
        output = capsys.readouterr().out
        seen.append(
            output.split("Blinded evidence (untrusted; may contain sensitive data):\n", 1)[1]
        )
        return "A"

    monkeypatch.setattr("builtins.input", answer)
    assert main(run_args) == 0
    request = json.loads(seen[0])
    encoded = json.dumps(request)
    assert baseline not in encoded and candidate not in encoded and SECRET not in encoded


def test_unavailable_docker_fails_closed_before_provider(tmp_path, monkeypatch, capsys):
    from arcen.sandbox.turn import IsolationUnavailable

    store, adopted, _, _, _, _, _, campaign_id, budget_id, run_args = setup(tmp_path, capsys)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: f"RUN {campaign_id}")

    def unavailable(*args, **kwargs):
        raise IsolationUnavailable("private daemon error")

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", unavailable)
    calls = provider(monkeypatch)
    assert main(run_args) == 1
    out = capsys.readouterr()
    assert "reference_isolation_failed" in out.out
    assert "private daemon error" not in out.out + out.err
    assert calls == []
    assert CampaignJournal(store).get(campaign_id).state == "failed"
    assert DurableBudget(store, budget_id).snapshot().model_calls == 0
    assert ReviewLedger(store).list() == ()
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_replay_refused_without_additional_model_calls(tmp_path, monkeypatch, capsys):
    _, _, _, _, _, _, _, campaign_id, _, run_args = setup(tmp_path, capsys)
    tty(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    answers = iter([f"RUN {campaign_id}", "B"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(run_args) == 0
    assert len(calls) == 4
    capsys.readouterr()
    assert main(run_args) == 1
    assert "automatic resume is unavailable" in capsys.readouterr().err
    assert len(calls) == 4


def test_stopped_budget_and_interrupt_refuse_start(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, _, _, campaign_id, budget_id, run_args = setup(tmp_path, capsys)
    tty(monkeypatch)

    def interrupted(_):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupted)
    assert main(run_args) == 1 and "cancelled" in capsys.readouterr().err
    assert CampaignJournal(store).get(campaign_id).state == "ready"
    DurableBudget(store, budget_id).stop()
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("confirmation after stop"))
    assert main(run_args) == 1 and "budget closed" in capsys.readouterr().err
    assert CampaignJournal(store).get(campaign_id).state == "ready"


def test_modified_baseline_rejected_before_prompt(tmp_path, monkeypatch, capsys):
    store, _, baseline, candidate, task, _, _, _, budget_id, run_args = setup(tmp_path, capsys)
    from arcen.harness.manual_cli import import_patch

    base = store.get_manifest(candidate)
    component = "prompts/draft.md"
    original = store.get_blob(base.components[component]).decode()
    patch_file = tmp_path / "second.patch"
    patch_file.write_text(
        "".join(
            difflib.unified_diff(
                original.splitlines(True),
                (original + "another line\n").splitlines(True),
                fromfile="a/" + component,
                tofile="b/" + component,
            )
        )
    )
    second = import_patch(store, candidate, component, str(patch_file))
    journal = CampaignJournal(store)
    commit = journal.get(run_args[4]).commit
    new_plan = journal.plan(candidate, (second,), task.read_text(), commit)
    run_args[4] = new_plan.id
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected prompt"))
    assert main(run_args) == 1
    assert "unchanged packaged baseline" in capsys.readouterr().err
    assert DurableBudget(store, budget_id).snapshot().trials == 0
    assert baseline != candidate


def test_real_docker_manual_cli_when_explicitly_enabled(tmp_path, monkeypatch, capsys):
    import os

    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires real Docker and sandbox image")
    pytest.importorskip("docker")
    store, adopted, _, _, _, _, _, campaign_id, budget_id, run_args = setup(tmp_path, capsys)
    tty(monkeypatch)
    calls = provider(monkeypatch)
    answers = iter([f"RUN {campaign_id}", "TIE"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(run_args) == 0
    assert len(calls) == 4
    assert CampaignJournal(store).get(campaign_id).state == "completed"
    assert DurableBudget(store, budget_id).snapshot().model_calls == 4
    assert len(ReviewLedger(store).list()) == 1
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
