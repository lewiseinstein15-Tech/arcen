"""Clearly labelled, offline simulated Harness² progress demo.

No campaign, model, sandbox, approval, database or ref is touched. The data is
fabricated for layout demonstration and is not evidence of real probe results.
"""

from __future__ import annotations

import asyncio

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical

from arcen.stream.emitter import StreamEmitter
from arcen.stream.events_v2 import ProgressStream
from arcen.tui.adapter import EventAdapter
from arcen.tui.app import ArcenApp, Footer, Header
from arcen.tui.cards.goal import goal_card
from arcen.tui.harness_progress import register_v2_progress
from arcen.tui.theme import TOKENS
from arcen.tui.views.rail import RunStateRail
from arcen.tui.views.stream import BackToLive, Narration, StreamView

_CANDIDATE = "c" * 64
_BASELINE = "b" * 64
_REVIEW = "d" * 32


def simulated_progress() -> tuple[dict, ...]:
    """Deterministic fabricated events matching the local progress schema."""
    return (
        {"seq": 1, "type": "harness.campaign.start", "candidate_count": 1},
        {"seq": 2, "type": "harness.policy", "candidate_id": _CANDIDATE, "decision": "reviewed"},
        {"seq": 3, "type": "harness.probe.start", "candidate_id": _BASELINE, "role": "reference"},
        {
            "seq": 4,
            "type": "harness.probe.done",
            "candidate_id": _BASELINE,
            "role": "reference",
            "status": "ok",
        },
        {"seq": 5, "type": "harness.probe.start", "candidate_id": _CANDIDATE, "role": "candidate"},
        {
            "seq": 6,
            "type": "harness.probe.done",
            "candidate_id": _CANDIDATE,
            "role": "candidate",
            "status": "ok",
        },
        {
            "seq": 7,
            "type": "harness.judge",
            "candidate_id": _CANDIDATE,
            "winner": "tie",
            "confidence": 0.5,
        },
        {
            "seq": 8,
            "type": "harness.review",
            "candidate_id": _CANDIDATE,
            "review_id": _REVIEW,
            "state": "pending",
        },
        {
            "seq": 9,
            "type": "harness.campaign.done",
            "status": "completed",
            "reason": None,
            "completed": 1,
        },
    )


class SimulationFooter(Footer):
    """Avoid presenting simulated progress as a live connection or control."""

    def render(self) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        grid.add_row(
            Text("Offline simulation · no actions were run", style=TOKENS["muted"]),
            Text("● SIMULATED", style=TOKENS["amber"]),
        )
        return Panel(
            grid, box=box.SQUARE, border_style=TOKENS["line"], style=TOKENS["panel"], padding=(0, 1)
        )


class HarnessDemo(ArcenApp):
    """Simulated campaign narrated through the existing TUI shell."""

    def __init__(self, headless_mode: bool = False, *, interval: float = 0.55):
        super().__init__(headless_mode=headless_mode)
        self._auto_exit = False
        self.interval = interval
        self.finished = asyncio.Event()

    def compose(self) -> ComposeResult:
        self.header = Header(
            session="DEMO · simulated",
            model="offline · no provider",
            quarantine="simulation · no sandbox",
        )
        self.footer = SimulationFooter(live=False)
        self.narration = Narration()
        self.rail = RunStateRail(id="rail", harness="demo · no adoption", network="offline")
        yield self.header
        with Horizontal(id="shell"):
            with Vertical(id="stream-column"):
                with StreamView(id="stream"):
                    yield self.narration
                yield BackToLive(" ↓ back to live ", id="back-to-live")
            yield self.rail
        yield self.footer

    def on_mount(self) -> None:
        super().on_mount()
        self.header.set_phase("DEMO")
        self.narration.bind_stream(self.query_one(StreamView))
        self.narration.push(
            goal_card("SIMULATED Harness² campaign · no real execution or approval")
        )
        self.adapter = EventAdapter(self.narration, self.rail)
        self.progress = register_v2_progress(self.adapter)
        self.demo_emitter = StreamEmitter("offline-simulated-harness")
        self.demo_emitter.subscribe(self.adapter.apply)
        self.demo_progress = ProgressStream(self.demo_emitter)
        asyncio.create_task(self.driver())

    async def driver(self) -> None:
        for event in simulated_progress():
            await asyncio.sleep(self.interval)
            self.demo_progress(event)
        self.finished.set()
        if self.headless_mode:
            await asyncio.sleep(0.2)
            self.exit()
