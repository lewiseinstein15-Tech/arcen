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

## H-11 manual sequential comparisons (experimental; partial)

`H-11b-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
wheel with its managed server and local mock provider. It is a normal direct
answer, not a campaign display; Docker was unavailable and tools were blocked.
`H-11b-real-campaign-tests.png` shows the focused campaign, budget, comparison
and review tests: **58 passed, 3 skipped**. The full suite reported **788
passed, 8 skipped**. The installed wheel had 115 entries.

`H-11b-real-installed-smoke.png` shows an installed-wheel run with a real local
HTTP mock provider, mocked Docker and a callback judge: one shared snapshot,
three trials, six model calls, two judge invocations, and two pending review
records. No candidate was selected or adopted. This is not real-Docker campaign
verification. The opt-in real-Docker manual campaign test was skipped locally;
the user later reported it passing on Omarchy at `4ecaf6e` as recorded below.
Earlier unbudgeted trial and paired tests passed there at `f34ea27`.

This Python-only path requires explicit review attestations and a shared
in-process admission budget; it is not an authenticated gate, a USD/token cap,
a hard timeout, or a resumable campaign runner. Stop does not cancel in-flight
work; callback blinding and redaction are best effort. No automatic selection,
adoption, canaries, campaign CLI, recursion or safe resume is enabled. See
`docs/HARNESS-MANUAL-CAMPAIGN.md`.

## H-11 journaled manual campaign (experimental; partial)

`H-11c-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
wheel, managed server and local mock provider answering a direct question; it
does not show a campaign. Docker was unavailable and tools were blocked.
`H-11c-real-journal-cli.png` shows the actual installed CLI inspecting a local
metadata-only plan; no trial was run. `H-11c-real-journal-tests.png` captures
the focused journal, manual campaign, CLI, review and budget tests: **72 passed,
3 skipped**. The full suite reported **800 passed, 9 skipped**. The built and
installed wheel contained 116 entries. The new journaled real-Docker campaign
test was skipped locally; the user later reported it passing on Omarchy at
`4ecaf6e` as recorded below.

The optional journal records phases and review IDs and prevents a plan from
being claimed twice. Stop is a stage-boundary request, not cancellation of
in-flight work. Crashed runs remain ambiguous and cannot automatically resume;
review and journal databases are not jointly transactional. There is no
campaign-start CLI, durable budget, authenticated approval or adoption. See
`docs/HARNESS-CAMPAIGN-JOURNAL.md` for limitations.

## H-17 durable shared admission accounting (experimental; partial)

`H-17b-real-live-tui.png` is a fresh PTY/xterm/Chromium capture of the installed
wheel and managed server answering through a local mock provider. It is not a
budget display; Docker was unavailable and tools were blocked.
`H-17b-real-durable-cli.png` shows the installed CLI inspecting a local demo
budget; its one trial and one model reservation were manual accounting calls,
not real executions. `H-17b-real-durable-tests.png` captures focused durable,
in-memory and journal tests: **47 passed, 3 skipped**. The full suite reported
**816 passed, 10 skipped**. The installed wheel contained 117 entries. The new
opt-in real-Docker durable-budget test was skipped locally; the user later
reported it passing on Omarchy at `4ecaf6e` as recorded below.

SQLite-backed counters and stop state can be shared by cooperating processes
using the same ID, and clock rollback closes admission. This is still not a
USD/token cap, hard runtime limit, in-flight kill, automatic resume or
campaign-wide enforcement against other IDs or nonparticipating callers. The
At this historical verification point, the journal did not bind the budget ID.
See `docs/HARNESS-DURABLE-BUDGET.md` for current behavior.


### User-reported real-Docker campaign and budget verification on Omarchy

On commit `4ecaf6e`, the user ran:

```sh
ARCEN_TEST_DOCKER_ISOLATION=1 uv run --extra dev --extra sandbox \
  python -m pytest tests/test_manual_campaign.py tests/test_campaign_journal.py \
  tests/test_durable_budget.py tests/test_harness_budget.py -k real_docker -v
```

The supplied terminal output reported **4 passed, 58 deselected in 43.87s**,
with no skips. This covers the manual campaign, journaled campaign, durable
admission budget and in-process budgeted pair against real Docker. These tests
use mocked model responses and a callback judge. They do not verify an external
model provider, authenticated approval, automatic resume, token/USD budgets or
adoption. This is user-reported terminal output, not a captured screenshot.

### H-11d — interactive manual campaign CLI (partial)

- `H-11d-real-manual-prompt.png`: fresh installed-wheel `arcen harness campaign
  run` in a real PTY, rendered by xterm.js/Chromium. A locally authored test
  patch, sample task, disposable Git repository and fake provider configuration
  were used. The screenshot is **before confirmation**; no trial, provider
  request, judge or Docker operation occurred. The terminal was closed at the
  prompt.
- `H-11d-real-manual-tests.png`: fresh PTY run against the installed wheel:
  12 passed, 1 skipped. The passed workflow tests mock the provider and Docker;
  the new opt-in CLI real-Docker test was skipped in the assistant sandbox.
- Full suite (source): 828 passed, 11 skipped. Wheel contents check: 118
  entries. Documentation links, scoped Ruff and diff checks passed.
- The new CLI is experimental and only covers explicitly confirmed, manually
  judged, sequential comparisons. This is not completion of H-11 or the wider
  Harness² roadmap. Adoption, selection, rollback, safe resume and autonomy
  remain disabled. Budget admissions are not USD/token/runtime caps. Earlier
  user-run Docker results tested the underlying APIs, not this new CLI.

### H-11e — durable-budget plan binding and visibility (partial)

- `H-11e-real-budget-bound-prompt.png`: fresh installed-wheel `arcen harness
  campaign run` in a real PTY, rendered by xterm.js/Chromium. The local example
  plan was bound to a durable budget, and the prompt displayed its usage,
  limits and approximate admission cutoff. It was captured before confirmation;
  no provider, judge or Docker activity occurred.
