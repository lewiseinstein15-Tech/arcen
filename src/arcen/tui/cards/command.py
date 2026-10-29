"""Command card with streaming output, a visible line cap, and exit status."""
from __future__ import annotations

from rich.table import Table
from rich.text import Text

from arcen.tui.cards.base import CURSOR, spine_card
from arcen.tui.theme import TOKENS

DEFAULT_OUTPUT_LIMIT = 20
# Prevent a single unbroken line from consuming an unbounded terminal height.
MAX_LINE_CELLS = 240


class CommandCard:
    """Mutable command view. The output cap applies to rendered lines."""

    def __init__(self, command: str, tool: str = "bash", *, output_limit: int = DEFAULT_OUTPUT_LIMIT):
        if output_limit < 0:
            raise ValueError("output_limit must be non-negative")
        self.command = command
        self.tool = tool
        self.output_limit = output_limit
        self._chunks: list[str] = []
        self.streaming = True
        self.exit_code: int | None = None
        self.duration_s: float | None = None
        self.ok: bool | None = None

    def append_output(self, chunk: str) -> None:
        if not self.streaming:
            raise RuntimeError("command already finished")
        self._chunks.append(chunk)

    def finish(self, *, exit_code: int | None, duration_s: float, ok: bool | None = None) -> None:
        self.exit_code = exit_code
        self.duration_s = duration_s
        self.ok = (exit_code == 0) if ok is None else ok
        self.streaming = False

    def render(self) -> Table:
        body = Table.grid(expand=True)
        body.add_column()
        head = Text("$ ", style=f"bold {TOKENS['cyan']}")
        head.append(self.command, style=f"bold {TOKENS['mono']}")
        body.add_row(head)
        body.add_row(Text(""))
        lines = "".join(self._chunks).splitlines()
        for line in lines[:self.output_limit]:
            row = Text("  " + line, style=TOKENS["muted"])
            row.truncate(MAX_LINE_CELLS, overflow="ellipsis")
            body.add_row(row)
        hidden = max(0, len(lines) - self.output_limit)
        if hidden:
            body.add_row(Text(f"  … {hidden} more lines", style=TOKENS["muted"]))
        if self.streaming:
            body.add_row(Text("  " + CURSOR, style=f"blink {TOKENS['cyan']}"))
        else:
            body.add_row(Text(""))
            status = f"exit {self.exit_code}" if self.exit_code is not None else ("ok" if self.ok else "failed")
            color = TOKENS["emerald"] if self.ok and self.exit_code in (None, 0) else TOKENS["rose"]
            body.add_row(Text(f"{status} · {self.duration_s:.2f}s", style=f"italic {color}"))
        return spine_card(body, f"forge · {self.tool}", TOKENS["cyan"])
