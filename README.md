<div align="center">

<img src="docs/logo.svg" width="120" alt="ARCEN logo" />

# ARCEN

**Agentic reasoning. Code. Engineer.**

[![CI](https://github.com/lewiseinstein15-Tech/arcen/actions/workflows/ci.yml/badge.svg)](https://github.com/lewiseinstein15-Tech/arcen/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-0.1.0-orange.svg)](docs/TICKETS.md)

*An agentic engineer that plans, builds, and verifies — with every action narrated in a live stream.*

[What is ARCEN](#what-is-arcen) · [Quick Start](#quick-start) · [How it Works](#how-it-works) · [Installation](#installation) · [Configuration](#configuration) · [Docs](docs/ARCHITECTURE.md)

</div>

---

## What is ARCEN?

Most coding agents are black boxes: you submit a task, wait, and receive an answer with no way to see what happened in between — or to trust it when it breaks. ARCEN is an agentic engineer that plans with DRAFT, executes with FORGE, and verifies with TEMPER, narrating every thought, command, and result as it happens. The work is watchable: a live NDJSON stream shows every step, so you can audit, interrupt, or rerun anything.

ARCEN does not invent. It pulls from the best open-source agent projects, edits only what it needs, wires it, and tests it.

## Quick Start

```bash
pip install arcen
export ANTHROPIC_API_KEY="sk-ant-..."   # or OPENAI_API_KEY, GROQ_API_KEY, ...
arcen "fix the failing test in tests/test_pay.py"
```

Every step DRAFT plans, FORGE runs, and TEMPER checks streams to your terminal as one JSON object per line. When TEMPER fails the work, DRAFT re-plans — you watch it happen.

### Pointing the server/UI at a model with env vars

Running `arcen serve` or `./scripts/dev.sh`? Set the `ARCEN_MODEL_*` variables before boot and the Settings page shows them already filled — no retyping, no "I need a model provider" on the first message:

```bash
export ARCEN_MODEL_PROVIDER="custom"                                 # or groq / deepseek / openai / anthropic / ollama
export ARCEN_MODEL_BASE_URL="https://inference.dahl.global/v1"       # your OpenAI-compatible endpoint (custom/ollama)
export ARCEN_MODEL_API_KEY="dahl_..."                                # seeded into the masked key field
export ARCEN_MODEL_NAME="deepseek-ai/DeepSeek-V4-Flash-0731"         # the model for all agents
./scripts/dev.sh
```

On boot ARCEN seeds any EMPTY provider slot from these vars (a value already in `~/.arcen/config.yaml` always wins) and writes the seeded file once, logging one line with the key masked — `[config] seeded from env: provider=custom model=… base_url=… api_key=dahl_...a71b`. After that first boot the file is the source of truth: restarts don't re-seed, and unsetting the env vars won't unconfigure the server.

### Running the dev stack (backend + UI)

The UI proxies `/api/*` to the backend on port **3002** — so the backend must be up FIRST, or Vite spams `ECONNREFUSED`. Two shells:

```bash
# Shell 1 — backend first (health check: http://localhost:3002/api/health → {"ok": true})
python -m uvicorn arcen.server.app:app --port 3002

# Shell 2 — then the frontend
cd ui && npm install && npm run dev      # UI at :5173
```

Or start both cleanly with one command — the script backgrounds the backend, traps it on exit, and brings up the UI:

```bash
./scripts/dev.sh
```

npm shortcuts are wired at the repo root too: `npm run dev:backend`, `npm run dev:frontend`, `npm run dev` (both).

## The Sandbox: Docker or Honest Fallback

ARCEN executes FORGE's commands inside a sandbox — one per session, zero host binds, network off, resources capped. Two backends, selected automatically at session start:

- **docker** — used when a docker daemon is reachable **and** the pinned sandbox image is present locally:

  ```bash
  docker pull ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0   # required for the docker backend
  ```

- **process** (degraded fallback) — when there is no daemon, or the image is absent. Commands run in a per-session quarantine root (`/tmp/arcen-s-<id>`), file-tool paths are resolved against that root, escapes are refused, the environment is scrubbed. Honest about the limit: this is confinement, not isolation — the runtime reports `degraded: true` and the UI never overclaims.

The image is built and pushed to GHCR by `.github/workflows/sandbox-image.yml` on every push to `main`. To build it locally instead:

```bash
docker build -t ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0 docker/sandbox
```

Only known-good references (ARCEN's own pinned GHCR repo, or an explicit `ARCEN_SANDBOX_IMAGE=<ref>` override) are ever auto-pulled, at most once per boot; anything else falls back to the process backend with zero network attempts. A container-create failure mid-session degrades the session to the process backend instead of crashing it.

## Features

- **Narrated execution** — every thought, command, and result is one NDJSON event on the stream
- **3 core agents** — DRAFT plans, FORGE executes, TEMPER verifies; nothing else decides
- **500+ sub-agents** — spawned on demand, named for their task, depth-capped
- **10,000+ skills** — SKILL.md folders loaded progressively, indexed at boot
- **1,000+ tools** — bash, file, search, browse, code; schema-generated, sandboxed
- **300+ MCPs** — Model Context Protocol servers, connected lazily
- **100+ plugins** — hooks at every point in the loop: `before_tool`, `after_tool`, `on_spawn`, `on_error`
- **Sandboxed execution** — one Docker container per session when the sandbox image is present; otherwise a quarantined process backend that reports `degraded: true`. The host is never touched
- **Persistent memory** — entity graph in a single SQLite file with decay and consolidation
- **Multi-provider** — one LiteLLM bridge: Anthropic, OpenAI, Groq, local models
- **NDJSON streaming** — 17 frozen event types; resume with `Last-Event-ID`
- **Local-first** — config, memory, and sessions live in `~/.arcen`; no cloud dependency

## How it Works

```
┌──────────────────────────────────────────────────────────────┐
│                             YOU                              │
│                 "fix the failing test in tests/"             │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
                   ┌───────────────────────┐
                   │         DRAFT         │  plans. narrates.
                   │  planner · opens turn │  spawns sub-agents.
                   └───────────┬───────────┘  re-plans on fail.
                               │ plan
                               ▼
                   ┌───────────────────────┐
                   │         FORGE         │  executes. one step
                   │ executor · tool calls │  at a time. returns
                   └───────────┬───────────┘  observations.
                               │ observation
                               ▼
                   ┌───────────────────────┐
                   │        TEMPER         │  verifies. tests
                   │ verifier · adversarial│  adversarially.
                   └───────────┬───────────┘  reports pass/fail.
                               │
                    pass ✓ ────┴──── ✗ fail ──▶ back to DRAFT
                               ▼
                   ┌───────────────────────┐
                   │        ANSWER         │  prose. every claim
                   └───────────────────────┘  backed by a step.
```

Sub-agents fan out under DRAFT for parallel work (research, exploration, bulk edits) and report back into the same stream:

```ndjson
{"type":"run.start","run_id":"r-01J9","goal":"fix the failing test","depth":0,"ts":1727500000.000}
{"type":"think","agent":"DRAFT","text":"Goal: fix failing test. Read the test first, then the module under test.","ts":1727500000.104}
{"type":"plan","agent":"DRAFT","steps":[{"id":1,"title":"read failing test","tool":"file.read"},{"id":2,"title":"run pytest -q","tool":"bash"},{"id":3,"title":"apply minimal fix","tool":"file.edit"}],"ts":1727500000.220}
{"type":"spawn","parent":"DRAFT","name":"TEST-READER","task":"extract the failing assertion","depth":1,"ts":1727500000.410}
{"type":"command","agent":"TEST-READER","step":1,"tool":"file.read","args":{"path":"tests/test_pay.py"},"ts":1727500000.655}
{"type":"command.done","step":1,"ok":true,"result":{"stdout":"def test_pay(): assert calc(2, 2) == 5"},"duration_s":0.004,"ts":1727500000.659}
{"type":"step.fail","step":1,"reason":"test expects 5, calc(2,2) returns 4 — test bug","retry":0,"ts":1727500001.002}
{"type":"plan.update","agent":"DRAFT","reason":"test bug found; fix the assertion","steps":[{"id":1,"title":"edit test to expect 4","tool":"file.edit"},{"id":2,"title":"re-run suite","tool":"bash"}],"ts":1727500001.300}
{"type":"command","agent":"FORGE","step":2,"tool":"file.edit","args":{"path":"tests/test_pay.py","find":"== 5","replace":"== 4"},"ts":1727500001.480}
{"type":"command.done","step":2,"ok":true,"result":{"path":"tests/test_pay.py","bytes_changed":9},"duration_s":0.006,"ts":1727500001.486}
{"type":"verify.start","agent":"TEMPER","target":"tests/","ts":1727500001.700}
{"type":"step.pass","step":3,"checks":["pytest -q tests/  # 12 passed"],"ts":1727500004.010}
{"type":"answer","text":"The test expected `calc(2, 2) == 5`; `calc` correctly returns 4. Fixed the assertion. Suite: 12 passed.","ts":1727500004.400}
{"type":"usage","tokens":{"input":18432,"output":1204},"cost_usd":0.021,"ts":1727500004.410}
{"type":"run.done","status":"ok","steps":3,"duration_s":4.5,"ts":1727500004.420}
```

## Installation

<details>
<summary><strong>pip</strong> (recommended)</summary>

```bash
pip install arcen
arcen --version
```

</details>

<details>
<summary><strong>uv</strong></summary>

```bash
uv tool install arcen
arcen --version
```

Or run without installing:

```bash
uvx arcen "summarize the failures in tests/"
```

</details>

<details>
<summary><strong>Docker</strong></summary>

```bash
docker pull ghcr.io/lewiseinstein15-tech/arcen:0.1.0
docker run --rm -it \
  -v ~/.arcen:/root/.arcen \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e ANTHROPIC_API_KEY \
  ghcr.io/lewiseinstein15-tech/arcen:0.1.0 "run pytest and fix failures"
```

The Docker socket is mounted so ARCEN can create per-session sandboxes. Omit it to run without sandboxing. The sandbox itself needs the pinned image: `docker pull ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0` (see [The Sandbox](#the-sandbox-docker-or-honest-fallback)) — without it, ARCEN degrades to the quarantined process backend.

</details>

<details>
<summary><strong>From source</strong></summary>

```bash
git clone https://github.com/lewiseinstein15-Tech/arcen
cd arcen
pip install -e ".[dev]"
pytest -q
arcen --version
```

</details>

## Usage

```bash
arcen "fix the failing pytest suite in tests/"          # plan → build → verify
arcen "refactor src/auth to use httpx" --dry-run        # stream the plan, change nothing
arcen "review this repo against the spec" --mcp github  # pull tools from an MCP server
arcen serve --port 3002                                 # NDJSON stream server for the UI
arcen resume r-01J9                                     # replay or continue a session
```

## Configuration

ARCEN reads `~/.arcen/config.yaml` (seeded from `ARCEN_MODEL_*` env vars on first boot — see Quick Start above). The provider block is four scalars; a literal API key is allowed (the file is chmod 600), and a `$VAR` reference is resolved from your environment at boot:

```yaml
provider:
  name: custom                                   # custom | groq | deepseek | openai | anthropic | ollama
  base_url: https://inference.dahl.global/v1     # OpenAI-compatible endpoint (custom/ollama)
  api_key: $DAHL_API_KEY                         # literal (chmod 600 file) or $VAR vault reference
  model: deepseek-ai/DeepSeek-V4-Flash-0731      # the model for all agents

agents:
  draft:
    max_steps: 40
    replan_on_fail: true
    model: null                                  # null → inherit provider.model
  forge:
    step_timeout_s: 120
    max_retries: 2
    model: null                                  # null → inherit provider.model
  temper:
    adversarial: true
    reruns: 1
    model: null                                  # an explicit value overrides just this agent

subagents:
  max_depth: 2
  max_concurrent: 8
  default_model: null    # null → inherit provider.model

stream:
  port: 3002
  content_type: application/x-ndjson
```

Every value has an API equivalent (`PUT /api/config`). See [docs/BACKEND-SPEC.md](docs/BACKEND-SPEC.md) Part 4.

## Skills

Skills are folders with a `SKILL.md`. They are indexed at boot and loaded progressively — the frontmatter first, the body only when a task matches:

```markdown
---
name: pytest-repair
version: 0.1.0
description: Fix failing pytest suites with minimal diffs
tools: [bash, file.read, file.edit]
---

# Pytest Repair

1. Run `pytest -q` and capture the first failure.
2. Read the failing test and the module under test.
3. Decide: test bug or code bug.
4. Apply the minimal edit.
5. Re-run the suite. Pass → report. Fail → escalate to DRAFT.
```

## Tools

Tools implement one Protocol. Schemas are generated from type hints — you never write JSON Schema by hand:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Tool(Protocol):
    name: str            # unique, dotted: "file.edit"
    description: str     # shown to the model
    schema: dict         # JSON Schema, auto-generated from execute() hints

    def execute(self, args: dict) -> dict:
        """Returns {"ok": bool, "result": Any, "error": str | None}."""
```

Register it once — it is then callable by FORGE, sub-agents, and any connected MCP client.

## MCPs

MCP servers are declared in config and connected lazily — no network I/O at boot:

```yaml
mcps:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
    state: declarative          # connects on first tool call
  - name: github
    transport: http
    url: https://api.githubcopilot.com/mcp/
    state: connected
    headers:
      Authorization: Bearer $GITHUB_PAT
```

## Plugins

Plugins hook every point in the loop:

```python
from arcen.plugins import Plugin, hook

class RedactSecrets(Plugin):
    name = "redact-secrets"

    @hook("after_tool")
    def scrub(self, event: dict) -> dict:
        if event["tool"] in {"bash", "file.read"}:
            event["result"] = redact(event["result"])
        return event
```

Available hooks: `on_boot`, `before_tool`, `after_tool`, `on_spawn`, `on_error`, `on_shutdown`.

## Contributing

The `.venv` directory is gitignored. Create it with `python -m venv .venv && source .venv/bin/activate`, then install the dev extras (`pip install -e ".[dev]"`) — CI and the GHCR image build are unaffected by local virtualenv provisioning.

```bash
git clone https://github.com/lewiseinstein15-Tech/arcen
cd arcen
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                      # full backend suite, must pass 3x back-to-back
./scripts/dev.sh               # backend on :3002 + UI on :5173
cd ui && npm install && npm run test   # frontend suite
```

Read [docs/BACKEND-SPEC.md](docs/BACKEND-SPEC.md) and [docs/FRONTEND-SPEC.md](docs/FRONTEND-SPEC.md) before your first PR. Pick a ticket from [docs/TICKETS.md](docs/TICKETS.md), follow its verification loop, and commit against it.

## License

[MIT](LICENSE) — © 2026 lewiseinstein15-Tech

---

<div align="center">

**Built from the best parts of the open-source agent ecosystem.**

[Aider](https://github.com/Aider-AI/aider) ·
[OpenHands](https://github.com/All-Hands-AI/OpenHands) ·
[SWE-agent](https://github.com/SWE-agent/SWE-agent) ·
[CrewAI](https://github.com/crewAIInc/crewAI) ·
[Anthropic Skills](https://github.com/anthropics/skills) ·
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) ·
[LiteLLM](https://github.com/BerriAI/litellm) ·
[Letta](https://github.com/letta-ai/letta) ·
[Graphiti](https://github.com/getzep/graphiti) ·
[AG-UI](https://github.com/ag-ui-protocol/ag-ui) ·
[OpenSandbox](https://github.com/alibaba/OpenSandbox) ·
[Claude Code](https://github.com/anthropics/claude-code)

</div>