- `H-11e-real-budget-bound-tests.png`: fresh PTY test run against the installed
  wheel: 51 passed, 3 skipped. Tests cover version-1 migration, legacy records,
  mixed-version claim blocking, competing claims, wrong budgets, display and
  malformed records. Passing execution tests mock provider and Docker; the
  opt-in real-Docker tests were skipped in the assistant environment.
- Full source suite: 839 passed, 11 skipped. Wheel: 118 entries; scoped Ruff,
  formatting, documentation links and diff checks passed.
- The binding is unsigned local metadata, not authenticated authorization or a
  transaction across databases. Legacy Python plans can remain unbound; CLI
  refuses them. This is not a monetary/token cap, hard runtime cancellation,
  resume, adoption or completion of the broader roadmap.

### H-08b — confirmed model-backed manual editor (partial)

- `H-08b-real-editor-prompt.png`: installed `arcen harness editor propose` in
  a fresh real PTY rendered by xterm.js/Chromium. The fake provider endpoint was
  not contacted: the screenshot was taken before the exact confirmation and the
  terminal was closed at the prompt. No candidate was generated or adopted.
- `H-08b-real-editor-tests.png`: fresh PTY run against the installed wheel:
  9 passed. Tests include two actual loopback HTTP calls to a local mock provider;
  the other provider responses are mocked in-process. Docker is not used by the
  editor. No paid/external provider was contacted or verified.
- Full source suite: 849 passed, 11 skipped. Wheel check: 118 entries. Scoped
  lint, formatting, docs-link and diff checks passed.
- The command sends the task and five editable components to the chosen pinned
  provider only after explicit confirmation. Admission counts are not USD/token
  caps. Candidates are independent, untrusted, unapproved and unadopted; this is
  neither a model panel, automatic campaign, autonomous selection nor completion
  of H-08/Harness². Candidate selection and adoption remain disabled.

### H-16a — manual fixed behavioral canaries (partial)

- `H-16a-real-canary-prompt.png`: installed `arcen harness canary run` in a
  fresh real PTY, rendered by xterm.js/Chromium. A local sample patch, Git
  repository, durable budget and fake provider config were displayed. The
  screenshot was taken before confirmation; no trial, provider request or
  container was started.
- `H-16a-real-canary-tests.png`: fresh PTY test run against the installed wheel:
  16 passed, 1 skipped. Verifier logic was exercised against temporary files;
  trial orchestration used mocked Docker and provider responses. The new
  opt-in real-Docker test was skipped because Docker is unavailable here.
- Full source suite: 865 passed, 12 skipped. Wheel check: 119 entries. Scoped
  Ruff, formatting, documentation links and diff checks passed.
- These are two public, simple artifact tasks, not adversarial safety tests.
  Results are ephemeral and unsigned; a pass is not an adoption gate, policy
  proof, authenticated approval, or authorization. No auto-rollback or
  autonomy was implemented. See `docs/HARNESS-CANARIES.md`.

### H-19a — manual-command configuration hygiene (partial)

- `H-19a-real-config-refusal.png`: fresh installed `arcen harness editor
  propose` in a real PTY with a deliberately duplicate-key local YAML config.
  The actual command refused it with exit status 1 before confirmation; the
  wrapper displayed the exit code and held the terminal open for capture. No
  provider call or Docker operation occurred.
- `H-19a-real-config-tests.png`: fresh PTY run against the installed wheel:
  11 passed. Tests cover duplicates, merge keys, aliases, anchors, explicit
  tags, invalid mappings, bounded inputs, final-component symlinks, safe error
  messages and environment-reference behavior.
- Full source suite: 876 passed, 12 skipped. Wheel: 119 entries; scoped lint,
  formatting, documentation links and diff checks passed.
- This stricter parser applies only to interactive manual harness commands, not
  ordinary ARCEN config loading. It is not prompt-injection detection,
  comprehensive secret scanning, a provider egress allowlist, or completion of
  probe hygiene hardening. Parent directories and the local filesystem remain
  trusted.

### H-19b — Docker startup and server cleanup uncertainty (partial)

- `H-19b-real-startup-refusal.png`: installed sandbox code executed in a fresh
  PTY rendered by xterm.js/Chromium, with a **mock Docker SDK** simulating an
  unacknowledged container creation. The generated container name is reported;
  no real Docker container or model call was involved.
- `H-19b-real-server-cleanup.png`: installed server code executed in a fresh
  PTY with a **mock provider and mock Docker registry**. A cleanup failure
  produced the actual `SANDBOX_CLEANUP_UNCONFIRMED` terminal event and no
  success terminal. This is not a real-Docker demonstration.
- `H-19b-real-startup-tests.png`: fresh installed-wheel PTY run: 135 passed,
  4 skipped. Includes mocked creation/cleanup/interrupt and server event-order
  tests; real-Docker tests were skipped here.
- Full source suite: 887 passed, 12 skipped. Wheel check: 119 entries. Scoped
  sandbox/test Ruff and formatting passed. The existing server module has seven
  pre-existing Ruff findings; the count and rule breakdown were unchanged by
  this edit. Documentation link and diff checks passed.
- Strict cleanup can detect uncertainty, not guarantee daemon cleanup after
  connectivity loss, process termination or host crash. Inspect potentially
  orphaned containers without disrupting live runs. Normal server results now
  wait for cleanup; previously streamed output cannot be retracted. No
  automatic recovery, safe resume or adoption gate was added.

### H-14a — local reusable task bank (partial)

- `H-14a-real-task-bank.png`: fresh installed `arcen harness` commands in a
  real PTY, rendered by xterm.js/Chromium. The local example initializes a
  temporary store, imports and shows a task, lists it and runs doctor. No
  provider, Docker container, campaign or adoption was invoked.
