"""Top-level TUI views — narration spine, run-state rail, modals, composer.

Scaffolded at TUI-01; implementations arrive in TUI-04 (shell), TUI-05
(rail), TUI-06 (spine), TUI-13 (composer), TUI-14/15 (drawer/modals).
"""

from arcen.tui.views.rail import PHASES, RailState, RunStateRail
from arcen.tui.views.stream import BackToLive, Narration, StreamView

__all__ = [
    "PHASES",
    "BackToLive",
    "Narration",
    "RailState",
    "RunStateRail",
    "StreamView",
]
