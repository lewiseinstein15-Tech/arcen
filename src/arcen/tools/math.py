"""ARCEN — math tools (Part 3 wrapped): safe eval with variables, stats, bases."""

from __future__ import annotations

import statistics

from pydantic import BaseModel, Field

from .code import safe_eval
from .registry import BaseTool


class MathEval(BaseTool):
    name = "math.eval"
    description = "Evaluate an arithmetic expression with named variables (safe, no eval)."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        expr: str = Field(description="e.g. rate * hours")
        variables: dict[str, float] = Field(default_factory=dict, description="name → number")

    def _run(self, a: "MathEval.Args") -> dict:
        return {"expr": a.expr, "value": safe_eval(a.expr, dict(a.variables))}


class MathStats(BaseTool):
    name = "math.stats"
    description = "Descriptive stats for a list of numbers: min, max, mean, median, stdev."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        numbers: list[float] = Field(description="sample values", min_length=1)

    def _run(self, a: "MathStats.Args") -> dict:
        nums = a.numbers
        return {
            "count": len(nums),
            "min": min(nums),
            "max": max(nums),
            "sum": sum(nums),
            "mean": statistics.fmean(nums),
            "median": statistics.median(nums),
            "stdev": statistics.stdev(nums) if len(nums) > 1 else 0.0,
        }


class MathConvert(BaseTool):
    name = "math.convert"
    description = "Convert an integer to bin/oct/hex representations."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        value: int = Field(description="integer to convert")

    def _run(self, a: "MathConvert.Args") -> dict:
        v = a.value
        return {
            "int": v,
            "bin": format(v, "b"),
            "oct": format(v, "o"),
            "hex": format(v, "x"),
        }
