"""Redacted configuration editing and sandbox views fetched from the server."""

from __future__ import annotations

from copy import deepcopy
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
from textual.widgets import Button, Input, Static

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
        "BLOCKED" if effective == "unavailable" else ("DEGRADED" if degraded else "AVAILABLE"),
        style=f"bold {TOKENS['amber' if degraded else 'emerald']}",
    )
    return _table(
        [
            ("status", marker),
            ("configured", status.get("backend") or "auto"),
            ("selected", effective),
            ("docker daemon", "reachable" if status.get("docker_available") else "not reachable"),
            ("sandbox image", "present" if status.get("image_present") else ("absent" if status.get("docker_available") else "not checked")),
            ("image", status.get("image") or "—"),
            ("reason", status.get("reason") or "—"),
            ("isolated tools", ", ".join(status.get("supported_tools") or []) or "—"),
        ]
    )


class InfoScreen(ModalScreen[None]):
    """Redacted configuration and sandbox view with an explicit edit path."""

    CSS = """
    InfoScreen { align: center middle; background: #0B0E14 75%; }
    #info-modal { width: 76; max-width: 96%; height: 80%; border: round #A78BFA;
        background: #10141D; padding: 1 2; }
    #info-body { height: auto; width: 100%; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape,q,enter", "close", "Close", priority=True),
        Binding("e", "edit_config", "Edit", priority=True),
    ]

    def __init__(self, client: ArcenClient, *, sandbox_only: bool = False) -> None:
        super().__init__()
        self.client, self.sandbox_only = client, sandbox_only
        self.config: dict | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="info-modal"):
            yield Static("Loading…", id="info-body")

    async def on_mount(self) -> None:
        body = self.query_one("#info-body", Static)
        items = []
        if not self.sandbox_only:
            items.append(Text("CONFIGURATION  /  redacted\n", style=f"bold {TOKENS['accent']}"))
            try:
                cfg = await self.client.get_config()
                self.config = cfg
                items.append(config_view(cfg))
            except (ArcenAPIError, httpx.HTTPError, OSError, ValueError) as exc:
                items.append(Text(f"Configuration unavailable: {exc}", style=TOKENS["rose"]))
        items.append(Text("\nSANDBOX  /  runtime decision\n", style=f"bold {TOKENS['accent']}"))
        try:
            sandbox = await self.client.sandbox_status()
            items.append(sandbox_view(sandbox))
        except (ArcenAPIError, httpx.HTTPError, OSError, ValueError) as exc:
            items.append(Text(f"Sandbox unavailable: {exc}", style=TOKENS["rose"]))
        hint = (
            "\nE  edit configuration   Esc / Enter  close"
            if not self.sandbox_only
            else "\nEsc / Enter  close"
        )
        items.append(Text(hint, style=TOKENS["muted"]))
        body.update(Group(*items))

    def action_edit_config(self) -> None:
        if not self.sandbox_only and self.config is not None:
            self.app.push_screen(ConfigEditScreen(self.client, self.config), self._edited)

    def _edited(self, saved: bool | None) -> None:
        if saved:
            # The old sandbox result may no longer be true after a PUT.
            self.app.header.update_meta(quarantine="connected · sandbox unknown")
            self.app.rail.apply_state({"environment": {"sandbox": "unknown"}})
            self.app.pop_screen()

    def action_close(self) -> None:
        self.dismiss(None)


def _has_unrecoverable_secrets(value: object, path: tuple[str, ...] = ()) -> bool:
    """PUT preserves provider.api_key only; reject other opaque secrets."""
    if isinstance(value, dict):
        return any(_has_unrecoverable_secrets(v, (*path, str(k))) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_unrecoverable_secrets(v, (*path, str(i))) for i, v in enumerate(value))
    return value == "<redacted>" and path != ("provider", "api_key")


class ConfigEditScreen(ModalScreen[bool]):
    """Explicit save, preserving opaque provider keys and other settings."""

    CSS = """
    ConfigEditScreen { align: center middle; background: #0B0E14 75%; }
    #edit-modal { width: 76; max-width: 96%; height: 90%; border: round #A78BFA;
        background: #10141D; padding: 1 2; }
    #edit-title { color: #A78BFA; text-style: bold; height: 2; }
    #edit-status { color: #FBBF24; height: auto; min-height: 1; }
    #edit-modal Input { height: 3; border: round #1D2430; background: #10141D; }
    #edit-modal Button { margin-top: 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel_edit", "Cancel", priority=True)]

    def __init__(self, client: ArcenClient, config: dict) -> None:
        super().__init__()
        self.client = client
        self.config = deepcopy(config)
        self.original_url = str((config.get("provider") or {}).get("base_url") or "")
        self.display_url = _safe_url(self.original_url) if self.original_url else ""
        self.saving = False

    def compose(self) -> ComposeResult:
        provider = self.config.get("provider") or {}
        sandbox = self.config.get("sandbox") or {}
        with VerticalScroll(id="edit-modal"):
            yield Static("EDIT CONFIGURATION  /  explicit save", id="edit-title")
            yield Static("Provider name")
            yield Input(str(provider.get("name") or ""), id="edit-provider")
            yield Static("Model")
            yield Input(str(provider.get("model") or ""), id="edit-model")
            yield Static("Endpoint (credentials and query hidden)")
            yield Input(self.display_url, id="edit-url")
            yield Static("New API key (leave blank to keep current)")
            yield Input(password=True, id="edit-key")
            yield Static("Sandbox backend: auto / docker / process (process blocks tools)")
            yield Input(str(sandbox.get("backend") or "auto"), id="edit-sandbox")
            yield Static("Enter or Save to apply; Esc cancels.", id="edit-status")
            yield Button("Save configuration", id="edit-save", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#edit-provider", Input).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "edit-save":
            await self.save()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        await self.save()

    async def save(self) -> None:
        if self.saving:
            return
        status = self.query_one("#edit-status", Static)
        if _has_unrecoverable_secrets(self.config):
            status.update(
                "Cannot safely save: another secret is redacted. Use web Settings or the config file."
            )
            return
        backend = self.query_one("#edit-sandbox", Input).value.strip().lower()
        if backend not in ("auto", "docker", "process"):
            status.update("Sandbox backend must be auto, docker or process.")
            return
        config = deepcopy(self.config)
        provider = config.setdefault("provider", {})
        provider["name"] = self.query_one("#edit-provider", Input).value.strip()
        provider["model"] = self.query_one("#edit-model", Input).value.strip()
        url = self.query_one("#edit-url", Input).value.strip()
        provider["base_url"] = self.original_url if url == self.display_url else url
        key = self.query_one("#edit-key", Input).value
        prior_key = str(provider.get("api_key") or "")
        provider["api_key"] = (
            key
            if key
            else (prior_key if prior_key.startswith("$") else "<redacted>" if prior_key else "")
        )
        config.setdefault("sandbox", {})["backend"] = backend
        self.saving = True
        try:
            await self.client.put_config(config)
        except (ArcenAPIError, httpx.HTTPError, OSError, ValueError) as exc:
            status.update(f"Save failed: {exc}")
        else:
            self.dismiss(True)
        finally:
            self.saving = False

    def action_cancel_edit(self) -> None:
        self.dismiss(False)


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
