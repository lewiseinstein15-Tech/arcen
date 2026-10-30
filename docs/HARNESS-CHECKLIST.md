# Harness² delivery checklist

`[x]` means that the item named on that line is implemented and verified for
its stated scope. `[ ]` means the full original ticket remains incomplete, even
if a useful foundation or partial sub-ticket exists. See
`HARNESS-REMAINING.md`, `REBUILD-MASTER-PLAN.md` and `verify/README.md` for
acceptance criteria, exact evidence and limitations. Do not tick a parent ticket
merely because a sub-scope is complete.

## Full roadmap tickets

- [ ] H-01 — Headless runner with safe candidate selection.
- [x] H-02 — Behavior-neutral prompts externalized to files.
- [x] H-03 — Guardrails and tool guidance externalized (local scope).
- [ ] H-04 — Harness manifest/package and complete configuration integration.
- [ ] H-05 — Content-addressed object-store ticket beyond its local API foundation.
- [ ] H-06 — Refs and lineage, including safe runtime selection.
- [ ] H-07 — Harness CLI including gated rollback.
- [ ] H-08 — Full editor, including multi-model panel routing.
- [ ] H-09 — Full isolated prober, tool and subagent coverage.
- [ ] H-10 — Complete contrastive judge and evidence handling.
- [ ] H-11 — Complete campaign runner, v2 events and safe recovery/resume.
- [ ] H-12 — Evidence-driven recursive composition and conflict resolution.
- [ ] H-13 — Model-backed reflector and safely experience-guided editor.
- [ ] H-14 — Parallel/sequential recursion, budgets and safe campaign recovery.
- [ ] H-15 — Authoritative immutable-core policy and adoption gate.
- [ ] H-16 — Adversarial canaries, adoption block, monitoring and rollback.
- [ ] H-17 — Full Governor: resource limits, concurrency and kill switch.
- [ ] H-18 — Hybrid judging and confidence-based authorization.
- [ ] H-19 — Comprehensive probe hygiene and safety regression hardening.
- [ ] H-20 — Integrated Harness² TUI.
- [ ] H-21 — Portability, CI and packaging validation.
- [ ] H-22 — End-to-end demo and complete operator documentation.

## Completed, narrower sub-scopes

- [x] Docker-only fail-closed isolation foundations; latest server cleanup
      uncertainty hardening is mock-tested and still needs real-Docker validation.
- [x] Local manifest/object/lineage, review, task-bank and manual-experience
      foundations; hashes and review labels are not authenticated evidence.
- [x] Explicitly confirmed manual editor, budget-bound sequential campaign,
      human A/B judge and pending-review workflow; no adoption or safe resume.
- [x] Operator-chosen syntactic composition, including from unsigned local
      campaign summaries; resulting candidates require separate testing.
- [x] H-04a: disabled harnessing configuration rejects unsupported settings and
      non-boolean values; validated config updates fail without side effects.
      H-04 package, signatures and trust remain incomplete.
- [x] H-04b: optional detached Ed25519 manifest-claim signing and explicit-key
      offline verification, including stored component integrity. No trust
      enrollment, authenticated lineage, runtime enforcement or adoption.
- [x] H-11g: guided selection of one to five candidates for a single manually
      confirmed sequential campaign, with lower-bound admission checks. This
      completes only this sub-scope, not H-11, H-14 or the Governor.

## Verification still required

- [ ] Real-Docker validation of the newer editor/CLI/canary, cleanup and guided
      paths on an appropriate machine. Earlier Docker tests covered older APIs.
- [ ] External provider validation; current demonstrations use mocks.
- [ ] Merge and deployment of the local Harness² branch and isolation fixes.

Do not enable candidate adoption, unattended autonomy or automatic resume until
the corresponding authorization and safety gates exist and have been verified.
