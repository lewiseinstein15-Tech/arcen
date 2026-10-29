# ARCEN Rebuild — Master Plan

> Status: TUI-01…18 merged; sandbox safety fix and H-01 are on local branches.
> The user reported the H-01 live Docker workspace test passing on Omarchy.
> H-01 remains partial: harness references are rejected until the store exists.
> H-02 and H-03 completed file-based prompts, tool guidance and validated
> guardrails on the local `feat/harness2` branch. H-04 has an unsigned bundled
> manifest and optional configured-model pin; signatures and full components
> remain future work. H-05 supplies a local content-addressed object API;
> refs, adoption and a git-backed store remain future work.
> Original plan: 2026-10-28.
> Umbrella document over two detailed plans:
> - **Track A — TUI redesign:** [TUI-REDESIGN-PLAN.md](TUI-REDESIGN-PLAN.md) (tickets TUI-01…18)
> - **Track B — ARCEN² recursive harnessing:** design in
>   [ARCEN2-ARCHITECTURE.md](ARCEN2-ARCHITECTURE.md), tickets H-01…22 below
>
> Ticket mechanics (status markers, verification loop, max-5-iterations rule,
> regression re-run before next ticket) follow [TICKETS.md](TICKETS.md).
> Branch strategy: Track A was merged to `main` at `bc4ae47`. Track B
> `feat/harness2` is based on the local `fix/sandbox-execution` safety branch;
> neither Track B nor the safety branch has been merged to remote `main`.

---

## 1. Why two tracks, and why they stay separate

The TUI is **presentation**; ARCEN² is a **new control plane above the
agent**. They share no code except the event contract, which is why both can
proceed in parallel and converge only in milestone M5.

```
                         ┌─────────────────────────────┐
                         │   event contract (NDJSON)    │
                         │  17 frozen types + v2 add    │
                         └──────────────┬──────────────┘
                                        │
        ┌───────────────────────────────┴───────────────────────────────┐
        │                                                                │
 TRACK A · TUI redesign                                      TRACK B · ARCEN²
 TUI-01…18 (10–12 days)                                      H-01…22 (~8–10 weeks)
 presentation-only, zero backend change                      headless, harness store,
 ignore-unknown-events rule makes v2 safe early              editor/prober/judge/reflector,
                                                             trust machinery
        │                                                                │
        └───────────────────────────┬────────────────────────────────────┘
                                     │
                          M5 convergence: H-20 builds the harness
                          surface on the cut-over TUI card registry
```

Hard ordering facts:

1. **H-01 (headless runner) is the keystone** — the Prober cannot drive a TUI;
   every harnessing ticket after it depends on it.
2. **TUI work needs nothing from Track B** — the adapter's ignore-unknown
   rule (TUI-10) means additive v2 events never crash the new TUI.
3. **H-20 is the only cross-track dependency** — it needs the TUI cut-over
   (TUI-18) *and* the v2 events (H-11).
4. **No autonomous self-modification exists before M4.** Until the policy,
   canary, and Governor tickets land, every harness edit is human
   diff/apply.

## 2. Milestone sequence

| Milestone | Contents | Gate (all must hold) |
|---|---|---|
| **M0 — Foundations** | TUI-01…06; H-01…04 | User-visible behavior identical to `3d32166`; full suite green; prompts load from files, not Python |
| **M1 — Shells** | TUI-07…18 (cut-over); H-05…07 | New TUI is the only TUI, legacy deleted; harness is content-addressed with refs and lineage |
| **M2 — Human-gated harnessing** | H-08…11 | A full campaign runs end-to-end; **every adoption requires manual diff/apply**; v2 events on the stream |
| **M3 — Recursive learning** | H-12…14 | Lessons persist across tasks via the memory graph; parallel/sequential probes with budget k |
| **M4 — Trusted autonomy** | H-15…19 | Tier-2 components may self-adopt behind policy + canaries + budgets; Tier 0 provably uneditable |
| **M5 — Converged surface** | H-20…22 | Harness approvals/campaigns narrated in the TUI; docs and demo scenarios complete |

## 3. Track A — TUI redesign (summary, details in its own plan)

18 tickets, seven phases, ~10–12 focused days. Critical path:
**TUI-01 → 02 → 03 → 04 → 07 → 10 → 11 → 18.** Reuses `client.py` and
`launcher.py` verbatim; rewrites presentation around the approved prototype
(narration spine + run-state rail). The full event→card map, package layout,
parity matrix, and test strategy live in
[TUI-REDESIGN-PLAN.md](TUI-REDESIGN-PLAN.md).

