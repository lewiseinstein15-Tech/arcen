"""Separately confirmed model reflection; mocked provider, no Docker/adoption."""

from __future__ import annotations

import json
import sqlite3
import sys

import litellm
import pytest
from test_experience_cli import setup_cli
from test_manual_cli import tty
from test_probe_model import SECRET, response

from arcen.harness.cli import main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.experience_cli_store import open_cli_experience
from arcen.harness.lineage import HarnessLineage


def fixture(tmp_path):
    store, baseline, candidate, adopted, ledger, review, _ = setup_cli(tmp_path)
    config = tmp_path / "reflection.yaml"
    config.write_text(
        "provider:\n  name: custom\n  base_url: https://provider.example/v1\n"
        f"  api_key: {SECRET}\n  model: mock-model\n"
    )
    observation = tmp_path / "observation.txt"
    observation.write_text("The checks were reviewed manually.\n")
    budget = DurableBudget.create(
        store, max_trials=1, max_model_calls=2, max_judge_calls=1, admission_seconds=120
    )
    args = [
        "--store",
        str(store.root),
        "experience",
        "reflect",
        "checks",
        "--review",
        review.id,
        "--observation-file",
        str(observation),
        "--config",
        str(config),
        "--budget",
        budget.id,
    ]
    return store, baseline, candidate, adopted, ledger, review, budget, observation, args


def provider(monkeypatch, text='{"lesson":"Review checks before retrying."}'):
    calls = []

    def completion(**kw):
        calls.append(kw)
        return response(text)

    monkeypatch.setattr(litellm, "completion", completion)
    return calls


def confirm(prompt, review_id):
    if prompt.startswith("Type REFLECT "):
        return f"REFLECT {review_id}"
    if prompt.startswith("Type SAVE "):
        return f"SAVE checks {review_id}"
    pytest.fail(f"unexpected prompt {prompt}")


def test_reflection_sends_after_confirmation_and_saves_after_separate_review(
    tmp_path, monkeypatch, capsys
):
    store, _, _, adopted, ledger, review, budget, _, args = fixture(tmp_path)
    tty(monkeypatch)
    calls = provider(monkeypatch)

    def answer(prompt):
        if prompt.startswith("Type REFLECT "):
            assert not calls
        else:
            assert len(calls) == 1 and not (store.root / "experience.sqlite3").exists()
        return confirm(prompt, review.id)

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "full trajectory is not retained" in out and "independently verify" in out
    assert "No editor prompt, trial, ref or adoption changed" in out
    payload = json.loads(calls[0]["messages"][-1]["content"])
    assert payload["observation"] == "The checks were reviewed manually."
    assert set(payload) == {
        "topic",
        "observation",
        "recorded_winner",
        "recorded_confidence",
        "instructions",
    }
    assert budget.snapshot().model_calls == 1 and budget.snapshot().trials == 0
    with open_cli_experience(store, ledger) as library:
        assert (
            library.active()[0].text == "Model-drafted hypothesis: Review checks before retrying."
        )
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


@pytest.mark.parametrize("cancel_stage", ["before-provider", "before-save"])
def test_cancellation_keeps_memory_absent_and_spends_only_actual_calls(
    tmp_path, monkeypatch, capsys, cancel_stage
):
    store, _, _, _, _, review, budget, _, args = fixture(tmp_path)
    tty(monkeypatch)
    calls = provider(monkeypatch)

    def answer(prompt):
        if cancel_stage == "before-provider" or prompt.startswith("Type SAVE "):
            return "CANCEL"
        return confirm(prompt, review.id)

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    expected = 0 if cancel_stage == "before-provider" else 1
    assert len(calls) == budget.snapshot().model_calls == expected
    assert not (store.root / "experience.sqlite3").exists()


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        '{"lesson":"x","lesson":"y"}',
        '{"lesson":"x","extra":1}',
        '{"lesson":"secret sk-abcdefghijklmnop"}',
        '{"lesson":"a\\nb"}',
    ],
)
def test_invalid_or_sensitive_output_never_written(tmp_path, monkeypatch, capsys, text):
    store, _, _, _, _, review, budget, _, args = fixture(tmp_path)
    tty(monkeypatch)
    calls = provider(monkeypatch, text)
    monkeypatch.setattr("builtins.input", lambda prompt: confirm(prompt, review.id))
    assert main(args) == 1
    captured = capsys.readouterr()
    assert (
        "reflection failed" in captured.err
        and "sk-abcdefghijklmnop" not in captured.out + captured.err
    )
    assert len(calls) == budget.snapshot().model_calls == 1
    assert not (store.root / "experience.sqlite3").exists()


