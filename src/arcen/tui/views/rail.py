"""Run-state rail — the right-hand mission-control panel (TUI-05).

The rail is a pure render of a plain :class:`RailState` value object. The
wire adapter (TUI-10) will build state dicts from ``usage`` / ``plan`` /
``step.*`` events and hand them to :meth:`RunStateRail.apply_state`; unknown
keys are ignored by design, mirroring the adapter's forward-compatibility
rule so additive ARCEN² events never crash the panel.

Blocks, top to bottom: run progress (step counter + bar), phase tracker,
context-window meter, spend, tool chips, environment, harness reference.
Every color resolves through :mod:`arcen.tui.theme` — no raw hex here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from arcen.tui.theme import PHASE_COLORS
from arcen.tui.theme import TOKENS as _T

# local aliases — every value traces back to a frozen theme token
PANEL: str = _T["panel"]
LINE: str = _T["line"]
MUTED: str = _T["muted"]
BODY: str = _T["body"]
ACCENT: str = _T["accent"]
CYAN: str = _T["cyan"]
EMERALD: str = _T["emerald"]
AMBER: str = _T["amber"]
MONO: str = _T["mono"]

#: Ordered phase track; index is the rail's phase position.
PHASES: tuple[str, ...] = ("DRAFT", "FORGE", "TEMPER", "DONE")
#: Width in cells of the progress / context meters.
BAR_WIDTH = 16
#: Default context-window ceiling used until a ``usage`` event says otherwise.
DEFAULT_TOKEN_LIMIT = 128_000


@dataclass
class RailState:
    """Everything the rail renders. Plain data — no Textual imports needed."""

    steps_done: int = 0
    steps_total: int = 0
    phase_idx: int = 0
    tokens: int = 0
    token_limit: int = DEFAULT_TOKEN_LIMIT
    cost_usd: float = 0.0
    tools: list[str] = field(default_factory=list)
    sandbox: str = "—"
    network: str = "—"
    workdir: str = "—"
    harness: str | None = None


class RunStateRail(Static):
    """Renders a :class:`RailState`; mutable through dicts or attributes."""

    def __init__(
        self,
        *,
        steps_total: int = 0,
        sandbox: str = "—",
        network: str = "—",
        workdir: str = "—",
        harness: str | None = None,
        **kwargs,
    ) -> None:
        # kwargs forwards Textual DOM params (id, classes, disabled…).
        super().__init__(**kwargs)
        self._state = RailState(
            steps_total=steps_total,
            sandbox=sandbox,
            network=network,
            workdir=workdir,
            harness=harness,
        )

    # ── state access ────────────────────────────────────────────────────
    @property
    def state(self) -> RailState:
        return self._state

    def apply_state(self, update: dict) -> None:
        """Merge a state dict into the rail.

        Accepts flat keys (``tokens``, ``cost_usd`` …) and a nested
        ``environment`` mapping. ``phase`` may be given as a phase name
        instead of ``phase_idx``. Unknown keys are ignored.
        """
        known = set(RailState.__dataclass_fields__)
        env = update.get("environment")
        if isinstance(env, dict):
            for key in ("sandbox", "network", "workdir"):
                if key in env:
                    setattr(self._state, key, str(env[key]))
        for key, value in update.items():
            if key in ("environment", "phase"):
                continue
            if key in known:
                setattr(self._state, key, value)
        if "phase" in update:
            try:
                self._state.phase_idx = PHASES.index(str(update["phase"]).upper())
            except ValueError:
                # Unknown phase name: keep the current position rather than
                # crash — same fail-safe rule as unknown event types.
                pass
        self.refresh()

    # ── attribute compatibility (the scripted demo mutates these) ──────
    @property
    def steps_done(self) -> int:
        return self._state.steps_done

    @steps_done.setter
    def steps_done(self, value: int) -> None:
        self._state.steps_done = int(value)

    @property
    def steps_total(self) -> int:
        return self._state.steps_total

    @steps_total.setter
    def steps_total(self, value: int) -> None:
        self._state.steps_total = int(value)

    @property
    def phase_idx(self) -> int:
        return self._state.phase_idx

    @phase_idx.setter
    def phase_idx(self, value: int) -> None:
        self._state.phase_idx = int(value)

    @property
    def tokens(self) -> int:
        return self._state.tokens

    @tokens.setter
    def tokens(self, value: int) -> None:
        self._state.tokens = int(value)

    @property
    def cost(self) -> float:
        """Demo-facing alias for the canonical ``cost_usd`` field."""
        return self._state.cost_usd

    @cost.setter
    def cost(self, value: float) -> None:
        self._state.cost_usd = float(value)

    @property
    def tools(self) -> list[str]:
        # Returning the live list keeps ``rail.tools.append(...)`` working.
        return self._state.tools

    # ── rendering ───────────────────────────────────────────────────────
    def _phase_timeline(self) -> Text:
        s = self._state
        started = s.steps_total > 0
        timeline = Text()
        for i, phase in enumerate(PHASES):
            color = _T[PHASE_COLORS[phase]]
            if not started:
                glyph, glyph_style, name_style = "○", LINE, MUTED
            elif i < s.phase_idx:
                glyph, glyph_style, name_style = "●", color, EMERALD
            elif i == s.phase_idx:
                glyph, glyph_style, name_style = "◐", f"bold {color}", f"bold {color}"
            else:
                glyph, glyph_style, name_style = "○", LINE, MUTED
            timeline.append(glyph + " ", style=glyph_style).append(phase, style=name_style)
            if i < len(PHASES) - 1:
                timeline.append("\n")
        return timeline

    @staticmethod
    def _meter(fraction: float, fill_color: str) -> Text:
        fraction = max(0.0, min(fraction, 1.0))
        filled = round(fraction * BAR_WIDTH)
        bar = Text()
        bar.append("█" * filled, style=fill_color)
        bar.append("░" * (BAR_WIDTH - filled), style=LINE)
        return bar

    @staticmethod
    def _network_style(network: str) -> str:
        if network == "off":
            return EMERALD
        if network == "on":
            return AMBER
        return MUTED  # unpopulated "—" must not look like a warning

    def _tool_chips(self) -> Text:
        chips = Text()
        for tool in sorted(set(self._state.tools)):
            chips.append(f" {tool} ", style=f"bold {CYAN} on {PANEL}")
            chips.append(" ")
        return chips if chips else Text("—", style=MUTED)

    def render(self) -> Panel:
        s = self._state
        grid = Table.grid(expand=True)
        grid.add_column()

        grid.add_row(Text("RUN PROGRESS", style=f"bold {MUTED}"))
        grid.add_row(Text(f"step {s.steps_done}/{s.steps_total}", style=f"bold {BODY}"))
        grid.add_row(self._meter(s.steps_done / max(s.steps_total, 1), ACCENT))
        grid.add_row(Text(""))

        grid.add_row(Text("PHASES", style=f"bold {MUTED}"))
        grid.add_row(self._phase_timeline())
        grid.add_row(Text(""))

        grid.add_row(Text("CONTEXT WINDOW", style=f"bold {MUTED}"))
        grid.add_row(self._meter(s.tokens / max(s.token_limit, 1), CYAN))
        grid.add_row(Text(f"{s.tokens:,} / {s.token_limit:,} tok", style=MUTED))
        grid.add_row(Text(""))

        grid.add_row(Text("SPEND", style=f"bold {MUTED}"))
        grid.add_row(Text(f"${s.cost_usd:.4f}", style=BODY))
        grid.add_row(Text(""))

        grid.add_row(Text("TOOLS", style=f"bold {MUTED}"))
        grid.add_row(self._tool_chips())
        grid.add_row(Text(""))

        grid.add_row(Text("ENVIRONMENT", style=f"bold {MUTED}"))
        grid.add_row(
            Text("sandbox  ", style=MUTED).append(s.sandbox, style=MONO)
        )
        grid.add_row(
            Text("network  ", style=MUTED)
            .append(s.network, style=self._network_style(s.network))
        )
        grid.add_row(
            Text("workdir  ", style=MUTED).append(s.workdir, style=MONO)
        )
        grid.add_row(Text(""))

        grid.add_row(Text("HARNESS", style=f"bold {MUTED}"))
        if s.harness:
            grid.add_row(Text(s.harness, style=f"italic {ACCENT}"))
        else:
            grid.add_row(Text("—", style=MUTED))

        return Panel(
            grid,
            box=box.ROUNDED,
            border_style=LINE,
            style=PANEL,
            padding=(1, 2),
            title=Text(" run state ", style=f"bold {MUTED}"),
        )
