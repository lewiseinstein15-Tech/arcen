"""Content-addressed manually curated tasks; never executes or adopts."""

from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from arcen.harness.resolver import HarnessError
from arcen.harness.store import HarnessStore
from arcen.harness.task_bank import TaskBank


def test_add_reopen_exact_bytes_and_no_implicit_replacement(tmp_path):
    store = HarnessStore(tmp_path / "store")
    bank = TaskBank(store, create=True)
    task = "Review the project.\nKeep exact spacing.\n"
    first = bank.add("review-one", task)
    assert first.digest == hashlib.sha256(task.encode()).hexdigest()
    assert bank.add("review-one", task) == first
    alias = bank.add("review-alias", task)
    assert alias.digest == first.digest
    with pytest.raises(HarnessError, match="already exists"):
        bank.add("review-one", "different task")
    other = TaskBank(store)
    assert other.read(first.digest) == task
    assert [entry.name for entry in other.list()] == ["review-alias", "review-one"]
    assert (bank.path.stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize(
    "name,text",
    [
        ("../escape", "task"),
        ("UPPER", "task"),
        ("ok", ""),
        ("ok", "a" * 4001),
        ("ok", "credential sk-abcdefghijklmnop"),
        ("ok", "bad\ud800"),
    ],
)
def test_invalid_input_rejected_without_blob_or_record(tmp_path, name, text):
    store = HarnessStore(tmp_path / "store")
    bank = TaskBank(store, create=True)
    before = set(store.objects.iterdir())
    with pytest.raises(HarnessError):
        bank.add(name, text)
    assert bank.list() == () and set(store.objects.iterdir()) == before


def test_concurrent_name_claim_is_atomic(tmp_path):
    store = HarnessStore(tmp_path / "store")
    TaskBank(store, create=True)

    def add(index):
        try:
            return TaskBank(store, create=True).add("one", f"task {index}")
        except HarnessError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(add, range(12)))
    assert sum(result is not None for result in results) == 1
    assert len(TaskBank(store).list()) == 1


def test_concurrent_first_creation_is_serialized(tmp_path):
    store = HarnessStore(tmp_path / "store")

    def create(index):
        return TaskBank(store, create=True).add(f"task-{index}", f"value {index}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(create, range(6)))
    assert len(results) == len(TaskBank(store).list()) == 6


def test_tampered_blob_metadata_and_schema_fail_closed(tmp_path):
    store = HarnessStore(tmp_path / "store")
    bank = TaskBank(store, create=True)
    entry = bank.add("example", "original task")
    object_path = store.objects / entry.digest
    object_path.write_bytes(b"altered")
    with pytest.raises(HarnessError):
        bank.read(entry.digest)
    with pytest.raises(HarnessError):
        bank.list()
    object_path.write_bytes(b"original task")
    with sqlite3.connect(bank.path) as db:
        db.execute("UPDATE tasks SET digest='invalid'")
    with pytest.raises(HarnessError):
        bank.list()
    with sqlite3.connect(bank.path) as db:
        db.execute("ALTER TABLE tasks ADD COLUMN foreign_data TEXT")
    with pytest.raises(HarnessError, match="schema"):
        TaskBank(store)


def test_missing_or_symlinked_database_fails_without_touching_victim(tmp_path):
    store = HarnessStore(tmp_path / "store")
    with pytest.raises(HarnessError, match="missing"):
        TaskBank(store)
    victim = tmp_path / "victim"
    victim.write_text("safe")
    (store.root / "tasks.sqlite3").symlink_to(victim)
    for create in (False, True):
        with pytest.raises(HarnessError):
            TaskBank(store, create=create)
    assert victim.read_text() == "safe"
