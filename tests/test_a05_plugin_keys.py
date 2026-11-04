"""A-05: boot hooks do not receive any part of the config object."""

from arcen.config import ArcenConfig, McpServer
from arcen.server import app as server


def test_boot_hook_receives_no_credentials_or_nested_config(monkeypatch):
    seen = []

    class CapturingLoader:
        def __init__(self, **kwargs):
            self.plugins = {}

        def load(self):
            pass

        def fire(self, name, payload):
            seen.append((name, payload))
            return payload, []

    monkeypatch.setattr(server, "PluginLoader", CapturingLoader)
    config = ArcenConfig()
    config.provider.api_key = "synthetic-provider-secret"
    config.provider.base_url = "https://synthetic-user:synthetic-password@example.invalid"
    config.mcps = [
        McpServer(
            name="sample", transport="http", headers={"Authorization": "synthetic-nested-secret"}
        )
    ]
    server._boot_plugins(config)
    assert seen == [("on_boot", {})]
    assert "synthetic" not in repr(seen)


def test_builtin_plugin_still_loads():
    config = ArcenConfig()
    config.plugins.enabled = ["redact-secrets"]
    config.plugins.paths = []
    loader = server._boot_plugins(config)
    assert "redact-secrets" in loader.plugins
    assert loader.active("after_tool") == ["redact-secrets"]
