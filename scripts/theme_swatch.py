"""Render the TUI theme tokens as a visual swatch sheet (TUI-02).

Draws every token as a color block with its name, truecolor hex and
precomputed xterm-256 fallback, plus the semantic phase/status maps, and
writes an SVG + PNG pair into docs/verify/. Run:

    python scripts/theme_swatch.py [TICKET]
"""

from __future__ import annotations

import pathlib
import sys

from rich.console import Console
from rich.table import Table
from rich.text import Text

from arcen.tui.theme import (
    ANSI256_FALLBACKS,
    CARD_ACCENTS,
    FONT_STACK,
    PHASE_COLORS,
    STATUS_COLORS,
    TOKENS,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "verify"


def swatch(hex_color: str) -> Text:
    # Four inverse-video spaces read as a solid color chip in terminals
    # and in the SVG export.
    return Text("    ", style=f"bold {hex_color} on {hex_color}")


def main(ticket: str = "TUI-02") -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    console = Console(record=True, width=118, force_terminal=True,
                      color_system="truecolor")
    console.rule("[bold]ARCEN theme swatch — truecolor tokens + 256 fallbacks[/]")

    table = Table(expand=True, padding=(0, 1))
    table.add_column("swatch", width=6)
    table.add_column("token", style="bold")
    table.add_column("hex")
    table.add_column("xterm-256", justify="right")
    table.add_column("luminance", justify="right")
    for name, hex_color in TOKENS.items():
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
        luminance = round(0.2126 * r + 0.7152 * g + 0.0722 * b)
        table.add_row(
            swatch(hex_color),
            name,
            Text(hex_color, style=hex_color),
            str(ANSI256_FALLBACKS[name]),
            f"{luminance}/255",
        )
    console.print(table)

    def semantic(title: str, mapping: dict[str, str]) -> None:
        console.rule(f"[bold]{title}[/]")
        t = Table(expand=True)
        t.add_column("key", style="bold")
        t.add_column("token")
        t.add_column("hex")
        t.add_column("swatch", width=6)
        for key, token in mapping.items():
            hex_color = TOKENS[token]
            t.add_row(key, token, Text(hex_color, style=hex_color), swatch(hex_color))
        console.print(t)

    semantic("phase colors", PHASE_COLORS)
    semantic("status colors", STATUS_COLORS)
    semantic("card accents", CARD_ACCENTS)
    console.print(Text("font stack: " + " → ".join(FONT_STACK), style="dim"))

    svg = OUT / f"{ticket}-palette.svg"
    png = OUT / f"{ticket}-palette.png"
    console.save_svg(str(svg), title=f"ARCEN {ticket} theme")
    import cairosvg

    cairosvg.svg2png(url=str(svg), write_to=str(png),
                     background_color="#0B0E14", output_width=1800)
    print(f"wrote {png.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "TUI-02"))
