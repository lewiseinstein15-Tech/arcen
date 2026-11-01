"""Cooperative durable trial slots; no automatic crash reclamation."""

from __future__ import annotations

import os
import select
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import litellm
import pytest
from test_durable_budget import create
from test_harness_parallel_trials import run
from test_manual_campaign import setup
from test_probe_execution import Boundary
from test_probe_model import response

from arcen.harness import HarnessError, parallel_trials, probe_container
from arcen.harness.budget import BudgetExhausted, TrialConcurrencyFull
from arcen.harness.database_audit import audit_auxiliary_databases
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.durable_trial_slots import DurableTrialSlots
from arcen.harness.store import HarnessStore


def test_reopen_release_capacity_and_fixed_limit(tmp_path):
    store = HarnessStore(tmp_path / "store")
    budget = create(store)
    slots = DurableTrialSlots.create(budget, max_active=1)
    other = DurableTrialSlots(DurableBudget(store, budget.id))
    assert slots.snapshot() == other.snapshot()
    with slots.trial_slot():
        assert other.snapshot().occupied == 1
        with pytest.raises(TrialConcurrencyFull), other.trial_slot():
            pytest.fail("over-admitted")
        assert not budget.snapshot().stopped
    assert slots.snapshot().occupied == 0
    assert budget.snapshot().trials == 0
    with pytest.raises(HarnessError, match="already configured"):
        DurableTrialSlots.create(budget, max_active=2)
    assert slots.snapshot().max_active == 1


@pytest.mark.parametrize("limit", [0, -1, True, 1.0, 100001, "2"])
def test_invalid_limit_does_not_create_database(tmp_path, limit):
    store = HarnessStore(tmp_path / "store")
    budget = create(store)
    with pytest.raises(HarnessError, match="limit"):
        DurableTrialSlots.create(budget, max_active=limit)
    assert not (store.root / "trial_slots.sqlite3").exists()


def test_exception_stops_budget_and_retains_slot(tmp_path):
    store = HarnessStore(tmp_path / "store")
    budget = create(store)
    slots = DurableTrialSlots.create(budget, max_active=2)
    with pytest.raises(ValueError, match="failure"), slots.trial_slot():
        raise ValueError("failure")
    assert budget.snapshot().stopped
    assert DurableTrialSlots(DurableBudget(store, budget.id)).snapshot().occupied == 1
    with pytest.raises(BudgetExhausted), slots.trial_slot():
        pass


def test_threads_share_a_single_persistent_cap(tmp_path):
    store = HarnessStore(tmp_path / "store")
    budget = create(store)
    slots = DurableTrialSlots.create(budget, max_active=2)
    gate = threading.Barrier(2, timeout=10)
    release = threading.Event()

    def worker():
        with DurableTrialSlots(DurableBudget(store, budget.id)).trial_slot():
            gate.wait()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        try:
            # The two workers enter the barrier together before releasing.
            for _ in range(100):
                if slots.snapshot().occupied == 2:
                    break
                threading.Event().wait(0.01)
            assert slots.snapshot().occupied == 2
            with pytest.raises(TrialConcurrencyFull), slots.trial_slot():
                pytest.fail("over-admitted")
        finally:
            release.set()
        for future in futures:
            future.result(timeout=10)
    assert slots.snapshot().occupied == 0 and not budget.snapshot().stopped


