# Signed portable harness package (H-04d, experimental)

The `package export` and `package verify` commands transfer or inspect the
**existing seven-component v1 manifest**, its component blobs, and a detached
Ed25519 attestation. This is an offline portability and integrity feature—not
candidate import, runtime selection, adoption, a complete eight-component
harness or a trust root. It requires `arcen[attestation]`.

A package is canonical ASCII JSON with an integer schema version `1`, base64
canonical manifest bytes, base64 detached attestation bytes, and a map of
SHA-256 → base64 component bytes. The verifier requires an independently
supplied expected manifest SHA-256 and raw Ed25519 public key. It rejects
unknown/duplicate fields, noncanonical JSON or base64, incorrect object sets,
component/manifest hash mismatches, bad signatures and oversize input. It
never extracts archive paths or writes into a store. The maximum serialized
package is 10 MiB; each component is bounded by the existing 1 MiB object limit.
The format is versioned but not yet a compatibility promise for future schemas.

```sh
# MANIFEST and PUBLIC_KEY must be authenticated by the operator independently.
arcen harness --store /trusted/store package export \
  --manifest "$MANIFEST" --public-key "$PUBLIC_KEY" \
  --attestation /trusted/attestation.json --output /trusted/new-package.json

# Verification is offline and does not require a store.
arcen harness package verify --manifest "$MANIFEST" \
  --public-key "$PUBLIC_KEY" --file /trusted/new-package.json
```

The attestation is created by trusted code as described in
[HARNESS-ATTESTATION.md](HARNESS-ATTESTATION.md). Export verifies the signature
and every store object before writing. Output is **plaintext**, created with
mode 0600 through a temporary file and exclusive hard-link publication: an
existing destination (including a symlink) is never replaced. The output parent
and local filesystem writers must be trusted. Temporary files may survive a
crash; directory fsync and recovery are not guaranteed. Files can contain
sensitive prompt content, and neither encoding nor the signature provides
confidentiality. Final-component symlinks are rejected for inputs on systems
supporting `O_NOFOLLOW`; parent-directory substitution and hostile filesystem
races are outside this boundary.

A successful signature proves only that the exact manifest and parent *claim*
were signed by the supplied key. It does not authenticate the key or signer,
verify lineage, guarantee package safety, check revocation, establish approval,
make files immutable after verification, or authorize execution/adoption.
The current runtime does not consume this package. The canonical package can be
replayed and copied. Other guardrails, Docker-only isolation and all future
trust/adoption gates remain mandatory.
