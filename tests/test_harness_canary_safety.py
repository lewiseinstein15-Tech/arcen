"""Narrow canary safeguards: admission preflight and uncertain result handling."""

from dataclasses import replace

import pytest
from test_canary_cli import fixture, tty
from test_harness_canary import run, setup
from test_harness_comparison import provider
from test_probe_execution import Boundary

from arcen.harness import canary, probe_container
from arcen.harness.budget import BudgetExhausted
from arcen.harness.cli import _init, main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.lineage import HarnessLineage
from arcen.harness.policy import AdoptionUnavailable, adopt_candidate


@pytest.mark.parametrize("trials,models", [(3, 16), (4, 3)])
def test_capacity_shortfall_refused_before_bind_git_container_and_provider(
    tmp_path, monkeypatch, trials, models
):
    args = setup(tmp_path)
    cap = DurableBudget.create(
        args[0], max_trials=trials, max_model_calls=models, max_judge_calls=0, admission_seconds=120
    )
    calls = provider(monkeypatch)
    monkeypatch.setattr(canary, "bind_probe_model", lambda *a, **k: pytest.fail("unexpected bind"))
    monkeypatch.setattr(canary, "snapshot_git_commit", lambda *a: pytest.fail("unexpected Git"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **k: pytest.fail("Docker")
    )
    with pytest.raises(BudgetExhausted, match="insufficient available"):
        run(args, budget=cap)
    state = cap.snapshot()
    assert (state.trials, state.model_calls, state.stopped) == (0, 0, False)
    assert not calls


@pytest.mark.parametrize("kind", ["trial", "model"])
def test_previously_consumed_capacity_counts_against_minimum(tmp_path, monkeypatch, kind):
    args = setup(tmp_path)
    cap = DurableBudget.create(
        args[0], max_trials=4, max_model_calls=4, max_judge_calls=0, admission_seconds=120
    )
    (cap.reserve_trial if kind == "trial" else cap.reserve_model_call)()
    monkeypatch.setattr(canary, "snapshot_git_commit", lambda *a: pytest.fail("unexpected Git"))
    with pytest.raises(BudgetExhausted, match="insufficient available"):
        run(args, budget=cap)
    assert not cap.snapshot().stopped


@pytest.mark.parametrize("bad", [None, 0, 1, "true", [], {}])
@pytest.mark.parametrize("which", [1, 2])
def test_invalid_verifier_flag_is_inconclusive_not_regression_or_pass(
    tmp_path, monkeypatch, bad, which
):
    args = setup(tmp_path)
    adopted = _init(str(args[0].root))
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    original = canary._run_bound_probe
    seen = 0

    def invalid(*a, **kw):
        nonlocal seen
        result = original(*a, **kw)
        seen += 1
        return replace(result, canary_passed=bad) if seen == which else result

    monkeypatch.setattr(canary, "_run_bound_probe", invalid)
    report = run(args)
    assert report.outcome == "inconclusive" and seen == which and len(calls) == which * 2
    expected = ("inconclusive", "not-run") if which == 1 else ("passed", "inconclusive")
    assert [(f.reference, f.candidate) for f in report.findings] == [expected]
    assert HarnessLineage(args[0], read_only=True).resolve("refs/heads/adopted") == adopted
    with pytest.raises(AdoptionUnavailable):
        adopt_candidate(args[0], args[1], args[2])


@pytest.mark.parametrize("when", ["before_prompt", "during_prompt"])
def test_cli_rechecks_capacity_before_any_git_or_trial(tmp_path, monkeypatch, capsys, when):
    store, adopted, _, candidate, budget, arguments = fixture(tmp_path, capsys)
    tty(monkeypatch)
    if when == "before_prompt":
        budget.reserve_trial()
        monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected prompt"))
    else:

        def confirm(_):
            budget.reserve_trial()  # a competing consumer after the first check
            return f"CANARY {candidate}"

        monkeypatch.setattr("builtins.input", confirm)
    monkeypatch.setattr(canary, "snapshot_git_commit", lambda *a: pytest.fail("unexpected Git"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **k: pytest.fail("Docker")
    )
    calls = provider(monkeypatch)
    assert main(arguments) == 1
    out = capsys.readouterr()
    assert "insufficient available" in out.err and "Canary result:" not in out.out
    state = budget.snapshot()
    assert (state.trials, state.model_calls, state.stopped) == (1, 0, False)
    assert not calls
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
