"""Explicit, non-destructive run interruption confirmation."""
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class InterruptScreen(ModalScreen[bool]):
    """Only an affirmative key authorizes an interrupt request."""

    CSS = """
    InterruptScreen { align: center middle; background: #0B0E14 75%; }
    #interrupt-dialog { width: 60; max-width: 95%; height: auto; padding: 1 2;
      border: round #FBBF24; background: #10141D; color: #DCE2EE; }
    #interrupt-title { color: #FBBF24; text-style: bold; margin-bottom: 1; }
    #interrupt-hint { color: #7D8699; margin-top: 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("y,enter", "confirm", "Interrupt", priority=True),
                Binding("n,escape,ctrl+c", "cancel", "Keep running", priority=True)]

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def compose(self) -> ComposeResult:
        with Vertical(id="interrupt-dialog"):
            yield Static("Interrupt this run?", id="interrupt-title")
            yield Static(f"Run {self.run_id}\nThe current step may finish before stopping.")
            yield Static("[Y / Enter] interrupt   [N / Esc] keep running", id="interrupt-hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