- `H-14a-real-task-tests.png`: fresh installed-wheel PTY suite: 94 passed,
  3 skipped. It covers task-bank and manual editor/campaign integration;
  provider and Docker execution in these tests is mocked. The opt-in real
  Docker tests were skipped in this environment.
- Full source suite: 909 passed, 12 skipped. Wheel: 120 entries. Scoped Ruff,
  formatting, documentation link and diff checks passed.
- Tasks and hashes are retained in plaintext; secret detection is incomplete,
  hashes do not authenticate origin and a crash can orphan plaintext objects.
  This is local manual storage, not recursive scheduling, prompt-injection
  protection or an adoption gate. See `docs/HARNESS-TASK-BANK.md`.

### H-11f — guided manual editor-to-review flow (partial)

- `H-11f-real-guided-editor-prompt.png`: fresh installed `arcen harness
  workflow run` in a real PTY, rendered by xterm.js/Chromium. The sample uses a
  local Git repository and a loopback mock provider. Capture occurred before
  the EDIT confirmation: no provider request or Docker trial occurred.
- `H-11f-real-guided-select.png`: a separate fresh installed-command PTY run.
  The editor confirmation was sent through the terminal; the installed command
  made two real HTTP requests to a local mock provider, generated two unadopted
  diffs, and waited for a manual selection. No candidate was selected, no
  campaign was started, and no Docker or external provider was used.
- `H-11f-real-guided-tests.png`: fresh installed-wheel PTY run: 105 passed,
  4 skipped. The guided end-to-end test mocks Docker and provider calls; other
  editor tests exercise a local HTTP mock. Real Docker paths were skipped here.
- Full source suite: 920 passed, 12 skipped. Wheel: 120 entries. Scoped Ruff,
  formatting, docs-link and diff checks passed.
- This flow supports one human-selected candidate, separate confirmations and
  pending reviews. No automatic selection, authenticated approval, adoption,
  resume or recursive learning is provided. The preliminary Git snapshot is
  not transactionally bound to the later trial. Budget counts are not monetary
  caps or reservations. See `docs/HARNESS-GUIDED-WORKFLOW.md`.

### H-12b — human-selected composition in guided comparison (partial)

- `H-12b-real-composite-review.png`: fresh installed `arcen harness workflow
  run` in a real PTY rendered by xterm.js/Chromium. Two editor responses came
  over real loopback HTTP from a local mock provider; terminal input selected
  both independent edits for composition. The command displayed the actual
  combined diff and stopped at the separate `USE` confirmation. No plan,
  Docker trial or external provider was used in this capture.
- `H-12b-real-composition-conflict.png`: a separate fresh installed-command
  PTY run with local mock editor responses proposing competing insertions. The
  actual command reported the conflict, created no composite or plan, and
  exited with status 1. The wrapper held the terminal open for capture.
- `H-12b-real-composition-tests.png`: installed-wheel PTY run: 62 passed,
  1 skipped. The guided end-to-end comparison uses mocked Docker and provider;
  other editor tests exercise local HTTP mock responses. Real Docker was not
  available in this environment.
- Full source suite: 930 passed, 12 skipped. Wheel: 120 entries. Scoped Ruff,
  formatting, documentation links and diff checks passed.
- This is a syntactic, operator-chosen merge of **uncompared** proposals, not
  evidence-based or recursive composition. A no-conflict merge is not proof of
  compatibility or safety. Composite objects can remain after cancellation.
  No approval, adoption, rollback or autonomous execution was enabled.

### H-12c — operator composition from recorded comparisons (partial)

- `H-12c-real-recorded-prompt.png`: fresh installed `arcen harness campaign
  compose` in a real PTY rendered by xterm.js/Chromium. The displayed source
  campaign was prepared using **mock Docker and a mock provider/judge**; the
  command displays its unsigned local summaries and stops for confirmation.
- `H-12c-real-recorded-result.png`: separate fresh installed-command PTY run on
  those mocked source records. Terminal input confirmed composition; the real
  command displayed an unadopted composite and its diff, with no provider call,
  Docker trial, new plan or approval during composition.
- `H-12c-real-recorded-tests.png`: installed-wheel PTY suite: 106 passed,
  3 skipped. Tests exercise linked-record validation, corruption, rechecking
  after confirmation, conflicts, human cancellation and a separate composite
  comparison; provider and Docker are mocked for those comparisons. Opt-in real
  Docker tests were skipped here.
- Full source suite: 941 passed, 12 skipped. Wheel: 121 entries. Scoped Ruff,
  formatting, documentation links and diff checks passed.
- The source journal and reviews are unsigned and can be fabricated; their
  association with the task is local metadata, not proof that trials occurred.
  Full trajectories and durable composite provenance are not retained. This is
  an operator-selected syntactic merge, not authenticated evidence, automatic
  behavioral selection, a safety gate or autonomous recursion. See
  `docs/HARNESS-RECORDED-COMPOSITION.md`.

### H-13b — operator-authored experience CLI (partial)

- `H-13b-real-note-prompt.png`: fresh installed `arcen harness experience
  record` in a real PTY rendered by xterm.js/Chromium. The example review is
  **fabricated local test metadata**, not a real provider or Docker comparison.
  The screenshot stops before the exact SAVE confirmation; no note was saved.
- `H-13b-real-note-saved.png`: separate fresh installed-command PTY run with
  the same type of fabricated local review. Terminal input confirmed one manual
  note; the actual commands then listed and showed it. No model, Docker trial,
  automatic prompting, ref change or adoption occurred.
- `H-13b-real-note-tests.png`: installed-wheel PTY suite: 95 passed, 1 skipped.
  Tests cover terminal confirmation, invalid notes, plaintext retention,
  supersession, expiry, review rechecks, schema/symlink failures and a
  separate-process CLI lock. Paired evidence in these tests is mocked or
  fabricated; real Docker was not used for this new note workflow.
