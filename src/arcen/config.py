"""ARCEN — config (BACKEND-SPEC Part 4 / Part 2 row 15).

Pulled from pydantic-settings — YAML + env loading and validation.

Edited per the Pull Map: ``$VAR`` indirection. Any config value matching
``^\\$[A-Z_]+$`` is a reference into the process environment (the
credential vault, Part 8). Literal secrets in the config file are a spec
violation, and the API never returns secret values — only their names.

Missing file → defaults + a ``CONFIG_DEFAULTED`` warning; every value
has an API equivalent (GET/PUT /api/config).

v0.1.5 (T-055): ``ARCEN_MODEL_*`` environment variables seed EMPTY
provider slots at boot (config wins where non-empty; env only fills
empty slots; the seeded file is written once so the Settings page has
something to read from on the next restart).
"""

from __future__ import annotations

import copy
import logging
import os
import re
import warnings
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

VAR_PATTERN = re.compile(r"^\$[A-Z_]+$")

log = logging.getLogger("arcen.config")

# T-055: the env vars that seed an empty provider block at boot. The
# user's contract: set these before boot and the Settings page shows
# the values without any retyping — env is the source of truth on
# first boot, the file is the source of truth after that.
ENV_PROVIDER_VARS: dict[str, str] = {
    "name": "ARCEN_MODEL_PROVIDER",
    "base_url": "ARCEN_MODEL_BASE_URL",
    "api_key": "ARCEN_MODEL_API_KEY",
    "model": "ARCEN_MODEL_NAME",
}

# The provider the UI displays when nothing is configured (SettingsView
# falls back to 'custom'); used when ARCEN_MODEL_PROVIDER is unset.
DEFAULT_PROVIDER_NAME = "custom"

DEFAULT_CONFIG: dict = {
    # T-049: the provider block is the four scalar fields Settings saves.
    # No Anthropic (or any vendor) defaults ship in the config — an empty
    # model means offline, never claude-* against a custom endpoint.
    "provider": {
        "name": "",  # custom | groq | deepseek | openai | anthropic | ollama
        "base_url": "",  # OpenAI-compatible endpoint (custom / ollama)
        "api_key": "",  # literal or $VAR (credential vault indirection)
        "model": "",  # the model for all agents — agents.<name>.model overrides
    },
    "agents": {
        "draft": {"max_steps": 40, "replan_on_fail": True, "model": None},
        "forge": {"step_timeout_s": 120, "max_retries": 2, "model": None},
        "temper": {"adversarial": True, "reruns": 1, "model": None},
    },
    "subagents": {
        "max_depth": 2,
        "max_concurrent": 8,
        "default_model": None,  # T-050: null → inherit provider.model
    },
    "skills": {"paths": ["~/.arcen/skills", "./skills"]},
    "mcps": [],
    "plugins": {"enabled": [], "paths": ["~/.arcen/plugins"]},
    "sandbox": {
        "image": "ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0",
        "mem_limit": "2g",
        "cpus": 2.0,
        "network": "none",
        "backend": "auto",
    },
    "stream": {"port": 3002, "content_type": "application/x-ndjson"},
    "session": {"dir": "~/.arcen/sessions"},
    "memory": {"db": "~/.arcen/memory.db", "decay_half_life_days": 14},
}


class ProviderConfig(BaseModel):
    """The provider Settings saves (T-049): four scalars, no per-vendor
    dicts, no shipped vendor defaults. ``api_key`` may be a ``$VAR``
    reference resolved from the environment at bridge-build time."""

    name: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class DraftConfig(BaseModel):
    max_steps: int = 40
    replan_on_fail: bool = True
    model: str | None = None  # T-050: null → inherit provider.model


class ForgeConfig(BaseModel):
    step_timeout_s: float = 120
    max_retries: int = 2
    model: str | None = None  # T-050: null → inherit provider.model


class TemperConfig(BaseModel):
    adversarial: bool = True
    reruns: int = 1
    model: str | None = None  # T-050: null → inherit provider.model


class AgentsConfig(BaseModel):
    draft: DraftConfig = Field(default_factory=DraftConfig)
    forge: ForgeConfig = Field(default_factory=ForgeConfig)
    temper: TemperConfig = Field(default_factory=TemperConfig)


class SubagentsConfig(BaseModel):
    max_depth: int = 2
    max_concurrent: int = 8
    # T-050: no vendor default — null inherits provider.model
    default_model: str | None = None


class SkillsConfig(BaseModel):
    paths: list[str] = Field(default_factory=lambda: ["~/.arcen/skills", "./skills"])


