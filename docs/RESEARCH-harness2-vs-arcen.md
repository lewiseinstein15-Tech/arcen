# Research: Google Harness² vs ARCEN (corrected target)

> Date: 2026-10-28 · Scope: research only — no code changes.
> This document corrects the earlier misread ("hernes2" → Hermes Agent).
> The intended subject is **Harness² (Harness2)** by Google Cloud AI Research.
> The runtime/Claude Code material in `RESEARCH-hermes-claude-code-vs-arcen.md`
> remains valid for the separate question "how should a terminal coding agent run."

## 1. What Harness² actually is — and what it is not

**Harness² is not a chat CLI and not an agent runtime.** It is an Apache-2.0
**research framework that optimizes another agent's harness** — the kit of
prompts, rules, memory, tools and hooks surrounding a frozen model. It was
open-sourced 2026-10-08 at [google-research/harness2](https://github.com/google-research/harness2)
alongside the paper *"Harness²: Recursive Agent Harnessing for an Open World"*
(arXiv 2610.14224; Xu et al., Northwestern + Google Cloud AI Research).

Facts that matter for comparison:

- The repo is **3 commits old, v0.1.0**, and its README states *"This is not
  an officially supported Google product."* Treat it as an experiment.
- It does not execute tasks itself. It drives existing terminal agents as
  **executors: OpenCode (default) or Codex**. Each "probe" is a full run of
  that external CLI.
- Model-backed runs need Node 20+, gcloud, Vertex AI and API budget; a
  credential-free deterministic demo (`harness2-demo`) exists for inspection.
- Cost is structural: one improvement step = 1 reference run + 2k probe runs
  + compositions + editor/judge calls. k=5 parallel probes multiply the bill.
- Safety is weak by default: reviewers and the README note **unrestricted
  executor networking** and **Codex sandbox disabled** during runs.
- A community fork, [harness2-cli](https://github.com/3ae3ae/harness2-cli),
  generalizes the method to any project and any executor (Claude Code, Codex,
  or an arbitrary command), with TOML config, budgets, `diff`/`apply` human
  review, and resume — closer to a usable product than the research release.

## 2. The core idea: Agent = Model + Harness, and the harness is recursive

```
Agent A(·; M, H)  =  frozen Model M  +  editable Harness H = (c1 … c8)
```

Harness² keeps model weights fixed and rewrites the harness. Two recursion
levels are connected:

**Task-level recursion — contrastive Propose–Probe–Compose (no ground truth).**
1. Run the task with the base harness H₀ → reference trajectory.
2. An *editor* (a second model; the paper uses Claude Opus 4.8 under OpenCode)
   proposes two edit scopes: *invariant* (general) and *domain-specific*.
3. **Probe**: execute each candidate harness on the same task.
4. **Compose**: keep edits whose behavioral contrast against the reference
   holds up. Selection needs no correct answer — only relative evidence.
5. Execute and deliver with the adopted harness H′.

**Harnessing-level recursion — the improver improves itself.**
After each task a *reflector* writes the adopted harness plus evidence-backed
lessons (`EXPERIENCE.md`) into a persistent **improvement harness R /
improvement library**. The next task still starts from H₀, but the editor's
proposals are steered by everything learned so far. Parallel recursion
explores k independent candidates; sequential recursion carries one harness
through k rounds.

### The eight editable harness components

| # | Component | Runtime role |
|---|---|---|
| C1 | System prompt | Context construction |
| C2 | Guardrails (always-on rules) | Context construction |
| C3 | Memory | Context construction |
| C4 | Tool guidance | Tool interface |
| C5 | Subagents | Orchestration / delegation |
| C6 | Skills | Context construction |
| C7 | Scripts | Tool interface |
| C8 | Plugins (middleware in the tool loop) | Middleware control — the only component that intercepts **every** tool call, outside model discretion |

Reported effect (paper, not independently reproduced): one step yields up to
+11.5 points WorkBuddy-Bench, +4.5 JobBench, +11.8 pp LAB partial pass;
k=5 parallel raises Gemini 3.5 Flash/OpenCode from 72.4 → 80.8 average.

## 3. The key reframe: ARCEN *is* an execution harness

Comparing feature lists is the wrong lens. Claude Code, Hermes Agent,
OpenCode and **ARCEN are all execution harnesses in Harness²'s vocabulary** —
the thing being optimized. ARCEN already contains all eight component slots;
the difference is that every one of them is **static and human-authored**,
whereas Harness² treats each as a machine-editable file:

| Harness² component | ARCEN slot today | Editable by an optimizer? |
|---|---|---|
| C1 System prompt | Embedded in `llm/client.py` (no external prompt files exist) | No — code change required |
| C2 Guardrails | `sandbox/runtime.py` quarantine + fail-closed `plugins/` hooks | No — code/config, strongest slot |
| C3 Memory | `memory/` SQLite entity graph (decay, consolidation, temporal) | Runtime-mutable, but entity memory, not harness lessons |
| C4 Tool guidance | `tools/registry.toml` + 10 tool modules | Partly — TOML is data, semantics are code |
| C5 Subagents | `subagents/agent.py` — **scaffolded, never invoked by `run_turn` (T-011)** | Slot exists, dead |
| C6 Skills | `skills/*/SKILL.md`, progressive loader | **Yes — plain markdown, the natural first target** |
| C7 Scripts | `tools/bash.py`, `tools/code.py`, `tools/proc.py` inside sandbox | No — fixed toolset |
| C8 Plugins | `plugins/loader.py`, `HookedRegistry.dispatch` (e.g. `redact_secrets`) | Code, but the interception point is exactly right |

## 4. Loop contrast: ARCEN adapts the *plan*; Harness² adapts the *kit*

| | ARCEN DRAFT→FORGE→TEMPER | Harness² Propose→Probe→Compose |
|---|---|---|
| What changes mid-task | The step plan (≤2 replans on failure) | Nothing — harness edits land *between* full runs |
| Feedback signal | TEMPER verification (explicit checks/grounding) | Contrastive behavior vs a reference trajectory — **deliberately needs no ground truth** |
| Unit of learning | None persisted across tasks about the harness itself | Adopted harness + `EXPERIENCE.md` in improvement library R |
| Execution count per task | 1 run | 1 + 2k probes + compositions + judge calls |
| What is frozen | Harness components | Model weights *and* base harness H₀ at task start |
| Parallelism | Strictly sequential, one tool per FORGE step | k parallel candidate sessions by design |

The two are complementary, not competing: TEMPER-style verification could
grade probes more cheaply than pure contrastive judging, while Harness²'s
no-ground-truth trick works where TEMPER has nothing to check against.

## 5. What ARCEN would need to host Harness²-style recursion

In dependency order, and explicitly **not implemented**:

1. **Headless execution entry point.** An outer optimizer cannot drive a
   TUI. ARCEN needs `arcen run "task" --json` (non-interactive, exits with a
   result) over the existing server API. Same gap identified versus Claude
   Code; it is the prerequisite for everything below.
2. **Externalize the eight components as files.** Skills already are;
   prompts, guardrail policy and tool guidance need to move out of Python
   into versioned, diffable files so an editor model can propose and a human
   can review (`harness2-cli`'s `diff`/`apply` gate is the model to copy).
3. **A contrastive judge + improvement library.** New store of trajectory
   pairs, adopted edits, and an `EXPERIENCE.md`-style lesson layer distinct
   from the entity memory graph.
4. **Parallel probe sessions.** The server already isolates per session;
   scheduling k concurrent runs with quotas and per-probe token/budget caps
   is an orchestration addition, not an architecture change.
5. **Wire or remove C5** (the sub-agent module, T-011) — an eight-component
   story with a dead fifth component would be the first thing a reviewer
   notices.
6. **Safety knobs for probe traffic.** Harness²'s defaults (open network,
   sandbox off) are its worst design choice; ARCEN's network-off quarantine
   is already better and should stay the default for all probe runs.

## 6. Where ARCEN is genuinely ahead *for this purpose*

- **Trajectory data is already first-class.** The 17-event frozen NDJSON
  contract and append-only JSONL sessions produce exactly the structured
  execution records contrastive probing consumes; Harness² must scrape
  free-form executor transcripts.
- **Probe safety.** Per-session quarantine, network off, scrubbed env —
  parallel k=5 probes in ARCEN would be far safer than Harness²'s documented
  defaults.
- **Provider freedom for the editor/judge roles.** LiteLLM bridge means the
  outer-loop models need not be Vertex/Gemini-locked as in the paper.
- **Auditability.** Every proposed harness edit could itself emit typed
  events, fitting the existing observability model rather than bolting on
  logging.

## 7. Bottom line

Harness² is a **meta-layer above** products like ARCEN, not a replacement
runtime. Its portable insight is small and implementable inside ARCEN:
treat prompts/guardrails/skills/tool-guidance as versioned files, run
contrastive re-runs of real tasks in the existing sandbox, keep what
measurably works, and accumulate lessons across tasks. ARCEN's event
contract and quarantine make it a better substrate for that loop than the
research code's own defaults — but the headless entry point and
file-externalized components are hard prerequisites.

## Sources

- Harness² repository (README, components, install, executors): https://github.com/google-research/harness2
- Harness² project page / paper site (two-level loop, eight components, results): https://harness2.github.io/
- Paper (arXiv): https://arxiv.org/abs/2610.14224
- Independent explainer with benchmark tables: https://aiprofitboardroom.com/blog/google-harness2/
- Safety/defaults critique and demo commands: https://explainx.ai/blog/google-harness2-recursive-agent-harnessing-open-source-workbuddy-jobbench-lab-2026
- General-purpose community fork (any executor, diff/apply, budgets): https://github.com/3ae3ae/harness2-cli
- Coverage of the Propose–Probe–Compose mechanics: https://pasqualepillitteri.it/en/news/25395/google-harness2-ai-agents-improve-themselves
