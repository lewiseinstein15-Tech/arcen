"""ARCEN TUI design tokens (TUI-02).

Single source of truth for the redesigned shell's color language, frozen
from the approved prototype (``prototype/arcen_tui_demo.py``):

- mission-control dark ink with one violet brand accent;
- color is semantic — cyan for tool actions, amber for active verification,
  emerald for pass, rose for fail;
- every truecolor hex carries a precomputed xterm-256 fallback so the TUI
  stays legible over SSH/tmux without ``TERM=truecolor``.

The module has no Textual import — tokens are plain strings/ints and Rich
:class:`~rich.color.Color` objects are only constructed on demand, so the
fallback table is unit-testable on a headless machine.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── truecolor tokens (hex without alpha) ────────────────────────────────────
TOKENS: dict[str, str] = {
    "ink":     "#0B0E14",  # app background
    "panel":   "#10141D",  # card surface
    "line":    "#1D2430",  # borders / narration spine
    "muted":   "#7D8699",  # secondary text
    "body":    "#DCE2EE",  # primary text
    "white":   "#FFFFFF",  # strongest emphasis (wordmark)
    "accent":  "#A78BFA",  # violet — ARCEN brand accent, DRAFT phase
    "cyan":    "#7DD3FC",  # FORGE / tool actions
    "emerald": "#34D399",  # pass / healthy / DONE
    "rose":    "#FB7185",  # fail / error
    "amber":   "#FBBF24",  # active / warn / TEMPER
    "thought": "#9AA6BF",  # italic streamed thought text
    "mono":    "#C9D4E8",  # terminal/monospace content
}

# Semantic aliases — views/cards must reference these names, never raw hex,
# so a re-skin means editing this table alone.
PHASE_COLORS: dict[str, str] = {
    "DRAFT":  "accent",
    "FORGE":  "cyan",
    "TEMPER": "amber",
    "DONE":   "emerald",
    "IDLE":   "muted",
    "ERROR":  "rose",
}

STATUS_COLORS: dict[str, str] = {
    "pending": "muted",
    "active":  "amber",
    "done":    "emerald",
    "pass":    "emerald",
    "fail":    "rose",
    "error":   "rose",
    "info":    "accent",
}

CARD_ACCENTS: dict[str, str] = {
    "goal":      "muted",
    "thought":   "accent",
    "plan":      "accent",
    "command":   "cyan",
    "diff":      "cyan",
    "verify":    "amber",
    "answer":    "emerald",
    "system":    "muted",
    "error":     "rose",
}

# Fonts are chosen by the terminal, not Textual; this documents the intended
# stack and drives the headless SVG test harness, which can embed fonts.
FONT_STACK: tuple[str, ...] = (
    "Fira Code",
    "JetBrains Mono",
    "Cascadia Mono",
    "DejaVu Sans Mono",
    "monospace",
)


# ── xterm-256 fallback computation ──────────────────────────────────────────
def _cube_rgb(index: int) -> tuple[int, int, int]:
    """RGB value of one axis index (0..5) in the 6×6×6 color cube."""
    return 0 if index == 0 else 55 + 40 * index


def _build_256_palette() -> list[tuple[int, int, int]]:
    palette: list[tuple[int, int, int]] = [(0, 0, 0)] * 256
    # 16..231 — 6×6×6 cube
    for code in range(16, 232):
        n = code - 16
        b, n = n % 6, n // 6
        g, r = n % 6, n // 6
        palette[code] = (_cube_rgb(r), _cube_rgb(g), _cube_rgb(b))
    # 232..255 — grayscale ramp
    for i in range(24):
        value = 8 + 10 * i
        palette[232 + i] = (value, value, value)
    # 0..15 — standard ANSI slots; map only via the cube/grays for stability,
    # so give them the cube-black / ramp endpoints they duplicate.
    palette[0] = (0, 0, 0)
    return palette


_PALETTE = _build_256_palette()


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected #rrggbb, got {value!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def nearest_ansi256(hex_color: str) -> int:
    """Return the xterm-256 code closest to ``hex_color`` by RGB distance.

    Only the deterministic cube (16..231) and grayscale ramp (232..255) are
    candidates — the theme never relies on the user's configurable 0..15
    ANSI slot colors.
    """
    target = _hex_to_rgb(hex_color)
    best_code, best_dist = 16, float("inf")
    for code in range(16, 256):
        candidate = _PALETTE[code]
        dist = sum((a - b) ** 2 for a, b in zip(target, candidate))
        if dist < best_dist:
            best_code, best_dist = code, dist
    return best_code


# Frozen at import time so tests can pin exact codes.
ANSI256_FALLBACKS: dict[str, int] = {
    name: nearest_ansi256(hex_color) for name, hex_color in TOKENS.items()
}


@dataclass(frozen=True)
class ResolvedColor:
    """A token resolved for one terminal color system."""

    name: str
    hex: str
    ansi256: int
    color_system: str

    def css(self) -> str:
        """Stylesheet value appropriate for the selected color system."""
        if self.color_system == "256":
            return f"ansi({self.ansi256})"
        return self.hex


def resolve(name: str, color_system: str = "truecolor") -> ResolvedColor:
    """Resolve a token (or semantic alias) for ``truecolor``/``256`` output."""
    if name not in TOKENS:
        raise KeyError(f"unknown theme token {name!r}")
    if color_system not in ("truecolor", "256"):
        raise ValueError(f"unsupported color system {color_system!r}")
    return ResolvedColor(name, TOKENS[name], ANSI256_FALLBACKS[name], color_system)


def resolve_semantic(table: dict[str, str], key: str,
                     color_system: str = "truecolor") -> ResolvedColor:
    """Resolve through a semantic alias table (PHASE_COLORS, STATUS_COLORS)."""
    return resolve(table[key], color_system)


def css_variables() -> dict[str, str]:
    """Textual ``--arcen-*`` custom properties (truecolor values)."""
    return {f"--arcen-{name}": hex_color for name, hex_color in TOKENS.items()}


def css_block() -> str:
    """:root stylesheet block wiring every token as a CSS custom property."""
    lines = [":root {"]
    lines.extend(f"    {prop}: {value};" for prop, value in css_variables().items())
    lines.append("}")
    return "\n".join(lines)
