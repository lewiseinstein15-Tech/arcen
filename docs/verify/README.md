# Verification screenshots

Standing convention for the TUI redesign (TUI-01…18) and ARCEN² harness
rebuild (H-01…22): **every ticket ends with a screenshot of its verification
test**, saved here as `<TICKET>.png` (with the source `.svg` alongside).

## Regenerate

```bash
python scripts/verify_shot.py <TICKET> "<test command>"
# example
python scripts/verify_shot.py TUI-01 "python -m pytest tests/test_tui_entry.py -q --color=yes"
```

The helper runs the command with forced ANSI colors, replays its output
through Rich, and writes an SVG terminal recording plus a CairoSVG PNG
raster on the ARCEN dark ink (`#0B0E14`). A full-suite regression frame is
kept as `<TICKET>-full-suite.png` when a ticket touches shared code.

## Files

| File | Contents |
|---|---|
| `TUI-01.png` | TUI-01 ticket tests: entry-point flag + all existing TUI tests (40 passed) |
| `TUI-01-full-suite.png` | Full repository suite after the TUI-01 restructure (362 passed) |
