"""Narration spine and its auto-scroll follow rules (TUI-06).

Two widgets:

* :class:`Narration` — the content stack. Cards are pushed or replaced in
  place by the scripted demo today and by the wire adapter (TUI-10) later.
* :class:`StreamView` — the scroll container around that stack. It follows
  the live edge only while the user is already at the bottom. Scrolling up
  pauses following, so incoming tokens never yank the reader away, and reveals
  a ``↓ back to live`` pill; clicking the pill (or pressing ``End``) returns
  to the live edge and re-engages following.

The rule is deliberately mechanical — follow state is derived purely from
the scroll position in :meth:`StreamView.watch_scroll_y`, so keyboard,
mouse and programmatic scrolling all take the same path.
"""

from __future__ import annotations

from rich.console import Group
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from arcen.tui.theme import TOKENS as _T

INK: str = _T["ink"]
LINE: str = _T["line"]
MUTED: str = _T["muted"]
BODY: str = _T["body"]
ACCENT: str = _T["accent"]
PANEL: str = _T["panel"]

# App-level rules for the floating pill, which is a sibling of the scroll
# view rather than its child: component DEFAULT_CSS only reaches the
# component's own type, so the id selectors live here and are composed into
# each host app's stylesheet (shell and test harness share this constant).
STREAM_CSS = f"""
#back-to-live {{
    dock: bottom;
    /* border-box sizing: one text row + the rounded border's two rows */
    height: 3;
    width: auto;
    padding: 0 1;
    margin: 0 0 1 2;
    color: {BODY};
    background: {PANEL};
    border: round {LINE};
    display: none;
}}
#stream-column.paused #back-to-live {{ display: block; }}
"""


class Narration(Static):
    """The stack of narration cards (goals, thoughts, tool cards…)."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.items: list = []
        self._stream: StreamView | None = None

    def bind_stream(self, stream: StreamView) -> None:
        self._stream = stream

    def _sync(self) -> None:
        # update() re-renders AND re-measures; plain refresh() would keep the
        # initial zero-item size and clip the whole narration.
        self.update(Group(*self.items) if self.items else Text(""))
        if self._stream is not None:
            self._stream.request_follow()

    def push(self, renderable) -> None:
        self.items.append(renderable)
        self._sync()

    def replace_last(self, renderable) -> None:
        self.items[-1] = renderable
        self._sync()

    def replace_at(self, index: int, renderable) -> None:
        """Mutate an existing card without moving it on the spine."""
        self.items[index] = renderable
        self._sync()

    def render(self):
        return Group(*self.items) if self.items else Text("")


class StreamView(VerticalScroll):
    """Scroll container that follows the live edge unless pinned by the user."""

    # Component CSS travels with the widgets, so any app (shell, demo, test
    # harness) gets the working layout without re-declaring it. Textual loads
    # component styles from DEFAULT_CSS (the CSS attr is App-level only).
    DEFAULT_CSS = f"""
    StreamView {{
        width: 1fr;
        height: 1fr;
        background: {INK};
        scrollbar-size: 1 1;
    }}
    Narration {{ width: 1fr; height: auto; padding: 0 1; }}
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Fresh content follows by default; flips to False whenever the user
        # is scrolled anywhere other than the bottom.
        self._following = True

    @property
    def following(self) -> bool:
        return self._following

    @property
    def _column(self):
        """The wrapper column that hosts the back-to-live pill."""
        return self.parent

    def watch_scroll_y(self, old: float, new: float) -> None:
        # Preserve Textual's repaint, scrollbar and anchoring behavior.
        super().watch_scroll_y(old, new)
        at_bottom = new >= self.max_scroll_y
        self._following = at_bottom
        # Only offer the pill when there is actually content to return to.
        paused = (not at_bottom) and self.max_scroll_y > 0
        if self._column is not None:
            self._column.set_class(paused, "paused")

    def watch_virtual_size(self, old, new) -> None:
        # Content often finishes measuring after the mutation that requested
        # a follow, so re-assert the live edge whenever the virtual size
        # grows while locked. max_scroll_y itself is only a computed
        # property, so virtual_size (a reactive) is the trigger.
        if self._following and new.height != old.height:
            self.call_after_refresh(lambda: self.scroll_end(animate=False))

    def request_follow(self) -> None:
        """Called after content mutations; scrolls only while following."""
        if self._following:
            self.call_after_refresh(lambda: self.scroll_end(animate=False))


class BackToLive(Static):
    """Floating pill shown while the spine is paused away from the live edge."""

    def on_click(self) -> None:
        stream = self.app.query_one(StreamView)
        stream.scroll_end(animate=False)
        # The scroll watcher re-engages follow and hides this pill.
