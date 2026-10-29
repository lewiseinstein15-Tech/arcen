"""Low-emphasis run/memory markers, subagent notices, and fatal error card."""
from __future__ import annotations

from rich.table import Table
from rich.text import Text

from arcen.tui.cards.base import GOAL_GLYPH, spine_card
from arcen.tui.theme import TOKENS


def run_marker(run_id: str) -> Text:
    text = Text(" ◆ ", style=TOKENS["accent"])
    text.append(f"run {run_id}", style=TOKENS["muted"])
    return text


def memory_chip(op: str, entity: str, fact: str) -> Text:
    text = Text(" · memory ", style=TOKENS["muted"])
    text.append(f"{op} · {entity} · {fact}", style=TOKENS["muted"])
    return text


def error_card(code: str, message: str, hint: str = "") -> Table:
    body = Text()
    body.append(f"{code}: ", style=f"bold {TOKENS['rose']}")
    body.append(message, style=TOKENS["body"])
    if hint:
        body.append("\n" + hint, style=TOKENS["muted"])
    return spine_card(body, "error", TOKENS["rose"], spine=GOAL_GLYPH)


def spawn_card(name: str, task: str, parent: str, depth: int = 1) -> Table:
    # Depth is bounded for terminal readability, but information remains visible.
    depth = max(0, min(depth, 2))
    body = Text(f"{'  ' * depth}{name} · parent {parent}\n{'  ' * depth}{task}",
                style=TOKENS["body"])
    return spine_card(body, "subagent · spawn", TOKENS["accent"])


def spawn_done_card(name: str, ok: bool, calls: int, duration_s: float) -> Table:
    color = TOKENS["emerald"] if ok else TOKENS["rose"]
    body = Text(f"{name} · {'ok' if ok else 'failed'} · {calls} calls · {duration_s:.2f}s",
                style=color)
    return spine_card(body, "subagent · done", TOKENS["accent"])
