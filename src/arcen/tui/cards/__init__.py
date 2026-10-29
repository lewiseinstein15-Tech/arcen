"""Event card factory registry — filled from TUI-07 onward.

Each frozen/v2 stream event maps to a Rich renderable card rendered on the
narration spine. The registry is data-driven so ARCEN² harness events can
register their own cards without touching the spine (TUI-10, H-20).
"""

from arcen.tui.cards.base import (
    CURSOR,
    GOAL_GLYPH,
    SPINE_BREAK,
    SPINE_GLYPH,
    SpineCard,
    WordBatcher,
    append_cursor,
    spine_break,
    spine_card,
    streaming_text,
)
from arcen.tui.cards.command import CommandCard
from arcen.tui.cards.diff import diff_card
from arcen.tui.cards.goal import goal_card
from arcen.tui.cards.plan import PlanCard, PlanStep
from arcen.tui.cards.thought import thought_card

__all__ = [
    "CURSOR",
    "GOAL_GLYPH",
    "SPINE_BREAK",
    "SPINE_GLYPH",
    "CommandCard",
    "PlanCard",
    "PlanStep",
    "SpineCard",
    "WordBatcher",
    "append_cursor",
    "diff_card",
    "goal_card",
    "spine_break",
    "spine_card",
    "streaming_text",
    "thought_card",
]
