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
- ``ARCEN_TUI=new`` — the redesigned shell. It only exists from the
  shell ticket (TUI-04) onward; selecting it earlier exits with a clear
  message instead of crashing.

Both clients are thin render-only clients of the same FastAPI server and
its frozen 17-event NDJSON contract. Textual is an optional dependency:
``pip install 'arcen[tui]'``, launch with ``arcen-tui`` or
``python -m arcen.tui``.
"""

from __future__ import annotations

import os

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

    impl = _selected_impl()
    if impl == _IMPL_NEW:
        try:
            from arcen.tui.app import run as run_new
        except ImportError:
            raise SystemExit(
                "ARCEN_TUI=new selected but the redesigned shell is not "
                "built yet (lands in TUI-04). Unset ARCEN_TUI to use the "
                "default legacy client."
            ) from None
        return run_new(argv)

    from arcen.tui._legacy.app import run as run_legacy

    return run_legacy(argv)
