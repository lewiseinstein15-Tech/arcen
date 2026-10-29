"""TUI-10: fixture replay through the real event adapter and view seams."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("textual")

from rich.console import Console
from rich.text import Text

from arcen.stream.events import EVENT_TYPES, from_dict
from arcen.tui.adapter import EventAdapter
from arcen.tui.app import Footer, Header
from arcen.tui.cards import CardRegistry
from arcen.tui.views.rail import RunStateRail

FIXTURE = Path(__file__).parent / "fixtures/tui/server-replan.jsonl"


class RecordingNarration:
    def __init__(self):
        self.items = []
    def push(self, item):
        self.items.append(item)
    def replace_at(self, index, item):
        self.items[index] = item


def render(item):
    console = Console(record=True, width=120)
    console.print(item)
    return console.export_text()


def setup_adapter():
    narration = RecordingNarration()
    rail, header, footer = RunStateRail(), Header(), Footer()
    return EventAdapter(narration, rail, header, footer), narration, rail, header, footer


def fixture():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines()]


def test_real_recorded_fixture_replays_to_exact_card_sequence():
    adapter, narration, rail, header, footer = setup_adapter()
    events = fixture()
    for event in events:
        assert from_dict(event).TYPE == event["type"]
        assert adapter.apply(event)
    assert [entry.kind for entry in adapter.state.cards] == [
        "run", "goal", "thought", "plan", "command", "thought", "command",
        "command", "verify", "memory", "answer",
    ]
    state = adapter.state
    assert state.last_seq == 17 and state.status == "ok" and state.phase == "DONE"
    assert state.steps_total == state.steps_done == 2
    assert state.tools == ["bash"] and rail.state.tools == ["bash"]
    assert rail.steps_done == 2 and rail.steps_total == 2
    assert header.phase == "DONE" and footer.live is False
    cards = [render(narration.items[entry.index]) for entry in state.cards]
    assert "Correct the probe" in cards[3] and "Run a failing probe" not in cards[3]
    assert "exit 3" in cards[4] and "fixed" in cards[6]
    assert "✓" in cards[8] and "Verification passed" in cards[-1]


def test_command_mutates_in_place_and_failure_replan_is_visible():
    adapter, narration, _, header, _ = setup_adapter()
    events = fixture()
    for event in events[:4]: adapter.apply(event)
    entry = adapter.state.commands["1"]
    count = len(adapter.state.cards)
    assert "▍" in render(narration.items[entry.index])
    adapter.apply(events[4])
    assert len(adapter.state.cards) == count
    assert "exit 3" in render(narration.items[entry.index])
    assert "▍" not in render(narration.items[entry.index])
    assert adapter.state.plan.model.steps[0].status == "fail"
    adapter.apply(events[5]); adapter.apply(events[6])
    assert header.phase == "DRAFT"
    assert adapter.state.plan.model.steps[0].title == "Correct the probe"


def test_duplicate_and_unknown_events_are_safe(caplog):
    adapter, narration, _, _, _ = setup_adapter()
    event = fixture()[0]
    assert adapter.apply(event)
    assert not adapter.apply(event)
    count = len(narration.items)
    with caplog.at_level("DEBUG", logger="arcen.tui.adapter"):
        assert not adapter.apply({"seq": 2, "type": "harness.future"})
    assert "harness.future" in caplog.text
    assert not adapter.apply({"seq": 2, "type": "answer", "text": "overlap"})
    assert len(narration.items) == count
    assert adapter.state.last_seq == 2


def test_usage_updates_rail_without_narration_card():
    adapter, narration, rail, _, _ = setup_adapter()
    adapter.apply({"seq": 1, "type": "run.start", "run_id": "r", "goal": "g"})
    count = len(narration.items)
    adapter.apply({"seq": 2, "type": "usage", "tokens": {"input": 20, "output": 7}, "cost_usd": 0.12})
    assert len(narration.items) == count
    assert rail.state.tokens == 27 and rail.state.cost_usd == 0.12


def test_all_frozen_types_have_a_handler():
    adapter, *_ = setup_adapter()
    assert set(adapter.handlers) == set(EVENT_TYPES)


def test_failure_subagent_diff_and_terminal_error():
    adapter, narration, _, header, footer = setup_adapter()
    for event in [
        {"type": "run.start", "run_id": "r", "goal": "g"},
        {"type": "spawn", "name": "child", "task": "find", "parent": "DRAFT", "depth": 1},
        {"type": "spawn.done", "name": "child", "ok": False, "calls": 1, "duration_s": 2},
        {"type": "file.diff", "path": "a.py", "patch": "-old\n+new"},
        {"type": "verify.start", "target": "test"},
        {"type": "step.fail", "step": 1, "reason": "broken", "retry": 1},
        {"type": "run.error", "code": "PROVIDER_ERROR", "message": "unauthorized"},
    ]: adapter.apply(event)
    kinds = [entry.kind for entry in adapter.state.cards]
    assert kinds == ["run", "goal", "spawn", "spawn.done", "diff", "verify", "error"]
    assert "broken" in render(narration.items[adapter.state.verification.index])
    assert "unauthorized" in render(narration.items[adapter.state.cards[-1].index])
    assert header.phase == "ERROR" and not footer.live and adapter.state.status == "failed"


def test_multiple_turns_reset_run_data_but_keep_history_and_seq():
    adapter, narration, rail, _, _ = setup_adapter()
    for e in fixture(): adapter.apply(e)
    old = list(narration.items)
    adapter.apply({"seq": 18, "type": "run.start", "run_id": "next", "goal": "another"})
    assert narration.items[:len(old)] == old
    assert adapter.state.last_seq == 18 and adapter.state.run_id == "next"
    assert adapter.state.plan is None and adapter.state.tools == []
    assert rail.state.tokens == 0 and rail.state.steps_total == 0


def test_registry_and_extension_event_are_data_driven():
    registry = CardRegistry()
    registry.register("plugin", lambda text: Text("custom " + text))
    adapter, narration, _, _, _ = setup_adapter()
    adapter.registry = registry
    adapter.register_handler("harness.propose", lambda event: adapter._append(
        "plugin", registry.create("plugin", event["text"])))
    assert adapter.apply({"type": "harness.propose", "seq": 1, "text": "candidate"})
    assert "custom candidate" in render(narration.items[-1])


async def test_real_widgets_receive_replayed_events():
    from textual.app import App, ComposeResult
    from textual.containers import Vertical

    from arcen.tui.views.stream import STREAM_CSS, BackToLive, Narration, StreamView

    class Harness(App):
        CSS = "#stream-column { height: 1fr; }" + STREAM_CSS
        def compose(self) -> ComposeResult:
            with Vertical(id="stream-column"):
                with StreamView(id="stream"):
                    yield Narration(id="narration")
                yield BackToLive(" ↓ back to live ", id="back-to-live")
            yield RunStateRail(id="rail")

    app = Harness()
    async with app.run_test(size=(100, 35)) as pilot:
        narration = app.query_one(Narration)
        narration.bind_stream(app.query_one(StreamView))
        adapter = EventAdapter(narration, app.query_one(RunStateRail))
        for event in fixture(): adapter.apply(event)
        await pilot.pause()
        assert adapter.state.status == "ok"
        assert "Verification passed" in render(narration.items[adapter.state.cards[-1].index])
        assert app.query_one(RunStateRail).state.steps_done == 2


def test_recorded_offline_turn_replays_refusal_without_inventing_tools():
    adapter, narration, rail, header, footer = setup_adapter()
    path = FIXTURE.with_name("server-offline.jsonl")
    for line in path.read_text().splitlines():
        event = json.loads(line)
        assert from_dict(event).TYPE == event["type"]
        adapter.apply(event)
    assert [e.kind for e in adapter.state.cards] == ["run", "goal", "thought", "answer"]
    assert "I need a model provider" in render(narration.items[adapter.state.cards[-1].index])
    assert rail.state.tools == [] and rail.state.steps_total == 0
    assert header.phase == "DONE" and not footer.live


def test_replay_demo_bundle_matches_recorded_fixture():
    from arcen.tui.replay_demo import recorded_events

    assert recorded_events() == fixture()


def test_replan_reason_is_visible_in_updated_plan():
    adapter, narration, *_ = setup_adapter()
    for event in fixture()[:7]:
        adapter.apply(event)
    assert "step 1 (bash) failed" in render(narration.items[adapter.state.plan.index])


def test_failed_step_shows_amber_replan_until_corrected():
    adapter, _, rail, _, _ = setup_adapter()
    for event in fixture()[:5]:
        adapter.apply(event)
    assert adapter.state.replanning is True and rail.state.replanning is True
    timeline = rail._phase_timeline()
    assert "DRAFT · re-plan" in timeline.plain
    assert any("#FBBF24" in str(span.style).upper() for span in timeline.spans)
    adapter.apply(fixture()[5])
    adapter.apply(fixture()[6])
    assert not adapter.state.replanning and not rail.state.replanning
    assert "re-plan" not in rail._phase_timeline().plain


def test_repeated_step_pass_without_checks_keeps_verification_safe():
    adapter, _, _, _, _ = setup_adapter()
    adapter.apply({"type": "verify.start", "target": "t"})
    adapter.apply({"type": "step.pass", "step": 1, "checks": ["one"]})
    adapter.apply({"type": "step.pass", "step": 1, "checks": []})
    assert adapter.state.verification.model.checks[0].status == "pass"