- Full source suite: 953 passed, 12 skipped. Wheel: 122 entries. Scoped Ruff,
  formatting, docs-link and diff checks passed.
- Notes remain untrusted plaintext; secret detection is incomplete, expiry
  hides but does not delete, and superseded data remains in history. The lock
  coordinates only cooperating CLI processes, and the review/memory databases
  are not one atomic transaction. Notes are not used by any model or adoption
  gate. This is not autonomous reflection; see `docs/HARNESS-EXPERIENCE.md`.

### H-11g — guided multi-candidate selection (partial)

- `H-11g-real-multi-run-prompt.png`: fresh installed `arcen harness workflow
  run` in a real PTY rendered by xterm.js/Chromium. The editor made two actual
  loopback HTTP requests to a local mock provider; terminal input selected two
  generated candidates. The screenshot shows both diffs and stops at the
  separate RUN confirmation. No Docker trial or external provider was used.
- `H-11g-real-multi-tests.png`: fresh installed-wheel PTY suite: 89 passed,
  3 skipped. Tests exercise human-selected two-candidate judging with a shared
  baseline, one-to-five selection, admission lower bounds and cancellation.
  Provider and Docker are mocked for the execution tests; opt-in real-Docker
  cases were skipped.
- Full source suite: 963 passed, 12 skipped. Wheel: 122 entries. Scoped Ruff,
  formatting, documentation links and diff checks passed.
- This completes only the manual multi-candidate sub-scope, not H-11, H-14 or
  H-17. Admissions are snapshots rather than reservations or USD/token caps;
  no winner is automatically adopted, no auto-resume or autonomy was enabled.
  The maintained ticket checklist is `docs/HARNESS-CHECKLIST.md`.

### H-04a — disabled harnessing configuration boundary (partial)

- `H-04a-real-config-refusal.png`: fresh installed `arcen run` in a real PTY,
  rendered by xterm.js/Chromium. A local config with an unsupported `autonomy`
  option is rejected before a run, with exit 1 and no events. No Docker or
  external provider was used.
- `H-04a-real-config-tests.png`: separate fresh installed-wheel PTY run of the
  focused configuration-boundary tests, **20 passed**. The ASGI API tests use
  an in-process test client; they are not a real network or Docker test.
- Complete source suite: **983 passed, 12 skipped**. Installed-wheel focused
  configuration, manifest, baseline prompt and headless regression suite:
  **118 passed, 1 skipped**. Wheel contents check: **122 entries**.
- This is schema hardening only. Normal YAML parsing still permits duplicate
  keys and trusted Python code can bypass validation. The full H-04 package,
  signatures and trust integration remain incomplete.

### H-04b — detached manifest-claim signatures (partial)

- `H-04b-real-attestation.png`: fresh installed `arcen harness attestation
  verify` commands in a real PTY rendered by xterm.js/Chromium. A freshly
  generated **demonstration** key verifies the intact manifest claim and the
  altered parent claim fails signature verification. The demo key is not a
  production trust anchor; neither Docker nor a provider was used.
- `H-04b-real-attestation-tests.png`: fresh installed-wheel PTY run of the
  focused attestation suite, **15 passed**.
- Source suite: **998 passed, 12 skipped**. Installed-wheel focused attestation,
  config, manifest, store, baseline prompt and headless tests: **100 passed,
  1 skipped**. The legacy CLI test helpers explicitly use source for some
  subprocesses; the attestation CLI subprocess uses the installed package.
  Wheel contents check: **123 entries**.
- Detached signatures are not enforced by boot or adoption. The public key is
  supplied explicitly; parent claims, signer identity, revocation and safety
  are not independently verified. Full H-04 remains incomplete.

### H-04c — verified packaged default snapshot (partial)

- `H-04c-real-packaged-refusal.png`: a fresh installed `arcen run --json`
  command in a real PTY rendered by xterm.js/Chromium, using a deliberately
  altered **copy** of the installed package via `PYTHONPATH`. The original
  installation was not modified. It returns a JSON error and exit 1 before a
  run; no Docker or provider was used.
- `H-04c-real-snapshot-tests.png`: fresh installed-wheel PTY run of the seven
  snapshot tests, **7 passed**. The tests copy the package actually imported,
  including the installed wheel, for their tamper and concurrency scenarios.
- Full source suite: **1005 passed, 12 skipped**. Installed-wheel regression
  selection: **142 passed, 1 skipped**. Some legacy tests explicitly copy or
  subprocess the source tree; the snapshot tests exercise a wheel copy.
  The pre-externalization golden prompt payload comparison passed. Wheel
  contents check: **123 entries**.
- The seven files are hash-bound to an unsigned manifest, not authenticated.
  Python code, tool implementations, configuration and plugins are outside this
  snapshot. Disk edits after capture are not monitored until a fresh process.
  Full H-04 remains incomplete.

### Harness² pre-merge regression verification

- `MERGE-HARNESS2-real-full-tests.png`: fresh source-suite run in a real PTY,
  rendered with xterm.js/Chromium after the portable temporary-directory test
  fix: **1006 passed, 12 skipped**. No real Docker daemon was available.
- The prior full installed-wheel run passed **1005 tests, 12 skipped** before
  the test-only portability fix; the installed-wheel sandbox/server subset was
  rerun afterward: **61 passed**. Some older subprocess helpers explicitly
  exercise the source tree. Wheel and documentation checks passed.
- The repository-wide Ruff run still reports pre-existing findings on `main`;
  this change fixes the import-order issue introduced by the branch and leaves
  the unrelated script permission changes unstaged.

### Sandbox-image workflow credential fix

The GitHub Actions run for `6002af2` failed at checkout with a Git
credential-prompt error. The workflow had preferred a repository PAT over the
scoped job token. It now uses the default checkout token without persisting it
and the job token for GHCR, retaining `contents: read` and `packages: write`.
A missing repository/package association or restrictive GitHub settings can
still prevent the image push; the actual Actions result must be checked.

