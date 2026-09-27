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
- **Status:** [~] in progress
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
- **Status:** [~] in progress
- **Depends on:** T-004, T-006
- **Deliverable:** src/arcen/agents/draft.py
- **Test:** `pytest tests/test_draft.py`
- **Command:** `python -m arcen.agents.draft "hello"`
- **Verification:** emits think + plan events

### [T-009] FORGE executor
- **Status:** [ ] todo
- **Depends on:** T-008
- **Deliverable:** src/arcen/agents/forge.py
- **Test:** `pytest tests/test_forge.py`
- **Command:** `python -m arcen.agents.forge`
- **Verification:** executes one step, emits command + command.done

### [T-010] TEMPER verifier
- **Status:** [ ] todo
- **Depends on:** T-009
- **Deliverable:** src/arcen/agents/temper.py
- **Test:** `pytest tests/test_temper.py`
- **Command:** `python -m arcen.agents.temper`
- **Verification:** adversarial check works, emits step.fail on bad work

### [T-011] Sub-agent spawner
- **Status:** [ ] todo
- **Depends on:** T-010
- **Deliverable:** src/arcen/subagents/agent.py
- **Test:** `pytest tests/test_subagents.py`
- **Command:** spawn RESEARCH, wait for done
- **Verification:** {ok, calls, duration} returned, depth cap enforced

### [T-012] Sandbox runtime
- **Status:** [ ] todo
- **Depends on:** T-006
- **Deliverable:** src/arcen/sandbox/runtime.py
- **Test:** `pytest tests/test_sandbox.py`
- **Command:** run bash in container, verify host untouched
- **Verification:** isolation proven

### [T-013] NDJSON streaming emitter
- **Status:** [ ] todo
- **Depends on:** T-003
- **Deliverable:** src/arcen/stream/emitter.py
- **Test:** `pytest tests/test_stream.py`
- **Command:** curl /api/stream, count lines
- **Verification:** 17 event types emit correctly

### [T-014] FastAPI server
- **Status:** [ ] todo
- **Depends on:** T-013
- **Deliverable:** src/arcen/server/app.py
- **Test:** `pytest tests/test_server.py`
- **Command:** `uvicorn arcen.server.app:app --port 3002`
- **Verification:** /api/health returns 200

### [T-015] Session store
- **Status:** [ ] todo
- **Depends on:** T-013
- **Deliverable:** src/arcen/session/store.py
- **Test:** `pytest tests/test_session.py`
- **Command:** write event, read back
- **Verification:** jsonl format correct

### [T-016] Memory store
- **Status:** [ ] todo
- **Depends on:** T-001
- **Deliverable:** src/arcen/memory/store.py + graph.py
- **Test:** `pytest tests/test_memory.py`
- **Command:** store fact, recall it
- **Verification:** decay + consolidation work

### [T-017] Skills loader
- **Status:** [ ] todo
- **Depends on:** T-001
- **Deliverable:** src/arcen/skills/loader.py
- **Test:** `pytest tests/test_skills.py`
- **Command:** load a SKILL.md
- **Verification:** parsed correctly

### [T-018] MCP client
- **Status:** [ ] todo
- **Depends on:** T-005
- **Deliverable:** src/arcen/mcp/client.py
- **Test:** `pytest tests/test_mcp.py`
- **Command:** connect to a test MCP server
- **Verification:** tools listed, callable

### [T-019] Plugin loader
- **Status:** [ ] todo
- **Depends on:** T-014
- **Deliverable:** src/arcen/plugins/loader.py
- **Test:** `pytest tests/test_plugins.py`
- **Command:** register a hook, trigger it
- **Verification:** hook fires

### [T-020] End-to-end integration
- **Status:** [ ] todo
- **Depends on:** T-001 through T-019
- **Deliverable:** full pipeline works
- **Test:** `python scripts/e2e.py`
- **Command:** run a complete build task
- **Verification:** all 12 tests pass 3× back-to-back

### [T-021] Frontend bootstrap
- **Status:** [ ] todo
- **Depends on:** T-001
- **Deliverable:** Vite project + tokens.css + App.tsx
- **Test:** `npm run dev` starts
- **Command:** open localhost:5173
- **Verification:** page renders

### [T-022] Stream reader + event renderer
- **Status:** [ ] todo
- **Depends on:** T-021, T-013
- **Deliverable:** src/stream/reader.ts + all 17 event components
- **Test:** F-04
- **Command:** mock NDJSON stream
- **Verification:** all event types render

### [T-023] Panel state machine
- **Status:** [ ] todo
- **Depends on:** T-022
- **Deliverable:** src/state/panelStore.ts
- **Test:** F-05
- **Command:** click chevrons
- **Verification:** state toggles

### [T-024] Auto-scroll + pill
- **Status:** [ ] todo
- **Depends on:** T-022
- **Deliverable:** src/stream/useAutoScroll.ts + ScrollPill.tsx
- **Test:** F-06, F-07, F-08
- **Command:** simulate long stream
- **Verification:** pinning works both ways

### [T-025] Markdown / math / code / mermaid
- **Status:** [ ] todo
- **Depends on:** T-022
- **Deliverable:** src/markdown/*
- **Test:** F-09
- **Command:** render test answer
- **Verification:** all render

### [T-026] Composer + keyboard
- **Status:** [ ] todo
- **Depends on:** T-021
- **Deliverable:** src/components/Composer.tsx
- **Test:** F-10
- **Command:** press Enter, Shift+Enter
- **Verification:** send / newline

### [T-027] Session store + persistence
- **Status:** [ ] todo
- **Depends on:** T-022
- **Deliverable:** src/state/sessionStore.ts + localStorage
- **Test:** F-12
- **Command:** reload page
- **Verification:** session replays

### [T-028] Mobile drawer
- **Status:** [ ] todo
- **Depends on:** T-021
- **Deliverable:** src/components/Drawer.tsx
- **Test:** F-11
- **Command:** open on 375px viewport
- **Verification:** drawer slides, sessions list

### [T-029] Full E2E (backend + frontend)
- **Status:** [ ] todo
- **Depends on:** T-020, T-028
- **Deliverable:** complete working system
- **Test:** all F-01 through F-12 × 3
- **Command:** `npm run test:e2e`
- **Verification:** 12/12 pass 3× back-to-back

### [T-030] Documentation complete
- **Status:** [ ] todo
- **Depends on:** all tickets
- **Deliverable:** README + all docs/ files
- **Test:** `ls docs/`
- **Command:** verify all 6 docs exist
- **Verification:** no missing files

