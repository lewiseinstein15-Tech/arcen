"""Best-effort, metadata-only progress for explicit manual campaigns.

This is not a durable event log, authorization, or replay/resume protocol.
Payloads use fixed fields and never include task, prompts, paths or transcripts.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any

from .resolver import HarnessError

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_STOP_REASONS = frozenset(
    {
        "stopped",
        "budget_closed",
        "concurrency_full",
        "reference_isolation_failed",
        "reference_failed",
        "candidate_isolation_failed",
        "candidate_failed",
        "judge_failed",
        "review_record_failed",
        "workspace_sensitive",
    }
)


class Progress:
    """Emit separately sequenced status dictionaries to an optional trusted sink.

    Ordinary sink exceptions are swallowed and events can be lost; they must
    not be used as evidence of completion or safe recovery. The sink is trusted
    local code and may itself affect the process, including via BaseException.
    """

    def __init__(self, sink: Callable[[dict[str, Any]], None] | None):
        if sink is not None and not callable(sink):
            raise HarnessError("invalid campaign progress sink")
        self._sink = sink
        self._seq = 0

    def emit(self, kind: str, **fields: Any) -> None:
        if self._sink is None:
            return
        self._seq += 1
        # Only call this with code-defined events and validated identifiers.
        payload = {"seq": self._seq, "type": kind, **fields}
        try:
            _validate(payload)
            self._sink(payload)
        except Exception:  # noqa: BLE001 — observer failure must not control a run
            return


def _validate(event: dict[str, Any]) -> None:
    """Reject accidental expansion of the progress-only privacy boundary."""
    schemas = {
        "harness.campaign.start": {"candidate_count"},
        "harness.policy": {"candidate_id", "decision"},
        "harness.probe.start": {"candidate_id", "role"},
        "harness.probe.done": {"candidate_id", "role", "status"},
        "harness.judge": {"candidate_id", "winner", "confidence"},
        "harness.review": {"candidate_id", "review_id", "state"},
        "harness.campaign.done": {"status", "reason", "completed"},
    }
    kind = event.get("type")
    if kind not in schemas or set(event) != schemas[kind] | {"type", "seq"}:
        raise HarnessError("invalid campaign progress event")
    if type(event["seq"]) is not int or event["seq"] < 1:
        raise HarnessError("invalid campaign progress sequence")
    if "candidate_id" in event and (
        type(event["candidate_id"]) is not str or not _HEX64.fullmatch(event["candidate_id"])
    ):
        raise HarnessError("invalid progress candidate ID")
    if "review_id" in event and (
        type(event["review_id"]) is not str or not _HEX32.fullmatch(event["review_id"])
    ):
        raise HarnessError("invalid progress review ID")
    if kind == "harness.campaign.start" and (
        type(event["candidate_count"]) is not int or not 1 <= event["candidate_count"] <= 5
    ):
        raise HarnessError("invalid progress candidate count")
    if kind == "harness.policy" and event["decision"] != "reviewed":
        raise HarnessError("invalid progress policy decision")
    if kind in {"harness.probe.start", "harness.probe.done"} and event["role"] not in {
        "reference",
        "candidate",
    }:
        raise HarnessError("invalid progress probe role")
    if kind == "harness.probe.done" and event["status"] not in {"ok", "failed", "unavailable"}:
        raise HarnessError("invalid progress probe status")
    if kind == "harness.judge" and (
        event["winner"] not in {"candidate", "reference", "tie"}
        or type(event["confidence"]) not in (int, float)
        or not math.isfinite(event["confidence"])
        or not 0 <= event["confidence"] <= 1
    ):
        raise HarnessError("invalid progress judgment")
    if kind == "harness.review" and event["state"] != "pending":
        raise HarnessError("invalid progress review state")
    if kind == "harness.campaign.done" and (
        event["status"] not in {"completed", "stopped"}
        or (event["reason"] is not None and event["reason"] not in _STOP_REASONS)
        or (event["status"] == "completed") != (event["reason"] is None)
        or type(event["completed"]) is not int
        or not 0 <= event["completed"] <= 5
    ):
        raise HarnessError("invalid progress campaign outcome")
