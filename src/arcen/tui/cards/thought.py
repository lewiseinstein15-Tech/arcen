"""Streaming thought card — DRAFT/FORGE reasoning (TUI-07).

The card displays italic thought text and a streaming cursor. The host
uses ``WordBatcher`` to coalesce incoming fragments before repainting.
"""

from __future__ import annotations

from rich.table import Table

from arcen.tui.cards.base import SPINE_GLYPH, spine_card, streaming_text
from arcen.tui.theme import TOKENS as _T

THOUGHT: str = _T["thought"]
ACCENT: str = _T["accent"]


def thought_card(
    text: str,
    streaming: bool = False,
    label: str = "draft · thinking",
) -> Table:
    """Return a thought card renderable.

    *text* is the accumulated thought so far (may be empty during the first
    batch). When *streaming* is ``True`` a blinking ``▍`` is appended; the
    label defaults to ``draft · thinking`` but callers use ``forge ·
    reasoning`` for the second thought.
    """
    body = streaming_text(text, f"italic {THOUGHT}", streaming, ACCENT)
    return spine_card(body, label, ACCENT, spine=SPINE_GLYPH)
