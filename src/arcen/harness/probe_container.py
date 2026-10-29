"""Disposable Docker-only probe workspace gateway; not a full probe runner.

This provides a narrow, redacting tool gateway for a reviewed Git snapshot.
It does not select a harness, call a model, persist trajectories or adopt code.
A trusted Docker daemon and trusted sandbox image are required.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

from arcen.config import ArcenConfig
from arcen.plugins.redact_secrets import redact_text
from arcen.sandbox.turn import DockerTurnRegistry

from .probe_workspace import GitSnapshot, materialize_git_snapshot


class RedactingProbeRegistry:
    """Apply mandatory, best-effort recursive redaction to tool responses."""

    supports_host_diff = False

    def __init__(self, inner: DockerTurnRegistry, secret_values: tuple[str, ...]):
        self._inner = inner
        self._secret_values = secret_values

    def _redact(self, value: Any, depth: int = 0) -> Any:
        if depth > 16:
            return "[REDACTED: nesting limit]"
        if isinstance(value, str):
            text = redact_text(value)
            for secret in self._secret_values:
                text = text.replace(secret, "[REDACTED]")
            return text
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if type(key) is not str:
                    return "[REDACTED: unsupported keys]"
                safe_key = self._redact(key, depth + 1)
                if safe_key in result:
                    return "[REDACTED: key collision]"
                result[safe_key] = self._redact(item, depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [self._redact(item, depth + 1) for item in value]
        if value is None or type(value) in (bool, int, float):
            return value
        return "[REDACTED: unsupported value]"

    def dispatch(self, name: str, args: dict) -> dict:
        """Only the underlying Docker gateway dispatches; no host fallback."""
        return self._redact(self._inner.dispatch(name, args))


def _provider_secret(config: ArcenConfig) -> tuple[str, ...]:
    key = config.provider.api_key
    if key.startswith("$"):
        key = os.environ.get(key[1:], "")
    return (key,) if len(key) >= 4 else ()


@contextmanager
def open_probe_container(snapshot: GitSnapshot, config: ArcenConfig):
    """Import a reviewed snapshot into a fresh hardened Docker container.

    The input is never bind-mounted or copied back. Tool results pass through
    mandatory best-effort redaction; this is not comprehensive secret detection.
    Docker creation/import failures propagate and never fall back to a host tool.
    This gateway is not wired to candidate model execution or campaigns.
    """
    with materialize_git_snapshot(snapshot) as workspace:
        registry = DockerTurnRegistry(config, workspace=str(workspace))
        try:
            yield RedactingProbeRegistry(registry, _provider_secret(config))
        finally:
            registry.close()
