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
.venv/bin/python scripts/capture_ui_demo.py
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
