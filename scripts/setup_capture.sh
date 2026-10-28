#!/usr/bin/env bash
# Bootstrap the screenshot tooling for a fresh environment (TUI-03+).
#
# The headless Textual SVGs hardcode Fira Code metrics; without the font
# installed, CairoSVG substitutes another face and middle-dot / style-run
# spacing drifts. This installs the variable TTF into the user font dir and
# the Python rasterizers. Safe to re-run.
set -euo pipefail

FONT_DIR="${HOME}/.local/share/fonts"
FONT="${FONT_DIR}/FiraCode-VF.ttf"
FONT_URL="https://raw.githubusercontent.com/google/fonts/main/ofl/firacode/FiraCode%5Bwght%5D.ttf"

mkdir -p "${FONT_DIR}"
if [ ! -f "${FONT}" ]; then
  echo "installing Fira Code variable font…"
  curl -fsSL -o "${FONT}" "${FONT_URL}"
  fc-cache -f "${FONT_DIR}" >/dev/null
else
  echo "Fira Code already present: ${FONT}"
fi

python -m pip install --quiet --upgrade cairosvg fonttools
echo "capture tooling ready — regenerate frames with:"
echo "  python scripts/capture_demo.py <TICKET>"
