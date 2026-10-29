"""Editable, multiline goal composer and discoverable slash commands."""

from __future__ import annotations

from typing import ClassVar

from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea

COMMANDS = {
    "/help": "Show commands and shortcuts",
    "/clear": "Clear the visible transcript",
    "/new": "Start a new session",
    "/sessions": "Open sessions",
    "/config": "Open configuration",
    "/sandbox": "Show sandbox status",
}


class Composer(TextArea):
    """Enter submits; Ctrl+T inserts a line (also supports modified Enter where available)."""

    DEFAULT_CSS = """
    Composer { height: 5; min-height: 3; border: round #A78BFA; background: #10141D;
      color: #DCE2EE; padding: 0 1; }
    Composer:focus { border: round #A78BFA; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("enter", "submit_goal", "Submit", priority=True),
        Binding("ctrl+t,alt+enter,shift+enter", "newline", "New line", priority=True),
        Binding("tab", "complete_command", "Complete command", priority=True),
    ]

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def action_submit_goal(self) -> None:
        self.post_message(self.Submitted(self.text))

    def action_newline(self) -> None:
        self.insert("\n")

    def action_complete_command(self) -> None:
        text = self.text.strip()
        matches = (
            [command for command in COMMANDS if command.startswith(text)]
            if text.startswith("/")
            else []
        )
        if len(matches) == 1:
            self.load_text(matches[0])
            self.move_cursor((0, len(matches[0])))
