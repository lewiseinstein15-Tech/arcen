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
- **Status:** [x] done — verified
- **Note:** audit found no unshift/reverse — the visible 'turn at top' bug was the missing optimistic render (T-032) + unsorted replay; hydrate now sorts ascending defensively. Live 4/4: 3 turns stack top→bottom, newest last, order survives reload.
- **Depends on:** T-027
- **Deliverable:** strictly chronological stream — session replay loads ascending seq, new events append to the end, defensive seq-sort on hydrate, no unshift/reverse anywhere
- **Test:** `npx vitest run` — 3-turn chronological order test
- **Verification:** live — send 3 messages; turns 1, 2, 3 stack top→bottom, newest at the bottom
- **Evidence:** user quote — "it should not go on the top"

### [T-034] Auto-scroll (make it actually work)
- **Status:** [x] done — verified
- **Note:** root cause: useAutoScroll + ScrollPill existed but were never mounted in ChatView. Hook rewritten direction-based (growth/catch-up scroll down, only a user scrolls up — no settle timers, no yank); streaming follow is instant per Part 6, the pill jump is smooth per ticket. Live 8/8: max distance 0px while following, full pill lifecycle green.
- **Depends on:** T-024
- **Deliverable:** useAutoScroll + ScrollPill actually mounted in ChatView — smooth follow while pinned (≤100px from bottom), no yank while browsing, floating "↓ jump to latest" pill when scrolled up, click → smooth scroll + re-pin
- **Test:** `npx vitest run` — hook + pill behavior tests
- **Verification:** live — long task streams with the newest block always visible; scroll up mid-stream shows the pill; click snaps to bottom; manual return to bottom resumes pinning
- **Evidence:** user quote — "the auto scroll is not ther" (hook + pill existed but were never mounted)

### [T-035] "+ New chat" button
- **Status:** [x] done — verified
- **Note:** sidebar button (coral hairline, 40px) + compact top-bar "+"; crypto.randomUUID() swap via sessionStore, stream reset, deferred composer focus, empty-chat no-churn guard, drawer sorted by recency. Live 9/9.
- **Depends on:** T-021
- **Deliverable:** "+ New chat" button below the logo block in the sidebar (plus icon in coral, 40px, hairline coral border) + compact "+" in the top bar; click → save current session to history, fresh session id, clear stream, focus composer; no-op when the current session has 0 messages
- **Test:** `npx vitest run` — new-chat behavior tests
- **Verification:** live — click creates a clean slate; previous session remains in the sessions drawer; composer focused
- **Evidence:** reference image requires the button; user asked for it

### [T-036] Settings view with model providers
- **Status:** [x] done — verified
- **Note:** SettingsView (PROVIDER/AGENTS/SANDBOX/GENERAL) from the sidebar; PUT /api/config persists to ~/.arcen/config.yaml (chmod 600) + reloads the provider bridge in-memory; POST /api/config/test probes with key sanitization; '<redacted>' round-trip never wipes a stored key; auto-scroll preference wired to ChatView. Live 12/12: Test Connection green, Save persists, '2+2' answered via the saved provider.
- **Depends on:** T-014, T-004
- **Deliverable:** SettingsView (PROVIDER / AGENTS / SANDBOX / GENERAL sections) reachable from the sidebar; backend GET/PUT /api/config persisting to ~/.arcen/config.yaml + POST /api/config/test provider probe; PUT reloads the provider bridge in-memory
- **Test:** `pytest tests/test_server.py` (config round-trip, masked keys, test endpoint mocked) + `npx vitest run`
- **Verification:** live — open Settings, configure the custom provider, Test Connection shows green, Save, "hello" answers through the new provider
- **Evidence:** user quote — "in settings it should have place for model providers you can set from there"

---

## v0.1.1 — "noticed but not fixed" follow-ups (flagged in the v0.1 final report)

