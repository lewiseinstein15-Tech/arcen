# Offline contrastive judge foundation

H-10 provides a standalone `compare` API for two supplied trajectories. It
builds reduced evidence from answers, pass/fail checks, command exit status and
terminal status; omits tool arguments, raw command output, diffs, explicit
candidate IDs, costs and editor reasoning; randomly swaps A/B; and asks a
caller-supplied callback for a strictly validated winner, confidence and reason.
Known trajectory identifiers, caller-supplied sensitive strings and certain
secret-shaped patterns are replaced before the callback. The output maps A/B
back to reference/candidate without enabling adoption. Inputs and judge output
are bounded, malformed responses fail closed, and no network or model client is
created by this module.

**Blinding and redaction are best effort, not a confidentiality guarantee.**
An answer or task may itself reveal provenance, include unknown secrets or
contain adversarial instructions. Pattern redaction is incomplete. The
caller must decide whether its evidence may be shared with a model provider.
The judge's result is not a verifier, policy decision, approval, or proof of
improvement. The experimental manually reviewed comparison API can pass it
reduced evidence from two trial trajectories and a caller-supplied callback.
Manual campaigns, experimental canaries and advisory-only fusion are now
available, but there is no built-in model judge or authoritative adoption gate.
See `HARNESS-FUSION.md`. The newer canary and guided paths need real-Docker
validation. H-10 remains partial until its full evidence and safety requirements
exist.
