"""Phase 0 observations; all plugin files and markers are temporary fixtures."""

from pathlib import Path
from tempfile import TemporaryDirectory

from arcen.config import ArcenConfig
from arcen.plugins.loader import PluginLoader
from arcen.skills.loader import SkillsLoader
from arcen.stream.events import EVENT_TYPES
from arcen.tools.registry import load_builtin


def main() -> None:
    tools = load_builtin().names()
    config = ArcenConfig()
    skills = SkillsLoader(paths=["./skills"]).index()
    print(f"built-in tools ({len(tools)}): {', '.join(tools)}")
    print(f"frozen event types ({len(EVENT_TYPES)}): {', '.join(EVENT_TYPES)}")
    print(f"repository skills ({len(skills)}): {', '.join(sorted(skills))}")
    print(f"default configured MCP servers: {len(config.mcps)}")
    print(f"default enabled plugins: {len(config.plugins.enabled)}")
    with TemporaryDirectory() as directory:
        root = Path(directory)
        marker = root / "imported.txt"
        (root / "disabled.py").write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('fixture')\n"
            "from arcen.plugins.loader import Plugin\n"
            "class Disabled(Plugin):\n    name = 'disabled'\n",
            encoding="utf-8",
        )
        loaded = PluginLoader(enabled=[], paths=[str(root)]).load()
        print(
            f"disabled plugin import executed: {marker.exists()}; enabled plugins loaded: {len(loaded)}"
        )
        assert marker.exists() and not loaded
    print("fixture reproduced; no external plugins or accounts used")


if __name__ == "__main__":
    main()
