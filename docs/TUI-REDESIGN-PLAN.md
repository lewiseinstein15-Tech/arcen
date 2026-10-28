# TUI Redesign — Rebuild Plan

> Part of the sequenced rebuild: see [REBUILD-MASTER-PLAN.md](REBUILD-MASTER-PLAN.md)
> for milestone gates and the parallel ARCEN² harness track.
>
> Status: **plan, no production code changed.** Date: 2026-10-28.
> Approved visual direction: `prototype/arcen_tui_demo.py` + the three frames
> in `prototype/shots/` ("mission control": narration spine + run-state rail).
> Ticket style and verification loop follow [TICKETS.md](TICKETS.md).
> Branch proposal: `feat/tui-redesign`, cut from `main` @ `3d32166`.

---

## 1. Decisions locked in (defaults — override before TUI-01 starts)

| # | Decision | Choice |
|---|---|---|
| D1 | Placement | **Rewrite in place** inside `src/arcen/tui/` on a feature branch; old modules move to `tui/_legacy/` and are deleted only at cutover (Phase 6). Same `arcen-tui` command throughout. |
| D2 | Backend target | **The 17 frozen events only.** ARCEN² harness views are designed as named extension points, not built (§8). |
| D3 | Reused as-is | `client.py` (NDJSON client), `launcher.py` (managed server), `__main__.py`. Zero changes expected. |
| D4 | Rebuilt | `app.py`, `render.py`, `widgets.py` → replaced by the package layout in §4. Their 29 tests are rewritten; the 12 launcher tests and all client tests stay. |
| D5 | Demo mode | Prototype's scripted driver becomes a supported `arcen-tui --demo` flag — useful for screenshots, onboarding, and offline tests. |
| D6 | Framework | Textual 8.x, Rich only for renderables. No new runtime dependency. |
| D7 | Terminals | Truecolor primary; every token gets a 256-color fallback. Must stay legible in Kitty, foot, tmux, and a dumb 80×24 SSH session. |

## 2. What the prototype proved (and what it did not)

**Proved and frozen:** design tokens (`#0B0E14` ink, `#A78BFA` violet accent,
cyan/amber/emerald/rose semantics), card-on-spine narration, run-state rail,
streaming block-cursor treatment, header/footer chrome.

**Known prototype limitations the rebuild must fix:**

