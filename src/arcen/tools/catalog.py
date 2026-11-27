"""ARCEN — the tool catalog the planner reads (Part 3 → Part 1).

The planner used to be handed a hand-written list of tool names inside
``tool-guidance.md``. That list drifted from the registry the moment a tool
was added, and it could never mention an MCP-bridged or plugin tool — those
are registered at boot, after the prompt file was written.

This module derives the catalog from the registry instead, so what the model
is told and what FORGE can actually run come from the same place. Two rules
keep it honest and cheap:

* **capability filter** — only tools the current executor can dispatch are
  advertised. A sandboxed turn runs seven tools; advertising the other 33
  would buy a guaranteed failure and a wasted replan.
* **token budget** — descriptions are clipped and the list is truncated at a
  character budget, because a 200-tool MCP server must not eat the context
  window. Required arguments are always kept; optional ones are dropped
  first.
"""

from __future__ import annotations

from collections.abc import Iterable

MAX_CHARS = 6000
MAX_TOOLS = 80
MAX_DESCRIPTION = 110

_TYPE_NAMES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
    "null": "none",
}


def _type_name(spec: dict) -> str:
    kind = spec.get("type")
    if isinstance(kind, str):
        return _TYPE_NAMES.get(kind, kind)
    for key in ("anyOf", "oneOf"):
        options = spec.get(key)
        if isinstance(options, list):
            names = [_type_name(o) for o in options if isinstance(o, dict)]
            names = [n for n in dict.fromkeys(names) if n != "none"]
            if names:
                return "|".join(names)
    return "any"


def _clip(text: str, limit: int = MAX_DESCRIPTION) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _args(schema: dict, *, optional: bool) -> list[str]:
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    required = set(schema.get("required") or [])
    rendered: list[str] = []
    for name in sorted(props):
        spec = props[name] if isinstance(props[name], dict) else {}
        is_required = name in required
        if is_required == optional:
            continue
        rendered.append(f"{name}:{_type_name(spec)}")
    return rendered


def entries(
    registry,
    *,
    available: Iterable[str] | None = None,
) -> list[dict]:
    """One entry per advertised tool, sorted by name.

    ``available`` is the capability filter: when given, a tool missing from it
    is not advertised at all. ``None`` means "everything in the registry".
    """
    allowed = None if available is None else set(available)
    out: list[dict] = []
    for name in registry.names():
        if allowed is not None and name not in allowed:
            continue
        try:
            tool = registry.get(name)
            schema = tool.schema()
        except Exception:  # noqa: BLE001 — a broken tool is not a planner problem
            continue
        if not isinstance(schema, dict):
            continue
        out.append(
            {
                "name": name,
                "description": _clip(getattr(tool, "description", "")),
                "danger": str(getattr(tool, "danger", "safe")),
                "required": _args(schema, optional=False),
                "optional": _args(schema, optional=True),
            }
        )
    return out


def _line(entry: dict, *, optional: bool) -> str:
    args = [f"*{a}" for a in entry["required"]]
    if optional:
        args += entry["optional"]
    head = f"{entry['name']} [{entry['danger']}] — {entry['description']}"
    return f"{head}\n    args: {', '.join(args)}" if args else head


LEGEND = "(* = required)"


def render(
    registry,
    *,
    available: Iterable[str] | None = None,
    max_chars: int = MAX_CHARS,
    max_tools: int = MAX_TOOLS,
) -> str:
    """The catalog as compact text, clipped to ``max_chars``.

    Degradation order: drop optional arguments, then drop descriptions, then
    truncate the list and say how many tools were left out. Required
    arguments and tool names survive longest because they are what the model
    needs to emit a runnable step.
    """
    try:
        items = entries(registry, available=available)
    except Exception:  # noqa: BLE001 — a proxy registry may not enumerate
        # The catalog is guidance, not a precondition: a registry that cannot
        # list itself still dispatches, so the turn proceeds without one.
        return ""
    if not items:
        return ""
    if len(items) > max_tools:
        hidden = len(items) - max_tools
        items = items[:max_tools]
        tail = f"\n(+{hidden} more tools not shown — use search.text or bash to discover them)"
    else:
        tail = ""

    for optional in (True, False):
        for describe in (True, False):
            lines = []
            for entry in items:
                rendered = _line(entry, optional=optional)
                if not describe:
                    rendered = f"{entry['name']} [{entry['danger']}]" + (
                        f" args: {', '.join(entry['required'] + (entry['optional'] if optional else []))}"
                        if (entry["required"] or (optional and entry["optional"]))
                        else ""
                    )
                lines.append(rendered)
            text = f"{LEGEND}\n" + "\n".join(lines) + tail
            if len(text) <= max_chars:
                return text
    return text[:max_chars]


def names(registry, *, available: Iterable[str] | None = None) -> set[str]:
    """The advertised names — what the planner may put in a step's ``tool``."""
    return {entry["name"] for entry in entries(registry, available=available)}
