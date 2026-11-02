"""Conservative provider usage accounting for one turn and benchmark summaries."""

from __future__ import annotations

import math
from typing import Any

import litellm


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def provider_metering(response: Any, model: str) -> dict:
    """Extract provider usage; estimate price only from LiteLLM's price map."""
    usage = _field(response, "usage")
    input_tokens = _field(usage, "prompt_tokens")
    output_tokens = _field(usage, "completion_tokens")
    if (
        type(input_tokens) is not int
        or type(output_tokens) is not int
        or min(input_tokens, output_tokens) < 0
    ):
        return {
            "tokens": {"input": 0, "output": 0},
            "cost_usd": 0.0,
            "measured": False,
            "usage_source": "unknown",
            "cost_source": "unknown",
        }
    cost = _field(usage, "cost")
    source = "provider" if _number(cost) else "unknown"
    if source == "unknown":
        try:
            inp, out = litellm.cost_per_token(
                model=model, prompt_tokens=input_tokens, completion_tokens=output_tokens
            )
            cost = inp + out
            if not _number(cost):
                raise ValueError("invalid model price")
            source = "estimated"
        except Exception:  # noqa: BLE001 — unknown model prices are not free
            cost = 0.0
    return {
        "tokens": {"input": input_tokens, "output": output_tokens},
        "cost_usd": float(cost),
        "measured": True,
        "usage_source": "provider",
        "cost_source": source,
    }


class UsageAccumulator:
    """Do not turn an incomplete collection of calls into a complete total."""

    def __init__(self) -> None:
        self.values: list[dict] = []

    def add(self, value: dict) -> None:
        self.values.append(value)

    def result(self) -> dict:
        if not self.values or any(v.get("measured") is not True for v in self.values):
            return {
                "tokens": {"input": 0, "output": 0},
                "cost_usd": 0.0,
                "measured": False,
                "usage_source": "unknown",
                "cost_source": "unknown",
            }
        sources = [v.get("cost_source", "unknown") for v in self.values]
        cost_source = (
            "unknown"
            if "unknown" in sources
            else "estimated"
            if "estimated" in sources
            else "provider"
        )
        return {
            "tokens": {
                key: sum(v["tokens"][key] for v in self.values) for key in ("input", "output")
            },
            "cost_usd": sum(v["cost_usd"] for v in self.values)
            if cost_source != "unknown"
            else 0.0,
            "measured": True,
            "usage_source": "provider",
            "cost_source": cost_source,
        }


class MeteredClient:
    """A per-turn proxy, so concurrent turns never share accounting state."""

    def __init__(self, inner: Any, accumulator: UsageAccumulator) -> None:
        self.inner = inner
        self.accumulator = accumulator

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def complete(self, *args: Any, **kwargs: Any) -> Any:
        try:
            response = self.inner.complete(*args, **kwargs)
        except Exception:
            self.accumulator.add({"measured": False})
            raise
        self.accumulator.add(
            {
                "tokens": response.tokens,
                "cost_usd": response.cost_usd,
                "measured": response.measured,
                "usage_source": response.usage_source,
                "cost_source": response.cost_source,
            }
        )
        return response


def summarize_benchmark_usage(rows: list[dict]) -> dict:
    """Sum only complete measured runs; missing cost is never counted as free."""
    usable = [
        r
        for r in rows
        if r.get("measured") is True and r.get("cost_source") in {"provider", "estimated"}
    ]
    skipped = len(rows) - len(usable)
    return {
        "cost_usd": sum(r["cost_usd"] for r in usable) if usable else None,
        "input_tokens": sum(r["tokens"]["input"] for r in usable) if usable else None,
        "output_tokens": sum(r["tokens"]["output"] for r in usable) if usable else None,
        "measured_runs": len(usable),
        "skipped_runs": skipped,
    }
