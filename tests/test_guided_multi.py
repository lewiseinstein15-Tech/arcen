"""Guided multi-candidate comparisons remain explicitly human-gated."""

from __future__ import annotations

import difflib
import json

import litellm
import pytest
from test_guided_workflow import db_count, fixture, providers
from test_manual_cli import tty
from test_probe_execution import Boundary
from test_probe_model import response

from arcen.harness import probe_container
from arcen.harness.campaign_journal import CampaignJournal
from arcen.harness.cli import main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.lineage import HarnessLineage
from arcen.harness.review import ReviewLedger


def candidates_from(out):
    ids = [
        line.split()[3]
        for line in out.splitlines()
        if line.startswith("Unadopted ") and "candidate:" in line
    ]
    assert len(ids) == 2 and len(set(ids)) == 2
    return ids


def new_budget(store, args, *, trials=3, model=8, judges=2):
    budget = DurableBudget.create(
        store,
        max_trials=trials,
        max_model_calls=model,
        max_judge_calls=judges,
        admission_seconds=120,
    )
    args[args.index("--budget") + 1] = budget.id
    return budget


def test_two_candidates_are_both_reviewed_against_one_baseline(tmp_path, monkeypatch, capsys):
    store, adopted, baseline, task_id, _, args = fixture(tmp_path, capsys)
    budget = new_budget(store, args)
    tty(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    editor, trials = providers(monkeypatch)
    seen = {"judges": 0}

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            assert not editor and not trials
            return f"EDIT {baseline}"
        if prompt.startswith("Type SELECT"):
            seen["candidates"] = candidates_from(capsys.readouterr().out)
            assert len(editor) == 2 and not trials
            return "SELECT " + " ".join(seen["candidates"])
        if prompt.startswith("Type RUN"):
            seen["campaign"] = prompt.split()[2]
            assert not trials
            return "RUN " + seen["campaign"]
        if prompt.startswith("Choose A"):
            seen["judges"] += 1
            return "TIE"
        pytest.fail("unexpected prompt " + prompt)

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 0
    output = capsys.readouterr().out
    assert output.count("Pending review:") == 2 and "No adoption occurred" in output
    assert "No winner is selected for adoption" in output
    record = CampaignJournal(store).get(seen["campaign"])
    assert record.state == "completed" and record.candidates == tuple(seen["candidates"])
    assert record.task_sha256 == task_id and record.budget_id == budget.id
    assert len(record.reviews) == 2 and len(ReviewLedger(store).list()) == 2
    assert len(trials) == 6 and len(editor) == 2 and seen["judges"] == 2
    assert (
        budget.snapshot().trials,
        budget.snapshot().model_calls,
        budget.snapshot().judge_calls,
    ) == (3, 8, 2)
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


@pytest.mark.parametrize("trials,model,judges", [(2, 8, 2), (3, 8, 1), (3, 4, 2)])
def test_selection_rechecks_remaining_budget_without_plan(
    tmp_path, monkeypatch, capsys, trials, model, judges
):
    store, _, baseline, _, _, args = fixture(tmp_path, capsys)
    budget = new_budget(store, args, trials=trials, model=model, judges=judges)
    tty(monkeypatch)
    editor, trial_calls = providers(monkeypatch)

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        if prompt.startswith("Type SELECT"):
            return "SELECT " + " ".join(candidates_from(capsys.readouterr().out))
        pytest.fail("no plan should be created")

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "insufficient remaining admissions" in capsys.readouterr().err
    assert len(editor) == 2 and not trial_calls and db_count(store) == 1
    assert budget.snapshot().trials == budget.snapshot().judge_calls == 0


@pytest.mark.parametrize("choice", ["duplicate", "unknown", "empty"])
def test_invalid_multi_selection_creates_no_plan(tmp_path, monkeypatch, capsys, choice):
    store, _, baseline, _, _, args = fixture(tmp_path, capsys)
    budget = new_budget(store, args)
    tty(monkeypatch)
    editor, trials = providers(monkeypatch)

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        ids = candidates_from(capsys.readouterr().out)
        return {
            "duplicate": f"SELECT {ids[0]} {ids[0]}",
            "unknown": f"SELECT {ids[0]} {'0' * 64}",
            "empty": "SELECT",
        }[choice]

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    assert len(editor) == 2 and not trials and db_count(store) == 1
    assert budget.snapshot().trials == 0


def test_cancelling_run_leaves_multi_candidate_plan_ready(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, _, args = fixture(tmp_path, capsys)
    budget = new_budget(store, args)
    tty(monkeypatch)
    editor, trials = providers(monkeypatch)
    seen = {}

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        if prompt.startswith("Type SELECT"):
            seen["candidates"] = candidates_from(capsys.readouterr().out)
            return "SELECT " + " ".join(seen["candidates"])
        if prompt.startswith("Type RUN"):
            seen["campaign"] = prompt.split()[2]
            return "CANCEL"
        pytest.fail("unexpected prompt")

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    record = CampaignJournal(store).get(seen["campaign"])
    assert record.state == "ready" and record.candidates == tuple(seen["candidates"])
    assert len(editor) == 2 and not trials and budget.snapshot().trials == 0
    assert not (store.root / "reviews.sqlite3").exists()


def test_maximum_five_selected_candidates_even_if_editor_generated_more(
    tmp_path, monkeypatch, capsys
):
    store, _, baseline, _, _, args = fixture(tmp_path, capsys)
    budget = new_budget(store, args, trials=6, model=16, judges=5)
    args.extend(["--k", "4"])
    tty(monkeypatch)
    calls = []

    def completion(**kwargs):
        req = json.loads(kwargs["messages"][-1]["content"])
        path = "prompts/draft.md"
        old = req["components"][path]
        edited = old + "\nIndividual " + req["scope"] + " " + str(req["index"]) + ".\n"
        patch = "".join(
            difflib.unified_diff(
                old.splitlines(True),
                edited.splitlines(True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
        calls.append(kwargs)
        return response(json.dumps({"path": path, "diff": patch}))

    monkeypatch.setattr(litellm, "completion", completion)

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        out = capsys.readouterr().out
        ids = [
            line.split()[3]
            for line in out.splitlines()
            if line.startswith("Unadopted ") and "candidate:" in line
        ]
        assert len(ids) == len(set(ids)) == 8
        return "SELECT " + " ".join(ids[:6])

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    assert len(calls) == 8 and db_count(store) == 1 and budget.snapshot().trials == 0


def test_five_generated_candidates_can_form_one_confirmed_plan(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, _, args = fixture(tmp_path, capsys)
    budget = new_budget(store, args, trials=6, model=16, judges=5)
    args.extend(["--k", "4"])
    tty(monkeypatch)
    calls = []

    def completion(**kwargs):
        req = json.loads(kwargs["messages"][-1]["content"])
        path = "prompts/draft.md"
        old = req["components"][path]
        edited = old + "\nUnique " + req["scope"] + " " + str(req["index"]) + ".\n"
        patch = "".join(
            difflib.unified_diff(
                old.splitlines(True),
                edited.splitlines(True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
        calls.append(kwargs)
        return response(json.dumps({"path": path, "diff": patch}))

    monkeypatch.setattr(litellm, "completion", completion)
    seen = {}

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        if prompt.startswith("Type SELECT"):
            output = capsys.readouterr().out
            ids = [
                line.split()[3]
                for line in output.splitlines()
                if line.startswith("Unadopted ") and "candidate:" in line
            ]
            seen["selected"] = tuple(ids[:5])
            return "SELECT " + " ".join(seen["selected"])
        if prompt.startswith("Type RUN"):
            seen["campaign"] = prompt.split()[2]
            return "CANCEL"
        pytest.fail("unexpected prompt")

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    record = CampaignJournal(store).get(seen["campaign"])
    assert record.state == "ready" and record.candidates == seen["selected"]
    assert len(record.candidates) == 5 and len(calls) == 8 and budget.snapshot().trials == 0
