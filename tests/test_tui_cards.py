"""TUI-07 — base spine chrome + goal/thought cards (pure renderables).

All cards are Rich renderables — no running app needed. Tests pin the
mission-control look (spine gutter, rounded panel, word-batch cursor) via a
plain ``Console`` and inspect styles so a re-skin touches only ``theme.py``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from rich.console import Console
from rich.text import Text as RichText

from arcen.tui.cards.base import (
    CURSOR,
    GOAL_GLYPH,
    SPINE_GLYPH,
    spine_break,
    spine_card,
)
from arcen.tui.cards.goal import goal_card
from arcen.tui.cards.thought import thought_card
from arcen.tui.theme import TOKENS


def _plain(renderable, width: int = 80) -> str:
    console = Console(record=True, width=width)
    console.print(renderable)
    return console.export_text()


def _segments(renderable):
    return list(Console(width=80, force_terminal=True, color_system="truecolor").render(renderable))


def _has_style(renderable, needle: str) -> bool:
    return any(segment.style and getattr(segment.style, needle, False)
               for segment in _segments(renderable))


def _style_hexes(renderable) -> set[str]:
    return {
        segment.style.color.name.lower()
        for segment in _segments(renderable)
        if segment.style and segment.style.color
    }


# ── base chrome ──────────────────────────────────────────────────────────────
def test_spine_card_renders_gutter_and_panel_title():
    card = spine_card(
        RichText("inner", style=TOKENS["body"]),
        "you · goal",
        TOKENS["muted"],
        spine=GOAL_GLYPH,
    )
    plain = _plain(card)
    assert GOAL_GLYPH in plain
    assert "you · goal" in plain
    assert "inner" in plain


def test_spine_break_is_line_glyph():
    br = spine_break()
    assert br.plain.strip() == "│"
    assert TOKENS["line"].lower() in str(br.style).lower()


def test_spine_card_uses_only_frozen_tokens():
    allowed = {v.lower() for v in TOKENS.values()}
    card = spine_card(RichText("hi", style=TOKENS["body"]), "test", TOKENS["accent"])
    hexes = _style_hexes(card)
    assert {TOKENS["accent"].lower(), TOKENS["body"].lower(), TOKENS["line"].lower()} <= hexes
    assert hexes <= allowed


def test_cursor_constant_is_block():
    assert CURSOR == "▍"


def test_spine_glyphs_are_single_char():
    assert len(SPINE_GLYPH) == 1
    assert len(GOAL_GLYPH) == 1
    assert SPINE_GLYPH == "◉"
    assert GOAL_GLYPH == "◆"


# ── goal card ────────────────────────────────────────────────────────────────
def test_goal_card_plain_contains_goal_text():
    text = "Add a /api/health endpoint and cover it with tests."
    card = goal_card(text)
    plain = _plain(card)
    assert text in plain
    assert "you · goal" in plain
    assert GOAL_GLYPH in plain


def test_goal_card_uses_muted_accent_and_body_style():
    card = goal_card("do the thing")
    plain = _plain(card)
    assert GOAL_GLYPH in plain
    allowed = {v.lower() for v in TOKENS.values()}
    hexes = _style_hexes(card)
    assert {TOKENS["muted"].lower(), TOKENS["body"].lower()} <= hexes
    assert hexes <= allowed


def test_goal_card_empty_still_renders_panel():
    card = goal_card("")
    plain = _plain(card)
    assert "you · goal" in plain
    assert GOAL_GLYPH in plain


# ── thought card ────────────────────────────────────────────────────────────
def test_thought_card_idle_has_no_cursor():
    card = thought_card("I think therefore I am.", streaming=False)
    plain = _plain(card)
    assert "I think therefore I am." in plain
    assert CURSOR not in plain
    assert "draft · thinking" in plain  # default label


def test_thought_card_streaming_appends_blinking_cursor():
    text = "The goal touches the FastAPI layer"
    card = thought_card(text, streaming=True)
    plain = _plain(card)
    assert text in plain
    assert CURSOR in plain
    assert plain.count(CURSOR) == 1
    assert _has_style(card, "blink")


def test_thought_card_idle_has_no_blink():
    card = thought_card("done thinking", streaming=False)
    assert not _has_style(card, "blink")


def test_thought_card_empty_streaming_shows_cursor_only():
    card = thought_card("", streaming=True)
    plain = _plain(card)
    assert CURSOR in plain
    assert plain.count(CURSOR) == 1


def test_thought_card_flip_from_streaming_to_idle_removes_cursor():
    text = "Routes are plain @app.get decorators."
    streaming = thought_card(text, streaming=True)
    assert CURSOR in _plain(streaming)
    idle = thought_card(text, streaming=False)
    assert CURSOR not in _plain(idle)
    assert text in _plain(idle)


def test_thought_card_label_overrides_default():
    card = thought_card("hello", streaming=False, label="forge · reasoning")
    plain = _plain(card)
    assert "forge · reasoning" in plain
    assert "draft · thinking" not in plain


def test_thought_card_long_text_wraps_without_clipping():
    long = "word " * 40  # forces wrapping at width 80
    card = thought_card(long.strip(), streaming=False)
    plain = _plain(card, width=50)
    assert "word" in plain
    assert plain.count("word") == 40


def test_thought_card_uses_theme_tokens():
    card = thought_card("hello", streaming=True)
    allowed = {v.lower() for v in TOKENS.values()}
    hexes = _style_hexes(card)
    assert {TOKENS["accent"].lower(), TOKENS["thought"].lower()} <= hexes
    assert hexes <= allowed


def test_goal_and_thought_share_base_shape():
    for card in (goal_card("g"), thought_card("t")):
        plain = _plain(card)
        assert any(g in plain for g in (GOAL_GLYPH, SPINE_GLYPH))


# ── batching exercises the actual implementation, not a synthetic loop ───────
async def test_batcher_coalesces_fast_fragments_and_finishes_exactly():
    import asyncio

    from arcen.tui.cards.base import WordBatcher

    paints = []
    batcher = WordBatcher(lambda text, active: paints.append((text, active)), interval=0.03)
    for fragment in ["Hel", "lo", "  ", "🌍", "\n", "world"]:
        batcher.feed(fragment)
    assert paints == []
    await asyncio.sleep(0.06)
    assert paints == [("Hello  🌍\nworld", True)]
    batcher.feed("!")
    batcher.finish()
    assert paints[-1] == ("Hello  🌍\nworld!", False)
    await asyncio.sleep(0.06)
    assert len(paints) == 2  # canceled timer must not repaint after finish
    batcher.finish()  # idempotent
    with pytest.raises(RuntimeError):
        batcher.feed("late")


async def test_batcher_cancel_drops_pending_paints():
    import asyncio

    from arcen.tui.cards.base import WordBatcher

    paints = []
    batcher = WordBatcher(lambda text, active: paints.append((text, active)), 0.02)
    batcher.feed("pending")
    batcher.cancel()
    await asyncio.sleep(0.05)
    assert paints == []


async def test_batcher_multiple_windows_and_empty_finish():
    import asyncio

    from arcen.tui.cards.base import WordBatcher

    paints = []
    batcher = WordBatcher(lambda text, active: paints.append((text, active)), 0.02)
    batcher.feed("a")
    await asyncio.sleep(0.05)
    batcher.feed(" b")
    await asyncio.sleep(0.05)
    batcher.finish()
    assert paints == [("a", True), ("a b", True), ("a b", False)]
    empty = []
    WordBatcher(lambda text, active: empty.append((text, active))).finish()
    assert empty == [("", False)]


def test_invalid_batch_interval_rejected():
    from arcen.tui.cards.base import WordBatcher

    with pytest.raises(ValueError):
        WordBatcher(lambda *_: None, 0)


async def test_demo_stream_text_uses_batched_updates_and_finishes():
    from arcen.tui.demo import DemoApp

    class FakeNarration:
        def __init__(self):
            self.paints = []

        def push(self, card):
            self.paints.append(card)

        def replace_last(self, card):
            self.paints.append(card)

    app = DemoApp()
    narration = FakeNarration()
    app.narration = narration
    await app.stream_text("one two three four five six", "draft · thinking")
    # Initial shell plus coalesced updates and final cursor-free render:
    # fewer renders than six individual word updates plus shell and finish.
    assert len(narration.paints) < 8
    assert CURSOR in _plain(narration.paints[0])
    assert "one two three four five six" in _plain(narration.paints[-1])
    assert CURSOR not in _plain(narration.paints[-1])
