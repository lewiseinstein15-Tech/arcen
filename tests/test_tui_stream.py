"""TUI-06 — narration spine auto-scroll rules.

The spine follows the live edge only while the reader is at the bottom.
Scrolling up pauses following and reveals the back-to-live pill; new
content must not yank the view; clicking the pill (or pressing End)
re-engages follow. All tests drive the real widgets under a headless pilot.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical

from arcen.tui.views.rail import RunStateRail
from arcen.tui.views.stream import (
    STREAM_CSS,
    BackToLive,
    Narration,
    StreamView,
)


class StreamHarness(App):
    """Minimal app mounting the real stream column beside a rail."""

    CSS = (
        "#shell { layout: horizontal; height: 1fr; }"
        "#stream-column { width: 1fr; height: 1fr; }"
        "#rail { width: 38; height: 1fr; padding: 0 0 0 1; }"
        + STREAM_CSS
    )

    def __init__(self, rows: int = 0) -> None:
        super().__init__()
        self._rows = rows

    def compose(self) -> ComposeResult:
        with Horizontal(id="shell"):
            with Vertical(id="stream-column"):
                with StreamView(id="stream"):
                    self.narration = Narration()
                    yield self.narration
                yield BackToLive(" ↓ back to live ", id="back-to-live")
            yield RunStateRail(id="rail")

    def on_mount(self) -> None:
        for i in range(self._rows):
            self.narration.push(Text(f"card {i:03d} " + "x" * 60))


def _pill(app) -> BackToLive:
    return app.query_one("#back-to-live", BackToLive)


async def test_fresh_spine_follows_live_edge():
    app = StreamHarness(rows=40)
    async with app.run_test(headless=True, size=(80, 16)) as pilot:
        await pilot.pause()
        stream = app.query_one(StreamView)
        assert stream.following is True
        assert stream.scroll_y == stream.max_scroll_y
        assert not app.query_one("#stream-column").has_class("paused")
        assert _pill(app).display is False


async def test_scrolling_up_pauses_follow_and_reveals_pill():
    app = StreamHarness(rows=40)
    async with app.run_test(headless=True, size=(80, 16)) as pilot:
        await pilot.pause()
        stream = app.query_one(StreamView)

        stream.scroll_to(y=0, animate=False)
        await pilot.pause()

        assert stream.following is False
        assert stream.scroll_y == 0
        assert app.query_one("#stream-column").has_class("paused")
        assert _pill(app).display is True


async def test_new_content_does_not_yank_a_paused_reader():
    app = StreamHarness(rows=40)
    async with app.run_test(headless=True, size=(80, 16)) as pilot:
        await pilot.pause()
        stream = app.query_one(StreamView)
        stream.scroll_to(y=0, animate=False)
        await pilot.pause()

        pinned_y = stream.scroll_y
        for i in range(5):
            app.narration.push(Text(f"new card {i}"))
        await pilot.pause()

        assert stream.following is False
        assert stream.scroll_y == pinned_y  # held position, not yanked down
        assert _pill(app).display is True


async def test_clicking_pill_returns_to_live_and_re_engages_follow():
    app = StreamHarness(rows=40)
    async with app.run_test(headless=True, size=(80, 16)) as pilot:
        await pilot.pause()
        stream = app.query_one(StreamView)
        stream.scroll_to(y=0, animate=False)
        await pilot.pause()
        assert _pill(app).display is True

        await pilot.click("#back-to-live")
        await pilot.pause()

        assert stream.following is True
        assert stream.scroll_y == stream.max_scroll_y
        assert _pill(app).display is False

        # follow stays engaged: later content rides the live edge
        bottom = stream.max_scroll_y
        app.narration.push(Text("one more card"))
        await pilot.pause()
        assert stream.following is True
        assert stream.max_scroll_y >= bottom


async def test_end_key_re_engages_follow_without_mouse():
    app = StreamHarness(rows=40)
    async with app.run_test(headless=True, size=(80, 16)) as pilot:
        await pilot.pause()
        stream = app.query_one(StreamView)
        stream.scroll_to(y=0, animate=False)
        await pilot.pause()
        assert stream.following is False

        await pilot.press("end")
        await pilot.pause()

        assert stream.following is True
        assert stream.scroll_y == stream.max_scroll_y
        assert _pill(app).display is False


async def test_no_pill_when_content_fits_without_overflow():
    app = StreamHarness(rows=2)
    async with app.run_test(headless=True, size=(80, 40)) as pilot:
        await pilot.pause()
        stream = app.query_one(StreamView)
        assert stream.max_scroll_y == 0
        # even after a forced scroll attempt, the pill stays hidden
        stream.scroll_to(y=0, animate=False)
        await pilot.pause()
        assert _pill(app).display is False
        assert not app.query_one("#stream-column").has_class("paused")


async def test_pill_carries_back_to_live_label_and_glyph():
    app = StreamHarness(rows=40)
    async with app.run_test(headless=True, size=(80, 16)) as pilot:
        await pilot.pause()
        stream = app.query_one(StreamView)
        stream.scroll_to(y=0, animate=False)
        await pilot.pause()
        pill = _pill(app)
        assert pill.display is True
        # the affordance keeps its down-arrow glyph and words
        assert "↓" in pill.render().plain
        assert "back to live" in pill.render().plain


async def test_replace_last_keeps_following_and_mutates_stack():
    app = StreamHarness(rows=30)
    async with app.run_test(headless=True, size=(80, 16)) as pilot:
        await pilot.pause()
        stream = app.query_one(StreamView)
        assert stream.following is True

        app.narration.replace_last(Text("replaced final card"))
        await pilot.pause()

        assert app.narration.items[-1].plain == "replaced final card"
        assert stream.following is True
        assert stream.scroll_y == stream.max_scroll_y
