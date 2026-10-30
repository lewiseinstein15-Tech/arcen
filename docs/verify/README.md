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
| `TUI-15-real-config.png` | **Real terminal**: redacted configuration and sandbox (before editing was added in TUI-18) |
| `TUI-15-real-sandbox.png` | **Real terminal**: degraded sandbox detail |
| `TUI-15-full-suite.png` | Full suite: **495 passed, 1 skipped** |
| `TUI-16.png` | Terminal matrix and regression tests: **41 passed** |
| `TUI-16-real-80x24.png` | **Real terminal**: submitted run at 80×24 |
| `TUI-16-real-wide-chars.png` | **Real terminal**: wide-character input at 80×24 |
| `TUI-16-real-tmux.png` | **Real terminal**: live TUI inside tmux 3.5a, mock HTTP backend |
| `TUI-16-full-suite.png` | Full suite: **497 passed, 1 skipped** |
| `TUI-17.png` | Local documentation link check |
| `TUI-17-real-live.png` | **Real terminal**: redesigned TUI against isolated mock HTTP server |
| `TUI-17-real-help.png` | **Real terminal**: keyboard help |
| `TUI-17-real-demo.png` | **Real terminal**: offline recorded-event demo |
| `TUI-18.png` | Cutover and TUI regression tests: **64 passed** |
| `TUI-18-real-clean-live.png` | **Real terminal**: clean-wheel TUI, actual managed ARCEN backend, isolated local mock model provider |
| `TUI-18-real-clean-demo.png` | **Real terminal**: clean-wheel offline recorded-event demo |
| `TUI-18-real-settings-edit.png` | **Real terminal**: clean-wheel configuration editor against isolated mock HTTP server |
| `TUI-18-wheel.png` | Wheel contents: replay fixture present; legacy TUI absent |
| `TUI-11-18-real-terminal-sheet.png` | Labeled overview assembled from one real PTY capture per ticket; originals remain available at full resolution |
| `TUI-18-full-suite.png` | Full suite after removing legacy-only tests: **482 passed, 1 skipped** |

## Sandbox execution safety work

`SANDBOX-fail-closed-real-terminal.png` is a fresh capture of the installed
`arcen-tui` wheel and its own managed server in a real PTY, rendered by xterm.js
in headless Chromium. It shows the live `/api/sandbox/status` response with
Docker unavailable; it is not evidence of working container isolation.
The Docker-specific unit tests use fakes. The opt-in real-Docker isolation test
is in `tests/test_turn_isolation.py` and was skipped in the Docker-less capture
environment.

`SANDBOX-refused-run-real-terminal.png` is another fresh installed-command PTY
capture, using a local mock model provider but the real managed server and its
Docker-unavailable execution gate. It shows a planned bash step refused before
FORGE or TEMPER execute. Neither screenshot demonstrates a live Docker run.

## H-01 headless runner

`H-01-real-headless-success.png` and `H-01-real-headless-blocked.png` are
fresh captures of the installed `arcen` command in a real PTY rendered by
xterm.js/Chromium; JSON is formatted with `python -m json.tool`. The first
shows a no-tool response and exit 0; the second shows a workspace request
refused with `SANDBOX_UNAVAILABLE` and exit 1 in this Docker-less environment.
`H-01-real-headless-tests.png` records the real focused pytest run in the same
PTY capture harness. The real-Docker workspace test is opt-in and was skipped
in this environment; these images are not proof of live workspace import.

### H-01 workspace import follow-up

The first real Docker workspace test on Omarchy failed because Docker refuses
`put_archive` on a read-only container rootfs, even for a tmpfs destination.
`H-01-real-import-fix-tests.png` is a fresh PTY/xterm capture of the revised
focused tests. They include the real Docker SDK speaking over TCP and Unix
sockets to a **fake** engine, and a local extraction process; they are not a
real Docker-daemon test. The read-only rootfs is retained. The user subsequently
reported the live Docker workspace test passing on Omarchy at `d6f805d`; see
[H-01-OMARCHY.md](H-01-OMARCHY.md) for the transcript summary. H-01 still
has an unresolved harness-reference requirement.

