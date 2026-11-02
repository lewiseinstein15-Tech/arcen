# Harness²: remaining work and safety status

Status as of 2 November 2026. This is a work-in-progress implementation, not a claim
that the Harness² roadmap is complete. The earlier Omarchy Docker runs covered
the then-current isolation and manual-campaign foundations, using mocked models
and judges. Newer editor, CLI, canary and cleanup paths have not all been
validated on real Docker or against a real external provider. The user later
reported the prepared H-12 composite comparison smoke test passing with real
Docker at `cbb4ac8` (mocked model and judge). See `docs/verify/README.md` for
the exact evidence and revisions.

## What works now

- Packaged behavior-neutral prompts and immutable guardrail declarations; a
  Docker-only tool boundary with no host-process fallback. Server terminal
  results now wait for strict cleanup; daemon failures can still leave an
  orphan requiring inspection. Inspection now rejects disabled or ambiguous
  no-new-privileges and missing/malformed key isolation fields; these newer
  checks need real-Docker validation.
- Content-addressed manifests/objects, local lineage and review metadata,
  baseline selection, candidate diff inspection and strict static policy review.
  Explicit-key signed packages can be verified and manually imported as objects;
  unregistered objects can be inspected without changing refs. A signed package
  can also be verified or interactively imported directly from a specific local
  Git commit, with no checkout or ref change; this is not a complete Git-backed
  object store. None establishes signer trust, safety, execution authorization
  or adoption.
  Doctor also performs SQLite quick-check and schema validation for present
  auxiliary databases; this does not validate all records or evidence.
- Explicit interactive manual proposal generation or patch import; a
  reviewed sequential baseline/candidate campaign with local human A/B judging,
  unsigned pending reviews and no automatic adoption. A guided single-terminal
  flow connects editor, optional manual syntactic composition, up to five
  human-selected sequential comparisons and pending reviews. Campaigns,
  paired comparisons and manual canaries now check each result's local
  baseline, candidate, commit, workspace and terminal status binding before
  further judging or recording. Mismatches stop the current operation; they do
  not authenticate the executor or close a shared budget. Metadata-only,
  best-effort CLI progress reports are not a persistent or authenticated stream.
  A Python-only opt-in bridge can stamp seven existing metadata events onto a
  session emitter. The offline demo and an opt-in live TUI reader can render
  them, including on replay, but the actual server and campaign CLI are not
  wired to produce these events. This bridge does not provide the full v2
  contract, durable history, authorization or resume. The live client drops
  duplicate-key NDJSON and invalid type/sequence envelopes, and applies the
  envelope check to replay; replay JSON duplicate keys are not checked. This
  is not complete payload validation, authentication, resource bounding, or
  protection against a validly shaped malicious stream.
  A separate command can compose human-selected candidates from a completed
  campaign's local summaries.
- Durable journal and shared admission counts; optional stop at stage
  boundaries and budget binding for new CLI campaign plans. Shared and durable
  budgets can check a momentary minimum without reserving capacity; the
  portability API rejects an obvious shortfall before checking images or
  starting trials. An optional in-process SharedBudget cap limits cooperating
  trial concurrency. Opt-in SQLite slots now provide a persistent per-budget
  cap across cooperating local processes using the reviewed parallel Python API;
  other APIs can bypass it, and crashed or uncertain slots are never reclaimed
  automatically. A later stop, expiry or competing consumer may still interrupt.
- Reviewed trial archives reject exact occurrences of the configured provider
  key before Docker or provider calls. Paired/manual campaigns also check
  explicitly supplied sensitive values. Paired/campaign model inputs and
  outputs and tool evidence also use caller-provided known-value checks and
  redaction. An English task-text heuristic blocks selected injection patterns
  but is easily evaded and can block benign tasks. Encoded, split and unknown
  secrets and most injections are not detected; inputs still require review.
  See `HARNESS-PROBE-HYGIENE.md`.
- Two experimental, public and gameable behavioral canaries, with exact file
  checks, not an adoption gate or security proof. An optional advisory combines
  a matching canary result with an unsigned paired review; it does not authorize
  adoption or establish baseline freshness.
- An explicitly confirmed two-image portability comparison can run baseline
  and candidate on two trusted local image IDs under one budget. It matches
  snapshot hashes across profiles and preflights both local image IDs before
  trials, but does not establish independence, safety, authenticated results or
  adoption eligibility. Image availability may change after preflight. Real
  Docker remains untested; see `HARNESS-PORTABILITY.md`.
- A local, plaintext content-addressed task bank usable by manual editor and
  campaign commands; it does not schedule tasks or provide recursion.
- Locally reviewed experience notes in a dedicated plaintext memory graph,
  with an interactive CLI. They are not automatically learned or placed into
  model prompts.

## What remains

