# ARCEN TUI — visual prototype

Standalone, self-streaming demo of a redesigned terminal UI. **No arcen
package imports** — the event stream is scripted, so it runs anywhere with
Textual installed and is safe to throw away or rewrite.

## Run it live

```bash
pip install textual
python prototype/arcen_tui_demo.py
```

The demo plays one full run by itself: goal → streaming thoughts → live plan
checklist → bash output streaming line-by-line → file diff → TEMPER
verification → answer, with the run-state rail updating throughout.

## Regenerate the screenshots

```bash
python prototype/capture.py          # headless, writes shots/*.svg
python prototype/render_png.py        # SVG -> PNG via CairoSVG + Fira Code
```

> Rendering note: the SVGs hardcode Fira Code cell metrics. Convert them with
> CairoSVG (not ImageMagick's default renderer, which substitutes fonts and
> drifts style-run positions). Install the font to
> `~/.local/share/fonts/` and run `fc-cache` first.

## Design language

- **Mission-control dark ink** (`#0B0E14`), one violet accent (`#A78BFA`),
  semantic colors only for state: cyan = tool/forge, amber = active verify,
  emerald = pass, rose = fail (reserved, unused in the happy path).
- **Narration spine** (left column): every event is a card on one vertical
  timeline — thoughts in italic with a streaming block cursor, tool calls as
  terminal cards with exit-status footers, diffs as green-addition blocks,
  verification as checklists, answer as the closing card.
- **Run-state rail** (right column): step counter, DRAFT/FORGE/TEMPER/DONE
  phase tracker, context-window meter, spend, tools used, environment
  posture, harness ref — everything "sit and watch" at a glance.
- **Header/footer chrome**: session + model + quarantine posture + live
  phase pill on top; keybind hints and a blinking LIVE indicator on the
  bottom.

## What is intentionally not built yet

Input box, real server wiring, scrollback search, panels/modals, harness
approval cards (ARCEN²), and tests. This is a visual prototype for
direction-setting; the shipped `src/arcen/tui/` is untouched.
