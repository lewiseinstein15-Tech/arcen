# Signed portable harness package (H-04d/e, experimental)

The `package export`, `package verify` and `package import` commands transfer,
inspect or store the **existing seven-component v1 manifest**, component blobs
and detached Ed25519 attestation. Import stores unadopted objects only; it does
not provide runtime selection, adoption, a complete eight-component harness or
a trust root. It requires `arcen[attestation]`.

A package is canonical ASCII JSON with an integer schema version `1`, base64
canonical manifest bytes, base64 detached attestation bytes, and a map of
SHA-256 → base64 component bytes. The verifier requires an independently
supplied expected manifest SHA-256 and raw Ed25519 public key. It rejects
unknown/duplicate fields, noncanonical JSON or base64, incorrect object sets,
component/manifest hash mismatches, bad signatures and oversize input. It
never extracts archive paths; `verify` does not write to a store. The maximum serialized
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

# Initialize the destination first; import requires stdin and stdout to be TTYs.
arcen harness --store /trusted/destination init
arcen harness --store /trusted/destination package import \
  --manifest "$MANIFEST" --public-key "$PUBLIC_KEY" \
  --file /trusted/new-package.json
# After reviewing the warning, type exactly: IMPORT <the full manifest SHA-256>
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

## Import boundary and failure behavior

The CLI verifies the complete bounded package and signature using the supplied
expected ID and key before asking for the exact interactive confirmation. It
retains the verified input bytes, so replacing the input file at the prompt does
not change the imported package. Non-TTY invocations and cancellation fail
without object writes. Import requires an existing initialized store. The
lower-level `import_package` Python API has no human prompt: callers are
responsible for their own authorization and must not expose it to untrusted
automation.

After confirmation the importer re-verifies the retained bytes, checks all
pre-existing relevant objects for integrity, and publishes component objects
and then the canonical manifest using the store's atomic per-object API.
Existing correct objects are reused; conflicting or corrupt ones fail. The
operation is **not transactional**: an I/O failure or interruption may leave
some unreferenced objects or temporary files. Directory fsync and crash
recovery are not guaranteed. No refs, lineage, approval, trust enrollment or
adoption are written; the parent remains an unverified claim. Successful import
itself never executes the contents. Other existing experimental APIs can accept
manifest IDs for separately gated manual testing; a signed or imported package
is not automatically safe or authorized for such use.

The destination store, local filesystem writers, and all parent directories
must be trusted. Preflight is not a lock against concurrent mutation, and no
hostile-filesystem race protection is claimed. Package contents remain
plaintext; storing them may persist sensitive material. Authenticate the public
key and manifest out of band before using this feature.
