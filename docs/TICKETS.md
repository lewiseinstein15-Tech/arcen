# ARCEN — Build Order Tickets

> Status tracking for v0.1. One ticket at a time, in ID order (dependencies permitting).
> Specs: [BACKEND-SPEC.md](BACKEND-SPEC.md) · [FRONTEND-SPEC.md](FRONTEND-SPEC.md)

**Status markers** (update as you go):

| Marker | Meaning |
|---|---|
| `[&nbsp;]` | todo |
| `[~]` | in progress |
| `[x]` | done — verified |
| `[!]` | blocked — needs help |
| `[-]` | skipped — justified |

**Verification loop (applies to every ticket):**

1. Write the code.
2. Run the test command from the ticket.
3. If output matches "Verification" → mark done — verified, git commit.
4. If output does NOT match → read the error, fix the code, re-run step 2.
5. Max 5 iterations per ticket.
6. If still failing after 5 → mark blocked with the exact error attached.
7. Before starting the next ticket, re-run ALL previous ticket tests (regression check). If any regress, stop and fix first.

Commit messages reference the ticket: `T-006: bash tool executes in sandbox`.

---

### [T-001] Repository bootstrap
- **Status:** [x] done — verified
- **Depends on:** none
- **Deliverable:** repo cloned, src/ and tests/ exist, pyproject.toml
- **Test:** `python -m pytest --collect-only` runs without error
- **Command:** `mkdir -p src/arcen tests && touch pyproject.toml`
- **Verification:** directories exist, pyproject.toml is valid TOML

### [T-002] Design tokens (frontend)
- **Status:** [x] done — verified
- **Depends on:** T-001
- **Deliverable:** src/styles/tokens.css with all CSS variables from frontend spec Part 3.1
- **Test:** `npm run build` succeeds
- **Command:** `cat src/styles/tokens.css`
- **Verification:** 20+ CSS variables present

### [T-003] Event schema (backend)
- **Status:** [x] done — verified
- **Depends on:** T-001
- **Deliverable:** src/arcen/stream/events.py with all 17 event types as dataclasses
- **Test:** `pytest tests/test_events.py`
- **Command:** `python -c "from arcen.stream.events import *; print('ok')"`
- **Verification:** all 17 types importable

### [T-004] LLM bridge
- **Status:** [x] done — verified
- **Depends on:** T-003
- **Deliverable:** src/arcen/llm/client.py wrapping LiteLLM
- **Test:** `pytest tests/test_llm.py` (mocked)
- **Command:** `python -c "from arcen.llm.client import Client"`
- **Verification:** class imports, identity block present

### [T-005] Tool schema + registry
- **Status:** [x] done — verified
- **Depends on:** T-003
- **Deliverable:** src/arcen/tools/registry.py with Tool Protocol
- **Test:** `pytest tests/test_registry.py`
- **Command:** `python -c "from arcen.tools.registry import Tool, Registry"`
- **Verification:** 40 tools registered

### [T-006] Bash tool
- **Status:** [x] done — verified
- **Depends on:** T-005
- **Deliverable:** src/arcen/tools/bash.py
- **Test:** `pytest tests/test_tools.py::test_bash`
- **Command:** `python -c "from arcen.tools.bash import BashTool; BashTool().execute({'cmd':'echo hi'})"`
- **Verification:** returns {ok: True, result: {stdout: 'hi\n', exit: 0}}

### [T-007] File tools (read, write, edit)
- **Status:** [x] done — verified
- **Depends on:** T-005
- **Deliverable:** src/arcen/tools/file.py
- **Test:** `pytest tests/test_tools.py::test_file`
- **Command:** round-trip write + read
- **Verification:** content matches

### [T-008] DRAFT planner
- **Status:** [x] done — verified
- **Depends on:** T-004, T-006
- **Deliverable:** src/arcen/agents/draft.py
- **Test:** `pytest tests/test_draft.py`
- **Command:** `python -m arcen.agents.draft "hello"`
- **Verification:** emits think + plan events

### [T-009] FORGE executor
- **Status:** [x] done — verified
- **Depends on:** T-008
- **Deliverable:** src/arcen/agents/forge.py
- **Test:** `pytest tests/test_forge.py`
- **Command:** `python -m arcen.agents.forge`
- **Verification:** executes one step, emits command + command.done

### [T-010] TEMPER verifier
- **Status:** [x] done — verified
- **Depends on:** T-009
- **Deliverable:** src/arcen/agents/temper.py
- **Test:** `pytest tests/test_temper.py`
- **Command:** `python -m arcen.agents.temper`
- **Verification:** adversarial check works, emits step.fail on bad work

### [T-011] Sub-agent spawner
- **Status:** [x] done — verified
- **Depends on:** T-010
- **Deliverable:** src/arcen/subagents/agent.py
- **Test:** `pytest tests/test_subagents.py`
- **Command:** spawn RESEARCH, wait for done
- **Verification:** {ok, calls, duration} returned, depth cap enforced

