"""Human-confirmed object import never updates lineage, refs or runtime."""

from __future__ import annotations

import json
import sys
from types import MappingProxyType

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arcen.harness.attestation import create_attestation
from arcen.harness.cli import _init, main
from arcen.harness.manifest import Manifest
from arcen.harness.model import content_hash
from arcen.harness.package import export_package, import_package
from arcen.harness.resolver import HarnessError
from arcen.harness.selection import resolve_packaged_baseline
from arcen.harness.store import HarnessStore


@pytest.fixture
def scenario(tmp_path):
    source_path = tmp_path / "source"
    target_path = tmp_path / "target"
    base = _init(str(source_path))
    assert _init(str(target_path)) == base
    source = HarnessStore(source_path)
    target = HarnessStore(target_path)
    baseline = source.get_manifest(base)
    components = dict(baseline.components)
    components["prompts/forge.md"] = source.put_blob(b"first new object\n")
    components["prompts/temper.md"] = source.put_blob(b"second new object\n")
    candidate = source.put_manifest(Manifest(1, baseline.model_pin, MappingProxyType(components)))
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))  # TEST KEY ONLY
    public = key.public_key().public_bytes_raw()
    attestation = create_attestation(candidate, base, key)
    package = export_package(source, candidate, attestation, public)
    package_file = tmp_path / "package.json"
    package_file.write_bytes(package)
    return target, base, candidate, public, package, package_file, components


def object_names(store):
    return {p.name for p in store.objects.iterdir()}


def command(store, candidate, public, package_file):
    return [
        "--store",
        str(store.root),
        "package",
        "import",
        "--manifest",
        candidate,
        "--public-key",
        public.hex(),
        "--file",
        str(package_file),
    ]


def tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)


def test_import_stores_only_verified_objects_and_never_registers_or_adopts(scenario):
    store, base, candidate, public, package, _, components = scenario
    before_db = (store.root / "lineage.sqlite3").read_bytes()
    before_objects = object_names(store)
    assert candidate not in before_objects
    verified = import_package(store, package, candidate, public)
    assert verified.attestation.parent == base
    assert store.get_manifest(candidate).components == components
    assert (store.root / "lineage.sqlite3").read_bytes() == before_db
    assert object_names(store) == before_objects | {
        candidate,
        components["prompts/forge.md"],
        components["prompts/temper.md"],
    }
    assert resolve_packaged_baseline("adopted", str(store.root)) == base
    with pytest.raises(HarnessError, match="candidate selection unavailable"):
        resolve_packaged_baseline("refs/candidates/imported", str(store.root))
    # Repeated import is idempotent and does not rewrite database refs.
    assert import_package(store, package, candidate, public) == verified
    assert (store.root / "lineage.sqlite3").read_bytes() == before_db


def test_bad_signature_or_content_is_rejected_before_any_write(scenario):
    store, _, candidate, public, package, _, _ = scenario
    before = object_names(store)
    before_db = (store.root / "lineage.sqlite3").read_bytes()
    bad_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    with pytest.raises(HarnessError):
        import_package(store, package, candidate, bad_key)
    with pytest.raises(HarnessError):
        import_package(store, package, "0" * 64, public)
    doc = json.loads(package)
    key = next(iter(doc["objects"]))
    doc["objects"][key] = "Y2hhbmdlZA=="
    altered = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(HarnessError):
        import_package(store, altered, candidate, public)
    assert object_names(store) == before
    assert (store.root / "lineage.sqlite3").read_bytes() == before_db


def test_corrupt_preexisting_object_fails_preflight_before_other_inserts(scenario):
    store, _, candidate, public, package, _, components = scenario
    target = store.objects / components["prompts/temper.md"]
    target.write_bytes(b"corrupt")
    before = object_names(store)
    with pytest.raises(HarnessError, match="integrity"):
        import_package(store, package, candidate, public)
    assert object_names(store) == before and candidate not in before


def test_late_failure_may_leave_orphans_but_does_not_update_refs(scenario, monkeypatch):
    store, _, candidate, public, package, _, _ = scenario
    before_db = (store.root / "lineage.sqlite3").read_bytes()
    before = object_names(store)
    real = store.put_blob
    calls = 0

    def fail_second(data):
        nonlocal calls
        if content_hash(data) not in before:
            calls += 1
            if calls == 2:
                raise HarnessError("simulated write failure")
        return real(data)

    monkeypatch.setattr(store, "put_blob", fail_second)
    with pytest.raises(HarnessError, match="simulated"):
        import_package(store, package, candidate, public)
    assert object_names(store) - before  # a completed blob can remain unreferenced
    assert candidate not in object_names(store)
    assert (store.root / "lineage.sqlite3").read_bytes() == before_db


def test_cli_requires_tty_and_explicit_exact_confirmation(scenario, monkeypatch, capsys):
    store, _, candidate, public, _, path, _ = scenario
    before = object_names(store)
    before_db = (store.root / "lineage.sqlite3").read_bytes()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(command(store, candidate, public, path)) == 1
    assert "interactive terminal" in capsys.readouterr().err
    assert object_names(store) == before
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert main(command(store, candidate, public, path)) == 1
    output = capsys.readouterr()
    assert "Key trust" in output.out and "cancelled" in output.err
    assert object_names(store) == before
    assert (store.root / "lineage.sqlite3").read_bytes() == before_db
    monkeypatch.setattr("builtins.input", lambda _: f" IMPORT {candidate}")
    assert main(command(store, candidate, public, path)) == 1
    assert object_names(store) == before
    monkeypatch.setattr("builtins.input", lambda _: f"IMPORT {candidate}")
    assert main(command(store, candidate, public, path)) == 0
    output = capsys.readouterr()
    assert "Verified objects stored" in output.out
    assert store.get_manifest(candidate)
    assert (store.root / "lineage.sqlite3").read_bytes() == before_db


def test_cli_invalid_data_fails_before_confirmation_or_store_writes(scenario, monkeypatch, capsys):
    store, _, candidate, public, _, path, _ = scenario
    path.write_text("invalid package")
    before = object_names(store)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected confirmation"))
    assert main(command(store, candidate, public, path)) == 1
    assert "invalid package" in capsys.readouterr().err
    assert object_names(store) == before


def test_cli_import_uses_reviewed_bytes_even_if_input_file_changes(scenario, monkeypatch, capsys):
    store, _, candidate, public, _, path, _ = scenario
    tty(monkeypatch)

    def confirm(_):
        path.write_text("altered after review")
        return f"IMPORT {candidate}"

    monkeypatch.setattr("builtins.input", confirm)
    assert main(command(store, candidate, public, path)) == 0
    assert store.get_manifest(candidate)
    assert "Verified objects stored" in capsys.readouterr().out
