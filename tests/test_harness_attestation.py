"""Detached signatures authenticate claims only against an explicit key."""

from __future__ import annotations

import builtins
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arcen.harness.attestation import (
    MAX_ATTESTATION_BYTES,
    create_attestation,
    verify_attestation,
)
from arcen.harness.cli import _init
from arcen.harness.resolver import HarnessError
from arcen.harness.store import HarnessStore


@pytest.fixture
def signed(tmp_path):
    root = tmp_path / "store"
    digest = _init(str(root))
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))  # TEST KEY ONLY
    public = key.public_key().public_bytes_raw()
    parent = "a" * 64
    return HarnessStore(root), digest, parent, key, public


def encoded(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def test_signature_binds_manifest_parent_key_and_verifies_objects(signed):
    store, manifest, parent, key, public = signed
    data = create_attestation(manifest, parent, key)
    result = verify_attestation(store, manifest, data, public)
    assert result.manifest == manifest and result.parent == parent
    assert result.public_key_sha256 == hashlib.sha256(public).hexdigest()
    assert create_attestation(manifest, parent, key) == data  # Ed25519 is deterministic
    # A signed null parent is supported; it is a claim, not proof of a root.
    assert (
        verify_attestation(store, manifest, create_attestation(manifest, None, key), public).parent
        is None
    )


def test_signature_has_an_independent_domain_separated_payload(signed):
    _, manifest, parent, key, public = signed
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    doc = json.loads(create_attestation(manifest, parent, key))
    signature = bytes.fromhex(doc.pop("signature"))
    payload = b"ARCEN-HARNESS-ATTESTATION\x00v1\x00" + encoded(doc)
    Ed25519PublicKey.from_public_bytes(public).verify(signature, payload)
    assert payload.startswith(b"ARCEN-HARNESS-ATTESTATION\x00v1\x00")


@pytest.mark.parametrize(
    "field,value",
    [
        ("parent", "b" * 64),
        ("manifest", "c" * 64),
        ("signature", "0" * 128),
        ("public_key_sha256", "d" * 64),
        ("schema_version", 2),
        ("algorithm", "other"),
    ],
)
def test_modified_signed_fields_fail(signed, field, value):
    store, manifest, parent, key, public = signed
    doc = json.loads(create_attestation(manifest, parent, key))
    doc[field] = value
    with pytest.raises(HarnessError):
        verify_attestation(store, manifest, encoded(doc), public)


def test_attacker_cannot_replace_key_fingerprint_and_signature(signed):
    store, manifest, parent, key, public = signed
    attacker = Ed25519PrivateKey.generate()
    forged = create_attestation(manifest, parent, attacker)
    with pytest.raises(HarnessError, match="public key"):
        verify_attestation(store, manifest, forged, public)
    with pytest.raises(HarnessError, match="public key"):
        verify_attestation(store, "f" * 64, create_attestation(manifest, parent, key), public)


def test_bad_serialization_and_duplicate_keys_rejected(signed):
    store, manifest, parent, key, public = signed
    data = create_attestation(manifest, parent, key)
    doc = json.loads(data)
    bad = [
        data + b"\n",
        json.dumps(doc).encode(),
        b'{"schema_version":1,"schema_version":1}',
        b"{" + b"x" * MAX_ATTESTATION_BYTES,
        b"\xff",
        b"[]",
        b"{" + b"[" * 2000,
        encoded({**doc, "unknown": 1}),
        encoded({**doc, "schema_version": True}),
        encoded({**doc, "parent": manifest}),
        encoded({**doc, "signature": "A" * 128}),
    ]
    for item in bad:
        with pytest.raises(HarnessError):
            verify_attestation(store, manifest, item, public)


def test_bad_key_and_identity_inputs_are_rejected(signed):
    store, manifest, parent, key, _public = signed
    data = create_attestation(manifest, parent, key)
    for value in (b"", b"x" * 33, "x" * 32, None):
        with pytest.raises(HarnessError):
            verify_attestation(store, manifest, data, value)
    for value in (None, 5, "A" * 64, "z" * 64):
        with pytest.raises(HarnessError):
            create_attestation(value, parent, key)
    with pytest.raises(HarnessError):
        create_attestation(manifest, manifest, key)
    with pytest.raises(HarnessError):
        create_attestation(manifest, parent, b"not a private key")


def test_corrupt_or_missing_referenced_objects_prevent_valid_result(signed):
    store, manifest, parent, key, public = signed
    data = create_attestation(manifest, parent, key)
    component = next(iter(store.get_manifest(manifest).components.values()))
    (store.objects / component).write_bytes(b"tampered")
    with pytest.raises(HarnessError, match="integrity"):
        verify_attestation(store, manifest, data, public)
    (store.objects / manifest).unlink()
    with pytest.raises(HarnessError):
        verify_attestation(store, manifest, data, public)


def test_missing_optional_crypto_fails_closed(signed, monkeypatch):
    store, manifest, parent, key, public = signed
    data = create_attestation(manifest, parent, key)
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name.startswith("cryptography"):
            raise ImportError("simulated missing extra")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(HarnessError, match=r"arcen\[attestation\]"):
        verify_attestation(store, manifest, data, public)


def test_installed_cli_verifies_without_mutating_adopted_ref_or_signature(signed, tmp_path):
    import os

    import arcen

    store, manifest, parent, key, public = signed
    path = tmp_path / "attestation.json"
    path.write_bytes(create_attestation(manifest, parent, key))
    before = (store.root / "lineage.sqlite3").read_bytes()
    original = path.read_bytes()
    env = os.environ.copy()
    env.update(HOME=str(tmp_path), PYTHONPATH=str(Path(arcen.__file__).resolve().parent.parent))
    command = [
        sys.executable,
        "-m",
        "arcen.cli",
        "harness",
        "--store",
        str(store.root),
        "attestation",
        "verify",
        "--manifest",
        manifest,
        "--file",
        str(path),
        "--public-key",
        public.hex(),
    ]
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "Signature valid" in result.stdout and parent in result.stdout
    assert "lineage, safety and authorization are not verified" in result.stdout
    assert "adoption remain disabled" in result.stdout
    assert path.read_bytes() == original
    assert (store.root / "lineage.sqlite3").read_bytes() == before
    command[-1] = Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 1 and "Signature valid" not in result.stdout


def test_cli_rejects_symlink_fifo_and_oversize_attestations(signed, tmp_path, capsys):
    from arcen.harness.cli import main

    store, manifest, parent, key, public = signed
    data = create_attestation(manifest, parent, key)
    path = tmp_path / "attest.json"
    path.write_bytes(data)
    link = tmp_path / "link"
    link.symlink_to(path)
    fifo = tmp_path / "fifo"
    import os

    os.mkfifo(fifo)
    huge = tmp_path / "huge"
    huge.write_bytes(b"x" * (MAX_ATTESTATION_BYTES + 1))
    for invalid in (link, fifo, huge):
        assert (
            main(
                [
                    "--store",
                    str(store.root),
                    "attestation",
                    "verify",
                    "--manifest",
                    manifest,
                    "--file",
                    str(invalid),
                    "--public-key",
                    public.hex(),
                ]
            )
            == 1
        )
        assert "Signature valid" not in capsys.readouterr().out
