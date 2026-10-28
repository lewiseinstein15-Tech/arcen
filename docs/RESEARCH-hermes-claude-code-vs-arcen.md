# Research: how terminal coding agents run — Hermes Agent & Claude Code vs ARCEN

> ⚠️ Naming correction: the user's "hernes2" actually meant **Google Harness²**,
> not Hermes Agent. The corrected analysis is in
> `RESEARCH-harness2-vs-arcen.md`. This document is retained because its
> Claude Code / terminal-runtime architecture findings still answer the
> separate question "how should a terminal coding agent run."
>
> Date: 2026-10-28 · Scope: research only ("stop here" — no code changes in this pass).
> Sources are listed at the bottom. ARCEN claims were verified against the
> source tree at commit `3d32166`.

## 0. Naming note

"hernes2" maps to **Hermes Agent** by Nous Research
([NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)) —
either the current mainline or its **Workspace V2 / "Mission Control"**
visual layer. Hermes Agent is the open-source Claude Code alternative
(MIT, Python, 60k+ commits, ~175k stars per third-party trackers). A
different product, *Hermes IDE* (hermes-hq), is a desktop console that
runs other vendors' CLIs and is not the subject here.

## 1. The canonical pattern: how a terminal coding agent should run

Claude Code is the reference implementation. Its core is deliberately
trivial — a **single-threaded while-loop** ("the dumb loop"):

```text
assemble context (system prompt + project file + full message history)
  → call model
  → response has tool_calls?
      yes → each call: permission gate → execute → append tool_result → loop
      no  → plain text answer → return control to user
```

Everything that makes it trustworthy lives in the layers *around* that
loop. Six subsystems matter:

1. **Agent loop as a feedback controller, not a pipeline.** A typical
   task runs 5–50 iterations; the model can emit several tool calls per
   turn (read three files, grep, edit — in one burst); execution results
   become the next turn's context. The stop condition is "text-only
   response," not a timer or a fixed step count. Streaming-first: tool
   calls execute mid-stream before the full response finishes.
2. **Permission system as a first-class subsystem.** Sits *between* the
   loop and execution. Five modes (default ask-everything, acceptEdits,
   plan/read-only, bypassPermissions, auto) and a five-step gauntlet per
   call: tool self-check → settings allow/deny globs → sandbox policy →
   active mode → PreToolUse hook overrides. Deny always wins.
3. **Tools as gated actuators.** ~18–26 built-in tools behind one
   interface (Zod-validated schema, permission check, executor, terminal
   renderer). MCP tools enter through the *same* gate — an MCP server is
   never a privileged channel.
4. **Context as a managed resource.** Async compaction pipeline triggers
   at context thresholds; prompt caching reuses stable prefixes.
5. **Sub-agents as bounded context forks.** A child runs its own loop
   with isolated context and returns only a condensed summary
   (~1–2k tokens). Shallow, depth-limited delegation — not a swarm.
6. **One core, many surfaces.** The same loop powers the interactive
   CLI, headless print mode (`claude -p`, for CI/scripts), the Agent SDK,
   and IDE plugins. Plus lifecycle hooks (PreToolUse, PostToolUse, Stop,
   SessionStart/End), session resume/fork, and git-native workflows.

## 2. How Hermes Agent implements it

Hermes follows the same loop philosophy but widens the deployment and
learning surface:

- **One synchronous core, five entry points.** The `AIAgent` class
  (`agent/conversation_loop.py`, `agent/turn_*.py`) serves the CLI,
  messaging gateway, ACP adapter, batch runner, and API server. Data
  flow: `HermesCLI.process_input() → AIAgent.run_conversation() →
  prompt_builder → runtime_provider → API call → tool_calls? →
  model_tools.handle_function_call() → loop → SessionDB`.
- **Terminal backends are pluggable execution environments, not just
  sandboxes.** Seven backends: **local** (host cwd, no isolation),
  **docker** (hardened: `--cap-drop ALL`, `no-new-privileges`,
  pids-limit, size-capped tmpfs, empty env-forward list), **ssh**,
  **Daytona**, **Modal**, **Singularity/Apptainer** (plugin), **Vercel
  Sandbox**. The agent's "terminal" is abstracted, so you can chat from
  Telegram while commands execute in a serverless microVM that
  hibernates when idle.
- **Explicit human approval.** Smart command approval on by default;
  `approvals.mode: manual` asks for every flagged command; separate write
  gates for memory and skills; dangerous-command checker (skipped inside
  containers, where the container itself is the boundary); protected
  path denylist; eight documented security layers. Two CVEs were
  published in Sept 2026 — the security model is real and tested by
  adversarial experience.
