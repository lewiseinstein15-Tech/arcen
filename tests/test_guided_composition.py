"""Guided composition is syntactic, explicitly confirmed, and never adopts."""

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
from arcen.harness.lineage import HarnessLineage
from arcen.harness.review import ReviewLedger


def diverse_provider(monkeypatch):
    editor_calls = []
    trial_calls = []

    def complete(**kwargs):
        if len(editor_calls) < 2:
            editor_calls.append(kwargs)
            req = json.loads(kwargs["messages"][-1]["content"])
            path = "prompts/forge.md" if req["scope"] == "invariant" else "prompts/temper.md"
            old = req["components"][path]
            edited = old + "\nReview " + req["scope"] + " details.\n"
            patch = "".join(
                difflib.unified_diff(
                    old.splitlines(True),
                    edited.splitlines(True),
                    fromfile="a/" + path,
                    tofile="b/" + path,
                )
            )
            return response(json.dumps({"path": path, "diff": patch}))
        trial_calls.append(kwargs)
        text = (
            "CODE"
            if len(trial_calls) % 2
            else json.dumps([{"title": "check", "tool": "bash", "args": {"cmd": "true"}}])
        )
        return response(text)

    monkeypatch.setattr(litellm, "completion", complete)
    return editor_calls, trial_calls


def ids_from_output(out):
    result = [
        line.split()[3]
        for line in out.splitlines()
        if line.startswith("Unadopted ") and "candidate:" in line
    ]
    assert len(result) == 2 and result[0] != result[1]
    return result


