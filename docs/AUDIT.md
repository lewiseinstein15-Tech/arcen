# Phase 0 audit — baseline 7af6cd0

**Draft: exception-by-exception semantic review is not complete.** No Phase 1 feature code was implemented. The active local baseline is `7af6cd0e440b6e677f5afe84394c8b9ea92fb5be`. On 2026-11-02 `git ls-remote https://github.com/lewiseinstein15-Tech/arcen.git refs/heads/main` returned `4cb3e1a433497a17d7985840aedac56a366d81dc`; remote main does not yet contain the locally audited baseline. These findings apply to the local baseline.

## Scope and evidence limits

`python docs/audit/inspect_repo.py` verifies the inventories in `docs/audit/`. It read all 414 Git-tracked files in the requested directories: 134 `src/arcen`, 133 `tests`, 40 `scripts`, 104 `ui`, 1 `docker`, 2 `.github`. Of these 380 were UTF-8 text and 34 binary. The inventory includes hashes and sizes; all 288 Python files parsed. Reading bytes and extracting syntax is **not** equivalent to manually understanding every file. Ignored, untracked, generated dependency and other directories are outside this inventory. The exception inventory is exhaustive for Python `except` syntax in parsed tracked Python files, not for all ways of suppressing failures; JS/TS and shell line matches are candidates, not an exhaustive parser or verdict. `docs/audit/python-exceptions.tsv` contains 338 handlers and 3 `contextlib.suppress` blocks; `other-catches.tsv` has 22 JS/TS candidate lines and 5 shell candidate lines, including vendor/minified content. Contextual review of every candidate remains open in A-10, so the requested definitive list of every hidden exception is not yet established.

## What the normal turn actually does

* **DRAFT:** `agents/draft.py:272-289` classifies the user's goal. Direct conversation returns an answer with no plan or tool; task turns without a provider refuse. Research/code turns call `_decompose` before FORGE (`:329-347`, `:365-431`). The provider returns a JSON list; DRAFT retains recognized tool names and nonempty `args`, with a strict retry for malformed/non-provider exceptions. ProviderError propagates. Planning is before execution for task turns, not direct replies.
* **FORGE:** `agents/forge.py:54-67` dispatches each step. `server/app.py:288-370` executes a precomputed pending list; tool arguments are the LLM-generated plan's `args` (`:329-332`), not a per-step observation-driven call. Failure may produce at most two replans, with repeated-step guards. This is not an open-ended one-call/observation loop.
* **TEMPER:** `server/app.py:372-379` invokes `TemperVerifier` after successful execution. It repeats the last bash `cmd`, or uses `true` for non-bash. `agents/temper.py:39-87` runs supplied checks through bash and retries failures; it does not independently discover project tests. The last command can be mutating and rerunning it is not independent evidence of correctness. Failure never triggers TEMPER's own repair. The emitted `Usage` has zero tokens and zero cost (`server/app.py:381-383`), not measured spend.
* **Boundary:** normal server execution uses a disposable, network-disabled Docker turn registry; process backend is rejected and only allowed isolated tools dispatch (`sandbox/turn.py:43-59, 173-179`). An explicitly supplied workspace is snapshotted and imported (`server/app.py:269-274`, `sandbox/turn.py:64-73`); the container uses temporary workspace and is removed (`turn.py:86-100, 246-258`). The turn does not export edits back to the host. This safety property must not be weakened to add persistence.

## Inventory and README claims

Reproduce the numbers, tool names and disabled-plugin import fixture with `PYTHONPATH=src python docs/audit/reproduce.py` in an environment with project dependencies. The built-in registry contains exactly **40** names:

`bash`, `code.diff`, `code.eval_expr`, `code.format`, `code.outline`, `code.run`, `data.csv`, `data.json`, `data.jsonl`, `data.toml`, `data.yaml`, `file.append`, `file.copy`, `file.delete`, `file.edit`, `file.glob`, `file.list`, `file.mkdir`, `file.move`, `file.read`, `file.write`, `http.get`, `http.head`, `http.post`, `math.convert`, `math.eval`, `math.stats`, `proc.cwd`, `proc.env`, `proc.time`, `search.files`, `search.replace`, `search.symbols`, `search.text`, `system.info`, `text.count`, `text.hash`, `text.replace`, `text.slice`, `text.wrap`.

Registry count is not normal isolated-turn capability: the current execution policy only permits `bash`. MCP names can be runtime additions; user configuration and external directories are variable.

| Alleged claim | Evidence at this checkout | Assessment |
|---|---|---|
| 500+ sub-agents | README:116; `subagents/agent.py:13-14, 28-29, 49-65, 68-125` | Named task scopes executing FORGE steps, default depth 2/concurrency 8; no 500-agent shipped catalog. Counts of possible names are not a catalog count. |
| 10,000+ skills | README:117; `skills/pytest-repair/SKILL.md`; repository index 1 | One repository skill; additional user skills depend on configured paths. Indexing reads full file bytes (`skills/loader.py:97-100`) although it only retains frontmatter and loads the body as a skill later. |
| 1,000+ tools | `grep -nE '1,000\\+|1000\\+' README.md` returns no match | This claim is **absent** at this baseline; do not call it a current README mismatch. Built-in registry count 40. |
| 300+ MCPs | README:119; default config `src/arcen/config.py:78` | Zero configured servers by default; external configured servers are variable. No evidence of 300 shipped/configured servers. |
| 100+ plugins | README:120; default config `config.py:79`; `plugins/redact_secrets.py` | Zero enabled by default; one built-in redaction plugin exists. User-supplied modules vary. Disabled discovered modules are still imported, demonstrated by the disposable fixture; trusted host plugin paths are not a sandbox. |