`SANDBOX-WORKFLOW-real-tests.png` is a fresh PTY/xterm.js/Chromium run:
**29 passed**, covering static workflow configuration and sandbox tests. These
are local tests, not proof that GitHub checkout or GHCR publishing succeeded.

### H-04d — portable signed v1 package (partial)

- `H-04d-real-package-export.png`: fresh installed `arcen harness package
  export` and offline `package verify` commands in a real PTY rendered by
  xterm.js/Chromium. The signing key was freshly generated for this demo;
  it is not a trusted production key. No Docker or model provider was used.
- `H-04d-real-package-tests.png`: fresh installed-wheel PTY test run,
  **9 passed**. Tests cover tampering, duplicate/invalid data, limits,
  explicit-key verification, no overwrite, and competing exports.
- Before recovery the complete source suite passed **1017 tests, 12 skipped**,
  and the installed-wheel selected regression run passed **89, 1 skipped**.
  The recovered code comes from that installed wheel and the package tests
  passed again. Wheel contents check: **124 entries**. Some older helpers
  explicitly exercise source-tree copies.
- This plaintext package covers only the existing seven-component v1 manifest.
  It does not authenticate the key, import or run the package, validate
  lineage, or permit adoption. Full H-04 remains incomplete.

### H-04e — confirmed object import (partial)

- `H-04e-real-import-prompt.png`: fresh installed `arcen harness package import`
  in an actual PTY, displaying verification and the confirmation gate.
- `H-04e-real-import-confirmed.png`: fresh installed-command PTY run with a
  scripted test keystroke; the test-key package was imported successfully and
  no ref was created. This is test evidence, not a real operator's approval.
- `H-04e-real-installed-tests.png`: fresh installed-wheel PTY run of the seven
  import tests, **7 passed**. The focused installed-wheel package/store suite
  passed **37 tests**; the full source suite passed **1024**, with **12 skipped**.
  Docker was unavailable here, and signature verification is not key trust.

### H-04f — read-only manifest inspection (partial)

- `H-04f-real-inspect.png`: fresh installed-command PTY run inspecting a
  test-key-imported, unregistered manifest and showing its opt-in diff.
- `H-04f-real-installed-tests.png`: fresh installed-wheel PTY test run,
  **8 passed**. The focused installed-wheel suite passed **52 tests**; the
  full source suite passed **1032**, with **12 skipped**. Inspection verifies
  hashes, not signer trust or safety; no Docker validation was performed.

### H-11h / H-21a — manual progress and validation workflow (partial)

- `H-11-progress-real-tests.png`: fresh installed-wheel tests in a real PTY,
  **6 passed**. Provider and Docker are mocked; progress is best effort, not
  authenticated evidence, safe resume, or a session NDJSON stream.
- `H-21-workflow-real-tests.png`: fresh real-PTY local workflow structure
  checks, **2 passed**. These tests do not execute GitHub Actions or Docker.
- Final full source suite: **1040 passed, 12 skipped**. The selected installed
  wheel suite: **106 passed, 3 skipped**. The new workflow has not been pushed
  or run on GitHub; Docker and external-provider validation remain open.

### H-19a — known credentials in reviewed probe snapshots (partial)

- `H-19a-real-secret-preflight-tests.png`: fresh installed-wheel tests in an
  actual PTY, **8 passed**. The tests cover exact configured key and explicitly
  supplied-value rejection before container/provider use, including the lower
  gateway; Docker and provider calls are mocked. Encoded/split/unknown secrets
  remain outside this check.
- Full source suite: **1048 passed, 12 skipped**. Selected installed-wheel
  suite: **73 passed, 6 skipped**. Real Docker was unavailable for this run.

### H-19c–d — narrow task screen and known-value handling (partial)

- `H-19c-real-screen-cli.png`: fresh installed `arcen harness workflow run`
  in a real PTY rejects a locally fabricated malicious task before the workflow
  preview or trial admission. The subsequent real budget status shows zero
  admitted trials and model calls. The task screen is heuristic, has false
  positives, and is easily evaded.
- `H-19d-real-known-values-tests.png`: fresh real-terminal installed-wheel run,
  17 tests passed for exact known-value input checks and redaction, including
  overlapping values. The provider and Docker boundary were mocked.
- Full source suite: 1,105 passed, 12 skipped. Selected installed-wheel tests:
  76 passed, 3 skipped. An earlier concurrent full run had one PTY timeout
  while Chromium/another test suite ran; the isolated full-suite retry passed.
  Real-Docker and external-provider behavior for these changes remains untested.
  These partial checks do not complete H-19 or permit autonomous adoption.

### H-07a / H-19e — auxiliary database checks and stricter Docker inspection

- `H-07a-real-doctor-cli.png` shows a fresh installed `arcen harness doctor`
  command in a real PTY: an initialized disposable store passes, then a locally
  injected malformed budget database is rejected. The checks cover SQLite
  quick-check and expected schema, not every record, provenance or authority.
- `H-19e-real-inspection-tests.png` shows 28 fresh installed-wheel test cases
  rejecting disabled, contradictory or missing/malformed isolation metadata and
  accepting the tested enabled encodings. Docker is mocked; these checks have
  **not** been validated against a real Docker daemon or all Docker versions.
- Full source suite: 1,150 passed, 12 skipped. Selected installed-wheel suite:
  143 passed, 3 skipped. Ruff for changed Python files and wheel/docs checks
  passed. Real Docker and external-provider tests remain outstanding; H-07 and
  H-19 are still open and adoption/rollback remain disabled.

### H-20a / H-21b / H-22a — simulated Harness² surface and wheel CI checks

- `H-20a-real-harness-demo.png`: fresh installed `arcen-tui --demo --harness`
  in a real PTY rendered by xterm.js/Chromium. All data is explicitly simulated;
  no server, Docker, provider, campaign, review or adoption occurred. The
  simulated footer is labelled `SIMULATED`, not `LIVE`.
