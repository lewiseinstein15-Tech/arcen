"""Render the frozen 17 ARCEN events as Rich renderables.

Pure functions over wire dicts — no Textual, no screen, no globals — so the
whole event vocabulary is unit-testable on a headless machine. Colors mirror
the brand palette (docs/logo.svg, docs/architecture-diagram.html):

    DRAFT coral #FF6B5C · FORGE blue #5B9DFF · TEMPER green #4CC38A
    sub-agents purple #B58CFF · warning amber #E8B34B · text #E6E8EB
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

# ---------------------------------------------------------------- palette

CORAL = "#FF6B5C"
BLUE = "#5B9DFF"
GREEN = "#4CC38A"
PURPLE = "#B58CFF"
AMBER = "#E8B34B"
RED = "#FF5C5C"
TEXT = "#E6E8EB"
MUTED = "#9AA0A8"
FAINT = "#6B7178"

AGENT_STYLES = {
    "DRAFT": Style(color=CORAL, bold=True),
    "FORGE": Style(color=BLUE, bold=True),
    "TEMPER": Style(color=GREEN, bold=True),
}
SUB_STYLE = Style(color=PURPLE, bold=True)

MAX_INLINE = 160  # hard cap for a single compact line (args, result snippets)


# ---------------------------------------------------------------- helpers

def clock(ts: float) -> str:
    """Unix seconds → local HH:MM:SS; a zero/garbage ts renders as '--:--:--'."""
    try:
        if not ts:
            return "--:--:--"
        return datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "--:--:--"


def _prefix(ts: float, seq: Any, icon: str, icon_style: Style | None = None) -> Text:
    """The dim `HH:MM:SS #seq · icon` lead every event line starts with."""
    line = Text()
    line.append(f"{clock(ts)} ", style=Style(color=FAINT))
    line.append(f"#{seq:<4}", style=Style(color=FAINT))
    line.append(" ")
    line.append(icon, style=icon_style or Style(color=MUTED))
    line.append(" ")
    return line


def _agent_tag(name: str) -> Text:
    style = AGENT_STYLES.get(str(name).upper(), SUB_STYLE)
    return Text.assemble(Text(str(name), style=style), Text(" "))


def _compact(value: Any, limit: int = MAX_INLINE) -> str:
    """One-line JSON for tool args/results, ellipsized for the log width."""
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def _fold(text: str, style: Style | None = None, width: int = 100) -> Text:
    """Soft-wrapped body text that never escapes the widget width."""
    out = Text(text, style=style or Style(color=TEXT), overflow="fold")
    out.truncate(width * 24, overflow="ellipsis", pad=False)  # pathological guard
    return out


def _unknown(event: dict) -> Text:
    """Forward-compatible fallback for a wire type this build doesn't know."""
    line = _prefix(event.get("ts", 0.0), event.get("seq", "?"), "?")
    line.append(event.get("type", "unknown"), style=Style(color=AMBER))
    return line


# ---------------------------------------------------------------- per-type renderers

def _run_start(e: dict, width: int) -> Text:
    line = _prefix(e["ts"], e["seq"], "▶", Style(color=CORAL, bold=True))
    line.append("RUN ", style=Style(color=CORAL, bold=True))
    line.append(str(e.get("run_id", "")), style=Style(color=MUTED))
    line.append("  ")
    line.append(_compact(e.get("goal", ""), max(48, width - 30)), style=Style(color=TEXT, bold=True))
    return line


def _think(e: dict, width: int) -> Text:
    line = _prefix(e["ts"], e["seq"], "❯", Style(color=CORAL))
    line.append(_agent_tag(e.get("agent", "DRAFT")))
    line.append(_fold(str(e.get("text", "")), Style(color=TEXT), width - 18))
    return line


