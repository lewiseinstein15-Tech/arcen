"""ARCEN — one registry over two trust domains.

A turn runs two kinds of tool. Sandbox tools execute inside the disposable
container: they see the workspace and nothing else. Host tools — skills, MCP
servers, plugin-contributed tools — execute in the server process, because
they need something the container deliberately lacks: a filesystem outside
the snapshot, a network, or a long-lived subprocess.

Until now the turn registry refused anything outside the sandbox allowlist, so
a registered host tool was unreachable. This composite makes both callable
through the frozen Tool interface while keeping the routing explicit: a name
in the sandbox allowlist always goes to the container, never to the host. A
host tool can therefore not shadow ``bash``, and a sandbox violation cannot
be laundered through a host fallback.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class CompositeRegistry:
    """Dispatch sandbox tools to the container, host tools to this process."""

    def __init__(self, sandbox, host) -> None:
        self._sandbox = sandbox
        self._host = host

    # -- introspection ------------------------------------------------------
    def sandbox_tools(self) -> list[str]:
        # A backend that cannot enumerate still dispatches; unknown names fall
        # through to it, so the boundary's own error text is preserved.
        ask = getattr(self._sandbox, "available_tools", None)
        return list(ask()) if callable(ask) else []

    def host_tools(self) -> list[str]:
        return [name for name in self._host.names() if name not in set(self.sandbox_tools())]

    def names(self) -> list[str]:
        return sorted(set(self.sandbox_tools()) | set(self.host_tools()))

    def available_tools(self) -> list[str]:
        return self.names()

    def __contains__(self, name: str) -> bool:
        return name in set(self.names())

    def get(self, name: str):
        if name in set(self.sandbox_tools()):
            return self._sandbox.get(name) if hasattr(self._sandbox, "get") else None
        return self._host.get(name)

    def schemas(self) -> dict[str, dict]:
        sandbox_names = set(self.sandbox_tools())
        merged = {
            name: schema
            for name, schema in self._host.schemas().items()
            if name not in sandbox_names
        }
        for name in sandbox_names:
            tool = getattr(self._sandbox, "get", lambda _n: None)(name)
            if tool is not None:
                try:
                    merged[name] = tool.schema()
                except Exception as exc:  # noqa: BLE001 — a broken schema is not fatal here
                    log.warning("composite: no schema for %s (%s)", name, exc)
                    continue
        return merged

    # -- execution ----------------------------------------------------------
    def dispatch(self, name: str, args: dict) -> dict:
        if name in set(self.sandbox_tools()):
            return self._sandbox.dispatch(name, args)
        if name in set(self._host.names()):
            return self._host.dispatch(name, args)
        # Unknown names keep the boundary's own error text: it names the
        # executor, which is what the user needs to see in the stream.
        return self._sandbox.dispatch(name, args)

    # -- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        closer = getattr(self._sandbox, "close", None)
        if callable(closer):
            closer()
