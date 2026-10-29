"""ARCEN TUI prototype — self-streaming demo (standalone, no arcen imports).

Run live:   python prototype/arcen_tui_demo.py
Screenshots are captured headlessly by prototype/capture.py.

Design language: "mission control" — calm dark ink, one violet accent,
a narration spine down the left, streaming italic thoughts, cards for
every tool action, and a status rail for at-a-glance run state.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import random

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Static

# ── design tokens ───────────────────────────────────────────────────────────
INK        = "#0B0E14"   # app background
PANEL      = "#10141D"   # card surface
LINE       = "#1D2430"   # borders / spine
MUTED      = "#7D8699"   # secondary text
BODY       = "#DCE2EE"   # primary text
ACCENT     = "#A78BFA"   # violet — ARCEN brand accent
CYAN       = "#7DD3FC"   # forge / tool accent
EMERALD    = "#34D399"   # pass
ROSE       = "#FB7185"   # fail
AMBER      = "#FBBF24"   # active / warn
THOUGHT    = "#9AA6BF"   # italic thought text
MONO       = "#C9D4E8"

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
    ("inspect",  "Inspect existing route + test patterns", "rg · app.py, tests/"),
    ("edit",     "Add GET /api/health to server/app.py",   "file edit"),
    ("test",     "Add tests/test_health.py",               "new file · 3 cases"),
    ("verify",   "Run full pytest suite in sandbox",       "pytest -q"),
]

CMD_1 = ("rg -n '@app\\.(get|post)' src/arcen/server/app.py",
         ["378:@app.get(\"/api/health\")",
          "383:@app.post(\"/api/run\")",
          "415:@app.delete(\"/api/run/{run_id}\")",
          "464:@app.get(\"/api/stream\")",
          "574:@app.get(\"/api/config\")"],
         "exit 0 · 0.41s")

CMD_2 = ("cat > tests/test_health.py <<'EOF' … EOF",
         ["wrote 41 lines · tests/test_health.py"],
         "exit 0 · 0.08s")

DIFF = (
    "src/arcen/server/app.py",
    [("+", "@app.get(\"/api/health\")"),
     ("+", "def health() -> dict:"),
     ("+", "    return {\"status\": \"ok\", \"session_count\": len(state.sessions)}")],
    "tests/test_health.py",
    [("+", "async def test_health_returns_ok(client):"),
     ("+", "    r = await client.get(\"/api/health\")"),
     ("+", "    assert r.status_code == 200"),
     ("+", "    assert r.json()[\"status\"] == \"ok\"")],
)

VERIFY = [
    ("imports resolve",         "python -c import arcen.server.app", True),
    ("route returns 200 + json", "httpx AsyncClient GET /api/health", True),
    ("full suite green",        "pytest -q · 361 passed",            True),
]

ANSWER = (
    f"Added [#A78BFA]GET /api/health[/] returning "
    f"[#C9D4E8]{{\"status\": \"ok\", \"session_count\": N}}[/], plus "
    f"[#A78BFA]tests/test_health.py[/] with 3 cases (200, payload shape, "
    f"zero-session count). Full suite: [#34D399]361 passed[/] in 6.2s, all "
    f"inside the quarantined sandbox with networking off. Nothing outside "
    f"the two files was touched."
)


# ── render helpers ─────────────────────────────────────────────────────────
def pill(text: str, color: str) -> Text:
    t = Text()
    t.append(" " + text + " ", style=f"bold {color} on #{int(color[1:3],16)//6:02x}"
                                     f"{int(color[3:5],16)//6:02x}{int(color[5:7],16)//6:02x}")
    return t


def phase_pill(phase: str) -> Text:
    colors = {"DRAFT": ACCENT, "FORGE": CYAN, "TEMPER": AMBER, "DONE": EMERALD,
              "IDLE": MUTED}
    c = colors.get(phase, MUTED)
    t = Text()
    t.append("● ", style=c)
    t.append(phase, style=f"bold {c}")
    return t


def card(body, title: str, accent: str, spine: str = "◉") -> Table:
    grid = Table.grid(expand=True, padding=(0, 0))
    grid.add_column(width=3, justify="center")
    grid.add_column(ratio=1)
    node = Text(spine, style=f"bold {accent}")
    panel = Panel(
        body,
        box=__import__("rich").box.ROUNDED,
        border_style=LINE,
        title=Text(f" {title} ", style=f"bold {accent}"),
        title_align="left",
        padding=(0, 1),
        subtitle=None,
    )
    grid.add_row(node, panel)
    return grid


def spine_break() -> Text:
    return Text(" │", style=LINE)


# ── widgets ─────────────────────────────────────────────────────────────────
class Header(Static):
    def __init__(self) -> None:
        super().__init__()
        self.phase = "IDLE"

    def render(self):
        t = Table.grid(expand=True)
        t.add_column(justify="left")
        t.add_column(justify="right")
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
        right.append(Text.from_markup(dt.datetime.now().strftime("%H:%M:%S"), style=MUTED))
        right.append("    ")
        right.append(phase_pill(self.phase))
        t.add_row(left, right)
        return Panel(t, box=__import__("rich").box.SQUARE, border_style=LINE,
                     style=PANEL, padding=(0, 1))


class Narration(Static):
    def __init__(self) -> None:
        super().__init__()
        self.items: list = []
        self._scroll: VerticalScroll | None = None

    def bind_scroll(self, parent: VerticalScroll) -> None:
        self._scroll = parent

    def _sync(self) -> None:
        # Static.update() re-renders AND re-measures, so the parent
        # VerticalScroll grows the virtual viewport. Plain refresh() repaints
        # with the old (zero-item) size and clips the whole narration.
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
        tl = Text()
        for i, p in enumerate(phases):
            if i < self.phase_idx:
                tl.append("● ", style=colors[i]).append(p, style=EMERALD)
            elif i == self.phase_idx:
                tl.append("◐ ", style=f"bold {colors[i]}").append(p, style=f"bold {colors[i]}")
            else:
                tl.append("○ ", style=LINE).append(p, style=MUTED)
            if i < len(phases) - 1:
                tl.append("\n")

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

        count = Text()
        count.append(f"step {self.steps_done}/{self.steps_total}", style=f"bold {BODY}")
        g = Table.grid(expand=True)
        g.add_column()
        g.add_row(Text("RUN PROGRESS", style=f"bold {MUTED}"))
        g.add_row(count)
        g.add_row(bar)
        g.add_row(Text(""))
        g.add_row(Text("PHASES", style=f"bold {MUTED}"))
        g.add_row(tl)
        g.add_row(Text(""))
        g.add_row(Text("CONTEXT WINDOW", style=f"bold {MUTED}"))
        g.add_row(tbar)
        g.add_row(Text(f"{self.tokens:,} / 128,000 tok", style=MUTED))
        g.add_row(Text(""))
        g.add_row(Text("SPEND", style=f"bold {MUTED}"))
        g.add_row(Text(f"${self.cost:.4f}", style=BODY))
        g.add_row(Text(""))
        g.add_row(Text("TOOLS", style=f"bold {MUTED}"))
        g.add_row(chips if chips else Text("—", style=MUTED))
        g.add_row(Text(""))
        g.add_row(Text("ENVIRONMENT", style=f"bold {MUTED}"))
        g.add_row(Text("sandbox  ", style=MUTED).append("proc-quarantine", style=MONO))
        g.add_row(Text("network  ", style=MUTED).append("off", style=EMERALD))
        g.add_row(Text("workdir  ", style=MUTED).append("/tmp/arcen-s-8f2a41", style=MONO))
        g.add_row(Text(""))
        g.add_row(Text("HARNESS", style=f"bold {MUTED}"))
        g.add_row(Text("adopted@a1f3c9", style=f"italic {ACCENT}"))

        return Panel(g, box=__import__("rich").box.ROUNDED, border_style=LINE,
                     style=PANEL, padding=(1, 2),
                     title=Text(" run state ", style=f"bold {MUTED}"))


class Footer(Static):
    def render(self):
        t = Table.grid(expand=True)
        t.add_column(justify="left")
        t.add_column(justify="right")
        hints = Text()
        for key, label in [("^C", "interrupt"), ("^G", "editor"),
                           ("/", "commands"), ("^R", "resume"), ("?", "help")]:
            hints.append(f" {key} ", style=f"bold {BODY} on {LINE}")
            hints.append(f" {label}   ", style=MUTED)
        live = Text()
        live.append("● ", style=f"blink {EMERALD}")
        live.append("LIVE", style=f"bold {EMERALD}")
        t.add_row(hints, live)
        return Panel(t, box=__import__("rich").box.SQUARE, border_style=LINE,
                     style=PANEL, padding=(0, 1))


# ── card builders ───────────────────────────────────────────────────────────
def goal_card() -> Table:
    body = Text(GOAL, style=BODY)
    return card(body, "you · goal", MUTED, spine="◆")


def thought_card(text: str, streaming: bool, label: str = "DRAFT · thinking") -> Table:
    body = Text()
    body.append(text, style=f"italic {THOUGHT}")
    if streaming:
        body.append("▍", style=f"blink {ACCENT}")
    return card(body, label, ACCENT, spine="◉")


def plan_card(statuses: list[str]) -> Table:
    body = Table.grid(expand=True, padding=(0, 1))
    body.add_column(width=3)
    body.add_column(ratio=1)
    body.add_column(justify="right")
    icons = {"pending": ("○", LINE, MUTED), "active": ("◐", f"bold {AMBER}", AMBER),
             "done": ("●", EMERALD, EMERALD), "fail": ("✕", ROSE, ROSE)}
    for (_, title, meta), st in zip(PLAN, statuses):
        icon, icon_style, title_style = icons[st]
        body.add_row(Text(icon, style=icon_style),
                     Text(title, style=BODY if st != "pending" else MUTED),
                     Text(meta, style=f"italic {MUTED}"))
    return card(body, "plan · 4 steps", ACCENT)


def command_card(cmd: str, output: list[str], footer: str | None, streaming: bool) -> Table:
    body = Table.grid(expand=True, padding=(0, 0))
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
    return card(body, "forge · bash", CYAN, spine="◉")


def diff_card(d) -> Table:
    _, left_lines, _, right_lines = d
    body = Table.grid(expand=True)
    body.add_column()
    body.add_row(Text(d[0], style=f"bold {MONO}"))
    for sign, line in left_lines:
        body.add_row(Text(f" {sign} {line}", style=EMERALD))
    body.add_row(Text(""))
    body.add_row(Text(d[2], style=f"bold {MONO}"))
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
    done_names = {r[0] for r in rows}
    for name, detail, ok in rows:
        body.add_row(Text("✓", style=f"bold {EMERALD}"),
                     Text(name, style=BODY),
                     Text(detail, style=f"italic {MUTED}"))
    if active:
        body.add_row(Text("◐", style=f"bold {AMBER}"),
                     Text(active, style=AMBER),
                     Text("running…", style=f"italic {MUTED}"))
    for name, detail, _ in VERIFY:
        if name not in done_names and name != active:
            body.add_row(Text("○", style=LINE),
                         Text(name, style=MUTED),
                         Text(detail, style=f"italic {MUTED}"))
    return card(body, "temper · verification", AMBER)


def answer_card() -> Table:
    body = Text.from_markup(ANSWER)
    return card(body, "answer", EMERALD, spine="◆")


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

    def __init__(self) -> None:
        super().__init__()
        self.phase_name = "boot"
        self._phase_event = asyncio.Event()

    def compose(self) -> ComposeResult:
        self.header = Header()
        self.narration = Narration()
        self.rail = Rail()
        self.footer = Footer()
        yield self.header
        with Horizontal(id="shell"):
            with VerticalScroll(id="stream") as scroll:
                yield self.narration
            yield self.rail
        yield self.footer

    def _signal_phase(self, name: str, label: str | None = None) -> None:
        self.phase_name = name
        if label:
            self.header.phase = label
            idx = ["DRAFT", "FORGE", "TEMPER", "DONE"].index(label)
            self.rail.phase_idx = idx
        self.header.refresh()
        self.rail.refresh()
        self._phase_event.set()
        self._phase_event = asyncio.Event()

    def set_phase(self, name: str, label: str | None = None) -> None:
        self._signal_phase(name, label)

    async def wait_phase(self, name: str, timeout: float = 60.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while self.phase_name != name:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"phase {name!r} never reached (at {self.phase_name!r})")
            event = self._phase_event
            try:
                await asyncio.wait_for(event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(0)

    async def stream_text(self, full: str, label: str) -> None:
        card = thought_card("", True, label)
        self.narration.push(card)
        shown = ""
        words = full.split(" ")
        for i, word in enumerate(words):
            shown = " ".join(words[: i + 1])
            self.narration.replace_last(thought_card(shown, True, label))
            await asyncio.sleep(0.025)
        self.narration.replace_last(thought_card(full, False, label))

    async def stream_output(self, cmd: str, lines: list[str], footer: str, tool: str) -> None:
        self.rail.tools.append(tool)
        shown: list[str] = []
        self.narration.push(command_card(cmd, shown, None, True))
        for line in lines:
            shown.append(line)
            self.narration.replace_last(command_card(cmd, shown, None, True))
            await asyncio.sleep(0.18)
        self.narration.replace_last(command_card(cmd, shown, footer, False))

    async def driver(self) -> None:
        await asyncio.sleep(0.4)
        # goal
        self.narration.push(goal_card())
        self.narration.push(spine_break())
        await asyncio.sleep(0.5)

        # DRAFT — thought + plan
        self.set_phase("draft", "DRAFT")
        await self.stream_text(THOUGHT_1, "draft · thinking")
        self.narration.push(spine_break())
        self.narration.push(plan_card(["active", "pending", "pending", "pending"]))
        self.plan_index = len(self.narration.items) - 1
        await asyncio.sleep(0.8)
        self.rail.steps_done = 1
        self.rail.tokens, self.rail.cost = 1820, 0.0041
        self.rail.refresh()
        self.update_plan(["done", "active", "pending", "pending"])
        self.set_phase("forge", "FORGE")

        # FORGE — inspect
        await self.stream_output(*CMD_1, tool="bash")
        self._signal_phase("forge_mid")
        self.narration.push(spine_break())
        self.rail.tokens, self.rail.cost = 3640, 0.0092
        self.rail.refresh()

        # second thought + edits
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

        # TEMPER
        self.set_phase("temper", "TEMPER")
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

        # answer
        self.set_phase("done", "DONE")
        self.narration.push(answer_card())
        self._signal_phase("finished")

    def update_plan(self, statuses: list[str]) -> None:
        self.narration.items[self.plan_index] = plan_card(statuses)
        self.narration.refresh()

    async def on_mount(self) -> None:
        self.set_phase("boot")
        self.narration.bind_scroll(self.query_one("#stream", VerticalScroll))
        asyncio.create_task(self.driver())

    def live_main(self) -> None:
        self.run()


if __name__ == "__main__":
    DemoApp().run()