def test_composed_candidate_is_explicitly_confirmed_then_compared(tmp_path, monkeypatch, capsys):
    store, adopted, baseline, task_id, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    editor_calls, trial_calls = diverse_provider(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    seen = {}

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            assert not editor_calls
            return f"EDIT {baseline}"
        if prompt.startswith("Type SELECT"):
            seen["inputs"] = ids_from_output(capsys.readouterr().out)
            assert len(editor_calls) == 2 and not trial_calls
            return "COMPOSE " + " ".join(seen["inputs"])
        if prompt.startswith("Type USE"):
            seen["composite"] = prompt.split()[2]
            out = capsys.readouterr().out
            assert (
                "Composite diff" in out
                and "Review invariant details." in out
                and "Review domain details." in out
            )
            assert seen["composite"] not in seen["inputs"] and not trial_calls
            return "USE " + seen["composite"]
        if prompt.startswith("Type RUN"):
            seen["campaign"] = prompt.split()[2]
            assert not trial_calls
            return "RUN " + seen["campaign"]
        if prompt.startswith("Choose A"):
            return "TIE"
        pytest.fail("unexpected prompt: " + prompt)

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "No adoption occurred" in out
    record = CampaignJournal(store).get(seen["campaign"])
    assert (
        record.candidates == (seen["composite"],)
        and record.task_sha256 == task_id
        and record.state == "completed"
    )
    composite = store.get_manifest(seen["composite"])
    base = store.get_manifest(baseline)
    assert composite.components["prompts/forge.md"] != base.components["prompts/forge.md"]
    assert composite.components["prompts/temper.md"] != base.components["prompts/temper.md"]
    assert len(ReviewLedger(store).list()) == 1
    assert len(trial_calls) == 4 and budget.snapshot().model_calls == 6
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_conflicting_candidates_never_create_composite_plan_or_trial(tmp_path, monkeypatch, capsys):
    store, adopted, baseline, _, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = providers(monkeypatch)  # Two competing insertions at same position.
    before = {}

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        if prompt.startswith("Type SELECT"):
            ids = ids_from_output(capsys.readouterr().out)
            before["objects"] = set(store.objects.iterdir())
            return "COMPOSE " + " ".join(ids)
        pytest.fail("unexpected confirmation")

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1
    output = capsys.readouterr()
    assert (
        "Conflict: prompts/draft.md" in output.out
        and "no composite candidate or plan created" in output.err
    )
    assert set(store.objects.iterdir()) == before["objects"] and db_count(store) == 1
    assert len(calls) == 2 and not trials and budget.snapshot().trials == 0
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


@pytest.mark.parametrize("choice", ["duplicate", "unknown", "one", "too-long"])
def test_invalid_composition_selection_fails_without_new_writes(
    tmp_path, monkeypatch, capsys, choice
):
    store, _, baseline, _, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = diverse_provider(monkeypatch)
    before = {}

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        ids = ids_from_output(capsys.readouterr().out)
        before["objects"] = set(store.objects.iterdir())
        return {
            "duplicate": f"COMPOSE {ids[0]} {ids[0]}",
            "unknown": f"COMPOSE {ids[0]} {'0' * 64}",
            "one": f"COMPOSE {ids[0]}",
            "too-long": "X" * 1100,
        }[choice]

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    assert set(store.objects.iterdir()) == before["objects"] and db_count(store) == 1
    assert len(calls) == 2 and not trials and budget.snapshot().trials == 0


def test_declined_composite_remains_unadopted_without_plan(tmp_path, monkeypatch, capsys):
    store, adopted, baseline, _, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = diverse_provider(monkeypatch)
    seen = {}

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        if prompt.startswith("Type SELECT"):
            return "COMPOSE " + " ".join(ids_from_output(capsys.readouterr().out))
        if prompt.startswith("Type USE"):
            seen["composite"] = prompt.split()[2]
            return "CANCEL"
        pytest.fail("unexpected prompt")

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    assert store.get_manifest(seen["composite"]) and db_count(store) == 1
    assert len(calls) == 2 and not trials and budget.snapshot().trials == 0
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_corrupt_input_is_rechecked_before_composition(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = diverse_provider(monkeypatch)

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        ids = ids_from_output(capsys.readouterr().out)
        (store.objects / ids[0]).write_bytes(b"bad")
        return "COMPOSE " + " ".join(ids)

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "integrity" in capsys.readouterr().err
    assert len(calls) == 2 and not trials and db_count(store) == 1 and budget.snapshot().trials == 0


def test_stop_before_composition_prevents_new_objects(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = diverse_provider(monkeypatch)
    before = {}

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        ids = ids_from_output(capsys.readouterr().out)
        before["objects"] = set(store.objects.iterdir())
        budget.stop()
        return "COMPOSE " + " ".join(ids)

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and capsys.readouterr().err
    assert set(store.objects.iterdir()) == before["objects"] and db_count(store) == 1
    assert len(calls) == 2 and not trials and budget.snapshot().trials == 0


def test_three_way_manual_composition_is_supported(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    args.extend(["--k", "2"])
    calls = []
    paths = ["prompts/system.md", "prompts/draft.md", "prompts/forge.md", "prompts/temper.md"]

    def four(**kwargs):
        req = json.loads(kwargs["messages"][-1]["content"])
        path = paths[len(calls)]
        calls.append(kwargs)
        old = req["components"][path]
        patch = "".join(
            difflib.unified_diff(
                old.splitlines(True),
                (old + "\nIndependent edit.\n").splitlines(True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
        return response(json.dumps({"path": path, "diff": patch}))

    monkeypatch.setattr(litellm, "completion", four)
    seen = {}

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        if prompt.startswith("Type SELECT"):
            out = capsys.readouterr().out
            ids = [
                line.split()[3]
                for line in out.splitlines()
                if line.startswith("Unadopted ") and "candidate:" in line
            ]
            assert len(ids) == 4
            return "COMPOSE " + " ".join(ids[:3])
        if prompt.startswith("Type USE"):
            seen["composite"] = prompt.split()[2]
            return "CANCEL"
        pytest.fail("unexpected prompt")

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    combined = store.get_manifest(seen["composite"])
    base = store.get_manifest(baseline)
    assert all(combined.components[p] != base.components[p] for p in paths[:3])
    assert combined.components[paths[3]] == base.components[paths[3]]
    assert len(calls) == 4 and db_count(store) == 1 and budget.snapshot().trials == 0