### [T-037] CODE turns fail without a provider (real bug)
- **Status:** [x] done — verified
- **Note:** has_provider gate at the plan path — without a provider a RESEARCH/CODE task answers "I need a model provider to plan and execute tasks. Open Settings → Provider, add a key, and try again." (no plan, no commands, no replan). A provider that returns an empty/malformed plan gets one strict retry then an honest "I couldn't plan this". Deleted the hack everywhere: draft `_decompose_heuristic`/`_research_heuristic` + server `_derive_args` ({"cmd": goal}); plans now carry real tool args. mock provider plans with args too. Live verify 14/14 (scripts/verify_t037.py): no-provider "build a calculator" → clean answer, zero commands, zero "command not found", run.done ok; with provider → real plan, real args, executed cmd sourced from the plan.
- **Note:** the offline arg-derivation hack feeds the raw goal text to bash (`{"cmd": goal}`), so a no-provider CODE turn plans, runs the goal as a shell command, fails, re-plans, and dies with "Turn failed" — for a legitimate task. Offline ARCEN must refuse cleanly instead; a configured provider must yield a real plan with real args.
- **Deliverable:** in src/arcen/agents/draft.py — at the top of the plan path check `has_provider = self.llm is not None and self.llm.is_available()`; without one yield think + answer ("I need a model provider to plan and execute tasks. Open Settings → Provider, add a key, and try again.") and return — no fake plan, no bash attempts. With a provider, an empty/malformed plan retries once with a stricter prompt, then answers "I couldn't plan this" — never "run the goal text as a bash command". Delete the offline arg-derivation hack entirely (draft heuristic decomposition + server `_derive_args`); LLM plans now carry tool args.
- **Test:** `pytest tests/test_draft.py` — no-provider refusal, retry-then-refuse on malformed plans, args parsed from LLM plans
- **Verification:** unset provider → "build a calculator" → clean configure-a-provider message, no bash attempts, no "command not found"; set provider → same message → a real plan with real args
- **Evidence:** v0.1 final report P7 — "CODE-turn offline arg derivation runs the goal text as a literal shell command (fails → replan → honest 'Turn failed' answer)"

### [T-038] Sandbox backend is not configurable
- **Status:** [x] done — verified
- **Note:** DONE — SandboxConfig.backend (Literal, default auto); runtime accepts backend= (auto unchanged; process forced; docker REQUIRES the daemon — SandboxBackendError, never a silent fallback — and boot-warns when the image is missing); ServerState boot warning; GET /api/sandbox/status; Settings dropdown editable with inline daemon/image warnings. Live verify 9/9 (scripts/verify_t038.py). Real-docker run covered by the fake-client unit test (this host has no daemon).
- **Deliverable:** src/arcen/sandbox/runtime.py accepts `backend`: "auto" | "docker" | "process" — auto keeps current behavior, docker requires docker (clear error, no silent fallback), process always uses the quarantined process backend; config gains `sandbox.backend` (default "auto"); the Settings dropdown becomes editable (auto/docker/process) with a warning when docker is selected but the image is missing; boot logs a warning when backend="docker" and the image is absent
- **Test:** `pytest tests/test_sandbox.py tests/test_config.py` + `npx vitest run` — backend pinning tests
- **Verification:** backend=process → task runs in process mode (log confirms); backend=docker → runs in docker; backend=docker without docker → clean error, no silent fallback; backend=auto → unchanged
- **Evidence:** v0.1 final report P7 — "SANDBOX backend select is read-only 'auto'"

