"""ARCEN terminal application — a Textual client for ``arcen serve``.

Layout: a one-line status bar over a sessions sidebar and the live NDJSON
transcript, with a goal composer pinned to the bottom. The turn flow mirrors
the web UI exactly: mint a UUID session, open the held /api/stream first,
POST /api/run, render the frozen 17 events until run.done/run.error.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import ListView

from arcen.tui._legacy.render import error_banner, welcome
from arcen.tui._legacy.widgets import (
    Composer,
    ConfigScreen,
    EventLog,
    HelpScreen,
    SessionSidebar,
    StatusBar,
)
from arcen.tui.client import (
    DEFAULT_BASE_URL,
    TERMINAL_EVENTS,
    ArcenAPIError,
    ArcenClient,
    new_session_id,
)

HEALTH_INTERVAL = 5.0  # seconds between liveness probes


class ArcenTUI(App):
    """The full-screen ARCEN client."""

    TITLE = "ARCEN"
    SUB_TITLE = "Agentic reasoning. Code. Engineer."

    CSS = """
    Screen { layout: vertical; background: #0A0B0D; }
    #statusbar {
        dock: top; height: 1; padding: 0 1;
        background: #121418; color: #E6E8EB;
    }
    #body { height: 1fr; }
    #sidebar {
        width: 34; min-width: 22; border: solid #2A2E35;
        background: #0F1114; padding: 0 1;
    }
    #sidebar.hidden { display: none; }
    #main { width: 1fr; }
    #event-log {
        height: 1fr; border: solid #2A2E35; padding: 0 1; background: #0A0B0D;
    }
    #composer { height: auto; border: solid #FF6B5C; background: #121418; }
    HelpScreen, ConfigScreen { align: center middle; }
    #help-modal, #config-modal {
        width: 82; height: 80%; border: thick #FF6B5C;
        background: #0A0B0D; padding: 1 2; overflow: auto;
    }
    """

    # Ctrl-prefixed so the composer can still receive every printable key
    # (a goal contains n/s/c/h/x/… letters) — single-key bindings would be
    # swallowed by the focused Input. Esc returns focus to the composer.
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+n", "new_chat", "New chat"),
        Binding("ctrl+b", "toggle_sidebar", "Sessions bar"),
        Binding("ctrl+r", "refresh_sessions", "Refresh"),
        Binding("ctrl+o", "show_config", "Config/options"),
        Binding("ctrl+x", "interrupt", "Stop run"),
        Binding("ctrl+l", "clear_log", "Clear log"),
        Binding("ctrl+h,f1", "help", "Help"),
        Binding("escape", "focus_composer", "Focus composer"),
    ]

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session_id: str | None = None,
        client: ArcenClient | None = None,
    ) -> None:
        super().__init__()
        self._client = client or ArcenClient(base_url)
        self._owns_client = client is None
        self.base_url = base_url if client is None else client.base_url
        self.session_id = session_id or new_session_id()
        self.run_id: str | None = None
        self.last_seq: int | None = None
        self.online = False
        self.busy = False
        self._sandbox: dict | None = None

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield StatusBar()
        with Horizontal(id="body"):
            yield SessionSidebar()
            with Vertical(id="main"):
                yield EventLog()
                yield Composer()

    async def on_mount(self) -> None:
        self.query_one(EventLog).write_renderable(welcome(self.base_url))
        self.query_one(Composer).focus()
        self.query_one(StatusBar).refresh_state(
            online=False, url=self.base_url, session_id=self.session_id,
            busy=False, sandbox=None,
        )
        self.health_watch()
        self.refresh_sessions()

    async def on_unmount(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------ widgets

    @property
    def event_log(self) -> EventLog:
        return self.query_one(EventLog)

    @property
    def composer(self) -> Composer:
        return self.query_one(Composer)

    @property
    def sidebar(self) -> SessionSidebar:
        return self.query_one(SessionSidebar)

    @property
    def statusbar(self) -> StatusBar:
        return self.query_one(StatusBar)

    def _refresh_status(self) -> None:
        self.statusbar.refresh_state(
            online=self.online, url=self.base_url, session_id=self.session_id,
            busy=self.busy, sandbox=self._sandbox,
        )

    # ------------------------------------------------------------------ background work

    @work(exclusive=False, name="health", group="health")
    async def health_watch(self) -> None:
        """Poll liveness + sandbox state; keeps the status bar truthful."""
        while True:
            self.online = await self._client.health()
            if self.online and self._sandbox is None:
                try:
                    self._sandbox = await self._client.sandbox_status()
                except ArcenAPIError:
                    self._sandbox = None
            self._refresh_status()
            await asyncio.sleep(HEALTH_INTERVAL)

    @work(exclusive=True, name="sessions", group="sessions")
    async def refresh_sessions(self) -> None:
        if not self.online:
            await self.sidebar.show_offline()
            return
        try:
            sessions = await self._client.list_sessions()
        except ArcenAPIError as exc:
            self.event_log.write_renderable(error_banner(f"sessions unavailable: {exc}"))
            return
        await self.sidebar.populate(sessions, self.session_id)

    @work(exclusive=True, name="turn", group="turn")
    async def run_turn(self, goal: str) -> None:
        """Open the held stream first, then start the turn (web UI ordering)."""
        if self.busy:
            self.notify("a turn is already running", severity="warning")
            return
        if not self.online:
            self.event_log.write_renderable(
                error_banner(
                    f"Cannot reach the ARCEN server at {self.base_url}. "
                    "Start one with `arcen serve`, or rerun without --no-serve."
                )
            )
            return

        self.busy = True
        self.run_id = None
        self.composer.set_busy(True)
        self._refresh_status()
        pump = asyncio.create_task(self._pump_stream())
        try:
            run = await self._client.submit_run(goal, self.session_id)
            self.run_id = str(run.get("run_id", ""))
            await pump
        except ArcenAPIError as exc:
            pump.cancel()
            self.event_log.write_renderable(error_banner(str(exc)))
        except Exception as exc:  # noqa: BLE001 — the TUI itself must not crash
            pump.cancel()
            self.event_log.write_renderable(error_banner(f"unexpected failure: {exc}"))
        finally:
            self.busy = False
            self.run_id = None
            self.composer.set_busy(False)
            self.composer.focus()
            self._refresh_status()
            self.refresh_sessions()

    async def _pump_stream(self) -> None:
        """Consume NDJSON until stream.done; every event lands in the log."""
        async for event in self._client.stream(self.session_id, self.last_seq):
            seq = int(event.get("seq", 0))
            if self.last_seq is not None and seq <= self.last_seq:
                continue  # replay overlap after a Last-Event-ID reconnect
            self.last_seq = seq
            self.event_log.write_event(event)
            if event.get("type") in TERMINAL_EVENTS:
                self.event_log.scroll_end(animate=False)

    # ------------------------------------------------------------------ messages

    def on_input_submitted(self, message: Composer.Submitted) -> None:
        goal = message.value.strip()
        if not goal:
            return
        self.composer.clear()
        self.run_turn(goal)

    async def on_list_view_selected(self, message: ListView.Selected) -> None:
        item_id = getattr(message.item, "id", None) or ""
        if not item_id.startswith("session-") or item_id == "session-empty":
            return
        sid = item_id.removeprefix("session-")
        await self._open_session(sid)

    async def _open_session(self, sid: str) -> None:
        if self.busy:
            self.notify("finish or stop the current turn first", severity="warning")
            return
        try:
            events = await self._client.session_events(sid)
        except ArcenAPIError as exc:
            self.event_log.write_renderable(error_banner(str(exc)))
            return
        self.session_id = sid
        self.last_seq = max((int(e.get("seq", 0)) for e in events if "seq" in e), default=None)
        self.event_log.clear()
        self.event_log.border_title = f"ARCEN — session {sid[:8]}…"
        if not events:
            self.event_log.write_renderable(error_banner("session exists but has no events yet"))
        for event in events:
            self.event_log.write_event(event)
        self._refresh_status()
        self.refresh_sessions()
        self.composer.focus()

    # ------------------------------------------------------------------ keybindings

    def action_new_chat(self) -> None:
        if self.busy:
            self.notify("finish or stop the current turn first", severity="warning")
            return
        self.session_id = new_session_id()
        self.last_seq = None
        self.run_id = None
        self.event_log.clear()
        self.event_log.border_title = EventLog.BORDER_TITLE
        self.event_log.write_renderable(welcome(self.base_url))
        self._refresh_status()
        self.refresh_sessions()
        self.composer.focus()

    def action_toggle_sidebar(self) -> None:
        self.sidebar.toggle_class("hidden")

    def action_focus_composer(self) -> None:
        self.composer.focus()

    def action_clear_log(self) -> None:
        self.event_log.clear()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_show_config(self) -> None:
        self.push_screen(ConfigScreen(self._client))

    @work(exclusive=False, name="interrupt", group="interrupt")
    async def action_interrupt(self) -> None:
        if not self.run_id:
            self.notify("no run to interrupt", severity="information")
            return
        try:
            await self._client.interrupt(self.run_id)
            self.notify(f"interrupt requested for {self.run_id}")
        except ArcenAPIError as exc:
            self.event_log.write_renderable(error_banner(str(exc)))


# ------------------------------------------------------------------ CLI entry


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arcen-tui",
        description=(
            "Terminal client for the ARCEN stream server. Starts and manages a "
            "local server automatically unless one is already running."
        ),
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("ARCEN_SERVER_URL", DEFAULT_BASE_URL),
        help=f"ARCEN server base URL (default: {DEFAULT_BASE_URL}, env ARCEN_SERVER_URL)",
    )
    parser.add_argument("--session", default=None, help="resume an existing session UUID")
    parser.add_argument(
        "--no-serve",
        action="store_true",
        help="never spawn a managed server; only attach to an already-running one",
    )
    args = parser.parse_args(argv)
    if args.session:
        try:
            uuid.UUID(args.session)
        except ValueError:
            parser.error("--session must be a valid UUID")

    # One-command UX: attach when a server exists, otherwise spawn and own one.
    from arcen.tui.launcher import ensure_server

    effective_url, manager = ensure_server(args.url, serve=not args.no_serve)
    try:
        app = ArcenTUI(base_url=effective_url, session_id=args.session)
        app.run()
    finally:
        if manager is not None:
            manager.stop()
    return 0
