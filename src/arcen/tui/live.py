"""Live server integration for the redesigned shell (TUI-11).

The existing ArcenClient owns NDJSON framing and 409 recovery; this layer
resumes on unexpected EOF/errors, announces gaps, and feeds the adapter. It
never starts a run merely by opening a session.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import subprocess
import tempfile
import uuid
from functools import partial
from pathlib import Path
from typing import ClassVar

import httpx
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, TextArea

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
from arcen.tui.composer import COMMANDS, Composer
from arcen.tui.interrupt import InterruptScreen
from arcen.tui.modals import HelpScreen, InfoScreen
from arcen.tui.sessions import SessionsScreen
from arcen.tui.theme import TOKENS
from arcen.tui.views.rail import RunStateRail
from arcen.tui.views.stream import BackToLive, Narration, StreamView

RETRY_SECONDS = 1.0


class LiveApp(ArcenApp):
    """Server-backed shell; input and other parity features arrive later."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+c", "interrupt", "Interrupt", priority=True),
        Binding("ctrl+g", "external_editor", "Editor", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+b", "sessions", "Sessions", priority=True),
        Binding("ctrl+r", "resume", "Resume", priority=True),
        Binding("ctrl+n", "new_chat", "New session", priority=True),
        Binding("ctrl+o", "show_config", "Configuration", priority=True),
        Binding("ctrl+s", "show_sandbox", "Sandbox", priority=True),
        Binding("f1", "show_help", "Help", priority=True),
        Binding("pageup", "scroll_narration_up", "Scroll up", priority=True),
        Binding("pagedown", "scroll_narration_down", "Scroll down", priority=True),
        Binding("ctrl+end", "narration_live", "Back to live", priority=True),
    ]

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
        self._submit_task: asyncio.Task | None = None
        self._session_task: asyncio.Task | None = None
        self._session_lock = asyncio.Lock()
        self._stream_started = asyncio.Event()
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
                yield Static("Enter submit  ·  Ctrl+T new line  ·  Tab complete", id="composer-hint")
                yield Composer(id="composer")
            yield self.rail
        yield self.footer

    def on_mount(self) -> None:
        super().on_mount()
        self.narration.bind_stream(self.query_one(StreamView))
        self.adapter = EventAdapter(self.narration, self.rail, self.header, self.footer)
        self.query_one(Composer).focus()
        self._reader_task = asyncio.create_task(self._boot_and_stream())

    async def on_unmount(self) -> None:
        self._closing = True
        if self._session_task:
            self._session_task.cancel()
            await asyncio.gather(self._session_task, return_exceptions=True)
        if self._submit_task:
            self._submit_task.cancel()
            await asyncio.gather(self._submit_task, return_exceptions=True)
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._owns_client:
            await self.client.aclose()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if not isinstance(event.text_area, Composer):
            return
        text = event.text_area.text.strip()
        matches = [f"{cmd}  {desc}" for cmd, desc in COMMANDS.items() if cmd.startswith(text)] if text.startswith("/") else []
        hint = "  ·  ".join(matches) if matches else "Enter submit  ·  Ctrl+T new line  ·  Tab complete"
        self.query_one("#composer-hint", Static).update(hint)

    def on_composer_submitted(self, event: Composer.Submitted) -> None:
        value = event.value.strip()
        if not value:
            return
        if value.startswith("/"):
            self._slash(value)
            return
        if self.busy or self.adapter.state.status == "running":
            self._notice("a turn is already running; draft preserved")
            return
        if not self.online:
            self._notice("server offline; draft preserved")
            return
        self.busy = True
        self._submit_task = asyncio.create_task(self._submit_goal(value))

    def _slash(self, value: str) -> None:
        command = value.split()[0].lower()
        if command == "/help":
            self._notice("Commands: " + ", ".join(COMMANDS) + " · Enter submit · Ctrl+T newline", warning=False)
        elif command == "/clear":
            self.narration.items.clear()
            self.narration._sync()
            # Keep adapter card indexes valid; cleared entries must not be mutated.
            self.adapter.state.cards.clear()
            self.adapter.state.plan = self.adapter.state.verification = None
            self.adapter.state.commands.clear()
        elif command == "/sessions":
            self.action_sessions()
        elif command == "/new":
            self.action_new_chat()
        elif command == "/config":
            self.action_show_config()
        elif command == "/sandbox":
            self.action_show_sandbox()
        elif command in COMMANDS:
            self._notice(f"{command} is not available yet")
            return
        else:
            self._notice(f"unknown command {command}; use /help")
            return
        self.query_one(Composer).load_text("")

    def action_show_help(self) -> None:
        if isinstance(self.screen, HelpScreen):
            self.screen.dismiss(None)
        elif len(self.screen_stack) == 1:
            self.push_screen(HelpScreen())

    def action_scroll_narration_up(self) -> None:
        if len(self.screen_stack) == 1:
            self.query_one(StreamView).scroll_page_up(animate=False)

    def action_scroll_narration_down(self) -> None:
        if len(self.screen_stack) == 1:
            self.query_one(StreamView).scroll_page_down(animate=False)

    def action_narration_live(self) -> None:
        if len(self.screen_stack) == 1:
            self.query_one(StreamView).scroll_end(animate=False)

    def action_show_config(self) -> None:
        if not isinstance(self.screen, InfoScreen):
            self.push_screen(InfoScreen(self.client))

    def action_show_sandbox(self) -> None:
        if not isinstance(self.screen, InfoScreen):
            self.push_screen(InfoScreen(self.client, sandbox_only=True))

    def _session_operation_allowed(self) -> bool:
        if self.busy or self.adapter.state.status == "running":
            self._notice("finish or interrupt the current run before switching sessions")
            return False
        return True

    def _start_session_task(self, coro) -> None:
        if self._session_task is not None and not self._session_task.done():
            coro.close()
            return
        self._session_task = asyncio.create_task(coro)

    def action_sessions(self) -> None:
        if isinstance(self.screen, SessionsScreen):
            self.screen.dismiss(None)
            return
        if self._session_operation_allowed():
            self._start_session_task(self._show_sessions())

    async def _show_sessions(self) -> None:
        try:
            sessions = await self.client.list_sessions()
        except (ArcenAPIError, httpx.HTTPError, OSError) as exc:
            self._notice(f"sessions unavailable: {exc}")
            return
        if self._session_operation_allowed():
            self.push_screen(SessionsScreen(sessions, self.session_id), self._session_selected)

    def _session_selected(self, session_id: str | None) -> None:
        if session_id and self._session_operation_allowed():
            self._start_session_task(self._open_session(session_id))

    def action_resume(self) -> None:
        if self._session_operation_allowed():
            self._start_session_task(self._resume_latest())

    async def _resume_latest(self) -> None:
        try:
            sessions = await self.client.list_sessions()
        except (ArcenAPIError, httpx.HTTPError, OSError) as exc:
            self._notice(f"sessions unavailable: {exc}")
            return
        if not sessions or not sessions[0].get("id"):
            self._notice("no saved sessions to resume")
            return
        await self._open_session(str(sessions[0]["id"]))

    def action_new_chat(self) -> None:
        if self._session_operation_allowed():
            self._start_session_task(self._replace_session(new_session_id(), []))

    async def _open_session(self, session_id: str) -> None:
        try:
            events = await self.client.session_events(session_id)
        except (ArcenAPIError, httpx.HTTPError, OSError) as exc:
            self._notice(f"session replay unavailable: {exc}")
            return
        await self._replace_session(session_id, events)

    async def _replace_session(self, session_id: str, events: list[dict]) -> None:
        async with self._session_lock:
            if not self._session_operation_allowed():
                return
            if self._reader_task:
                self._reader_task.cancel()
                await asyncio.gather(self._reader_task, return_exceptions=True)
            self.session_id = session_id
            self.run_id = None
            self.header.update_meta(session=session_id[:8])
            self.header.set_phase("IDLE")
            self.footer.set_live(False)
            self.rail.apply_state({"steps_done": 0, "steps_total": 0, "phase_idx": 0,
                                   "tokens": 0, "cost_usd": 0.0, "tools": [], "replanning": False})
            self.narration.items.clear()
            self.narration._sync()
            self.adapter = EventAdapter(self.narration, self.rail, self.header, self.footer)
            for event in events:
                self._apply_event(event)
            self._stream_started.clear()
            self._reader_task = asyncio.create_task(self._stream_loop())

    async def _submit_goal(self, goal: str) -> None:
        try:
            if self._reader_task is None or self._reader_task.done():
                self._stream_started.clear()
                self._reader_task = asyncio.create_task(self._stream_loop())
            await asyncio.wait_for(self._stream_started.wait(), timeout=6.0)
            await asyncio.sleep(0)  # allow the held stream request to start first
            run = await self.client.submit_run(goal, self.session_id)
            self.run_id = str(run.get("run_id", ""))
            composer = self.query_one(Composer)
            if composer.text.strip() == goal:
                composer.load_text("")
        except (ArcenAPIError, httpx.HTTPError, OSError, TimeoutError) as exc:
            self.busy = False
            detail = str(exc) or "stream could not connect in time"
            self.narration.push(error_card("SUBMIT", detail, "Your draft was preserved."))

    def action_external_editor(self) -> None:
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if not editor:
            self._notice("set $VISUAL or $EDITOR to use an external editor")
            return
        composer = self.query_one(Composer)
        path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", delete=False) as f:
                path = Path(f.name)
                f.write(composer.text)
            with self.suspend():
                result = subprocess.run([*shlex.split(editor), str(path)], check=False)
            if result.returncode == 0:
                composer.load_text(path.read_text(encoding="utf-8"))
            else:
                self._notice(f"editor exited {result.returncode}; draft preserved")
        except (OSError, ValueError) as exc:
            self._notice(f"editor unavailable: {exc}; draft preserved")
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
            composer.focus()

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
        applied = self.adapter.apply(event)
        if applied and event.get("type") in TERMINAL_EVENTS:
            self.busy = False
        return applied

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
                if effective == "unavailable":
                    self.header.update_meta(quarantine="tools blocked")
                    self._notice(f"sandbox unavailable: {sandbox.get('reason') or effective}")
                elif sandbox.get("degraded"):
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
                self._stream_started.set()
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