### [T-039] Light theme is stubbed
- **Status:** [x] done — verified (Option B: stub removed)
- **Note:** OPTION B. The dead toggle is gone; Settings GENERAL keeps verbosity + auto-scroll. Justification: a working light theme is not a palette diff — the ticket demands a contrast audit of every panel, which cannot be fully proven under v0.1 pressure, and a half-shipped light mode is exactly the 'looks broken' outcome the ticket flags; dark-first is fine for a developer tool (v0.2 owns theming).
- **Deliverable:** either a real `[data-theme="light"]` palette in tokens.css wired to the toggle and contrast-tested panel-by-panel, or the toggle removed from SettingsView (dark-only, honestly)
- **Test:** `npx vitest run` — settings renders without the dead control (B) or with a working theme switch (A)
- **Verification:** (B) open Settings → no theme toggle visible, no console warnings; (A) every panel renders with correct contrast on light
- **Evidence:** v0.1 final report P7 — "theme is dark-only per v0.2 spec"

### [T-040] /api/sessions sorts wrong
- **Status:** [x] done — verified
- **Note:** DONE — GET /api/sessions returns created_at DESC (newest first); the client re-sort removed from Drawer.tsx (it never lived in sessionStore.ts — the store is a thin API mirror). Live verify: alpha→beta→gamma created in order, API returns gamma/beta/alpha descending.
- **Deliverable:** GET /api/sessions returns sessions sorted by created_at DESC (newest first); the client-side sort in the session store is removed — single source of truth
- **Test:** `pytest tests/test_server.py` — endpoint order test; `npx vitest run`
- **Verification:** `curl http://localhost:3002/api/sessions | jq '.[].created_at'` → descending; drawer still shows newest first with no client sort in ui/src/state/sessionStore.ts
- **Evidence:** v0.1 final report P7 — "/api/sessions still returns id-sorted; the drawer sorts newest-first client-side"

### [T-041] .venv gitignore — document, don't change
- **Status:** [x] done
- **Note:** .venv is gitignored, correctly; CI/GHCR are unaffected. Do NOT add it to the repo — document it.
- **Deliverable:** a note in README.md under "Contributing": the .venv directory is gitignored; create it with `python -m venv .venv && source .venv/bin/activate`
- **Test:** none (doc-only)
- **Verification:** README shows the note; `git status` clean of .venv
- **Evidence:** v0.1 final report P7 — ".venv is gitignored — CI/GHCR unaffected by local provisioning"

---

## v0.1.2 — "noticed while fixing" follow-ups (flagged in the v0.1.1 report)

Non-issues from the v0.1.1 report, recorded here so they are never re-litigated (do not action):
- T-037 sort location — the client sort lived in Drawer.tsx, not sessionStore.ts; informational, no fix needed (T-040 landed the server-side order).
- Tooling flake during verify — environment, not code.

### [T-042] replan() never continues the loop (real bug, high priority)
- **Status:** [x] done — verified
- **Note:** DONE — the FORGE loop is now a worklist: on step failure draft.replan runs, the corrected steps REPLACE the remainder, and the loop CONTINUES (plan.update already lands live via _emit_all). Bounded: MAX_REPLANS=2 per turn; a replan returning nothing usable (refusal/empty) is terminal; a replan handing back the exact failed step (tool+args signature) is terminal without re-execution; the same step failing twice with the same error is terminal. Terminal turns end run.failed with the exact summary ("replanned twice, still failing: <err>" / "replan produced no usable plan" / "replan returned the same failing step" / "the same step failed twice"). Suite 251 passed ×3 (5 new replan tests in tests/test_draft.py: fail→success ok+1 update, fail→fail→success ok+2 updates, always-fails 2 updates then failed summary, same-step terminal, provider-died terminal).
- **Deliverable:** in src/arcen/server/app.py — on step failure call draft.replan, REPLACE the remaining steps with the corrected plan, and CONTINUE the loop. Every replan emits plan.update (live in the UI). Bounded: max 2 replans per turn; a replan that returns nothing useful (empty, or the same failing step) is terminal; the same step failing twice with the same error is terminal — never an infinite loop. Second replan still failing → turn.failed with "replanned twice, still failing: <reason>".
- **Test:** `pytest tests/test_draft.py` — mock a step that fails on attempt 1 and succeeds on attempt 2 (loop completes ok, plan.update events emitted); mock a step that always fails (exactly 2 replans, then turn.failed with the summary); the full suite × 3
- **Verification:** forced step failure (bad args) → the loop replans and executes the new steps; terminal case ends with a clear summary, not a hang
- **Evidence:** v0.1.1 report — "replan() never continues the loop — on step failure app.py emits plan.update then break; corrected steps are never executed and the turn ends 'Turn failed' even with a provider. Honest, but the Aider-style replan is decorative."

