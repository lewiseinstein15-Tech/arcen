"""Check local Markdown links in the TUI guide and project README."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []
for path in (ROOT / "README.md", ROOT / "docs/TUI.md"):
    links = re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8"))
    local = []
    for target in links:
        target = target.split("#", 1)[0].split(" ", 1)[0]
        if not target or target.startswith(("http:", "https:", "mailto:")):
            continue
        local.append(target)
        if not (path.parent / target).exists():
            errors.append(f"{path.relative_to(ROOT)}: missing {target}")
    print(f"{path.relative_to(ROOT)}: checked {len(local)} local links")
if errors:
    raise SystemExit("\n".join(errors))
print("All local links exist.")
