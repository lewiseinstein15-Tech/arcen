"""Capture headless frames of the scripted TUI demo (TUI-03 harness).

Drives :class:`arcen.tui.demo.DemoApp` through its durable phase checkpoints
and writes SVG + PNG frames into docs/verify/. Reused by later TUI tickets
to screenshot new cards against the same scripted run.

Usage:
    python scripts/capture_demo.py TUI-03
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from arcen.tui.demo import DemoApp  # noqa: E402

OUT = REPO / "docs" / "verify"
SIZE = (132, 44)

# checkpoint phase -> output filename suffix
FRAMES = [
    ("forge", "demo-forge"),
    ("forge_mid", "demo-forge-mid"),
    ("finished", "demo-finished"),
]


async def main(ticket: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = DemoApp(headless_mode=True)
    written: list[pathlib.Path] = []
    async with app.run_test(headless=True, size=SIZE):
        for phase, suffix in FRAMES:
            await app.wait_phase(phase, timeout=60)
            await asyncio.sleep(0.35)  # let the final paint settle
            svg = OUT / f"{ticket}-{suffix}.svg"
            app.save_screenshot(filename=svg.name, path=str(OUT))
            written.append(svg)

    import cairosvg

    for svg in written:
        png = svg.with_suffix(".png")
        cairosvg.svg2png(url=str(svg), write_to=str(png),
                         background_color="#0B0E14", output_width=1856)
        print(f"wrote {png.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    ticket = sys.argv[1] if len(sys.argv) > 1 else "TUI-03"
    raise SystemExit(asyncio.run(main(ticket)))