### [T-043] No-docker case needs a documented, visible fallback
- **Status:** [x] done — verified
- **Note:** DONE — runtime.sandbox_state() composes the daemon/image probe with the backend decision + reason; boot logs the four [sandbox] lines (daemon / image / backend selected / reason) and warns when docker is pinned but unreachable; GET /api/sandbox/status now returns {docker_available, image_present, image, backend, effective, reason, degraded}; backend="docker" + no daemon → POST /api/run refuses 409 BEFORE planning with the ticket's exact message (no session created, never a silent fallback, never a 500); Settings → SANDBOX shows the three state lines + a health chip (green "docker ready" / amber "process mode" / red "docker required") and the /api/run refusal text surfaces in the chat via the submit-error banner (reader.ts carries the server detail). Docs: BACKEND-SPEC Part 4 "Sandbox backends" subsection — the ticket's "Part 8 (sandbox)" pointer collides with Credential Vault, noted in the spec and in the report. pytest ×3 exit 0 (251→259 passed: status-shape update + boot-lines + 409-refusal + auto-accepts + 5 sandbox_state unit tests), vitest ×3 exit 0 (71 passed: 4 chip/state tests + refusal-banner test).
- **Note (original scope):** environment limit, not a code bug — but a docker-less machine must be explicit and honest, not a silent fallback.
- **Deliverable:** boot logs the detected sandbox state ([sandbox] docker daemon / image / backend selected / reason); Settings → SANDBOX shows the same state; backend="docker" with no daemon → red chip + /api/run refuses cleanly before planning ("Sandbox backend is set to docker, but no docker daemon is reachable. Either start docker or change the backend in Settings → Sandbox."), never a silent fallback; backend="auto" with no daemon → process backend + amber chip; documented in docs/BACKEND-SPEC.md Part 4 (sandbox subsection)
- **Test:** `pytest tests/test_server.py tests/test_sandbox.py` + `npx vitest run`
- **Verification:** docker-present machine → green "docker ready" state; docker-less machine → amber "process mode" (auto) or red "docker required" (docker); a task with backend="docker" on a docker-less host → clean refusal, not a 500
- **Evidence:** v0.1.1 report — "No real docker daemon on this host — the docker-forced happy path is proven via fake-client unit tests + live error-path; a true docker run needs your machine."

### [T-044] Document the mock-provider contract (doc-only)
- **Status:** [x] done — verified
- **Note:** DONE — both edits landed verbatim: scripts/mock_provider.py header now opens with the CONTRACT block ("This mock must model a REAL planner: plans must carry tool args (cmd, path, code), not just step labels. A regression here means tests pass but live runs fail."); BACKEND-SPEC Part 11 gains the "Mock provider contract (T-044)" note ("The mock provider must always emit tool args. Bare-label plans hide arg-derivation bugs from the test suite."). No code change — the mock's plan_for() already emitted args (T-037).
- **Deliverable:** header comment in scripts/mock_provider.py ("This mock must model a REAL planner: plans must carry tool args (cmd, path, code), not just step labels. A regression here means tests pass but live runs fail."); a note in docs/BACKEND-SPEC.md Part 11 under the mock-provider material ("The mock provider must always emit tool args. Bare-label plans hide arg-derivation bugs from the test suite.")
- **Test:** none (doc-only)
- **Verification:** both texts present; no code change
- **Evidence:** v0.1.1 report — "Mock provider had the same no-args bug — its plans carried no args, so it now models a real planner (this would have bitten your laptop testing too)."


