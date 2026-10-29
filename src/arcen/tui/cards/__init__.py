"""Event card factory registry — filled from TUI-07 onward.

Each frozen/v2 stream event maps to a Rich renderable card rendered on the
narration spine. The registry is data-driven so ARCEN² harness events can
register their own cards without touching the spine (TUI-10, H-20).
"""

from arcen.tui.cards.answer import answer_card
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
from arcen.tui.cards.system import error_card, memory_chip, run_marker, spawn_card, spawn_done_card
from arcen.tui.cards.thought import thought_card
from arcen.tui.cards.verify import Check, VerifyCard

__all__ = [
    "CURSOR",
    "GOAL_GLYPH",
    "SPINE_BREAK",
    "SPINE_GLYPH",
    "CardRegistry",
    "Check",
    "CommandCard",
    "PlanCard",
    "PlanStep",
    "SpineCard",
    "VerifyCard",
    "WordBatcher",
    "answer_card",
    "append_cursor",
    "diff_card",
    "error_card",
    "goal_card",
    "memory_chip",
    "run_marker",
    "spawn_card",
    "spawn_done_card",
    "spine_break",
    "spine_card",
    "streaming_text",
    "thought_card",
]


class CardRegistry:
    """Data-driven card/model constructors; extensions may register new kinds."""

    def __init__(self):
        self._factories = {
            "goal": goal_card, "thought": thought_card, "plan": PlanCard,
            "command": CommandCard, "diff": diff_card, "verify": VerifyCard,
            "answer": answer_card, "run": run_marker, "memory": memory_chip,
            "error": error_card, "spawn": spawn_card, "spawn.done": spawn_done_card,
        }

    def register(self, kind, factory):
        if not kind or not callable(factory):
            raise ValueError("a kind and callable factory are required")
        self._factories[kind] = factory

    def create(self, kind, *args, **kwargs):
        return self._factories[kind](*args, **kwargs)
