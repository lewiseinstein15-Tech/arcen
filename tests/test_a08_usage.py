"""A-08: numeric compatibility without confusing unknown usage with zero."""

from types import SimpleNamespace

from arcen.llm.client import Client
from arcen.llm.usage import UsageAccumulator, provider_metering, summarize_benchmark_usage
from arcen.stream.events import Usage, from_dict, to_dict


def response(usage):
    return SimpleNamespace(
        usage=usage, choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
    )


def test_provider_usage_and_provider_cost():
    client = Client(
        models={"planner": "unit-model"},
        completion_fn=lambda **_: response(
            SimpleNamespace(prompt_tokens=17, completion_tokens=5, cost=0.25)
        ),
    )
    result = client.complete("planner", [])
    assert result.measured is True
    assert result.usage_source == result.cost_source == "provider"
    assert result.tokens == {"input": 17, "output": 5}
    assert result.cost_usd == 0.25


def test_missing_usage_is_unknown():
    result = provider_metering(response(None), "no-such-model")
    assert result == {
        "tokens": {"input": 0, "output": 0},
        "cost_usd": 0.0,
        "measured": False,
        "usage_source": "unknown",
        "cost_source": "unknown",
    }


def test_tokens_only_estimates_cost(monkeypatch):
    monkeypatch.setattr("arcen.llm.usage.litellm.cost_per_token", lambda **_: (0.2, 0.3))
    result = provider_metering(response({"prompt_tokens": 17, "completion_tokens": 5}), "fixture")
    assert result["measured"] is True and result["usage_source"] == "provider"
    assert result["cost_source"] == "estimated" and result["cost_usd"] == 0.5


def test_missing_price_stays_unknown(monkeypatch):
    def unknown(**_):
        raise ValueError("no price")

    monkeypatch.setattr("arcen.llm.usage.litellm.cost_per_token", unknown)
    result = provider_metering(response({"prompt_tokens": 17, "completion_tokens": 5}), "fixture")
    assert result["measured"] and result["cost_source"] == "unknown" and result["cost_usd"] == 0


def test_accumulator_and_benchmark_ignore_unknown():
    known = {
        "measured": True,
        "usage_source": "provider",
        "cost_source": "provider",
        "tokens": {"input": 17, "output": 5},
        "cost_usd": 0.25,
    }
    unknown = {
        "measured": False,
        "usage_source": "unknown",
        "cost_source": "unknown",
        "tokens": {"input": 0, "output": 0},
        "cost_usd": 0.0,
    }
    result = summarize_benchmark_usage([known, unknown])
    assert result == {
        "cost_usd": 0.25,
        "input_tokens": 17,
        "output_tokens": 5,
        "measured_runs": 1,
        "skipped_runs": 1,
    }
    assert summarize_benchmark_usage([unknown])["cost_usd"] is None
    acc = UsageAccumulator()
    acc.add(known)
    acc.add(unknown)
    assert acc.result() == unknown


def test_new_and_old_wire_shapes_round_trip():
    old = {
        "seq": 1,
        "type": "usage",
        "tokens": {"input": 1, "output": 2},
        "cost_usd": 0.3,
        "ts": 0.0,
    }
    assert to_dict(from_dict(old)) == old
    new = Usage(
        seq=1,
        tokens={"input": 1, "output": 2},
        cost_usd=0.3,
        measured=True,
        usage_source="provider",
        cost_source="provider",
    )
    assert to_dict(from_dict(to_dict(new))) == to_dict(new)


def test_retry_cannot_claim_complete_measured_usage():
    calls = 0

    def transient(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        return response(SimpleNamespace(prompt_tokens=1, completion_tokens=2, cost=0.25))

    client = Client(models={"planner": "fixture"}, completion_fn=transient, retry_backoff_seconds=0)
    result = client.complete("planner", [])
    assert calls == 2 and result.measured is False
    assert result.usage_source == result.cost_source == "unknown"


def test_benchmark_skips_missing_or_unknown_cost():
    measured = {"measured": True, "tokens": {"input": 10, "output": 2}, "cost_usd": 0.0}
    result = summarize_benchmark_usage([measured, {**measured, "cost_source": "unknown"}])
    assert result["cost_usd"] is None and result["skipped_runs"] == 2


def test_event_rejects_partial_or_invalid_metadata():
    import pytest

    from arcen.stream.events import EventError

    old = {
        "seq": 1,
        "type": "usage",
        "tokens": {"input": 1, "output": 2},
        "cost_usd": 0.3,
        "ts": 0.0,
    }
    with pytest.raises(EventError):
        from_dict({**old, "measured": True})
    with pytest.raises(EventError):
        from_dict({**old, "measured": False, "usage_source": "provider", "cost_source": "unknown"})


def test_client_without_provider_usage_marks_unknown():
    client = Client(models={"planner": "fixture"}, completion_fn=lambda **_: response(None))
    result = client.complete("planner", [])
    assert not result.measured
    assert result.tokens == {"input": 0, "output": 0}
    assert result.usage_source == result.cost_source == "unknown"