- **Learning loop.** Skills are procedural memory the agent authors and
  improves itself; persistent `MEMORY.md` / `USER.md`; a Honcho-based
  user model; GEPA optimization across sessions. This is Hermes's
  differentiator — Claude Code deliberately has no self-improvement.
- **TUI ergonomics.** Multiline input, slash-command autocomplete,
  streaming tool output, interrupt-and-redirect, `--continue` /
  `--resume` / `--fork-session`, isolated git-worktree mode (`-w`),
  profile isolation (`-p`), Ctrl+G external-editor editing.
- **Scale and breadth.** 70+ tools in ~28 toolsets via a self-registering
  registry; 200+ models through one provider abstraction; cron daemon;
  25+ messaging platforms; SQLite + FTS5 session storage.
- **Weaknesses to learn from:** default local backend has zero
  isolation; third-party reviews flag ALLOW-ALL-era defaults; the
  messaging gateway widens the blast radius (a leaked bot token reaches
  a host full of credentials).

## 3. What ARCEN actually does today (verified in source)

| Dimension | ARCEN implementation | Evidence |
|---|---|---|
| Topology | **Client–server.** FastAPI/uvicorn process owns the agent; web UI and the Textual TUI are render-only clients speaking HTTP + NDJSON | `src/arcen/server/app.py`, `src/arcen/tui/` |
| Control model | **Fixed 3-role pipeline, not a free while-loop.** DRAFT classifies intent (DIRECT/CODE/RESEARCH) and emits a plan *once*; FORGE executes strictly one tool step at a time; TEMPER verifies; failure → max 2 replans | `agents/draft.py`, `agents/forge.py`, `agents/temper.py`, `server/app.py:run_turn` |
| Tool calls per turn | Exactly one per FORGE step, strictly sequential — no multi-tool bursts, no re-reading between steps | `ForgeExecutor.execute_step` |
| Human approval | **None.** No permission modes, no allow/deny lists, no per-command prompt. Boundaries are the sandbox and plugin `before_tool` hooks (fail-closed) only | grep finds no approval subsystem; `plugins/` |
| Execution context | Always sandboxed: one Docker container/session (network off, no host binds) or a quarantined process root `/tmp/arcen-s-<id>` with scrubbed env. The user's repo is not visible by default | `sandbox/runtime.py` |
| Sub-agents | **Scaffolded but not wired.** `subagents/agent.py` exists and is unit-tested, but nothing in the turn pipeline imports or spawns it; `spawn`/`spawn.done` events are defined yet never emitted by `run_turn` (DRAFT comment: "spawn hooks left to the sub-agent spawner T-011") | grep of import graph |
| Context management | None for the LLM window — no compaction, no prompt-cache strategy. "Compaction" in the codebase refers only to stream-event buffer trimming | `stream/emitter.py` vs no equivalent in `llm/` |
| Surfaces | Server + browser UI + Textual TUI. **No headless/print mode, no SDK, no CI entry** — the only console scripts are `arcen serve` and `arcen-tui` | `pyproject.toml [project.scripts]` |
| Observability | **Strongest area.** 17 frozen NDJSON event types, monotonic seq, `Last-Event-ID` resume, held-stream semantics, append-only per-session JSONL in Claude Code format | `stream/events.py`, `session/store.py` |
| Memory | SQLite entity graph with decay/consolidation/temporal validity; skills are static `SKILL.md` files (progressively loaded), never self-authored | `memory/`, `skills/` |
| Providers | LiteLLM bridge, 6 provider families, per-agent model override, fail-fast bounded retries | `llm/bridge.py`, `llm/client.py` |
| Steering | Run-level interrupt only (`DELETE /api/run/{id}`, checked between steps). No mid-turn instruction injection | `server/app.py` |
| Sessions | Replay exists (full event history per UUID); no fork, no worktree isolation | `session/store.py`, TUI sidebar |

## 4. The difference map at a glance