1. **H-01 / H-06–07: candidate selection, adoption and rollback.** Candidate
   refs cannot be selected for ordinary runs; review records and user labels
   are unsigned and cannot authorize adoption. Design and implement an
   authenticated human authorization, stale-baseline checks, atomic ref
   updates, lineage, rollback and safe failure behavior. Keep these disabled
   until all mandatory policy and safety checks exist.
2. **H-08–11: complete manual campaign.** The editor uses one model pinned to
   the baseline, not a separate multi-model panel. The probe only supports
   Docker-isolated `bash`, not the full tool set or spawned subagents. The
   guided flow handles up to five manually selected candidates and still requires
   separate confirmations and review; it is not an autonomous or recursive
   campaign. Full event streams, persistent evidence and safe recovery/resume
   remain absent.
3. **H-12–14: recursion and learning.** The composer can combine manually
   chosen editor proposals before a guided comparison, or manually combine
   selected candidates from one completed campaign's unsigned summaries.
   Both merges are syntactic, and the composite needs its own separate trial.
   A Python-only callback can draft replacements for conflicting paths without
   writing them; human review and separate composition remain required. The
   callback can discard unrelated edits and has no network, cost, or safety
   guarantee. A separate recorded-campaign CLI can accept manually authored
   local replacement patches after explicit review. It can optionally create
   and run a separately confirmed, budget-bound composite test. New plans bind
   the unsigned recorded-workspace hash; older unbound plans are not upgraded
   retroactively and do not have the guard. A read-only advisory lists local
   candidate wins, ties, losses and rejections using an explicit unranked rule;
   these unsigned summaries are not independent behavioral evidence or an
   automatic composition decision. It does not automatically resolve conflicts
   or perform trustworthy behavioral-contrast selection.
   An optional model-drafted tentative lesson from an operator-supplied
   observation requires separate provider and save confirmations; it has no full
   trajectory and no automatic editor use. The editor can send up to three
   explicitly selected, reviewed notes as untrusted context, but this is not
   authenticated or safe against all prompt injections. The task bank is a
   manual storage foundation only. A reviewed Python API can now run one
   reference followed by bounded parallel candidate waves with an in-process
   or opt-in durable budget and cooperative persisted trial slots. Identity and
   terminal consistency are checked; a mismatch stops scheduling and retains
   an affected durable slot. This does not authenticate evidence, and a budget
   stop may fail if its database fails. The parallel result reports whether
   this invocation's stop calls returned without error; that does not prove a
   persistent or universal stop. Results have no judging, persistence, CLI, or
   recovery. The user reported a narrow
   real-Docker smoke passing at `51d971a`, with the provider mocked; live
   providers remain untested for this path. There is no
   autonomous reflector, full safe experience-guidance, durable parallel
   campaign scheduler or sequential carry-forward recursion.
4. **H-15–16: adoption safety and canaries.** Static protected-file checks
   exist, but no authoritative policy gate or authenticated approval exists.
   The two small manual canaries are public and easy to game; there is no
   comprehensive adversarial canary bank, tamper-resistant evidence, adoption
   block based on canaries, live monitoring or automatic rollback.
5. **H-17: full Governor.** Durable limits count cooperating admissions and
   have an admission cutoff. They do not enforce a USD/token budget, hard
   runtime deadline, universal cross-process concurrency enforcement, provider
   billing guarantee, in-flight kill switch, early elimination, convergence
   stopping or caching. The opt-in SQLite slot cap does not constrain callers
   that do not use it, and does not recover crashed slots.
6. **H-18–19: judging and probe hardening.** Reduced/blinded evidence and
   manual judgments do not constitute verifier fusion or a confidence gate.
   The task-text heuristic is easily evaded; provider egress restrictions,
   comprehensive secret handling and adversarial safety-core checks remain
   incomplete.
   Model/provider output, repository content and local metadata are untrusted
   for purposes of future automation. Model pin names do not authenticate model
   weights, and local hashes/review labels are not signatures.
7. **H-20–22: surface, portability and release.** A clearly labelled offline
   simulated Harness² TUI demo renders example progress. An opt-in live client
   can render compatible progress events from a stream, but ARCEN's server does
   not yet produce campaign events and there is no integrated campaign control
   or approval surface. GitHub CI passed for baseline `4cb3e1a`, but later
   local changes and the expanded workflow have not been verified remotely.
   Cross-platform/install checks, a real end-to-end demo and complete operator
   documentation still need work. New real-Docker paths and any paid-provider integration require
   validation on suitable systems; mock tests are not that validation.

Check local and remote Git refs for the current merge state. A local checkout or
bundle is not proof of a remote merge or a deployment. Preserve Docker-only
fail-closed isolation and leave candidate adoption, automatic resume and
unattended autonomy disabled until the actual gates above are implemented and
verified. Never infer safety or improvement merely from a passing canary,
contrastive judgment, local approval label, content hash or admission counter.
