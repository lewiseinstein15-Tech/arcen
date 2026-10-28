# Verification screenshots

Standing convention for the TUI redesign (TUI-01…18) and ARCEN² harness
rebuild (H-01…22): **every ticket ends with a screenshot of its verification
test**, saved here as `<TICKET>.png` (with the source `.svg` alongside).

## Regenerate

```bash
# one-time on a fresh machine: Fira Code font + CairoSVG + fontTools
bash scripts/setup_capture.sh

# pytest-style verification (SVG + PNG, forced ANSI colors)
python scripts/verify_shot.py <TICKET> "<test command>"

# real running-app capture (headless pilot, full scripted turn)
python scripts/verify_tui.py
# then rasterize docs/tui-screenshot*.svg with CairoSVG

# redesigned-shell demo frames (mission-control prototype, TUI-03+)
python scripts/capture_demo.py <TICKET>

# app-shell frames: wide rail, collapsed rail, bare shell (TUI-04+)
python scripts/capture_shell.py <TICKET>

# REAL TERMINAL pixels — actual command in a PTY, xterm.js in headless
# Chromium (not a Textual SVG export). One-time browser setup:
bash scripts/setup_terminal_shot.sh
python scripts/terminal_shot.py --cols 132 --rows 44 --wait 20 \
    --out docs/verify/<TICKET>-real.png -- arcen-tui --demo
# narrow / other commands: --cols 80 --rows 24, and --env KEY=VAL (repeatable)
```

### Two kinds of frame

* **SVG exports** (`capture_demo.py`, `capture_shell.py`) — Textual renders
  its own widget tree to SVG, rasterized with CairoSVG. Deterministic and
  fast, but a library render, not a terminal.
* **Real-terminal frames** (`terminal_shot.py`, filenames contain `real`) —
  the installed command runs in a real PTY with real termios sizing; bytes
  flow over a websocket into xterm.js inside headless Chromium, which is
  then screenshot. These show genuine terminal rasterization (glyphs,
  scrollbars, 256/truecolor handling) and are the primary visual evidence
  from TUI-04 onward.

The pytest helper replays output through Rich and writes an SVG terminal
recording plus a CairoSVG PNG on the ARCEN dark ink (`#0B0E14`). The app
capture drives the actual Textual app with a scripted in-memory client —
no server or sockets — through a complete narrated turn.

## Files

| File | Contents |
|---|---|
| `TUI-01.png` | TUI-01 ticket tests, verbose: **46 TUI tests passed** (5 entry + 9 app + 10 render + 10 client + 12 launcher) |
| `TUI-01-full-suite.png` | Full repository suite after the TUI-01 restructure: **362 passed** |
| `TUI-01-app-transcript.png` | **Real app capture** — legacy `arcen-tui` running an 18-event turn (spawn → fail → re-plan → diff → verify → answer) through the headless pilot |
| `TUI-01-app-config-modal.png` | **Real app capture** — configuration (redacted) + sandbox status modal, degraded process backend shown honestly |
| `TUI-02.png` | TUI-02 ticket tests, verbose: **21 passed** (14 theme token/fallback tests + 7 key-map tests) |
| `TUI-02-palette.png` | Visual swatch sheet — all 13 tokens with hex, xterm-256 code, luminance, and the phase/status/card semantic mappings |
| `TUI-02-full-suite.png` | Full repository suite after TUI-02: **383 passed** |
| `TUI-03.png` | TUI-03 ticket tests, verbose: **11 passed, 1 skipped** (snapshot test is env-gated) |
| `TUI-03-demo-forge.png` / `demo-forge-mid.png` / `demo-finished.png` | Real headless frames of the maintained `arcen-tui --demo` app at three checkpoints |
| `TUI-03-contact-sheet.png` | All three demo checkpoints in one image with labels |
| `TUI-03-test-evidence.png` | Ticket tests + full-suite frames in one image |
| `TUI-03-full-suite.png` | Full repository suite after TUI-03: **389 passed, 1 skipped** |
| `TUI-04.png` | TUI-04 ticket tests, verbose: **22 passed, 1 skipped** (shell + demo + entry) |
| `TUI-04-shell-wide.png` / `-narrow.png` / `-empty.png` | **Real headless app captures** — redesigned shell at 132×44 (rail beside spine), 80×24 (rail collapsed, full-width spine), and the bare `ARCEN_TUI=new` shell (IDLE, placeholder rail) |
| `TUI-04-contact-sheet.png` | All three SVG shell frames in one labeled image |
| `TUI-04-real-demo-wide.png` | **Real terminal** (132×44 PTY → xterm.js → Chromium): demo finished, DONE |
| `TUI-04-real-demo-mid.png` | **Real terminal**, caught mid-run at TEMPER: step 3/4, live verify row |
| `TUI-04-real-demo-narrow.png` | **Real terminal** 80×24 PTY: rail collapsed, narration full width |
| `TUI-04-real-shell-empty.png` | **Real terminal**: bare `ARCEN_TUI=new` shell, IDLE, no server attached |
| `TUI-04-real-terminal-sheet.png` | All four real-terminal frames in one labeled 2×2 image |
| `TUI-04-full-suite.png` | Full repository suite after TUI-04: **400 passed, 1 skipped** |
