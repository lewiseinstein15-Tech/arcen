"""ARCEN terminal UI — a Textual client for the ARCEN stream server.

The TUI is a thin, faithful terminal client of the same FastAPI server the
web UI talks to (``arcen serve`` on :3002):

- ``POST /api/run`` starts a narrated turn (DRAFT → FORGE → TEMPER);
- ``GET /api/stream`` delivers the frozen 17 events as NDJSON — the TUI
  honors the same transport contract as ``ui/src/stream/reader.ts``
  (partial-line buffering, seq-less ``stream.ping`` heartbeats ignored,
  ``stream.done`` ends the read, ``Last-Event-ID`` resume, 409 compaction
  restarts from zero, held streams never 404);
- ``GET /api/sessions`` replays history, ``DELETE /api/run/{id}``
  interrupts a turn, ``/api/config`` and ``/api/sandbox/status`` feed the
  config screen.

Textual is an optional dependency: install with ``pip install 'arcen[tui]'``
and launch with ``arcen-tui`` or ``python -m arcen.tui``.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point — keeps the Textual import lazy.

    A user without the ``tui`` extra gets a one-line install hint instead
    of an ImportError traceback.
    """
    try:
        import textual  # noqa: F401
    except ImportError:
        raise SystemExit(
            "ARCEN TUI needs the optional Textual dependency.\n"
            "Install it with:  pip install 'arcen[tui]'"
        ) from None

    from arcen.tui.app import run

    return run(argv)