## H-02 file-based prompts

`H-02-real-live-tui.png` is a fresh capture of the final wheel's installed
`arcen-tui` and its managed server in a real PTY, rendered by xterm.js in
headless Chromium. A local mock provider classified and answered the `hello`
turn using the newly packaged prompts; the capture waits for the DONE state.
Docker was unavailable and tools were blocked; this direct-answer run did not
exercise Docker. The mock provider and managed server were stopped afterward.

`H-02-real-prompt-tests.png` captures the real focused pytest run in a PTY.
The golden fixture `tests/fixtures/prompts/H-02-before.json` was recorded from
the pre-externalization code against a deterministic mock provider; 12 full
provider payloads are compared byte-for-byte after the change. The final full
suite reported **535 passed, 3 skipped**. The wheel was built and its four
prompt files and installed-resource resolution were verified separately.


## H-03 guardrails and tool guidance

`H-03-real-live-tui.png` is a fresh capture of the final H-03 wheel's installed
`arcen-tui` and managed server in a real PTY, rendered by xterm.js in headless
Chromium. A local mock provider answered `hello`; the capture waits for DONE.
Docker was unavailable, so tool execution was blocked and this run did not
exercise container isolation. The provider and managed server were stopped.

`H-03-real-policy-tests.png` is a fresh PTY/xterm capture of the actual focused
pytest run: **54 passed**. These include invalid-policy startup failures,
mocked Docker limit enforcement, and all 12 pre-H-02 provider-payload golden
comparisons. The full local suite reported **572 passed, 3 skipped**. The
installed wheel was separately checked for both guidance and policy files and
loaded them outside the source tree. The local Docker tests remained skipped;
no new real-Docker claim is made for H-03. Previously reported user Omarchy
results are documented above.

## H-04 bundled manifest foundation (partial)

`H-04-real-live-tui.png` is a fresh PTY/xterm/Chromium screenshot of the
installed H-04 wheel and managed server, with a local mock model provider.
It captures a completed direct-answer turn; Docker was unavailable and tools
were blocked. `H-04-real-manifest-tests.png` is a fresh capture of the focused
manifest suite: **21 passed**. The final full suite reported **593 passed,
3 skipped**. An earlier concurrently loaded test run timed out while importing
another test subprocess; the subprocess timeout was increased, and the full
suite passed when rerun. The manifest verifies hashes but is unsigned, the
shipped model selection remains provider-configured, and the eight-component
package and trust-root work remain incomplete. No live Docker claim is made.

## H-05 content-addressed store foundation

`H-05-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the
installed H-05 wheel and managed server completing a direct-answer turn with a
local mock provider. Docker was unavailable and tools were blocked.
`H-05-real-store-tests.png` captures the focused pytest run: **6 passed**.
The full local suite reported **599 passed, 3 skipped**; the installed wheel's
store API was also exercised separately. This is a local API foundation, not a
ref store, adoption mechanism, signed store or a git-backed implementation.

## H-06 refs and lineage metadata foundation

`H-06-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the final
installed H-06 wheel, its managed server and a local mock provider, after a
completed direct-answer turn. Docker was unavailable and tools were blocked.
`H-06-real-lineage-tests.png` captures the focused pytest run: **7 passed**.
The final full local suite reported **606 passed, 3 skipped**; installed wheel
loading and a private SQLite database were checked separately. The metadata refs
are not connected to runtime harness selection or adoption; no live-Docker
claim is made for this ticket.

## H-07 inspection CLI (partial)

