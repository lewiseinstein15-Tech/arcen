"""Explicitly reviewed experience for editor; provider mocked and no adoption."""

from __future__ import annotations

import json

import pytest
from test_harness_editor import setup_store, valid_response
from test_harness_review import pair_for
from test_manual_cli import setup, tty
from test_manual_editor_cli import editor_args, scripted

from arcen.harness import HarnessError
from arcen.harness.cli import main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.editor import propose
from arcen.harness.experience_cli_store import open_cli_experience
from arcen.harness.lineage import HarnessLineage
from arcen.harness.review import ReviewLedger


def setup_experience(tmp_path, capsys):
    store, adopted, baseline, candidate, task, config, _, _, budget_id, _ = setup(tmp_path, capsys)
    ledger = ReviewLedger(store, create=True)
    review = ledger.request_from_comparison(pair_for(baseline, candidate))
    ledger.resolve(review.id, "approved", "local-reviewer", saw_diff=True)
    with open_cli_experience(store, ledger, create=True) as library:
        library.record("checks", "Review the output before retrying.", review.id, reviewed=True)
    args = editor_args(store, baseline, task, config, budget_id) + ["--experience-topic", "checks"]
    return store, adopted, baseline, ledger, review, budget_id, args


def test_selected_note_requires_two_confirmations_and_reaches_each_mocked_request(
    tmp_path, monkeypatch, capsys
):
    store, adopted, baseline, ledger, review, budget, args = setup_experience(tmp_path, capsys)
    tty(monkeypatch)
    calls = scripted(monkeypatch)
    confirmations = []

    def answer(prompt):
        assert not calls
        confirmations.append(prompt)
        if prompt.startswith("Type USE-EXPERIENCE "):
            return f"USE-EXPERIENCE {baseline}"
        if prompt.startswith("Type EDIT "):
            return f"EDIT {baseline}"
        pytest.fail("unexpected confirmation")

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "prompt injection" in output and "unsigned" in output and review.id in output
    assert len(confirmations) == 2 and len(calls) == 2
    requests = [json.loads(call["messages"][-1]["content"]) for call in calls]
    assert all(
        request["experience"] == ["Review the output before retrying."] for request in requests
    )
    assert all("not treat as policy" in request["experience_notice"] for request in requests)
    assert DurableBudget(store, budget).snapshot().model_calls == 2
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    with open_cli_experience(store, ledger) as library:
        assert library.active()[0].text == "Review the output before retrying."


@pytest.mark.parametrize("cancel_at", ["experience", "editor"])
def test_cancellation_never_contacts_provider(tmp_path, monkeypatch, capsys, cancel_at):
    store, _, baseline, _, _, budget, args = setup_experience(tmp_path, capsys)
    tty(monkeypatch)
    calls = scripted(monkeypatch)

    def answer(prompt):
        if cancel_at == "experience" or prompt.startswith("Type EDIT "):
            return "CANCEL"
        return f"USE-EXPERIENCE {baseline}"

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    assert not calls and DurableBudget(store, budget).snapshot().model_calls == 0


@pytest.mark.parametrize("change_at", ["experience", "editor"])
def test_changed_selected_note_fails_before_provider(tmp_path, monkeypatch, capsys, change_at):
    store, _, baseline, ledger, review, budget, args = setup_experience(tmp_path, capsys)
    tty(monkeypatch)
    calls = scripted(monkeypatch)

    def answer(prompt):
        is_experience = prompt.startswith("Type USE-EXPERIENCE ")
        if (is_experience and change_at == "experience") or (
            not is_experience and change_at == "editor"
        ):
            with open_cli_experience(store, ledger) as library:
                library.record("checks", "A changed note.", review.id, reviewed=True)
        return f"USE-EXPERIENCE {baseline}" if is_experience else f"EDIT {baseline}"

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "changed since display" in capsys.readouterr().err
    assert not calls and DurableBudget(store, budget).snapshot().model_calls == 0