def _steps_lines(e: dict, *, update: bool) -> list[Text]:
    icon = "⟳" if update else "≡"
    style = Style(color=AMBER, bold=True) if update else Style(color=CORAL, bold=True)
    head = _prefix(e["ts"], e["seq"], icon, style)
    label = "RE-PLAN" if update else "PLAN"
    head.append(label + " ", style=style)
    head.append(str(e.get("agent", "DRAFT")), style=AGENT_STYLES.get("DRAFT"))
    if update and e.get("reason"):
        head.append(" — " + _compact(e["reason"], 120), style=Style(color=AMBER, italic=True))
    lines = [head]
    for step in e.get("steps") or []:
        row = Text("        ")
        row.append(f"{step.get('id', '?'):>2}. ", style=Style(color=FAINT))
        row.append(str(step.get("title", "")), style=Style(color=TEXT))
        tool = step.get("tool")
        if tool:
            row.append("  ")
            row.append(f"[{tool}]", style=Style(color=BLUE))
        lines.append(row)
    return lines


def _spawn(e: dict, width: int) -> Text:
    line = _prefix(e["ts"], e["seq"], "↳", Style(color=PURPLE, bold=True))
    line.append("SPAWN ", style=Style(color=PURPLE, bold=True))
    line.append(str(e.get("name", "")), style=SUB_STYLE)
    line.append(f"  (depth {e.get('depth', 1)}, parent {e.get('parent', 'DRAFT')})",
                style=Style(color=FAINT))
    line.append("\n        ")
    line.append(_compact(e.get("task", ""), max(40, width - 20)), style=Style(color=MUTED, italic=True))
    return line


def _spawn_done(e: dict, width: int) -> Text:
    ok = bool(e.get("ok"))
    line = _prefix(e["ts"], e["seq"], "↵", Style(color=GREEN if ok else RED, bold=True))
    line.append("DONE  ", style=Style(color=MUTED, bold=True))
    line.append(str(e.get("name", "")), style=SUB_STYLE)
    line.append("  ")
    verdict = "ok" if ok else "failed"
    line.append(verdict, style=Style(color=GREEN if ok else RED, bold=True))
    line.append(f"  · {e.get('calls', 0)} call(s) · {e.get('duration_s', 0):.2f}s",
                style=Style(color=FAINT))
    return line


def _command(e: dict, width: int) -> Text:
    line = _prefix(e["ts"], e["seq"], "⚙", Style(color=BLUE, bold=True))
    line.append(_agent_tag(e.get("agent", "FORGE")))
    line.append(f"step {e.get('step', '?')} ", style=Style(color=FAINT))
    line.append(str(e.get("tool", "")), style=Style(color=BLUE, bold=True))
    line.append("  " + _compact(e.get("args", {}), max(40, width - 24)),
                style=Style(color=MUTED))
    return line


def _command_done(e: dict, width: int) -> Text:
    ok = bool(e.get("ok"))
    line = _prefix(e["ts"], e["seq"], "✓" if ok else "✗",
                   Style(color=GREEN if ok else RED, bold=True))
    line.append("RESULT", style=Style(color=MUTED, bold=True))
    line.append(f"  step {e.get('step', '?')} · {e.get('duration_s', 0):.2f}s",
                style=Style(color=FAINT))
    result = e.get("result")
    if isinstance(result, dict):
        if not ok and (result.get("error") or result.get("detail")):
            body = str(result.get("error") or result.get("detail"))
        elif "stdout" in result:
            body = str(result.get("stdout") or "").strip() or "(no output)"
        else:
            body = _compact(result, max(40, width - 24))
    else:
        body = str(result)
    line.append("\n        ")
    line.append(_compact(body, max(40, width - 12)),
                style=Style(color=GREEN if ok else RED))
    return line


def _file_diff(e: dict, width: int) -> Panel:
    path = str(e.get("path", ""))
    patch = str(e.get("patch", ""))
    body = Text()
    for raw in patch.splitlines() or ["(empty patch)"]:
        if raw.startswith(("+++", "---")):
            body.append(raw + "\n", style=Style(color=FAINT, bold=True))
        elif raw.startswith("@@"):
            body.append(raw + "\n", style=Style(color=PURPLE))
        elif raw.startswith("+"):
            body.append(raw + "\n", style=Style(color=GREEN))
        elif raw.startswith("-"):
            body.append(raw + "\n", style=Style(color=RED))
        else:
            body.append(raw + "\n", style=Style(color=MUTED))
    head = Text.assemble(Text("✎ FILE DIFF  ", style=Style(color=BLUE, bold=True)),
                         Text(path, style=Style(color=TEXT, bold=True)))
    return Panel(body, title=head, border_style=Style(color=BLUE),
                 expand=False, padding=(0, 1))


