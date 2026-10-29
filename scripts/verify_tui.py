#!/usr/bin/env python3
"""Run the offline demo and documentation check; terminal captures are separate.

For genuine screenshots use scripts/terminal_shot.py, as described in docs/TUI.md.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    subprocess.run([sys.executable, str(ROOT / "scripts/check_tui_docs.py")], check=True)
    subprocess.run([sys.executable, "-m", "arcen.tui", "--demo", "--replay"], check=True, cwd=ROOT)
    print("TUI offline replay and documentation checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
