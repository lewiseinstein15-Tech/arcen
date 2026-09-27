# ARCEN — Architecture Overview

> One page. Details live in [BACKEND-SPEC.md](BACKEND-SPEC.md) and [FRONTEND-SPEC.md](FRONTEND-SPEC.md). Build order lives in [TICKETS.md](TICKETS.md).

ARCEN = Agentic reasoning + Code + Engineer. An agentic engineer that plans, builds, and verifies — every action narrated on a live stream. The rule: pull from the best open-source projects, edit only what is needed, wire, test. Never invent.

## The 3 agent roles

| Agent | Role | Job |
|---|---|---|
| **DRAFT** | Planner | Opens every turn. Breaks goals into steps, spawns sub-agents, re-plans on failure. |
| **FORGE** | Executor | Runs tools, one step at a time. Returns observations. |
| **TEMPER** | Verifier | Tests adversarially. Reports pass/fail. |

Only 3 core agents exist. Everything else — 500+ of them — is a sub-agent: spawned on demand, named for its task (`TEST-READER`, `MIGRATOR`), depth-capped, torn down when done.

## The 4-layer architecture

```
┌──────────────────────────────────────────────────────┐
│  L1 · AGENTS          DRAFT · FORGE · TEMPER          │   the only 3
├──────────────────────────────────────────────────────┤
│  L2 · SUB-AGENTS      500+, spawned on demand         │   depth cap = 2
├──────────────────────────────────────────────────────┤
│  L3 · CAPABILITY      skills (10k+) · tools (1k+)     │
│                       MCPs (300+) · plugins (100+)   │
│                       memory (entity graph, SQLite)  │
├──────────────────────────────────────────────────────┤
│  L4 · RUNTIME         Docker sandbox per session      │
│                       FastAPI · NDJSON stream        │
│                       session jsonl · config vault   │
└──────────────────────────────────────────────────────┘
```

## Event flow

```
 user goal
     │
     ▼
 ┌─────────┐  think · plan · spawn        ┌──────────────┐
 │  DRAFT  │ ───────────────────────────▶ │  sub-agents  │ (depth ≤ 2)
 └────┬────┘                              └──────┬───────┘
      │ plan                                     │ observations
      ▼                                          │
 ┌─────────┐   command / command.done            │
 │  FORGE  │ ── one tool call at a time          │
 └────┬────┘                                      │
      │ observation                               │
      ▼                                           ▼
 ┌─────────┐   step.pass / step.fail
 │ TEMPER  │ ── adversarial checks
 └────┬────┘
      │
      ├── pass ──▶ answer ──▶ run.done ──▶ user
      └── fail ──▶ back to DRAFT (re-plan)
```

## The stream contract

- **NDJSON over HTTP** — `Content-Type: application/x-ndjson`, one JSON object per line, every event carries `seq` + `ts`.
- **17 frozen event types** — `run.start`, `think`, `plan`, `plan.update`, `spawn`, `spawn.done`, `command`, `command.done`, `file.diff`, `verify.start`, `step.pass`, `step.fail`, `answer`, `memory`, `usage`, `run.done`, `run.error`. Shapes: [BACKEND-SPEC.md](BACKEND-SPEC.md) Part 9. Component map: [FRONTEND-SPEC.md](FRONTEND-SPEC.md) Part 2.
- **Resume** — reconnecting clients send `Last-Event-ID: <seq>` and the server replays from that point.
- **Session persistence** — every event lands append-only in `~/.arcen/sessions/<id>.jsonl` (Claude Code jsonl format), replayable forever.

## Where things live

| Path | Holds |
|---|---|
| `~/.arcen/config.yaml` | providers, agents, sub-agents, MCPs, plugins, sandbox |
| `~/.arcen/memory.db` | entity graph — decay, consolidation, conflicts, temporal validity |
| `~/.arcen/sessions/<id>.jsonl` | one append-only event log per session |

## Source docs

- [BACKEND-SPEC.md](BACKEND-SPEC.md) — pull map, tool schema, config, memory, MCP state machine, plugins, vault, streaming protocol, boot sequence, test plan
- [FRONTEND-SPEC.md](FRONTEND-SPEC.md) — components, render rules, panel machine, auto-scroll, composer, mobile, performance, accessibility
- [TICKETS.md](TICKETS.md) — 30 tickets with the verification loop
