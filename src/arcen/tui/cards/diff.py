"""Unified file diff, including context and both addition/deletion colors."""
from __future__ import annotations

from rich.table import Table
from rich.text import Text

from arcen.tui.cards.base import spine_card
from arcen.tui.theme import TOKENS


def diff_card(path: str, patch: str) -> Table:
    body = Table.grid(expand=True)
    body.add_column()
    body.add_row(Text(path, style=f"bold {TOKENS['mono']}"))
    for line in patch.splitlines():
        if line.startswith(("+++", "---")):
            color = TOKENS["mono"]
        elif line.startswith("+"):
            color = TOKENS["emerald"]
        elif line.startswith("-"):
            color = TOKENS["rose"]
        elif line.startswith("@@"):
            color = TOKENS["cyan"]
        else:
            color = TOKENS["muted"]
        body.add_row(Text(line, style=color))
    return spine_card(body, "file.diff", TOKENS["cyan"])
