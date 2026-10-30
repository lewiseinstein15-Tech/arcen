"""Momentary admission minima are not reservations or financial limits."""

import pytest

from arcen.harness.budget import BudgetExhausted, SharedBudget
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.resolver import HarnessError
from arcen.harness.store import HarnessStore


@pytest.fixture(params=["memory", "durable"])
def budget(request, tmp_path):
    limits = {"max_trials": 4, "max_model_calls": 6, "max_judge_calls": 2, "admission_seconds": 60}
    if request.param == "memory":
        return SharedBudget(**limits)
    return DurableBudget.create(HarnessStore(tmp_path / "store"), **limits)


def test_minimum_is_a_read_only_count_check(budget):
    budget.reserve_trial()
    budget.reserve_model_call()
    budget.require_available(trials=3, model_calls=5, judge_calls=2)
    state = budget.snapshot()
    assert (state.trials, state.model_calls, state.judge_calls, state.stopped) == (1, 1, 0, False)


@pytest.mark.parametrize("category", ["trials", "model_calls", "judge_calls"])
def test_insufficient_minimum_does_not_latch_budget(budget, category):
    request = {"trials": 4, "model_calls": 6, "judge_calls": 2}
    request[category] += 1
    with pytest.raises(BudgetExhausted, match="insufficient available"):
        budget.require_available(**request)
    assert not budget.snapshot().stopped
    budget.reserve_trial()
    assert budget.snapshot().trials == 1


@pytest.mark.parametrize("value", [True, -1, 1.0, "1", None, 100001])
def test_minimum_type_validation(budget, value):
    with pytest.raises(HarnessError, match="invalid minimum"):
        budget.require_available(trials=value, model_calls=0, judge_calls=0)
    assert not budget.snapshot().stopped


def test_stopped_budget_refuses_minimum(budget):
    budget.stop()
    with pytest.raises(BudgetExhausted, match="closed"):
        budget.require_available(trials=0, model_calls=0, judge_calls=0)


def test_intervening_consumer_can_spend_after_check(budget):
    budget.require_available(trials=4, model_calls=0, judge_calls=0)
    budget.reserve_trial()
    with pytest.raises(BudgetExhausted, match="insufficient"):
        budget.require_available(trials=4, model_calls=0, judge_calls=0)
    assert not budget.snapshot().stopped


def test_durable_check_observes_other_instance_without_reserving(tmp_path):
    store = HarnessStore(tmp_path / "store")
    first = DurableBudget.create(
        store, max_trials=4, max_model_calls=4, max_judge_calls=2, admission_seconds=60
    )
    second = DurableBudget(store, first.id)
    first.require_available(trials=4, model_calls=4, judge_calls=2)
    second.reserve_trial()
    with pytest.raises(BudgetExhausted, match="insufficient"):
        first.require_available(trials=4, model_calls=4, judge_calls=2)
    assert first.snapshot().trials == 1 and not second.snapshot().stopped
