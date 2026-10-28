"""ARCEN terminal UI.

Two implementations coexist during the TUI redesign
(see ``docs/TUI-REDESIGN-PLAN.md``):

- the **legacy** full-screen Textual client, parked in
  :mod:`arcen.tui._legacy`, remains the default through TUI-17 and is
  deleted at the cut-over ticket TUI-18;
- the **new** mission-control shell (narration spine + run-state rail,
  prototyped in ``prototype/arcen_tui_demo.py``) is built ticket by ticket
  in :mod:`arcen.tui.app`, :mod:`arcen.tui.cards` and :mod:`arcen.tui.views`.

Selection is controlled by the ``ARCEN_TUI`` environment variable:

- ``ARCEN_TUI=legacy`` (default) — the frozen legacy app;
- ``ARCEN_TUI=new`` — the redesigned mission-control shell
  (:mod:`arcen.tui.app`), built from TUI-04 onward.

Both clients are thin render-only clients of the same FastAPI server and
its frozen 17-event NDJSON contract. Textual is an optional dependency:
``pip install 'arcen[tui]'``, launch with ``arcen-tui`` or
``python -m arcen.tui``.
"""

from __future__ import annotations

import os
import sys

__all__ = ["main"]

_IMPL_ENVVAR = "ARCEN_TUI"
_IMPL_LEGACY = "legacy"
_IMPL_NEW = "new"


def _selected_impl() -> str:
    impl = os.environ.get(_IMPL_ENVVAR, _IMPL_LEGACY).strip().lower()
    if impl not in (_IMPL_LEGACY, _IMPL_NEW):
        # Unknown values fail safe toward the shipped implementation rather
        # than crashing with an import error.
        impl = _IMPL_LEGACY
    return impl


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

    # Console scripts call main() with no args, so fall back to the real
    # process command line; explicit argv (tests, library use) wins.
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    if "--demo" in argv:
        # Scripted self-streaming demo — works with no server and, without
        # a TTY, renders headlessly and exits 0 (CI and the test harness).
        from arcen.tui.demo import run_demo

        return run_demo([arg for arg in argv if arg != "--demo"])

    impl = _selected_impl()
    if impl == _IMPL_NEW:
        from arcen.tui.app import run as run_new

        return run_new(argv)

    from arcen.tui._legacy.app import run as run_legacy

    return run_legacy(argv)