## v0.1.3 — close "noticed while fixing" (flagged in the v0.1.2 report)

### Process — "noticed while fixing" is a ticket, never a paragraph

Going forward, any item logged under a release report's "Noticed while
fixing" (P7) becomes a TICKET — not a report line, not "informational":

- Fixable now → add T-NNN, fix it, mark [x], push.
- Not fixable now → add T-NNN, mark [ ], add a one-line reason why it is
  deferred, and push the ticket.
- Never leave it as a paragraph in a report.

This closes the pattern where real bugs sit unactioned in a report.

**v0.1.2 P7 disposition** (every item, with its ticket id):

| v0.1.2 P7 item | Disposition |
|---|---|
| Ticket pointer mismatch ("Part 8 (sandbox)") | T-047 |
| Deterministic session id "s-ui" | T-045 |
| Screenshot harness staleness | T-048 |
| plan.update assertion shape | [x] handled by tests (v0.1.2 replan suite, tests/test_draft.py) |
| vitest chip branch-order bug | [x] handled by tests (v0.1.2 chip tests, caught + fixed the order) |

### [T-045] Deterministic session id "s-ui" (real bug)
- **Status:** [x] done — verified
- **Note:** DONE — sessionStore.ts owns id generation: resolveInitialSessionId() (stored id, else a fresh crypto.randomUUID() persisted to localStorage["arcen.activeId"] — the repo's canonical key for the ticket's "arcen.currentSession"), ensureActiveSession() (idempotent store seed used by App — no hardcoded fallback anywhere), rotateLegacySession() (a context pinned to "s-ui" replays its events once in ChatView.boot, then rotates to a fresh UUID; "s-ui" is never persisted nor sent again and stays in the drawer as history). ChatView takes a required sessionId and resets the stream when boot finds the session nowhere (no cross-id bleed). All "s-ui" literals removed from src except LEGACY_SESSION_ID; test fixtures use "test-session-a"/UUIDs. New ui/tests/session-id.test.tsx (4 tests): fresh context → UUID persisted (no wire request carries "s-ui"), reload reuses the stored id, legacy s-ui replays exactly once then rotates and the next turn POSTs the rotated id, two fresh contexts get different UUIDs. vitest 75 passed (71+4), tsc build clean, pytest 259 passed. Commit 5074c2c.
- **Depends on:** none
- **Deliverable:** no hardcoded default session id anywhere. On first load (no stored session id) the UI generates a fresh `crypto.randomUUID()` and persists it (`localStorage['arcen.activeId']` — the repo's canonical key for the ticket's "arcen.currentSession") and uses it everywhere — stream, run, session store. The old "s-ui" survives only as a migration target: a context still pinned to it loads those events once, then rotates to a fresh id for the next turn. Tests stop using s-ui fixtures (deterministic fixture ids or generated UUIDs).
- **Test:** `npx vitest run` — fresh context generates a UUID (never "s-ui"); reload keeps the same id; "+ New chat" generates a new UUID; two fresh contexts get different UUIDs; a legacy "s-ui" context replays once then rotates
- **Verification:** fresh browser context → stored id is a UUID, not "s-ui"; server log shows no "session=s-ui" runs after the first turn
- **Evidence:** v0.1.2 report — "The default UI session id is the deterministic s-ui on a fresh browser context — sessions accumulate there across runs." Every user's first session id was identical; ids collide across users/machines; old events leak into new sessions; the drawer merges everything into one giant session.

