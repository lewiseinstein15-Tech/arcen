# Proof of a real turn

Screenshots from a live run of the app, not mockups. The goal was
`build a calc module with tests and make them pass`; the planner wrote a
module with a real bug, the suite failed, DRAFT re-planned, FORGE fixed the
file, the suite passed, and TEMPER signed off.

| File | What it shows |
| --- | --- |
| `01-plan.png` | DRAFT returns a two-step plan |
| `02-red-tests.png` | FORGE runs `python -m pytest -q` inside the sandbox and the suite fails |
| `03-replan-fix.png` | DRAFT re-plans, FORGE reads the file and edits it |
| `04-verified.png` | Suite green, TEMPER verified, turn `ok` |
| `05-sandbox-settings.png` | Settings page: provider, sandbox backend, isolation policy |
| `06-terminal-proof.png` | Container isolation sampled mid-turn, exported patch, patch applied and tested on the host |

The `07-geometry-*` set is the same app driven through `file.write` instead of
`file.edit`: the goal was `create a geometry module with tests and make them
pass`, nothing existed in the workspace, and both the module and its tests were
created by whole-file writes from inside the container.

| File | What it shows |
| --- | --- |
| `07-geometry-01-plan.png` | DRAFT plans two `file.write` steps plus a test run |
| `07-geometry-02-red-tests.png` | Both writes land (`bytes: 85`, `bytes: 163`), pytest fails with `2 failed` |
| `07-geometry-03-replan-fix.png` | DRAFT re-plans after the failure |
| `07-geometry-04-verified.png` | `file.read`, whole-file rewrite, `2 passed`, TEMPER verified |

The `08-live-*` set is not scripted at all: a real model planned it. Provider
`kilo` (keyless gateway), model `baidu/ernie-5.5-flash-preview:free`, goal
`create a module stats.py with mean, median and mode plus tests, run the tests
and fix any failures`. Three steps, 16.12 s, 719 in / 3163 out, cost 0.000.

| File | What it shows |
| --- | --- |
| `08-live-01-plan.png` | The model's own three-step plan, two `file.write` results, `unittest` 4/4 OK, TEMPER starting |
| `08-live-03-verified.png` | TEMPER verified, turn `ok`, token and cost meters |
| `08-live-04-provider.png` | Settings: provider `kilo`, base URL, "not required — this provider is keyless" |

## Reproducing

```bash
# 1. a planner that needs no API key (scripted, deterministic)
DEMO_DELAY=3 .venv/bin/python scripts/demo_agent.py 9378 &

# 2. point ARCEN at it
mkdir -p ~/.arcen
printf 'provider:\n  name: custom\n  base_url: http://127.0.0.1:9378/v1\n  api_key: demo-key\n  model: demo-planner\n' > ~/.arcen/config.yaml

# 3. app
.venv/bin/uvicorn arcen.server.app:app --port 3002 &
(cd ui && npm run dev -- --port 12000 --host 0.0.0.0)

# 4. drive the UI and capture the frames
.venv/bin/python scripts/capture_ui_demo.py          # the calc/edit run
.venv/bin/python scripts/capture_ui_demo.py geometry # the file.write run
.venv/bin/python scripts/capture_live_model.py       # a real-model turn (needs a provider)
```

The headless path needs no browser:

```bash
mkdir -p /tmp/calc && cd /tmp/calc && git init -q
# add a module with a failing test, commit, then:
arcen run "fix the failing test in calc" --workspace /tmp/calc --json
arcen apply <session-id> --yes   # from inside /tmp/calc
```

Only planning is scripted. Execution is real: the steps run in the Docker
sandbox, pytest really fails and then really passes, and the patch in
`06-terminal-proof.png` is a host-generated diff applied to the host repo.

The `09-tools-*` and `10-loop-*` sets are from the v0.2 tool surface: the
Tools view (tools/skills/MCP/prompt tabs), the run trace waterfall, and a live
DRAFT → FORGE → TEMPER turn against Docker with the git tools. Provider
`kilo`, model `baidu/ernie-5.5-flash-preview:free`, served by the backend
itself (`npm run build` in `ui/`, then `python -m arcen.server.app` on one
port — no Vite in the loop).

| File | What it shows |
| --- | --- |
| `09-tools-01-tool-catalog.png` | 20 tools advertised to the planner, grouped by trust domain (Sandbox 17 / Host 3) with each tool's arguments |
| `09-tools-02-skills.png` | The 11 installed skills with the tools each one is allowed to use |
| `09-tools-03-prompt-inspector.png` | The exact catalog string the planner receives, plus the prompt templates |
| `10-loop-01-draft-forge-temper-pass.png` | Live turn: `file.write` ×2, `python -m pytest -q` → `1 passed`, TEMPER verified, turn `ok`, trace strip reading `11 steps · 5.1s` |
| `10-loop-02-git-tools-in-sandbox.png` | Live turn using `git.add`, `git.commit`, `git.log` with `root=/workspace`; commit `d3061a4b` on `master`, tree clean, TEMPER `unverified · no test command found` |

`10-loop-03-followup-verified.png` is the second message of that same
conversation, and the one that mattered: a turn gets a disposable container,
so `calc.py` from the previous message was gone. Before the planner was told
this, it planned `file.read calc.py`, re-planned twice, and the turn died with
`no such file or directory`. Now the workspace note is part of the brief the
planner receives (`## workspace`, also visible in the prompt inspector), so
the same goal plans `file.write calc.py` → `file.write test_calc.py` →
`pytest` → `2 passed`, TEMPER verified, turn `ok`, 3 steps · 14.01 s.

The `11-reasoning-*` set is the v0.3 reasoning layer in the product UI, on a
live provider (`kilo`, `baidu/ernie-5.5-flash-preview:free`), served by the
backend alone. Nothing was scripted: the goal
`create fizzbuzz.py with fizzbuzz(n) and test_fizzbuzz.py, then run pytest`
went through the real planner, the real Docker sandbox and the real verifier.

| File | What it shows |
| --- | --- |
| `11-reasoning-01-idle.png` | The app before the turn |
| `11-reasoning-02-turn.png` | Turn `ok`: `file.write` ×2, `pytest` → `3 passed`, TEMPER verified, memory write, `3 steps · 7.9s` |
| `11-reasoning-03-plan.png` | The same turn from the top: a `recall` line from memory, the 3-step plan, and `DRAFT Complexity moderate (score 1.60); allowing 1 refinement pass(es).` |

That last line is the new part. The goal is scored before any work starts, and
the budget it earns is what bounds the refinement loop. On this goal the first
verification passed, so no refinement was spent — which is the intended
outcome, and visible on the stream rather than hidden.

Capture them again with:

```bash
.venv/bin/arcen serve                                  # serves the API and ui/dist
.venv/bin/python scripts/capture_reasoning_shots.py    # writes docs/screenshots/11-*.png
```
