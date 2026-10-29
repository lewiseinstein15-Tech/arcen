#!/usr/bin/env bash
# Rootless bootstrap for scripts/terminal_shot.py — real-terminal screenshots.
#
# Installs Playwright + headless Chromium and, because the sandbox has no
# root, fetches Chromium's Debian shared libraries with `apt-get download`
# and extracts them into ~/.local/chromium-libs (LD_LIBRARY_PATH at launch
# time, see terminal_shot.py). Nothing is installed system-wide.
set -euo pipefail

PREFIX="${HOME}/.local/chromium-libs"
LIBDIR="${PREFIX}/usr/lib/x86_64-linux-gnu"
SHELL_BIN="$(ls -d "${HOME}"/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell 2>/dev/null | head -1 || true)"

python -m pip install --quiet --upgrade playwright aiohttp ptyprocess
python -m playwright install chromium

missing() { LD_LIBRARY_PATH="${LIBDIR}" ldd "$1" 2>/dev/null | grep "not found" || true; }

if [ -n "${SHELL_BIN}" ] && [ -z "$(missing "${SHELL_BIN}")" ]; then
  echo "chromium dependencies already satisfied"
  exit 0
fi

PACKAGES=(
  libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64
  libxkbcommon0 libxdamage1 libasound2t64 libcups2t64 libdrm2 libgbm1
  libxcomposite1 libxrandr2 libxshmfence1 libepoxy0 libwayland-client0
  libwayland-server0 libwayland-egl1 libpango-1.0-0 libpangocairo-1.0-0
  libcairo2 libxkbcommon-x11-0
)

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
cd "${WORK}"
echo "downloading ${#PACKAGES[@]} Debian packages (no root)…"
apt-get download "${PACKAGES[@]}" >/dev/null
mkdir -p "${PREFIX}"
for deb in *.deb; do dpkg-deb -x "${deb}" "${PREFIX}"; done

SHELL_BIN="$(ls -d "${HOME}"/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell | head -1)"
if [ -n "$(missing "${SHELL_BIN}")" ]; then
  echo "ERROR: chromium still has missing libraries:" >&2
  missing "${SHELL_BIN}" >&2
  exit 1
fi
echo "terminal-shot tooling ready — e.g.:"
echo "  python scripts/terminal_shot.py --cols 132 --rows 44 --wait 20 \\"
echo "      --out docs/verify/TUI-NN-real.png -- arcen-tui --demo"
