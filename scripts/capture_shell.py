"""Capture headless frames proving the TUI-04 app shell and its collapse rule.

Three frames go to docs/verify/:

* ``<TICKET>-shell-wide``    — scripted demo finished at 132×44, rail visible;
* ``<TICKET>-shell-narrow``  — same run resized to 80×24, rail collapsed and
  the narration spine taking the full width;
* ``<TICKET>-shell-empty``   — the bare :class:`ArcenApp` (what
  ``ARCEN_TUI=new`` boots before cards/rail content land in later tickets).

Usage:
    python scripts/capture_shell.py TUI-04
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from arcen.tui.app import ArcenApp
from arcen.tui.demo import DemoApp

OUT = REPO / "docs" / "verify"
BG = "#0B0E14"


def _rasterize(svg: pathlib.Path, width: int) -> None:
    import cairosvg

    cairosvg.svg2png(
        url=str(svg),
        write_to=str(svg.with_suffix(".png")),
        background_color=BG,
        output_width=width,
    )
    print(f"wrote {svg.with_suffix('.png').relative_to(REPO)}")


async def main(ticket: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    written: list[tuple[pathlib.Path, int]] = []

    # 1+2: populated shell, wide then collapsed in one pilot session.
    # Keep the app alive past "finished" so the resize actually repaints.
    app = DemoApp(headless_mode=True, exit_on_finished=False)
    async with app.run_test(headless=True, size=(132, 44)) as pilot:
        await app.wait_phase("finished", timeout=60)
        await asyncio.sleep(0.35)
        wide = OUT / f"{ticket}-shell-wide.svg"
        app.save_screenshot(filename=wide.name, path=str(OUT))
        written.append((wide, 1856))

        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        await asyncio.sleep(0.25)  # let the collapse repaint settle
        narrow = OUT / f"{ticket}-shell-narrow.svg"
        app.save_screenshot(filename=narrow.name, path=str(OUT))
        written.append((narrow, 1126))

    # 3: bare shell chrome with its placeholder rail (no demo driver).
    bare = ArcenApp()  # headless_mode off: no auto-exit inside run_test
    async with bare.run_test(headless=True, size=(132, 44)) as pilot:
        await pilot.pause()
        empty = OUT / f"{ticket}-shell-empty.svg"
        bare.save_screenshot(filename=empty.name, path=str(OUT))
        written.append((empty, 1856))

    for svg, width in written:
        _rasterize(svg, width)
    return 0


if __name__ == "__main__":
    ticket = sys.argv[1] if len(sys.argv) > 1 else "TUI-04"
    raise SystemExit(asyncio.run(main(ticket)))
