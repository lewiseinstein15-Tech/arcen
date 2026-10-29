"""Redesigned mission-control shell — chrome, layout, responsive rail (TUI-04).

This module owns the structural :class:`ArcenApp` shared by every later
redesign ticket:

* :class:`Header` — wordmark, session id, model, quarantine state, clock and
  the phase pill (colors resolved through :data:`theme.PHASE_COLORS`);
* :class:`Footer` — the frozen key hints from :data:`keys.FOOTER_HINTS` plus
  the LIVE indicator, which stops blinking when the run settles;
* a two-column body — the narration spine container ``#stream`` beside the
  run-state :class:`~arcen.tui.views.rail.RunStateRail` mounted at ``#rail``.
  Below :data:`RAIL_COLLAPSE_WIDTH` columns the rail collapses automatically
  and the transcript takes the full width.

The shell is render-only: it holds no server logic. Cards (TUI-07…09),
spine scroll rules (TUI-06) and the wire adapter (TUI-10…) mount into these
containers later. The scripted demo subclasses :class:`ArcenApp`, so every
shell change is immediately proven by a full narrated run.
"""

from __future__ import annotations

import datetime as dt
import sys

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from arcen.tui import keys
from arcen.tui.theme import PHASE_COLORS
from arcen.tui.theme import TOKENS as _T
from arcen.tui.views.rail import RunStateRail
from arcen.tui.views.stream import STREAM_CSS, BackToLive, StreamView

# local aliases — every value traces back to a frozen theme token
INK: str = _T["ink"]
PANEL: str = _T["panel"]
LINE: str = _T["line"]
MUTED: str = _T["muted"]
BODY: str = _T["body"]
ACCENT: str = _T["accent"]
CYAN: str = _T["cyan"]
EMERALD: str = _T["emerald"]
MONO: str = _T["mono"]

#: Rail becomes an overlay/collapses when the terminal is narrower than this.
RAIL_COLLAPSE_WIDTH = 100
#: Reserved column width for the run-state rail on wide terminals.
RAIL_WIDTH = 38


def _phase_pill(phase: str) -> Text:
    """Colored ``● PHASE`` marker; unknown phases fail safe to muted."""
    color = _T[PHASE_COLORS.get(phase, "muted")]
    text = Text()
    text.append("● ", style=color)
    text.append(phase, style=f"bold {color}")
    return text


class Header(Static):
    """Top chrome: identity, session metadata, clock and phase pill."""

    def __init__(
        self,
        session: str = "—",
        model: str = "—",
        quarantine: str = "quarantine · net off",
        phase: str = "IDLE",
    ) -> None:
        super().__init__()
        self.session = session
        self.model = model
        self.quarantine = quarantine
        self.phase = phase
        self.now: dt.datetime = dt.datetime.now()

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self.refresh()

    def update_meta(
        self,
        *,
        session: str | None = None,
        model: str | None = None,
        quarantine: str | None = None,
    ) -> None:
        if session is not None:
            self.session = session
        if model is not None:
            self.model = model
        if quarantine is not None:
            self.quarantine = quarantine
        self.refresh()

    def tick(self) -> None:
        """Clock callback — one refresh per second from the app interval."""
        self.now = dt.datetime.now()
        self.refresh()

    def render(self) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")

        left = Text()
        left.append("◆ ", style=f"bold {ACCENT}")
        left.append("ARCEN", style="bold #FFFFFF")
        left.append(" · console", style=MUTED)
        left.append("    ")
        left.append("session ", style=MUTED)
        left.append(self.session, style=MONO)
        left.append("   ")
        left.append(self.model, style=f"italic {MUTED}")

        right = Text()
        status = self.quarantine.lower()
        status_color = (_T["rose"] if "offline" in status else
                        _T["amber"] if "degraded" in status else
                        MUTED if "unknown" in status or "connecting" in status else EMERALD)
        right.append(self.quarantine, style=status_color)
        right.append("    ")
        right.append(self.now.strftime("%H:%M:%S"), style=MUTED)
        right.append("    ")
        right.append(_phase_pill(self.phase))

        grid.add_row(left, right)
        return Panel(
            grid,
            box=box.SQUARE,
            border_style=LINE,
            style=PANEL,
            padding=(0, 1),
        )