Cross-track obligations baked into Track A:

- TUI-10 adapter **ignores unknown event types** (forward-compat for v2).
- Rail reserves the **HARNESS block**; card registry is data-driven so H-20
  registers new card types without spine changes.
- `arcen-tui --demo` (TUI-03) gains a harness scenario in H-22.

## 4. Track B — ARCEN² harness rebuild (full tickets)

Size scale: S ≤ half day, M ~1 day, L ~2 days, XL ~3–5 days.
Service codenames from [ARCEN2-ARCHITECTURE.md](ARCEN2-ARCHITECTURE.md) §5.

### Phase P0 — Headless + externalized harness (behavior-neutral)

| Ticket | Size | Depends | Deliverable | Verification |
|---|---|---|---|---|
| **H-01** Headless runner (harness refs pending) | L | — | `src/arcen/headless.py`; `arcen run "goal" --json [--harness <ref>] [--workspace <path>]`; shared executor API with `server/app.run_turn`; result envelope + exit codes; no TTY required | headless pytest with mocked LLM; JSON schema test; nonzero exit on `run.error` |
| **H-02** Prompts as files (complete) | M | — | `prompts/system.md`, `prompts/{draft,forge,temper}.md`; `HarnessResolver`; Python-embedded prompt strings removed | fixture-golden compare of assembled prompt payloads before/after; 357-test suite stays green |
| **H-03** Guardrails + tool guidance as files (complete locally) | M | — | `guardrails/policy.yaml`, `tool-guidance.md`; loader with validation; `registry.toml` stays data | invalid policy rejected at boot; effective policy snapshot test |
| **H-04** Harness package + manifest (partial: unsigned foundation) | S | H-02, H-03 | `harness.toml` (component hashes, schema version, model pin); default harness shipped in-repo; `[harnessing]` config section | tampered manifest fails hash check; config round-trip test |

**M0 gate for Track B:** an ordinary interactive run is byte-identical in
behavior and event output to `main`, merely loading its kit from files.

### Phase P1 — Content-addressed harness store

| Ticket | Size | Depends | Deliverable | Verification |
|---|---|---|---|---|
| **H-05** Object store + hashing (local API foundation) | M | H-04 | `harness/model.py`, `harness/store.py`: blob-addressed components, manifest hashing | hash stability test; tamper detection; no two writes of same content duplicate |
| **H-06** Refs + lineage DAG (metadata foundation; selection pending) | L | H-05 | SQLite lineage `(ref, parent, task, trajectories, judge, decision)`; `refs/heads/adopted`, `refs/candidates/*`; `run.start` gains optional `harness_ref` (absent ⇒ adopted) | lineage traversal tests; old session jsonl without the field still replays |
| **H-07** Harness CLI skeleton (inspection only; rollback pending) | M | H-06 | `arcen harness init\|doctor\|diff\|rollback` (read/select ops only) | CLI tests incl. rollback to a prior ref; doctor detects corrupt store |

### Phase P2 — Manual harnessing loop (human gate, no auto-adopt)

| Ticket | Size | Depends | Deliverable | Verification |
|---|---|---|---|---|
| **H-08** Editor (ALLOY) | L | H-06 | `harness/editor.py`: k invariant + k domain-specific proposals as unified diffs over tier-1/2 paths; multi-model panel routing via LiteLLM | mocked editor tests; diffs apply/revert cleanly; no Tier-0 path ever appears |
| **H-09** Prober (QUENCH) | L | H-01, H-08 | worktree clones + fresh quarantine per probe via `sandbox/runtime.py`; empty credential envelope; forced-on `redact_secrets`; **`spawn`/`spawn.done` go live** (closes the T-011 *wiring* gap — module exists, `run_turn` never emitted) | probe isolation tests; creds absent inside probe; spawn events appear in jsonl; depth cap retained |
| **H-10** Contrastive Judge (TOUCHSTONE) | L | H-09 | blind shuffled, anonymized pairwise judging; candidate IDs and editor rationale hidden | blinding test (no provenance leaks into judge prompt); deterministic mocked verdicts |
| **H-11** Campaign runner + v2 events | XL | H-10 | `harness/runner.py` 8-stage flow with resume; `stream/events_v2.py` (all additive types from architecture §8); `arcen harness run\|stop\|status\|resume`; **adoption requires human `apply`** | recorded campaign fixture; interrupt/resume test; legacy client ignores v2 types; rejection path keeps H₀ |