| Property | Claude Code | Hermes Agent | ARCEN |
|---|---|---|---|
| Core shape | Free while-loop, model-driven | Synchronous `AIAgent` loop, model-driven | Fixed DRAFT→FORGE→TEMPER pipeline, plan-driven |
| Runs where | In-process, in your repo cwd | In-process; 7 pluggable backends incl. host cwd | Server-side, inside a per-session sandbox only |
| Works on your actual repo | By default | Local/docker/ssh backends | Not without explicitly placing files in the sandbox |
| Human-in-the-loop permissions | 5 modes, 5-layer gauntlet, hooks | Smart approval + manual mode + write gates | **Absent** — sandbox + plugin hooks only |
| Tool calls per turn | Many, parallel bursts | Many via registry | One, sequential |
| Dynamic re-planning | Continuous (every iteration) | Continuous | Capped at 2 replans; plan is otherwise static |
| Sub-agents | Bounded context forks, summaries | Isolated subagent spawning | Schema + module only, **not connected** |
| Context compaction | Yes, async + prompt caching | Yes (compression in core) | No |
| Self-improvement | None | Skills + GEPA + user model | None (static skills) |
| Headless/CI mode | `claude -p`, SDK, Actions | Batch runner, API server, cron, gateway | None (server API is callable but undocumented as a CLI) |
| Channels | Terminal, IDE, web | Terminal + 25 messaging platforms + cron | Terminal TUI + browser, same server |
| Provider lock-in | Anthropic only | 200+ models | 6 families via LiteLLM |
| Event/audit contract | Hooks + jsonl | Callbacks + SQLite/FTS5 | **17 frozen typed events, NDJSON resume contract** (most rigorous) |
| Maturity | Production, closed core | Massive OSS project, CVEs on record | v0.1.x, 357 tests, spec/ticket-driven |

## 5. The honest gap list (what ARCEN would need to feel like Claude Code in a terminal)

In rough priority order, and explicitly *not* implemented in this pass:

1. **Foreground execution context.** Either a host-cwd backend (like
   Hermes `local`, gated behind explicit trust) or workspace
   bind-mounting into the sandbox, so "fix my repo" works from the
   directory the user launched in. Today every command is trapped in
   `/tmp/arcen-s-*`.
2. **A permission subsystem.** Modes (ask/auto/plan/deny-all),
   allow/deny globs per tool, and an interactive approve/deny prompt in
   the TUI fed by a new stream event. Plugin hooks already provide the
   interception point (`HookedRegistry.dispatch`).
3. **Wire the sub-agent layer** (T-011) — or remove the spawn events
   from the frozen 17 until it exists, since the UI/TUI render events the
   server can currently never emit.
4. **A dynamic loop mode.** Let DRAFT re-enter after observations
   instead of freezing a full plan up front; allow FORGE multi-tool
   bursts; add mid-turn steering into the composer.
5. **Headless print mode** (`arcen run "goal" --json`) over the existing
   server API — small effort, unlocks CI/scripting and closes the biggest
   surface gap.
6. **Context compaction** before long sessions hit the model window.
7. **Session fork and git-worktree mode**, slash commands, external
   `$EDITOR` composing — the TUI ergonomics both peers treat as table
   stakes.
8. **Keep and double down on the strengths:** the frozen event contract,
   honest degraded-sandbox reporting, and the clean client/server split
   are genuinely ahead of where Claude Code started.

## Sources

- Hermes Agent repository (structure, README): https://github.com/NousResearch/hermes-agent
- Hermes official architecture doc: https://hermes-agent.nousresearch.com/docs/developer-guide/architecture
- Hermes V2 Mission Control guide: https://aisuccesslabjuliangoldie.com/blog/hermes-agent-mission-control/
- Hermes beginner's guide (memory, channels, install): https://hermesatlas.com/guide/
- Hermes security/backends analysis (8-layer model, CVEs, docker flags): https://safeguard.sh/resources/blog/what-is-hermes-agent-nous-research-self-improving-agent-explained
- Hermes harness overview (AIAgent, backends): https://innfactory.ai/en/ai-harness/hermes-agent/
- Hermes CLI/TUI reference (keybindings, resume, worktrees): https://www.neura.market/ai-agents/resources/guides/hermes-agent-documentation-guide
- Claude Code architecture (5 subsystems, permissions): https://qubytes.substack.com/p/claude-code-architecture-explained
- Claude Code agentic loop & five-step permission gauntlet: https://dev.to/oldeucryptoboi/inside-claude-codes-architecture-the-agentic-loop-that-codes-for-you-cmk
- Anatomy of a Claude Code session (loop pseudocode, sub-agent forks): https://codewithmukesh.com/blog/anatomy-claude-code-session/
- Claude Code six-layer system design: https://medium.com/@milesk_33/the-system-design-of-claude-code-agent-explained-318d17496534
- Head-to-head comparison (Hermes vs Claude Code vs Codex): https://hermes-tutorials.dev/blog/hermes-agent-vs-claude-code-vs-codex-cli-which-open-source-ai-agent-should-you-u/
