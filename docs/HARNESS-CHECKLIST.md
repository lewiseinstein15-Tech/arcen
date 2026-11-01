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
- [x] H-04c: packaged prompts, guardrails and registry metadata consume one
      immutable hash-verified default snapshot, including concurrent startup.
      This does not authenticate the package or implement all components.
- [x] H-04d: signed v1 package export and offline verification with explicit key
      and manifest ID; verification alone does not import, execute or adopt.
      The full eight-component package and trusted runtime integration remain open.
- [x] H-04e: TTY-confirmed verified v1 object import without refs, lineage or
      adoption; no signer enrollment. Object writes are not transactional.
- [x] H-04f: read-only inspection of unregistered manifest objects, with an
      opt-in sanitized diff and bounded output; no trust or execution approval.
- [x] H-11g: guided selection of one to five candidates for a single manually
      confirmed sequential campaign, with lower-bound admission checks. This
      completes only this sub-scope, not H-11, H-14 or the Governor.
- [x] H-14b: reviewed Python-only bounded parallel probe waves over one
      reference and two to five candidates, using an in-process shared budget.
      Mock-verified only; no judge, persistence, selection, adoption, automatic
      resume, durable concurrency, or cross-process guarantees. H-14 remains open.
- [x] H-11h: metadata-only best-effort manual campaign progress in the CLI
      and trusted callback API. Not durable, authenticated, replayable, or
      integrated into the session NDJSON stream; safe resume remains absent.
- [x] H-21a: CI workflow configuration for installed-wheel and opt-in Docker
      validation, structurally tested locally. A remote run is still required;
      this does not complete portability, CI verification or H-21.
- [x] H-19a: reviewed trial snapshots reject exact configured provider keys;
      comparisons and campaigns also reject explicitly supplied known values
      before trial admission. Not a complete secret or injection scanner.
- [x] H-18a: advisory-only fusion of a matched unsigned paired review and
      manual canary report, with negative/inconclusive results taking priority.
      This cannot authenticate evidence or authorize adoption; H-18 remains open.
- [x] H-19c: a narrow task-text injection heuristic rejects selected phrases
      before manual editor callbacks or reviewed probe admission. Easily evaded,
      can block benign tasks, and is not a safety or authorization gate.
- [x] H-19d: extra caller-provided known values are checked in model-bound
      inputs and best-effort redacted from reviewed model/tool evidence.
      This is not comprehensive secret detection; H-19 remains open.
- [x] H-19e: Docker inspection rejects disabled, contradictory or malformed
      no-new-privileges options and unconfirmed key isolation fields. Mocked
      verification only; real-Docker validation remains outstanding.
- [x] H-07a: doctor checks integrity and expected schema of present auxiliary
      SQLite files without creating absent databases. This is not full record,
      cross-database or authorization verification; rollback remains disabled.
- [x] H-20a / H-22a: a clearly simulated offline harness TUI demo and read-only
      renderer for local progress metadata. No live stream, approval or adoption.
- [x] H-21b: CI configuration checks installed import origin and runs selected
      installed-wheel harness/TUI tests outside the checkout; wheel contents
      include the new modules. Remote execution has not been verified.
- [x] H-21c: interactive and Python two-image baseline/candidate comparisons
      share a budget and reject a changed second workspace snapshot. Local
      Docker/provider are mocked; images and evidence remain untrusted claims,
      no executor adapter or adoption gate, and H-21 remains open.
- [x] H-21d: fail-closed availability checks for both local Docker image IDs
      before portability trials; mock-tested only. This is not a reservation,
      image trust verification, safety proof or complete portability validation.
- [x] H-17c / H-21e: a non-reserving admission-minimum check for shared and
      durable budgets; the portability API rejects obvious shortfalls before
      image checks or trials. Capacity can be consumed after the check; H-17
      and H-21 remain open, with no spending or runtime guarantee.
- [x] H-12a: Python-only, explicitly reviewed conflict-editor handoff and
      read-only composition preview. Returned drafts require independent human
      inspection and testing; callbacks and local evidence are untrusted. Full
      behavioral selection and H-12 remain open.
- [x] H-12b: opt-in interactive conflict patch resolution for recorded manual
      campaigns, with local patch-file input, review and separate confirmation.
      No model call, trial, approval or adoption; full H-12 remains open.
- [x] H-12c: optional separately confirmed test plan and manual paired campaign
      for a selected composite. Historical H-12c plans used an invocation-only
      check; they do not acquire a hash retroactively.
- [x] H-12d: new composite plans bind the unsigned recorded workspace hash in
      journal schema v3 and enforce it on later manual starts. Older unbound
      plans remain unbound; no automatic resume, provenance or adoption.
      Automatic behavioral selection, recursion and H-12 remain open.
- [x] H-12e: read-only advisory classification of locally recorded candidate
      wins, ties, losses and rejections. Unsigned, not ranked or automatically
      composed; full behavioral evidence and H-12 remain open.
- [x] H-13a: separately confirmed budget-bound model draft from an operator
      observation and unsigned approved review, followed by independent SAVE.
      No trajectories, autonomous reflection, automatic editor injection or adoption;
      provider validation and the full H-13 ticket remain open.
- [x] H-13b: up to three operator-selected, baseline-matched active notes can
      be separately confirmed as untrusted editor context. No automatic injection,
      safety guarantee or adoption; full H-13 remains open.
- [x] H-17e: opt-in SQLite trial slots for the reviewed parallel Python API,
      with a persisted per-budget cap across cooperating local processes.
      Crashed/uncertain slots are never automatically reclaimed; other APIs can
      bypass this cap. No kill switch, trusted cross-host scheduler or automatic
      resume. Real Docker and remote CI have not been tested. H-17 remains open.
- [x] H-17d: optional per-instance, in-process trial slots for SharedBudget;
      full slots fail without spending, and errors stop the budget. No durable
      concurrency, waiting, kill switch, hard runtime or spending enforcement.
- [x] H-21f: trusted native Docker executor protocol/seam used by paired
      comparisons, with mock contract tests. No selectable external adapter,
      no real-Docker or remote-CI validation, and H-21 remains open.

## Verification still required

- [x] H-12d Docker smoke: user reported 8 passed at `2ff50ba`; see
      `docs/HARNESS-H12D-LAPTOP-TEST.md`. Provider and judgment were mocked;
      H-12 and safe resume remain open.
- [x] H-12c Docker smoke: user reported 4 passed at `db75d86`; see
      `docs/HARNESS-H12C-LAPTOP-TEST.md`. Provider and judgment were mocked;
      H-12 and safe resume remain open.
- [x] H-12 Docker smoke: user reported the mocked and real-daemon cases
      passing on their laptop at `cbb4ac8`. This validates only the prepared
      composed-candidate comparison path, not the full H-12 ticket.

- [ ] Real-Docker validation of the newer editor/CLI/canary, cleanup and guided
      paths on an appropriate machine. Earlier Docker tests covered older APIs.
- [ ] External provider validation; current demonstrations use mocks.
- [ ] Release verification: confirm the remote merge and deploy the Harness²
      work and isolation fixes on an appropriate system.

Do not enable candidate adoption, unattended autonomy or automatic resume until
the corresponding authorization and safety gates exist and have been verified.
