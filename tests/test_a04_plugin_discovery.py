"""Disabled plugin modules must never execute merely during discovery."""

from arcen.plugins.loader import PluginLoader


def test_disabled_plugin_module_not_imported(tmp_path):
    marker = tmp_path / "marker"
    (tmp_path / "disabled.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n"
    )
    assert PluginLoader(enabled=[], paths=[str(tmp_path)]).load() == {}
    assert not marker.exists()


def test_enabled_plugin_filename_is_normalized_and_loaded(tmp_path):
    marker = tmp_path / "marker"
    (tmp_path / "cost_guard.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n"
        "from arcen.plugins.loader import Plugin\n"
        "class Guard(Plugin):\n    name = 'cost-guard'\n"
    )
    assert "cost-guard" in PluginLoader(enabled=["cost-guard"], paths=[str(tmp_path)]).load()
    assert marker.exists()


def test_different_filename_not_imported_even_when_declared_name_would_match(tmp_path):
    marker = tmp_path / "marker"
    (tmp_path / "other.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n"
        "from arcen.plugins.loader import Plugin\n"
        "class Guard(Plugin):\n    name = 'cost-guard'\n"
    )
    assert PluginLoader(enabled=["cost-guard"], paths=[str(tmp_path)]).load() == {}
    assert not marker.exists()
