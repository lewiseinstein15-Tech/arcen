"""User goal card — the opening card on every run (TUI-07)."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text

from arcen.tui.cards.base import GOAL_GLYPH, spine_card
from arcen.tui.theme import TOKENS as _T

BODY: str = _T["body"]
MUTED: str = _T["muted"]


def goal_card(text: str) -> Table:
    """Render the user's goal text as a muted/diamond-gutter card.

    The card is static — no streaming cursor — so one render is enough.
    """
    body = Text(text, style=BODY)
    return spine_card(body, "you · goal", MUTED, spine=GOAL_GLYPH)
