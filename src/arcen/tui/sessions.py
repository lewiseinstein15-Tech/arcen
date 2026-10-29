"""Session picker: API metadata in server order; replay remains in LiveApp."""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static


class SessionItem(ListItem):
    def __init__(self, session: dict, current: str) -> None:
        self.session_id = str(session.get("id", ""))
        title = str(session.get("title") or "(untitled)")
        label = Text("● " if self.session_id == current else "  ", style="#A78BFA")
        label.append(title)
        label.append(
            f"\n    {self.session_id[:8]}… · {session.get('events', 0)} events", style="#7D8699"
        )
        super().__init__(Label(label))


class SessionsScreen(ModalScreen[str | None]):
    CSS = """
    SessionsScreen { align: left middle; background: #0B0E14 70%; }
    #sessions-drawer { width: 48; max-width: 100%; height: 85%; border: round #A78BFA;
        background: #10141D; padding: 1 1; }
    #sessions-title { color: #DCE2EE; text-style: bold; height: 2; }
    #sessions-help { color: #7D8699; height: 2; }
    #sessions-list { height: 1fr; background: #10141D; }
    #sessions-list > ListItem { height: 3; }
    #sessions-list:focus > ListItem.-highlight { background: #302641; color: #DCE2EE; }
    #sessions-list > ListItem.-highlight { background: #302641; color: #DCE2EE; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape,q", "close", "Close", priority=True)]

    def __init__(self, sessions: list[dict], current: str) -> None:
        super().__init__()
        self.sessions = sessions
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="sessions-drawer"):
            yield Static("SESSIONS  /  recent", id="sessions-title")
            if self.sessions:
                yield ListView(
                    *(SessionItem(item, self.current) for item in self.sessions), id="sessions-list"
                )
            else:
                yield Static("No sessions yet.", id="sessions-list")
            yield Static("↑↓ choose   Enter open   Esc close", id="sessions-help")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, SessionItem) and event.item.session_id:
            self.dismiss(event.item.session_id)

    def action_close(self) -> None:
        self.dismiss(None)