class McpServer(BaseModel):
    name: str
    transport: str  # "stdio" | "http"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    state: str = "declarative"
    headers: dict[str, str] = Field(default_factory=dict)


class PluginsConfig(BaseModel):
    enabled: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=lambda: ["~/.arcen/plugins"])


class SandboxConfig(BaseModel):
    image: str = DEFAULT_CONFIG["sandbox"]["image"]
    mem_limit: str = "2g"
    cpus: float = 2.0
    network: str = "none"
    # T-038: auto = docker when usable, else the quarantined process backend;
    # docker = require docker (clear error, never a silent fallback);
    # process = always the quarantined process backend
    backend: Literal["auto", "docker", "process"] = "auto"


class StreamConfig(BaseModel):
    port: int = 3002
    content_type: str = "application/x-ndjson"


class SessionConfig(BaseModel):
    dir: str = "~/.arcen/sessions"


class MemoryConfig(BaseModel):
    db: str = "~/.arcen/memory.db"
    decay_half_life_days: int = 14


class ArcenConfig(BaseModel):
    """The full validated config — one model per Part 4 section."""

    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    subagents: SubagentsConfig = Field(default_factory=SubagentsConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    mcps: list[McpServer] = Field(default_factory=list)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    stream: StreamConfig = Field(default_factory=StreamConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

    def to_dict(self) -> dict:
        return self.model_dump()

    def redacted(self) -> dict:
        """API view: secret values become their $VAR names, never literals."""
        return redact_secrets(self.model_dump())


# The provider/models values the old config shipped; anything else in a
# legacy file is a genuine user override worth carrying across (T-049).
_LEGACY_ROLE_DEFAULTS = {
    "planner": "claude-sonnet-4-5",
    "executor": "claude-sonnet-4-5",
    "verifier": "claude-haiku-4-5",
}
_LEGACY_ROLE_AGENTS = {"planner": "draft", "executor": "forge", "verifier": "temper"}


def migrate_legacy_config(raw: dict) -> dict:
    """v0.1.4 (T-049): legacy provider dict-shape → the scalar shape, once,
    on load.

    ``default`` → ``name``; ``api_keys[<name>]`` → ``api_key``;
    ``base_urls[<name>]`` → ``base_url``; the per-role ``models`` map only
    survives where the user actually overrode the shipped Anthropic
    defaults — all-equal overrides become ``provider.model``, mixed ones
    map onto ``agents.<name>.model``. The claude-* seed values are dropped:
    they never fit a custom endpoint.
    """
    if not isinstance(raw, dict):
        return raw
    provider = raw.get("provider")
    if isinstance(provider, dict) and "name" not in provider:
        name = str(provider.get("default") or "")
        if name:
            provider["name"] = name
            keys = provider.get("api_keys")
            if isinstance(keys, dict) and keys.get(name):
                provider.setdefault("api_key", keys[name])
            urls = provider.get("base_urls")
            if isinstance(urls, dict) and urls.get(name):
                provider.setdefault("base_url", urls[name])
        models = provider.get("models")
        if isinstance(models, dict):
            agents = raw.setdefault("agents", {})
            overrides: dict[str, str] = {
                role: str(value)
                for role, value in models.items()
                if value and value != _LEGACY_ROLE_DEFAULTS.get(role)
            }
            roles = set(overrides)
            if len(overrides) == 3 and len(set(overrides.values())) == 1:
                provider.setdefault("model", next(iter(overrides.values())))
            else:
                for role in roles & set(_LEGACY_ROLE_AGENTS):
                    slot = agents.setdefault(_LEGACY_ROLE_AGENTS[role], {})
                    if isinstance(slot, dict):
                        slot.setdefault("model", overrides[role])
        for stale in ("default", "models", "api_keys", "base_urls"):
            provider.pop(stale, None)
    subagents = raw.get("subagents")
    if isinstance(subagents, dict) and subagents.get("default_model") == "claude-haiku-4-5":
        subagents["default_model"] = None  # shipped seed → inherit
    return raw


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def mask_secret(key: str | None) -> str:
    """Boot-log view of a credential: its shape, never its value (T-055).

    ``dahl_9f2c...a71b`` style — first4...last4 — is enough for support
    to confirm WHICH key is in play without leaking it. Short values are
    masked entirely: 4+4 would reveal more than it hides.
    """
    if not key:
        return "<none>"
    key = str(key).strip()
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def seed_provider_from_env(raw: dict) -> tuple[dict, list[str]]:
    """Fill EMPTY provider slots from ``ARCEN_MODEL_*`` env vars (T-055).

    Precedence: a non-empty config value always wins; the env var fills
    an empty slot; an unset env var leaves the slot as-is (the user must
    fill it in Settings). ``provider.name`` additionally falls back to
    ``custom`` — the provider the UI already displays — but that default
    is NOT an env contribution and never triggers a file write.

    Returns the mutated raw dict plus the list of fields an env var
    actually filled — the caller persists the file only when that list
    is non-empty, so a plain restart never rewrites the file.
    """
    provider = raw.get("provider")
    if not isinstance(provider, dict):
        provider = {}
        raw["provider"] = provider
    filled: list[str] = []
    for field, var in ENV_PROVIDER_VARS.items():
        if str(provider.get(field) or "").strip():
            continue  # config wins where present
        value = str(os.environ.get(var) or "").strip()
        if not value:
            continue  # env unset → leave empty; the user fills it in Settings
        provider[field] = value
        filled.append(field)
    if not str(provider.get("name") or "").strip():
        provider["name"] = DEFAULT_PROVIDER_NAME  # in-memory display default
    return raw, filled


def load_config(path: str | Path | None = None) -> ArcenConfig:
    """Read ~/.arcen/config.yaml (or an explicit path), validate, return.

    Missing file → defaults with a CONFIG_DEFAULTED warning (Part 10, step 1).

    T-055: empty provider slots are then seeded from ``ARCEN_MODEL_*`` env
    vars (config wins where non-empty). When an env var actually filled a
    slot, the merged config is written back ONCE — the seeded file is what
    makes the seeding survive restarts and gives the Settings page a file
    to read from — and one boot line records it, api_key masked. With no
    env contribution nothing is written (a restart never rewrites the
    file, and the T-054 test-suite guard stays green).
    """
    file = Path(path).expanduser() if path else default_config_path()
    if file.exists():
        raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"config {file} must be a YAML mapping")
    else:
        warnings.warn(
            "config file not found; using defaults", UserWarning, stacklevel=2
        )
        raw = {}  # CONFIG_DEFAULTED — then seeded from env below (T-055)
    seeded, filled = seed_provider_from_env(migrate_legacy_config(raw))
    config = ArcenConfig.model_validate(deep_merge(DEFAULT_CONFIG, seeded))
    if filled:  # env contributed → persist the seeded file, exactly once
        try:
            save_config(file, config)
        except OSError as exc:  # degrade — boot never aborts on a write failure
            warnings.warn(
                f"seeded config could not be written to {file}: {exc}",
                UserWarning,
                stacklevel=2,
            )
        else:
            log.info(
                "[config] seeded from env: provider=%s model=%s base_url=%s api_key=%s",
                config.provider.name,
                config.provider.model or "none",
                config.provider.base_url or "none",
                mask_secret(config.provider.api_key),
            )
    return config


def default_config_path() -> Path:
    """Where the user config lives. ARCEN_CONFIG_PATH overrides (tests)."""
    env = os.environ.get("ARCEN_CONFIG_PATH")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".arcen" / "config.yaml"


def save_config(path: str | Path, config: ArcenConfig) -> None:
    """Persist the validated config as YAML (T-036 Settings → Save).

    The file is user-local and chmod 600 — it may hold the API key the
    user typed in Settings. The API never returns that value (redacted).
    """
    file = Path(path).expanduser()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        yaml.safe_dump(config.model_dump(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    file.chmod(0o600)


def resolve_secrets(config: dict) -> tuple[dict, list[str]]:
    """Expand every ``$VAR`` from the process environment.

    Returns the resolved mapping plus the list of names that could NOT be
    resolved — their dependents boot degraded, boot itself never aborts
    (Part 8 rule 2). Values live only in process memory.
    """
    missing: list[str] = []

    def walk(node: object) -> object:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str) and VAR_PATTERN.match(node):
            name = node[1:]
            value = os.environ.get(name)
            if value is None:
                missing.append(name)
                return node  # keep the reference; dependent is degraded
            return value
        return node

    return walk(config), sorted(set(missing))


def redact_secrets(config: dict) -> dict:
    """API-safe view: any resolved value that came from a $VAR is shown
    only as its variable name. Defence-in-depth for the config endpoint."""

    def walk(node: object, secret: bool) -> object:
        if isinstance(node, dict):
            return {
                k: walk(v, secret or k in {"api_keys", "api_key", "headers"})
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [walk(v, secret) for v in node]
        if isinstance(node, str) and secret and not VAR_PATTERN.match(node) and node != "":
            return "<redacted>"
        return node

    return walk(config, False)