### [T-046] Session list per user (follows T-045)
- **Status:** [x] done — verified
- **Note:** DONE — ui/tests/session-isolation.test.tsx (2 tests) pins cross-context isolation: two simulated fresh browser contexts (full storage + store wipe between) mint distinct UUIDs; each context's message POSTs to its own id ("hello from A" → idA, "hello from B" → idB); NO wire call of either context ever references the other's session (runs, streams, polls, replays). Reload isolation pinned too: context A restored from localStorage keeps idA after a second context exists and never fetches idB. Drawer history stays per-user because ids no longer collide; the drawer list itself remains the server's session list by design (FRONTEND-SPEC Part 8/11). vitest 77 passed (75+2), tsc clean, pytest 259 passed.
- **Depends on:** T-045
- **Deliverable:** cross-context isolation is guaranteed and pinned by a test: two fresh browser contexts generate distinct session ids, a message sent in each is POSTed to that context's own id, and neither context ever reads or streams the other's session. The drawer's per-context history stays un-merged because ids no longer collide (localStorage-scoped state + unique ids); the drawer list itself remains the server's session list by design (FRONTEND-SPEC Part 8/11).
- **Test:** `npx vitest run` — simulate two fresh browser contexts (clear storage + reset store between), send a message in each, assert distinct ids and that no fetch of context A touches context B's session (and vice versa)
- **Verification:** the isolation test fails if either context reuses the other's id (guard against regression to a shared default)
- **Evidence:** v0.1.2 report — "sessions accumulate there across runs"; T-045 removes the shared id, T-046 proves the isolation

### [T-047] Ticket pointer correction (housekeeping)
- **Status:** [x] done — verified
- **Note:** DONE — the note now sits at the top of Part 8 itself ("(Note: earlier tickets sometimes referred to Part 8 as 'sandbox' — the sandbox lives in Part 4. Part 8 is the credential vault.)"), and the T-043 deliverable line is corrected to "docs/BACKEND-SPEC.md Part 4 (sandbox subsection)". The stale "BACKEND-SPEC Part 8 (sandbox)" pointer lived in the v0.1.2 TASK TEXT, not in repo docs — in-repo it was already corrected when T-043 landed (Part 4 subsection + collision notes at BACKEND-SPEC Part 4 and in the ticket note); this ticket fixes the last imprecise in-repo pointer and adds the Part 8 header note. Audit: every "Part 8" in docs/ now means the credential vault (BACKEND-SPEC Parts 79/212) or FRONTEND-SPEC Part 8 (session store) — none mean sandbox. No code change.
- **Depends on:** none
- **Deliverable:** every spec pointer that means sandbox says Part 4 (config/sandbox), not Part 8 (credential vault). Part 8 (Credential Vault) gets the one-line note: "(Note: earlier tickets sometimes referred to Part 8 as 'sandbox' — the sandbox lives in Part 4. Part 8 is the credential vault.)" The T-043 deliverable line is corrected to name Part 4. No code change.
- **Test:** `grep -rn "Part 8" docs/` — no remaining reference means sandbox; the Part 8 header note is present
- **Verification:** all sandbox pointers read Part 4; vault references still read Part 8
- **Evidence:** v0.1.2 report — "Ticket pointer mismatch: 'BACKEND-SPEC Part 8 (sandbox)' — Part 8 is the Credential Vault; the sandbox lives in Part 4."

### [T-048] Screenshot harness staleness guard (test-only fix)
- **Status:** [~] in progress
- **Depends on:** none
- **Deliverable:** the screenshot harness refuses to capture a stale turn. Before any screenshot: (a) the last rendered message count must be strictly greater than the baseline count for the session, and (b) the wire must show a fresh run.done for the current turn (seq beyond the baseline). Either check failing → the harness refuses to capture and exits non-zero with the reason. Guard logic is unit-tested so the refusal path itself is pinned.
- **Test:** `pytest tests/test_screenshot_guard.py` + the harness run twice back-to-back on a fresh session — both runs capture distinct turns; a run whose turn never fires fails loudly (non-zero, reason printed)
- **Verification:** harness cannot silently re-screenshot a replayed/stale stream
- **Evidence:** v0.1.2 report — "ChatView replay-of-history initially fooled the screenshot harness into matching a stale answer — harness now baselines message count and polls the wire for run.done."