1. It is one 540-line file with scripted data and no event adapter.
2. `Static.refresh()` does not re-measure — production must use
   `Static.update(Group(...))` (already proven in the prototype's `_sync`).
3. SVG/PNG tooling (CairoSVG, Fira Code) is a **test-only** concern; the
   running TUI must not depend on either and must define a font fallback chain.
4. No input/composer, no reconnect logic, no modals, no session switcher.
5. No failure/error styling yet (`run.error`, `step.fail`, interrupts).
6. Rail is fixed-width 38; needs a responsive collapse under ~100 columns.

## 3. Feature parity matrix (old TUI → new TUI)

| Existing feature (shipped) | New TUI | Notes |
|---|---|---|
| NDJSON live stream, all 17 events | ✅ mandatory | event→card map in §5 |
| `Last-Event-ID` resume / replay | ✅ mandatory | reconnect banner + gap indicator |
| Sessions list + replay sidebar | ✅ mandatory | rail or left drawer, TUI-09 |
| Interrupt run (`DELETE /api/run/{id}`) | ✅ mandatory | `^C` confirmation card in-stream |
| Config modal | ✅ mandatory | restyled modal, same `PUT /api/config` |
| Sandbox status modal | ✅ mandatory | sources the rail's ENVIRONMENT block |
| Ctrl-prefixed shortcut scheme | ✅ mandatory | key map frozen in TUI-02 |
| Managed-server launcher | ✅ inherited | `launcher.py` untouched |
| Offline/degraded banner | ✅ mandatory | honest refusal styling |
| `--url / --session / --no-serve` flags | ✅ mandatory | unchanged surface |
| `--demo` scripted run | 🆕 | prototype driver, D5 |
| Harness/approval views (ARCEN²) | ⛔ extension only | §8 |

## 4. Target package layout

```
src/arcen/tui/
  __init__.py            # public run() entry — unchanged signature
  __main__.py            # unchanged
  app.py                 # App shell: compose, modes, key bindings, lifecycle
  client.py              # UNCHANGED — NDJSON transport
  launcher.py            # UNCHANGED — managed uvicorn
  theme.py               # design tokens, Color objects, 256 fallback table
  keys.py                # frozen key-binding map + help screen content
  cards/
    __init__.py          # event type → card factory registry
    base.py              # SpineCard (node glyph + rounded panel + streaming helper)
    goal.py              # user goal card
    thought.py           # streaming italic thought (word-batch cursor)
    plan.py              # plan checklist with live plan.update mutation
    command.py           # bash/tool card: streaming stdout, exit footer
    diff.py              # file.diff additions/deletions
    verify.py            # verify.start / step.pass / step.fail checklist
    answer.py            # closing answer, inline markup
    system.py            # run.start / run.done / run.error / memory / usage
  views/
    stream.py            # narration spine VerticalScroll (auto-scroll rules)
    rail.py              # run-state rail (progress, phases, meters, env, harness)
    sessions.py          # session drawer
    modals.py            # config + sandbox modals, interrupt confirm
    composer.py          # input box, multiline, slash commands, ^G editor
  state.py               # client-side view model: run state, plan index, rail data
  adapter.py             # 17 wire events → state mutations + card factory calls
  demo.py                # scripted driver ported from the prototype
tests/
  test_tui_theme.py      # token completeness, fallback resolution
  test_tui_cards.py      # pure renderable tests (no app needed)
  test_tui_adapter.py    # event fixtures → expected state/card sequence
  test_tui_app.py        # headless pilot tests (run_test), incl. --demo
  test_tui_launcher.py   # UNCHANGED (12 existing tests)
  test_tui_client.py     # UNCHANGED (existing client tests)
```

## 5. Event → card mapping (the contract for `adapter.py`)

| Wire event | Card / mutation | Stream behavior |
|---|---|---|
| `run.start` | header phase pill → DRAFT; rail resets; divider | new run marker on spine |
| `think` | `thought.py` card, streamed token batches, blinking `▍` | card mutates in place until done |
| `plan` | `plan.py` checklist card, index stored in state | created once |
| `plan.update` | mutate checklist statuses (pending/active/done/fail) | in-place, no new card |
| `spawn` / `spawn.done` | indented nested spine node (T-011 events; render today even though server rarely emits) | nesting depth ≤ 2 |
| `command` | `command.py` card, streaming stdout lines | in-place mutation |
| `command.done` | footer with exit code/duration; rose styling on non-zero | closes the card |
| `file.diff` | `diff.py` card, green add / rose del lines | append card |
| `verify.start` | `verify.py` card with first active row | append card |
| `step.pass` | green ✓ row; rail progress +1 | mutate card + rail |
| `step.fail` | rose ✕ row; rail phase → re-plan amber | mutate card; failure styling |
| `answer` | `answer.py` closing card | append, auto-scroll |
| `memory` | subtle one-line system chip (not a full card) | low-emphasis |
| `usage` | **rail only** — context meter, spend, tool chips | never a spine card |
| `run.done` | phase pill → DONE; LIVE indicator stops blinking | header/footer only |
| `run.error` | rose error card with retry hint; phase pill → ERROR | full-width emphasis |

Unknown event types are ignored with a debug log — forward-compatibility rule
so additive ARCEN² events never crash the TUI.

## 6. Phased tickets

Size scale: S ≤ half day, M ~1 day, L ~2 days. Each ticket follows the
TICKETS.md verification loop; the full TUI test subset is re-run between
tickets. Commit prefix `TUI-NN:`.

### Phase 0 — Scaffolding (no user-visible change)

> Progress: **TUI-01 done — verified** (362 passed; TUI subset 46 passed;
> evidence `docs/verify/TUI-01.png`, `TUI-01-full-suite.png`, plus real-app
> captures `TUI-01-app-transcript.png` and `TUI-01-app-config-modal.png`).

| Ticket | Size | Deliverable | Verification |
|---|---|---|---|
| **TUI-01** Branch + skeleton ✅ | S | `feat/tui-redesign`; old modules moved to `tui/_legacy/`; new `cards/`, `views/` dirs; legacy stays the default behind the `ARCEN_TUI` env flag; new shell refused cleanly pre-TUI-04 | 5 new entry tests + all 357 prior tests green (362 total); wheel contains all TUI modules; `arcen-tui --help` resolves through legacy |
| **TUI-02** Theme + key map ✅ | M | `theme.py` (13 prototype tokens, computed xterm-256 fallbacks, phase/status/card semantic maps, CSS custom-property block, font stack), `keys.py` (frozen global/composer/modal bindings, scoped Textual factory, footer hints) | 21 new tests (`test_tui_theme.py` 14, `test_tui_keys.py` 7); every token resolves at truecolor and 256; palette sheet `docs/verify/TUI-02-palette.png`; full suite 383 passed |
| **TUI-03** Headless test harness + `--demo` ✅ | M | `tui/demo.py` (prototype ported onto theme tokens; durable phase checkpoints), `arcen-tui --demo` routing incl. no-TTY headless exit, `tests/_tui_snapshot.py` SVG/PNG helper, `scripts/capture_demo.py` reusable frame capture; fixes: console-script argv routing, transient-phase wait race | 6 new demo tests + 1 regression; demo runs headless with no server spawned; frames in `docs/verify/TUI-03-demo-*.png`; full suite 389 passed, 1 skipped (env-gated snapshot) |

### Phase 1 — Shell

| Ticket | Size | Deliverable | Verification |
|---|---|---|---|
| **TUI-04** App shell | M | header (session/model/quarantine/phase pill), footer (hints + LIVE), two-column layout, responsive rail collapse at <100 cols | pilot test asserts widget tree at 132×44 and 80×24 |
| **TUI-05** Run-state rail | M | `views/rail.py`: step counter, phase tracker, context meter, spend, tools, environment, harness ref | state-dict → rendered rail assertions |
| **TUI-06** Narration spine + scroll rules | S | `views/stream.py`: auto-scroll only when user is at bottom; scroll-up pauses, "↓ back to live" affordance | pilot scroll test |

### Phase 2 — Card library

| Ticket | Size | Deliverable | Verification |
|---|---|---|---|
| **TUI-07** Base + goal/thought cards | M | `cards/base.py`, streaming word-batch cursor (no per-token repaint storm) | render tests; cursor present/absent states |
| **TUI-08** Plan + command + diff cards | L | checklist mutation, streaming stdout with output cap ("… N more lines"), exit footer, diff coloring | fixture-driven render tests incl. non-zero exit |
| **TUI-09** Verify + answer + system cards | M | pass/fail rows, error card, memory chip, run markers | all 17 events have at least one render test |

### Phase 3 — Wire it to the real server

| Ticket | Size | Deliverable | Verification |
|---|---|---|---|
| **TUI-10** View model + adapter | L | `state.py`, `adapter.py`, card factory registry; full §5 mapping | `test_tui_adapter.py` replays recorded session jsonl fixtures → exact card sequence assertions |
| **TUI-11** Live integration | L | real `client.py` stream drives the adapter; reconnect with `Last-Event-ID`, gap banner, offline/degraded states | pilot test against a mock NDJSON server; recorded-fixture replay end to end |
| **TUI-12** Interrupt + error paths | M | `^C` confirm card → `DELETE /api/run/{id}`; `run.error` rose card; non-zero command styling | adapter + pilot tests for each failure path |

### Phase 4 — Input and chrome parity

| Ticket | Size | Deliverable | Verification |
|---|---|---|---|
| **TUI-13** Composer | L | multiline input, slash-command autocomplete, `^G` external editor, submit → `POST /api/run` | pilot typing/submit tests |
| **TUI-14** Sessions drawer | M | list/replay from session store, `^R` resume | fixture sessions render and switch |
| **TUI-15** Modals | M | config + sandbox modals restyled to tokens; same API calls as legacy | pilot open/close/submit tests |

### Phase 5 — Hardening

| Ticket | Size | Deliverable | Verification |
|---|---|---|---|
| **TUI-16** Resize/terminal matrix | M | 80×24 legibility, long-output caps, wide-character handling, tmux check | matrix of pilot sizes; no clipped mandatory info |
| **TUI-17** Docs + screenshots | S | rewrite `docs/TUI.md`, new SVG/PNG screenshots via the TUI-03 helper, README refresh | docs link-check; screenshots generated from `--demo` |

### Phase 6 — Cutover

| Ticket | Size | Deliverable | Verification |
|---|---|---|---|
| **TUI-18** Delete legacy | M | remove `tui/_legacy/`; wheel contents check; `arcen-tui` single implementation; full suite (target ≥ existing 357, adjusted for rewritten tests), ruff clean | clean install into a fresh venv; demo + live run both work; no legacy imports remain |

**Critical path:** TUI-01 → 02 → 03 → 04 → 07 → 10 → 11. Everything else
parallelizes. Estimated total: ~10–12 focused working days.

## 7. Test strategy

- **Pure renderables first.** Cards take data, return Rich renderables — most
  tests need no running app and stay fast.
- **Recorded fixtures.** Capture real session jsonl files (anonymized) into
  `tests/fixtures/tui/`; the adapter replays them. This is the main defense
  against event-handling regressions and doubles as ARCEN² forward-compat
  testing (feed unknown event types, assert no crash).
- **Headless pilots** via Textual's `run_test` for layout, keys, focus,
  scrolling, modals — the prototype's capture script is the seed.
- **Visual snapshots optional and env-gated** (`ARCEN_SNAPSHOT=1`), because
  SVG golden files are brittle across font installs; structural assertions
  are the default gate.
- **Untouched guarantees:** the 12 launcher tests and existing client tests
  keep passing from TUI-01 onward; the 357-test backend suite never changes
  for this work.

## 8. ARCEN² extension points (designed now, built later)

Named seams so the harnessing work needs no second redesign:

1. **Card registry is data-driven** — `harness.propose`, `approval.request`,
   `canary.done` etc. register new card types without touching the spine.
2. **Rail already reserves the HARNESS block** (`adopted@<ref>`); future
   state fields populate it.
3. **Modal namespace** reserves an approval modal (diff/apply/reject) driven
   by future `approval.*` events.
4. **Adapter's ignore-unknown rule** means additive v2 events are safe on
   day one of the backend work.
5. **Demo driver** gains harness scenarios later as a second scripted track,
   reusing the same card factory.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Textual repaint cost on fast token streams | Batch updates (~30–50 ms coalescing, already the prototype's word-batch approach); cap stdout card lines |
| Truecolor assumptions break on SSH/tmux | D7 fallback table; TUI-16 matrix includes `TERM=xterm-256color` |
| Rail eats width on narrow terminals | TUI-04 collapse rules; rail becomes a toggleable overlay under 100 cols |
| Rewrite regresses the 29 existing app/render/widget tests' coverage | Behavior coverage re-expressed as adapter + pilot tests before legacy deletion (TUI-18 gate) |
| Prototype look depends on Fira Code | Font fallback chain in `theme.py`; no hard font dependency at runtime |
| Scope creep into ARCEN² views | §4/§8 seam-only rule; any harness UI is a separate plan |

## 10. Definition of done

1. All TUI-01…18 tickets verified under the TICKETS.md loop on
   `feat/tui-redesign`, merged to `main`.
2. Full test suite green; ruff clean; fresh-venv wheel install boots
   `arcen-tui` and `arcen-tui --demo`.
3. Every one of the 17 events demonstrably renders via fixture replay.
4. Parity matrix §3 has no unchecked mandatory row.
5. Legacy package deleted; no dead imports; docs and screenshots current.
6. Omarchy install instructions still valid unchanged.