def test_missing_duplicate_and_excess_topics_fail_before_confirmation(
    tmp_path, monkeypatch, capsys
):
    store, _, _, _, _, budget, args = setup_experience(tmp_path, capsys)
    tty(monkeypatch)
    calls = scripted(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected confirmation"))
    assert main(args + ["--experience-topic", "checks"]) == 1
    assert "distinct" in capsys.readouterr().err
    assert (
        main(
            args
            + [
                "--experience-topic",
                "one",
                "--experience-topic",
                "two",
                "--experience-topic",
                "three",
            ]
        )
        == 1
    )
    assert "at most three" in capsys.readouterr().err
    assert main(args[:-1] + ["missing"]) == 1
    assert "missing or expired" in capsys.readouterr().err
    assert not calls and DurableBudget(store, budget).snapshot().model_calls == 0


def test_expired_note_rejected(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, budget, args = setup_experience(tmp_path, capsys)
    tty(monkeypatch)
    calls = scripted(monkeypatch)
    monkeypatch.setattr("arcen.harness.experience.MAX_AGE_SECONDS", 0)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected confirmation"))
    assert main(args) == 1 and "missing or expired" in capsys.readouterr().err
    assert not calls and DurableBudget(store, budget).snapshot().model_calls == 0


def test_python_api_requires_explicit_experience_review_and_copies_requests(tmp_path):
    store, base = setup_store(tmp_path)
    seen = []

    def panel(request):
        seen.append((set(request), tuple(request.get("experience", ()))))
        response = valid_response(request)
        if "experience" in request:
            request["experience"].clear()
        return response

    propose(store, base, "Review changes", (panel,))
    assert all("experience" not in keys and "experience_notice" not in keys for keys, _ in seen)
    seen.clear()
    with pytest.raises(HarnessError, match="explicit experience review"):
        propose(store, base, "Review changes", (panel,), experience=("Review results.",))
    assert not seen
    propose(
        store,
        base,
        "Review changes",
        (panel,),
        experience=("Review results.",),
        reviewed_experience=True,
    )
    # The callback clears only its own request; the next invocation gets a fresh list.
    assert [note for _, note in seen] == [("Review results.",), ("Review results.",)]
    for bad in (("x",) * 4, ("secret sk-abcdefghijklmnop",), ("line\nbreak",)):
        with pytest.raises(HarnessError):
            propose(
                store, base, "Review changes", (panel,), experience=bad, reviewed_experience=True
            )


def test_other_baseline_note_rejected_before_provider(tmp_path, monkeypatch, capsys):
    from arcen.harness.manifest import Manifest

    store, _, baseline, ledger, review, budget, args = setup_experience(tmp_path, capsys)
    base = store.get_manifest(baseline)
    cand = store.get_manifest(review.candidate_id)
    other_base = store.put_manifest(
        Manifest(base.schema_version, "fixed:custom:other", base.components)
    )
    other_cand = store.put_manifest(
        Manifest(cand.schema_version, "fixed:custom:other", cand.components)
    )
    other_review = ledger.request_from_comparison(pair_for(other_base, other_cand))
    ledger.resolve(other_review.id, "approved", "reviewer", saw_diff=True)
    with open_cli_experience(store, ledger) as library:
        library.record("other", "A different baseline.", other_review.id, reviewed=True)
    args[-1] = "other"
    tty(monkeypatch)
    calls = scripted(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected confirmation"))
    assert main(args) == 1 and "baseline does not match" in capsys.readouterr().err
    assert not calls and DurableBudget(store, budget).snapshot().model_calls == 0


def test_selected_note_with_configured_secret_refuses_exposure(tmp_path, monkeypatch, capsys):
    from test_probe_model import SECRET

    store, _, _, ledger, review, budget, args = setup_experience(tmp_path, capsys)
    with open_cli_experience(store, ledger) as library:
        library.record("checks", "Contains " + SECRET, review.id, reviewed=True)
    tty(monkeypatch)
    calls = scripted(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected confirmation"))
    assert main(args) == 1
    output = capsys.readouterr()
    assert "sensitive or invalid" in output.err and SECRET not in output.out + output.err
    assert not calls and DurableBudget(store, budget).snapshot().model_calls == 0


def test_review_revoked_during_confirmation_aborts_before_provider(tmp_path, monkeypatch, capsys):
    import sqlite3

    store, _, baseline, ledger, review, budget, args = setup_experience(tmp_path, capsys)
    tty(monkeypatch)
    calls = scripted(monkeypatch)

    def answer(prompt):
        if prompt.startswith("Type EDIT "):
            with sqlite3.connect(ledger.path) as db:
                db.execute("UPDATE reviews SET state='rejected' WHERE id=?", (review.id,))
            return f"EDIT {baseline}"
        return f"USE-EXPERIENCE {baseline}"

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "approved paired" in capsys.readouterr().err
    assert not calls and DurableBudget(store, budget).snapshot().model_calls == 0