def test_noninteractive_and_invalid_observation_never_contact_provider(
    tmp_path, monkeypatch, capsys
):
    store, _, _, _, _, _review, budget, observation, args = fixture(tmp_path)
    calls = provider(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(args) == 1 and "interactive terminal" in capsys.readouterr().err
    tty(monkeypatch)
    observation.write_text("secret sk-abcdefghijklmnop")
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected confirmation"))
    assert main(args) == 1 and "detected secret" in capsys.readouterr().err
    assert not calls and budget.snapshot().model_calls == 0
    assert not (store.root / "experience.sqlite3").exists()


def test_changed_observation_before_provider_and_changed_review_before_save(
    tmp_path, monkeypatch, capsys
):
    store, _, _, _, ledger, review, budget, observation, args = fixture(tmp_path)
    tty(monkeypatch)
    calls = provider(monkeypatch)

    def change_observation(prompt):
        observation.write_text("Changed observation.\n")
        return confirm(prompt, review.id)

    monkeypatch.setattr("builtins.input", change_observation)
    assert main(args) == 1 and "observation changed" in capsys.readouterr().err
    assert not calls and budget.snapshot().model_calls == 0
    observation.write_text("The checks were reviewed manually.\n")

    def change_review(prompt):
        if prompt.startswith("Type SAVE "):
            with sqlite3.connect(ledger.path) as db:
                db.execute("UPDATE reviews SET note='changed' WHERE id=?", (review.id,))
        return confirm(prompt, review.id)

    monkeypatch.setattr("builtins.input", change_review)
    assert main(args) == 1 and "review changed" in capsys.readouterr().err
    assert len(calls) == budget.snapshot().model_calls == 1
    assert not (store.root / "experience.sqlite3").exists()


def test_insufficient_budget_and_symlink_observation_fail_without_provider(
    tmp_path, monkeypatch, capsys
):
    store, _, _, _, _, _review, budget, observation, args = fixture(tmp_path)
    tty(monkeypatch)
    calls = provider(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected confirmation"))
    victim = tmp_path / "victim.txt"
    victim.write_text("Private source.\n")
    observation.unlink()
    observation.symlink_to(victim)
    assert main(args) == 1 and "cannot read" in capsys.readouterr().err
    observation.unlink()
    observation.write_text("A reviewed observation.\n")
    budget.reserve_model_call()
    budget.reserve_model_call()
    assert main(args) == 1 and "insufficient available" in capsys.readouterr().err
    assert calls == [] and not (store.root / "experience.sqlite3").exists()
    assert victim.read_text() == "Private source.\n"


def test_unapproved_review_and_unknown_topic_do_not_call_provider(tmp_path, monkeypatch, capsys):
    store, baseline, candidate, _, ledger, _, budget, _, args = fixture(tmp_path)
    tty(monkeypatch)
    calls = provider(monkeypatch)
    pending = ledger.request(baseline, candidate)
    args[args.index("--review") + 1] = pending.id
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected confirmation"))
    assert main(args) == 1 and "approved paired" in capsys.readouterr().err
    args[args.index("reflect") + 1] = "../escape"
    assert main(args) == 1 and "invalid lesson topic" in capsys.readouterr().err
    assert not calls and budget.snapshot().model_calls == 0
    assert not (store.root / "experience.sqlite3").exists()
