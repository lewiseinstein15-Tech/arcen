"""Capture a verification test run as a screenshot (SVG + PNG).

Standing convention for the TUI/ARCEN2 rebuild tickets: every ticket ends
with a screenshot of its verification test, stored in ``docs/verify/``.

Usage:
    python scripts/verify_shot.py TUI-01 "python -m pytest tests/test_tui_entry.py -q --color=yes"

The command runs in a subprocess with ANSI colors forced, its output is
replayed through Rich (``Text.from_ansi``) and exported to an SVG terminal
recording, then rasterized to PNG via CairoSVG. Falls back to SVG-only if
CairoSVG is unavailable.
"""

from __future__ import annotations

import os
import pathlib
import shlex
import subprocess
import sys

from rich.console import Console
from rich.text import Text

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "docs" / "verify"
MAX_LINES = 80
CONSOLE_WIDTH = 125


def run_capture(command: list[str]) -> int:
    env = dict(os.environ)
    env["FORCE_COLOR"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run(
        command,
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    lines = output.splitlines()
    if len(lines) > MAX_LINES:
        head = lines[:15]
        tail = lines[-(MAX_LINES - 17):]
        lines = head + [f"  … {len(lines) - MAX_LINES} lines truncated …"] + tail
    return proc.returncode, "\n".join(lines)


def save_screenshot(ticket: str, command: list[str], output: str, code: int) -> pathlib.Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    console = Console(
        record=True,
        width=CONSOLE_WIDTH,
        force_terminal=True,
        color_system="truecolor",
    )
    console.rule(f"[bold]ARCEN verification — {ticket}[/]")
    console.print(f"[dim]$ {' '.join(command)}[/]")
    console.print(
        Text.from_ansi(output) if output.strip() else Text("(no output)", style="dim")
    )
    verdict = "PASS" if code == 0 else f"FAIL (exit {code})"
    console.rule(f"[bold {'green' if code == 0 else 'red'}]{verdict}[/]")

    svg_path = OUT_DIR / f"{ticket}.svg"
    console.save_svg(str(svg_path), title=f"ARCEN {ticket}")

    png_path = OUT_DIR / f"{ticket}.png"
    try:
        import cairosvg

        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            background_color="#0B0E14",
            output_width=1800,
        )
    except ImportError:
        print("cairosvg not installed — SVG written only", file=sys.stderr)
    return png_path if png_path.exists() else svg_path


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    ticket, command = argv[1], shlex.split(" ".join(argv[2:]))
    code, output = run_capture(command)
    shot = save_screenshot(ticket, command, output, code)
    print(f"screenshot: {shot.relative_to(REPO)} (exit {code})")
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
