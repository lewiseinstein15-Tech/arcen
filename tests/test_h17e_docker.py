"""Opt-in real Docker parallel probes with cooperative durable slot saturation.

Provider responses are mocked. The reference and both candidates use the
same reviewed snapshot; no judge, adoption, crash recovery, or network call.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import litellm
import pytest
from test_harness_parallel_trials import run
from test_manual_campaign import setup
from test_probe_execution import Boundary
from test_probe_model import response

from arcen.harness import probe_container
from arcen.harness.cli import _init
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.durable_trial_slots import DurableTrialSlots
from arcen.harness.lineage import HarnessLineage
from arcen.sandbox.turn import DockerTurnRegistry


def exercise_parallel(tmp_path, monkeypatch, *, real_docker):
    args = setup(tmp_path)
    store, baseline, candidates, cfg, repo, commit, _ = args
    cfg.sandbox.image = os.environ.get("ARCEN_H12_DOCKER_IMAGE", "arcen-h12-test:local")
    adopted = _init(str(store.root))
    budget = DurableBudget.create(
        store, max_trials=3, max_model_calls=6, max_judge_calls=0, admission_seconds=600
    )
    slots = DurableTrialSlots.create(budget, max_active=2)
    monkeypatch.setenv("ARCEN_H17E_HOST_MARKER", "host-only-test-marker")
    lock = threading.Lock()
    both_started, release = threading.Event(), threading.Event()
    ids, outcomes, calls = [], [], []

    class TrackingRegistry(DockerTurnRegistry if real_docker else Boundary):
        def __init__(self, config, *, workspace):
            super().__init__(config, workspace=workspace)
            with lock:
                identifier = self._container.id if real_docker else f"mock-{len(ids)}"
                ids.append(identifier)
                ordinal = len(ids)
                if ordinal == 3:
                    both_started.set()
            if ordinal > 1:
                # Both candidate containers remain alive while a separate process
                # verifies the durable cap. If setup fails, clean this registry.
                try:
                    if not release.wait(timeout=90):
                        raise RuntimeError("candidate synchronization timed out")
                except BaseException:
                    self.close(strict=True)
                    raise

        def dispatch(self, name, args):
            outcome = super().dispatch(name, args)
            with lock:
                outcomes.append(outcome)
            return outcome

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", TrackingRegistry)

    def completion(**kwargs):
        with lock:
            calls.append(kwargs)
        command = (
            'test -f src/main.py && test -z "${ARCEN_H17E_HOST_MARKER:-}" '
            "&& printf changed > src/main.py"
        )
        user_text = kwargs["messages"][-1]["content"]
        text = (
            json.dumps([{"title": "check", "tool": "bash", "args": {"cmd": command}}])
            if user_text.startswith("Goal: inspect project\nReturn ONLY a JSON array")
            else "CODE"
        )
        return response(text)

    monkeypatch.setattr(litellm, "completion", completion)

    def inspect_from_other_process():
        try:
            assert both_started.wait(timeout=85), "candidate containers did not both start"
            assert slots.snapshot().occupied == 2
            script = """
import sys
from arcen.harness.budget import TrialConcurrencyFull
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.durable_trial_slots import DurableTrialSlots
from arcen.harness.store import HarnessStore
slots = DurableTrialSlots(DurableBudget(HarnessStore(sys.argv[1]), sys.argv[2]))
assert slots.snapshot().occupied == 2
try:
    with slots.trial_slot():
        raise AssertionError('third trial admitted')
except TrialConcurrencyFull:
    print('DURABLE_CAP_FULL')
"""
            check = subprocess.run(
                [sys.executable, "-c", script, str(store.root), budget.id],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
                env=os.environ.copy(),
            )
            assert check.returncode == 0, check.stderr
            assert "DURABLE_CAP_FULL" in check.stdout
            assert slots.snapshot().occupied == 2
        finally:
            release.set()

    with ThreadPoolExecutor(max_workers=1) as monitor:
        check = monitor.submit(inspect_from_other_process)
        try:
            result = run(args, budget, durable_slots=slots)
        finally:
            # On a runner failure do not leave a candidate waiting indefinitely.
            if not both_started.is_set():
                both_started.set()
                release.set()
        assert result.stop_reason is None, f"parallel probe stopped: {result.stop_reason}"
        check.result(timeout=120)

    assert result.reference.status == "ok" and result.reference.candidate_id == baseline
    assert [item.candidate_id for item in result.candidates] == list(candidates)
    assert all(item.status == "ok" for item in result.candidates)
    assert result.stop_reason is None and result.unstarted == ()
    assert all(
        item.result.workspace_sha256 == result.workspace_sha256 and item.result.commit == commit
        for item in (result.reference, *result.candidates)
    )
    assert len(ids) == len(set(ids)) == 3
    assert len(outcomes) == 6 and all(item["ok"] is True for item in outcomes)
    assert len(calls) == 6
    snap = budget.snapshot()
    assert (snap.trials, snap.model_calls, snap.judge_calls) == (3, 6, 0)
    assert not snap.stopped and slots.snapshot().occupied == 0
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    assert (repo / "src/main.py").read_text() == "print('committed')\n"
    return ids


def test_h17e_parallel_durable_mocked_boundary(tmp_path, monkeypatch):
    exercise_parallel(tmp_path, monkeypatch, real_docker=False)


def test_h17e_parallel_durable_real_docker(tmp_path, monkeypatch):
    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("set ARCEN_TEST_DOCKER_ISOLATION=1 to require real Docker")
    try:
        import docker
    except ImportError:
        pytest.fail("real Docker requested but the Docker Python SDK is missing")
    client = docker.from_env()
    try:
        assert client.ping()
        client.images.get(os.environ.get("ARCEN_H12_DOCKER_IMAGE", "arcen-h12-test:local"))
        ids = exercise_parallel(tmp_path, monkeypatch, real_docker=True)
        for identifier in ids:
            with pytest.raises(docker.errors.NotFound):
                client.containers.get(identifier)
    finally:
        client.close()