### [T-012] Sandbox runtime
- **Status:** [x] done — verified
- **Depends on:** T-006
- **Deliverable:** src/arcen/sandbox/runtime.py
- **Test:** `pytest tests/test_sandbox.py`
- **Command:** run bash in container, verify host untouched
- **Verification:** isolation proven
- **Note:** Fixed environment mismatch — falls back to process when docker image missing (daemon alone no longer selects the docker backend; missing image → one trusted auto-pull attempt, then quarantined process backend with `degraded=true`; image shipped via `docker/sandbox/Dockerfile` + GHCR workflow)

### [T-013] NDJSON streaming emitter
- **Status:** [x] done — verified
- **Depends on:** T-003
- **Deliverable:** src/arcen/stream/emitter.py
- **Test:** `pytest tests/test_stream.py`
- **Command:** curl /api/stream, count lines
- **Verification:** 17 event types emit correctly

### [T-014] FastAPI server
- **Status:** [x] done — verified
- **Depends on:** T-013
- **Deliverable:** src/arcen/server/app.py
- **Test:** `pytest tests/test_server.py`
- **Command:** `uvicorn arcen.server.app:app --port 3002`
- **Verification:** /api/health returns 200

### [T-015] Session store
- **Status:** [x] done — verified
- **Depends on:** T-013
- **Deliverable:** src/arcen/session/store.py
- **Test:** `pytest tests/test_session.py`
- **Command:** write event, read back
- **Verification:** jsonl format correct

### [T-016] Memory store
- **Status:** [x] done — verified
- **Depends on:** T-001
- **Deliverable:** src/arcen/memory/store.py + graph.py
- **Test:** `pytest tests/test_memory.py`
- **Command:** store fact, recall it
- **Verification:** decay + consolidation work

### [T-017] Skills loader
- **Status:** [x] done — verified
- **Depends on:** T-001
- **Deliverable:** src/arcen/skills/loader.py
- **Test:** `pytest tests/test_skills.py`
- **Command:** load a SKILL.md
- **Verification:** parsed correctly

### [T-018] MCP client
- **Status:** [x] done — verified
- **Depends on:** T-005
- **Deliverable:** src/arcen/mcp/client.py
- **Test:** `pytest tests/test_mcp.py`
- **Command:** connect to a test MCP server
- **Verification:** tools listed, callable
- **Note:** MCP tests now hermetic — no npx/uvx dependency (test server is stdlib-only JSON-RPC over stdio, spawned via `sys.executable`; MCP Python SDK promoted to core dependency)

### [T-019] Plugin loader
- **Status:** [x] done — verified
- **Depends on:** T-014
- **Deliverable:** src/arcen/plugins/loader.py
- **Test:** `pytest tests/test_plugins.py`
- **Command:** register a hook, trigger it
- **Verification:** hook fires

### [T-020] End-to-end integration
- **Status:** [x] done — verified
- **Depends on:** T-001 through T-019
- **Deliverable:** full pipeline works
- **Test:** `python scripts/e2e.py`
- **Command:** run a complete build task
- **Verification:** all 12 tests pass 3× back-to-back

### [T-021] Frontend bootstrap
- **Status:** [x] done — verified
- **Depends on:** T-001
- **Deliverable:** Vite project + tokens.css + App.tsx
- **Test:** `npm run dev` starts
- **Command:** open localhost:5173
- **Verification:** page renders

### [T-022] Stream reader + event renderer
- **Status:** [x] done — verified
- **Depends on:** T-021, T-013
- **Deliverable:** src/stream/reader.ts + all 17 event components
- **Test:** F-04
- **Command:** mock NDJSON stream
- **Verification:** all event types render

### [T-023] Panel state machine
- **Status:** [x] done — verified
- **Depends on:** T-022
- **Deliverable:** src/state/panelStore.ts
- **Test:** F-05
- **Command:** click chevrons
- **Verification:** state toggles

### [T-024] Auto-scroll + pill
- **Status:** [x] done — verified
- **Depends on:** T-022
- **Deliverable:** src/stream/useAutoScroll.ts + ScrollPill.tsx
- **Test:** F-06, F-07, F-08
- **Command:** simulate long stream
- **Verification:** pinning works both ways