def test_crashed_process_leaves_slot_occupied_and_no_auto_reclaim(tmp_path):
    store = HarnessStore(tmp_path / "store")
    budget = create(store)
    slots = DurableTrialSlots.create(budget, max_active=1)
    script = """
import sys, time
from arcen.harness.store import HarnessStore
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.durable_trial_slots import DurableTrialSlots
s=DurableTrialSlots(DurableBudget(HarnessStore(sys.argv[1]),sys.argv[2]))
with s.trial_slot():
 print('ACQUIRED',flush=True)
 time.sleep(120)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(store.root), budget.id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    )
    try:
        ready, _, _ = select.select([proc.stdout], [], [], 15)
        assert ready and proc.stdout.readline().strip() == "ACQUIRED"
        assert slots.snapshot().occupied == 1
        with pytest.raises(TrialConcurrencyFull), slots.trial_slot():
            pytest.fail("over-admitted")
    finally:
        proc.kill()
        proc.communicate(timeout=10)
    reopened = DurableTrialSlots(DurableBudget(store, budget.id))
    assert reopened.snapshot().occupied == 1 and not budget.snapshot().stopped
    with pytest.raises(TrialConcurrencyFull), reopened.trial_slot():
        pytest.fail("crashed slot reclaimed")


def test_schema_blank_database_and_symlink_fail_closed(tmp_path):
    store = HarnessStore(tmp_path / "store")
    budget = create(store)
    path = store.root / "trial_slots.sqlite3"
    path.touch()
    with pytest.raises(HarnessError, match="schema"):
        DurableTrialSlots.create(budget, max_active=1)
    path.unlink()
    victim = tmp_path / "victim"
    victim.write_text("safe")
    path.symlink_to(victim)
    with pytest.raises(HarnessError):
        DurableTrialSlots.create(budget, max_active=1)
    assert victim.read_text() == "safe"


def test_database_tampering_and_doctor_fail_closed(tmp_path):
    store = HarnessStore(tmp_path / "store")
    budget = create(store)
    slots = DurableTrialSlots.create(budget, max_active=1)
    assert audit_auxiliary_databases(store) == 2
    with sqlite3.connect(slots.path) as db:
        db.execute("UPDATE limits SET max_active=0 WHERE budget_id=?", (budget.id,))
    with pytest.raises(HarnessError, match="record"):
        slots.snapshot()
    with pytest.raises(HarnessError, match="record"), slots.trial_slot():
        pytest.fail("bad limit admitted")
    with sqlite3.connect(slots.path) as db:
        db.execute("ALTER TABLE slots ADD COLUMN extra TEXT")
    with pytest.raises(HarnessError, match="trial_slots.sqlite3"):
        audit_auxiliary_databases(store)


def test_parallel_trials_use_durable_slots_and_admissions(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = create(args[0], max_trials=3, max_model_calls=6)
    slots = DurableTrialSlots.create(budget, max_active=2)
    Boundary.instances.clear()
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    monkeypatch.setattr(
        litellm,
        "completion",
        lambda **kw: response(
            "answer" if kw["messages"][-1]["content"] == "inspect project" else "DIRECT"
        ),
    )
    result = run(args, budget, durable_slots=slots)
    assert result.stop_reason is None and result.unstarted == ()
    assert len(result.candidates) == 2 and all(x.status == "ok" for x in result.candidates)
    assert (budget.snapshot().trials, budget.snapshot().model_calls) == (3, 6)
    assert slots.snapshot().occupied == 0
    assert len(Boundary.instances) == 3 and all(
        b.closed and not b.workspace.exists() for b in Boundary.instances
    )


def test_parallel_durable_preflight_requires_matching_slots_and_capacity(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = create(args[0])
    slots = DurableTrialSlots.create(budget, max_active=1)
    another = create(args[0])
    monkeypatch.setattr(
        parallel_trials.NativeDockerProbeExecutor,
        "execute",
        lambda *a: pytest.fail("trial started"),
    )
    for options in ({}, {"durable_slots": slots}, {"budget": another, "durable_slots": slots}):
        selected = options.pop("budget", budget)
        with pytest.raises(HarnessError):
            run(args, selected, **options)
    assert budget.snapshot().trials == another.snapshot().trials == 0
    assert slots.snapshot().occupied == 0


def test_parallel_cleanup_failure_retains_slot_and_stops_budget(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = create(args[0])
    slots = DurableTrialSlots.create(budget, max_active=2)

    class BadBoundary(Boundary):
        fail_close = True

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", BadBoundary)
    monkeypatch.setattr(
        litellm,
        "completion",
        lambda **kw: response(
            "answer" if kw["messages"][-1]["content"] == "inspect project" else "DIRECT"
        ),
    )
    result = run(args, budget, durable_slots=slots)
    assert result.stop_reason == "reference_unavailable" and result.unstarted == args[2]
    assert budget.snapshot().stopped and slots.snapshot().occupied == 1


def test_stop_racing_acquisition_releases_unstarted_slot(tmp_path, monkeypatch):
    store = HarnessStore(tmp_path / "store")
    budget = create(store)
    slots = DurableTrialSlots.create(budget, max_active=1)
    original = budget.checkpoint
    checks = 0

    def stop_on_second_check():
        nonlocal checks
        checks += 1
        if checks == 2:
            budget.stop()
        original()

    monkeypatch.setattr(budget, "checkpoint", stop_on_second_check)
    with pytest.raises(BudgetExhausted), slots.trial_slot():
        pytest.fail("work started after stop")
    assert budget.snapshot().stopped and slots.snapshot().occupied == 0


def test_failed_release_retains_slot_and_stops_budget(tmp_path, monkeypatch):
    store = HarnessStore(tmp_path / "store")
    budget = create(store)
    slots = DurableTrialSlots.create(budget, max_active=1)

    def fail(_token):
        raise HarnessError("release failure")

    monkeypatch.setattr(slots, "_release", fail)
    with pytest.raises(HarnessError, match="release failure"), slots.trial_slot():
        pass
    assert budget.snapshot().stopped and slots.snapshot().occupied == 1


def test_distinct_durable_budgets_have_independent_caps(tmp_path):
    store = HarnessStore(tmp_path / "store")
    one, two = create(store), create(store)
    first = DurableTrialSlots.create(one, max_active=1)
    second = DurableTrialSlots.create(two, max_active=2)
    with first.trial_slot(), second.trial_slot():
        assert first.snapshot().occupied == second.snapshot().occupied == 1
        with pytest.raises(TrialConcurrencyFull), first.trial_slot():
            pytest.fail("first budget cap bypassed")
        with second.trial_slot():
            assert second.snapshot().occupied == 2
    assert first.snapshot().occupied == second.snapshot().occupied == 0


def test_invalid_slot_records_fail_closed(tmp_path):
    store = HarnessStore(tmp_path / "store")
    budget = create(store)
    slots = DurableTrialSlots.create(budget, max_active=1)
    with sqlite3.connect(slots.path) as db:
        db.execute("INSERT INTO slots VALUES (?,?)", ("invalid", budget.id))
    with pytest.raises(HarnessError, match="slot records"), slots.trial_slot():
        pytest.fail("malformed slot admitted")
