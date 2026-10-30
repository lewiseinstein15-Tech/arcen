"""Durable, shared admissions; no promise of token/USD or in-flight control."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_harness_comparison import provider
from test_manual_campaign import run, setup
from test_probe_execution import Boundary

from arcen.harness import HarnessError, probe_container
from arcen.harness.budget import BudgetExhausted
from arcen.harness.campaign_journal import CampaignJournal
from arcen.harness.cli import _init, main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.store import HarnessStore


def create(store, **changes):
    return DurableBudget.create(
        store,
        **(
            {"max_trials": 3, "max_model_calls": 6, "max_judge_calls": 2, "admission_seconds": 120}
            | changes
        ),
    )


def test_persistence_reopen_and_limits_are_latched(tmp_path):
    store = HarnessStore(tmp_path / "store")
    b = create(store, max_trials=1)
    b.reserve_trial()
    other = DurableBudget(store, b.id)
    assert other.snapshot().trials == 1
    with pytest.raises(BudgetExhausted, match="trials"):
        other.reserve_trial()
    assert DurableBudget(store, b.id).snapshot().stopped
    with pytest.raises(BudgetExhausted):
        b.reserve_model_call()
    assert b.snapshot().model_calls == 0


def test_atomic_reservations_across_independent_instances_and_threads(tmp_path):
    store = HarnessStore(tmp_path / "store")
    b = create(store, max_model_calls=7)
    instances = [DurableBudget(store, b.id) for _ in range(12)]

    def reserve(i):
        try:
            instances[i % len(instances)].reserve_model_call()
            return True
        except BudgetExhausted:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(reserve, range(100)))
    assert sum(results) == 7
    assert b.snapshot().model_calls == 7 and b.snapshot().stopped


def test_another_process_consumes_same_budget_and_stop_persists(tmp_path):
    store = HarnessStore(tmp_path / "store")
    b = create(store)
    script = "from arcen.harness.store import HarnessStore; from arcen.harness.durable_budget import DurableBudget; import sys; b=DurableBudget(HarnessStore(sys.argv[1]),sys.argv[2]); b.reserve_model_call(); b.stop()"
    proc = subprocess.run(
        [sys.executable, "-c", script, str(store.root), b.id],
        text=True,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )
    assert proc.returncode == 0, proc.stderr
    assert b.snapshot().model_calls == 1 and b.snapshot().reason == "stopped"
    with pytest.raises(BudgetExhausted):
        b.reserve_trial()


def test_clock_rollback_and_deadline_latch_closed(tmp_path, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("arcen.harness.durable_budget.time.time", lambda: now[0])
    store = HarnessStore(tmp_path / "store")
    b = create(store, admission_seconds=2)
    now[0] = 1001.0
    b.checkpoint()
    now[0] = 1000.5
    with pytest.raises(BudgetExhausted, match="rollback"):
        b.reserve_trial()
    now[0] = 1001.5
    assert DurableBudget(store, b.id).snapshot().reason == "clock rollback"
    other = create(store, admission_seconds=2)
    now[0] += 2
    with pytest.raises(BudgetExhausted, match="deadline"):
        other.checkpoint()
    assert DurableBudget(store, other.id).snapshot().reason == "deadline reached"


@pytest.mark.parametrize(
    "change",
    [
        {"max_trials": 0},
        {"max_trials": True},
        {"max_model_calls": -1},
        {"max_judge_calls": 100001},
        {"admission_seconds": float("nan")},
        {"admission_seconds": True},
        {"admission_seconds": 0},
    ],
)
def test_invalid_limits_rejected_before_database_creation(tmp_path, change):
    store = HarnessStore(tmp_path / "store")
    with pytest.raises(HarnessError, match="limits"):
        create(store, **change)
    assert not (store.root / "budgets.sqlite3").exists()


def test_tamper_and_symlink_fail_closed(tmp_path):
    store = HarnessStore(tmp_path / "store")
    b = create(store)
    with sqlite3.connect(b.path) as db:
        db.execute("UPDATE budgets SET model_calls=999 WHERE id=?", (b.id,))
    with pytest.raises(HarnessError, match="record"):
        b.reserve_model_call()
    b.path.unlink()
    victim = tmp_path / "victim"
    victim.write_text("safe")
    b.path.symlink_to(victim)
    with pytest.raises(HarnessError):
        DurableBudget(store, b.id)
    with pytest.raises(HarnessError):
        create(store)
    assert victim.read_text() == "safe"


def test_schema_corruption_and_unknown_id_fail_closed(tmp_path):
    store = HarnessStore(tmp_path / "store")
    b = create(store)
    with pytest.raises(HarnessError, match="unknown"):
        DurableBudget(store, "a" * 32)
    with sqlite3.connect(b.path) as db:
        db.execute("ALTER TABLE budgets ADD COLUMN foreign_data TEXT")
    with pytest.raises(HarnessError, match="schema"):
        DurableBudget(store, b.id)
    with pytest.raises(HarnessError, match="schema"):
        create(store)


def test_manual_journaled_campaign_uses_durable_budget(tmp_path, monkeypatch):
    args = setup(tmp_path)
    store, baseline, candidates, _, _, commit, reviews = args
    cap = create(store)
    journal = CampaignJournal(store, create=True)
    rec = journal.plan(baseline, candidates, "inspect project", commit)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    result = run(args, budget=cap, journal=journal, campaign_id=rec.id)
    assert result.stop_reason is None and len(calls) == 6
    snap = DurableBudget(store, cap.id).snapshot()
    assert (snap.trials, snap.model_calls, snap.judge_calls) == (3, 6, 2)
    assert journal.get(rec.id).state == "completed" and len(reviews.list()) == 2


def test_external_stop_blocks_later_admissions(tmp_path, monkeypatch):
    args = setup(tmp_path)
    cap = create(args[0])
    other = DurableBudget(args[0], cap.id)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch, hook=lambda n: other.stop() if n == 2 else None)
    result = run(args, budget=cap)
    assert result.stop_reason == "budget_closed" and len(calls) == 2
    assert not Boundary.instances[-1].calls and Boundary.instances[-1].closed
    assert DurableBudget(args[0], cap.id).snapshot().reason == "stopped"


def test_cli_budget_status_and_stop(tmp_path, capsys):
    store = HarnessStore(tmp_path / "store")
    _init(str(store.root))
    b = create(store)
    b.reserve_model_call()
    assert main(["--store", str(store.root), "budget", "status", b.id]) == 0
    assert "model calls=1" in capsys.readouterr().out
    assert main(["--store", str(store.root), "budget", "stop", b.id]) == 0
    assert "stopped=True" in capsys.readouterr().out
    with pytest.raises(BudgetExhausted):
        b.reserve_trial()


def test_real_docker_durable_budget_when_explicitly_enabled(tmp_path, monkeypatch):
    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires real Docker and sandbox image")
    pytest.importorskip("docker")
    args = setup(tmp_path)
    cap = create(args[0])
    provider(monkeypatch)
    result = run(args, budget=cap)
    assert result.stop_reason is None and len(result.completed) == 2
    assert (cap.snapshot().trials, cap.snapshot().model_calls, cap.snapshot().judge_calls) == (
        3,
        6,
        2,
    )
