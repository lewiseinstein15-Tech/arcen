"""ARCEN's single server-backed terminal UI and offline demo entry point."""

from __future__ import annotations

import sys

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Console entry point; Textual remains an optional dependency."""
    try:
        import textual  # noqa: F401
    except ImportError:
        raise SystemExit(
            "ARCEN TUI needs the optional Textual dependency.\n"
            "Install it with: pip install 'arcen[tui]'"
        ) from None
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    if "--demo" in argv:
        from arcen.tui.demo import run_demo

        return run_demo([arg for arg in argv if arg != "--demo"])
    from arcen.tui.live import run

    return run(argv)
