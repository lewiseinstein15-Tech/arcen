# ARCEN² — Target Architecture: Recursive Harnessing for ARCEN

> Build sequencing for this design: tickets H-01…22 and milestone gates in
> [REBUILD-MASTER-PLAN.md](REBUILD-MASTER-PLAN.md).
>
> Status: **design proposal only — no code changed.** Date: 2026-10-28.
> Inputs: Harness² paper (arXiv 2610.14224), google-research/harness2 README
> and project page, community fork 3ae3ae/harness2-cli, and ARCEN source at
> `3d32166` (357 tests, 17 frozen events, DRAFT→FORGE→TEMPER pipeline).
> Reading order: §1 thesis → §3 additions over Harness² → §4–7 the architecture
> → §11 safety → §14 migration.

---

## 1. Thesis

Harness²'s core equation:

```
Agent = frozen Model (M) + editable Harness (H = c1…c8)
```

ARCEN today is a hand-built harness with a frozen kit and a plan-adapting
inner loop. The rebuild makes the **kit itself the unit of learning**, while
keeping everything that already differentiates ARCEN: the event contract,
the quarantine, the verifier role, the provider bridge.

Two loops, strictly separated:

- **Execution loop (inner):** DRAFT→FORGE→TEMPER, largely unchanged, but
  driven from a **versioned, file-based harness** instead of prompts and
  rules baked into Python. This is the thing being measured.
- **Harnessing loop (outer, new):** Propose → Probe → Judge → Compose →
  Canary → Adopt → Reflect, running *between* tasks, mutating only harness
  files, never model weights and never a live task.

The outer loop is **gated, budgeted, and observable** — the three properties
the Google research code lacks (see §3).

### Design principles

1. **Safe by default, opt-in risky.** Probes inherit ARCEN's network-off
   quarantine; the Harness² defaults (open network, sandbox disabled) are
   treated as an anti-pattern, not a template.
2. **Every edit is a diff, every diff has evidence, every adoption is
   reversible.** No silent self-modification.
3. **Use ground truth whenever it exists.** Contrastive judging is the
   fallback for open-world tasks without verifiers, not the only channel.
4. **One event stream narrates both loops.** The meta-loop is not a hidden
   background daemon — it is a first-class, replayable observable.
5. **The frozen 17-event contract stays.** All meta-loop events are
   additive v2 types; old clients keep working by ignoring unknown types.

---

## 2. What we keep from Harness²

| Harness² idea | Kept in ARCEN² |
|---|---|
| Agent = model + editable 8-component harness | Yes — components externalized as files (§6) |
| Task-level Propose–Probe–Compose, no ground truth required | Yes, as one of three evidence channels (§7.3) |
| Harnessing-level recursion: persistent improvement library steers future edits | Yes — `library/`, fused with the existing memory graph |
| Parallel (explore wide) and sequential (refine deep) recursion with budget k | Yes, scheduled by the Governor |
| Each task starts from base harness H₀; library only steers the editor | Yes — prevents cross-task contamination of runs |
| Executors are swappable; the harnessing loop is substrate-agnostic | Yes — ARCEN's own executor is default; OpenCode/Codex can later be registered as external executors using the same interface |
| Resume by re-invoking with the same run directory | Yes — harness runs are content-addressed and resumable |

---

## 3. What Harness² is missing — and what ARCEN² adds

These are the creative gaps. Each maps to a concrete component in §5.

