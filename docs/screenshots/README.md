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
