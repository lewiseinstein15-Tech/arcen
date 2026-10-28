"""Scripted, self-streaming demo of the redesigned TUI (TUI-03).

Ported from the approved ``prototype/arcen_tui_demo.py`` and re-based on the
frozen tokens in :mod:`arcen.tui.theme` so the demo can never drift from the
real palette. The app needs no server: an in-memory script plays one full
narrated turn (goal → streamed thoughts → plan → tool cards → diff →
verification → answer) through the mission-control narration spine and
run-state rail.

Launch with ``arcen-tui --demo``. On a machine without a TTY (CI) the demo
runs headless, plays to completion, and exits 0 — the same path the pilot
test harness in ``tests/test_tui_demo.py`` exercises.

Note: this is prototype-grade, intentionally self-contained code. Later
tickets (TUI-04…09) refactor its widgets into :mod:`arcen.tui.cards` and
:mod:`arcen.tui.views` as the real shell is built.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Static

from arcen.tui.theme import TOKENS as _T

# local aliases — every value traces back to a frozen theme token
INK: str = _T["ink"]
PANEL: str = _T["panel"]
LINE: str = _T["line"]
MUTED: str = _T["muted"]
BODY: str = _T["body"]
ACCENT: str = _T["accent"]
CYAN: str = _T["cyan"]
EMERALD: str = _T["emerald"]
ROSE: str = _T["rose"]
AMBER: str = _T["amber"]
THOUGHT: str = _T["thought"]
MONO: str = _T["mono"]

# ── scripted demo data ──────────────────────────────────────────────────────
GOAL = "Add a /api/health endpoint to the server and cover it with tests."

THOUGHT_1 = (
    "The goal touches the FastAPI layer and the test suite. Before writing "
    "anything I want to see how existing routes are declared in app.py so the "
    "new endpoint matches house style — decorators, response shape, error "
    "handling. Then I'll add the smallest possible test that exercises the "
    "route through the real ASGI app, and let the sandbox pytest run be the "
    "verdict instead of assuming it works."
)
THOUGHT_2 = (
    "Routes are plain @app.get decorators returning dicts, and tests live "
    "flat under tests/ with httpx AsyncClient. I'll mirror both exactly: a "
    "JSON body of {status, session_count} so the endpoint is actually useful "
    "for the launcher's health probe, then a test that asserts 200 and the "
    "payload keys."
)

PLAN = [
    ("inspect", "Inspect existing route + test patterns", "rg · app.py, tests/"),
    ("edit", "Add GET /api/health to server/app.py", "file edit"),
    ("test", "Add tests/test_health.py", "new file · 3 cases"),
    ("verify", "Run full pytest suite in sandbox", "pytest -q"),
]

CMD_1 = (
    "rg -n '@app\\.(get|post)' src/arcen/server/app.py",
    [
        '378:@app.get("/api/health")',
        '383:@app.post("/api/run")',
        '415:@app.delete("/api/run/{run_id}")',
        '464:@app.get("/api/stream")',
        '574:@app.get("/api/config")',
    ],
    "exit 0 · 0.41s",
)

CMD_2 = (
    "cat > tests/test_health.py <<'EOF' … EOF",
    ["wrote 41 lines · tests/test_health.py"],
    "exit 0 · 0.08s",
)

DIFF = (
    "src/arcen/server/app.py",
    [
        ("+", '@app.get("/api/health")'),
        ("+", "def health() -> dict:"),
        ("+", '    return {"status": "ok", "session_count": len(state.sessions)}'),
    ],
    "tests/test_health.py",
    [
        ("+", "async def test_health_returns_ok(client):"),
        ("+", "    r = await client.get(\"/api/health\")"),
        ("+", "    assert r.status_code == 200"),
        ("+", "    assert r.json()[\"status\"] == \"ok\""),
    ],
)

VERIFY = [
    ("imports resolve", "python -c import arcen.server.app", True),
    ("route returns 200 + json", "httpx AsyncClient GET /api/health", True),
    ("full suite green", "pytest -q · 361 passed", True),
]

ANSWER = (
    f"Added [{ACCENT}]GET /api/health[/] returning "
    f"[{MONO}]{{\"status\": \"ok\", \"session_count\": N}}[/], plus "
    f"[{ACCENT}]tests/test_health.py[/] with 3 cases (200, payload shape, "
    f"zero-session count). Full suite: [{EMERALD}]361 passed[/] in 6.2s, all "
    f"inside the quarantined sandbox with networking off. Nothing outside "
    f"the two files was touched."
)


# ── render helpers ─────────────────────────────────────────────────────────
def phase_pill(phase: str) -> Text:
    colors = {"DRAFT": ACCENT, "FORGE": CYAN, "TEMPER": AMBER,
              "DONE": EMERALD, "IDLE": MUTED}
    color = colors.get(phase, MUTED)
    text = Text()
    text.append("● ", style=color)
    text.append(phase, style=f"bold {color}")
    return text


def card(body, title: str, accent: str, spine: str = "◉") -> Table:
    grid = Table.grid(expand=True, padding=(0, 0))
    grid.add_column(width=3, justify="center")
    grid.add_column(ratio=1)
    panel = Panel(
        body,
        box=box.ROUNDED,
        border_style=LINE,
        title=Text(f" {title} ", style=f"bold {accent}"),
        title_align="left",
        padding=(0, 1),
    )
    grid.add_row(Text(spine, style=f"bold {accent}"), panel)
    return grid


def spine_break() -> Text:
    return Text(" │", style=LINE)


class Header(Static):
    def __init__(self) -> None:
        super().__init__()
        self.phase = "IDLE"

    def render(self):
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        left = Text()
        left.append("◆ ", style=f"bold {ACCENT}")
        left.append("ARCEN", style="bold #FFFFFF")
        left.append(" · console", style=MUTED)
        left.append("    ")
        left.append("session ", style=MUTED)
        left.append("s_8f2a41", style=MONO)
        left.append("   ")
        left.append("glm-5.1 · litellm", style=f"italic {MUTED}")
        right = Text()
        right.append("quarantine · net off", style=EMERALD)
        right.append("    ")
        right.append(dt.datetime.now().strftime("%H:%M:%S"), style=MUTED)
        right.append("    ")
        right.append(phase_pill(self.phase))
        grid.add_row(left, right)
        return Panel(grid, box=box.SQUARE, border_style=LINE,
                     style=PANEL, padding=(0, 1))


class Narration(Static):
    def __init__(self) -> None:
        super().__init__()
        self.items: list = []
        self._scroll: VerticalScroll | None = None

    def bind_scroll(self, parent: VerticalScroll) -> None:
        self._scroll = parent

    def _sync(self) -> None:
        # update() re-renders AND re-measures; plain refresh() would keep the
        # initial zero-item size and clip the whole narration.
        self.update(Group(*self.items) if self.items else Text(""))
        if self._scroll is not None:
            self.app.call_after_refresh(
                lambda: self._scroll.scroll_end(animate=False)
            )

    def push(self, renderable) -> None:
        self.items.append(renderable)
        self._sync()

    def replace_last(self, renderable) -> None:
        self.items[-1] = renderable
        self._sync()

    def render(self):
        return Group(*self.items) if self.items else Text("")


class Rail(Static):
    def __init__(self) -> None:
        super().__init__()
        self.steps_done = 0
        self.steps_total = len(PLAN)
        self.phase_idx = 0
        self.tokens = 0
        self.cost = 0.0
        self.tools: list[str] = []

    def render(self):
        phases = ["DRAFT", "FORGE", "TEMPER", "DONE"]
        colors = [ACCENT, CYAN, AMBER, EMERALD]
        timeline = Text()
        for i, phase in enumerate(phases):
            if i < self.phase_idx:
                timeline.append("● ", style=colors[i]).append(phase, style=EMERALD)
            elif i == self.phase_idx:
                timeline.append("◐ ", style=f"bold {colors[i]}")
                timeline.append(phase, style=f"bold {colors[i]}")
            else:
                timeline.append("○ ", style=LINE).append(phase, style=MUTED)
            if i < len(phases) - 1:
                timeline.append("\n")

        frac = self.steps_done / max(self.steps_total, 1)
        width = 16
        filled = round(frac * width)
        bar = Text()
        bar.append("█" * filled, style=ACCENT)
        bar.append("░" * (width - filled), style=LINE)

        tok_frac = min(self.tokens / 128_000, 1.0)
        tbar = Text()
        tbar.append("█" * round(tok_frac * width), style=CYAN)
        tbar.append("░" * (width - round(tok_frac * width)), style=LINE)

        chips = Text()
        for tool in sorted(set(self.tools)):
            chips.append(f" {tool} ", style=f"bold {CYAN} on {PANEL}")
            chips.append(" ")

        grid = Table.grid(expand=True)
        grid.add_column()
        grid.add_row(Text("RUN PROGRESS", style=f"bold {MUTED}"))
        grid.add_row(Text(
            f"step {self.steps_done}/{self.steps_total}", style=f"bold {BODY}"
        ))
        grid.add_row(bar)
        grid.add_row(Text(""))
        grid.add_row(Text("PHASES", style=f"bold {MUTED}"))
        grid.add_row(timeline)
        grid.add_row(Text(""))
        grid.add_row(Text("CONTEXT WINDOW", style=f"bold {MUTED}"))
        grid.add_row(tbar)
        grid.add_row(Text(f"{self.tokens:,} / 128,000 tok", style=MUTED))
        grid.add_row(Text(""))
        grid.add_row(Text("SPEND", style=f"bold {MUTED}"))
        grid.add_row(Text(f"${self.cost:.4f}", style=BODY))
        grid.add_row(Text(""))
        grid.add_row(Text("TOOLS", style=f"bold {MUTED}"))
        grid.add_row(chips if chips else Text("—", style=MUTED))
        grid.add_row(Text(""))
        grid.add_row(Text("ENVIRONMENT", style=f"bold {MUTED}"))
        grid.add_row(Text("sandbox  ", style=MUTED).append("proc-quarantine", style=MONO))
        grid.add_row(Text("network  ", style=MUTED).append("off", style=EMERALD))
        grid.add_row(Text("workdir  ", style=MUTED).append("/tmp/arcen-s-8f2a41", style=MONO))
        grid.add_row(Text(""))
        grid.add_row(Text("HARNESS", style=f"bold {MUTED}"))
        grid.add_row(Text("adopted@a1f3c9", style=f"italic {ACCENT}"))

        return Panel(grid, box=box.ROUNDED, border_style=LINE, style=PANEL,
                     padding=(1, 2), title=Text(" run state ", style=f"bold {MUTED}"))


class Footer(Static):
    def render(self):
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        hints = Text()
        for key, label in [("^C", "interrupt"), ("^G", "editor"),
                           ("/", "commands"), ("^R", "resume"), ("?", "help")]:
            hints.append(f" {key} ", style=f"bold {BODY} on {LINE}")
            hints.append(f" {label}   ", style=MUTED)
        live = Text()
        live.append("● ", style=f"blink {EMERALD}")
        live.append("LIVE", style=f"bold {EMERALD}")
        grid.add_row(hints, live)
        return Panel(grid, box=box.SQUARE, border_style=LINE, style=PANEL,
                     padding=(0, 1))


# ── card builders ───────────────────────────────────────────────────────────
def goal_card() -> Table:
    return card(Text(GOAL, style=BODY), "you · goal", MUTED, spine="◆")


def thought_card(text: str, streaming: bool,
                 label: str = "DRAFT · thinking") -> Table:
    body = Text()
    body.append(text, style=f"italic {THOUGHT}")
    if streaming:
        body.append("▍", style=f"blink {ACCENT}")
    return card(body, label, ACCENT)


def plan_card(statuses: list[str]) -> Table:
    body = Table.grid(expand=True, padding=(0, 1))
    body.add_column(width=3)
    body.add_column(ratio=1)
    body.add_column(justify="right")
    icons = {
        "pending": ("○", LINE, MUTED),
        "active": ("◐", f"bold {AMBER}", AMBER),
        "done": ("●", EMERALD, EMERALD),
        "fail": ("✕", ROSE, ROSE),
    }
    for (_, title, meta), status in zip(PLAN, statuses):
        icon, icon_style, _title_style = icons[status]
        body.add_row(
            Text(icon, style=icon_style),
            Text(title, style=BODY if status != "pending" else MUTED),
            Text(meta, style=f"italic {MUTED}"),
        )
    return card(body, "plan · 4 steps", ACCENT)


def command_card(cmd: str, output: list[str], footer: str | None,
                 streaming: bool) -> Table:
    body = Table.grid(expand=True)
    body.add_column()
    head = Text()
    head.append("$ ", style=f"bold {CYAN}")
    head.append(cmd, style=f"bold {MONO}")
    body.add_row(head)
    body.add_row(Text(""))
    for line in output:
        body.add_row(Text("  " + line, style=MUTED))
    if streaming:
        body.add_row(Text("  ▍", style=f"blink {CYAN}"))
    if footer:
        body.add_row(Text(""))
        body.add_row(Text(footer, style=f"italic {EMERALD}"))
    return card(body, "forge · bash", CYAN)


def diff_card(data) -> Table:
    left_path, left_lines, right_path, right_lines = data
    body = Table.grid(expand=True)
    body.add_column()
    body.add_row(Text(left_path, style=f"bold {MONO}"))
    for sign, line in left_lines:
        body.add_row(Text(f" {sign} {line}", style=EMERALD))
    body.add_row(Text(""))
    body.add_row(Text(right_path, style=f"bold {MONO}"))
    for sign, line in right_lines:
        body.add_row(Text(f" {sign} {line}", style=EMERALD))
    return card(body, "file.diff", CYAN)


def verify_card(rows: list[tuple[str, str, bool]] | None = None,
                active: str | None = None) -> Table:
    body = Table.grid(expand=True, padding=(0, 1))
    body.add_column(width=3)
    body.add_column(ratio=1)
    body.add_column(justify="right")
    rows = rows or []
    done_names = {row[0] for row in rows}
    for name, detail, _ok in rows:
        body.add_row(Text("✓", style=f"bold {EMERALD}"),
                     Text(name, style=BODY),
                     Text(detail, style=f"italic {MUTED}"))
    if active:
        body.add_row(Text("◐", style=f"bold {AMBER}"),
                     Text(active, style=AMBER),
                     Text("running…", style=f"italic {MUTED}"))
    for name, detail, _ok in VERIFY:
        if name not in done_names and name != active:
            body.add_row(Text("○", style=LINE),
                         Text(name, style=MUTED),
                         Text(detail, style=f"italic {MUTED}"))
    return card(body, "temper · verification", AMBER)


def answer_card() -> Table:
    return card(Text.from_markup(ANSWER), "answer", EMERALD, spine="◆")


# ── the app ─────────────────────────────────────────────────────────────────
class DemoApp(App):
    TITLE = "ARCEN console"
    CSS = f"""
    Screen {{ background: {INK}; }}
    #shell {{ layout: horizontal; height: 1fr; }}
    #stream {{ width: 1fr; height: 1fr; background: {INK}; scrollbar-size: 1 1; }}
    Rail {{ width: 38; height: 1fr; padding: 0 0 0 1; }}
    Header {{ height: auto; margin: 0 0 1 0; }}
    Footer {{ height: auto; margin: 1 0 0 0; }}
    Narration {{ width: 1fr; height: auto; padding: 0 1; }}
    """

    def __init__(self, headless_mode: bool = False) -> None:
        super().__init__()
        self.headless_mode = headless_mode
        self.phase_name = "boot"
        # durable checkpoint record — transient signals (e.g. "done"
        # immediately followed by "finished") stay observable to tests.
        self.phase_history: list[str] = ["boot"]
        self._phase_event = asyncio.Event()

    def compose(self) -> ComposeResult:
        self.header = Header()
        self.narration = Narration()
        self.rail = Rail()
        self.footer = Footer()
        yield self.header
        with Horizontal(id="shell"):
            with VerticalScroll(id="stream"):
                yield self.narration
            yield self.rail
        yield self.footer

    def _signal_phase(self, name: str, label: str | None = None) -> None:
        self.phase_name = name
        self.phase_history.append(name)
        if label:
            self.header.phase = label
            self.rail.phase_idx = ["DRAFT", "FORGE", "TEMPER", "DONE"].index(label)
        self.header.refresh()
        self.rail.refresh()
        self._phase_event.set()
        self._phase_event = asyncio.Event()

    async def wait_phase(self, name: str, timeout: float = 60.0) -> None:
        """Test/capture hook: block until the scripted driver reaches ``name``."""
        # Loop on the durable history, not the current phase name: a
        # transient signal such as "done" (immediately followed by
        # "finished") must still satisfy a waiter that arrived mid-flight.
        deadline = asyncio.get_running_loop().time() + timeout
        while name not in self.phase_history:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(
                    f"phase {name!r} never reached (at {self.phase_name!r})"
                )
            event = self._phase_event
            try:
                await asyncio.wait_for(event.wait(), timeout=remaining)
            except TimeoutError:
                pass
            await asyncio.sleep(0)

    async def stream_text(self, full: str, label: str) -> None:
        self.narration.push(thought_card("", True, label))
        words = full.split(" ")
        for i in range(len(words)):
            shown = " ".join(words[: i + 1])
            self.narration.replace_last(thought_card(shown, True, label))
            await asyncio.sleep(0.025)
        self.narration.replace_last(thought_card(full, False, label))

    async def stream_output(self, cmd: str, lines: list[str],
                            footer: str, tool: str) -> None:
        self.rail.tools.append(tool)
        shown: list[str] = []
        self.narration.push(command_card(cmd, shown, None, True))
        for line in lines:
            shown.append(line)
            self.narration.replace_last(command_card(cmd, shown, None, True))
            await asyncio.sleep(0.18)
        self.narration.replace_last(command_card(cmd, shown, footer, False))

    def update_plan(self, statuses: list[str]) -> None:
        self.narration.items[self.plan_index] = plan_card(statuses)
        self.narration._sync()

    async def driver(self) -> None:
        await asyncio.sleep(0.4)
        self.narration.push(goal_card())
        self.narration.push(spine_break())
        await asyncio.sleep(0.5)

        self._signal_phase("draft", "DRAFT")
        await self.stream_text(THOUGHT_1, "draft · thinking")
        self.narration.push(spine_break())
        self.narration.push(plan_card(["active", "pending", "pending", "pending"]))
        self.plan_index = len(self.narration.items) - 1
        await asyncio.sleep(0.8)
        self.rail.steps_done = 1
        self.rail.tokens, self.rail.cost = 1820, 0.0041
        self.rail.refresh()
        self.update_plan(["done", "active", "pending", "pending"])
        self._signal_phase("forge", "FORGE")

        await self.stream_output(*CMD_1, tool="bash")
        self._signal_phase("forge_mid")
        self.narration.push(spine_break())
        self.rail.tokens, self.rail.cost = 3640, 0.0092
        self.rail.refresh()

        await self.stream_text(THOUGHT_2, "forge · reasoning")
        self.narration.push(spine_break())
        self.update_plan(["done", "done", "active", "pending"])
        await self.stream_output(*CMD_2, tool="file")
        self.update_plan(["done", "done", "done", "active"])
        self.rail.steps_done = 3
        self.rail.tokens, self.rail.cost = 7410, 0.0198
        self.rail.refresh()
        self.narration.push(diff_card(DIFF))
        self.narration.push(spine_break())

        self._signal_phase("temper", "TEMPER")
        self.narration.push(verify_card(active=VERIFY[0][0]))
        await asyncio.sleep(0.9)
        partial = [VERIFY[0]]
        self.narration.replace_last(verify_card(partial, active=VERIFY[1][0]))
        await asyncio.sleep(0.9)
        partial = VERIFY[:2]
        self.narration.replace_last(verify_card(partial, active=VERIFY[2][0]))
        await asyncio.sleep(1.1)
        self.narration.replace_last(verify_card(VERIFY))
        self.rail.steps_done = 4
        self.rail.tokens, self.rail.cost = 12384, 0.0412
        self.rail.refresh()
        self.narration.push(spine_break())

        self._signal_phase("done", "DONE")
        self.narration.push(answer_card())
        self._signal_phase("finished")
        if self.headless_mode:
            # Let the final paint land, then exit cleanly with code 0.
            await asyncio.sleep(0.2)
            self.exit()

    def on_mount(self) -> None:
        self._signal_phase("boot")
        self.narration.bind_scroll(self.query_one("#stream", VerticalScroll))
        asyncio.create_task(self.driver())


def run_demo(argv: list[str] | None = None,
             headless: bool | None = None, size: tuple[int, int] = (132, 44)) -> int:
    """Entry point for ``arcen-tui --demo``.

    Auto-detects a missing TTY so CI runs render headlessly and exit 0.
    """
    if headless is None:
        headless = not sys.stdout.isatty()
    app = DemoApp(headless_mode=headless)
    if headless:
        app.run(headless=True, size=size)
    else:
        app.run()
    return 0
