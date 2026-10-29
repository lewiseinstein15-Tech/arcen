"""Content address determinism, integrity and deduplication."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from arcen.harness import HarnessError
from arcen.harness.manifest import COMPONENT_PATHS, Manifest, default_manifest
from arcen.harness.model import canonical_manifest, content_hash, parse_manifest
from arcen.harness.store import HarnessStore

ROOT = Path(__file__).resolve().parents[1] / "src/arcen"


def populated_store(tmp_path):
    store = HarnessStore(tmp_path / "store")
    manifest = default_manifest()
    for path, digest in manifest.components.items():
        assert store.put_blob((ROOT / path).read_bytes()) == digest
    return store, manifest


def test_canonical_manifest_hash_is_stable_and_map_order_independent():
    manifest = default_manifest()
    reversed_items = dict(reversed(list(manifest.components.items())))
    equivalent = Manifest(1, manifest.model_pin, MappingProxyType(reversed_items))
    assert canonical_manifest(manifest) == canonical_manifest(equivalent)
    assert content_hash(canonical_manifest(manifest)) == content_hash(
        canonical_manifest(equivalent)
    )
    assert parse_manifest(canonical_manifest(manifest)) == manifest


def test_store_deduplicates_and_detects_corruption(tmp_path):
    store, manifest = populated_store(tmp_path)
    blob = b"same content"
    digest = store.put_blob(blob)
    before = (store.objects / digest).stat().st_ino
    assert store.put_blob(blob) == digest
    assert (store.objects / digest).stat().st_ino == before
    assert store.get_blob(digest) == blob
    ref = store.put_manifest(manifest)
    assert store.get_manifest(ref) == manifest
    (store.objects / digest).write_bytes(b"bad")
    with pytest.raises(HarnessError, match="integrity"):
        store.get_blob(digest)
    with pytest.raises(HarnessError, match="integrity"):
        store.put_blob(blob)
    component = next(iter(manifest.components.values()))
    (store.objects / component).unlink()
    with pytest.raises(HarnessError):
        store.get_manifest(ref)


def test_no_manifest_if_component_missing_and_strict_hashes(tmp_path):
    store = HarnessStore(tmp_path / "store")
    with pytest.raises(HarnessError):
        store.put_manifest(default_manifest())
    for bad in ("../file", "f" * 63, "G" * 64, 42):
        with pytest.raises(HarnessError):
            store.get_blob(bad)
    with pytest.raises(HarnessError):
        store.put_blob(b"x" * (1024 * 1024 + 1))


def test_store_rejects_symlinks_and_nonregular_objects(tmp_path):
    root = tmp_path / "link"
    root.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(HarnessError, match="symlink"):
        HarnessStore(root)
    store = HarnessStore(tmp_path / "store")
    digest = content_hash(b"secret")
    (store.objects / digest).symlink_to(tmp_path / "external")
    with pytest.raises(HarnessError):
        store.get_blob(digest)
    with pytest.raises(HarnessError):
        store.put_blob(b"secret")


def test_stored_manifest_duplicate_keys_and_unknown_components_rejected():
    doc = json.loads(canonical_manifest(default_manifest()))
    del doc["components"][next(iter(COMPONENT_PATHS))]
    with pytest.raises(HarnessError):
        parse_manifest(json.dumps(doc).encode())
    with pytest.raises(HarnessError, match="duplicate"):
        parse_manifest(b'{"schema_version":1,"schema_version":1}')


def test_concurrent_identical_writes_deduplicate(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = HarnessStore(tmp_path / "store")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.put_blob(b"concurrent"), range(32)))
    assert len(set(results)) == 1
    assert store.get_blob(results[0]) == b"concurrent"
    assert [p.name for p in store.objects.iterdir()] == results[:1]
