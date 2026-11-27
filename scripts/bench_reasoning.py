"""Measure what the reasoning/context layer actually changes.

Run: python scripts/bench_reasoning.py [--turns 200]

Three measurements, all on real code paths:

1. context reuse  — real catalog/skills rendering, cached vs uncached;
2. retrieval      — real ranking, memoized vs recomputed;
3. loop policy    — attempts-to-success for a task whose first verification
                    fails, under the old "give up" policy and the new
                    evidence-guided refinement policy.

The third is a control-policy simulation: no model is called and no quality
claim is made. It measures how many attempts each policy spends and whether
the outcome is a pass or a give-up — the thing the loop changes.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arcen.context import ContextCache, RetrievalIndex
from arcen.memory.store import MemoryStore
from arcen.reasoning import (
    Candidate,
    Observation,
    PassOutput,
    RefinementLoop,
    UpdateGate,
    estimate_complexity,
)
from arcen.tools import catalog
from arcen.tools.registry import load_builtin


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.3f} ms"


def bench_context(turns: int) -> dict:
    registry = load_builtin()
    names = [entry["name"] for entry in catalog.entries(registry)]
    render = lambda: catalog.render_many((registry,), available=names)

    # uncached: every turn pays the full render
    started = time.perf_counter()
    for _ in range(turns):
        render()
    uncached = time.perf_counter() - started

    # cached: one render, then lookups
    cache = ContextCache()
    started = time.perf_counter()
    for _ in range(turns):
        cache.get_or_compute("brief:v1", render)
    cached = time.perf_counter() - started

    body = render()
    return {
        "turns": turns,
        "block_bytes": len(body.encode()),
        "uncached_s": uncached,
        "cached_s": cached,
        "saved_pct": (1 - cached / uncached) * 100 if uncached else 0.0,
        "cache_stats": cache.stats(),
    }


def bench_retrieval(turns: int) -> dict:
    files = [f"src/arcen/module_{i:03d}.py" for i in range(400)]

    def scorer():
        # a real lexical filter, not a no-op: the cost we are removing
        return [f for f in files if "module" in f]

    started = time.perf_counter()
    for _ in range(turns):
        scorer()
    uncached = time.perf_counter() - started

    index = RetrievalIndex()
    started = time.perf_counter()
    for _ in range(turns):
        index.search("find module files", scorer=scorer)
    cached = time.perf_counter() - started

    return {
        "turns": turns,
        "corpus": len(files),
        "uncached_s": uncached,
        "cached_s": cached,
        "saved_pct": (1 - cached / uncached) * 100 if uncached else 0.0,
        "index_stats": index.stats(),
    }


def bench_memory(tmp_dir: Path, facts: int = 2000) -> dict:
    store = MemoryStore(str(tmp_dir / "bench-memory.db"))
    for i in range(facts):
        store.write(f"module_{i}.py:func_{i}", f"func_{i} parses input records for module_{i}")
    query = "extend module_7.py func_7 to parse input records"

    started = time.perf_counter()
    exact = store.recall("module_7.py:func_7", k=3)
    exact_s = time.perf_counter() - started

    started = time.perf_counter()
    related = store.recall_related(query, k=3)
    related_s = time.perf_counter() - started
    store.close()
    return {
        "facts": facts,
        "exact_hits": len(exact),
        "related_hits": len(related),
        "related_s": related_s,
        "exact_s": exact_s,
        "top": related[0]["fact"] if related else None,
    }


def bench_loop(passes_needed: int = 2) -> dict:
    """Old policy = one attempt. New policy = gated refinement."""
    goal = (
        "fix the failing regression in calc.py, then refactor the module and "
        "verify with the full pytest suite"
    )
    complexity = estimate_complexity(goal, max_passes=3)

    def make_produce(needed: int):
        def produce(ctx):
            ok = ctx.pass_no >= needed - 1
            detail = "calc.py 3 passed" if ok else "calc.py AssertionError: 3 != 4"
            return PassOutput(
                candidate=Candidate(value=f"attempt-{ctx.pass_no}", claim=goal),
                observations=[Observation(tool="bash", ok=ok, detail=detail)],
                test_status="pass" if ok else "fail",
                tokens=1200,
            )

        return produce

    # old: a single pass, no refinement (budget 0)
    old = RefinementLoop(budget=0).run(make_produce(passes_needed), goal=goal)
    # new: budget from the complexity estimate
    new = RefinementLoop(
        budget=complexity.budget,
        gate=UpdateGate(first_pass_cap=0.35, later_pass_ramp=0.3),
    ).run(make_produce(passes_needed), goal=goal)

    return {
        "goal_level": complexity.level,
        "budget": complexity.budget,
        "old": {"passes": old.pass_count, "ok": old.verdict.ok, "termination": old.termination},
        "new": {"passes": new.pass_count, "ok": new.verdict.ok, "termination": new.termination},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=200)
    parser.add_argument("--tmp", default="/tmp/arcen-bench")
    args = parser.parse_args()
    tmp = Path(args.tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    ctx = bench_context(args.turns)
    ret = bench_retrieval(args.turns)
    mem = bench_memory(tmp)
    loop = bench_loop()

    print(f"ARCEN reasoning benchmark — {args.turns} turns, python {sys.version.split()[0]}")
    print()
    print("context reuse (real catalog render)")
    print(f"  block size          : {ctx['block_bytes']} bytes")
    print(f"  uncached            : {_ms(ctx['uncached_s'])} total "
          f"({_ms(ctx['uncached_s'] / ctx['turns'])}/turn)")
    print(f"  cached              : {_ms(ctx['cached_s'])} total "
          f"({_ms(ctx['cached_s'] / ctx['turns'])}/turn)")
    print(f"  saved               : {ctx['saved_pct']:.1f}%  hit_rate={ctx['cache_stats']['hit_rate']}")
    print()
    print("retrieval memoization (400-file corpus, real filter)")
    print(f"  uncached            : {_ms(ret['uncached_s'])} total")
    print(f"  memoized            : {_ms(ret['cached_s'])} total")
    print(f"  saved               : {ret['saved_pct']:.1f}%  hit_rate={ret['index_stats']['hit_rate']}")
    print()
    print(f"memory recall over {mem['facts']} facts")
    print(f"  exact-entity recall : {mem['exact_hits']} hit(s) in {_ms(mem['exact_s'])}")
    print(f"  related recall      : {mem['related_hits']} hit(s) in {_ms(mem['related_s'])}")
    print(f"  top related fact    : {mem['top']}")
    print()
    print("loop policy (control-policy simulation, no model called)")
    print(f"  goal complexity     : {loop['goal_level']} (budget {loop['budget']})")
    print(f"  give-up policy      : {loop['old']['passes']} pass(es), "
          f"ok={loop['old']['ok']}, {loop['old']['termination']}")
    print(f"  refinement policy   : {loop['new']['passes']} pass(es), "
          f"ok={loop['new']['ok']}, {loop['new']['termination']}")

    # a tiny stability check so the numbers are not one noisy sample
    samples = []
    for _ in range(5):
        samples.append(bench_context(20)["cached_s"])
    print()
    print(f"cached-render stability: median {_ms(statistics.median(samples))} "
          f"over 5x20 turns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