`H-07-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the final
installed H-07 wheel, its managed server and a local mock provider, after a
completed direct-answer turn. Docker was unavailable and tools were blocked.
`H-07-real-cli-tests.png` captures the focused CLI suite: **7 passed**.
The full local suite reported **613 passed, 3 skipped**. The final installed
`arcen` command separately initialized and inspected a temporary store without
booting the server or plugins. Rollback and runtime selection still fail closed;
this is not a completed adoption/rollback implementation. No live-Docker
claim is made for H-07.

## H-08 offline editor foundation (partial)

`H-08-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the final
installed H-08 wheel, its managed server and a local mock provider completing a
normal direct-answer turn. Docker was unavailable and tools were blocked.
`H-08-real-editor-tests.png` captures the focused proposal-validation suite:
**9 passed**. The full local suite reported **622 passed, 3 skipped**, and an
installed-wheel patch-validation check passed separately. Callbacks in tests
are mocked; the editor is not connected to a real provider, probe, campaign,
or adoption. No live-Docker or autonomous-improvement claim is made.

## H-09 probe preflight (incomplete; execution blocked)

`H-09-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
H-09 wheel with the managed server and local mock provider completing a normal
direct-answer turn. Docker was unavailable and tools were blocked. It does not
show a probe. `H-09-real-preflight-tests.png` captures the focused preflight
suite: **6 passed**. The full local suite reported **628 passed, 3 skipped**;
the wheel contained and loaded the preflight module. Candidate probe execution,
worktree quarantine, forced redaction and live Docker isolation remain
unimplemented; `run_probe` refuses rather than running on the host.

## H-10 offline judge foundation (partial)

`H-10-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
H-10 wheel, its managed server and a local mock provider completing a normal
answer. Docker was unavailable and tools were blocked; it does not show a
probe or judge. `H-10-real-judge-tests.png` records the focused mocked judge
suite: **15 passed**. The full local suite reported **643 passed, 3 skipped**;
an installed-wheel mock-judge check passed separately. The judge has no live
probe inputs or provider/campaign integration; redaction and blinding are
best effort and no adoption is enabled.

## H-15 static policy-review foundation (partial)

`H-15-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
H-15 wheel, managed server and local mock provider completing a normal direct
answer. Docker was unavailable and tools were blocked. `H-15-real-policy-tests.png`
captures the focused static-review tests: **5 passed**. The full local suite
reported **648 passed, 3 skipped**, and the installed wheel refused the
adoption call separately. This is not an operational policy/adoption engine;
human approval, canaries, rollback and runtime enforcement remain unimplemented.

## H-09 Git workspace and Docker gateway foundations (partial)

`H-09b-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the
installed wheel, its managed server and a local mock provider answering a
normal direct question. Docker was unavailable and tools were blocked; this
is **not** a probe run. `H-09b-real-workspace-tests.png` is a fresh terminal
capture of the focused tests: **27 passed, 1 skipped**. The skipped opt-in test
requires real Docker and the sandbox image. The full development suite reported
**669 passed, 4 skipped**. The built wheel contained 105 entries and its new
modules imported from outside the source tree.

The workspace and gateway tests use real local Git archives but mock Docker.
They establish bounded input processing, no working-tree writeback, teardown,
fail-closed construction and best-effort tool-result redaction. They do not
establish that committed content is secret-free or prove real-Docker behavior.
`run_probe` is still deliberately blocked; model execution, mandatory
end-to-end redaction and the rest of the Harness² campaign remain incomplete.

**User-reported real-Docker verification (Omarchy):** on commit `6127883`,
`ARCEN_TEST_DOCKER_ISOLATION=1 uv run --extra dev --extra sandbox python -m pytest tests/test_turn_isolation.py tests/test_headless.py tests/test_workspace_snapshot.py tests/test_probe_workspace.py tests/test_probe_container.py -v`
reported **60 passed in 40.75s**, with no skips. This includes the live Docker
isolation, headless workspace, and probe-container smoke tests. It does not
verify a model-driven probe or a complete campaign; those remain unavailable.

## H-12 offline composer foundation (partial)

