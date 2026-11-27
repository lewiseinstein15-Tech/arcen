# Adapting GLM-5.4's intelligence architecture to ARCEN

Source: Z.ai, *Toward Generalized Coding with Our First Loop Transformer*,
published 2026-11-23. This document maps each published idea onto an ARCEN
component, states what transfers, states what cannot, and gives the measured
cost of each choice.

The hard constraint holds throughout: this is ARCEN's architecture. No JEXI
identity, branding, personality, or component is involved, and none of the
code below assumes a particular vendor's model.

## What GLM-5.4 actually published

| Idea | What it is | Where it lives |
| --- | --- | --- |
| Loop Transformer | One shared block of layers executed repeatedly; *loop depth* scales alongside parameter count | Model weights / inference |
| Per-iteration gates | Each loop iteration writes its update through a learned gate; early iterations write conservatively, later ones write full refinements | Model weights |
| KV sharing across loops | Later iterations reuse earlier iterations' KV state | Inference engine |
| Sparse-attention index reuse | The first pass computes which tokens matter; later passes reuse that index | Inference engine |
| Generalized coding | Beyond code: self-narrated music video, 6-axis robotic arm CAD in FreeCAD | Model capability |

Five of these are properties of a trained network and its inference engine.
A hosted chat-completion API exposes none of them: no layer reuse, no gate
weights, no KV cache, no attention indices. Anything claiming otherwise in
an agent codebase is marketing.

What *does* transfer is the control policy around repeated refinement — how
much depth a task deserves, whether a pass is applied, how a pass is judged,
and when to stop. That is what ARCEN implements, at the level of artifacts
and evidence instead of hidden states.

## Mapping

| GLM-5.4 idea | ARCEN equivalent | Module | Status |
| --- | --- | --- | --- |
| Loop depth scales with difficulty | Complexity estimate → refinement budget | `reasoning/complexity.py` | implemented |
| Per-iteration gated updates | `UpdateGate`: preserve / modify / replace / request-evidence, with a `write_weight` | `reasoning/gate.py` | implemented |
| Shared block executed repeatedly | One produce→verify→gate block re-entered with the previous contradictions | `reasoning/loop.py` | implemented |
| KV reuse across iterations | Rendered context blocks cached per content version; retrieval memoized per `(query, corpus version)` | `context/cache.py`, `context/retrieval.py` | implemented |
| Sparse-attention index reuse | Retrieval rankings reused across refinement passes, invalidated on `bump()` | `context/retrieval.py` | implemented |
| Long-horizon stability | Atomic per-pass checkpoints under `~/.arcen/checkpoints` | `reasoning/checkpoint.py` | implemented |
| Single-vendor risk | Ordered provider fallbacks, per-agent models | `llm/fallback.py`, `config.py` | implemented |
| Vision-grounded verification | Capability probe + content-part messages; refuses when the model cannot see | `llm/vision.py` | implemented |
| Learned gates | — | — | **not reproducible** without weights |
| Loop-level KV sharing | — | — | **not reproducible** through a chat API |

## The five pieces, and why each is shaped the way it is

### 1. Complexity → budget (`reasoning/complexity.py`)

A lexical scorer produces `simple` / `moderate` / `complex` and a refinement
budget clamped by `reasoning.max_passes` (default 3, i.e. one attempt plus up
to two refinements). A one-file goal gets zero refinements; a multi-stage
repository goal gets two.

Deterministic on purpose: a model call to decide "is this hard?" costs
tokens, cannot be unit-tested, and cannot be audited. The estimator is
coarse, and it says so.

### 2. Gated updates (`reasoning/gate.py`)

A refinement is never applied wholesale by default. The gate classifies it:

- `preserve` — verified, no contradictions: keep what you have;
- `modify` — evidence contradicts part of the candidate: accept the
  refinement, weighted by `write_weight`;
- `replace` — contradicted *and* confidence below the floor: patching would
  keep the error, so take the refinement whole;
- `request_info` — no executable evidence exists: refining now would be the
  model grading its own homework.

`write_weight` follows the published observation that first passes write
conservatively (`min(first_pass_cap, 1 - confidence)`) and later passes open
up (`+ later_pass_ramp` per pass). It is a scheduling heuristic derived from
verification evidence, not a probability, and the code says so.

