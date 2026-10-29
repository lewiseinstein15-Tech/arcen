"""Mutable plan checklist, independent of the transport adapter."""
from __future__ import annotations

from dataclasses import dataclass, replace

from rich.table import Table
from rich.text import Text

from arcen.tui.cards.base import spine_card
from arcen.tui.theme import TOKENS


@dataclass(frozen=True)
class PlanStep:
    id: str
    title: str
    detail: str = ""
    status: str = "pending"


_STYLES = {
    "pending": ("○", TOKENS["line"]),
    "active": ("◐", TOKENS["amber"]),
    "done": ("●", TOKENS["emerald"]),
    "fail": ("✕", TOKENS["rose"]),
}


class PlanCard:
    """A checklist whose steps can be updated or replaced in place."""

    def __init__(self, steps: list[PlanStep]):
        self.replace_steps(steps)

    def replace_steps(self, steps: list[PlanStep]) -> None:
        if len({step.id for step in steps}) != len(steps):
            raise ValueError("plan step ids must be unique")
        if any(step.status not in _STYLES for step in steps):
            raise ValueError("invalid plan step status")
        self.steps = list(steps)

    def set_status(self, step_id: str, status: str) -> None:
        if status not in _STYLES:
            raise ValueError(f"invalid plan step status: {status}")
        for index, step in enumerate(self.steps):
            if step.id == step_id:
                self.steps[index] = replace(step, status=status)
                return
        raise KeyError(step_id)

    def render(self) -> Table:
        body = Table.grid(expand=True, padding=(0, 1))
        body.add_column(width=3)
        body.add_column(ratio=1)
        body.add_column(justify="right")
        for step in self.steps:
            icon, color = _STYLES[step.status]
            body.add_row(
                Text(icon, style=color),
                Text(step.title, style=TOKENS["muted"] if step.status == "pending" else TOKENS["body"]),
                Text(step.detail, style=f"italic {TOKENS['muted']}"),
            )
        return spine_card(body, f"plan · {len(self.steps)} steps", TOKENS["accent"])