| # | Harness² gap | ARCEN² addition |
|---|---|---|
| A1 | **No human gate.** Edits auto-adopt; the only review is third-party tooling (the CLI fork added `diff`/`apply`). | **Adoption Gate** with per-component mutability tiers; TUI approval prompts; nothing reaches a real user task without policy + (for protected tiers) a human. |
| A2 | **Guardrail self-weakening.** Nothing stops an optimizer from editing its own guardrails to make tasks easier. Defaults even disable the sandbox. | **Immutable safety core** (Tier 0): guardrail policy, plugin set, network/sandbox posture cannot be edited by any LLM call, plus a forbidden-edit linter that rejects proposals touching them. |
| A3 | **Pure contrastive judging**, even when real verifiers exist. | **Hybrid Judge** fusing three channels: hard verifiers (TEMPER, pytest, type checks, exit codes) > human signal > blind contrastive LIM judging. Contrastive only fires where no ground truth exists. |
| A4 | **No regression protection.** A winning edit on one task can silently degrade others. | **Canary bank**: every candidate runs a persistent graded task suite before adoption; any regression blocks adoption and auto-rolls-back the current ref if a live version regresses. |
| A5 | **Cost explosion** — every probe is a full agent run; no caps, no early stopping, no cache strategy. | **Governor**: per-run token/USD budgets, concurrency caps, bandit-style early elimination of losing probes, shared prompt-prefix caching across probes, convergence stop. |
| A6 | **Judge bias** — the judge sees editor-authored candidates and reference trajectories with provenance. | **Blind judging**: trajectories are anonymized and shuffled; the judge sees no editor rationale, no component labels, no candidate IDs. |
| A7 | **Unbounded `EXPERIENCE.md`** — lessons accumulate forever, stale advice never expires. | Lessons are entities in the **existing memory graph** with decay, consolidation, temporal validity and conflict resolution (machinery ARCEN already has), exported as a generated `EXPERIENCE.md` view. |
| A8 | **Weak provenance** — results dumped under `runs/`, no lineage graph. | **Content-addressed harness store**: every component version is hash-addressed, git-backed, with a lineage DAG H₀ → candidates → adopted H′ → lessons, each edge linked to trajectory IDs and judge reports. |
| A9 | **Batch-only, invisible while running.** | The full harnessing loop emits typed events on the existing NDJSON stream, with a TUI "Harness" view, live diffs, and interrupt/steering. |
| A10 | **Secret and injection exposure** — unrestricted networking, Codex sandbox off, no per-probe credential scoping. | Probes run in cloned quarantines with **empty credential envelopes**, the existing `redact_secrets` plugin forced on, and an injection scanner over task content before execution. |
| A11 | **Single editor model** (paper: one Claude Opus editor). | **Editor panel**: k proposals can come from different models via the LiteLLM bridge, with cost/routing policy; diversity of editors is itself a recursion-budget knob. |
| A12 | **No stop condition beyond budget**; no notion of "good enough." | Convergence detection: stop when best-vs-base delta < ε for two rounds, or all candidates fail policy; report *no change* as a first-class outcome. |
| A13 | **Environment overfitting** — a harness tuned inside one sandbox. | Optional **portability probes**: candidate harnesses re-run on a second executor/environment profile before adoption. |

---

## 4. Layered architecture

Today's four layers stay; a new layer sits above them and a new
cross-cuting service plane wraps them.

```
┌─────────────────────────────────────────────────────────────────────┐
│  L0 · HARNESSING LOOP        editor · prober · judge · composer      │
│      (arcen/harness/)        reflector · library · governor ·        │
│                              adoption gate · canary · policy         │
├─────────────────────────────────────────────────────────────────────┤
│  L1 · AGENTS                DRAFT · FORGE · TEMPER                   │
│      (unchanged roles,      now reading prompts/rules from the       │
│       file-based harness)   versioned harness store, not Python      │
├─────────────────────────────────────────────────────────────────────┤
│  L2 · SUB-AGENTS            depth-capped spawns (T-011 finally       │
│                             wired; probe runs reuse spawn events)    │
├─────────────────────────────────────────────────────────────────────┤
│  L3 · CAPABILITY            skills · tools · MCPs · plugins ·        │
│                             memory graph  — all addressable as        │
│                             harness components c3,c4,c6,c7,c8         │
├─────────────────────────────────────────────────────────────────────┤
│  L4 · RUNTIME               FastAPI · NDJSON v2 stream · per-session │
│                             quarantine sandboxes · session jsonl ·    │
│                             headless runner · config vault           │
└─────────────────────────────────────────────────────────────────────┘
        cross-cutting: Governor (budgets) · Policy (tiers/gates) ·
        Provenance (content-addressed store + lineage)
```