- `H-21b-real-wheel-tests.png`: fresh real-terminal installed-wheel test run
  from outside the checkout, 76 passed. Docker/provider are mocked. The CI
  workflow configuration is statically checked; it has not run remotely.
- The installed offline demo also exited zero headlessly. Final full source
  suite: 1,153 passed, 12 skipped; selected installed-wheel tests: 76 passed.
  The demo is not live campaign integration, an approval interface, a real
  end-to-end campaign, or a safety proof. H-20, H-21 and H-22 remain open.

### H-21c — advisory two-image comparisons (partial)

- `H-21c-real-portability-preview.png`: fresh installed `arcen harness`
  command in a real PTY rendered by xterm.js/Chromium. It stops at the explicit
  confirmation prompt. Image IDs and provider are fabricated; no Docker,
  provider or judge call occurred.
- `H-21c-real-portability-tests.png`: fresh installed-wheel test run from
  outside the checkout: 27 passed, 2 skipped. Docker and provider are mocked;
  skipped cases include opt-in real-Docker coverage.
- Final source suite: 1,173 passed, 13 skipped. A broader installed-wheel run:
  36 passed, 2 skipped. Changed-file Ruff, format, wheel and documentation
  checks passed. Two IDs are not evidence of independent environments or safety;
  CI's second image is only a labelled variant, and remote CI has not run.
  H-21 remains open, as do adoption, safe resume and unattended autonomy.

### H-21d — local image availability preflight (partial)

- `H-21d-real-image-preflight-tests.png` is a fresh installed-wheel test run
  in a real PTY rendered by xterm.js/Chromium. The six cases use a mocked Docker
  daemon: both IDs must resolve exactly, no pull is permitted, failures are
  sanitized and no trial, model or judge admission occurs on preflight failure.
- Final source suite: 1,179 passed, 13 skipped. Selected installed-wheel suite:
  42 passed, 2 skipped. Changed-file Ruff, format, wheel and docs checks passed.
  This check has not been validated against a real Docker daemon. It does not
  reserve images, attest their provenance, establish safety or prevent a later
  disappearance; H-21 and the adoption/automation gates remain open.

### H-17c / H-21e — momentary admission-minimum checks (partial)

- `H-17c-real-budget-preflight-tests.png`: fresh installed-wheel tests in a
  real PTY rendered by xterm.js/Chromium; 25 passed. Both in-memory and durable
  budgets are exercised, including validation, shortfall, stop, and spending
  after a check. This is a minimum snapshot, not an admission reservation.
- `H-21e-real-budget-guard-tests.png`: fresh installed-wheel portability tests
  in the same real-terminal capture method; 5 passed, 22 deselected. Docker and
  providers are mocked. They cover rejection before image/trial/provider work
  and a competing consumer interrupting a run after the check.
- Full source suite: 1,208 passed, 13 skipped. Selected installed-wheel suite:
  95 passed, 3 skipped. Changed-file Ruff, format, wheel and docs checks passed.
  The CI change has not run remotely, and real Docker and providers remain
  unvalidated. These partial increments do not complete H-17 or H-21, enforce
  a spending/runtime limit, authorize adoption or permit safe auto-resume.

### H-17d / H-21f — local concurrency and native executor (partial)

- `H-17d-real-concurrency-tests.png`: fresh installed-wheel tests in a real PTY
  rendered by xterm.js/Chromium; 10 passed. Docker/provider are mocked. A single
  cooperating `SharedBudget` instance can reject concurrent probes without
  spending; uncertain cleanup stops it. This does not coordinate processes or
  terminate work already running.
- `H-21f-real-executor-tests.png`: fresh installed-wheel native-executor tests
  using the same real-terminal capture method; 5 passed. Docker/provider are
  mocked. A Python protocol is not evidence that an adapter is safe, and only
  ARCEN's native executor is wired into paired comparison.
- Final source suite: 1,223 passed, 13 skipped. Selected installed-wheel suite:
  129 passed, 5 skipped. Changed-file Ruff, format, wheel and docs checks pass.
  No Docker daemon was available, the workflow has not run remotely, and
  H-17 and H-21 remain incomplete; no adoption or automatic resume enabled.

### H-12 Docker laptop smoke-test preparation (not H-12 completion)

- `H-12-real-laptop-test-preparation.png`: fresh installed-wheel tests in a real
  PTY rendered by xterm.js/Chromium; 11 passed, 1 skipped. The composed-candidate
  flow uses a mocked Docker boundary here. The opt-in real-Docker case was
  skipped because this environment has no daemon; the screenshot is not a
  Docker-validation result. The user subsequently ran it on their laptop, as
  reported below.
- Full source suite: 1,224 passed, 14 skipped. Selected installed-wheel suite:
  25 passed, 1 skipped. Changed-file Ruff and wheel/docs checks passed. The
  prepared real-Docker test creates two disposable containers with a mocked
  model and judge; it had not yet run on the laptop when this was captured. See
  `docs/HARNESS-H12-LAPTOP-TEST.md`. H-12 remains open regardless of this
  narrow test, and no adoption or autonomous composition is enabled.

### User-reported H-12 real-Docker laptop result

On 31 October 2026 the user reported building `arcen-h12-test:local` and
running `tests/test_h12_docker.py` with `ARCEN_TEST_DOCKER_ISOLATION=1` at
`cbb4ac8`. Their terminal showed `.. [100%]`: both test cases passed, one
with real Docker and one with a mocked Docker boundary. Double-quiet pytest
suppressed the numerical summary. The provider and judge were mocked. This
was the user's report, not a daemon run in this workspace; no laptop screenshot
was supplied. The full H-12 ticket remains open.

### H-12a/b — reviewed conflict drafts and local patch workflow (partial)

