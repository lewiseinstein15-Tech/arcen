# Detached manifest attestations (H-04b, experimental)

The optional `arcen[attestation]` extra adds an Ed25519 detached attestation
for the existing version-1 content-addressed manifest. The packaged default
`harness.toml` is **still unsigned**; ordinary startup, selection, probing,
review and adoption do not use these attestations. This is not a signing or
trust-root solution for the complete H-04 package.

An attestation signs the canonical manifest's SHA-256 ID, a nullable parent ID
and the SHA-256 fingerprint of the raw 32-byte Ed25519 public key. The signer
claims the parent; verification does **not** establish that the parent exists,
is authorized, or is a real lineage edge. There is no identity verification,
key enrollment, rotation, revocation, timestamp, expiry, anti-replay, chain
validation, policy check, or safety/improvement assessment. The user must
independently authenticate the exact public key before using it. A compromised or
mistaken signer can sign a malicious manifest. A valid result never authorizes
selection or adoption.

## API and verification

Trusted code with an independently managed `Ed25519PrivateKey` may call
`create_attestation(manifest_id, parent_id_or_none, private_key)` to produce
canonical bytes. **This function signs claims only; it does not check that the
objects exist.** Key generation, custody, signing authorization and storage are
outside ARCEN. Do not share or print a private key. The verification CLI takes a
public key, not a private key:

```sh
# The attestation is canonical JSON, without a trailing newline.
# PUBLIC_KEY_HEX is the independently authenticated raw public key (64 lowercase hex characters).
arcen harness --store /path/to/existing/store attestation verify \
  --manifest "$MANIFEST_SHA256" --file /path/to/attestation.json \
  --public-key "$PUBLIC_KEY_HEX"
```

The verifier requires an existing initialized trusted local store, a bounded
regular attestation file (final symlinks rejected on platforms with
`O_NOFOLLOW`), the expected manifest ID, and the explicit public key. It checks
strict canonical encoding and the signature first, then reads and verifies the
canonical manifest and all referenced component hashes. A nonzero exit means
no verified result. The store, its directory hierarchy, the executing process,
cryptographic library and caller-supplied public key are trusted; filesystem
races or mutations after checking are not prevented. The command does not alter
refs or install a trust anchor. Existing SQLite and object-store assumptions
still apply.

## Wire format

The input is a single UTF-8 JSON object, no whitespace, sorted keys, ASCII
escaping, exactly these six fields: `schema_version` integer `1`, `algorithm`
`"ed25519"`, `manifest` lowercase 64-hex, `parent` null or lowercase 64-hex
(not equal to `manifest`), `public_key_sha256` lowercase 64-hex, and
`signature` lowercase 128-hex. Duplicate/unknown fields and noncanonical
encodings are rejected. The signed message is the fixed byte string
`ARCEN-HARNESS-ATTESTATION\x00v1\x00` followed by the same canonical JSON with
the `signature` field omitted. Fingerprinting is SHA-256 over the raw public-key
bytes. Domain separation prevents this signature from being accepted as an
ARCEN attestation for a different protocol. Compatibility or trust of future
schemas is not implied.