Three operating modes share one codebase:

| Mode | Command | Loop | Use |
|---|---|---|---|
| Interactive | `arcen-tui` / web | inner only, on adopted harness | daily use |
| Headless | `arcen run "goal" --json` | inner only, exits with result + code | CI, scripts, and the outer loop's executor |
| Harnessing | `arcen harness run …` | outer over inner | improvement campaigns; `diff`/`apply`/`rollback`/`canary` subcommands |

---

## 5. The new services (forge-themed codenames in brackets)

All live in a new package `src/arcen/harness/`. Functional names are
canonical; codenames are optional UI labels.

| Service | Codename | Responsibility |
|---|---|---|
| **Harness Store** | — | Content-addressed, git-backed storage of component files, manifests, refs (`adopted`, `candidate/*`), lineage edges |
| **Editor** | ALLOY | Given reference trajectory + improvement library, proposes k invariant (general) and k domain-specific component edits as unified diffs |
| **Prober** | QUENCH | Fans candidate harnesses out as isolated probe runs: identical task input, fresh sandbox snapshot, git worktree, empty credential envelope; supports parallel/sequential modes |
| **Judge** | TOUCHSTONE | Blind, shuffled evaluation; fuses verifier / contrastive / human evidence into scored reports with confidence |
| **Composer** | ANNEAL | Merges non-conflicting winning edits into one successor harness manifest; rejects overlapping hunks back to the Editor |
| **Reflector** | SMELT | Distills the improvement record into lesson entities (with evidence links), writes the generated `EXPERIENCE.md` view, updates the library |
| **Governor** | GAUGE | Non-LLM control plane: token/USD budgets, concurrency, early elimination, cache-prefix reuse, convergence/stop, kill switch |
| **Policy Engine** | — | Mutability tiers, forbidden-edit lint, adoption-gate decisions, approval requests |
| **Canary Runner** | — | Maintains the graded task bank and gates every adoption on regression results |
| **Harness Runner** | — | Orchestrates the 8-stage pipeline, resume, and the `arcen harness` CLI surface |

---

## 6. The harness as files — eight components, ARCEN paths, mutability tiers

A harness is a directory with a signed manifest (`harness.toml`: component
hashes, parent ref, model pin, schema version). Store root:
`~/.arcen/harness/`; projects may add an overlay at `<repo>/.arcen/harness/`.

| C | Harness² component | ARCEN² file(s) | Current home being replaced | Tier |
|---|---|---|---|---|
| C1 | System prompt | `prompts/system.md`, `prompts/{draft,forge,temper}.md` | strings embedded in `llm/client.py`, `agents/*.py` | 1 |
| C2 | Guardrails | `guardrails/policy.yaml` (machine rules) + `guardrails/rules.md` | scattered in `sandbox/runtime.py`, plugins | **0 — immutable** |
| C3 | Memory | `memory/seed.md` + config; runtime graph stays in `memory.db` | `memory/` | 2 |
| C4 | Tool guidance | `tool-guidance.md` + `tools/registry.toml` | `tools/registry.toml` (already data) | 2 |
| C5 | Subagents | `subagents/*.md` definitions | `subagents/agent.py` (dead → wired, T-011) | 1 |
| C6 | Skills | `skills/<name>/SKILL.md` | already files — unchanged shape | 2 |
| C7 | Scripts | `scripts/*` mounted read-only into sandbox | absorbed from `tools/bash.py` conventions | 1 |
| C8 | Plugins | `plugins/*` + enabled-list in manifest | `plugins/loader.py`, `redact_secrets.py` | **0 — immutable** |

**Tiers (the A1/A2 answer):**

- **Tier 0 — human-only, LLM-locked.** C2 policy, C8 plugin set, sandbox/network posture, approval policy. The Editor's tool literally cannot write these paths; the Policy linter also rejects any proposal containing them as defense in depth.
- **Tier 1 — gated.** C1, C5, C7. Proposed automatically, adopted only after an explicit human `apply` (or an explicit auto-approve policy in a CI environment).
- **Tier 2 — auto-adoptable within policy.** C3, C4, C6. May self-adopt when canaries pass and the confidence threshold is met; every auto-adoption still emits an event and stays one-command rollback-able.

