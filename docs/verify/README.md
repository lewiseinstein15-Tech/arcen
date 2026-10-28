# Verification screenshots

Standing convention for the TUI redesign (TUI-01…18) and ARCEN² harness
rebuild (H-01…22): **every ticket ends with a screenshot of its verification
test**, saved here as `<TICKET>.png` (with the source `.svg` alongside).

## Regenerate

```bash
# pytest-style verification (SVG + PNG, forced ANSI colors)
python scripts/verify_shot.py <TICKET> "<test command>"

# real running-app capture (headless pilot, full scripted turn)
python scripts/verify_tui.py
# then rasterize docs/tui-screenshot*.svg with CairoSVG
```

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
