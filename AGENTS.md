# AGENTS.md

Local run/verification notes for this repo (backend `src/arcen`, UI `ui/`).

## Run the dev stack
```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev,sandbox]"
.venv/bin/python -m uvicorn arcen.server.app:app --port 3002 --host 0.0.0.0
cd ui && npm install && npm run dev -- --port 12000 --host 0.0.0.0
```
- Backend health: `GET /api/health` -> `{"ok": true}`.
- Vite 6 blocks unknown Host headers. Expose the UI behind a proxy host with
  `__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=<host> npm run dev ...` (only works
  because the dev config leaves `server.allowedHosts` unset; it is appended
  when the value is an array).

## Offline model provider
No API key is needed to exercise the loop:
```bash
.venv/bin/python scripts/mock_provider.py 9377   # OpenAI-compatible mock
curl -X PUT localhost:3002/api/config -H 'Content-Type: application/json' \
  -d '{"provider":{"name":"custom","base_url":"http://localhost:9377/v1","api_key":"mock-key","model":"mock-planner"}}'
```
Mock planner shapes: DIRECT (no tools), RESEARCH (`search.text`/`http.get`),
CODE (`file.list`, then `bash`). Goals containing `flaky` fail once then
succeed; `doomed` always fails.

For a demo that exercises the full fix-a-real-bug loop (red tests → replan →
edit → green → TEMPER), use `scripts/demo_agent.py` on port 9378: goals
containing `calc` scaffold a module with a real bug, watch pytest fail, then
read, edit and re-run. `DEMO_DELAY=<seconds>` paces the provider so the phases
are visible on screen; `scripts/capture_ui_demo.py` drives the UI with
Playwright and writes `docs/screenshots/`.

## Sandbox (tool execution)
FORGE/TEMPER fail closed without Docker. Start the daemon and make the socket
reachable to the server user, then restart the backend (backend selection is
made at boot):
```bash
sudo dockerd > /tmp/docker.log 2>&1 &
sudo chmod 666 /var/run/docker.sock
sudo docker pull ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0
```
Live isolation check (host paths hidden, server env not leaked, no network):
`ARCEN_TEST_DOCKER_ISOLATION=1 .venv/bin/pytest tests/test_turn_isolation.py -k real_docker`

## Things that bite
- `file.edit` invalidates sibling `__pycache__/<stem>.*.pyc` after a write. A
  same-second, same-size rewrite otherwise passes CPython's (mtime, size)
  check and the next run imports the old bytecode — it looks like the edit
  silently did nothing.
- Exported patches skip `__pycache__`, `.pytest_cache`, `.mypy_cache`,
  `.ruff_cache`, `.tox` and `node_modules`; a turn that runs tests would
  otherwise ship its own caches into the user's diff.
- Docker socket permissions reset when the daemon restarts; the server user
  needs `sudo chmod 666 /var/run/docker.sock` (or group membership) and a
  backend restart.

## Current gaps
- The isolated turn executor ports `bash`, `file.read`, `file.list`, `file.glob`,
  `search.text` and `file.edit` (path-confined to `/workspace`). `file.write`,
  `http.get` and the code tools are denied, so plans using them fail/replan.
- Container edits leave the sandbox as a host-generated patch in
  `~/.arcen/artifacts/<session>/patch.diff`; `arcen apply SESSION --yes` applies
  it to the repo the turn ran against (no commit).
- UI `Projects` and `Tools` nav entries are `view: null` placeholders (v0.2).
- CLI: `arcen --version` and `arcen resume SESSION [--after SEQ] [--list]` are
  implemented (usage: `arcen [serve | run GOAL --json | apply SESSION | resume SESSION | harness]`).
- Config, sessions and memory live in `~/.arcen` (`config.yaml` chmod 600).