---

## 7. How it runs

### 7.1 Inner execution loop (both interactive and headless)

```
goal + harness ref (default: refs/heads/adopted)
  → resolve manifest from store, load component files
  → DRAFT (reads C1/C6/C3) → plan
  → FORGE (tools governed by C4/C7/C8, one call per step as today)
  → TEMPER verdicts
  → full trajectory + tool IO + usage + verdicts persisted as a
    Trajectory Record (the session jsonl gains a harness_ref field)
  → answer; headless mode prints JSON, exits 0/non-zero
```

No behavioral change for existing users except prompt provenance: prompts now
load from the adopted harness instead of Python constants.

### 7.2 Outer harnessing loop — eight stages

```
                        ─────────── HARNESS RUN (resumable) ───────────
 1 ARRIVE     task pulled from task bank; Governor allocates budget;
              base = H0 = refs/heads/adopted; library snapshot attached
 2 REFERENCE  inner loop executes task under H0
              → reference trajectory T0 (invariant, archived)
 3 PROPOSE    Editor (one or many models) emits 2k diffs:
              k invariant + k domain-specific, each scoped to tier-1/2 paths
 4 POLICY     forbidden-edit lint + tier check; illegal diffs rejected here
 5 PROBE      each surviving candidate gets an identical isolated run:
              worktree clone + fresh quarantine + empty creds + shared
              prompt-prefix cache; parallel or sequential per --mode
 6 JUDGE      blind shuffled evaluation; hybrid evidence fusion (§7.3)
 7 COMPOSE    non-conflicting winners merged → successor manifest H′
 8 CANARY     H′ runs the regression bank; pass → Adoption Gate
              → ADOPT (auto tier-2 / human tier-1) or REJECT
 9 REFLECT    lesson entities + EXPERIENCE.md update; lineage edge written;
              next task still starts from H0, library carries the learning
```

Stages 1–8 are one task-level recursion; budget `--k` scales candidates
(parallel) or rounds (sequential), exactly as in the paper. Stage 9 is the
harnessing-level recursion that makes learning generalize across tasks.

### 7.3 Hybrid Judge decision rule

For each candidate Hᵢ vs reference H₀ on the same task:

1. **Verifier channel (preferred).** TEMPER verdicts, test/type/lint exit
   codes, explicit acceptance checks. A hard pass/fail delta decides outright.
2. **Human channel (optional).** TUI `--selector human` presents anonymized
   outputs; recorded as weighted evidence.
3. **Contrastive channel (fallback).** Blind pairwise LLM judge over
   redacted, shuffled trajectories — the Harness² method, used only when
   channels 1–2 are unavailable.

Fusion: adopt only when (a) zero canary regressions, (b) fused score delta
exceeds threshold τ with reported confidence, (c) all changed components
satisfy tier policy. Tie or failure → keep H₀ and emit `harness.reject`;
"no improvement" is a normal, recorded outcome (A12).

### 7.4 CLI surface (mirrors the fork's proven commands)

```
arcen run "<goal>" [--json] [--harness <ref>] [--workspace <path>]
arcen harness init|doctor
arcen harness task new|ls|import
arcen harness run [--k K] [--mode parallel|sequential]
                  [--budget-usd N] [--max-tasks N] [--selector human]
arcen harness status|stop|resume
arcen harness diff <ref>          # review proposed component changes
arcen harness apply|reject <ref>
arcen harness rollback [--to <ref>]
arcen harness canary run|report
```

---

## 8. Event contract: additive v2 (the frozen 17 stay untouched)

The existing `spawn` / `spawn.done` events, currently defined but never
emitted, finally get a job: **probe runs are spawned sub-runs** with
`parent_run_id`. New types are additive; renderers ignore unknown types.