**M2 gate:** a real task can be re-run under proposed harnesses, judged
blind, and the winning diff applied only after explicit human approval.

### Phase P3 — Full recursion

| Ticket | Size | Depends | Deliverable | Verification |
|---|---|---|---|---|
| **H-12** Composer (ANNEAL) | M | H-11 | non-conflicting hunk merge → successor manifest; overlapping hunks returned to Editor | merge/conflict fixture suite; composed manifest hashes verify |
| **H-13** Reflector (SMELT) + improvement library | L | H-11 | Lesson entities in the existing memory graph (decay, temporal validity, conflict rules); generated `library/EXPERIENCE.md` view; each task still starts from H₀ | lesson lifecycle tests; stale lessons expire; library steers a mocked editor |
| **H-14** Recursion modes + task bank | L | H-12, H-13 | `--mode parallel\|sequential`, budget `--k`; `arcen harness task new\|ls\|import`; campaign-level resume under `runs/harness-<id>/` | parallel probe scheduling test; sequential mode carries evidence forward; budget respected |

### Phase P4 — Trust machinery (prerequisite for any autonomy)

| Ticket | Size | Depends | Deliverable | Verification |
|---|---|---|---|---|
| **H-15** Policy engine + immutable core | L | H-08 | `harness/policy.py`: Tier 0 path locks (C2 guardrails, C8 plugins, sandbox/network posture), Tier 1 gated, Tier 2 auto-eligible; forbidden-edit linter; adoption gate | red-team tests: every crafted Tier-0 proposal rejected at two layers; tier matrix test |
| **H-16** Canary bank + auto-rollback | L | H-15, H-14 | graded task bank under `harness/canaries/`; adoption blocked on any regression; live adopted ref auto-rolls-back when canary monitoring fails | seeded regression fixture blocks adoption; rollback restores prior ref |
| **H-17** Governor (GAUGE) | L | H-14 | `--budget-usd/--max-tokens/--k`/wall-clock caps; concurrency limit; early elimination; convergence stop (Δ < ε for 2 rounds); shared prefix caching; kill switch; `budget.usage` events | budget breach aborts campaign; convergence emits no-change outcome; elimination frees probe slots |
| **H-18** Hybrid judge fusion | M | H-16, H-10 | verifier channel (TEMPER verdicts, pytest/type/lint/exit codes) > human > contrastive; confidence threshold τ; Tier-2 auto-adopt path opens only here | each channel's precedence tested; low-confidence result falls back to human/keep-H₀ |
| **H-19** Probe hygiene hardening | M | H-09 | injection scanner over task content; egress allowlist (network stays off by default); secret-envelope and safety-core regression suites | malicious-task fixtures blocked; egress denial tested; no probe can reach host creds |

**M4 gate (the safety release):** Tier-2 self-adoption is possible *only*
with policy + canary + Governor + hybrid judging all enabled; Tier 0 is
provably outside the Editor's writable namespace.

### Phase P5 — Surface, portability, docs

| Ticket | Size | Depends | Deliverable | Verification |
|---|---|---|---|---|
| **H-20** TUI harness surface | L | TUI-18, H-11 | harness cards via the data-driven registry; approval modal (diff/apply/reject) fed by `approval.*`; campaign narration; budget in rail; canary results view | pilot tests for approve/reject; unknown-event compat already proven in TUI-10 |
| **H-21** Portability probes + executor interface | M | H-19 | candidate re-run on a second environment profile; executor adapter interface (ARCEN native first; OpenCode/Codex later, not built) | same candidate judged on two profiles; adapter contract tests |
| **H-22** Docs, demo, canary seeding | S | H-20 | ARCEN² user docs; harness scenario in `arcen-tui --demo`; canary bank seeded from anonymized historical session jsonl | docs link-check; demo runs offline; seed fixtures committed |

## 5. Event contract evolution

- The **17 frozen types never change shape**; `run.start` gains one optional
  `harness_ref` field whose absence means `adopted` (old sessions replay
  byte-for-byte).
