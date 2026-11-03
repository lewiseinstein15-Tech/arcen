"""Conservative benchmark data formatting, without executing agent output."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Protocol

from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError, validate_patch


class ScoringRuntime(Protocol):
    """Evaluator must apply and test the patch in its own isolated environment."""

    def score(self, task_id: str, patch: bytes) -> bool | None: ...


def read_patch(path: Path) -> bytes:
    """Bound reads before materializing data; validate untrusted bytes."""
    with path.open("rb") as stream:
        data = stream.read(MAX_PATCH_BYTES + 1)
    validate_patch(data)
    return data


def score_patch(task_id: str, patch_path: Path, runtime: ScoringRuntime) -> dict:
    if not task_id:
        raise ValueError("task ID is required")
    patch = read_patch(patch_path)
    result = runtime.score(task_id, patch)
    if result is not None and type(result) is not bool:
        raise ValueError("scorer must return true, false, or unknown")
    return {
        "task_id": task_id,
        "resolved": result,
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
    }


def swebench_prediction(instance_id: str, model: str, patch_path: Path) -> dict:
    if not instance_id or not model:
        raise ValueError("instance ID and fixed model are required")
    patch = read_patch(patch_path)
    try:
        text = patch.decode("utf-8")
    except UnicodeError as exc:
        raise ArtifactError("patch is not UTF-8") from exc
    return {"instance_id": instance_id, "model_name_or_path": model, "model_patch": text}


def aggregate(rows: list[dict]) -> dict:
    """Summarize measured outcomes only; missing values never become zero."""
    outcomes = [r["resolved"] for r in rows if type(r.get("resolved")) is bool]
    costs = [
        r["cost_usd"]
        for r in rows
        if r.get("cost_measured") is True
        and type(r.get("cost_usd")) in (int, float)
        and math.isfinite(r["cost_usd"])
        and r["cost_usd"] >= 0
    ]
    return {
        "resolved": sum(outcomes),
        "scored": len(outcomes),
        "unscored": len(rows) - len(outcomes),
        "resolved_percent": 100 * sum(outcomes) / len(outcomes) if outcomes else None,
        "cost_usd": sum(costs) if costs else None,
        "cost_measured_runs": len(costs),
        "cost_skipped_runs": len(rows) - len(costs),
    }
