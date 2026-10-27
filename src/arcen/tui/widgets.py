"""Textual widgets for the ARCEN TUI.

Kept thin: all event-drawing logic lives in :mod:`arcen.tui.render` (pure
Rich, headless-testable); these classes only handle focus, selection and
screen plumbing.
"""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, RichLog, Static

from arcen.tui import render

# ---------------------------------------------------------------- event log


class EventLog(RichLog):
    """Scrollable NDJSON transcript; one Rich renderable per wire event."""

    BORDER_TITLE = "ARCEN — live stream"

    def __init__(self) -> None:
        super().__init__(id="event-log", highlight=False, markup=False, wrap=True)
        self.border_title = self.BORDER_TITLE

    def write_event(self, event: dict) -> None:
        self.write(render.render_event(event, self.size.width or 100))

    def write_renderable(self, renderable: object) -> None:
        self.write(renderable)


# ---------------------------------------------------------------- composer


class Composer(Input):
    """The goal input at the bottom of the screen."""

    def __init__(self) -> None:
        super().__init__(
            placeholder="Describe a task for ARCEN — Enter to run · Ctrl+H help · Ctrl+Q quit",
            id="composer",
        )

    def set_busy(self, busy: bool) -> None:
        self.disabled = busy
        if busy:
            self.placeholder = "ARCEN is working…  (x to interrupt)"
        else:
            self.placeholder = (
                "Describe a task for ARCEN — Enter to run · Ctrl+H help · Ctrl+Q quit"
            )


# ---------------------------------------------------------------- sidebar


class SessionSidebar(VerticalScroll):
    """Newest-first session list backed by GET /api/sessions."""

    BORDER_TITLE = "Sessions"

    def __init__(self) -> None:
        super().__init__(id="sidebar")
        self.border_title = self.BORDER_TITLE
        self._list = ListView(id="session-list")

    def compose(self) -> ComposeResult:
        yield self._list

    async def show_empty(self, message: str) -> None:
        await self._list.clear()  # awaitable: old IDs must leave the DOM first
        self._list.append(ListItem(Label(message), id="session-empty", disabled=True))

    async def show_offline(self) -> None:
        await self._list.clear()
        self._list.append(
            ListItem(Label("server offline"), id="session-offline", disabled=True)
        )

    async def populate(self, sessions: list[dict], current_id: str) -> None:
        await self._list.clear()
        if not sessions:
            await self.show_empty("no sessions yet")
            return
        for meta in sessions:
            sid = str(meta.get("id", ""))
            title = str(meta.get("title") or "(untitled)")
            events = meta.get("events", 0)
            active = sid == current_id
            label = Text()
            label.append("● " if active else "  ", style="bold #FF6B5C" if active else "dim")
            label.append(title[:26], style="bold" if active else "")
            label.append(f"\n    {sid[:8]}… · {events} ev", style="dim")
            self._list.append(ListItem(Label(label), id=f"session-{sid}"))

    @property
    def list_view(self) -> ListView:
        return self._list


# ---------------------------------------------------------------- status bar


class StatusBar(Static):
    """One-line connection / sandbox / session / keybinding summary."""

    def __init__(self) -> None:
        super().__init__(id="statusbar")

    def refresh_state(
        self,
        *,
        online: bool,
        url: str,
        session_id: str,
        busy: bool,
        sandbox: dict | None,
    ) -> None:
        line = Text()
        dot = "●" if online else "○"
        line.append(dot + " ", style="bold #4CC38A" if online else "bold #FF5C5C")
        line.append("online  " if online else "offline  ",
                    style="bold #4CC38A" if online else "bold #FF5C5C")
        line.append(url, style="#5B9DFF")
        line.append("   ")
        if sandbox:
            effective = str(sandbox.get("effective", sandbox.get("backend", "?")))
            degraded = bool(sandbox.get("degraded"))
            color = "#E8B34B" if degraded or effective == "process" else "#4CC38A"
            line.append(f"sandbox: {effective}", style=color)
            if degraded:
                line.append(" (degraded)", style="#E8B34B")
            line.append("   ")
        line.append("session ", style="dim")
        line.append(session_id[:13] + "…", style="#E6E8EB")
        line.append("   ")
        line.append("● running " if busy else "idle  ",
                    style="bold #FF6B5C" if busy else "dim")
        line.append("  ^N new  ^B bar  ^O config  ^X stop  ^H help  ^Q quit", style="dim")
        self.update(line)


# ---------------------------------------------------------------- modals


class HelpScreen(ModalScreen):
    """Keybinding reference — dismissed with Esc, q or any click."""

    BINDINGS: ClassVar[list] = [
        ("escape,q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        body = Static(id="help-body")
        body.update(
            Text.from_markup(
                "[b #FF6B5C]ARCEN TUI — keybindings[/]\n\n"
                "[b]Enter[/]             submit the goal in the composer\n"
                "[b]Esc[/]               return focus to the composer\n"
                "[b]Ctrl+N[/]            start a new chat (fresh session UUID)\n"
                "[b]Ctrl+B[/]            toggle the sessions sidebar\n"
                "[b]Ctrl+R[/]            refresh the session list\n"
                "[b]Enter (sidebar)[/]   open a past session and replay its events\n"
                "[b]Ctrl+O[/]            config + sandbox status (redacted)\n"
                "[b]Ctrl+X[/]            interrupt the running turn (DELETE /api/run)\n"
                "[b]Ctrl+L[/]            clear the transcript\n"
                "[b]Ctrl+H / F1[/]       this help\n"
                "[b]Ctrl+Q[/]            quit\n\n"
                "[dim]Global shortcuts use Ctrl so every printable key stays "
                "available for typing your goal. Events are the frozen 17 "
                "(NDJSON), streamed from /api/stream with Last-Event-ID resume.[/]"
            )
        )
        yield VerticalScroll(body, id="help-modal")

    def on_click(self) -> None:  # pragma: no cover - trivial dismissal
        self.dismiss()


class ConfigScreen(ModalScreen):
    """Redacted config + sandbox decision, fetched live on open."""

    BINDINGS: ClassVar[list] = [
        ("escape,q", "dismiss", "Close"),
    ]

    def __init__(self, client: object) -> None:
        super().__init__()
        self._client = client

    def compose(self) -> ComposeResult:
        self._body = Static(id="config-body")
        self._body.update("Loading config…")
        yield VerticalScroll(self._body, id="config-modal")

    async def on_mount(self) -> None:
        from rich.console import Group

        try:
            cfg = await self._client.get_config()  # type: ignore[attr-defined]
            sandbox = await self._client.sandbox_status()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 — modal must never crash the app
            self._body.update(render.error_banner(f"config unavailable: {exc}"))
            return
        from rich.rule import Rule

        self._body.update(
            Group(
                Text("Configuration (redacted)", style="bold #FF6B5C"),
                Rule(style="dim"),
                render.render_config(cfg),
                Text("\nSandbox", style="bold #FF6B5C"),
                Rule(style="dim"),
                render.render_sandbox(sandbox),
                Text("\n[esc/q] close", style="dim"),
            )
        )