- `H-12a-real-conflict-draft-tests.png`: fresh installed-wheel test run in a
  real PTY rendered by xterm.js/Chromium; 15 passed. Callback responses are
  mocked; no provider, Docker, trial or adoption occurred. The API returns
  unpersisted proposals requiring separate inspection and testing.
- `H-12b-real-conflict-cli.png`: fresh installed `arcen harness` command in a
  real PTY with a disposable locally created recorded-campaign fixture. The
  fixture's earlier provider and Docker work was mocked. The screenshot stops
  at the replacement-file prompt, after the initial confirmation; no patch was
  supplied and no candidate was created. The image is not a safety proof.
- Final source suite: 1,246 passed, 14 skipped; selected installed-wheel tests:
  47 passed, 1 skipped. Changed-file Ruff/format, wheel and docs checks passed.
  Remote CI did not run. The earlier user-reported real-Docker smoke was at
  `cbb4ac8`, before this composer refactor; real Docker was not rerun for this
  newer code. Callbacks may expose data and cost money; local patch resolution
  is syntactic, untrusted and may discard other edits for the same path.
  Full H-12, behavioral selection and automatic recursion remain open.

### H-12c — separately confirmed composite test continuation (partial)

- `H-12c-real-composite-test-cases.png`: fresh installed-wheel tests in a real
  PTY rendered by xterm.js/Chromium; 6 passed. Provider and Docker are mocked.
  Tests cover separate confirmations, mismatch before trial, conflict-patch
  continuation, cancellation, and changed local evidence.
- `H-12c-real-composite-plan-cli.png`: fresh installed `arcen harness` command
  in a real PTY using a disposable recorded-campaign fixture; its earlier model
  and Docker work was mocked. The displayed composite was created locally, and
  the screenshot stops before the `PLAN` confirmation: no new plan, provider
  call, trial or adoption occurred during the captured command.
- Final source suite: 1,257 passed, 14 skipped; selected installed-wheel suite:
  68 passed, 2 skipped. Changed-file Ruff/format, wheel and docs checks passed.
  The current change has not run with real Docker or remote CI. The recorded
  workspace hash is unsigned and checked only during this invocation; it is not
  persisted in the new plan. This does not authorize adoption or safe resume.
  Full H-12, behavioral selection and autonomous recursion remain open.

### H-12c laptop Docker smoke-test preparation

`H-12c-real-docker-test-preflight.png` is a fresh installed-package test run
in a real PTY rendered by xterm.js/Chromium: two mocked-boundary cases passed,
and both real-Docker cases were deliberately skipped because Docker is absent
here. This is preparation, not a Docker pass. The opt-in laptop instructions
and exact scope are in `docs/HARNESS-H12C-LAPTOP-TEST.md`.

### H-12d — workspace-bound composite plans (partial)

`H-12d-real-bound-workspace-tests.png` shows a fresh installed-wheel test run in
a real PTY rendered by xterm.js/Chromium: 6 passed, 25 deselected. Docker and
provider are mocked. The selected cases cover schema migration, required hash
matching and the later-manual-run path after `RUN` cancellation. Full source
suite: 1,264 passed, 16 skipped; selected installed-wheel suite: 65 passed,
5 skipped. Changed-file Ruff/format, wheel, docs and diff checks passed.

The laptop real-Docker pass at `db75d86` preceded this change and does not
validate schema v3. Hashes and the journal are unsigned, older plans remain
unbound, and interrupted campaigns cannot be safely resumed automatically.
No adoption or automatic selection is enabled; full H-12 remains open.

### H-12d laptop Docker smoke-test preparation

`H-12d-real-docker-test-preflight.png` is a fresh installed-wheel run in a real
PTY rendered by xterm.js/Chromium. Four mock-boundary cases passed; four
real-Docker cases were deliberately skipped because Docker is absent here. This
is preparation, **not** a Docker pass. Exact opt-in instructions and limitations
are in `docs/HARNESS-H12D-LAPTOP-TEST.md`.

### H-13a — explicitly confirmed model-drafted lesson (partial)

- `H-13a-real-reflection-confirm.png` is the installed `arcen harness` command
  in a genuine PTY rendered by xterm.js/Chromium, using a disposable fabricated
  local review and observation. Capture stops at `REFLECT`; no provider call,
  lesson write, trial or adoption occurred.
- `H-13a-real-reflection-tests.png` is a fresh installed-wheel terminal run:
  12 passed with provider mocked. Full source suite: 1,278 passed, 18 skipped;
  selected installed-wheel suite: 60 passed. Changed-file Ruff/format, wheel,
  docs and diff checks passed. CI configuration includes these tests and the
  H-12c/d Docker cases but has not run remotely at this revision.
- Reflection consumes only an operator observation and unsigned metadata, not
  retained trajectories; generated hypotheses can be wrong or adversarial.
  Explicit `REFLECT` and `SAVE` are required, and no editor injection, adoption,
  automatic reflection, safe resume or full H-13 completion is claimed. No live
  external provider was used to validate this change.

### H-13b — explicitly reviewed editor experience (partial)

- `H-13b-real-experience-review-cli.png` shows the installed CLI in a real PTY,
  rendered by xterm.js/Chromium with a fabricated local review/note. Capture stops
  at the first confirmation; no provider call, candidate, trial or adoption.
- `H-13b-real-experience-editor-tests.png` is a fresh installed-wheel terminal
  run: 11 passed with provider mocked. Full source suite: 1,289 passed, 18 skipped;
  selected installed-wheel suite: 67 passed. Changed-file Ruff/format, wheel,
  docs and diff checks passed. Remote CI has not been run for this revision.
- Explicit selections are untrusted and may contain prompt injection, falsehoods
  or undiscovered secrets. The selected snapshot is checked after each human
  confirmation but cannot be recalled after provider exposure. No live provider,
  autonomous learning, authenticated approval, adoption or full H-13 is claimed.

### H-12e — read-only contrast advisory (partial)

