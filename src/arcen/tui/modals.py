"""Read-only configuration and sandbox views, fetched from the server."""

from __future__ import annotations

from typing import ClassVar
from urllib.parse import urlsplit, urlunsplit

import httpx
from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from arcen.tui.client import ArcenAPIError, ArcenClient
from arcen.tui.theme import TOKENS


def _safe_url(value: object) -> str:
    """Don't show userinfo, query parameters or fragments from provider URLs."""
    raw = str(value or "")
    if not raw:
        return "—"
    try:
        url = urlsplit(raw)
        host = url.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if url.port:
            host += f":{url.port}"
        return urlunsplit((url.scheme, host, url.path, "", "")) if url.scheme else "<configured>"
    except ValueError:
        return "<configured>"


def _table(rows: list[tuple[str, object]]) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=TOKENS["muted"], no_wrap=True)
    table.add_column(style=TOKENS["body"], overflow="fold")
    for key, value in rows:
        table.add_row(key, value if isinstance(value, Text) else str(value))
    return table


def config_view(cfg: dict) -> Table:
    provider = cfg.get("provider") if isinstance(cfg.get("provider"), dict) else {}
    agents = cfg.get("agents") if isinstance(cfg.get("agents"), dict) else {}
    sandbox = cfg.get("sandbox") if isinstance(cfg.get("sandbox"), dict) else {}
    plugins = cfg.get("plugins") if isinstance(cfg.get("plugins"), dict) else {}
    enabled = plugins.get("enabled") or []
    rows = [
        ("provider", provider.get("name") or "—"),
        ("model", provider.get("model") or "—"),
        ("endpoint", _safe_url(provider.get("base_url"))),
        ("api key", "<redacted>" if provider.get("api_key") else "not set"),
    ]
    rows.extend(
        (f"{name} model", block.get("model") or "inherit")
        for name, block in agents.items()
        if isinstance(block, dict)
    )
    rows.extend(
        [
            ("sandbox backend", sandbox.get("backend") or "auto"),
            ("MCP servers", len(cfg.get("mcps") or [])),
            ("plugins", ", ".join(map(str, enabled)) if enabled else "none"),
        ]
    )
    return _table(rows)


def sandbox_view(status: dict) -> Table:
    degraded = bool(status.get("degraded"))
    effective = str(status.get("effective") or "unknown")
    marker = Text(
        "DEGRADED" if degraded else "READY",
        style=f"bold {TOKENS['amber' if degraded else 'emerald']}",
    )
    return _table(
        [
            ("status", marker),
            ("configured", status.get("backend") or "auto"),
            ("selected", effective),
            ("docker daemon", "present" if status.get("docker_available") else "absent"),
            ("sandbox image", "present" if status.get("image_present") else "absent"),
            ("image", status.get("image") or "—"),
            ("reason", status.get("reason") or "—"),
        ]
    )


class InfoScreen(ModalScreen[None]):
    """Read-only parity with the legacy config view; no secret writes."""

    CSS = """
    InfoScreen { align: center middle; background: #0B0E14 75%; }
    #info-modal { width: 76; max-width: 96%; height: 80%; border: round #A78BFA;
        background: #10141D; padding: 1 2; }
    #info-body { height: auto; width: 100%; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape,q,enter", "close", "Close", priority=True)]

    def __init__(self, client: ArcenClient, *, sandbox_only: bool = False) -> None:
        super().__init__()
        self.client, self.sandbox_only = client, sandbox_only

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="info-modal"):
            yield Static("Loading…", id="info-body")

    async def on_mount(self) -> None:
        body = self.query_one("#info-body", Static)
        items = []
        if not self.sandbox_only:
            items.append(
                Text("CONFIGURATION  /  redacted · read-only\n", style=f"bold {TOKENS['accent']}")
            )
            try:
                cfg = await self.client.get_config()
                items.append(config_view(cfg))
            except (ArcenAPIError, httpx.HTTPError, OSError, ValueError) as exc:
                items.append(Text(f"Configuration unavailable: {exc}", style=TOKENS["rose"]))
        items.append(Text("\nSANDBOX  /  runtime decision\n", style=f"bold {TOKENS['accent']}"))
        try:
            sandbox = await self.client.sandbox_status()
            items.append(sandbox_view(sandbox))
        except (ArcenAPIError, httpx.HTTPError, OSError, ValueError) as exc:
            items.append(Text(f"Sandbox unavailable: {exc}", style=TOKENS["rose"]))
        items.append(Text("\nEsc / Enter  close", style=TOKENS["muted"]))
        body.update(Group(*items))

    def action_close(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    CSS = """
    HelpScreen { align: center middle; background: #0B0E14 75%; }
    #help-modal { width: 68; max-width: 96%; height: auto; max-height: 90%;
        border: round #A78BFA; background: #10141D; padding: 1 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape,q,enter,f1", "close", "Close", priority=True)
    ]

    def compose(self) -> ComposeResult:
        body = Text("ARCEN  /  KEYBOARD\n\n", style=f"bold {TOKENS['accent']}")
        body.append("Enter  submit goal        Ctrl+T  new line\n")
        body.append("Ctrl+G  external editor  Tab  complete slash command\n")
        body.append("Ctrl+C  interrupt        Ctrl+N  new session\n")
        body.append("Ctrl+B  sessions         Ctrl+R  resume latest\n")
        body.append("Ctrl+O  configuration    Ctrl+S  sandbox\n")
        body.append("PageUp / PageDown  scroll    Ctrl+End  back to live\n")
        body.append("F1  help                 Ctrl+Q  quit\n\n")
        body.append(
            "Slash: /help /clear /new /sessions /config /sandbox\n\n", style=TOKENS["muted"]
        )
        body.append("Esc / Enter  close", style=TOKENS["muted"])
        yield VerticalScroll(Static(body), id="help-modal")

    def action_close(self) -> None:
        self.dismiss(None)
