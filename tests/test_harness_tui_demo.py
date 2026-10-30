"""Offline, clearly simulated Harness² TUI; no provider, Docker or adoption."""

from __future__ import annotations

from io import StringIO

import pytest

pytest.importorskip("textual")

from rich.console import Console

from arcen.harness.progress import _validate
from arcen.tui.harness_demo import HarnessDemo, simulated_progress
from arcen.tui.harness_progress import HarnessProgressView


class RecordingNarration:
    def __init__(self):
        self.items = []

    def push(self, item):
        self.items.append(item)


def rendered(items) -> str:
    output = StringIO()
    console = Console(file=output, width=120, color_system=None)
    for item in items:
        console.print(item)
    return output.getvalue()


def test_simulated_events_follow_local_schema_and_show_non_authoritative_review():
    narration = RecordingNarration()
    adapter = HarnessProgressView(narration)
    for event in simulated_progress():
        _validate(event)
        assert adapter.apply(event)
    text = rendered(narration.items)
    assert adapter.accepted == 9
    assert "pending" in text and "uncalibrated" in text.lower()
    assert "not an adoption decision" in text and "No candidate was adopted" in text
    assert "bbbbbbbbbbbb" in text and "cccccccccccc" in text


def test_invalid_duplicate_and_private_extra_fields_never_render():
    narration = RecordingNarration()
    adapter = HarnessProgressView(narration)
    event = simulated_progress()[0]
    assert adapter.apply(event) and not adapter.apply(event)
    before = len(narration.items)
    for bad in (
        None,
        [],
        {"seq": 2, "type": ["harness.policy"]},
        {"seq": 2, "type": "harness.policy", "candidate_id": "x", "decision": "reviewed"},
        {"seq": 2, "type": "harness.campaign.start", "candidate_count": 1, "task": "private"},
        {
            "seq": 2,
            "type": "harness.judge",
            "candidate_id": "c" * 64,
            "winner": [],
            "confidence": 0.5,
        },
        {"seq": True, "type": "harness.campaign.start", "candidate_count": 1},
    ):
        assert not adapter.apply(bad)
    assert len(narration.items) == before and adapter.last_seq == 1
    assert "private" not in rendered(narration.items)


async def test_demo_completes_headlessly_without_network_or_external_calls(monkeypatch):
    import socket

    def blocked(*args, **kwargs):
        pytest.fail("simulation attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    app = HarnessDemo(headless_mode=True, interval=0.01)
    async with app.run_test(headless=True, size=(132, 40)):
        await __import__("asyncio").wait_for(app.finished.wait(), 10)
        assert app.progress.accepted == 9
        text = rendered(app.narration.items)
        assert "SIMULATED" in text and "no real execution" in text
        assert "No candidate was adopted" in text
        assert app.header.phase == "DEMO"
        footer = rendered([app.footer.render()])
        assert "SIMULATED" in footer and "LIVE" not in footer
        assert "no actions were run" in footer
