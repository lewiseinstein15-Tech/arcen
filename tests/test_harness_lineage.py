"""Transactional refs/lineage foundation; no runtime harness selection."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import MappingProxyType

import pytest

from arcen.harness import HarnessError
from arcen.harness.lineage import HarnessLineage
from arcen.harness.manifest import Manifest, default_manifest
from arcen.harness.store import HarnessStore
from arcen.stream.events import EventError, RunStart, from_dict, from_line, to_line

ROOT = Path(__file__).resolve().parents[1] / "src/arcen"


def setup_store(tmp_path):
    store = HarnessStore(tmp_path / "store")
    manifest = default_manifest()
    for path in manifest.components:
        store.put_blob((ROOT / path).read_bytes())
    base = store.put_manifest(manifest)
    db = HarnessLineage(store)
    db.initialize_baseline(base)
    return store, db, manifest, base


def variation(store, db, manifest, label):
    components = dict(manifest.components)
    components["tool-guidance.md"] = store.put_blob(label.encode())
    modified = Manifest(1, manifest.model_pin, MappingProxyType(components))
    digest = store.put_manifest(modified)
    db.register(digest)
    return digest


def test_baseline_only_once_and_candidate_compare_and_set(tmp_path):
    store, db, manifest, base = setup_store(tmp_path)
    assert db.resolve("refs/heads/adopted") == base
    assert db.path.stat().st_mode & 0o777 == 0o600
    db.initialize_baseline(base)
    assert db.history("refs/heads/adopted") == ((None, base),)
    a, b = (variation(store, db, manifest, x) for x in ("a", "b"))
    with pytest.raises(HarnessError, match="packaged"):
        db.initialize_baseline(a)
    db.set_candidate("refs/candidates/alpha", a)
    with pytest.raises(HarnessError, match="compare-and-set"):
        db.set_candidate("refs/candidates/alpha", b)
    db.set_candidate("refs/candidates/alpha", b, expected=a)
    assert db.resolve("refs/candidates/alpha") == b
    assert db.history("refs/candidates/alpha") == ((None, a), (a, b))
    with pytest.raises(HarnessError, match="candidate"):
        db.set_candidate("refs/heads/adopted", a)
    assert db.resolve("refs/heads/adopted") == base


def test_dag_multiple_parents_cycle_and_duplicate_detection(tmp_path):
    store, db, manifest, base = setup_store(tmp_path)
    a, b, c = (variation(store, db, manifest, x) for x in ("a", "b", "c"))
    db.add_edge(a, base, task="task one", trajectory_ids=("run-1",), judge_report="judge-1")
    db.add_edge(b, base, task="task two", decision="rejected")
    db.add_edge(c, a, task="compose", decision="observed")
    db.add_edge(c, b, task="compose", decision="observed")
    assert {edge.parent for edge in db.parents(c)} == {a, b}
    assert db.parents(a)[0].trajectory_ids == ("run-1",)
    with pytest.raises(HarnessError, match="cycle"):
        db.add_edge(base, c, task="loop")
    with pytest.raises(HarnessError, match="cycle"):
        db.add_edge(base, base, task="loop")
    with pytest.raises(HarnessError, match="already recorded"):
        db.add_edge(a, base, task="replace metadata")
    assert db.parents(base) == ()
    # Persistence after reconstructing the API object.
    assert HarnessLineage(store).parents(c) == db.parents(c)


def test_invalid_refs_metadata_and_corrupt_objects_fail(tmp_path):
    store, db, manifest, base = setup_store(tmp_path)
    a = variation(store, db, manifest, "a")
    for name in ("refs/candidates/../secret", "refs/candidates/", "refs/candidates/a/b", "x"):
        with pytest.raises(HarnessError):
            db.set_candidate(name, a)
    with pytest.raises(HarnessError, match="decision"):
        db.add_edge(a, base, task="task", decision="approved")
    with pytest.raises(HarnessError, match="task"):
        db.add_edge(a, base, task="")
    with pytest.raises(HarnessError, match="trajectory"):
        db.add_edge(a, base, task="t", trajectory_ids=("",))
    db.set_candidate("refs/candidates/a", a)
    component = store.get_manifest(a).components["tool-guidance.md"]
    (store.objects / component).write_bytes(b"changed")
    with pytest.raises(HarnessError, match="integrity"):
        db.resolve("refs/candidates/a")


def test_concurrent_compare_and_set_has_one_winner(tmp_path):
    store, db, manifest, base = setup_store(tmp_path)
    a, b = (variation(store, db, manifest, x) for x in ("a", "b"))
    db.set_candidate("refs/candidates/race", base)

    def change(digest):
        try:
            db.set_candidate("refs/candidates/race", digest, expected=base)
            return True
        except HarnessError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, [a, b]))
    assert sorted(results) == [False, True]
    assert db.resolve("refs/candidates/race") in (a, b)


def test_legacy_run_start_is_byte_identical_and_optional_ref_roundtrips():
    old = '{"seq":1,"type":"run.start","run_id":"r-1","goal":"hello","depth":0,"ts":1.5}'
    assert to_line(from_line(old)) == old
    event = RunStart(
        seq=1, run_id="r-1", goal="hello", depth=0, ts=1.5, harness_ref="refs/candidates/a"
    )
    line = to_line(event)
    assert from_line(line).harness_ref == "refs/candidates/a"
    assert '"harness_ref":"refs/candidates/a"' in line
    with pytest.raises(EventError):
        from_dict(
            {
                "seq": 1,
                "type": "run.start",
                "run_id": "r",
                "goal": "x",
                "depth": 0,
                "harness_ref": None,
            }
        )


def test_lineage_ref_missing_and_symlink_database_fail_closed(tmp_path):
    store, db, manifest, _base = setup_store(tmp_path)
    with pytest.raises(HarnessError, match="unknown ref"):
        db.resolve("refs/candidates/missing")
    # Create an intact but unregistered distinct manifest.
    components = dict(manifest.components)
    components["tool-guidance.md"] = store.put_blob(b"unregistered")
    unregistered = store.put_manifest(Manifest(1, manifest.model_pin, MappingProxyType(components)))
    with pytest.raises(HarnessError, match="not registered"):
        db.set_candidate("refs/candidates/other", unregistered)
    store2 = HarnessStore(tmp_path / "other")
    (store2.root / "lineage.sqlite3").symlink_to(db.path)
    with pytest.raises(HarnessError, match="regular file"):
        HarnessLineage(store2)


def test_session_replay_preserves_legacy_and_new_run_start(tmp_path):
    from arcen.session.store import SessionStore
    from arcen.stream.events import to_dict

    sessions = SessionStore(tmp_path)
    legacy = {"seq": 1, "type": "run.start", "run_id": "r", "goal": "x", "depth": 0, "ts": 1.5}
    extended = to_dict(
        RunStart(seq=2, run_id="r2", goal="x", depth=0, ts=2.0, harness_ref="refs/candidates/x")
    )
    sessions.append("old-and-new", legacy)
    sessions.append("old-and-new", extended)
    assert sessions.read("old-and-new") == [legacy, extended]
    assert sessions.validate("old-and-new") == (2, 0)
