# ARCEN — Architecture Diagrams (Mermaid)

> Companion to [`ARCHITECTURE.md`](ARCHITECTURE.md). These diagrams render natively on GitHub and inside ARCEN's own Markdown view (`ui/src/markdown/Mermaid.tsx`). A dependency-free visual version is in [`architecture-diagram.html`](architecture-diagram.html).

## 1. System & deployment view

```mermaid
flowchart TB
    user(["User goal"])

    subgraph UI["Browser — ARCEN UI · React 19 + Vite · :5173"]
        direction TB
        comp["components: ChatView · Sidebar · Composer · SettingsView · Drawer"]
        stores["state: 8 Zustand stores (session · stream · chatActions · persist)"]
        reader["stream/reader.ts — NDJSON fetch reader"]
        render["events/ — Think · Answer · Spawn · FileDiff render blocks"]
    end

    subgraph API["FastAPI / Uvicorn server · :3002 — src/arcen/server/app.py"]
        direction TB
        routes["REST: /api/health · /api/run · /api/stream · /api/config · /api/sessions · /api/sandbox/status"]
        turn["run_turn() orchestrator"]
        emitter["StreamEmitter — NDJSON, 17 frozen events, Last-Event-ID resume"]
        plugmw["Plugin middleware — before_tool / after_tool"]
    end

    subgraph ENGINE["Agent engine — src/arcen/agents + subagents"]
        draft["DRAFT — planner"]
        forge["FORGE — executor"]
        temper["TEMPER — verifier"]
        suba["Sub-agents · depth ≤ 2 · max 8 concurrent"]
    end

    subgraph CAP["Capability layer — L3"]
        tools["Tools (1k+): bash · file · http · search · code · …"]
        skills["Skills (10k+): SKILL.md progressive loader"]
        mcp["MCP bridge — lazy stdio/http, 3-state machine"]
        plugins["Plugins — 6 lifecycle hooks"]
        memory["Memory graph — SQLite, decay + consolidation"]
    end

    subgraph SBX["Sandbox runtime — src/arcen/sandbox"]
        docker["docker backend — 1 container/session, network off (isolated)"]
        process["process fallback — quarantine root, degraded: true"]
    end

    subgraph DISK["Local persistence — ~/.arcen"]
        cfg["config.yaml (chmod 600, $VAR refs)"]
        db[("memory.db — SQLite")]
        logs["sessions/<id>.jsonl — append-only event log"]
    end

    subgraph EXT["External"]
        llm["LLM providers via LiteLLM — anthropic · openai · groq · deepseek · custom · ollama"]
        mcpsrv["MCP servers (stdio / http)"]
        ghcr["Docker daemon · GHCR sandbox image"]
    end

    user --> UI
    UI -- "POST /api/run · GET /api/stream (x-ndjson)" --> routes
    routes --> turn
    turn --> draft --> forge --> temper
    draft -. spawn .-> suba
    suba -. observations .-> emitter
    temper --> emitter
    turn --> CAP
    forge --> tools
    tools --> SBX
    docker -. unavailable .-> process
    API --> DISK
    llm -. LiteLLM bridge .-> ENGINE
    mcp -. lazy connect .-> mcpsrv
    docker --> ghcr
    emitter -- "seq + ts per line" --> reader
    render --> user
```

## 2. The four-layer architecture

```mermaid
flowchart TB
    subgraph L1["L1 · AGENTS — the only 3 that decide"]
        D["DRAFT · planner (agents/draft.py)"]
        F["FORGE · executor (agents/forge.py)"]
        T["TEMPER · verifier (agents/temper.py)"]
    end
    subgraph L2["L2 · SUB-AGENTS — 500+, spawned on demand, depth cap = 2"]
        S1["TEST-READER"] --- S2["MIGRATOR"] --- S3["…task-named, torn down when done"]
    end
    subgraph L3["L3 · CAPABILITY"]
        SK["skills (10k+)"] --- TL["tools (1k+)"] --- MC["MCPs (300+)"] --- PL["plugins (100+)"] --- MEM["memory: SQLite entity graph"]
    end
    subgraph L4["L4 · RUNTIME"]
        R1["Docker sandbox per session / process fallback"] --- R2["FastAPI · NDJSON stream"] --- R3["session jsonl · config vault"]
    end
    L1 --> L2 --> L3 --> L4
```

## 3. Agent turn loop & event flow

```mermaid
flowchart LR
    goal(["user goal"]) --> draft
    subgraph draftnode["DRAFT — planner"]
        draft["think → plan"]
    end
    draft -- "spawn / spawn.done · depth ≤ 2" --> sub["sub-agents<br/>parallel research & edits"]
    sub -- observations --> draft
    draft -- plan --> forge["FORGE<br/>one tool call at a time<br/>command → command.done · file.diff"]
    forge -- observation --> temper["TEMPER<br/>adversarial verification<br/>verify.start"]
    temper -- "step.pass ✓" --> answer["ANSWER<br/>prose, every claim backed by a step"]
    answer --> done["usage → run.done"]
    temper -- "step.fail ✗" --> replan["plan.update — bounded retry"]
    replan --> draft

    draft -. NDJSON events .-> stream(["StreamEmitter<br/>application/x-ndjson · 17 event types<br/>seq + ts · Last-Event-ID resume"])
    forge -. NDJSON events .-> stream
    temper -. NDJSON events .-> stream
    stream --> disk[("~/.arcen/sessions/&lt;id&gt;.jsonl<br/>append-only")]
```

## 4. Sequence of one streamed turn

```mermaid
sequenceDiagram
    participant UI as React UI (:5173)
    participant API as FastAPI (:3002)
    participant D as DRAFT
    participant F as FORGE
    participant T as TEMPER
    participant SBX as Sandbox

    UI->>API: POST /api/run {goal, session_id}
    API-->>UI: run.start
    D-->>UI: think · plan
    D-->>UI: spawn (sub-agent, depth 1) · spawn.done
    D->>F: planned step
    F->>SBX: tool call (bash / file / http …)
    SBX-->>F: observation
    F-->>UI: command · command.done · file.diff
    F->>T: observation
    T->>SBX: adversarial test rerun
    SBX-->>T: result
    alt pass
        T-->>UI: verify.start · step.pass
        T-->>UI: answer · usage · run.done
    else fail
        T-->>UI: step.fail {reason, retry}
        T->>D: re-plan (plan.update, bounded retries)
    end
    Note over API,SBX: every event is also appended to ~/.arcen/sessions/<id>.jsonl<br/>reconnect with Last-Event-ID: <seq> to replay
```

## 5. Sandbox backend selection

```mermaid
flowchart TB
    start(["session starts"]) --> probe{"docker daemon reachable<br/>AND pinned image local?"}
    probe -- yes --> d["backend = docker<br/>container per session · network none · capped resources"]
    probe -- no --> q{"backend forced<br/>to docker?"}
    q -- yes --> err["SandboxBackendError — never silently overclaim isolation"]
    q -- no --> p["backend = process (degraded: true)<br/>quarantine root /tmp/arcen-s-<id><br/>escapes refused · env scrubbed"]
    d -. create failure mid-session .-> p
```
