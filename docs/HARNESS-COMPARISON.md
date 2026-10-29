# Experimental reviewed proposal comparison

`run_reviewed_comparison` freezes the provider configuration, validates both
baseline and candidate manifests and prompt sets, and archives the explicitly
selected Git commit **once**. It runs the baseline and candidate sequentially
in two fresh Docker-only containers using copies of that same verified archive,
the same task, provider/model pin and per-trial limits. A changed host working
tree cannot change the second trial's input. Model responses and execution are
not deterministic, and a model name does not authenticate model weights.

After both trials finish without infrastructure/provider errors, the existing
`compare` judge receives reduced, shuffled A/B evidence through a caller-supplied
callback. If the reference errors, the candidate and judge are not called; if
the candidate errors, the judge is not called. A malformed or failing judge
returns no judgment. Redaction and blinding are best effort: task or answer text
can still expose secrets or provenance, and the callback can contact a provider
and incur cost. The caller must separately attest `reviewed_inputs=True` and
`reviewed_judge_inputs=True`; these booleans are **not verified human approval**.

`compare_reviewed_proposals` first applies the offline composer to one or more
editor proposals, then invokes the paired path for a non-conflicting result.
A conflict returns immediately without a candidate, Git snapshot, model call or
judge. Successful composition can leave immutable, unreferenced objects if a
later stage fails. Neither API writes a ref or adopts anything. A judge result
is not proof of quality, a verifier, a canary, an approval or permission to
change the adopted harness.

These are experimental trusted-Python APIs, not an unattended campaign or CLI.
They have no resume, full campaign-level token/USD budget, canaries, rollback,
spawn events or approval interface. The per-trial call cap and command limits
still apply, and TEMPER reruns the last command once inside each disposable
container. Review the commit, prompts and task before provider exposure. The
trusted Docker daemon and image are required, cleanup failure is fatal, and no
host fallback exists. Unit tests use a mocked Docker boundary; the opt-in
real-Docker paired test has not yet been run by the user.
