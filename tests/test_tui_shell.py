"""TUI-04 — redesigned app shell: chrome, layout, responsive rail collapse.

Pilot tests assert the widget tree at the prototype size (132×44) and at a
narrow terminal (80×24), plus dynamic resize behavior across the 100-column
threshold. All tests are headless — no server, no TTY.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from rich.console import Console

from arcen.tui import keys
from arcen.tui.app import (
    RAIL_COLLAPSE_WIDTH,
    RAIL_WIDTH,
    ArcenApp,
    Footer,
    Header,
    run,
)
from arcen.tui.theme import PHASE_COLORS, TOKENS
from arcen.tui.views.rail import RunStateRail


def _plain(widget) -> str:
    console = Console(record=True, width=140)
    console.print(widget.render())
    return console.export_text()


# ── chrome renderables (no running app needed) ─────────────────────────────
def test_header_defaults_show_idle_pill_and_metadata():
    header = Header(session="s_abc", model="glm-5.1 · litellm")
    text = _plain(header)
    assert "ARCEN" in text and "console" in text
    assert "s_abc" in text and "glm-5.1 · litellm" in text
    assert "quarantine · net off" in text
    assert "IDLE" in text


def test_header_phase_and_meta_updates():
    header = Header()
    header.set_phase("FORGE")
    assert header.phase == "FORGE"
    assert "FORGE" in _plain(header)

    header.update_meta(session="s_new", model="other-model", quarantine="docker · net on")
    rendered = _plain(header)
    assert "s_new" in rendered and "other-model" in rendered
    assert "docker · net on" in rendered


def test_phase_pill_uses_semantic_theme_colors():
    from arcen.tui.app import _phase_pill

    pill = _phase_pill("ERROR")
    assert pill.plain == "● ERROR"
    rose = TOKENS[PHASE_COLORS["ERROR"]]
    assert any(rose in str(style) for _s, _e, style in pill.spans)


def test_footer_hints_come_from_frozen_key_map():
    footer = Footer()
    text = _plain(footer)
    for key, label in keys.FOOTER_HINTS:
        assert key in text and label in text
    assert "LIVE" in text


def test_footer_live_indicator_loses_blink_when_settled():
    live = Footer(live=True)._live_indicator()
    settled = Footer(live=False)
    settled.set_live(False)
    idle = settled._live_indicator()

    assert any("blink" in str(style) for _s, _e, style in live.spans)
    assert not any("blink" in str(style) for _s, _e, style in idle.spans)
    assert idle.plain.strip().endswith("LIVE")


# ── widget tree at the two ticket sizes ─────────────────────────────────────
async def test_shell_tree_wide_keeps_rail_beside_stream():
    app = ArcenApp()
    async with app.run_test(headless=True, size=(132, 44)) as pilot:
        await pilot.pause()

        assert isinstance(app.header, Header)
        assert isinstance(app.footer, Footer)
        assert isinstance(app.query_one("#rail"), RunStateRail)
        assert app.query_one("#stream-empty") is not None

        shell = app.query_one("#shell")
        stream = app.query_one("#stream")
        rail = app.query_one("#rail")

        assert app.size.width == 132
        assert not app.rail_collapsed
        assert rail.display is True
        # horizontal two-column arrangement, rail reserves its column
        assert RAIL_WIDTH <= rail.region.width <= RAIL_WIDTH + 2
        assert stream.region.x == shell.region.x
        assert rail.region.x >= stream.region.right - 1
        assert stream.region.width > rail.region.width


async def test_shell_collapses_rail_below_100_columns():
    app = ArcenApp()
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause()

        assert app.size.width == 80
        assert app.rail_collapsed
        rail = app.query_one("#rail")
        assert rail.display is False

        # the narration spine gets the full shell width
        shell = app.query_one("#shell")
        stream = app.query_one("#stream")
        assert stream.region.width == shell.region.width


async def test_rail_re_expands_and_collapses_on_resize():
    app = ArcenApp()
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.rail_collapsed

        await pilot.resize_terminal(132, 44)
        await pilot.pause()
        assert not app.rail_collapsed
        assert app.query_one("#rail").display is True

        # boundary: exactly the threshold stays open, one less collapses
        await pilot.resize_terminal(RAIL_COLLAPSE_WIDTH, 30)
        await pilot.pause()
        assert not app.rail_collapsed
        await pilot.resize_terminal(RAIL_COLLAPSE_WIDTH - 1, 30)
        await pilot.pause()
        assert app.rail_collapsed
        assert app.query_one("#rail").display is False


def test_headless_shell_paints_one_frame_and_exits_zero():
    # no TTY path: no server attached, so it must not hang on the loop.
    # Sync on purpose — run() owns its own asyncio loop via app.run().
    assert run(headless=True) == 0


async def test_demo_runs_inside_collapsed_shell():
    # the scripted demo inherits the shell; narrow mode must not break it
    from arcen.tui.demo import DemoApp

    app = DemoApp(headless_mode=True)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await app.wait_phase("finished", timeout=60)
        await pilot.pause()
        assert app.rail_collapsed
        assert app.query_one("#rail").display is False
        assert len(app.narration.items) >= 10
