"""Client-side view state for the event-driven TUI (TUI-10)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CardEntry:
    """One item in the narration, with an optional mutable backing model."""
    kind: str
    index: int
    model: Any = None


@dataclass
class ViewState:
    run_id: str = ""
    phase: str = "IDLE"
    status: str = "idle"
    replanning: bool = False
    steps_total: int = 0
    steps_done: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    tools: list[str] = field(default_factory=list)
    last_seq: int = 0
    cards: list[CardEntry] = field(default_factory=list)
    plan: CardEntry | None = None
    verification: CardEntry | None = None
    commands: dict[str, CardEntry] = field(default_factory=dict)