- `H-12e-real-contrast-advisory-cli.png` shows the installed CLI in a genuine
  PTY rendered by xterm.js/Chromium. Earlier review records and judgments are a
  fabricated disposable fixture; the displayed command does not call a model or
  Docker, select/create candidates, run trials or move refs.
- `H-12e-real-contrast-advisory-tests.png` is a fresh installed-wheel test run:
  6 passed with provider and Docker mocked. Full source suite: 1,295 passed,
  18 skipped; selected installed-wheel suite: 57 passed, 1 skipped. Changed-file
  Ruff/format, wheel, docs and diff checks passed. Remote CI has not been run.
- This is an unranked filter of unsigned local judgments, not independent
  behavioral validation or proof of improvement, safety, approval, provenance,
  automatic composition or H-12 completion.

### H-14b — reviewed parallel probe waves (partial)

- `H-14b-real-parallel-trials-tests.png` shows a fresh installed-wheel test
  run in a real PTY rendered by xterm.js/Chromium: 12 passed. Provider and
  Docker boundaries are mocked; no adoption or resume takes place.
- Full source suite: 1,307 passed, 18 skipped; selected installed-wheel suite:
  85 passed, 4 skipped. Changed-file Ruff/format, wheel, docs and diff checks
  passed. The updated CI configuration has not been executed remotely.
- The Python-only primitive waits for a reference and then starts bounded
  candidate waves against one snapshot with a shared in-process budget. It
  does not judge, persist, select, adopt or resume. Budgets are not durable or
  cross-process, preflight is non-reserving, and already-started work is not
  canceled. This parallel path has not been tested with real Docker or a live
  provider. Full H-14 remains open; see `docs/HARNESS-PARALLEL-TRIALS.md`.

### H-17e — cooperative durable trial slots (partial)

- `H-17e-real-durable-concurrency-tests.png` is a fresh installed-wheel run
  in a real PTY rendered by xterm.js/Chromium: 19 passed. It uses real local
  SQLite and an independently killed subprocess; provider and Docker are
  mocked for the parallel probe path.
- Full source suite: 1,326 passed, 18 skipped; selected installed-wheel suite:
  85 passed, 3 skipped. Changed-file Ruff/format, wheel, docs and diff checks
  passed. The updated CI has not been executed remotely.
- SQLite slots are opt-in, per durable budget, for cooperating local processes
  using the reviewed parallel API. Other APIs can bypass the cap; no distributed
  lease, in-flight kill, automatic reclaim, safe resume or adoption is provided.
  A killed process can leave an occupied slot without closing its budget. Local
  filesystem and database integrity are trusted. Real Docker and live provider
  behavior of this parallel path remain unverified. H-17 remains open.

### H-17e — laptop Docker smoke preparation

- `H-17e-real-laptop-preflight.png` shows a fresh installed-wheel PTY test run
  via xterm.js/Chromium: **20 passed, 1 skipped**. The real-Docker test was
  deliberately skipped here because no Docker daemon was available; the local
  smoke used mocked Docker and provider responses.
- `tests/test_h17e_docker.py` and `HARNESS-H17E-LAPTOP-TEST.md` prepare a
  separate real-Docker run: one reference and two concurrent candidate
  containers with a subprocess checking the durable slot cap. Provider is
  mocked. Laptop result and remote CI are not yet known.

### H-17e — user-reported laptop Docker result

- The user reported commit `51d971a32240dafb26c7a478c7fda5371652c74d`,
  Python 3.12.14 and image `arcen-h12-test:local`: **21 passed in 55.69s**,
  with no skips. This is a terminal report, not a screenshot or independent
  execution by the agent. The real-Docker test held two candidate containers
  concurrently and checked the durable cap from another local process.
- Provider responses were mocked; no judge, live provider, automatic resume,
  adoption or real-container crash recovery was tested. The earlier entries
  describe what was known at their capture time. Full H-14/H-17 remain open.

### H-11i — opt-in campaign progress v2 bridge (partial)

- `H-11i-real-v2-simulation.png` is a fresh installed `arcen-tui --demo
  --harness` PTY capture rendered by xterm.js/Chromium. It is an explicitly
  labelled, fabricated offline simulation; no campaign, Docker, provider,
  approval or adoption occurred. The demo uses the new emitter bridge and
  opt-in TUI registration.
- `H-11i-real-v2-progress-tests.png` is a fresh installed-wheel terminal run:
  **25 passed**; provider and Docker are mocked. Full source: **1,352 passed,
  19 skipped**. Selected installed-wheel tests: **90 passed, 1 skipped**.
  Changed-file Ruff/format, wheel, docs and diff checks passed. The updated CI
  configuration has not been run remotely.
- Seven metadata-only manual progress types can opt in to a session emitter.
  The frozen legacy types and strict decoder are unchanged; the legacy TUI
  ignores unknown types. Events are unauthenticated, best-effort narration,
  not durable evidence or authorization. The live server and CLI are not wired
  to this bridge, and the full architecture v2 event contract and H-11 remain
  incomplete. No live provider was tested.

### CI — deterministic Docker detection and pytest subprocess tests

- GitHub Harness validation run `41354334179` for `a4d736c` had a successful
  real-Docker job but failed the Python 3.12 and 3.13 full suites on the same
  two environment-dependent tests: daemon availability and noisy third-party
  pytest plugin stderr. The failure did not establish a production regression.
- The server warning test now explicitly mocks an unavailable daemon, and the
  planted-assertion subprocess disables third-party pytest plugin autoload.
  No production code or model payload was changed.
- Fresh local full suites on Python 3.12.16 and 3.13 each reported **1,352
  passed, 19 skipped**. `CI-real-runner-determinism-tests.png` shows a fresh
  installed-package Python 3.12 PTY run of nine focused tests, rendered using
  xterm.js/Chromium. GitHub validation of the follow-up commit is pending.