At the turn level a candidate is a whole attempt — a plan plus the files it
wrote — so "partial application" means the gate decides whether the new
attempt is accepted at all, and records the weight it would have applied.
Blending two file sets is not a thing a repository wants; a wrong half-merge
is worse than either attempt.

### 3. The loop (`reasoning/loop.py`)

One block, re-entered:

```
produce → verify → gate → (refine | stop)
```

Bounded four ways: the complexity budget, `max_passes`, a two-pass no-gain
streak, and best-so-far acceptance. That last one matters most: the accepted
candidate is the highest-scoring pass ever seen, never simply the last one,
so a refinement that makes things worse cannot become the answer. A pass that
raises rolls back to the previous candidate and terminates with `error`.

### 4. Evidence-first verification (`reasoning/verify.py`)

Two rules:

1. Deterministic checks decide — test status, failed steps, whether the files
   the goal named were actually touched, whether a numeric claim ("2 passed")
   appears in real output.
2. A model review can only **downgrade**. `combine()` conjoins; a reviewer
   saying "looks fine" can never overrule a failed test.

`independent` is reported honestly: `True` only when the reviewer ran on a
different model than the producer. With a single provider it is `False`, and
the stream says so rather than implying an independence that does not exist.

### 5. Context reuse (`context/`)

Not a KV cache. The recomputed things in an agent are rendered prompt blocks
and retrieval rankings:

- `ContextCache` keys blocks by content fingerprint, deduplicates identical
  text, and evicts by LRU under entry and byte limits;
- `RetrievalIndex` memoizes rankings per `(normalized query, corpus version)`
  and drops everything on `bump()` — a stale ranking is worse than a recompute.

## Wiring in a real turn

`run_turn` in `server/app.py` now:

1. recalls related facts (`MemoryStore.recall_related`) and emits
   `memory op=recall` — memory was write-only before this;
2. renders the tool catalog and skills index through `ContextCache`, keyed by
   a fingerprint of tools, skills, workspace import and MCP servers;
3. wraps plan → execute → verify in `RefinementLoop`. A failed verification
   re-plans with the verifier's contradictions, executes, and re-verifies;
   the loop accepts the best attempt;
4. narrates the loop with two existing event types (`think` from DRAFT and
   TEMPER) — the frozen 17-type schema is untouched;
5. writes one checkpoint per pass when `reasoning.checkpoints` is on.

## Measured cost and benefit

`python scripts/bench_reasoning.py` on this machine (Python 3.13, 200 turns):

| Measurement | Before | After | Change |
| --- | --- | --- | --- |
| Catalog + skills block render (5,876 B) | 9.78 ms/turn | 0.042 ms/turn | −99.6% |
| Retrieval over a 400-file corpus | 12.5 µs/query | 1.5 µs/query | −88.0% |
| Related-memory recall over 2,000 facts | not possible (exact entity only) | 15.3 ms/query, 3 hits | new capability |
| Loop policy on a task whose first verification fails | 1 pass, `ok=False`, give up | 2 passes, `ok=True`, verified | outcome changes |

The loop row is a control-policy simulation: no model is called, so it
measures attempts and outcomes, not answer quality. The other three are real
timings of real code.

## What this does not do

- It does not make ARCEN a Loop Transformer. There is no weight sharing and
  no looped hidden state.
- It does not improve a model's raw reasoning. It changes how many attempts
  ARCEN spends and how it decides to stop.
- It does not verify by opinion. A review without evidence cannot pass work.
- It does not touch the frozen event schema, the sandbox policy, or the
  three-role agent model (`ROLE_AGENTS`: planner / executor / verifier).

## Configuration

```yaml
reasoning:
  enabled: true
  max_passes: 3          # first attempt + up to 2 refinements
  min_gain: 0.05         # stop when a pass improves confidence by less
  first_pass_cap: 0.35   # conservative first write
  later_pass_ramp: 0.3   # opened gates on later passes
  confidence_floor: 0.6  # below this, replace instead of patch
  independent_review: true
  checkpoints: true
provider:
  vision_model: ""       # set to a multimodal model id to enable image checks
  fallbacks: []          # ordered alternates, tried only on provider failure
```
