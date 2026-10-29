"""Responsive live UI, bounded output, wide characters and keyboard navigation."""

import asyncio

import httpx
import pytest
from rich.console import Console

pytest.importorskip("textual")
from arcen.tui.cards.command import MAX_LINE_CELLS, CommandCard
from arcen.tui.client import ArcenClient
from arcen.tui.composer import Composer
from arcen.tui.live import LiveApp
from arcen.tui.modals import HelpScreen
from arcen.tui.views.stream import StreamView


def test_long_and_wide_command_output_is_visually_bounded():
    card = CommandCard("echo hello", output_limit=2)
    card.append_output("界" * 3000 + "\n" + "A" * 5000 + "\nthird\nfourth")
    card.finish(exit_code=0, duration_s=0.1)
    console = Console(record=True, width=80, color_system=None)
    console.print(card.render())
    text = console.export_text()
    assert "2 more lines" in text
    assert "…" in text
    assert len(text.splitlines()) < 20
    assert MAX_LINE_CELLS < 300


async def test_resize_help_and_paging_from_focused_composer():
    async def handler(req):
        return httpx.Response(503)

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=60)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            assert app.rail_collapsed
            composer = app.query_one(Composer)
            assert composer.has_focus and composer.region.height == 5
            assert app.header.region.height == 3
            assert app.query_one(StreamView).region.height >= 8
            for index in range(40):
                app._apply_event(
                    {
                        "seq": index + 1,
                        "type": "think",
                        "agent": "DRAFT",
                        "text": f"row {index} 界🙂",
                    }
                )
            await pilot.pause()
            stream = app.query_one(StreamView)
            for _ in range(40):
                if stream.max_scroll_y > 0 and stream.scroll_y == stream.max_scroll_y:
                    break
                await asyncio.sleep(0.05)
            assert stream.max_scroll_y > 0 and stream.scroll_y == stream.max_scroll_y
            await pilot.press("pageup")
            await pilot.pause()
            assert stream.scroll_y < stream.max_scroll_y
            assert not stream.following
            await pilot.press("pagedown", "ctrl+end")
            await pilot.pause()
            assert stream.scroll_y == stream.max_scroll_y
            await pilot.press("f1")
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.resize_terminal(132, 44)
            await pilot.pause()
            assert not app.rail_collapsed and app.query_one(StreamView).region.width > 60
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            assert app.rail_collapsed and composer.region.width > 60
    finally:
        await http.aclose()
