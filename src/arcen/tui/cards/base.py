"""Shared card chrome — the mission-control spine (TUI-07).

Every narration card is a rounded panel alongside a gutter node. The
streaming helper coalesces incoming text fragments over a short time window,
then delivers the accumulated text to the host in one repaint.

Pure Rich — no Textual import, so the whole file is unit-testable via a
plain ``Console``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from arcen.tui.theme import TOKENS as _T

LINE: str = _T["line"]

# ── glyphs ───────────────────────────────────────────────────────────────────
CURSOR: str = "▍"
SPINE_GLYPH: str = "◉"
GOAL_GLYPH: str = "◆"
SPINE_BREAK: str = " │"


def spine_card(
    body,
    title: str,
    accent: str,
    spine: str = SPINE_GLYPH,
) -> Table:
    """Wrap *body* in the standard spine+gutter panel.

    *accent* is a hex color string (a resolved theme token value, e.g.
    ``TOKENS[\"accent\"]``). The same accent colors the node glyph and the
    panel title so the eye can skim the spine without reading every title.
    """
    grid = Table.grid(expand=True, padding=(0, 0))
    grid.add_column(width=3, justify="center")
    grid.add_column(ratio=1)
    panel = Panel(
        body,
        box=box.ROUNDED,
        border_style=LINE,
        title=Text(f" {title} ", style=f"bold {accent}"),
        title_align="left",
        padding=(0, 1),
    )
    grid.add_row(Text(spine, style=f"bold {accent}"), panel)
    return grid


# Back-compat alias — the plan calls it ``SpineCard``.
SpineCard = spine_card


def spine_break() -> Text:
    """Thin vertical connector between cards on the narration spine."""
    return Text(SPINE_BREAK, style=LINE)


def append_cursor(text: Text, streaming: bool, accent: str) -> None:
    """Append the blinking ``▍`` cursor to *text* in place when streaming.

    Mutates *text* so callers can build their body in one place::

        body = Text(\"hello\", style=THOUGHT)
        append_cursor(body, streaming=True, accent=ACCENT)
    """
    if streaming:
        text.append(CURSOR, style=f"blink {accent}")


def streaming_text(
    content: str,
    content_style: str,
    streaming: bool,
    cursor_accent: str,
) -> Text:
    """Build an italic body ``Text`` with an optional trailing cursor.

    This function builds a renderable; batching is handled by WordBatcher.
    """
    body = Text()
    if content:
        body.append(content, style=content_style)
    append_cursor(body, streaming, cursor_accent)
    return body


class WordBatcher:
    """Coalesce arbitrary text fragments into paints at most once per window.

    Construct on the event-loop thread. ``emit(text, streaming)`` receives
    exact accumulated text, without stripping whitespace or modifying Unicode.
    ``finish`` immediately flushes pending content and removes the cursor;
    ``cancel`` cancels pending work when the view is torn down.
    """

    def __init__(self, emit: Callable[[str, bool], None], interval: float = 0.05):
        if interval <= 0:
            raise ValueError("batch interval must be positive")
        self._emit = emit
        self._interval = interval
        self._chunks: list[str] = []
        self._text = ""
        self._timer: asyncio.TimerHandle | None = None
        self._closed = False

    def feed(self, fragment: str) -> None:
        if self._closed:
            raise RuntimeError("batcher is closed")
        if not fragment:
            return
        self._chunks.append(fragment)
        if self._timer is None:
            self._timer = asyncio.get_running_loop().call_later(self._interval, self._flush)

    def _flush(self) -> None:
        self._timer = None
        if self._closed or not self._chunks:
            return
        self._text += "".join(self._chunks)
        self._chunks.clear()
        self._emit(self._text, True)

    def finish(self) -> None:
        if self._closed:
            return
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._text += "".join(self._chunks)
        self._chunks.clear()
        self._closed = True
        self._emit(self._text, False)

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._chunks.clear()
        self._closed = True
