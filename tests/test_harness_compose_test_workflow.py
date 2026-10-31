"""Manual composite-to-test continuation; Docker and provider mocked."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_evidence_composition import completed
from test_harness_conflict_cli import fixture as conflict_fixture
from test_manual_cli import tty
from test_probe_model import SECRET

from arcen.harness import manual_campaign
from arcen.harness.cli import main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.lineage import HarnessLineage


def _test_options(tmp_path, data, *, trials=2, model_calls=4, judge_calls=1):
    store, _, _, _, _, _, _, _, _ = data
    budget = DurableBudget.create(
        store,
        max_trials=trials,
        max_model_calls=model_calls,
        max_judge_calls=judge_calls,
        admission_seconds=120,
    )
    config = tmp_path / "test-config.yaml"
    config.write_text(
        "provider:\n  name: custom\n  base_url: https://provider.example/v1\n"
        f"  api_key: {SECRET}\n  model: mock-model\n"
    )
    options = [
        "--test-budget",
        budget.id,
        "--test-config",
        str(config),
        "--test-repo",
        str(tmp_path / "repo"),
    ]
    return budget, options


def answer(prompt):
    if prompt.startswith(("Type COMPOSE ", "Type PLAN ")):
        return prompt.removeprefix("Type ").split(" to ", 1)[0]
    if prompt.startswith("Type RUN "):
        return prompt.removeprefix("Type ").split(" to ", 1)[0]
    if prompt.startswith("Choose A, B"):
        return "TIE"
    pytest.fail(f"unexpected prompt: {prompt}")


def test_compose_then_separately_confirm_test_on_recorded_snapshot(tmp_path, monkeypatch, capsys):
    data = completed(tmp_path, monkeypatch)
    store, adopted, baseline, _, journal, ledger, record, calls, cli = data
    budget, options = _test_options(tmp_path, data)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", answer)
    assert main([*cli, *options]) == 0
    out = capsys.readouterr().out
    assert "No plan, trial, approval or adoption occurred" in out
    assert "not stored in the plan" in out and "Required workspace SHA-256" in out
    assert "Campaign completed" in out and "No adoption occurred" in out
    plan_id = next(
        line.split()[4].rstrip(";")
        for line in out.splitlines()
        if line.startswith("Created composite test plan:")
    )
    plan = journal.get(plan_id)
    assert plan.state == "completed" and len(plan.candidates) == len(plan.reviews) == 1
    assert ledger.get(plan.reviews[0]).state == "pending"
    assert (
        plan.baseline == baseline and plan.commit == record.commit and plan.budget_id == budget.id
    )
    assert len(calls) == 10
    usage = budget.snapshot()
    assert (usage.trials, usage.model_calls, usage.judge_calls) == (2, 4, 1)
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_changed_workspace_stops_before_probe_or_model(tmp_path, monkeypatch, capsys):
    data = completed(tmp_path, monkeypatch)
    _, _, _, _, journal, _, _, calls, cli = data
    budget, options = _test_options(tmp_path, data)
    tty(monkeypatch)
    real = manual_campaign.snapshot_git_commit
    monkeypatch.setattr(
        manual_campaign,
        "snapshot_git_commit",
        lambda *args: replace(real(*args), sha256="0" * 64),
    )
    monkeypatch.setattr("builtins.input", answer)
    assert main([*cli, *options]) == 1
    out = capsys.readouterr().out
    assert "workspace_changed" in out
    plan_id = next(
        line.split()[4].rstrip(";")
        for line in out.splitlines()
        if line.startswith("Created composite test plan:")
    )
    assert journal.get(plan_id).state == "failed"
    usage = budget.snapshot()
    assert (usage.trials, usage.model_calls, usage.judge_calls) == (0, 0, 0)
    assert len(calls) == 6


def test_resolved_conflict_can_be_tested_after_all_confirmations(tmp_path, monkeypatch, capsys):
    data, patch_file = conflict_fixture(tmp_path, monkeypatch)
    _, _, _, _, journal, _, record, calls, cli = data
    budget, options = _test_options(tmp_path, data)
    tty(monkeypatch)

    def respond(prompt):
        if prompt.startswith("Replacement patch file"):
            return str(patch_file)
        if prompt.startswith("Type RESOLVE "):
            return f"RESOLVE {record.id}"
        return answer(prompt)

    monkeypatch.setattr("builtins.input", respond)
    assert main([*cli, "--resolve-conflicts", *options]) == 0
    out = capsys.readouterr().out
    assert "Replacement diff" in out and "Campaign completed" in out
    plan_id = next(
        line.split()[4].rstrip(";")
        for line in out.splitlines()
        if line.startswith("Created composite test plan:")
    )
    assert journal.get(plan_id).state == "completed" and len(calls) == 10
    assert budget.snapshot().trials == 2


def test_cancelling_run_leaves_ready_plan_without_persisted_workspace_guard(
    tmp_path, monkeypatch, capsys
):
    data = completed(tmp_path, monkeypatch)
    _, _, _, _, journal, _, _, calls, cli = data
    budget, options = _test_options(tmp_path, data)
    tty(monkeypatch)

    def respond(prompt):
        if prompt.startswith("Type RUN "):
            return "CANCEL"
        return answer(prompt)

    monkeypatch.setattr("builtins.input", respond)
    assert main([*cli, *options]) == 1
    output = capsys.readouterr()
    assert "cancelled" in output.err and "not stored in the plan" in output.out
    plan_id = next(
        line.split()[4].rstrip(";")
        for line in output.out.splitlines()
        if line.startswith("Created composite test plan:")
    )
    assert journal.get(plan_id).state == "ready" and budget.snapshot().trials == 0
    assert len(calls) == 6


def test_partial_flags_or_insufficient_budget_fail_before_composition(
    tmp_path, monkeypatch, capsys
):
    data = completed(tmp_path, monkeypatch)
    store, _, _, _, _, _, _, calls, cli = data
    cap, options = _test_options(tmp_path, data, trials=1)
    tty(monkeypatch)
    before = set(store.objects.iterdir())
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("confirmation"))
    assert main([*cli, "--test-budget", cap.id]) == 1
    assert "requires --test-budget" in capsys.readouterr().err
    assert main([*cli, *options]) == 1
    assert "insufficient available" in capsys.readouterr().err
    assert set(store.objects.iterdir()) == before and len(calls) == 6


def test_changed_evidence_before_plan_is_refused(tmp_path, monkeypatch, capsys):
    from arcen.harness import evidence_composition

    data = completed(tmp_path, monkeypatch)
    store, adopted, _, _, _, _, _, calls, cli = data
    budget, options = _test_options(tmp_path, data)
    tty(monkeypatch)
    real = evidence_composition.prepare_recorded_composition
    seen = []

    def changing(*args, **kwargs):
        value = real(*args, **kwargs)
        seen.append(1)
        return replace(value, task="changed") if len(seen) == 3 else value

    monkeypatch.setattr(evidence_composition, "prepare_recorded_composition", changing)
    monkeypatch.setattr("builtins.input", answer)
    assert main([*cli, *options]) == 1
    captured = capsys.readouterr()
    assert "changed since display" in captured.err
    assert "Unadopted composite candidate" in captured.out
    assert "Created composite test plan:" not in captured.out
    assert len(calls) == 6 and budget.snapshot().trials == 0
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
