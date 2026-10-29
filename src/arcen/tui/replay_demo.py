"""Offline replay of an actual recorded server turn through the TUI-10 adapter.

The bundled fixture was recorded from ``run_turn`` with a deterministic mock
provider and real benign bash calls, then timestamps were anonymized. No server
or credentials are required. This is a scripted replay, not live transport.
"""
from __future__ import annotations

import asyncio
import json
from importlib.resources import files

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical

from arcen.tui.adapter import EventAdapter
from arcen.tui.app import ArcenApp, Footer, Header
from arcen.tui.views.rail import RunStateRail
from arcen.tui.views.stream import BackToLive, Narration, StreamView


def recorded_events() -> list[dict]:
    content = files("arcen.tui").joinpath("fixtures/server-replan.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in content.splitlines() if line.strip()]


class ReplayDemo(ArcenApp):
    """Recorded replan scenario driven entirely by :class:`EventAdapter`."""

    def __init__(self, headless_mode: bool = False):
        super().__init__(headless_mode=headless_mode)
        self._auto_exit = False
        self.finished = asyncio.Event()

    def compose(self) -> ComposeResult:
        self.header = Header(session="recorded", model="mock provider", quarantine="recorded · offline")
        self.footer = Footer()
        self.narration = Narration()
        self.rail = RunStateRail(id="rail")
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
        self.narration.bind_stream(self.query_one(StreamView))
        self.adapter = EventAdapter(self.narration, self.rail, self.header, self.footer)
        asyncio.create_task(self.driver())

    async def driver(self) -> None:
        for event in recorded_events():
            await asyncio.sleep(0.55)
            self.adapter.apply(event)
        self.finished.set()
        if self.headless_mode:
            await asyncio.sleep(0.2)
            self.exit()