| New event | Emitted at | Key fields |
|---|---|---|
| `harness.propose` | stage 3 | run_id, candidate_id, scope (invariant/domain), component, diff_ref |
| `harness.policy` | stage 4 | candidate_id, decision, violated_rule |
| `spawn` / `spawn.done` | stage 5 | reused: probe sub-run, sandbox id, worktree |
| `harness.judge` | stage 6 | candidate_id, channel (verifier/human/contrastive), score, confidence |
| `harness.compose` | stage 7 | successor_ref, merged/rejected hunks |
| `canary.start` / `canary.done` | stage 8 | task ids, pass/fail deltas |
| `approval.request` / `approval.resolve` | gate | tier, diff_ref, human decision |
| `harness.adopt` / `harness.reject` / `harness.rollback` | gate outcomes | ref, reason, evidence trajectory ids |
| `budget.usage` | throughout | tokens, usd, remaining, early-kills |

Wire envelope gains one optional field, `harness_ref`, on `run.start`;
absence means "adopted," preserving old sessions byte-for-byte.

---

## 9. Storage layout

```
~/.arcen/
  config.yaml                 # adds [harnessing] section: tiers, budgets, editor models
  memory.db                   # existing graph + new Lesson entities (decay/validity)
  sessions/<id>.jsonl         # trajectories, now with harness_ref
  harness/
    store/objects/<sha256>/   # content-addressed component blobs
    store/manifests/<sha>.toml
    refs/heads/adopted        # current production harness
    refs/candidates/<id>      # probe-era harnesses
    library/EXPERIENCE.md     # generated view over lesson entities
    canaries/tasks/*.yaml     # graded regression bank
    canaries/results.db
    runs/harness-<id>/        # one resumable campaign: proposals, probes, reports
    worktrees/probe-<id>/     # ephemeral, destroyed after judging
```

Lineage is a DAG in SQLite: `(harness_ref, parent_ref, task_id,
trajectory_ids, judge_report, decision, timestamp)` — every adopted byte is
traceable to the evidence that promoted it (A8).

---

## 10. Runtime topology and the Prober

The FastAPI server remains the single process for the interactive single-user
Omarchy deployment; the harnessing services run inside it as a bounded
**worker pool** behind the Governor (default concurrency 2, configurable).
The Prober schedules through the existing `sandbox/runtime.py`, so probes get
the same quarantine guarantees as normal sessions, plus:

- identical task input and seeded RNG for fair contrasts;
- git-worktree clones of the target repo, destroyed after judging;
- empty credential envelope and forced-on `redact_secrets` (A10);
- network off unless a canary explicitly requires it, in which case egress
  is allowlisted and benchmark-answer domains are blocked (the paper's own
  web-access warning, enforced rather than documented);
- shared prompt-prefix cache across probes to cut duplicate token cost (A5).

A later split (separate harnessing worker process) is a deployment option,
not an architecture change, because all coordination goes through the store
and event stream.

---

## 11. Safety model (the part Harness² gets wrong)

1. **Immutable safety core.** C2/C8 and runtime posture are outside the
   Editor's writable path namespace; Policy linter is second-chance rejection.
2. **Deny-first adoption.** Unknown component, unparseable diff, missing
   evidence, expired confidence → reject. Default decision is always "keep H₀."
3. **Quarantine for every probe**, network off, no host binds, scrubbed env —
   ARCEN's existing posture, inherited, never relaxed by an optimizer.
4. **One-command rollback** to any prior ref; automatic rollback if canary
   monitoring catches a regression in a live adopted harness.
5. **Kill switch**: Governor aborts the whole campaign on budget breach,
   repeated policy violations, or injection-scanner findings.
6. **Human is the default Tier-1 approver.** Auto-apply exists but must be
   configured explicitly per environment.
7. **All of it is narrated**: no self-modification without an event, a diff,
   and an evidence link.

---

## 12. Budget and cost controls (Governor)

- Per-campaign caps: `--budget-usd`, `--max-tokens`, `--k`, wall-clock.
- Early elimination: after a first judging round, candidates statistically
  below the running best lose their remaining probe slots.
