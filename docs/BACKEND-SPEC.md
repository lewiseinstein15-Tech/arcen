# ARCEN — Backend Specification

> Status: **frozen for v0.1** · Version: 0.1.0 · Owner: [@lewiseinstein15-Tech](https://github.com/lewiseinstein15-Tech)
> Companion docs: [ARCHITECTURE.md](ARCHITECTURE.md) · [FRONTEND-SPEC.md](FRONTEND-SPEC.md) · [TICKETS.md](TICKETS.md)

---

## Part 0 — What ARCEN is

ARCEN (Agentic reasoning + Code + Engineer) is an agentic engineer that plans, builds, and verifies — with full transparency. Every action is narrated on a live NDJSON stream: every thought, every command, every result, every pass/fail.

- Repository: <https://github.com/lewiseinstein15-Tech/arcen>
- The rule: **pull, edit, wire, test. Never invent.** Every component borrows from a named open-source project (Part 2). We edit only what we need, wire it together, and prove it with tests. If a component cannot be pulled from an existing project, we write the minimum and mark it in the pull map.

Three core agents only: **DRAFT** (planner), **FORGE** (executor), **TEMPER** (verifier). Everything else is a sub-agent or a capability layer service.

---

## Part 1 — Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  L1 · CORE AGENTS (the only 3)                                     │
│                                                                    │
│   DRAFT ──plan──▶ FORGE ──observation──▶ TEMPER                    │
│   planner          executor          verifier                      │
│   opens turn       one step          adversarial                   │
│   spawns subs      at a time         pass / fail                   │
│        ▲                 │                   │                     │
│        └────── re-plan ◀─┴──── fail ────────┘                     │
├────────────────────────────────────────────────────────────────────┤
│  L2 · SUB-AGENT POOL                                               │
│   500+ sub-agents, spawned on demand, named for their task         │
│   TEST-READER · RESEARCH · MIGRATOR · BENCH · DOC-WRITER · ...     │
│   depth-capped (default 2), concurrency-capped (default 8)         │
├────────────────────────────────────────────────────────────────────┤
│  L3 · CAPABILITY LAYER                                             │
│   skills (10,000+) · tools (1,000+) · MCPs (300+)                  │
│   plugins (100+) · memory (entity graph)                           │
├────────────────────────────────────────────────────────────────────┤
│  L4 · RUNTIME                                                      │
│   Docker sandbox per session · FastAPI server · NDJSON stream      │
│   session jsonl on disk · SQLite memory · config + vault           │
└────────────────────────────────────────────────────────────────────┘
```

The 3 core agents and their jobs:

| Agent | Role | Job | Pulled from |
|---|---|---|---|
| **DRAFT** | Planner | Opens every turn. Breaks the goal into steps, spawns sub-agents, re-plans on failure. Emits `think` + `plan` events. | Aider |
| **FORGE** | Executor | Runs tools, one step at a time. Returns observations. Emits `command` + `command.done`. | OpenHands |
| **TEMPER** | Verifier | Tests adversarially — tries to break the work. Reports pass/fail. Emits `verify.start`, `step.pass`, `step.fail`. | SWE-agent |

**Only 3 agents exist.** Planners, executors, verifiers at other depths are all sub-agents — spawned by DRAFT (or by other sub-agents, depth-capped), named for their task (`TEST-READER`, `MIGRATOR`), and torn down when done. No fourth core agent is ever added without a spec revision.

---

## Part 2 — Pull Map

Every component borrows from a named source. "What to edit" is the full allowed diff — anything beyond it is a spec violation.

| # | Component | Source repo | What to pull | What to edit |
|---|---|---|---|---|
| 1 | DRAFT planner | [Aider](https://github.com/Aider-AI/aider) | `architect_coder.py` — plan decomposition loop | Prompts → 3-agent shape; emit `think`/`plan`/`plan.update`; spawn hooks |
| 2 | FORGE executor | [OpenHands](https://github.com/All-Hands-AI/OpenHands) | `controller/agent.py` + `tools/` — agent state machine | Reduce to step-at-a-time; emit `command`/`command.done`; route through registry |
| 3 | TEMPER verifier | [SWE-agent](https://github.com/SWE-agent/SWE-agent) | `reviewer.py` — adversarial review pass | Output → binary pass/fail + reasons; emit `verify.start`/`step.pass`/`step.fail` |
| 4 | Sub-agents | [CrewAI](https://github.com/crewAIInc/crewAI) | `agent.py` + `task.py` — spawn/task model | Add depth cap, concurrency cap, per-sub-agent naming, spawn events |
| 5 | Skills | [Anthropic Skills](https://github.com/anthropics/skills) | loader + registry pattern (`loader.py`, `registry.py` equivalent) | Progressive loading: index frontmatter at boot, body on match |
| 6 | Tools | [OpenHands](https://github.com/All-Hands-AI/OpenHands) | `tools/` package — bash, file, search, browse, code | Wrap each in the frozen Tool schema (Part 3); sandbox routing |
| 7 | Tool registry | ToolRegistry pattern | `registry.py` — schema generation + lookup | JSON Schema auto-gen from type hints; TOML registry file |
| 8 | MCPs | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | `client/` — stdio + HTTP transports | Add lazy state machine (Part 6); config-driven declaration |
| 9 | Plugins | DeepSeek Harness pattern | plugin loader — hook registry | Freeze 6 hooks (Part 7); sync hook chain, async allowed per hook |
| 10 | Streaming | [AG-UI](https://github.com/ag-ui-protocol/ag-ui) | `sdk/python/ag_ui/` — event typing, encoder | Reduce to the frozen 17 events (Part 9); NDJSON framing |
| 11 | Sandbox | [OpenSandbox](https://github.com/alibaba/OpenSandbox) | `runtime/` — container lifecycle | One container per session; image pinning; host-filesystem quarantine |
| 12 | Memory | [Letta](https://github.com/letta-ai/letta) + [Graphiti](https://github.com/getzep/graphiti) | `memory/` + `src/` — store + graph memory | Single SQLite file; the five GraphMem innovations (Part 5) |
| 13 | Session format | [Claude Code](https://github.com/anthropics/claude-code) | `history.jsonl` format | Add event `seq`, `run_id`, `ts`; write-once append-only |
| 14 | LLM bridge | [LiteLLM](https://github.com/BerriAI/litellm) | provider routing, retries, cost metering | Per-role models resolve via `model_for`: `agents.<name>.model` else `provider.model` (T-049/T-050) |
| 15 | Config | [pydantic-settings](https://github.com/pydantic/pydantic-settings) | YAML + env loading, validation | `$VAR` indirection via the credential vault (Part 8) |

---

## Part 3 — Tool Schema (frozen)

One Protocol. Every tool — core, community, or MCP-bridged — implements it.

```python
from typing import Protocol, Any, runtime_checkable

@runtime_checkable
class Tool(Protocol):
    name: str            # unique, dotted, lowercase: "file.edit", "bash", "http.get"
    description: str     # one paragraph, shown to the model
    version: str         # semver of the tool contract
    danger: str          # "safe" | "sandboxed" | "escalate"

    def schema(self) -> dict:
        """JSON Schema of execute() args, auto-generated from type hints."""

    def execute(self, args: dict) -> dict:
        """Returns {"ok": bool, "result": Any, "error": str | None}.
        Never raises — failures are values. Sandbox violations are ok=False."""
```

**JSON Schema auto-generation.** Implementations write plain typed Python:

```python
class FileEdit:
    name = "file.edit"
    description = "Replace an exact string in a file."
    version = "1.0.0"
    danger = "sandboxed"

    def execute(self, args: FileEditArgs) -> dict: ...
```

At registration, the registry builds the argument model with `pydantic.TypeAdapter` and derives the JSON Schema from the `execute` hints. Hand-written JSON Schema is rejected at registration — the schema always matches the code.

**Registry file format.** Built-in tools are declared in `src/arcen/tools/registry.toml`:

```toml
[[tool]]
name = "bash"
module = "arcen.tools.bash"
class = "BashTool"
danger = "sandboxed"

[[tool]]
name = "file.read"
module = "arcen.tools.file"
class = "FileRead"
danger = "safe"
```

The registry validates: unique names, no shadowing of MCP tool namespaces (`mcp.<server>.<tool>`), schema generation succeeds, and the class satisfies the Protocol (`isinstance(x, Tool)` via `runtime_checkable`). v0.1 ships 40 core tools.

---

## Part 4 — Config File

`~/.arcen/config.yaml`. Full example (v0.1.4 scalar provider — T-049/T-050;
legacy dict-shape files migrate once on load):

```yaml
provider:
  name: custom               # custom | groq | deepseek | openai | anthropic | ollama
  base_url: https://inference.dahl.global/v1   # OpenAI-compatible endpoint (custom/ollama)
  api_key: $DAHL_API_KEY     # literal (file is chmod 600) or $VAR vault reference
  model: deepseek-ai/DeepSeek-V4-Flash-0731    # the model for all agents
  max_retries: 3             # v0.1.6: transient-failure retries (429/500/502/503 only)
  retry_backoff_seconds: 1.0 # v0.1.6: exponential base → 1s, 2s, 4s

agents:
  draft:
    max_steps: 40
    replan_on_fail: true
    model: null              # null → inherit provider.model
  forge:
    step_timeout_s: 120
    max_retries: 2
    model: null              # null → inherit provider.model
  temper:
    adversarial: true
    reruns: 1
    model: null              # an explicit value overrides just this agent

subagents:
  max_depth: 2
  max_concurrent: 8
  default_model: null        # null → inherit provider.model

skills:
  paths: ["~/.arcen/skills", "./skills"]

mcps:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
    state: declarative
  - name: github
    transport: http
    url: https://api.githubcopilot.com/mcp/
    state: connected
    headers:
      Authorization: Bearer $GITHUB_PAT

plugins:
  enabled: ["redact-secrets", "cost-guard"]
  paths: ["~/.arcen/plugins"]

sandbox:
  image: ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0
  mem_limit: 2g
  cpus: 2.0
  network: none              # tools opt in to network explicitly

stream:
  port: 3002
  content_type: application/x-ndjson

session:
  dir: ~/.arcen/sessions

memory:
  db: ~/.arcen/memory.db
  decay_half_life_days: 14
```

Rules:

1. **Secrets use `$VAR`.** Any value matching `^\$[A-Z_]+$` is resolved from the process environment by the credential vault (Part 8) at boot. Literal secrets in the config file are a spec violation.
2. **Every value has an API equivalent.** Anything readable in the YAML is exposed via `GET /api/config` and mutable via `PUT /api/config` — the file is never the only interface. Secret values are never returned by the API, only their variable names.

### Env seeding on boot (v0.1.5, T-055)

The server/UI can be pointed at a model entirely from the environment. Four
variables seed EMPTY provider slots at boot:

| config slot       | env var                  |
|-------------------|--------------------------|
| `provider.name`   | `ARCEN_MODEL_PROVIDER`   |
| `provider.base_url` | `ARCEN_MODEL_BASE_URL` |
| `provider.api_key`  | `ARCEN_MODEL_API_KEY`  |
| `provider.model`    | `ARCEN_MODEL_NAME`     |

Precedence: **a non-empty config value always wins; an env var only fills an
empty slot; an unset env var leaves the slot empty** (the user fills it in
Settings). `provider.name` falls back to `custom` — what the UI already
displays — but that default is not an env contribution and never triggers a
write. When at least one env var actually filled a slot, the merged config is
written to `~/.arcen/config.yaml` **once** (chmod 600, same as Settings →
Save) so the seeding survives restarts, and boot logs exactly one line:

```
[config] seeded from env: provider=custom model=deepseek-ai/DeepSeek-V4-Flash-0731 base_url=https://inference.dahl.global/v1 api_key=dahl_...a71b
```

The `api_key` is masked `first4...last4` (`mask_secret`); values of eight
characters or fewer are masked entirely; it is never logged in full. A boot
where the config already has every slot filled writes nothing and logs
nothing — the file, not the environment, is the source of truth after the
first seeded boot.

### LLM retry policy (v0.1.6)

The provider block owns ONE retry policy. LiteLLM's internal retry loop and
the provider SDK's own retry loop are both DISABLED (`num_retries=0`,
`max_retries=0` on every `litellm.completion` call) — stacked retriers with
independent 10-second backoffs were what hung the UI for minutes while the
stream sat silent (`Retrying request to /chat/completions in 10.0s` ×5+).
ARCEN retries instead, in one place (`llm/client.py`):

| failure class | policy |
|---------------|--------|
| HTTP 400 / 401 / 403 / 404 | **fail immediately** — the request itself is wrong; a second identical call cannot succeed |
| HTTP 429 / 500 / 502 / 503 | retry up to `provider.max_retries` (default 3), exponential backoff `provider.retry_backoff_seconds` × 2^k → **1s, 2s, 4s** |
| connection error (never reached the provider) | treated as transient — same retry budget as 5xx |
| timeout | the call is CANCELLED and reported at `provider` timeout (default **60s** per call, spec'd) — a call that already burned its whole budget is never re-burned |

The FIRST failure's status + response-body excerpt is recorded; when the
last attempt dies, the turn ends with a `run.error` event carrying the wire
format **`provider error: <status> <brief message>`** (e.g. `provider error:
401 invalid api key`) — the stream closes cleanly and the UI's spinner ends
with the cause on screen. `ProviderError` is never swallowed into offline
fallbacks: DRAFT's classifier, DIRECT replies, and the planner all re-raise
it. The Test-Connection probe (`POST /api/config/test`) is a single call —
no retries — and answers with the fix-it-shaped message (e.g. `provider
error: 401 unauthorized — check your API key`) within seconds.

### Sandbox backends (T-043)

> Note: the v0.1.2 ticket pointed at "Part 8 (sandbox)"; Part 8 is the
> Credential Vault, and the sandbox lives here in the Part 4 config —
> this subsection is the sandbox part of the spec.

The sandbox has THREE backend states, configured via `sandbox.backend`
(default `auto`; Settings → Sandbox or `PUT /api/config`):

| backend | docker daemon present | docker daemon absent |
|---|---|---|
| `auto` (default) | docker backend (image pulled on first use if absent); **green** "docker ready" chip in Settings | quarantined **process** backend, degraded; **amber** chip "running in process mode — docker not available" |
| `docker` (forced) | docker backend, real isolation; green chip | runs are **REFUSED** at `/api/run` (HTTP 409) with: *"Sandbox backend is set to docker, but no docker daemon is reachable. Either start docker or change the backend in Settings → Sandbox."* — **red** chip "docker daemon not detected — running tasks will fail". Never a silent fallback to process. |
| `process` (forced) | quarantined process backend anyway; amber chip "docker bypassed by config" | quarantined process backend; amber chip |

**To force docker-only** (no silent degrade, for machines where real
isolation is mandatory): set `sandbox.backend: docker`. The runtime
raises `SandboxBackendError` and the server refuses runs before planning
while the daemon is unreachable — misconfiguration is an error, not a
degrade.

**Why process mode is degraded but functional:** without a daemon there
is no container boundary, so commands run in a per-session quarantine
root with a scrubbed environment; file-tool paths are resolved against
the root and escapes are refused. This is confinement, not isolation —
the runtime reports `degraded=True`, the boot log and Settings say so,
and nothing ever overclaims docker-grade isolation.

**Visibility (the docker-less machine is explicit, not silent):** boot
logs the detected state verbatim —

```
[sandbox] docker daemon: <present|absent>
[sandbox] image <name>: <present|absent>
[sandbox] backend selected: <docker|process>
[sandbox] reason: <why this backend was chosen>
```

and `GET /api/sandbox/status` returns the same picture
(`docker_available`, `image_present`, `image`, `backend`, `effective`,
`reason`, `degraded`) for the Settings → SANDBOX panel, which renders
the three lines plus the health chip. A docker-pinned refusal never
creates a session, never plans, and never reaches FORGE.

---

## Part 5 — Memory

Single SQLite file: `~/.arcen/memory.db`. WAL mode. All state — entities, relations, facts, usage counters — lives in that one file so backup is `cp`.

Memory is a graph, not a log: entities are nodes (`calc()`, `tests/test_pay.py`, `anthropic`), facts are typed edges with timestamps. DRAFT recalls before planning; TEMPER records verified outcomes; every turn writes what it learned.

**The five GraphMem innovations** (pulled from the graph-memory work in Letta + Graphiti, reduced to SQLite):

| # | Innovation | What it does | Example |
|---|---|---|---|
| 1 | **Decay** | Facts carry a half-life (default 14 days). Unaccessed facts lose weight; weight below threshold → archived, not deleted. | "deploy script is `scripts/deploy.sh`" fades if unused for months |
| 2 | **Consolidation** | Repetited observations merge into one stronger fact with a source list. Ten "tests are slow" observations become one fact, ten sources. | avoids unbounded growth from repeated turns |
| 3 | **Conflict resolution** | A new fact that contradicts an existing one supersedes it; the old fact is kept as history with an `invalid_at` timestamp, never silently overwritten. | "port is 3002" then "port is 3003" → both kept, latter valid |
| 4 | **Temporal validity** | Every fact is queryable "as of" a time. Recall defaults to now, but TEMPER can ask what was believed when a bug was introduced. | `recall(entity, as_of=ts)` |
| 5 | **Prioritization** | Recall ranks by weight × recency × graph centrality, capped at k results, so prompts stay small. | memory budget is prompt tokens |

**MCP integration:** memory is exposed as a first-class MCP server (`arcen memory`) with tools `memory.recall`, `memory.write`, `memory.forget` — so any external MCP client (the UI, another agent, a script) reads and writes the same graph.

---

## Part 6 — MCP State Machine

Each configured MCP server is always in exactly one of three states:

| State | Meaning | Tool visibility | Network I/O |
|---|---|---|---|
| `connected` | Handshake done; tools listed and callable | Live, callable | done at first use |
| `declarative` | Declared in config, not yet contacted | Advertised from config schema; calls trigger lazy connect | deferred |
| `disabled` | Present in config, ignored | None | none |

**Lazy connection rule:** no MCP network I/O happens at boot — ever. Boot lists servers, applies `disabled`, and leaves the rest `declarative`. A `declarative` server transitions to `connected` on its first tool call (or an explicit `arcen mcp connect <name>`). If the handshake fails, the server falls to `declarative` with an error event, and the calling step fails normally — boot never blocks on MCP.

```
              first call / explicit connect          handshake ok
  declarative ───────────────────────▶ connecting ────────────▶ connected
      ▲                                      │                      │
      │              handshake fail          │    arcen mcp disable │
      └──────────────────────────────────────┘                      ▼
                                                                 disabled
```

---

## Part 7 — Plugin Lifecycle

Plugins are Python modules exposing a `Plugin` subclass with decorated hooks. Hooks are synchronous by default; a hook may declare `async def` and the loader runs it on the loop. A hook that raises is a plugin bug: the error is emitted as an event and the pipeline continues without that plugin (fail-open), except `before_tool` which fails-closed for safety hooks.

**Frozen hook list (6):**

| Hook | Fires | May do |
|---|---|---|
| `on_boot` | Once, after config + registry, before server listens | mutate config, register tools, warm caches |
| `before_tool` | Before each tool `execute()` | inspect/mutate args, deny (fail-closed) |
| `after_tool` | After each tool result | inspect/mutate result (redaction), meter |
| `on_spawn` | When a sub-agent is spawned | rename, re-scope, deny depth violations |
| `on_error` | On any step error | capture, alert, request re-plan |
| `on_shutdown` | On graceful shutdown | flush, close connections |

```python
from arcen.plugins import Plugin, hook

class CostGuard(Plugin):
    name = "cost-guard"

    def __init__(self):
        self.spent_usd = 0.0

    @hook("on_boot")
    def setup(self, config: dict) -> None:
        self.limit = config.get("plugins", {}).get("cost_guard", {}).get("limit_usd", 5.0)

    @hook("after_tool")
    def meter(self, event: dict) -> dict:
        self.spent_usd += event.get("usage", {}).get("cost_usd", 0.0)
        if self.spent_usd > self.limit:
            raise BudgetExceeded(self.spent_usd)
        return event

    @hook("on_error")
    def alert(self, error: dict) -> None:
        print(f"[cost-guard] error observed: {error.get('code')}")
```

---

## Part 8 — Credential Vault

> (Note: earlier tickets sometimes referred to Part 8 as 'sandbox' — the
> sandbox lives in Part 4. Part 8 is the credential vault.)

ARCEN runs untrusted code, streams everything to disk, and replays sessions. A literal secret that reaches a session file is a leaked credential. The vault makes that impossible by construction:

1. **Reference.** Config, tool args, and prompts refer to secrets only by `$VAR` name. The vault compiles the set of referenced names at boot.
2. **Resolve.** At boot, each `$VAR` is resolved from the process environment. Missing vars do not abort boot — the dependent provider/server is marked degraded and a warning event is emitted.
3. **Inject.** Resolved values live only in process memory and are injected into provider clients (LiteLLM, MCP headers) at call time. They never pass through the event pipeline.
4. **Redact.** The stream and session writer store names, never values; the shipped `redact-secrets` plugin scrubs tool results with value-shaped patterns (`sk-…`, `ghp_…`, `Bearer …`) as defense-in-depth against a secret entering via tool output.

Why it matters: sessions are stored as plain jsonl, streamed over HTTP, and replayed in the UI. Any of those surfaces would leak a literal. With the vault, a full session dump is safe to share — it contains `$GITHUB_PAT`, never `ghp_…`.

---

## Part 9 — Streaming Protocol

All turn traffic is NDJSON over HTTP:

- `Content-Type: application/x-ndjson`
- One JSON object per line, terminated `\n`; UTF-8; `ts` is Unix epoch seconds (float)
- Endpoint: `GET /api/stream?session=<id>` (live) — `POST /api/run` submits and returns `run_id`
- Every event carries `seq` (monotonic per session) and `ts`

**The 17 event types — frozen.** Adding, removing, or renaming is a breaking change requiring a spec version bump and a UI release in lockstep.

| # | `type` | Producer | Purpose |
|---|---|---|---|
| 1 | `run.start` | DRAFT | turn begins |
| 2 | `think` | DRAFT | narrated reasoning |
| 3 | `plan` | DRAFT | plan emitted |
| 4 | `plan.update` | DRAFT | re-plan / step status change |
| 5 | `spawn` | DRAFT | sub-agent created |
| 6 | `spawn.done` | sub-agent | sub-agent finished |
| 7 | `command` | FORGE | tool call issued |
| 8 | `command.done` | FORGE | tool result returned |
| 9 | `file.diff` | FORGE | file mutation patch |
| 10 | `verify.start` | TEMPER | adversarial check begins |
| 11 | `step.pass` | TEMPER | check passed |
| 12 | `step.fail` | TEMPER | check failed |
| 13 | `answer` | DRAFT | final prose to the user |
| 14 | `memory` | memory | write/recall notice |
| 15 | `usage` | runtime | token/cost meter |
| 16 | `run.done` | runtime | turn complete |
| 17 | `run.error` | runtime | fatal error |

JSON shapes (representative, one line each as they appear on the wire):

```ndjson
{"seq":1,"type":"run.start","run_id":"r-01J9","goal":"fix the failing test","depth":0,"ts":1727500000.000}
{"seq":2,"type":"think","agent":"DRAFT","text":"Read the test first, then the module.","ts":1727500000.104}
{"seq":3,"type":"plan","agent":"DRAFT","steps":[{"id":1,"title":"read failing test","tool":"file.read"}],"ts":1727500000.220}
{"seq":4,"type":"plan.update","agent":"DRAFT","reason":"test bug","steps":[{"id":1,"title":"edit assertion","tool":"file.edit"}],"ts":1727500001.300}
{"seq":5,"type":"spawn","parent":"DRAFT","name":"TEST-READER","task":"extract assertion","depth":1,"ts":1727500000.410}
{"seq":6,"type":"spawn.done","name":"TEST-READER","ok":true,"calls":3,"duration_s":12.4,"ts":1727500012.900}
{"seq":7,"type":"command","agent":"FORGE","step":2,"tool":"bash","args":{"cmd":"pytest -q tests/"},"ts":1727500002.000}
{"seq":8,"type":"command.done","step":2,"ok":true,"result":{"stdout":"12 passed","exit":0},"duration_s":3.2,"ts":1727500005.200}
{"seq":9,"type":"file.diff","path":"tests/test_pay.py","patch":"--- a/tests/test_pay.py\n+++ b/tests/test_pay.py\n@@ -1 +1 @@\n-assert calc(2, 2) == 5\n+assert calc(2, 2) == 4","ts":1727500001.486}
{"seq":10,"type":"verify.start","agent":"TEMPER","target":"tests/","ts":1727500005.500}
{"seq":11,"type":"step.pass","step":3,"checks":["pytest -q tests/  # 12 passed"],"ts":1727500006.000}
{"seq":12,"type":"step.fail","step":3,"reason":"assert 4 == 5","retry":1,"ts":1727500006.000}
{"seq":13,"type":"answer","text":"The test expected 5; calc returns 4. Fixed the assertion. 12 passed.","ts":1727500006.400}
{"seq":14,"type":"memory","op":"write","entity":"calc()","fact":"returns int sum; test_pay had a wrong assertion","ts":1727500006.410}
{"seq":15,"type":"usage","tokens":{"input":18432,"output":1204},"cost_usd":0.021,"ts":1727500006.420}
{"seq":16,"type":"run.done","status":"ok","steps":3,"duration_s":6.5,"ts":1727500006.430}
{"seq":17,"type":"run.error","code":"SANDBOX_UNAVAILABLE","message":"docker daemon not reachable","ts":1727500006.430}
```

**Resume.** The stream is replayable by `seq`. A reconnecting client sends:

```
GET /api/stream?session=s-77 HTTP/1.1
Last-Event-ID: 42
```

and the server resumes from `seq` 43, re-emitting buffered events first, then live. A compacted-away `Last-Event-ID` returns `409` with the oldest available `seq` so the client can re-decide; garbage or future ids replay fresh from the top (never a 400).

**Held streams (v0.1.6).** The stream never rejects a valid session: a malformed id is a client bug → `400`; a valid id that exists nowhere (memory AND disk) — a client-minted uuid before its first `/api/run` — returns **200 and holds**, polling for the session's birth (attach within ~0.25s of the POST), then replays and delivers live until the terminal event, then `stream.done` + close. `{"type":"stream.ping"}` heartbeats every 15s of silence keep proxies from killing the idle hold (the ping is a transport frame, seq-less — invisible to the event store). **There is no 404 on `/api/stream` for valid sessions.**

---

## Part 10 — Boot Sequence

Twelve steps, in order. Each step is observable: boot logs to stderr and, once the server is up, emits boot events on `/api/stream`.

1. **Load config** — read `~/.arcen/config.yaml`, validate with pydantic-settings; missing file → defaults + `CONFIG_DEFAULTED` warning.
2. **Resolve secrets** — the credential vault expands every `$VAR` from the environment; missing vars mark their dependents degraded, never abort boot.
3. **Open session store** — ensure `~/.arcen/sessions/` exists; create the new session's `<id>.jsonl`, append-only.
4. **Open memory** — open `~/.arcen/memory.db` (SQLite, WAL), run migrations if schema version differs.
5. **Load tool registry** — parse `registry.toml`, import tool classes, generate JSON Schemas, validate the Protocol; count must equal expected core tools (40 for v0.1).
6. **Index skills** — walk skill paths, parse each `SKILL.md` frontmatter into the index; bodies stay on disk (progressive loading).
7. **Declare MCPs** — apply state machine: `disabled` stays down, everything else `declarative`; zero network I/O.
8. **Load plugins** — import enabled plugins, validate hook signatures, fire `on_boot`.
9. **Build LLM bridge** — configure LiteLLM with per-role models (agent override → provider.model inheritance) and resolved credentials; probe nothing (first call is the probe).
10. **Warm sub-agent pool** — load sub-agent definitions (names, tool scopes, models); no processes spawned yet.
11. **Start server** — FastAPI on `stream.port` (default 3002); mount `/api/run`, `/api/stream`, `/api/health`, `/api/config`, `/api/sessions`.
12. **Ready** — emit `run.ready` on the boot stream; system accepts work.

Failure rule: steps 1–5 are fatal (exit non-zero with the reason). Steps 6–9 degrade gracefully — the system boots with that capability marked degraded.

---

## Part 11 — Test Plan

| ID | Test | Proves |
|---|---|---|
| T-01 | Config: loads, validates, defaults on missing file, `$VAR` expansion | Part 4 contract |
| T-02 | Events: all 17 types serialize → deserialize → byte-identical; unknown type rejected | Part 9 schema is frozen |
| T-03 | LLM bridge: mocked provider returns completion; per-role model mapping honored | Part 2 #14 |
| T-04 | Registry: 40 tools register; duplicate name and hand-written schema rejected | Part 3 |
| T-05 | Bash tool: `echo hi` in sandbox → `{ok, result: {stdout: "hi\n", exit: 0}}`; host untouched | Part 2 #11 |
| T-06 | File tools: write → read → edit round-trip; content matches byte-for-byte | Part 2 #6 |
| T-07 | DRAFT: goal in → `think` + `plan` events out; failure triggers `plan.update` | Part 1 |
| T-08 | FORGE: executes exactly one step per call; emits `command` + `command.done` | Part 1 |
| T-09 | TEMPER: planted broken code → `step.fail`; clean code → `step.pass` | Part 1 |
| T-10 | Sub-agents: spawn → done; depth cap enforced at max_depth; concurrency capped | Part 1 |
| T-11 | Stream: 17 event types over HTTP in order; `Last-Event-ID` resume re-emits from seq | Part 9 |
| T-12 | E2E: full turn (goal → plan → steps → verify → answer → done) through the server | everything wired |

**Flakiness rule:** every test must pass **3× back-to-back** (`pytest -q && pytest -q && pytest -q`). Two passes and one failure is a failure — no flaky test ships, no `retry=3` in CI, no `sleep()` masking races.

**Mock provider contract (T-044):** the mock provider must always emit
tool args. Bare-label plans hide arg-derivation bugs from the test
suite. `scripts/mock_provider.py` must stay in sync with the real
planner contract — plans carry `cmd` / `path` / `code`, never just step
labels; a regression there means tests pass but live runs fail (the
exact no-args bug T-037 fixed).

---

## Part 12 — Repository Structure

```
arcen/
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md
│   ├── BACKEND-SPEC.md
│   ├── FRONTEND-SPEC.md
│   ├── TICKETS.md
│   └── logo.svg
├── scripts/
│   └── e2e.py
├── src/
│   └── arcen/
│       ├── __init__.py
│       ├── config.py
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── draft.py
│       │   ├── forge.py
│       │   └── temper.py
│       ├── llm/
│       │   ├── __init__.py
│       │   └── client.py
│       ├── memory/
│       │   ├── __init__.py
│       │   ├── store.py
│       │   └── graph.py
│       ├── mcp/
│       │   ├── __init__.py
│       │   └── client.py
│       ├── plugins/
│       │   ├── __init__.py
│       │   └── loader.py
│       ├── sandbox/
│       │   ├── __init__.py
│       │   └── runtime.py
│       ├── server/
│       │   ├── __init__.py
│       │   └── app.py
│       ├── session/
│       │   ├── __init__.py
│       │   └── store.py
│       ├── skills/
│       │   ├── __init__.py
│       │   └── loader.py
│       ├── stream/
│       │   ├── __init__.py
│       │   ├── emitter.py
│       │   └── events.py
│       ├── subagents/
│       │   ├── __init__.py
│       │   └── agent.py
│       └── tools/
│           ├── __init__.py
│           ├── registry.py
│           ├── registry.toml
│           ├── bash.py
│           └── file.py
└── tests/
    ├── conftest.py
    ├── test_draft.py
    ├── test_events.py
    ├── test_forge.py
    ├── test_llm.py
    ├── test_memory.py
    ├── test_mcp.py
    ├── test_plugins.py
    ├── test_registry.py
    ├── test_sandbox.py
    ├── test_server.py
    ├── test_session.py
    ├── test_skills.py
    ├── test_stream.py
    ├── test_subagents.py
    ├── test_temper.py
    └── test_tools.py
```

One module per Part 2 component. `stream/events.py` is the frozen schema; everything imports from it.

---

## Part 13 — README Specification

`README.md` at the repo root follows the 15-section structure defined in this spec's source brief: centered header block (logo, H1, tagline, badges, italic one-liner, quick links), What is ARCEN (3 sentences, problem → solution), Quick Start, Features (12 items), How it Works (ASCII loop + sample stream), Installation (`<details>` blocks: pip, uv, Docker, source), Usage (5 commands), Configuration (YAML), Skills (SKILL.md), Tools (Protocol), MCPs (YAML), Plugins (hook), Contributing, License, and a footer crediting the 12 source repos with links.

The README was written to this structure in the bootstrap commit `docs: add professional README` and renders from this spec. Content rules: no marketing words, problem-first framing, every code block copy-paste runnable, ASCII diagrams only (the logo is the sole image), `<details>` for long sections.

---

## Part 14 — Builder Instructions

The build process, in order. Each step gates the next.

1. **Read the spec** — this document and [FRONTEND-SPEC.md](FRONTEND-SPEC.md) in full. No coding before that.
2. **Read the source repos** — for each Pull Map row, read the named files in the source project. Understand what is being pulled before pulling it.
3. **Write the README** — per Part 13; it is the contract the UI and CLI must match.
4. **Freeze the event schema** — implement `src/arcen/stream/events.py` with all 17 types as dataclasses; tests T-02 must pass before anything else is built on top.
5. **Pull the code** — copy the named source files, adapt imports, keep provenance comments (`# pulled from OpenHands controller/agent.py @ <sha>`).
6. **Wire the agents** — DRAFT → FORGE → TEMPER loop with re-plan on fail; T-07, T-08, T-09 green.
7. **Wire the capability layer** — registry, skills, MCPs, plugins, memory; T-04, T-10 green.
8. **Wire the runtime** — sandbox, server, streaming, sessions; T-05, T-06, T-11, T-12 green.
9. **Run the test plan** — T-01…T-12, 3× back-to-back, zero flakes.
10. **Write the docs** — close tickets in [TICKETS.md](TICKETS.md), update ARCHITECTURE.md, tag `v0.1.0`.

---

## Part 15 — Final Checklist

All 15 must be true before v0.1 ships:

1. All 30 tickets in [TICKETS.md](TICKETS.md) are closed
2. T-01…T-12 pass 3× back-to-back with zero flakes
3. The 17 event types are frozen, versioned, and match FRONTEND-SPEC Part 2 exactly
4. No literal secret appears in the repo, config, sessions, or stream output
5. Every config value has an API equivalent (`GET`/`PUT /api/config`)
6. Sandbox isolation is proven — host filesystem untouched under T-05/T-12
7. Stream resume works via `Last-Event-ID` (T-11)
8. DRAFT re-plans on TEMPER failure (T-07 + T-09 composed)
9. Sub-agent depth cap enforced — no runaway recursion (T-10)
10. Memory: decay, consolidation, conflict resolution, temporal validity, prioritization all exercised in T-series tests
11. `pip install -e .` works from a clean clone; `pytest -q` green
12. README renders correctly: badges, logo, `<details>`, ASCII diagrams, runnable code blocks
13. `docs/` contains all files; no doc references a missing file
14. No marketing words anywhere in docs or UI copy
15. Tag `v0.1.0` pushed; the tag commit is the checklist commit

---

## Part 16 — Verification Loop

The loop that applies to every ticket and every change, with no exceptions:

1. **Make a change** — one logical change per iteration; ticket-scoped.
2. **Run the relevant tests** — the test(s) named by the ticket.
3. **If pass → commit.** If fail → read the error, fix, re-run step 2. No commit on red.
4. **Re-run all tests** (regression check) — `pytest -q` full suite.
5. **If all pass → push.** If any fail → back to step 2. Never push red.

Constraints:

- **Max 5 iterations per ticket.** A ticket still failing after 5 iterations is marked `[!]` blocked with the exact error attached — move on, ask for help, do not thrash.
- Before starting the next ticket, re-run **all** previous ticket tests. A regression stops everything until fixed.
- Commit messages reference the ticket: `T-006: bash tool executes in sandbox`.

```
       ┌──▶ change ──▶ ticket tests ──┐
       │                              │
       │                 pass ──▶ full suite ──┐
       │                                       │
       └──── fix ◀── error ◀── fail            │
                                               │
                              all pass ──▶ commit + push
```


