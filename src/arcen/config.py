"""ARCEN — config (BACKEND-SPEC Part 4 / Part 2 row 15).

Pulled from pydantic-settings — YAML + env loading and validation.

Edited per the Pull Map: ``$VAR`` indirection. Any config value matching
``^\\$[A-Z_]+$`` is a reference into the process environment (the
credential vault, Part 8). Literal secrets in the config file are a spec
violation, and the API never returns secret values — only their names.

Missing file → defaults + a ``CONFIG_DEFAULTED`` warning; every value
has an API equivalent (GET/PUT /api/config).
"""

from __future__ import annotations

import copy
import os
import re
import warnings
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

VAR_PATTERN = re.compile(r"^\$[A-Z_]+$")

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


def load_config(path: str | Path | None = None) -> ArcenConfig:
    """Read ~/.arcen/config.yaml (or an explicit path), validate, return.

    Missing file → defaults with a CONFIG_DEFAULTED warning (Part 10, step 1).
    """
    candidates = [Path(path)] if path else [default_config_path()]
    file = next((c for c in candidates if c.exists()), None)
    if file is None:
        warnings.warn("config file not found; using defaults", UserWarning, stacklevel=2)
        return ArcenConfig()  # CONFIG_DEFAULTED
    raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config {file} must be a YAML mapping")
    return ArcenConfig.model_validate(
        deep_merge(DEFAULT_CONFIG, migrate_legacy_config(raw))
    )


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
