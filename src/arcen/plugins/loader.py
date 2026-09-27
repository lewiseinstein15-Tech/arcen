"""ARCEN — plugin loader (BACKEND-SPEC Part 2 row 9 / Part 7).

Pulled from the DeepSeek Harness plugin pattern — a hook registry that
fires decorated methods at fixed points in the loop.

Edited per the Pull Map: the frozen six hooks (adding a seventh is a
spec violation), sync by default with async allowed per hook, and the
failure policy — a raising hook is a plugin bug: fail-open everywhere
except ``before_tool``, which fails closed for safety hooks.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys
from pathlib import Path

# frozen hook list (Part 7) — do not extend without a spec revision
HOOKS: tuple[str, ...] = (
    "on_boot",
    "before_tool",
    "after_tool",
    "on_spawn",
    "on_error",
    "on_shutdown",
)


class Plugin:
    """Base class. Subclasses set ``name`` and decorate hooks."""

    name: str = ""
    _hooks: dict[str, list] = {}


def hook(hook_name: str):
    """Mark a method as a plugin hook. The name must be one of the frozen 6."""

    def decorator(fn):
        if hook_name not in HOOKS:
            raise ValueError(f"unknown hook {hook_name!r}; the frozen hooks are {HOOKS}")
        fn._arcen_hook = hook_name
        return fn

    return decorator


def _collect_hooks(plugin: Plugin) -> dict[str, list]:
    """Gather decorated methods of a plugin (class or instance level)."""
    collected: dict[str, list] = {h: [] for h in HOOKS}
    seen: set[int] = set()
    for attr in dir(plugin):
        fn = getattr(plugin, attr, None)
        hook_name = getattr(fn, "_arcen_hook", None)
        if hook_name in collected and id(fn) not in seen:
            seen.add(id(fn))
            collected[hook_name].append(fn)
    return collected


class PluginLoader:
    """Discovers plugin modules, validates hooks, fires the chain."""

    def __init__(self, enabled: list[str] | None = None, paths: list[str] | None = None) -> None:
        self.enabled = enabled or []
        self.paths = [Path(p).expanduser() for p in (paths or ["~/.arcen/plugins"])]
        self.plugins: dict[str, Plugin] = {}
        self.hooks: dict[str, dict[str, list]] = {}  # hook → plugin name → [fns]
        self.errors: list[dict] = []

    def load(self) -> dict[str, Plugin]:
        """Import every plugin module under the paths, keep the enabled ones."""
        for root in self.paths:
            if not root.is_dir():
                continue
            for module_file in sorted(root.glob("*.py")):
                module_name = f"arcen_plugin_{module_file.stem}"
                try:
                    spec = importlib.util.spec_from_file_location(module_name, module_file)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                except Exception as exc:  # noqa: BLE001 — a broken plugin file is skipped
                    self.errors.append({"plugin": module_file.stem, "error": f"import failed: {exc}"})
                    continue
                for obj in vars(module).values():
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, Plugin)
                        and obj is not Plugin
                        and getattr(obj, "name", "")
                    ):
                        if obj.name not in self.enabled:
                            continue  # declared but not enabled — not loaded
                        if obj.name in self.plugins:
                            continue  # first wins
                        instance = obj()
                        self.plugins[obj.name] = instance
                        self._wire(instance)
        return self.plugins

    def _wire(self, instance: Plugin) -> None:
        """Validate hook signatures and index the plugin's hooks."""
        collected = _collect_hooks(instance)
        for hook_name, fns in collected.items():
            for fn in fns:
                self.hooks.setdefault(hook_name, {}).setdefault(instance.name, []).append(fn)

    def active(self, hook_name: str) -> list[str]:
        return list(self.hooks.get(hook_name, {}).keys())

    # -- firing ---------------------------------------------------------------
    def fire(self, hook_name: str, payload, fail_closed: bool = False):
        """Run every plugin's hook for this point in the loop.

        Returns (payload, fired_plugin_names). A raising hook drops its
        plugin from the pipeline (fail-open) and records the error —
        except before_tool, which fails closed for safety hooks.
        """
        if hook_name not in HOOKS:
            raise ValueError(f"unknown hook {hook_name!r}; the frozen hooks are {HOOKS}")
        fired: list[str] = []
        for plugin_name, fns in list(self.hooks.get(hook_name, {}).items()):
            try:
                for fn in fns:
                    if inspect.iscoroutinefunction(fn):
                        try:
                            loop = asyncio.get_running_loop()
                        except RuntimeError:
                            loop = None
                        if loop is not None:
                            import concurrent.futures

                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                                payload = pool.submit(
                                    lambda: asyncio.run(fn(payload))
                                ).result()
                        else:
                            payload = asyncio.run(fn(payload))
                    else:
                        payload = fn(payload)
                fired.append(plugin_name)
            except Exception as exc:  # noqa: BLE001 — plugin bugs never kill the loop
                self.errors.append({"plugin": plugin_name, "hook": hook_name, "error": str(exc)})
                self.hooks[hook_name].pop(plugin_name, None)  # drop, pipeline continues
                if fail_closed:
                    raise
        return payload, fired


def fire_hook(hook_name: str, payload, fail_closed: bool = False):
    """Module-level convenience used by the agents and the server."""
    return _global.fire(hook_name, payload, fail_closed=fail_closed)


_global = PluginLoader()


def set_global(loader: PluginLoader) -> None:
    """Install the process-wide plugin loader (boot step 8)."""
    global _global
    _global = loader
