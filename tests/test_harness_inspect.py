"""Read-only inspection of imported, unregistered manifest objects."""

from __future__ import annotations

from types import MappingProxyType

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arcen.harness.attestation import create_attestation
from arcen.harness.cli import _init, main
from arcen.harness.lineage import HarnessLineage
from arcen.harness.manifest import Manifest
from arcen.harness.package import export_package, import_package
from arcen.harness.store import HarnessStore


@pytest.fixture
def imported(tmp_path):
    src = tmp_path / "source"
    dst = tmp_path / "destination"
    base = _init(str(src))
    assert _init(str(dst)) == base
    source, target = HarnessStore(src), HarnessStore(dst)
    manifest = source.get_manifest(base)
    components = dict(manifest.components)
    components["prompts/forge.md"] = source.put_blob(
        b"untrusted \x1b[31mred\x1b[0m and \xe2\x80\xae spoof\n"
    )
    candidate = source.put_manifest(
        Manifest(1, "fixed:demo:unsafe\u202epin", MappingProxyType(components))
    )
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))  # public test key
    public = key.public_key().public_bytes_raw()
    data = export_package(source, candidate, create_attestation(candidate, base, key), public)
    import_package(target, data, candidate, public)
    return target, base, candidate, components


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def run(store, identifier, *extra):
    return main(["--store", str(store.root), "inspect", identifier, *extra])


def test_inspect_imported_unregistered_manifest_without_writes_or_plaintext(imported, capsys):
    store, base, candidate, components = imported
    before = snapshot(store.root)
    assert run(store, candidate) == 0
    output = capsys.readouterr()
    assert candidate in output.out and base in output.out
    assert components["prompts/forge.md"] in output.out and "[changed]" in output.out
    assert "[same]" in output.out and "untrusted" not in output.out
    assert "signer, provenance, safety and authorization are not established" in output.out
    assert "No refs, approval, execution or adoption" in output.out
    assert "unsafe�pin" in output.out and "\u202e" not in output.out
    assert snapshot(store.root) == before
    lineage = HarnessLineage(store, read_only=True)
    assert lineage.resolve("refs/heads/adopted") == base
    assert lineage.audit()["nodes"] == 1


def test_opt_in_diff_is_sanitized_and_read_only(imported, capsys):
    store, _, candidate, _ = imported
    before = snapshot(store.root)
    assert run(store, candidate, "--diff") == 0
    output = capsys.readouterr().out
    assert "Untrusted sanitized diff" in output and "may contain sensitive data" in output
    assert "+untrusted" in output and "candidate/prompts/forge.md" in output
    assert "\x1b" not in output and "\u202e" not in output
    assert "�" in output and snapshot(store.root) == before


def test_inspect_rejects_corruption_without_partial_output(imported, capsys):
    store, _, candidate, components = imported
    (store.objects / components["prompts/forge.md"]).write_bytes(b"tampered")
    before = snapshot(store.root)
    assert run(store, candidate, "--diff") == 1
    output = capsys.readouterr()
    assert output.out == "" and "integrity" in output.err
    assert snapshot(store.root) == before


def test_inspect_missing_or_invalid_ids_do_not_mutate_or_print_report(imported, capsys):
    store, _, _, _ = imported
    before = snapshot(store.root)
    for identifier in ("../escape", "0" * 64):
        assert run(store, identifier) == 1
        assert capsys.readouterr().out == ""
    assert snapshot(store.root) == before


def test_binary_content_metadata_is_inspectable_but_diff_fails_closed(imported, capsys):
    store, _, candidate, _ = imported
    manifest = store.get_manifest(candidate)
    components = dict(manifest.components)
    components["prompts/forge.md"] = store.put_blob(b"\xff\xfe")
    binary_id = store.put_manifest(Manifest(1, manifest.model_pin, MappingProxyType(components)))
    before = snapshot(store.root)
    assert run(store, binary_id) == 0
    assert "Components" in capsys.readouterr().out
    assert run(store, binary_id, "--diff") == 1
    output = capsys.readouterr()
    assert output.out == "" and "non-UTF-8" in output.err
    assert snapshot(store.root) == before


def test_diff_limit_does_not_print_partial_report(imported, capsys):
    store, _, candidate, _ = imported
    manifest = store.get_manifest(candidate)
    components = dict(manifest.components)
    components["prompts/forge.md"] = store.put_blob(b"x" * (1024 * 1024))
    large_id = store.put_manifest(Manifest(1, manifest.model_pin, MappingProxyType(components)))
    before = snapshot(store.root)
    assert run(store, large_id, "--diff") == 1
    output = capsys.readouterr()
    assert output.out == "" and "diff exceeds display limit" in output.err
    assert snapshot(store.root) == before


def test_diff_line_limit_rejects_adversarial_large_inputs(imported, capsys):
    store, _, candidate, _ = imported
    manifest = store.get_manifest(candidate)
    components = dict(manifest.components)
    components["prompts/forge.md"] = store.put_blob(
        "".join(f"untrusted line {i}\n" for i in range(2049)).encode()
    )
    large_id = store.put_manifest(Manifest(1, manifest.model_pin, MappingProxyType(components)))
    before = snapshot(store.root)
    assert run(store, large_id, "--diff") == 1
    output = capsys.readouterr()
    assert output.out == "" and "input line limit" in output.err
    assert snapshot(store.root) == before


def test_missing_store_is_not_created(tmp_path, capsys):
    root = tmp_path / "does-not-exist"
    assert main(["--store", str(root), "inspect", "0" * 64]) == 1
    assert not root.exists() and capsys.readouterr().out == ""
