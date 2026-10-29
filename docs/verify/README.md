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
# inject real keystrokes into the PTY (scroll/pause/resume evidence):
#   --send-at 6.0:pageup --send-at 9.4:end   (keys: pageup/pagedown/home/end/…)
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
| `TUI-05.png` | TUI-05 ticket tests, verbose: **38 passed, 1 skipped** (rail + shell + demo + entry) |
| `TUI-05-real-idle-rail.png` | **Real terminal**: idle `ARCEN_TUI=new` rail — step 0/0, all phases pending, neutral placeholders |
| `TUI-05-real-rail-mid.png` | **Real terminal**, live at TEMPER: state-driven rail step 3/4, verify row running |
| `TUI-05-real-rail-done.png` | **Real terminal**, run finished DONE: step 4/4, full meters, tool chips |
| `TUI-05-real-narrow.png` | **Real terminal** 80×24: rail collapsed |
| `TUI-05-real-terminal-sheet.png` | All four real-terminal rail frames in one 2×2 image |
| `TUI-05-full-suite.png` | Full repository suite after TUI-05: **416 passed, 1 skipped** |
| `TUI-06.png` | TUI-06 ticket tests, verbose: **46 passed, 1 skipped** (stream + rail + shell + demo + entry) |
| `TUI-06-real-paused.png` | **Real terminal**: PageUp pauses follow — view pinned to top while run continues; back-to-live pill visible |
| `TUI-06-real-resume.png` | **Real terminal**: End re-engages follow — back at live edge, pill hidden |
| `TUI-06-real-live.png` | **Real terminal**: normal auto-follow streaming, no scroll input |
| `TUI-06-real-narrow-paused.png` | **Real terminal** 80×24: paused with rail collapsed |
| `TUI-06-real-terminal-sheet.png` | All four scroll-rule frames in one 2×2 image |
| `TUI-06-full-suite.png` | Full repository suite after TUI-06: **424 passed, 1 skipped** |
| `TUI-07.png` | TUI-07 ticket and prior TUI tests: **68 passed, 1 skipped** |
| `TUI-07-real-thought-streaming.png` | **Real terminal**: shared goal and thought card, streaming cursor |
| `TUI-07-real-paused.png` | **Real terminal**: completed goal and thought while paused |
| `TUI-07-real-narrow.png` | **Real terminal**: streaming thought at 80×24 |
| `TUI-07-real-live.png` | **Real terminal**: completed demo |
| `TUI-07-real-terminal-sheet.png` | Four fresh real-terminal captures |
| `TUI-07-full-suite.png` | Full repository suite after TUI-07: **446 passed, 1 skipped** |
| `TUI-08.png` | Ticket and prior TUI tests: **79 passed, 1 skipped** |
| `TUI-08-real-plan-command.png` | **Real terminal**: plan checklist and command output |
| `TUI-08-real-diff.png` | **Real terminal**: file diffs and verification |
| `TUI-08-real-narrow.png` | **Real terminal**: 80×24 narrow view |
| `TUI-08-real-terminal-sheet.png` | Fresh real-terminal capture sheet |
| `TUI-08-full-suite.png` | Full repository suite: **457 passed, 1 skipped** |
| `TUI-09.png` | Ticket and prior TUI tests: **87 passed, 1 skipped** |
| `TUI-09-real-verifying.png` | **Real terminal**: verification in progress |
| `TUI-09-real-answer.png` | **Real terminal**: completed answer at live edge; xterm buffer inspected |
| `TUI-09-real-narrow.png` | **Real terminal**: 80×24 completed demo |
| `TUI-09-real-run-marker.png` | **Real terminal**: run marker and paused history |
| `TUI-09-real-terminal-sheet.png` | Four fresh real-terminal captures |
| `TUI-09-full-suite.png` | Full repository suite: **465 passed, 1 skipped** |
| `TUI-10.png` | Ticket and prior TUI tests: **101 passed, 1 skipped** |
| `TUI-10-real-failure.png` | **Real terminal**: recorded failing command and amber re-plan |
| `TUI-10-real-replan.png` | **Real terminal**: corrected plan after recorded failure |
| `TUI-10-real-done.png` | **Real terminal**: adapter-driven recovery and final answer |
| `TUI-10-real-narrow.png` | **Real terminal**: 80×24 recorded replay |
| `TUI-10-real-terminal-sheet.png` | Four fresh PTY/xterm captures from `arcen-tui --demo --replay` |
| `TUI-10-full-suite.png` | Full repository suite: **479 passed, 1 skipped** |
| `TUI-11.png` | Live integration and regression tests: **66 passed** |
| `TUI-11-real-reconnect.png` | **Real terminal** against mock NDJSON server: reconnect and degraded sandbox |
| `TUI-11-real-done.png` | **Real terminal** against mock NDJSON server: resumed through answer |
| `TUI-11-real-narrow.png` | **Real terminal**: live mock NDJSON at 80×24 |
| `TUI-11-full-suite.png` | Full suite: **484 passed, 1 skipped** |
| `TUI-12.png` | Interrupt and regression tests: **27 passed** |
| `TUI-12-real-confirm.png` | **Real terminal**: interrupt confirmation against local mock server |
| `TUI-12-real-interrupted.png` | **Real terminal**: server-confirmed interrupted run |
| `TUI-12-full-suite.png` | Full suite: **486 passed, 1 skipped** |
| `TUI-13.png` | Composer and regression tests: **31 passed** |
| `TUI-13-real-slash.png` | **Real terminal**: slash-command suggestions |
| `TUI-13-real-compose.png` | **Real terminal**: multiline goal before submission |
| `TUI-13-real-submit.png` | **Real terminal**: posted goal and mock-server answer |
| `TUI-13-full-suite.png` | Full suite: **490 passed, 1 skipped** |
| `TUI-14.png` | Sessions and regression tests: **27 passed** |
| `TUI-14-real-drawer.png` | **Real terminal**: isolated fixture session picker |
| `TUI-14-real-replay.png` | **Real terminal**: selected recorded session replay |
| `TUI-14-full-suite.png` | Full suite before final drawer styling: **492 passed, 1 skipped** |
| `TUI-15.png` | Modal and regression tests: **16 passed** |
| `TUI-15-real-config.png` | **Real terminal**: redacted read-only configuration and sandbox |
| `TUI-15-real-sandbox.png` | **Real terminal**: degraded sandbox detail |
| `TUI-15-full-suite.png` | Full suite: **495 passed, 1 skipped** |
