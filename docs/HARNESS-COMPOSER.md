# Offline harness composer (H-12 foundation)

`compose_proposals(store, baseline_id, proposals)` combines one to ten editor
`Proposal` objects that each apply independently to the same verified baseline.
It rechecks each exact diff, source hash and result, verifies the packaged
protected policy and registry, validates the complete prompt set, and preserves
the baseline model pin. Proposals can change only the editor's prompt/guidance
allowlist.

Distinct, non-touching base-line edits can be merged within a file, while
identical edits are deduplicated. Overlapping or touching edits—including
competing insertions at the same boundary—are conservatively returned as
`Conflict(path, first, second)` records with zero-based proposal indices. On
conflict it returns no candidate ID and writes no objects. In the guided manual
workflow, an operator can choose generated proposals for composition, inspect
the resulting diff, and separately confirm a comparison. The workflow reports
conflicts and stops; it does not resolve them. A no-conflict result creates
immutable content-addressed blobs and a successor manifest; it never changes a
ref or records a lineage decision. A storage failure can leave unreferenced blobs.

This is a **syntactic** merge, not an assessment of prompt compatibility,
correctness, safety or improvement. Candidates are unapproved. The standalone
composer does not run a model, probe, judge, canary or approval. The separate
reviewed proposal-comparison API can compose and then run experimental paired
trials; candidate runtime selection and adoption still fail closed. Guided
composition happens before comparison of its inputs and is not evidence-based.
H-12 remains incomplete until behavioral-contrast selection, iterative campaign
integration and conflict resolution are implemented.

A separate interactive `campaign compose` command can reconstruct and combine
operator-selected candidates from one completed campaign's locally recorded
comparison summaries. The local summaries are unsigned, full trajectories
are not retained, and the newly combined candidate must be tested separately.
See `HARNESS-RECORDED-COMPOSITION.md`; this is not automatic behavioral
selection, authenticated evidence or adoption.
