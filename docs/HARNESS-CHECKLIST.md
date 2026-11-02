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
- [x] H-05a: inspect or interactively import an explicitly signed v1 package
      from a full local Git commit without checkout, hooks, ref changes or
      adoption. The key and repository are trusted; this is not a complete
      Git-backed store, authenticated lineage or full H-05.
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
- [x] H-17f: parallel-probe error handling reports whether its budget-stop calls
      returned without error; failed stops end local scheduling and are not
      presented as successful global stops. Mock-tested; no in-flight kill,
      universal budget enforcement or complete H-17.
- [x] H-14c: parallel probes reject mismatched or malformed result attribution
      and terminal status; an uncertain durable trial retains its slot. Mocked
      Docker/provider tests only. In-flight work may continue; H-14 remains open.
- [x] H-14b: reviewed Python-only bounded parallel probe waves over one
      reference and two to five candidates, using an in-process shared budget.
      Mock-verified only; no judge, persistence, selection, adoption, automatic
      resume, durable concurrency, or cross-process guarantees. H-14 remains open.
- [x] H-11k: reviewed probe results require exactly one final terminal event,
      consistent with claimed status; malformed event envelopes and earlier
      terminals are rejected in campaign, comparison, canary and parallel
      attribution, and paired review recording. This does not authenticate
      events, validate their payloads, prove isolation, or enable adoption or
      recovery. H-11 remains open.
- [x] H-11j / H-21g: manual campaigns, reviewed paired comparisons and manual
      canaries reject locally misattributed probe results before judging or
      recording them. Tests mock provider and Docker. This checks result shape
      and bindings, not authenticity, sandbox integrity, adoption or recovery.
      H-11 and H-21 remain open.
- [x] H-11i: opt-in metadata-only v2 progress bridge on the existing session
      emitter, with strict decoding and optional TUI registration. The offline
      demo and opt-in live reader use it; the server and CLI do not emit it.
      It is not the complete v2 contract, durable evidence, approval or recovery.
      H-11 remains open.
- [x] H-11h: metadata-only best-effort manual campaign progress in the CLI
      and trusted callback API. Not durable, authenticated, replayable, or
      integrated into the session NDJSON stream; safe resume remains absent.
- [x] H-21a: CI workflow for installed-wheel and real-Docker validation. GitHub
      run 41356481120 passed for the earlier `4cb3e1a` baseline; later workflow
      changes have not been run remotely. This does not complete H-21.
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
- [x] H-16c: the fixed canary verifier opens its final output path with
      no-follow/nonblocking flags and checks/reads the same descriptor, closing
      an lstat-then-open symlink race. Local Linux tests only; shared-workspace
      interference, hard links, compromised images, authenticity, adoption and
      rollback remain out of scope. H-16 stays open.
- [x] H-16b: manual canaries reject obvious admission shortfalls before Git,
      provider or Docker work and treat non-boolean verifier flags as
      inconclusive. This is a non-reserving snapshot, not a guarantee of
      completion, spend or safety; no adoption or rollback. H-16 remains open.
- [x] H-15a: static review fails on inconsistent code-defined tier/editable
      allowlists, and optional read-only inspection reports changed tiers.
      This is advisory only; no policy authority, approval, adoption or runtime
      candidate selection. H-15 remains open.
- [x] H-19k: probe snapshots reject any effective local Git filter configuration
      before `git archive`, including included config and inert filters. Real
      smudge-filter control tested; local Git/config/filesystem must be trusted
      and stable. This is not an OS-level execution sandbox; H-19 remains open.
- [x] H-19j: the shared local Git object reader disables promisor lazy fetch
      for probe snapshots and signed-package reads, and fails if Git lacks that
      option or needed objects are absent. This trusts local Git, repository and
      configuration; it is not OS-level egress isolation. H-19 remains open.
- [x] H-19i: TUI live-stream HTTP error bodies are closed without being read;
      a 409 compaction reset occurs at most once with a resume hint, and an
      unresolved compaction halts the stream. No global HTTP, retry, total
      memory or remote-run control guarantee; H-19 remains open.
- [x] H-19h: the TUI bounds the raw body and top-level event count of session
      replay; rejects compressed, invalid, duplicate-key and non-finite JSON;
      and halts initial restore on these protocol errors. Transport chunks,
      parsed-object expansion, other endpoints and total UI memory are not
      bounded; no authenticity or safe campaign resume is established.
- [x] H-19g: the TUI's successful live NDJSON reader bounds each pending line
      to 1 MiB, refuses encoded streams and halts on oversized lines without
      skipping forward or retrying automatically. Replay, error bodies,
      transport chunks and total UI memory remain unbounded; H-19 remains open.
- [x] H-19f: the TUI discards malformed event envelopes in live streams and
      session replay, and duplicate-key JSON in live NDJSON. H-19h adds replay
      duplicate-key rejection. Neither is authentication, complete payload
      validation, comprehensive resource bounding or safe resume; H-19 remains open.
- [x] H-19e: Docker inspection rejects disabled, contradictory or malformed
      no-new-privileges options and unconfirmed key isolation fields. Mocked
      verification only; real-Docker validation remains outstanding.
- [x] H-07a: doctor checks integrity and expected schema of present auxiliary
      SQLite files without creating absent databases. This is not full record,
      cross-database or authorization verification; rollback remains disabled.
- [x] H-20a / H-22a: a clearly simulated offline harness TUI demo and read-only
      renderer for local progress metadata. No live stream, approval or adoption.
- [x] H-20b: opt-in live TUI rendering of validated, unsigned v2 progress
      received from a compatible stream, including reconnect and session replay.
      Mock-server tested; the real server does not yet emit campaign progress.
      No campaign controls, approval, adoption or complete H-20.
- [x] H-21b: CI configuration checks installed import origin and runs selected
      installed-wheel harness/TUI tests outside the checkout; wheel contents
      include the new modules. The earlier CI baseline passed remotely; the
      subsequently expanded selected suite has not yet run remotely.
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
      resume. A narrow real-Docker smoke passed on the laptop with the provider
      mocked; remote CI has not been tested. H-17 remains open.
- [x] H-17d: optional per-instance, in-process trial slots for SharedBudget;
      full slots fail without spending, and errors stop the budget. No durable
      concurrency, waiting, kill switch, hard runtime or spending enforcement.
- [x] H-21f: trusted native Docker executor protocol/seam used by paired
      comparisons, with mock contract tests. No selectable external adapter,
      no real-Docker or remote-CI validation, and H-21 remains open.

## Verification still required

- [x] H-17e real-Docker parallel smoke: user reported 21 passed, no skips at
      `51d971a`; see `HARNESS-H17E-LAPTOP-TEST.md`. The provider was mocked;
      crash recovery, live providers and full H-17 remain unverified.

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