class Footer(Static):
    """Bottom chrome: frozen key hints and the LIVE indicator."""

    def __init__(self, live: bool = True) -> None:
        super().__init__()
        self.live = live

    def set_live(self, live: bool) -> None:
        """``run.done`` flips this so LIVE stops blinking (plan §5)."""
        self.live = live
        self.refresh()

    def _live_indicator(self) -> Text:
        # Same label in both states; only the blink changes, per the
        # run.done contract in the redesign plan.
        live = Text()
        live.append("● ", style=f"blink {EMERALD}" if self.live else MUTED)
        live.append("LIVE", style=f"bold {EMERALD}" if self.live else f"bold {MUTED}")
        return live

    def render(self) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")

        hints = Text()
        for key, label in keys.FOOTER_HINTS:
            hints.append(f" {key} ", style=f"bold {BODY} on {LINE}")
            hints.append(f" {label}   ", style=MUTED)

        grid.add_row(hints, self._live_indicator())
        return Panel(
            grid,
            box=box.SQUARE,
            border_style=LINE,
            style=PANEL,
            padding=(0, 1),
        )


class ArcenApp(App):
    """Mission-control shell: header, two-column body, footer."""

    TITLE = "ARCEN console"

    CSS = f"""
    Screen {{ background: {INK}; }}
    #shell {{ layout: horizontal; height: 1fr; }}
    #stream-column {{ width: 1fr; height: 1fr; }}
    #rail {{ width: {RAIL_WIDTH}; height: 1fr; padding: 0 0 0 1; }}
    Header {{ height: auto; margin: 0 0 1 0; }}
    Footer {{ height: auto; margin: 1 0 0 0; }}
    /* Narrow terminals: rail collapses and the spine takes full width. */
    App.narrow #rail {{ display: none; }}
    {STREAM_CSS}
    """

    def __init__(self, headless_mode: bool = False) -> None:
        super().__init__()
        self.headless_mode = headless_mode
        # Bare-shell CI runs paint one frame and leave; the scripted demo
        # flips this off and exits at its own "finished" checkpoint.
        self._auto_exit = headless_mode

    def compose(self) -> ComposeResult:
        self.header = Header()
        self.footer = Footer()
        yield self.header
        with Horizontal(id="shell"):
            with Vertical(id="stream-column"):
                with StreamView(id="stream"):
                    # The demo/adapter mounts the narration stack here.
                    yield Static(id="stream-empty")
                yield BackToLive(" ↓ back to live ", id="back-to-live")
            yield RunStateRail(id="rail")
        yield self.footer

    def on_mount(self) -> None:
        self.set_interval(1.0, self.header.tick)
        self._apply_responsive(self.size.width)
        if self._auto_exit:
            # Let the first frame paint, then leave cleanly (no TTY/CI).
            self.set_timer(0.35, self.exit)

    def on_resize(self, event) -> None:
        self._apply_responsive(event.size.width)

    def _apply_responsive(self, width: int) -> None:
        self.set_class(width < RAIL_COLLAPSE_WIDTH, "narrow")

    @property
    def rail_collapsed(self) -> bool:
        """True while the narrow-terminal rule hides the rail column."""
        return self.has_class("narrow")


def run(
    argv: list[str] | None = None,
    headless: bool | None = None,
    size: tuple[int, int] = (132, 44),
) -> int:
    """Entry point for ``ARCEN_TUI=new``.

    Auto-detects a missing TTY so CI/headless runs paint one frame and exit
    0 instead of hanging on an event loop with no server attached.
    """
    if argv is not None:
        from arcen.tui.live import run as run_live

        return run_live(argv)
    if headless is None:
        headless = not sys.stdout.isatty()
    app = ArcenApp(headless_mode=headless)
    app.run(headless=headless, size=size)
    return 0
