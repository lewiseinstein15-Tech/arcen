"""T-019 — plugin loader (BACKEND-SPEC Part 7).

Proves: register a hook, trigger it; the frozen 6 hooks; async hooks;
fail-open everywhere except fail-closed before_tool; file discovery;
the shipped redact-secrets plugin scrubs secrets.
"""

import asyncio
import textwrap

import pytest

from arcen.plugins.loader import (
    HOOKS,
    Plugin,
    PluginLoader,
    hook,
)
from arcen.plugins.redact_secrets import RedactSecrets


def test_register_hook_and_trigger() -> None:
    # mirrors the ticket: register a hook, trigger it → hook fires
    class Recorder(Plugin):
        name = "recorder"

        @hook("after_tool")
        def note(self, event: dict) -> dict:
            event["seen_by"] = "recorder"
            return event

    loader = PluginLoader(enabled=["recorder"])
    instance = Recorder()
    loader.plugins[instance.name] = instance
    loader._wire(instance)

    payload, fired = loader.fire("after_tool", {"tool": "bash", "result": {}})
    assert fired == ["recorder"]
    assert payload["seen_by"] == "recorder"


def test_frozen_six_hooks() -> None:
    assert HOOKS == (
        "on_boot",
        "before_tool",
        "after_tool",
        "on_spawn",
        "on_error",
        "on_shutdown",
    )


def test_unknown_hook_rejected_at_decoration() -> None:
    with pytest.raises(ValueError, match="unknown hook"):
        @hook("on_everything")  # a 7th hook is a spec violation
        def boom(payload):
            return payload


def test_async_hooks_run() -> None:
    class AsyncGreeter(Plugin):
        name = "async-greeter"

        @hook("on_boot")
        async def greet(self, config: dict) -> dict:
            config["greeted"] = True
            return config

    loader = PluginLoader(enabled=["async-greeter"])
    instance = AsyncGreeter()
    loader.plugins[instance.name] = instance
    loader._wire(instance)
    payload, fired = loader.fire("on_boot", {})
    assert fired == ["async-greeter"]
    assert payload["greeted"] is True
    # and from inside a running loop (server context)
    async def in_loop():
        return loader.fire("on_boot", {"again": True})

    payload2, _ = asyncio.run(in_loop())
    assert payload2["again"] is True


def test_fail_open_drops_plugin_others_continue() -> None:
    class Broken(Plugin):
        name = "broken"

        @hook("after_tool")
        def explode(self, event: dict) -> dict:
            raise RuntimeError("plugin bug")

    class Healthy(Plugin):
        name = "healthy"

        @hook("after_tool")
        def stamp(self, event: dict) -> dict:
            event["healthy"] = True
            return event

    loader = PluginLoader(enabled=["broken", "healthy"])
    b, h = Broken(), Healthy()
    loader.plugins.update({"broken": b, "healthy": h})
    loader._wire(b)
    loader._wire(h)

    payload, fired = loader.fire("after_tool", {"n": 1})
    assert payload["healthy"] is True  # pipeline continued
    assert "broken" not in fired
    assert loader.errors[-1]["plugin"] == "broken"
    # the broken plugin is dropped from subsequent fires
    _, fired2 = loader.fire("after_tool", {"n": 2})
    assert "broken" not in fired2 and "healthy" in fired2


def test_before_tool_fails_closed() -> None:
    class Guard(Plugin):
        name = "guard"

        @hook("before_tool")
        def deny(self, args: dict) -> dict:
            raise PermissionError("denied by policy")

    loader = PluginLoader(enabled=["guard"])
    g = Guard()
    loader.plugins[g.name] = g
    loader._wire(g)
    with pytest.raises(PermissionError):
        loader.fire("before_tool", {"cmd": "rm -rf /"}, fail_closed=True)


def test_every_frozen_hook_fires() -> None:
    class Journal(Plugin):
        name = "journal"

        def __init__(self) -> None:
            self.calls: list[str] = []
            for h in HOOKS:
                setattr(self, f"_{h}", self._record(h))

        def _record(self, hook_name: str):
            @hook(hook_name)
            def fn(payload):
                self.calls.append(hook_name)
                return payload

            return fn

    loader = PluginLoader(enabled=["journal"])
    j = Journal()
    loader.plugins[j.name] = j
    loader._wire(j)
    for h in HOOKS:
        loader.fire(h, {} if h != "on_boot" else {"config": True})
    assert sorted(j.calls) == sorted(HOOKS)


def test_file_discovery(tmp_path) -> None:
    plugin_file = tmp_path / "cost_guard.py"
    plugin_file.write_text(
        textwrap.dedent(
            """
            from arcen.plugins.loader import Plugin, hook

            class CostGuard(Plugin):
                name = "cost-guard"

                @hook("on_error")
                def alert(self, error: dict) -> dict:
                    error["alerted"] = True
                    return error
            """
        ),
        encoding="utf-8",
    )
    loader = PluginLoader(enabled=["cost-guard"], paths=[str(tmp_path)])
    loaded = loader.load()
    assert "cost-guard" in loaded
    payload, fired = loader.fire("on_error", {"code": "X"})
    assert fired == ["cost-guard"] and payload["alerted"] is True


def test_disabled_plugins_not_loaded(tmp_path) -> None:
    plugin_file = tmp_path / "extra.py"
    plugin_file.write_text(
        textwrap.dedent(
            """
            from arcen.plugins.loader import Plugin, hook

            class Extra(Plugin):
                name = "extra"

                @hook("on_boot")
                def boot(self, config: dict) -> dict:
                    return config
            """
        ),
        encoding="utf-8",
    )
    loader = PluginLoader(enabled=[], paths=[str(tmp_path)])
    assert loader.load() == {}


def test_redact_secrets_builtin() -> None:
    loader = PluginLoader(enabled=["redact-secrets"])
    loader.plugins["redact-secrets"] = RedactSecrets()
    loader._wire(loader.plugins["redact-secrets"])
    event = {
        "tool": "bash",
        "result": {
            "stdout": "token is ghp_ABCDEFGHIJKLMNOPQRSTUVWX and Bearer abcdefghijklmnop12",
            "exit": 0,
        },
    }
    out, fired = loader.fire("after_tool", event)
    assert "redact-secrets" in fired
    assert "ghp_" not in out["result"]["stdout"]
    assert "[REDACTED]" in out["result"]["stdout"]
