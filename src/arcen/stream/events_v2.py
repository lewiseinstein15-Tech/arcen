"""Opt-in metadata-only manual campaign events for the existing stream.

This is not the complete Harness² v2 contract. It adds no server routes,
execution, durable history, approval, adoption, or recovery. Legacy events and
their strict decoder are unchanged. Records and subscribers are untrusted;
stream events are best-effort narration, never authorization or evidence.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, fields
from typing import ClassVar

from arcen.harness.progress import _validate
from arcen.harness.resolver import HarnessError

from .emitter import StreamEmitter
from .events import EventError, to_dict


@dataclass
class CampaignStart:
    seq: int
    candidate_count: int
    ts: float = 0.0
    TYPE: ClassVar[str] = "harness.campaign.start"


@dataclass
class PolicyReviewed:
    seq: int
    candidate_id: str
    decision: str
    ts: float = 0.0
    TYPE: ClassVar[str] = "harness.policy"


@dataclass
class ProbeStart:
    seq: int
    candidate_id: str
    role: str
    ts: float = 0.0
    TYPE: ClassVar[str] = "harness.probe.start"


@dataclass
class ProbeDone:
    seq: int
    candidate_id: str
    role: str
    status: str
    ts: float = 0.0
    TYPE: ClassVar[str] = "harness.probe.done"


@dataclass
class JudgeObserved:
    seq: int
    candidate_id: str
    winner: str
    confidence: float
    ts: float = 0.0
    TYPE: ClassVar[str] = "harness.judge"


@dataclass
class ReviewPending:
    seq: int
    candidate_id: str
    review_id: str
    state: str
    ts: float = 0.0
    TYPE: ClassVar[str] = "harness.review"


@dataclass
class CampaignDone:
    seq: int
    status: str
    reason: str | None
    completed: int
    ts: float = 0.0
    TYPE: ClassVar[str] = "harness.campaign.done"


_CLASSES = {
    cls.TYPE: cls
    for cls in (
        CampaignStart,
        PolicyReviewed,
        ProbeStart,
        ProbeDone,
        JudgeObserved,
        ReviewPending,
        CampaignDone,
    )
}
V2_PROGRESS_TYPES = tuple(_CLASSES)
_MAX_LINE_BYTES = 16384


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _checked_progress(data: object) -> dict:
    if type(data) is not dict:
        raise EventError("invalid v2 progress event")
    try:
        _validate(data)
    except (HarnessError, TypeError, ValueError, OverflowError, KeyError):
        raise EventError("invalid v2 progress event") from None
    return dict(data)


def from_v2_dict(data: object):
    """Strictly decode one of the seven metadata-only v2 progress events."""
    if type(data) is not dict or type(data.get("type")) is not str:
        raise EventError("invalid v2 progress event")
    cls = _CLASSES.get(data["type"])
    if cls is None:
        raise EventError("unknown v2 progress event")
    names = {item.name for item in fields(cls)}
    if set(data) != names | {"type"}:
        raise EventError("invalid v2 progress event fields")
    ts = data["ts"]
    try:
        valid_ts = type(ts) in (int, float) and math.isfinite(ts) and ts > 0
    except (OverflowError, ValueError):
        valid_ts = False
    if not valid_ts:
        raise EventError("invalid v2 progress timestamp")
    progress = dict(data)
    del progress["ts"]
    _checked_progress(progress)
    return cls(**{name: data[name] for name in names})


def from_v2_line(line: str):
    if type(line) is not str:
        raise EventError("invalid v2 progress line")
    try:
        if len(line.encode("utf-8")) > _MAX_LINE_BYTES:
            raise EventError("oversized v2 progress line")
        data = json.loads(line, object_pairs_hook=_pairs)
    except (UnicodeError, ValueError):
        raise EventError("invalid v2 progress line") from None
    return from_v2_dict(data)


def to_v2_line(event) -> str:
    if type(event) not in _CLASSES.values():
        raise EventError("invalid v2 progress event")
    wire = to_dict(event)
    from_v2_dict(wire)
    return json.dumps(wire, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def progress_from_wire(data: object) -> dict:
    """Validate v2 wire data and recover the privacy-bounded progress shape."""
    event = from_v2_dict(data)
    result = to_dict(event)
    del result["ts"]
    return result


class ProgressStream:
    """Trusted opt-in callback: stamp manual progress onto a session emitter.

    Pass an instance as ``on_progress``. Session sequence numbers replace the
    separate local progress sequence. The emitter/subscribers are trusted and
    can fail or mutate records; normal Progress suppresses observer exceptions.
    Events are neither durable nor suitable to resume or authorize a campaign.
    """

    def __init__(self, emitter: StreamEmitter):
        if type(emitter) is not StreamEmitter:
            raise EventError("invalid progress stream emitter")
        self.emitter = emitter

    def __call__(self, progress: dict) -> None:
        data = _checked_progress(progress)
        cls = _CLASSES[data.pop("type")]
        data.pop("seq")
        now = time.time()
        try:
            valid_now = type(now) in (int, float) and math.isfinite(now) and now > 0
        except (OverflowError, ValueError):
            valid_now = False
        if not valid_now:
            raise EventError("invalid progress clock")
        event = cls(seq=0, ts=now, **data)
        self.emitter.emit(event)
