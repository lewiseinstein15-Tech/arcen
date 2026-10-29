# Guardrails and tool guidance

H-03 loads the packaged `arcen/guardrails/policy.yaml` at server startup. The
policy is a strict, immutable, process-wide snapshot: missing, unreadable,
malformed, oversized, duplicate-key, unknown-field, or unsafe policies abort
startup. Files and immediate policy directories may not be symlinks. Restart to
pick up a trusted local package edit; there is no policy ref, adoption mechanism,
or untrusted-harness policy editor yet.

The schema fixes the Docker-only security posture in code: no process fallback,
network, host mounts, host process environment, root user, rootfs writes,
privileges, or Linux capabilities. YAML cannot relax these rules. It can only
narrow the `bash` allowlist (including to empty) and lower the code-capped
`max_pids` (1–128), `max_output_bytes` (1,024–262,144, multiples of 1,024),
`max_entries` (0–10,000), and `max_file_bytes` (0–67,108,864). Limits apply to
each turn's container and input workspace snapshot. Docker's inspected PID limit
must match the requested value. The output cap counts combined stdout/stderr.
Workspace byte limits count file contents, not tar metadata. The workspace is
input-only; no files are copied back, and symlinks are rejected. A snapshot is
not atomic: edit the workspace only while ARCEN is not importing it.

The `/api/sandbox/status` response includes a JSON `policy` snapshot and
`supported_tools` derived from the active policy. It describes the intended
validated requirements; `effective: unavailable` means the executor is not
usable. Docker isolation is independently enforced and inspected when a
turn starts, and a trusted Docker daemon is required. The returned JSON is a
copy, not a mutable handle to the runtime policy. The separate `registry.toml`
remains tool metadata; it grants no host-execution authority.

`arcen/tool-guidance.md` holds DRAFT's `plan` and `research` sections. They are
preserved byte-for-byte for M0 prompt compatibility. **They still mention tools
other than bash**, but the current isolated gateway rejects those tools; it
never sends them to the host. Do not interpret prompt guidance or tool registry
metadata as evidence that a tool is implemented inside Docker.

H-03 tests use mocked Docker plus policy boot and enforcement regressions; they
are not a fresh real-Docker isolation proof. See `docs/verify/README.md` for
screenshot provenance and the previously reported Omarchy live tests.
