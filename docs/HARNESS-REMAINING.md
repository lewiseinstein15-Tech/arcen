# Harness²: remaining work and safety status

Status as of 30 October 2026. This is a work-in-progress branch, not a claim
that the Harness² roadmap is complete. The earlier Omarchy Docker runs covered
the then-current isolation and manual-campaign foundations, using mocked models
and judges. Newer editor, CLI, canary and cleanup paths have not all been
validated on real Docker or against a real external provider. See
`docs/verify/README.md` for the exact evidence and revisions.

## What works now

- Packaged behavior-neutral prompts and immutable guardrail declarations; a
  Docker-only tool boundary with no host-process fallback. Server terminal
  results now wait for strict cleanup; daemon failures can still leave an
  orphan requiring inspection.
- Content-addressed manifests/objects, local lineage and review metadata,
  baseline selection, candidate diff inspection and strict static policy review.
- Explicit interactive manual proposal generation or patch import; a
  reviewed sequential baseline/candidate campaign with local human A/B judging,
  unsigned pending reviews and no automatic adoption.
- Durable journal and shared admission counts; optional stop at stage
  boundaries and budget binding for new CLI campaign plans.
- Two experimental, public and gameable behavioral canaries, with exact file
  checks, not an adoption gate or security proof.
- Locally reviewed experience notes in a memory graph; they are not
  automatically learned or placed into model prompts.

## What remains

1. **H-01 / H-06–07: candidate selection, adoption and rollback.** Candidate
   refs cannot be selected for ordinary runs; review records and user labels
   are unsigned and cannot authorize adoption. Design and implement an
   authenticated human authorization, stale-baseline checks, atomic ref
   updates, lineage, rollback and safe failure behavior. Keep these disabled
   until all mandatory policy and safety checks exist.
2. **H-08–11: complete manual campaign.** The editor uses one model pinned to
   the baseline, not a separate multi-model panel. The probe only supports
   Docker-isolated `bash`, not the full tool set or spawned subagents. Manual
   CLI steps are not one integrated editor→probe→judge→review workflow. Full
   event streams, persistent evidence and safe recovery/resume remain absent.
3. **H-12–14: recursion and learning.** The composer is an offline syntactic
   foundation. It is not connected to an iterative behavioral comparison.
   There is no model-backed reflector, task bank, experience-guided editor,
   parallel candidate scheduling or sequential carry-forward recursion.
4. **H-15–16: adoption safety and canaries.** Static protected-file checks
   exist, but no authoritative policy gate or authenticated approval exists.
   The two small manual canaries are public and easy to game; there is no
   comprehensive adversarial canary bank, tamper-resistant evidence, adoption
   block based on canaries, live monitoring or automatic rollback.
5. **H-17: full Governor.** Durable limits count cooperating admissions and
   have an admission cutoff. They do not enforce a USD/token budget, hard
   runtime deadline, concurrency ceiling, provider billing guarantee,
   in-flight kill switch, early elimination, convergence stopping or caching.
6. **H-18–19: judging and probe hardening.** Reduced/blinded evidence and
   manual judgments do not constitute verifier fusion or a confidence gate.
   Prompt-injection detection, provider egress restrictions, comprehensive
   secret handling and adversarial safety-core checks remain incomplete.
   Model/provider output, repository content and local metadata are untrusted
   for purposes of future automation. Model pin names do not authenticate model
   weights, and local hashes/review labels are not signatures.
7. **H-20–22: surface, portability and release.** There is no integrated
   Harness² campaign TUI. Cross-platform/install checks, CI/release packaging,
   a reproducible end-to-end demo and complete operator documentation still
   need work. New real-Docker paths and any paid-provider integration require
   validation on suitable systems; mock tests are not that validation.

The remote `main` has not received the Harness² branch or its isolation fixes.
A locally downloaded bundle is not a merge or deployment. Preserve Docker-only
fail-closed isolation and leave candidate adoption, automatic resume and
unattended autonomy disabled until the actual gates above are implemented and
verified. Never infer safety or improvement merely from a passing canary,
contrastive judgment, local approval label, content hash or admission counter.
