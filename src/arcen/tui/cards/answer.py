"""Closing answer card: Markdown wire text or an explicitly styled Rich Text."""
from __future__ import annotations

from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from arcen.tui.cards.base import GOAL_GLYPH, spine_card
from arcen.tui.theme import TOKENS


def answer_card(content: str | Text) -> Table:
    # Markdown supports inline emphasis/code without interpreting arbitrary
    # model-generated brackets as Rich markup directives.
    body = Markdown(content) if isinstance(content, str) else content.copy()
    return spine_card(body, "answer", TOKENS["emerald"], spine=GOAL_GLYPH)
