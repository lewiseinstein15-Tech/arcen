"""Live server integration for the redesigned shell (TUI-11).

The existing ArcenClient owns NDJSON framing and 409 recovery; this layer
resumes on unexpected EOF/errors, announces gaps, and feeds the adapter. It
never starts a run merely by opening a session.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from functools import partial
from typing import ClassVar

import httpx
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical

from arcen.tui.adapter import EventAdapter
from arcen.tui.app import ArcenApp, Footer, Header
from arcen.tui.cards.system import error_card
from arcen.tui.client import (
    DEFAULT_BASE_URL,
    TERMINAL_EVENTS,
    ArcenAPIError,
    ArcenClient,
    new_session_id,
)
from arcen.tui.interrupt import InterruptScreen
from arcen.tui.theme import TOKENS
from arcen.tui.views.rail import RunStateRail
from arcen.tui.views.stream import BackToLive, Narration, StreamView

RETRY_SECONDS = 1.0


class LiveApp(ArcenApp):
    """Server-backed shell; input and other parity features arrive later."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("ctrl+c", "interrupt", "Interrupt", priority=True)]

    def __init__(self, *, base_url: str = DEFAULT_BASE_URL, session_id: str | None = None,
                 client: ArcenClient | None = None, retry_seconds: float = RETRY_SECONDS):
        super().__init__()
        self._auto_exit = False
        self.client = client or ArcenClient(base_url)
        self._owns_client = client is None
        self.base_url = self.client.base_url
        self.session_id = session_id or new_session_id()
        self._restore_session = bool(session_id)
        self.retry_seconds = retry_seconds
        self.online = False
        self.busy = False
        self.run_id: str | None = None
        self._reader_task: asyncio.Task | None = None
        self._closing = False
        self._connection_message = ""

    def compose(self) -> ComposeResult:
        self.header = Header(session=self.session_id[:8], model="—", quarantine="connecting")
        self.footer = Footer(live=False)
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
        self._reader_task = asyncio.create_task(self._boot_and_stream())

    async def on_unmount(self) -> None:
        self._closing = True
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._owns_client:
            await self.client.aclose()

    def action_interrupt(self) -> None:
        if isinstance(self.screen, InterruptScreen):
            self.screen.dismiss(False)
            return
        run_id = self.adapter.state.run_id
        if not run_id or self.adapter.state.status != "running":
            self._notice("no active run to interrupt")
            return
        self.push_screen(InterruptScreen(run_id), partial(self._interrupt_confirmed, run_id))

    async def _interrupt_confirmed(self, run_id: str, confirmed: bool | None) -> None:
        if not confirmed:
            return
        if self.adapter.state.run_id != run_id or self.adapter.state.status != "running":
            self._notice("run already finished; no interrupt sent")
            return
        try:
            await self.client.interrupt(run_id)
        except (ArcenAPIError, httpx.HTTPError, OSError) as exc:
            self.narration.push(error_card("INTERRUPT", str(exc), "The run may still be active."))
        else:
            self._notice("interrupt requested; waiting for the current step to stop")

    def _notice(self, message: str, *, warning: bool = True) -> None:
        if message == self._connection_message:
            return
        self._connection_message = message
        self.narration.push(Text(" · " + message, style=TOKENS["amber" if warning else "muted"]))

    async def _boot_and_stream(self) -> None:
        if self._restore_session:
            try:
                for event in await self.client.session_events(self.session_id):
                    self._apply_event(event)
            except (ArcenAPIError, httpx.HTTPError, OSError) as exc:
                self._notice(f"session replay unavailable: {exc}")
        await self._stream_loop()

    def _apply_event(self, event: dict) -> bool:
        seq = event.get("seq")
        last = self.adapter.state.last_seq
        if isinstance(seq, int) and not isinstance(seq, bool) and seq > last + 1:
            self._notice(f"event gap: expected {last + 1}, received {seq}")
        return self.adapter.apply(event)

    async def _stream_loop(self) -> None:
        """Reconnect after an abnormal EOF; terminal events end this pump."""
        reconnecting = False
        while not self._closing:
            self.online = await self.client.health()
            if not self.online:
                self.header.update_meta(quarantine="offline")
                self._notice(f"offline: cannot reach {self.base_url}; retrying")
                reconnecting = True
                await asyncio.sleep(self.retry_seconds)
                continue
            try:
                sandbox = await self.client.sandbox_status()
            except (ArcenAPIError, httpx.HTTPError, OSError):
                self.header.update_meta(quarantine="connected · sandbox unknown")
            else:
                effective = str(sandbox.get("effective") or "unknown")
                self.rail.apply_state({"environment": {"sandbox": effective}})
                if sandbox.get("degraded"):
                    self.header.update_meta(quarantine=f"{effective} · degraded")
                    self._notice(f"sandbox degraded: {sandbox.get('reason') or effective}")
                else:
                    self.header.update_meta(quarantine=f"{effective} · connected")
            if reconnecting:
                self._notice("connection restored; resuming stream", warning=False)
            terminal = False
            try:
                after = self.adapter.state.last_seq or None
                # Disable client's internal retry loop so reconnections are
                # visible here; its framing and 409 behavior remain unchanged.
                async for event in self.client.stream(self.session_id, after, max_hold_retries=0):
                    if self._apply_event(event) and event.get("type") in TERMINAL_EVENTS:
                        terminal = True
                if terminal:
                    self.online = True
                    return
                self._notice("stream disconnected; reconnecting")
            except (ArcenAPIError, httpx.HTTPError, OSError) as exc:
                self._notice(f"stream disconnected; reconnecting: {exc}")
            reconnecting = True
            await asyncio.sleep(self.retry_seconds)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arcen-tui", description="ARCEN terminal client")
    parser.add_argument("--url", default=os.environ.get("ARCEN_SERVER_URL", DEFAULT_BASE_URL))
    parser.add_argument("--session", default=None)
    parser.add_argument("--no-serve", action="store_true")
    args = parser.parse_args(argv)
    if args.session:
        try:
            uuid.UUID(args.session)
        except ValueError:
            parser.error("--session must be a valid UUID")
    from arcen.tui.launcher import ensure_server

    url, manager = ensure_server(args.url, serve=not args.no_serve)
    try:
        LiveApp(base_url=url, session_id=args.session).run()
    finally:
        if manager is not None:
            manager.stop()
    return 0