`H-12-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
wheel, its managed server and a local mock provider completing a normal direct
answer. Docker was unavailable and tools were blocked; it does not show a
campaign or composition. `H-12-real-composer-tests.png` captures the focused
composer/editor/policy suite: **21 passed**. The full local suite reported
**676 passed, 4 skipped**. The 106-entry wheel included the composer module,
which imported from outside the source tree.

Composition is syntactic and offline: conflicts are reported, unconflicted
changes make an unapproved immutable candidate, and no ref moves. A campaign,
behavioral selection, conflict resolution, runtime selection and adoption are
not implemented; this is not the completed H-12 ticket.

## H-01 packaged baseline selection (partial)

`H-01b-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
wheel, managed server and local mock provider answering a normal direct
question. It does not show a selected harness or probe; Docker was unavailable
and tools were blocked. `H-01b-real-selection-tests.png` captures the focused
selection/headless tests: **13 passed, 1 skipped** (real Docker). The full local
suite reported **681 passed, 4 skipped**; all 12 baseline provider-payload
fixtures remain unchanged. The 107-entry wheel was installed and its real
`arcen harness init` / `arcen run hello --json --harness adopted` commands were
verified outside the source tree.

Headless selection accepts only the verified packaged adopted baseline and
emits its immutable manifest ID in `run.start`. The package is the source of
prompts; the local store is an integrity check, not authenticated provenance.
Candidate refs, probes, approval, adoption and rollback remain unavailable.
No claim of full H-01 or a running campaign is made.

## H-09 candidate model binding (partial)

`H-09c-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
wheel, its managed server and a local mock provider answering a normal question;
it does not depict a candidate probe. Docker was unavailable and tools were
blocked. `H-09c-real-model-tests.png` captures the focused candidate-model and
preflight tests: **17 passed**, using mocked provider responses. The full suite
reported **692 passed, 4 skipped**. The 108-entry wheel included the module.

Separately, the installed candidate-bound model and DRAFT planner made two real
HTTP calls to the local mock provider and completed a direct answer; no tools
ran and no external provider was contacted. Provider pinning is by configured
name, filtering is best effort, and the per-client call cap is not a campaign
budget. `run_probe` still refuses: model binding does not connect the Docker
gateway, event redaction, approval or adoption.

## H-09 reviewed trial integration (experimental; partial)

`H-09d-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
wheel, its managed server and a local mock provider answering a normal question;
it does not depict a candidate trial. Docker was unavailable and tools were
blocked. `H-09d-real-trial-tests.png` captures the reviewed-trial, gateway and
model tests: **24 passed, 2 skipped**, using mocked Docker and provider calls;
the skipped tests require real Docker. The full local suite reported **703
passed, 5 skipped**. The 109-entry installed wheel included the trial module.

Separately, the installed trial used real HTTP to a local mock provider and a
mocked Docker boundary: two model calls, two fake dispatches, and cleanup
passed. This does not establish real-Docker trial behavior. The experimental
Python-only API requires an explicit input-review attestation, never moves refs
or adopts a candidate, and returns only after strict cleanup. Redaction remains
best effort and cannot establish that reviewed inputs or outputs are secret-free.
The standard campaign `run_probe` remains blocked; no campaign is running.

## H-10 paired reviewed comparison (experimental; partial)