- Sequential mode reuses one sandbox snapshot; parallel mode shares prefix
  caches. Editor model routing prefers cheap models for invariant edits and
  reserves strong models for domain-specific ones (A11).
- Convergence stop: Δ(best, base) < ε for two rounds → clean finish with
  `harness.reject(reason=converged)`.
- Every campaign ends with a cost report on `budget.usage` events and in
  `runs/harness-<id>/report.md`.

---

## 13. Module plan (new code surface)

```
src/arcen/
  harness/
    __init__.py
    model.py        # Harness, Component, Manifest, hashing
    store.py        # content-addressed store, refs, lineage DAG
    policy.py       # tiers, forbidden-edit lint, adoption gate
    editor.py       # proposal generation (multi-model panel)
    prober.py       # worktree + sandbox fan-out, spawn events
    judge.py        # verifier/human/contrastive fusion, blinding
    composer.py     # hunk merge / conflict return
    reflector.py    # lesson extraction
    library.py      # EXPERIENCE.md view over memory graph
    canary.py       # regression bank runner
    governor.py     # budgets, concurrency, elimination, convergence
    runner.py       # 8-stage orchestration, resume
    cli.py          # `arcen harness ...`
  headless.py       # `arcen run --json` entry, shared executor API
  stream/events_v2.py  # additive event dataclasses (§8)
```

Refactors required of existing code: prompt strings move out of
`llm/client.py` and `agents/*.py` into harness files loaded through a new
`HarnessResolver`; `subagents/agent.py` is finally wired into `run_turn`
(T-011) and reused by the Prober; `server/app.py` gains the headless route
and harness campaign endpoints but keeps every existing route.

---

## 14. Migration path (each phase independently shippable)

| Phase | Outcome | Rough scope |
|---|---|---|
| **P0 — Headless + externalize** | `arcen run --json`; prompts/guardrails load from files; behavior identical, 357 tests stay green | headless runner, HarnessResolver, first static harness dir |
| **P1 — Store** | content-addressed store, manifests, refs, lineage; `adopted` ref; read-only selection per run | `harness/store.py`, `model.py` |
| **P2 — Manual loop** | Editor + Prober + contrastive Judge; campaigns end in a human `diff`/`apply`; spawn events go live | editor, prober, judge, cli, events_v2 |
| **P3 — Full recursion** | Composer, Reflector, library in memory graph; parallel/sequential modes; resume | composer, reflector, library, runner |
| **P4 — Trust machinery** | Policy tiers + forbidden-edit lint, canary bank, Governor budgets, hybrid verifier-fused judging, rollback | policy, canary, governor, judge fusion |
| **P5 — Surface** | TUI Harness view + approval prompts, v2 renderers, sub-agent wiring (T-011), portability probes | tui, subagents, docs |

Nothing in P0–P1 changes user-visible behavior; the self-improvement
machinery only becomes capable of adopting changes in P4, and only inside
the tier policy.

---

## 15. Non-goals and open questions

- **No model weight training, ever.** The frozen-model boundary is the whole
  point; ARCEN² optimizes context and tooling, not parameters.
- External executors (OpenCode/Codex) are a later adapter, not a launch
  dependency — ARCEN's own inner loop is the first substrate.
- Open questions for when build approval is given:
  1. Default Tier-1 posture in headless CI — auto-apply opt-in wording?
  2. Canary bank seed content: synthesize from existing session jsonl history?
  3. Editor panel defaults (which LiteLLM models, what routing thresholds)?
  4. Should project-level harness overlays be allowed to downgrade global
     tiers, or only narrow them? (Recommendation: narrow only.)
  5. ε and τ defaults for convergence/adoption — needs empirical calibration
     from the first campaigns.

---

## Sources

- Paper and abstract: https://arxiv.org/abs/2610.14224
- Reference implementation: https://github.com/google-research/harness2
- Method diagrams and 8-stage pipeline: https://harness2.github.io/
- Productized fork (command/diff/apply/budget patterns): https://github.com/3ae3ae/harness2-cli
- Prior gap analysis in this repo: `docs/RESEARCH-harness2-vs-arcen.md`
