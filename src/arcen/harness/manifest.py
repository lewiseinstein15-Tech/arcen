"""Integrity-check the bundled harness manifest; not a signature or trust root.

The manifest lists only shipped file components currently implemented. Refs
and user-selected harness packages are not implemented.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType

from .resolver import HarnessError

COMPONENT_PATHS = frozenset(
    {
        "prompts/system.md",
        "prompts/draft.md",
        "prompts/forge.md",
        "prompts/temper.md",
        "tool-guidance.md",
        "guardrails/policy.yaml",
        "tools/registry.toml",
    }
)
MAX_MANIFEST_BYTES = 64 * 1024
MAX_COMPONENT_BYTES = 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class Manifest:
    schema_version: int
    model_pin: str
    components: Mapping[str, str]


def _read(item, name: str, limit: int) -> bytes:
    if isinstance(item, Path) and (item.is_symlink() or item.parent.is_symlink()):
        raise HarnessError(f"manifest resource cannot be a symlink: {name}")
    try:
        with item.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as exc:
        raise HarnessError(f"cannot read manifest resource: {name}") from exc
    if len(data) > limit:
        raise HarnessError(f"manifest resource too large: {name}")
    return data


def load_manifest(root: str | Path | None = None) -> Manifest:
    """Verify every allowlisted component against the manifest before use.

    Explicit roots are trusted local inputs, not an untrusted edit boundary.
    Hashes detect accidental change, not malicious edits to manifest and files.
    """
    base = resources.files("arcen") if root is None else Path(root)
    raw = _read(base.joinpath("harness.toml"), "harness.toml", MAX_MANIFEST_BYTES)
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise HarnessError("invalid harness manifest") from exc
    if set(data) != {"schema_version", "model_pin", "components"}:
        raise HarnessError("invalid harness manifest fields")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise HarnessError("unsupported manifest schema")
    pin = data["model_pin"]
    if type(pin) is not str or not (
        pin == "provider-configured"
        or re.fullmatch(r"fixed:[a-z][a-z0-9_-]{0,31}:[^\s]{1,200}", pin)
    ):
        raise HarnessError("invalid model pin")
    components = data["components"]
    if type(components) is not dict or set(components) != COMPONENT_PATHS:
        raise HarnessError("manifest components must match the shipped allowlist")
    for name, expected in sorted(components.items()):
        if type(expected) is not str or not _HASH.fullmatch(expected):
            raise HarnessError(f"invalid component hash: {name}")
        actual = hashlib.sha256(
            _read(base.joinpath(*name.split("/")), name, MAX_COMPONENT_BYTES)
        ).hexdigest()
        if actual != expected:
            raise HarnessError(f"component hash mismatch: {name}")
    return Manifest(1, data["model_pin"], MappingProxyType(dict(components)))


def check_model_pin(manifest: Manifest, config) -> None:
    """Enforce a concrete pin at boot and configuration update, when set.

    The shipped default intentionally uses provider-configured (no fixed pin)
    to preserve the user's existing model choices in the M0 foundation.
    """
    if manifest.model_pin == "provider-configured":
        return
    _, provider, model = manifest.model_pin.split(":", 2)
    configured = config.provider
    if configured.name.strip() != provider or configured.model.strip() != model:
        raise HarnessError("configured provider/model does not match the manifest pin")
    overrides = (
        config.agents.draft.model,
        config.agents.forge.model,
        config.agents.temper.model,
        config.subagents.default_model,
    )
    if any(value is not None and value.strip() and value.strip() != model for value in overrides):
        raise HarnessError("agent model override does not match the manifest pin")


@lru_cache(maxsize=1)
def default_manifest() -> Manifest:
    return load_manifest()
