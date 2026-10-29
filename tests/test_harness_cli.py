"""CLI initialization, inspection and fail-closed behavior."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

from arcen.harness.lineage import HarnessLineage
from arcen.harness.manifest import Manifest, default_manifest
from arcen.harness.store import HarnessStore

ROOT = Path(__file__).resolve().parents[1]


def invoke(tmp_path, *args):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "HOME": str(tmp_path)}
    return subprocess.run(
        [sys.executable, "-m", "arcen.harness.cli", "--store", str(tmp_path / "store"), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_cli_init_doctor_idempotent_and_read_only(tmp_path):
    missing = invoke(tmp_path, "doctor")
    assert missing.returncode != 0 and not (tmp_path / "store").exists()
    first = invoke(tmp_path, "init")
    assert first.returncode == 0 and "Metadata only" in first.stdout
    second = invoke(tmp_path, "init")
    assert second.returncode == 0 and second.stdout == first.stdout
    before = (tmp_path / "store/lineage.sqlite3").read_bytes()
    status = invoke(tmp_path, "doctor")
    assert status.returncode == 0 and "nodes=1" in status.stdout and "refs=1" in status.stdout
    assert (tmp_path / "store/lineage.sqlite3").read_bytes() == before


def test_cli_diff_candidate_is_safe_and_rollback_is_refused(tmp_path):
    assert invoke(tmp_path, "init").returncode == 0
    store = HarnessStore(tmp_path / "store")
    db = HarnessLineage(store)
    baseline = default_manifest()
    components = dict(baseline.components)
    components["tool-guidance.md"] = store.put_blob(b"hello \x1b[31mred\n")
    candidate = store.put_manifest(Manifest(1, baseline.model_pin, MappingProxyType(components)))
    db.register(candidate)
    db.set_candidate("refs/candidates/test", candidate)
    diff = invoke(tmp_path, "diff", "refs/candidates/test")
    assert diff.returncode == 0
    assert "candidate/tool-guidance.md" in diff.stdout and "hello" in diff.stdout
    assert "\x1b" not in diff.stdout
    before = db.resolve("refs/heads/adopted")
    rollback = invoke(tmp_path, "rollback", "refs/candidates/test")
    assert rollback.returncode != 0 and "unavailable" in rollback.stderr
    assert db.resolve("refs/heads/adopted") == before


def test_doctor_detects_corrupt_object_and_bad_ref_history(tmp_path):
    assert invoke(tmp_path, "init").returncode == 0
    store = HarnessStore(tmp_path / "store")
    objects = list(store.objects.iterdir())
    objects[0].write_bytes(b"corrupt")
    status = invoke(tmp_path, "doctor")
    assert status.returncode != 0 and "integrity" in status.stderr
    # A separate initialized store with a tampered ref audit trail fails too.
    other = tmp_path / "other"
    other.mkdir()
    assert invoke(other, "init").returncode == 0
    path = other / "store/lineage.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM ref_history")
    status = invoke(other, "doctor")
    assert status.returncode != 0 and "history" in status.stderr


def test_doctor_rejects_symlink_objects_and_missing_refs(tmp_path):
    assert invoke(tmp_path, "init").returncode == 0
    store = HarnessStore(tmp_path / "store")
    (store.objects / ("0" * 64)).symlink_to(tmp_path / "outside")
    assert invoke(tmp_path, "doctor").returncode != 0
    assert invoke(tmp_path, "diff", "refs/candidates/not-there").returncode != 0


def test_real_console_entrypoint_dispatches_harness_command(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "HOME": str(tmp_path)}
    executable = Path(sys.executable).parent / "arcen"
    if not executable.exists():
        pytest.skip("console script not installed in this environment")
    result = subprocess.run(
        [str(executable), "harness", "--store", str(tmp_path / "store"), "init"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Initialized packaged baseline" in result.stdout


def test_doctor_reports_lineage_cycles_and_sqlite_corruption(tmp_path):
    assert invoke(tmp_path, "init").returncode == 0
    store = HarnessStore(tmp_path / "store")
    db = HarnessLineage(store)
    base = db.resolve("refs/heads/adopted")
    manifest = default_manifest()
    components = dict(manifest.components)
    components["tool-guidance.md"] = store.put_blob(b"other")
    changed = store.put_manifest(Manifest(1, manifest.model_pin, MappingProxyType(components)))
    db.register(changed)
    db.add_edge(changed, base, task="normal")
    with sqlite3.connect(db.path) as connection:
        connection.execute(
            "INSERT INTO edges VALUES (?,?,?,?,?,?)",
            (base, changed, "bad", "[]", "", "proposed"),
        )
    status = invoke(tmp_path, "doctor")
    assert status.returncode != 0 and "cycle" in status.stderr
    db.path.write_bytes(b"not a sqlite database")
    assert invoke(tmp_path, "doctor").returncode != 0


def test_console_router_does_not_boot_server_for_inspection(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "HOME": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-m", "arcen.cli", "harness", "--store", str(tmp_path / "store"), "init"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "sandbox" not in result.stderr.lower()
    assert not (tmp_path / ".arcen").exists()
