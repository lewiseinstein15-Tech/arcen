# Experimental probe hygiene

These measures reduce a few accidental exposures in the opt-in Harness² manual
editor and reviewed probes. They are not a security boundary, a comprehensive
injection/secret detector, or an authorization to adopt a candidate. The normal
ARCEN runtime and its P0/M0 model payloads are unchanged.

## Task-text heuristic (H-19c)

Before proposal callbacks, or before a reviewed probe binds a provider, the task
is checked for a short, code-defined list of English instruction-override,
credential-exfiltration and sandbox-bypass phrases, and common role delimiters.
The screen applies Unicode NFKC normalization, removes format characters and
collapses whitespace. A match refuses the operation without echoing the task;
no Git snapshot, Docker container, model call, trial admission, judge or new
review is started by the screened execution. Existing campaign plans and local
input files are not deleted. The manual editor CLI also binds a reviewed probe
model, so its task is checked before provider calls.

This deliberately blocks some benign tasks, including security research quoting
these phrases. There is no override for a matched phrase. The narrow heuristics
are easy to evade by paraphrasing, encoding, translating or splitting an attack;
they do not screen the repository, candidate prompts, tool output or model
output. A non-match does **not** mean the task is safe. Maintain manual review,
isolation and all other safety gates.

## Explicit known values (H-19d)

Python callers of reviewed trials, paired comparisons and manual campaigns can supply up to 31
nonempty sensitive values (`sensitive_values`, each 4–256 Unicode characters).
The exact values, plus the configured provider key, are checked in bounded
workspace archives before trial/container admission, and in model-bound tasks,
prompts and messages before requests. Known exact values are also redacted
best-effort from model output, tool results, trajectories and reduced judge
evidence. Longer values are replaced first to reduce overlap problems. Direct
`bind_probe_model` callers may also supply these values. Invalid values are
rejected, not printed. The credential itself is still necessarily used to
authenticate to the configured provider.

This cannot find unknown, encoded, transformed or split secrets, and does not
cover every possible local file, external provider, callback, log, metadata,
exception or malicious component. Redaction is not a data-loss-prevention
system; partial or related information can still be disclosed. The caller must
supply the values and review the whole workspace, prompts, task, endpoint and
judge before any provider request. The CLI does not currently collect additional
sensitive values; it only supplies the configured provider key. Local metadata
and evidence remain unsigned. Real Docker and external-provider validation of
these new paths remains outstanding.
