"""Recompute src/arcen/harness.toml hashes after editing a pinned component.

Boot verifies every component in the bundled manifest, so a prompt, policy or
tool-manifest edit fails closed until the hashes are updated. Run this after
touching anything listed in harness.toml:

    .venv/bin/python scripts/pin_harness.py          # rewrite hashes
    .venv/bin/python scripts/pin_harness.py --check  # exit 1 when stale
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "arcen"
MANIFEST = ROOT / "harness.toml"
LINE = re.compile(r'^"([^"]+)" = "([0-9a-f]{64})"$', re.MULTILINE)


def main(argv: list[str]) -> int:
    text = MANIFEST.read_text()
    stale = [
        name
        for name, pinned in LINE.findall(text)
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != pinned
    ]
    if "--check" in argv:
        for name in stale:
            print(f"stale: {name}")
        return 1 if stale else 0
    for name in stale:
        digest = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        text = re.sub(
            rf'^"{re.escape(name)}" = "[0-9a-f]{{64}}"$',
            f'"{name}" = "{digest}"',
            text,
            flags=re.MULTILINE,
        )
    MANIFEST.write_text(text)
    print(f"repinned {len(stale)} component(s)" if stale else "already pinned")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