`stream/events.py:233-273` lists 17 frozen event types; future changes must preserve them unless the user approves a breaking change.

## Hidden or obscured failures: confirmed examples, not a complete verdict

| Location | Observed handling | Interpretation |
|---|---|---|
| `agents/draft.py:199-202` | non-ProviderError classification exception discarded, heuristic used | cause hidden; ProviderError explicitly reraised |
| `agents/draft.py:323-325` | non-ProviderError direct-reply failure discarded, offline reply used | cause hidden; ProviderError reraised |
| `agents/draft.py:391-398` | first broad exception discarded before strict retry, second becomes generic refusal | cause obscured, not a claim all provider failures are swallowed |
| `server/app.py:218-221` | unexpected exception around `on_boot` dropped | `fire` records ordinary hook failures in loader.errors; outer unexpected failure is silent |
| `mcp/client.py:232-233`; `sandbox/runtime.py:404-409` | cleanup exceptions discarded | diagnostics lost; distinct from strict turn cleanup |
| `harness/progress.py:60` | observer exceptions ignored | intentional observer isolation, no diagnostic |
| `ui/src/components/ChatView.tsx:71,143,206` | polling/replay failures ignored | best effort; persistent failure can be invisible |
| `scripts/dev.sh:32-35,43` | discovery, force-kill and cleanup errors masked | can hide failures; also force-kills unrelated port owners (A-11) |

Some catches are intentional expected control flow or transform exceptions into visible envelopes/events. `tools/registry.py:80-89` returns tool error envelopes and `server/app.py:396-405` emits terminal errors; `server/app.py:410-417` intentionally hides untrusted daemon details while emitting `SANDBOX_CLEANUP_UNCONFIRMED`. They must not all be described as silent defects.

## Ten ranked weaknesses and tickets

Rank is an engineering judgment, not a measured effect size. Acceptance criteria are in `docs/TICKETS.md`.

1. **A-01 — misleading verification:** server repeats last command or `true`; `server/app.py:372-379`.
2. **A-02 — no measured engineering baseline:** no resolved/cost/time baseline was run in Phase 0; passing unit tests are not a benchmark.
3. **A-03 — no safe edit return:** disposable workspace removed with no host patch export (`sandbox/turn.py:86-100,246-258`).
4. **A-04 — disabled plugin files execute at discovery:** `plugins/loader.py:79-100`; verified by isolated fixture. Plugin directories are explicitly trusted host code; this is opt-in semantics, not a demonstrated sandbox escape.
5. **A-05 — literal provider credential sent to enabled on_boot plugin:** `server/app.py:219`, `config.py:107,221,225`. These are trusted host plugins, not external workers; full config expands their access unnecessarily.
6. **A-06 — static plan limits observation-driven adaptation:** `server/app.py:319-370`, `draft.py:415-428`.
7. **A-07 — built-in catalog differs from effective tools:** 40 built-ins vs isolated bash-only dispatch (`sandbox/turn.py:173-179`).
8. **A-08 — usage values are placeholders:** `server/app.py:381-383` emits zeros, so unknown spend is indistinguishable from free.
9. **A-09 — exaggerated counts and skill-loading description:** README:116-120 and `skills/loader.py:97-100`; see table.
10. **A-10 — swallowed errors and incomplete semantic inventory:** confirmed examples above and 338 Python handlers still need individual classification.

Additional tickets: A-11 unsafe `scripts/dev.sh` port killing, A-12 frontend build exited 137 in this environment (investigate rather than assert cause), A-13 provenance/license verification for existing attributions, A-14 React act warnings in tests. These are findings, not permission to implement later-phase features now.

## Verification recorded

* Backend: `TMPDIR=/home/user/.cache/tmp PYTHONPATH=src /home/user/.cache/env13/bin/python -m pytest -o asyncio_default_fixture_loop_scope=function -o addopts='' -q` → **1652 passed, 19 skipped, 9 warnings in 215.62s**. Suite counts are not task-resolution metrics.
* Frontend dependencies: `cd ui && npm ci --ignore-scripts --no-audit --no-fund` → 461 packages added, exit 0. Lifecycle scripts were deliberately not run.
* Frontend: `cd ui && npm test -- --run` → **14 files, 84 tests passed**, 19.99s; React `act(...)` warnings occurred. `npm run build` proceeded through 2,841 modules then printed `Killed`, exit 137; a `NODE_OPTIONS=--max-old-space-size=1024` retry also printed `Killed`. See A-12; cause not established.
* Audit scanner and fixture: see commands above; changed Python files passed `ruff check` and `ruff format`.
* No real Docker executable/socket was available in this environment. Prior laptop Docker results do not prove this new audit revision. No benchmark of resolved %, cost, or task time was run; before/after values are **not measured**.
