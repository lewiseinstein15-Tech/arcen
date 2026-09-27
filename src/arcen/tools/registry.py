"""ARCEN — Tool schema + registry (BACKEND-SPEC Part 3, frozen).

One Protocol. Every tool — core, community, or MCP-bridged — implements it.
Schemas are auto-generated from the ``execute()`` type hints with
``pydantic.TypeAdapter``; hand-written JSON Schema is rejected at
registration so the schema always matches the code.

Registry file: ``src/arcen/tools/registry.toml`` declares built-in tools.
The registry validates: unique names, no shadowing of MCP tool namespaces
(``mcp.<server>.<tool>``), schema generation succeeds, and the class
satisfies the Protocol via ``runtime_checkable``.

Pulled from OpenHands (tools/ package) + the ToolRegistry pattern
(BACKEND-SPEC Part 2, rows 6–7); wrapped in the frozen Tool schema.
"""

from __future__ import annotations

import importlib
import tomllib
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, TypeAdapter

DANGERS = ("safe", "sandboxed", "escalate")


def _ok(result: Any) -> dict:
    return {"ok": True, "result": result, "error": None}


def _err(error: str) -> dict:
    return {"ok": False, "result": None, "error": error}


@runtime_checkable
class Tool(Protocol):
    """The frozen tool contract (Part 3). Never raises — failures are values."""

    name: str  # unique, dotted, lowercase: "file.edit", "bash", "http.get"
    description: str  # one paragraph, shown to the model
    version: str  # semver of the tool contract
    danger: str  # "safe" | "sandboxed" | "escalate"

    def schema(self) -> dict:
        """JSON Schema of execute() args, auto-generated from type hints."""
        ...

    def execute(self, args: dict) -> dict:
        """Returns {"ok": bool, "result": Any, "error": str | None}.

        Never raises — failures are values. Sandbox violations are ok=False.
        """
        ...


class BaseTool:
    """Shared implementation for core tools.

    Subclasses declare ``name`` / ``description`` / ``version`` / ``danger``
    and a nested ``Args`` pydantic model — the registry derives the JSON
    Schema from it (the typed argument of ``execute``). Subclasses may not
    override ``schema()``; hand-written schemas are rejected.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    version: ClassVar[str] = "1.0.0"
    danger: ClassVar[str] = "safe"
    Args: ClassVar[type[BaseModel]]

    def schema(self) -> dict:
        """JSON Schema, auto-generated from the execute() args model."""
        return TypeAdapter(self.Args).json_schema()

    def execute(self, args: dict) -> dict:
        """Validate into ``Args``, run ``_run``, wrap in the envelope.

        Never raises. Subclasses implement ``_run`` — the typed body of
        the tool; its signature is the schema's source of truth.
        """
        try:
            model = self.Args.model_validate(args)
        except Exception as exc:  # noqa: BLE001 — envelope contract
            return _err(f"invalid args: {exc}")
        try:
            out = self._run(model)
        except Exception as exc:  # noqa: BLE001 — envelope contract
            return _err(str(exc))
        return _ok(out)


class RegistryError(ValueError):
    """A tool failed registration."""


class SchemaRejected(RegistryError):
    """A hand-written schema (overridden ``schema()``) was submitted."""


class Registry:
    """Holds every callable tool, keyed by dotted name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"unknown tool {name!r}")
        return self._tools[name]

    def schemas(self) -> dict[str, dict]:
        return {name: tool.schema() for name, tool in self._tools.items()}

    def register(self, tool: Tool) -> None:
        """Register one tool, enforcing every Part 3 validation."""
        if "schema" in type(tool).__dict__:
            # BaseTool.schema is inherited, never redefined — a class that
            # ships its own schema() is hand-writing JSON Schema.
            raise SchemaRejected(
                f"{getattr(tool, 'name', '?')}: hand-written schema rejected — "
                "schemas are auto-generated from type hints (Part 3)"
            )
        if not isinstance(tool, Tool):
            raise RegistryError(f"{type(tool).__name__} does not satisfy the Tool Protocol")
        name = tool.name
        if not name or name != name.strip().lower() or " " in name:
            raise RegistryError(f"tool name {name!r} must be lowercase dotted, no spaces")
        if name.startswith("mcp."):
            raise RegistryError(f"tool name {name!r} shadows the MCP namespace mcp.<server>.<tool>")
        if name in self._tools:
            raise RegistryError(f"duplicate tool name {name!r}")
        if tool.danger not in DANGERS:
            raise RegistryError(f"tool {name!r}: danger must be one of {DANGERS}, got {tool.danger!r}")
        try:
            schema = tool.schema()
        except Exception as exc:  # noqa: BLE001
            raise RegistryError(f"tool {name!r}: schema generation failed: {exc}") from exc
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise RegistryError(f"tool {name!r}: generated schema is not a JSON object schema")
        self._tools[name] = tool

    def dispatch(self, name: str, args: dict) -> dict:
        """Call a tool by name. Always returns the envelope, never raises."""
        tool = self._tools.get(name)
        if tool is None:
            return _err(f"unknown tool {name!r}")
        try:
            return tool.execute(args)
        except Exception as exc:  # noqa: BLE001 — tools never raise, belt and braces
            return _err(f"tool {name!r} raised: {exc}")

    @classmethod
    def load_builtin(cls, toml_path: str | None = None) -> "Registry":
        """Load the 40 core tools from registry.toml."""
        import pathlib

        path = pathlib.Path(toml_path) if toml_path else pathlib.Path(__file__).parent / "registry.toml"
        registry = cls()
        with open(path, "rb") as fh:
            manifest = tomllib.load(fh)
        for entry in manifest.get("tool", []):
            module = importlib.import_module(entry["module"])
            klass = getattr(module, entry["class"])
            registry.register(klass())
        return registry


def load_builtin(toml_path: str | None = None) -> Registry:
    """Convenience: the v0.1 registry with all 40 core tools."""
    return Registry.load_builtin(toml_path)