`H-10b-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
wheel, its managed server and a local mock provider answering a normal question.
It does not depict the experimental comparison; Docker was unavailable and tools
were blocked. `H-10b-real-comparison-tests.png` captures the focused paired,
proposal and trial tests: **17 passed, 2 skipped**. The full development suite
reported **711 passed, 6 skipped**; the 111-entry wheel included both comparison
modules. The installed paired path was separately exercised using real HTTP to a
local mock provider, a mocked Docker boundary and a callback judge.

The pair captures one Git archive and uses separate trial containers, with the
same pinned provider settings. The real-Docker pair test was skipped locally;
the user later reported it passing on Omarchy, as recorded below. Review flags are caller attestations; redaction and
blinding are best effort. There is no automatic adoption, full campaign, USD
budget, canary, authenticated approval gate or rollback. No improvement claim is made.


## H-11 local human review record (experimental; partial)

`H-11a-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
wheel, its managed server and a local mock provider answering a direct question.
It does not depict review or a campaign; Docker was unavailable and tools were
blocked. `H-11a-real-review-cli.png` shows the installed wheel's actual review
show command against a locally created static candidate and its sanitized diff.
`H-11a-real-review-tests.png` captures the focused review, CLI and comparison
tests: **35 passed, 1 skipped**; comparison dependencies use mocked Docker and
provider calls. The full suite reported **734 passed, 6 skipped**; the installed
wheel had **112 entries**. The real-Docker reviewed trial and paired-comparison
tests were skipped locally; the user later reported them passing as noted below.

The ledger is unsigned, local review metadata only, not an authenticated human
approval gate. Static reviews cannot be approved; paired records require
successful caller-supplied comparison data. The interactive CLI shows a
sanitized diff and requires explicit confirmation, while Python flags are caller
attestations. No record adopts or selects a candidate or authorizes execution.
See `docs/HARNESS-REVIEW.md` for limitations and required future checks.


### User-reported real-Docker verification on Omarchy

On commit `f34ea27`, the user ran:

```sh
ARCEN_TEST_DOCKER_ISOLATION=1 uv run --extra dev --extra sandbox \
  python -m pytest tests/test_probe_execution.py tests/test_harness_comparison.py \
  -k real_docker -v
```

The supplied terminal output reported **2 passed, 14 deselected in 16.09s**,
with no skips. This covers the reviewed trial and paired comparison against real
Docker. Their model responses and judge are mocked; the result does not verify
an external model provider, unattended campaign, adoption or authentication.
This is user-reported terminal output, not a captured screenshot.

## H-17 shared admission accounting (experimental; partial)

`H-17a-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
wheel, managed server and local mock provider answering a normal question. It is
not a budget display or campaign; Docker was unavailable and tools were blocked.
`H-17a-real-budget-tests.png` captures the new budget tests: **19 passed,
1 skipped** (the new real-Docker budgeted-pair test). The full suite reported
**753 passed, 7 skipped**. The built and installed wheel contained 113 entries.

`H-17a-real-installed-smoke.png` captures an installed-wheel paired comparison
using a real local HTTP mock provider, a mocked Docker boundary and a callback
judge: two trial admissions, four model calls and one judge invocation were
counted; an extra trial was refused. It is not a real-Docker budget test. The
user previously reported the unbudgeted trial and pair passing with real Docker
at `f34ea27`; the new budgeted path has not been tested with real Docker.

This is opt-in in-process admission accounting, not token/USD spending control,
a durable campaign budget or a hard deadline. It cannot stop in-flight work or
control a trusted judge callback's internal requests. It does not enable a
campaign, candidate adoption or autonomy; see `docs/HARNESS-BUDGET.md`.

## H-13 manual experience foundation (experimental; partial)

`H-13a-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
wheel and managed server answering through a local mock provider; it does not
show the experience library. Docker was unavailable and tools were blocked.
`H-13a-real-experience-tests.png` shows the focused experience, memory and review
tests: **59 passed**. The full suite reported **777 passed, 7 skipped**. The
installed wheel contained 114 entries. `H-13a-real-installed-smoke.png` shows
an installed-wheel persistence and rendering exercise using deliberately
fabricated paired evidence and a local review record, not a real human review.

The offline library stores bounded manual notes in the existing memory graph,
links them to an approved local paired-review record, exposes a human-facing
render, uses temporal conflict history and decay scores, and hides notes after
30 days. The review/lesson attestations are unsigned and secret detection is
incomplete. No model automatically generates or consumes these lessons; there
is no campaign, authenticated approval, ref movement or adoption. See
`docs/HARNESS-EXPERIENCE.md` for limits.