def _verify_start(e: dict, width: int) -> Text:
    line = _prefix(e["ts"], e["seq"], "⬢", Style(color=GREEN, bold=True))
    line.append(_agent_tag(e.get("agent", "TEMPER")))
    line.append("adversarial verification", style=Style(color=GREEN, bold=True))
    line.append("  target " + _compact(e.get("target", ""), max(30, width - 40)),
                style=Style(color=FAINT))
    return line


def _step_pass(e: dict, width: int) -> list[Text]:
    head = _prefix(e["ts"], e["seq"], "✓", Style(color=GREEN, bold=True))
    head.append("PASS", style=Style(color=GREEN, bold=True))
    head.append(f"  step {e.get('step', '?')}", style=Style(color=FAINT))
    lines = [head]
    for check in e.get("checks") or []:
        lines.append(Text("        " + _compact(check, max(40, width - 12)),
                          style=Style(color=GREEN)))
    return lines


def _step_fail(e: dict, width: int) -> list[Text]:
    head = _prefix(e["ts"], e["seq"], "✗", Style(color=RED, bold=True))
    head.append("FAIL", style=Style(color=RED, bold=True))
    head.append(f"  step {e.get('step', '?')} · retry {e.get('retry', 0)}",
                style=Style(color=FAINT))
    body = Text("        " + _compact(str(e.get("reason", "")), max(40, width - 12)),
                style=Style(color=RED))
    return [head, body]


def _answer(e: dict, width: int) -> Panel:
    head = Text("❯❯ ANSWER", style=Style(color=CORAL, bold=True))
    return Panel(_fold(str(e.get("text", "")), width=max(20, width - 8)),
                 title=head, border_style=Style(color=CORAL),
                 expand=False, padding=(0, 1))


def _memory(e: dict, width: int) -> Text:
    line = _prefix(e["ts"], e["seq"], "◍", Style(color=PURPLE))
    line.append(f"MEMORY {e.get('op', 'write')} ", style=Style(color=PURPLE, bold=True))
    line.append(str(e.get("entity", "")), style=Style(color=TEXT))
    line.append(" — " + _compact(e.get("fact", ""), max(40, width - 24)),
                style=Style(color=MUTED))
    return line


def _usage(e: dict, width: int) -> Text:
    tokens = e.get("tokens") or {}
    line = _prefix(e["ts"], e["seq"], "∑", Style(color=FAINT))
    line.append("USAGE ", style=Style(color=MUTED, bold=True))
    line.append(f"in {tokens.get('input', 0)}  out {tokens.get('output', 0)} tokens",
                style=Style(color=MUTED))
    line.append(f"  ·  ${float(e.get('cost_usd', 0)):.4f}", style=Style(color=FAINT))
    return line


def _run_done(e: dict, width: int) -> list[Any]:
    status = str(e.get("status", ""))
    color = {"ok": GREEN, "failed": RED, "interrupted": AMBER}.get(status, MUTED)
    head = _prefix(e["ts"], e["seq"], "■", Style(color=color, bold=True))
    head.append("RUN ", style=Style(color=color, bold=True))
    head.append(status.upper(), style=Style(color=color, bold=True))
    head.append(f"  · {e.get('steps', 0)} step(s) · {e.get('duration_s', 0):.2f}s",
                style=Style(color=FAINT))
    return [Rule(style=Style(color=FAINT)), head]


def _run_error(e: dict, width: int) -> Panel:
    body = Text()
    body.append(str(e.get("code", "ERROR")) + "\n", style=Style(color=RED, bold=True))
    body.append(str(e.get("message", "")), style=Style(color=TEXT))
    head = Text("✖ RUN ERROR", style=Style(color=RED, bold=True))
    return Panel(body, title=head, border_style=Style(color=RED),
                 expand=False, padding=(0, 1))


