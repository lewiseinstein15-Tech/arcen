"""Mutable TEMPER verification checklist."""
from __future__ import annotations

from dataclasses import dataclass, replace

from rich.table import Table
from rich.text import Text

from arcen.tui.cards.base import spine_card
from arcen.tui.theme import TOKENS


@dataclass(frozen=True)
class Check:
    id: str
    label: str
    detail: str = ""
    status: str = "pending"


_STYLES = {
    "pending": ("○", "line"),
    "active": ("◐", "amber"),
    "pass": ("✓", "emerald"),
    "fail": ("✕", "rose"),
}


class VerifyCard:
    """Keep check updates in one card; callers repaint after each mutation."""

    def __init__(self, checks: list[Check] | None = None):
        self.checks: list[Check] = []
        for check in checks or []:
            self.add_check(check)

    def add_check(self, check: Check) -> None:
        if check.status not in _STYLES:
            raise ValueError(f"invalid check status: {check.status}")
        if any(item.id == check.id for item in self.checks):
            raise ValueError("check ids must be unique")
        self.checks.append(check)

    def set_status(self, check_id: str, status: str, *, detail: str | None = None) -> None:
        if status not in _STYLES:
            raise ValueError(f"invalid check status: {status}")
        for index, check in enumerate(self.checks):
            if check.id == check_id:
                self.checks[index] = replace(check, status=status,
                    detail=check.detail if detail is None else detail)
                return
        raise KeyError(check_id)

    def render(self) -> Table:
        body = Table.grid(expand=True, padding=(0, 1))
        body.add_column(width=3)
        body.add_column(ratio=1)
        body.add_column(justify="right")
        for check in self.checks:
            icon, color = _STYLES[check.status]
            label_color = (TOKENS["muted"] if check.status == "pending" else
                           TOKENS["amber"] if check.status == "active" else TOKENS["body"])
            detail = "running…" if check.status == "active" else check.detail
            body.add_row(Text(icon, style=f"bold {TOKENS[color]}"),
                         Text(check.label, style=label_color),
                         Text(detail, style=f"italic {TOKENS['muted']}"))
        return spine_card(body, "temper · verification", TOKENS["amber"])
