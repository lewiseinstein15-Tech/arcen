"""ARCEN — the frozen event schema (BACKEND-SPEC Part 9).

17 event types. Adding, removing, or renaming is a breaking change
requiring a spec version bump and a UI release in lockstep.

Wire format: NDJSON over HTTP, one JSON object per line terminated \\n,
UTF-8, Content-Type: application/x-ndjson. Every event carries ``seq``
(monotonic per session) and ``ts`` (Unix epoch seconds, float).

Key order on the wire is canonical: seq, type, payload..., ts.

Pulled from AG-UI (sdk/python/ag_ui/) — event typing + encoder pattern;
reduced to the frozen 17 (BACKEND-SPEC Part 2, row 10).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from typing import Any, ClassVar, Union


class EventError(ValueError):
    """Raised for malformed or unknown events on the wire."""


class UnknownEventError(EventError):
    """Raised when a line carries a type outside the frozen 17."""


@dataclass
class RunStart:
    """1 · run.start — DRAFT — turn begins."""

    seq: int
    run_id: str
    goal: str
    depth: int = 0
    ts: float = 0.0
    TYPE: ClassVar[str] = "run.start"


@dataclass
class Think:
    """2 · think — DRAFT — narrated reasoning."""

    seq: int
    agent: str
    text: str
    ts: float = 0.0
    TYPE: ClassVar[str] = "think"


@dataclass
class Plan:
    """3 · plan — DRAFT — plan emitted. steps: [{id, title, tool}]."""

    seq: int
    agent: str
    steps: list[dict[str, Any]]
    ts: float = 0.0
    TYPE: ClassVar[str] = "plan"


@dataclass
class PlanUpdate:
    """4 · plan.update — DRAFT — re-plan / step status change."""

    seq: int
    agent: str
    reason: str
    steps: list[dict[str, Any]]
    ts: float = 0.0
    TYPE: ClassVar[str] = "plan.update"


@dataclass
class Spawn:
    """5 · spawn — DRAFT — sub-agent created."""

    seq: int
    parent: str
    name: str
    task: str
    depth: int = 1
    ts: float = 0.0
    TYPE: ClassVar[str] = "spawn"


@dataclass
class SpawnDone:
    """6 · spawn.done — sub-agent — sub-agent finished."""

    seq: int
    name: str
    ok: bool
    calls: int
    duration_s: float
    ts: float = 0.0
    TYPE: ClassVar[str] = "spawn.done"


@dataclass
class Command:
    """7 · command — FORGE — tool call issued."""

    seq: int
    agent: str
    step: int
    tool: str
    args: dict[str, Any]
    ts: float = 0.0
    TYPE: ClassVar[str] = "command"


@dataclass
class CommandDone:
    """8 · command.done — FORGE — tool result returned."""

    seq: int
    step: int
    ok: bool
    result: dict[str, Any]
    duration_s: float
    ts: float = 0.0
    TYPE: ClassVar[str] = "command.done"


@dataclass
class FileDiff:
    """9 · file.diff — FORGE — file mutation patch (unified diff)."""

    seq: int
    path: str
    patch: str
    ts: float = 0.0
    TYPE: ClassVar[str] = "file.diff"


@dataclass
class VerifyStart:
    """10 · verify.start — TEMPER — adversarial check begins."""

    seq: int
    agent: str
    target: str
    ts: float = 0.0
    TYPE: ClassVar[str] = "verify.start"


@dataclass
class StepPass:
    """11 · step.pass — TEMPER — check passed."""

    seq: int
    step: int
    checks: list[str]
    ts: float = 0.0
    TYPE: ClassVar[str] = "step.pass"


@dataclass
class StepFail:
    """12 · step.fail — TEMPER — check failed."""

    seq: int
    step: int
    reason: str
    retry: int = 0
    ts: float = 0.0
    TYPE: ClassVar[str] = "step.fail"


@dataclass
class Answer:
    """13 · answer — DRAFT — final prose to the user."""

    seq: int
    text: str
    ts: float = 0.0
    TYPE: ClassVar[str] = "answer"


@dataclass
class Memory:
    """14 · memory — memory — write/recall notice."""

    seq: int
    op: str  # "write" | "recall" | "forget"
    entity: str
    fact: str
    ts: float = 0.0
    TYPE: ClassVar[str] = "memory"


@dataclass
class Usage:
    """15 · usage — runtime — token/cost meter. tokens: {input, output}."""

    seq: int
    tokens: dict[str, int]
    cost_usd: float
    ts: float = 0.0
    TYPE: ClassVar[str] = "usage"


@dataclass
class RunDone:
    """16 · run.done — runtime — turn complete."""

    seq: int
    status: str  # "ok" | "failed" | "interrupted"
    steps: int
    duration_s: float
    ts: float = 0.0
    TYPE: ClassVar[str] = "run.done"


@dataclass
class RunError:
    """17 · run.error — runtime — fatal error."""

    seq: int
    code: str
    message: str
    ts: float = 0.0
    TYPE: ClassVar[str] = "run.error"


# The frozen 17, name-for-name. FRONTEND-SPEC Part 17 mirrors this list in
# ui/src/types/events.ts; a CI test fails on drift.
EVENT_TYPES: tuple[str, ...] = (
    "run.start",
    "think",
    "plan",
    "plan.update",
    "spawn",
    "spawn.done",
    "command",
    "command.done",
    "file.diff",
    "verify.start",
    "step.pass",
    "step.fail",
    "answer",
    "memory",
    "usage",
    "run.done",
    "run.error",
)

_EVENT_CLASSES: dict[str, type] = {
    RunStart.TYPE: RunStart,
    Think.TYPE: Think,
    Plan.TYPE: Plan,
    PlanUpdate.TYPE: PlanUpdate,
    Spawn.TYPE: Spawn,
    SpawnDone.TYPE: SpawnDone,
    Command.TYPE: Command,
    CommandDone.TYPE: CommandDone,
    FileDiff.TYPE: FileDiff,
    VerifyStart.TYPE: VerifyStart,
    StepPass.TYPE: StepPass,
    StepFail.TYPE: StepFail,
    Answer.TYPE: Answer,
    Memory.TYPE: Memory,
    Usage.TYPE: Usage,
    RunDone.TYPE: RunDone,
    RunError.TYPE: RunError,
}

assert len(EVENT_TYPES) == 17, "the 17 are frozen; do not touch this list"
assert len(_EVENT_CLASSES) == 17

Event = Union[
    RunStart,
    Think,
    Plan,
    PlanUpdate,
    Spawn,
    SpawnDone,
    Command,
    CommandDone,
    FileDiff,
    VerifyStart,
    StepPass,
    StepFail,
    Answer,
    Memory,
    Usage,
    RunDone,
    RunError,
]


def to_dict(event: Event) -> dict[str, Any]:
    """Serialize an event dataclass to its canonical wire dict.

    Key order: seq, type, payload..., ts (BACKEND-SPEC Part 9).
    """
    data = asdict(event)
    seq = data.pop("seq")
    ts = data.pop("ts")
    out: dict[str, Any] = {"seq": seq, "type": event.TYPE}
    out.update(data)  # payload fields in declaration order
    out["ts"] = ts
    return out


def to_line(event: Event) -> str:
    """One NDJSON line for the wire — compact, UTF-8, no trailing newline."""
    return json.dumps(to_dict(event), ensure_ascii=False, separators=(",", ":"))


def from_dict(data: dict[str, Any]) -> Event:
    """Build an event from a wire dict. Unknown/missing type is rejected."""
    if not isinstance(data, dict):
        raise EventError(f"event must be a JSON object, got {type(data).__name__}")
    etype = data.get("type")
    if etype is None:
        raise EventError("event missing required field 'type'")
    cls = _EVENT_CLASSES.get(etype)
    if cls is None:
        raise UnknownEventError(
            f"unknown event type {etype!r} — the 17 are frozen (BACKEND-SPEC Part 9)"
        )
    field_names = {f.name for f in fields(cls)}
    payload = {k: v for k, v in data.items() if k in field_names}
    dropped = {k for k in data if k != "type" and k not in field_names}
    if dropped:
        raise EventError(f"{etype}: unknown fields {sorted(dropped)}")
    missing = {n for n in field_names if n not in payload and n != "ts"}
    if missing:
        raise EventError(f"{etype}: missing required fields {sorted(missing)}")
    return cls(**payload)  # type: ignore[return-value]


def from_line(line: str) -> Event:
    """Parse one NDJSON line. Malformed JSON / unknown type → EventError."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise EventError(f"malformed NDJSON line: {exc}") from exc
    return from_dict(data)


def validate_registry() -> None:
    """Fail loudly if the frozen list and the class table ever drift."""
    if sorted(EVENT_TYPES) != sorted(_EVENT_CLASSES):
        raise EventError("EVENT_TYPES and event classes are out of sync")