_DISPATCH = {
    "run.start": _run_start,
    "think": _think,
    "plan": lambda e, w: _steps_lines(e, update=False),
    "plan.update": lambda e, w: _steps_lines(e, update=True),
    "spawn": _spawn,
    "spawn.done": _spawn_done,
    "command": _command,
    "command.done": _command_done,
    "file.diff": _file_diff,
    "verify.start": _verify_start,
    "step.pass": _step_pass,
    "step.fail": _step_fail,
    "answer": _answer,
    "memory": _memory,
    "usage": _usage,
    "run.done": _run_done,
    "run.error": _run_error,
}


def render_event(event: dict, width: int = 100) -> Any:
    """Render one wire event. Always returns ONE drawable renderable.

    Multi-line renderers return lists; they are wrapped in a Group so a
    RichLog never prints a Python list's repr.
    """
    renderer = _DISPATCH.get(str(event.get("type", "")))
    if renderer is None:
        return _unknown(event)
    rendered = renderer(event, width)
    if isinstance(rendered, list):
        return Group(*rendered)
    return rendered


# ---------------------------------------------------------------- summaries

def render_sandbox(status: dict) -> Table:
    """The /api/sandbox/status decision as a two-column key/value table."""
    table = Table(show_header=False, box=None, padding=(0, 1), expand=False)
    table.add_column(style=Style(color=FAINT), no_wrap=True)
    table.add_column(style=Style(color=TEXT))
    effective = str(status.get("effective", status.get("backend", "?")))
    degraded = bool(status.get("degraded"))
    backend_color = AMBER if degraded or effective == "process" else GREEN
    rows = [
        ("configured", str(status.get("backend", "auto"))),
        ("selected", Text(effective, style=Style(color=backend_color, bold=True))),
        ("docker daemon", "present" if status.get("docker_available") else "absent"),
        ("sandbox image", "present" if status.get("image_present") else "absent"),
        ("image", str(status.get("image", ""))),
        ("degraded", Text("true" if degraded else "false",
                          style=Style(color=AMBER if degraded else GREEN, bold=True))),
        ("reason", str(status.get("reason", ""))),
    ]
    for key, value in rows:
        table.add_row(key, value)
    return table


def render_config(cfg: dict) -> Table:
    """The redacted GET /api/config view — secrets stay redacted, always."""
    table = Table(show_header=False, box=None, padding=(0, 1), expand=False)
    table.add_column(style=Style(color=FAINT), no_wrap=True)
    table.add_column(style=Style(color=TEXT))
    provider = cfg.get("provider") or {}
    for key in ("name", "model", "base_url", "api_key"):
        table.add_row(f"provider.{key}", str(provider.get(key, "") or "—"))
    agents = cfg.get("agents") or {}
    for name, block in agents.items():
        if isinstance(block, dict):
            table.add_row(f"agents.{name}.model", str(block.get("model") or "inherit"))
    sandbox = cfg.get("sandbox") or {}
    table.add_row("sandbox.backend", str(sandbox.get("backend", "auto")))
    mcps = cfg.get("mcps") or []
    table.add_row("mcps", f"{len(mcps)} declared" if mcps else "none")
    plugins = (cfg.get("plugins") or {}).get("enabled") or []
    table.add_row("plugins", ", ".join(plugins) if plugins else "none")
    return table


def welcome(server_url: str) -> Panel:
    """Boot banner shown before the first event."""
    body = Text()
    body.append("Agentic reasoning. Code. Engineer.\n", style=Style(color=CORAL, bold=True))
    body.append("DRAFT plans · FORGE executes · TEMPER verifies — every step narrated live.\n\n",
                style=Style(color=MUTED))
    body.append("Server: ", style=Style(color=FAINT))
    body.append(server_url, style=Style(color=BLUE))
    body.append("\nType a goal and press Enter. Press ", style=Style(color=MUTED))
    body.append("h", style=Style(color=TEXT, bold=True))
    body.append(" for keybindings, ", style=Style(color=MUTED))
    body.append("q", style=Style(color=TEXT, bold=True))
    body.append(" to quit.", style=Style(color=MUTED))
    return Panel(body, border_style=Style(color=CORAL), expand=False, padding=(1, 2))


def error_banner(message: str) -> Panel:
    return Panel(Text(message, style=Style(color=RED)),
                 title=Text("✖ ERROR", style=Style(color=RED, bold=True)),
                 border_style=Style(color=RED), expand=False, padding=(0, 1))
