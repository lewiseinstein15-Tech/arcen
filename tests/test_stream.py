"""T-013 / Test-plan T-11 (emitter half) — NDJSON streaming emitter.

Proves: every event is stamped seq+ts, framed as NDJSON, buffered for
Last-Event-ID replay; live subscribers notified; the frozen schema
rejects unknown types even here.
"""

import json

import pytest

from arcen.stream.emitter import StreamEmitter
from arcen.stream.events import (
    EVENT_TYPES,
    Answer,
    Command,
    CommandDone,
    FileDiff,
    Memory,
    Plan,
    PlanUpdate,
    RunDone,
    RunError,
    RunStart,
    Spawn,
    SpawnDone,
    StepFail,
    StepPass,
    Think,
    UnknownEventError,
    Usage,
    VerifyStart,
    from_line,
)


def _all_17() -> list:
    """One instance of each frozen type, in spec order."""
    return [
        RunStart(seq=0, run_id="r-01J9", goal="fix the failing test", depth=0),
        Think(seq=0, agent="DRAFT", text="Read the test first, then the module."),
        Plan(seq=0, agent="DRAFT", steps=[{"id": 1, "title": "read failing test", "tool": "file.read"}]),
        PlanUpdate(seq=0, agent="DRAFT", reason="test bug", steps=[{"id": 1, "title": "edit assertion", "tool": "file.edit"}]),
        Spawn(seq=0, parent="DRAFT", name="TEST-READER", task="extract assertion", depth=1),
        SpawnDone(seq=0, name="TEST-READER", ok=True, calls=3, duration_s=12.4),
        Command(seq=0, agent="FORGE", step=2, tool="bash", args={"cmd": "pytest -q tests/"}),
        CommandDone(seq=0, step=2, ok=True, result={"stdout": "12 passed", "exit": 0}, duration_s=3.2),
        FileDiff(seq=0, path="tests/test_pay.py", patch="--- a/f\n+++ b/f\n@@ -1 +1 @@"),
        VerifyStart(seq=0, agent="TEMPER", target="tests/"),
        StepPass(seq=0, step=3, checks=["pytest -q tests/  # 12 passed"]),
        StepFail(seq=0, step=3, reason="assert 4 == 5", retry=1),
        Answer(seq=0, text="The test expected 5; calc returns 4. Fixed."),
        Memory(seq=0, op="write", entity="calc()", fact="returns int sum"),
        Usage(seq=0, tokens={"input": 18432, "output": 1204}, cost_usd=0.021),
        RunDone(seq=0, status="ok", steps=3, duration_s=6.5),
        RunError(seq=0, code="SANDBOX_UNAVAILABLE", message="docker daemon not reachable"),
    ]


def test_emit_all_17_in_order() -> None:
    emitter = StreamEmitter("s-test")
    lines = [emitter.to_line(emitter.emit(e)) for e in _all_17()]
    assert len(lines) == 17
    parsed = [json.loads(l) for l in lines]
    assert [p["type"] for p in parsed] == list(EVENT_TYPES)
    assert [p["seq"] for p in parsed] == list(range(1, 18))  # monotonic from 1


def test_every_event_carries_seq_and_ts() -> None:
    emitter = StreamEmitter("s-test")
    for event in _all_17():
        wire = emitter.emit(event)
        assert isinstance(wire["seq"], int) and wire["seq"] > 0
        assert isinstance(wire["ts"], float) and wire["ts"] > 1_600_000_000


def test_line_is_compact_utf8_ndjson() -> None:
    emitter = StreamEmitter("s-test")
    line = emitter.to_line(emitter.emit(Think(seq=0, agent="DRAFT", text="héllo ✱")))
    assert "\n" not in line.rstrip("\n")
    assert ", " not in line and '": ' not in line  # compact separators
    assert "héllo ✱" in line  # ensure_ascii=False
    parsed = from_line(line)
    assert parsed.agent == "DRAFT"


def test_replay_from_last_event_id() -> None:
    emitter = StreamEmitter("s-test")
    for e in _all_17():
        emitter.emit(e)
    # client reconnects with Last-Event-ID: 14 → server re-emits 15..17
    resumed = emitter.replay(14)
    assert [e["seq"] for e in resumed] == [15, 16, 17]
    assert emitter.replay_lines(14)[0].strip().startswith('{"seq":15,"type":"usage"')
    # replay of everything
    assert len(emitter.replay(0)) == 17


def test_buffer_respects_keep_last() -> None:
    emitter = StreamEmitter("s-test", keep_last=5)
    for i in range(10):
        emitter.emit(Think(seq=0, agent="DRAFT", text=f"t{i}"))
    assert len(emitter.replay(0)) == 5
    assert emitter.replay(0)[0]["seq"] == 6  # oldest five compacted away
    assert emitter.last_seq == 10


def test_subscribers_notified_live() -> None:
    emitter = StreamEmitter("s-test")
    seen: list[dict] = []
    emitter.subscribe(seen.append)
    emitter.emit(RunStart(seq=0, run_id="r-1", goal="g"))
    emitter.emit(RunDone(seq=0, status="ok", steps=1, duration_s=0.1))
    assert [e["type"] for e in seen] == ["run.start", "run.done"]


def test_seed_adopts_disk_log_and_continues_seq() -> None:
    """Server-restart recovery: seed from disk, seqs continue at N+1."""
    emitter = StreamEmitter("s-test")
    for e in _all_17():
        emitter.emit(e)
    disk_log = emitter.replay(0)  # what SessionStore.read() hands back

    fresh = StreamEmitter("s-test")  # new process, empty memory
    fresh.seed(disk_log)
    assert fresh.last_seq == 17  # continuity — NOT reset to 0
    assert [e["seq"] for e in fresh.replay(0)] == list(range(1, 18))
    wire = fresh.emit(Answer(seq=0, text="post-restart"))
    assert wire["seq"] == 18  # new turns never collide with disk history

    fresh.seed(disk_log)  # seeding a live emitter is a no-op
    assert fresh.last_seq == 18

    empty = StreamEmitter("s-empty")
    empty.seed([])
    assert empty.last_seq == 0
    assert empty.emit(Answer(seq=0, text="first"))["seq"] == 1


def test_unknown_event_rejected_by_schema() -> None:
    # the emitter only accepts the frozen 17 — enforced by the dataclass table
    class Fake:
        TYPE = "not.real"
        seq = 0
        ts = 0.0

    emitter = StreamEmitter("s-test")
    with pytest.raises((UnknownEventError, AttributeError, TypeError)):
        emitter.emit(Fake())  # type: ignore[arg-type]


def test_lines_parse_back_through_frozen_schema() -> None:
    emitter = StreamEmitter("s-test")
    for e in _all_17():
        emitter.emit(e)
    for line in emitter.all_lines():
        event = from_line(line.strip())
        assert event is not None
