"""Opt-in campaign progress wire bridge; no approval or live server wiring."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from test_harness_comparison import provider
from test_manual_campaign import run, setup
from test_probe_execution import Boundary
from test_probe_model import SECRET

from arcen.harness import probe_container
from arcen.stream.emitter import StreamEmitter
from arcen.stream.events import (
    EVENT_TYPES,
    EventError,
    RunDone,
    RunStart,
    UnknownEventError,
    from_dict,
)
from arcen.stream.events_v2 import (
    V2_PROGRESS_TYPES,
    CampaignStart,
    ProgressStream,
    from_v2_dict,
    from_v2_line,
    progress_from_wire,
    to_v2_line,
)
from arcen.tui.adapter import EventAdapter
from arcen.tui.harness_demo import simulated_progress
from arcen.tui.harness_progress import register_v2_progress


class Narration:
    def __init__(self):
        self.items = []

    def push(self, item):
        self.items.append(item)

    def replace_at(self, index, item):
        self.items[index] = item


class Rail:
    def apply_state(self, state):
        pass


def wire_events():
    emitter = StreamEmitter("test")
    bridge = ProgressStream(emitter)
    for event in simulated_progress():
        bridge(event)
    return emitter.replay(0)


def test_all_seven_types_round_trip_to_privacy_bounded_progress():
    wires = wire_events()
    assert {e["type"] for e in wires} == set(V2_PROGRESS_TYPES)
    for wire, expected in zip(wires, simulated_progress(), strict=True):
        decoded = from_v2_dict(wire)
        assert from_v2_line(to_v2_line(decoded)) == decoded
        assert progress_from_wire(wire) == expected
        assert list(wire)[0:2] == ["seq", "type"] and list(wire)[-1] == "ts"


def test_stream_sequence_is_shared_with_legacy_events_and_schema_stays_frozen():
    emitter = StreamEmitter("session")
    start = emitter.emit(RunStart(seq=0, run_id="r", goal="work"))
    bridge = ProgressStream(emitter)
    for item in simulated_progress():
        bridge(item)
    done = emitter.emit(RunDone(seq=0, status="ok", steps=0, duration_s=0))
    events = emitter.replay(0)
    assert [e["seq"] for e in events] == list(range(1, 12))
    assert from_dict(start).TYPE == "run.start" and from_dict(done).TYPE == "run.done"
    assert len(EVENT_TYPES) == 17 and all(kind not in EVENT_TYPES for kind in V2_PROGRESS_TYPES)
    with pytest.raises(UnknownEventError):
        from_dict(events[1])  # strict legacy decoder deliberately rejects v2


def test_tui_v2_registration_is_opt_in_and_never_replaces_handlers():
    wires = wire_events()
    old = EventAdapter(Narration(), Rail())
    assert all(not old.apply(wire) for wire in wires)
    assert old.state.last_seq == len(wires) and old.narration.items == []
    new = EventAdapter(Narration(), Rail())
    view = register_v2_progress(new)
    assert all(new.apply(wire) for wire in wires)
    assert view.accepted == len(wires) and len(new.narration.items) > len(wires)
    assert not new.apply(wires[-1])  # replay watermark
    with pytest.raises(ValueError, match="already"):
        register_v2_progress(new)


def test_tui_discards_malformed_or_extra_private_data():
    adapter = EventAdapter(Narration(), Rail())
    view = register_v2_progress(adapter)
    wire = wire_events()[0]
    wire["task"] = "private task text"
    adapter.apply(wire)
    assert view.accepted == 0 and not adapter.narration.items


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e | {"task": "private"},
        lambda e: e | {"seq": True},
        lambda e: e | {"candidate_count": 0},
        lambda e: e | {"ts": float("nan")},
        lambda e: e | {"ts": 10**1000},
        lambda e: e | {"ts": True},
        lambda e: e | {"type": "approval.resolve"},
        lambda e: {k: v for k, v in e.items() if k != "ts"},
        lambda e: e | {"type": ["invalid"]},
    ],
)
def test_v2_decoder_rejects_invalid_extra_or_authorization_claims(mutate):
    with pytest.raises(EventError):
        from_v2_dict(mutate(wire_events()[0]))


@pytest.mark.parametrize("line", ['{"type":"x","type":"y"}', "{", "x" * 16385, "\\ud800"])
def test_v2_lines_reject_invalid_json_duplicates_and_oversize(line):
    with pytest.raises(EventError):
        from_v2_line(line)


def test_bridge_rejects_invalid_progress_without_emitting_and_keeps_payload_private():
    emitter = StreamEmitter("s")
    bridge = ProgressStream(emitter)
    event = {"seq": 1, "type": "harness.campaign.start", "candidate_count": 1, "task": "secret"}
    with pytest.raises(EventError):
        bridge(event)
    assert emitter.last_seq == 0 and emitter.replay(0) == []
    with pytest.raises(EventError):
        ProgressStream(object())
    with pytest.raises(EventError):
        to_v2_line(replace(CampaignStart(seq=1, candidate_count=1), ts=-1))


def test_real_manual_campaign_can_opt_in_without_leaking_task_or_changing_refs(
    tmp_path, monkeypatch
):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    emitter = StreamEmitter("manual")
    result = run(args, on_progress=ProgressStream(emitter))
    wires = emitter.replay(0)
    assert result.stop_reason is None and len(result.completed) == 2 and len(calls) == 6
    assert [wire["seq"] for wire in wires] == list(range(1, len(wires) + 1))
    assert wires[-1]["type"] == "harness.campaign.done" and wires[-1]["status"] == "completed"
    assert sum(wire["type"] == "harness.review" for wire in wires) == 2
    for item in wires:
        from_v2_dict(item)
    payload = json.dumps(wires)
    for forbidden in (SECRET, "inspect project", "CANDIDATE PLANNER", str(args[4])):
        assert forbidden not in payload
    assert not (args[0].root / "lineage.sqlite3").exists()


def test_observer_failure_still_does_not_control_campaign(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch)
    emitter = StreamEmitter("manual")
    emitter.subscribe(lambda _event: (_ for _ in ()).throw(ValueError("observer failure")))
    result = run(args, on_progress=ProgressStream(emitter))
    assert result.stop_reason is None and len(result.completed) == 2
    assert emitter.last_seq > 0


@pytest.mark.parametrize(
    "clock", [float("nan"), float("inf"), 0, True, pytest.param(10**1000, id="huge-int")]
)
def test_invalid_clock_cannot_consume_stream_sequence(monkeypatch, clock):
    monkeypatch.setattr("arcen.stream.events_v2.time.time", lambda: clock)
    emitter = StreamEmitter("test")
    with pytest.raises(EventError):
        ProgressStream(emitter)(simulated_progress()[0])
    assert emitter.last_seq == 0
