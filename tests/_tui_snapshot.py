"""Headless screenshot helper shared by TUI tests (TUI-03).

Wraps Textual's ``App.save_screenshot`` and optionally rasterizes the SVG
through CairoSVG. CairoSVG is an optional test extra: PNG rasterization is
skipped (not failed) when it is absent, so CI without system Cairo still
runs the structural pilot tests.
"""

from __future__ import annotations

import pathlib

DARK_INK = "#0B0E14"


def save_svg(app, target: pathlib.Path) -> pathlib.Path:
    """Save a headless Textual app frame as SVG; returns the path."""
    target.parent.mkdir(parents=True, exist_ok=True)
    app.save_screenshot(filename=target.name, path=str(target.parent))
    if not target.exists() or target.stat().st_size < 500:
        raise RuntimeError(f"screenshot not written or too small: {target}")
    return target


def rasterize(svg: pathlib.Path, png: pathlib.Path,
              width: int = 1800) -> pathlib.Path | None:
    """SVG → PNG via CairoSVG; returns None when CairoSVG is unavailable."""
    try:
        import cairosvg
    except ImportError:
        return None
    cairosvg.svg2png(
        url=str(svg), write_to=str(png),
        background_color=DARK_INK, output_width=width,
    )
    return png
