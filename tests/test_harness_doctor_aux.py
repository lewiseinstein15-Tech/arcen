"""Doctor's local auxiliary SQLite checks; no provider or Docker involved."""

from __future__ import annotations

import sqlite3

import pytest

from arcen.harness.campaign_journal import CampaignJournal
from arcen.harness.cli import _existing, _init, main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.experience_cli_store import open_cli_experience
from arcen.harness.review import ReviewLedger
from arcen.harness.task_bank import TaskBank

DATABASES = (
    "tasks.sqlite3",
    "reviews.sqlite3",
    "campaigns.sqlite3",
    "budgets.sqlite3",
    "experience.sqlite3",
)


def setup(tmp_path):
    root = tmp_path / "store"
    adopted = _init(str(root))
    store, lineage = _existing(str(root))
    TaskBank(store, create=True).add("first", "Inspect the project")
    reviews = ReviewLedger(store, create=True)
    CampaignJournal(store, create=True)
    budget = DurableBudget.create(
        store, max_trials=2, max_model_calls=4, max_judge_calls=1, admission_seconds=120
    )
    with open_cli_experience(store, reviews, create=True):
        pass
    return store, lineage, adopted, budget


def test_doctor_checks_all_auxiliary_schemas_without_mutating_records(tmp_path, capsys):
    store, lineage, adopted, budget = setup(tmp_path)
    before = {name: (store.root / name).read_bytes() for name in DATABASES}
    assert main(["--store", str(store.root), "doctor"]) == 0
    text = capsys.readouterr().out
    assert "aux_databases=5" in text and "not every record" in text
    assert {name: (store.root / name).read_bytes() for name in DATABASES} == before
    assert lineage.resolve("refs/heads/adopted") == adopted
    assert budget.snapshot().trials == 0


@pytest.mark.parametrize("name", DATABASES)
def test_doctor_rejects_corrupt_auxiliary_sqlite_without_echoing_contents(tmp_path, capsys, name):
    store, _, _, _ = setup(tmp_path)
    (store.root / name).write_bytes(b"malformed-secret-123")
    assert main(["--store", str(store.root), "doctor"]) == 1
    error = capsys.readouterr().err
    assert name in error and "invalid auxiliary database" in error
    assert "malformed-secret-123" not in error


@pytest.mark.parametrize("name", DATABASES)
def test_doctor_rejects_unsupported_auxiliary_schema(tmp_path, capsys, name):
    store, _, _, _ = setup(tmp_path)
    with sqlite3.connect(store.root / name) as db:
        db.execute("PRAGMA user_version=999")
    assert main(["--store", str(store.root), "doctor"]) == 1
    assert f"invalid auxiliary database: {name}" in capsys.readouterr().err


@pytest.mark.parametrize("name", DATABASES)
def test_doctor_rejects_symlink_auxiliary_database(tmp_path, capsys, name):
    store, _, _, _ = setup(tmp_path)
    path = store.root / name
    path.unlink()
    path.symlink_to(tmp_path / "does-not-exist")
    assert main(["--store", str(store.root), "doctor"]) == 1
    assert name in capsys.readouterr().err


def test_doctor_does_not_create_missing_optional_databases(tmp_path, capsys):
    root = tmp_path / "store"
    _init(str(root))
    assert main(["--store", str(root), "doctor"]) == 0
    assert "aux_databases=0" in capsys.readouterr().out
    assert all(not (root / name).exists() for name in DATABASES)