### [T-025] Markdown / math / code / mermaid
- **Status:** [x] done — verified
- **Depends on:** T-022
- **Deliverable:** src/markdown/*
- **Test:** F-09
- **Command:** render test answer
- **Verification:** all render

### [T-026] Composer + keyboard
- **Status:** [x] done — verified
- **Depends on:** T-021
- **Deliverable:** src/components/Composer.tsx
- **Test:** F-10
- **Command:** press Enter, Shift+Enter
- **Verification:** send / newline

### [T-027] Session store + persistence
- **Status:** [x] done — verified
- **Depends on:** T-022
- **Deliverable:** src/state/sessionStore.ts + localStorage
- **Test:** F-12
- **Command:** reload page
- **Verification:** session replays

### [T-028] Mobile drawer
- **Status:** [x] done — verified
- **Depends on:** T-021
- **Deliverable:** src/components/Drawer.tsx
- **Test:** F-11
- **Command:** open on 375px viewport
- **Verification:** drawer slides, sessions list

### [T-029] Full E2E (backend + frontend)
- **Status:** [x] done — verified
- **Depends on:** T-020, T-028
- **Deliverable:** complete working system
- **Test:** all F-01 through F-12 × 3
- **Command:** `npm run test:e2e`
- **Verification:** 12/12 pass 3× back-to-back

### [T-030] Documentation complete
- **Status:** [x] done — verified
- **Depends on:** all tickets
- **Deliverable:** README + all docs/ files
- **Test:** `ls docs/`
- **Command:** verify all 6 docs exist
- **Verification:** no missing files

---

## v0.1 release blockers (laptop-tested, real API key)

### [T-031] Intent classifier (CRITICAL)
- **Status:** [x] done — verified
- **Note:** classify_intent (LLM-first, heuristic fallback) + provider bridge (llm/bridge.py) + server wiring; live-verified 10/10 via mock provider — "2+2"→"4" direct, name→ARCEN, closures prose, calculator/search route to plans. Test fixture made hermetic while re-verifying.
- **Depends on:** T-008
- **Deliverable:** `classify_intent(text)` in src/arcen/agents/draft.py — LLM-driven routing into DIRECT / RESEARCH / CODE (UNKNOWN falls through to CODE); DIRECT skips the plan and answers with the ARCEN identity; server wires a real LLM client built from config
- **Test:** `pytest tests/test_draft.py` — classifier matrix (hello/hi/2+2/what is 2+2?/what is your name/who built you?/explain closures → DIRECT; weather/search → RESEARCH; calculator/list files/python script → CODE)
- **Verification:** live — "2+2" answers "4" directly; "what is your name" answers as ARCEN; "explain closures" answers in prose; "build a calculator" still plans; "search for ai news" plans web search
- **Evidence:** "2+2" was planned as a bash task and failed (`bash: 2+2: command not found`); same for "what is you name"

### [T-032] Live streaming visibility
- **Status:** [x] done — verified
- **Note:** optimistic user pill + DRAFT skeleton appear <50ms after Send; store inserts seq-ordered (gap-safe, no out-of-order render); generating indicator names DRAFT/FORGE/TEMPER and disappears on completion. Live 7/7 (mock provider, chromium).
- **Depends on:** T-022, T-027
- **Deliverable:** optimistic user pill + "◆ DRAFT" skeleton block on send; events stream into it in seq order; "generating" indicator (pulse dot + "DRAFT is thinking…" / "FORGE is working…") near the composer; out-of-order events wait for the gap
- **Test:** `npx vitest run` — optimistic pill + skeleton + indicator tests
- **Verification:** live — pressing Send shows the message and skeleton immediately, thinking/plan/answer stream into place, indicator disappears on turn completion
- **Evidence:** user quote — "i cant see when is thinking when i sent the question i have to find where it is"

### [T-033] Turn order (new turns at bottom)
- **Status:** [~] in progress
- **Depends on:** T-027
- **Deliverable:** strictly chronological stream — session replay loads ascending seq, new events append to the end, defensive seq-sort on hydrate, no unshift/reverse anywhere
- **Test:** `npx vitest run` — 3-turn chronological order test
- **Verification:** live — send 3 messages; turns 1, 2, 3 stack top→bottom, newest at the bottom
- **Evidence:** user quote — "it should not go on the top"

### [T-034] Auto-scroll (make it actually work)
- **Status:** [ ] todo
- **Depends on:** T-024
- **Deliverable:** useAutoScroll + ScrollPill actually mounted in ChatView — smooth follow while pinned (≤100px from bottom), no yank while browsing, floating "↓ jump to latest" pill when scrolled up, click → smooth scroll + re-pin
- **Test:** `npx vitest run` — hook + pill behavior tests
- **Verification:** live — long task streams with the newest block always visible; scroll up mid-stream shows the pill; click snaps to bottom; manual return to bottom resumes pinning
- **Evidence:** user quote — "the auto scroll is not ther" (hook + pill existed but were never mounted)

### [T-035] "+ New chat" button
- **Status:** [ ] todo
- **Depends on:** T-021
- **Deliverable:** "+ New chat" button below the logo block in the sidebar (plus icon in coral, 40px, hairline coral border) + compact "+" in the top bar; click → save current session to history, fresh session id, clear stream, focus composer; no-op when the current session has 0 messages
- **Test:** `npx vitest run` — new-chat behavior tests
- **Verification:** live — click creates a clean slate; previous session remains in the sessions drawer; composer focused
- **Evidence:** reference image requires the button; user asked for it

### [T-036] Settings view with model providers
- **Status:** [ ] todo
- **Depends on:** T-014, T-004
- **Deliverable:** SettingsView (PROVIDER / AGENTS / SANDBOX / GENERAL sections) reachable from the sidebar; backend GET/PUT /api/config persisting to ~/.arcen/config.yaml + POST /api/config/test provider probe; PUT reloads the provider bridge in-memory
- **Test:** `pytest tests/test_server.py` (config round-trip, masked keys, test endpoint mocked) + `npx vitest run`
- **Verification:** live — open Settings, configure the custom provider, Test Connection shows green, Save, "hello" answers through the new provider
- **Evidence:** user quote — "in settings it should have place for model providers you can set from there"

