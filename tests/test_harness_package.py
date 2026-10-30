"""Bounded signed packages are transport/inspection, never runtime selection."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import arcen
from arcen.harness.attestation import create_attestation
from arcen.harness.cli import _init, main
from arcen.harness.package import (
    MAX_PACKAGE_BYTES,
    export_package,
    verify_package,
    write_new_package,
)
from arcen.harness.resolver import HarnessError
from arcen.harness.store import HarnessStore


@pytest.fixture
def signed_package(tmp_path):
    root = tmp_path / "store"
    manifest = _init(str(root))
    store = HarnessStore(root)
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))  # TEST KEY ONLY
    public = key.public_key().public_bytes_raw()
    signature = create_attestation(manifest, "a" * 64, key)
    data = export_package(store, manifest, signature, public)
    return store, manifest, public, signature, data


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def test_signed_package_roundtrip_is_deterministic_and_never_adopts(signed_package):
    store, manifest, public, signature, data = signed_package
    before = (store.root / "lineage.sqlite3").read_bytes()
    result = verify_package(data, manifest, public)
    assert result.attestation.manifest == manifest
    assert result.attestation.parent == "a" * 64
    assert result.component_count == 7 and result.unique_objects == 7
    assert data == export_package(store, manifest, signature, public)
    assert (store.root / "lineage.sqlite3").read_bytes() == before


def test_changed_blob_and_missing_or_extra_objects_rejected(signed_package):
    _, manifest, public, _, data = signed_package
    original = json.loads(data)
    key = next(iter(original["objects"]))
    for change in ("tamper", "missing", "extra", "path"):
        doc = json.loads(data)
        if change == "tamper":
            doc["objects"][key] = base64.b64encode(b"changed").decode()
        elif change == "missing":
            del doc["objects"][key]
        elif change == "extra":
            doc["objects"]["f" * 64] = ""
        else:
            doc["objects"]["../../outside"] = ""
        with pytest.raises(HarnessError):
            verify_package(canonical(doc), manifest, public)


def test_wrong_public_key_manifest_and_signature_rejected(signed_package):
    store, manifest, public, signature, data = signed_package
    other = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    with pytest.raises(HarnessError):
        verify_package(data, manifest, other)
    with pytest.raises(HarnessError):
        verify_package(data, "f" * 64, public)
    with pytest.raises(HarnessError):
        export_package(store, manifest, signature, other)
    doc = json.loads(data)
    att = json.loads(base64.b64decode(doc["attestation"]))
    att["parent"] = "b" * 64
    doc["attestation"] = base64.b64encode(canonical(att)).decode()
    with pytest.raises(HarnessError, match="signature"):
        verify_package(canonical(doc), manifest, public)


def test_invalid_encoding_schema_and_duplicate_fields_fail_closed(signed_package):
    _, manifest, public, _, data = signed_package
    doc = json.loads(data)
    corrupt = [
        b"",
        b"\xff",
        b"{}",
        b"[" * 2000,
        b'{"schema_version":1,"schema_version":1}',
        b"x" * (MAX_PACKAGE_BYTES + 1),
        data + b"\n",
        canonical({**doc, "schema_version": True}),
        canonical({**doc, "extra": "bad"}),
        canonical({**doc, "manifest": "%%%"}),
        canonical({**doc, "attestation": 42}),
        canonical({**doc, "objects": []}),
        canonical({**doc, "objects": {"x": "!"}}),
        b'{"schema_version":' + b"9" * 5000 + b"}",
    ]
    for item in corrupt:
        with pytest.raises(HarnessError):
            verify_package(item, manifest, public)


def test_archive_files_are_atomic_private_and_never_overwrite(signed_package, tmp_path):
    _, manifest, public, _, data = signed_package
    out = tmp_path / "package.json"
    write_new_package(str(out), data)
    assert verify_package(out.read_bytes(), manifest, public).component_count == 7
    assert out.stat().st_mode & 0o777 == 0o600
    before = out.read_bytes()
    with pytest.raises(HarnessError, match="already exists"):
        write_new_package(str(out), b"replacement")
    link = tmp_path / "link"
    link.symlink_to(out)
    with pytest.raises(HarnessError, match="already exists"):
        write_new_package(str(link), b"replacement")
    assert out.read_bytes() == before
    assert not list(tmp_path.glob(".arcen-package-*"))


def test_competing_exports_never_replace_each_other(signed_package, tmp_path):
    _, _, _, _, data = signed_package
    out = tmp_path / "shared.json"

    def publish(_):
        try:
            write_new_package(str(out), data)
            return True
        except HarnessError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(publish, range(8)))
    assert sum(results) == 1 and out.read_bytes() == data
    assert not list(tmp_path.glob(".arcen-package-*"))


def test_cli_export_and_offline_verify_leave_refs_unchanged(signed_package, tmp_path, capsys):
    store, manifest, public, signature, _ = signed_package
    sig = tmp_path / "signature.json"
    sig.write_bytes(signature)
    out = tmp_path / "package.json"
    before = (store.root / "lineage.sqlite3").read_bytes()
    assert (
        main(
            [
                "--store",
                str(store.root),
                "package",
                "export",
                "--manifest",
                manifest,
                "--attestation",
                str(sig),
                "--public-key",
                public.hex(),
                "--output",
                str(out),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert "not imported, activated or adopted" in captured.out
    assert out.is_file() and (store.root / "lineage.sqlite3").read_bytes() == before
    assert (
        main(
            [
                "--store",
                str(tmp_path / "nonexistent"),
                "package",
                "verify",
                "--manifest",
                manifest,
                "--file",
                str(out),
                "--public-key",
                public.hex(),
            ]
        )
        == 0
    )
    assert "Verified manifest" in capsys.readouterr().out
    assert not (tmp_path / "nonexistent").exists()
    old = out.read_bytes()
    assert (
        main(
            [
                "--store",
                str(store.root),
                "package",
                "export",
                "--manifest",
                manifest,
                "--attestation",
                str(sig),
                "--public-key",
                public.hex(),
                "--output",
                str(out),
            ]
        )
        == 1
    )
    assert out.read_bytes() == old


def test_cli_refuses_symlinks_and_does_not_create_unverified_output(
    signed_package, tmp_path, capsys
):
    store, manifest, public, signature, _ = signed_package
    sig = tmp_path / "signature.json"
    sig.write_bytes(signature)
    link = tmp_path / "sig-link"
    link.symlink_to(sig)
    out = tmp_path / "package.json"
    assert (
        main(
            [
                "--store",
                str(store.root),
                "package",
                "export",
                "--manifest",
                manifest,
                "--attestation",
                str(link),
                "--public-key",
                public.hex(),
                "--output",
                str(out),
            ]
        )
        == 1
    )
    assert not out.exists()
    assert "written" not in capsys.readouterr().out


def test_installed_command_verifies_offline_in_subprocess(signed_package, tmp_path):
    _, manifest, public, _, data = signed_package
    path = tmp_path / "package.json"
    path.write_bytes(data)
    env = os.environ.copy()
    env.update(HOME=str(tmp_path), PYTHONPATH=str(Path(arcen.__file__).resolve().parent.parent))
    command = [
        sys.executable,
        "-m",
        "arcen.cli",
        "harness",
        "package",
        "verify",
        "--manifest",
        manifest,
        "--public-key",
        public.hex(),
        "--file",
        str(path),
    ]
    result = subprocess.run(
        command, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "not imported, activated or adopted" in result.stdout
    assert not (tmp_path / ".arcen").exists()