- v2 types are strictly additive (`harness.propose`, `harness.policy`,
  `harness.judge`, `harness.compose`, `canary.start/done`,
  `approval.request/resolve`, `harness.adopt/reject/rollback`,
  `budget.usage`; `spawn/spawn.done` reused, not redefined). Full table in
  [ARCEN2-ARCHITECTURE.md](ARCEN2-ARCHITECTURE.md) §8.
- Both the legacy web UI and the new TUI must ignore unknown types; the TUI
  adapter encodes this as a tested rule in TUI-10 and the web client gets a
  matching tolerance test in H-11.

## 6. Combined test strategy

| Layer | Mechanism | Owned by |
|---|---|---|
| Pure renderables | data-in → Rich renderable, no app | TUI-07…09 |
| Event adaptation | recorded session jsonl fixtures replayed through adapter; unknown-event fuzz | TUI-10, H-11 |
| Headless behavior | no-TTY runs against mocked LLM/sandbox | H-01 onward |
| Harness correctness | content-hash, lineage, merge/conflict, policy red-team fixtures | H-05…19 |
| Safety | dedicated suite: Tier-0 edit attempts, credential leakage, injection, egress | H-15, H-19 |
| Backend regression | existing 357 tests re-run before every ticket; never modified for this work | all |
| Visual | env-gated CairoSVG snapshots, structural assertions as the real gate | TUI-03, TUI-17 |

## 7. Consolidated risks

| Risk | Track | Mitigation |
|---|---|---|
| Prompt externalization silently changes model behavior | B | H-02 golden payload diffs; M0 forbids any behavioral delta |
| Probe cost runaway | B | Governor (H-17) before auto-adopt; campaigns always budget-capped |
| Optimizer weakens its own guardrails | B | Tier-0 path locks + linter, red-team tested in H-15 |
| Canary overfitting / flaky gates | B | canary bank versioned; flaky quarantine rules; human override logged |
| v2 events break old clients | both | additive-only contract + ignore-unknown tests on both clients |
| TUI rewrite loses shipped coverage | A | adapter/pilot tests replace the 29 old tests before legacy deletion (TUI-18) |
| Two long branches diverge | both | milestone gates merge to `main`; shared contract tests run on both branches |
| Scope creep into external executors | B | H-21 defines the interface only; OpenCode/Codex adapters are a later plan |

## 8. Decisions needed before kickoff

Carried from both source docs; defaults apply if unanswered.

| # | Decision | Default |
|---|---|---|
| C1 | TUI placement (in-place rewrite vs `tui2` package) | In-place, legacy parked until TUI-18 |
| C2 | Keep `arcen-tui --demo` permanently | Yes |
| C3 | Color support assumption | Truecolor + 256 fallback table |
| C4 | Tier-1 posture in headless CI | Human approval required; auto-apply must be explicitly configured |
| C5 | Canary bank seed | Anonymized historical session jsonl (H-22) |
| C6 | Editor panel model routing | Cheap models for invariant edits, strong models for domain-specific; configurable |
| C7 | Project harness overlays vs global tiers | Overlays may only narrow, never downgrade |
| C8 | Adoption threshold τ / convergence ε | Empirically calibrated in first campaigns; no hard-coded guess |

## 9. Definition of done (whole rebuild)

1. All TUI-01…18 and H-01…22 tickets verified under the TICKETS.md loop and
   merged to `main` through the six milestone gates.
2. Full suite green (357 today, plus all new tests), ruff clean, fresh-venv
   wheel install boots `arcen-tui`, `arcen-tui --demo`, and
   `arcen run --json`.
3. All 17 frozen events render via fixture replay; all v2 events are
   additive and ignored safely by both clients.
4. A complete harness campaign can run, and **no component outside Tier 2 is
   ever changed without explicit human approval**; Tier 0 is provably
   immutable to LLM-proposed edits.
5. Legacy TUI deleted; docs (`TUI.md`, ARCEN² guide), screenshots, and Omarchy
   install instructions current.

## 10. Rough calendar

- Track A alone: **~10–12 working days**.
- Track B alone: **~8–10 focused weeks** (P0/P1 ~2 wks, P2 ~2.5 wks,
  P3 ~1.5 wks, P4 ~2 wks, P5 ~1 wk).
- Run in parallel with one engineer each: wall-clock ≈ Track B, with Track A
  landing inside M1. Solo sequential: ~3 months. Estimates are planning
  anchors, not commitments; the verification-loop gates are the real pace.
