"""Two-profile reviewed comparisons; Docker/provider mocked unless opted in."""

from __future__ import annotations

import dataclasses
import os

import litellm
import pytest
from test_harness_comparison import provider
from test_probe_execution import Boundary
from test_probe_model import SECRET, configured
from test_probe_workspace import repository

from arcen.harness import comparison as comparison_module
from arcen.harness import probe_container
from arcen.harness.budget import SharedBudget
from arcen.harness.cli import _init
from arcen.harness.lineage import HarnessLineage
from arcen.harness.portability import run_portability_comparison
from arcen.harness.resolver import HarnessError

IMAGES = ("sha256:" + "a" * 64, "sha256:" + "b" * 64)


def budget(**changes):
    return SharedBudget(
        **(
            {"max_trials": 4, "max_model_calls": 8, "max_judge_calls": 2, "admission_seconds": 60}
            | changes
        )
    )


def run(args, judge, **changes):
    store, baseline, candidate, cfg, repo, commit = args
    options = {
        "image_ids": IMAGES,
        "repo": repo,
        "commit": commit,
        "budget": budget(),
        "reviewed_inputs": True,
        "reviewed_judge_inputs": True,
        "reviewed_images": True,
    }
    options.update(changes)
    return run_portability_comparison(
        store, baseline, candidate, "inspect project", cfg, judge, **options
    )


def fixture(tmp_path):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    return store, baseline, candidate, cfg, repo, commit


def verdict(_):
    return '{"winner":"tie","confidence":0.5,"reason":"no clear difference"}'


def test_two_images_same_inputs_and_shared_budget_without_adoption(tmp_path, monkeypatch):
    args = fixture(tmp_path)
    store, baseline, candidate, cfg, _, _ = args
    adopted = _init(str(store.root))
    cfg.provider.api_key = "$PORTABILITY_KEY"
    monkeypatch.setenv("PORTABILITY_KEY", SECRET)
    images = []

    class Capture(Boundary):
        def __init__(self, config, *, workspace):
            images.append(config.sandbox.image)
            super().__init__(config, workspace=workspace)

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Capture)

    def mutate(n):
        if n == 1:
            cfg.provider.model = "changed-after-start"
            monkeypatch.setenv("PORTABILITY_KEY", "other-secret")

    calls = provider(monkeypatch, hook=mutate)
    requests = []

    def judge(request):
        requests.append(request)
        assert baseline not in repr(request) and candidate not in repr(request)
        return verdict(request)

    cap = budget()
    result = run(args, judge, budget=cap)
    assert result.outcome == "compared" and result.adoption_authorized is False
    assert images == [IMAGES[0], IMAGES[0], IMAGES[1], IMAGES[1]]
    assert result.first.judgment.winner == result.second.judgment.winner == "tie"
    assert result.first.reference.workspace_sha256 == result.second.reference.workspace_sha256
    assert result.first.reference.commit == result.second.reference.commit == args[-1]
    assert len(calls) == 8 and len(requests) == 2
    assert all(call["api_key"] == SECRET and call["model"] == "openai/mock-model" for call in calls)
    snapshot = cap.snapshot()
    assert (snapshot.trials, snapshot.model_calls, snapshot.judge_calls) == (4, 8, 2)
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    assert not (store.root / "reviews.sqlite3").exists()


def test_workspace_change_rejects_second_profile_before_trial(tmp_path, monkeypatch):
    args = fixture(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    real = comparison_module.snapshot_git_commit
    snapshots = []

    def capture(*a):
        snapshot = real(*a)
        snapshots.append(snapshot)
        if len(snapshots) == 2:
            return dataclasses.replace(snapshot, sha256="f" * 64)
        return snapshot

    monkeypatch.setattr(comparison_module, "snapshot_git_commit", capture)
    cap = budget()
    with pytest.raises(HarnessError, match="workspace snapshot does not match"):
        run(args, verdict, budget=cap)
    snap = cap.snapshot()
    assert len(snapshots) == 2 and len(calls) == 4
    assert (snap.trials, snap.model_calls, snap.judge_calls) == (2, 4, 1)


def test_incomplete_first_profile_never_starts_second(tmp_path, monkeypatch):
    args = fixture(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch, fail_at=1)
    cap = budget()
    result = run(args, lambda _: pytest.fail("judge"), budget=cap)
    assert result.outcome == "inconclusive" and result.second is None
    assert result.adoption_authorized is False and len(calls) == 1 and cap.snapshot().trials == 1


@pytest.mark.parametrize(
    "images",
    [
        None,
        (),
        (IMAGES[0],),
        (IMAGES[0], IMAGES[0]),
        ("tag:latest", IMAGES[1]),
        [*IMAGES],
        ("sha256:" + "A" * 64, IMAGES[1]),
    ],
)
def test_invalid_profiles_fail_before_git_docker_and_provider(tmp_path, monkeypatch, images):
    args = fixture(tmp_path)
    monkeypatch.setattr(comparison_module, "snapshot_git_commit", lambda *a: pytest.fail("git"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("docker")
    )
    monkeypatch.setattr(litellm, "completion", lambda **kw: pytest.fail("provider"))
    cap = budget()
    with pytest.raises(HarnessError, match="two distinct"):
        run(args, verdict, image_ids=images, budget=cap)
    assert cap.snapshot().trials == 0


@pytest.mark.parametrize("option", ["reviewed_inputs", "reviewed_judge_inputs", "reviewed_images"])
def test_all_review_attestations_are_required(tmp_path, monkeypatch, option):
    args = fixture(tmp_path)
    monkeypatch.setattr(comparison_module, "snapshot_git_commit", lambda *a: pytest.fail("git"))
    with pytest.raises(HarnessError, match="explicit review"):
        run(args, verdict, **{option: False})


def test_network_and_process_backends_are_not_accepted(tmp_path, monkeypatch):
    args = fixture(tmp_path)
    monkeypatch.setattr(comparison_module, "snapshot_git_commit", lambda *a: pytest.fail("git"))
    args[3].sandbox.network = "bridge"
    with pytest.raises(HarnessError, match="networking disabled"):
        run(args, verdict)
    args[3].sandbox.network = "none"
    args[3].sandbox.backend = "process"
    with pytest.raises(HarnessError, match="networking disabled"):
        run(args, verdict)


def test_real_two_image_portability_when_explicitly_enabled(tmp_path, monkeypatch):
    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires real Docker and two explicitly provided local image IDs")
    images = (
        os.environ.get("ARCEN_PORTABILITY_IMAGE_A"),
        os.environ.get("ARCEN_PORTABILITY_IMAGE_B"),
    )
    if not all(images):
        pytest.skip("requires ARCEN_PORTABILITY_IMAGE_A and ARCEN_PORTABILITY_IMAGE_B")
    pytest.importorskip("docker")
    args = fixture(tmp_path)
    calls = provider(monkeypatch)
    cap = budget(admission_seconds=300)
    result = run(args, verdict, image_ids=images, budget=cap)
    assert result.outcome == "compared" and result.adoption_authorized is False
    assert result.first.reference.workspace_sha256 == result.second.reference.workspace_sha256
    assert len(calls) == 8 and cap.snapshot().trials == 4


def test_shared_budget_stops_before_second_profile_trial(tmp_path, monkeypatch):
    from arcen.harness.budget import BudgetExhausted

    args = fixture(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    cap = budget(max_trials=2)
    with pytest.raises(BudgetExhausted):
        run(args, verdict, budget=cap)
    state = cap.snapshot()
    assert state.stopped and state.trials == 2 and state.model_calls == 4 and len(calls) == 4


def test_missing_second_image_fails_without_returning_complete_report(tmp_path, monkeypatch):
    from arcen.harness.probe import ProbeUnavailable
    from arcen.sandbox.turn import IsolationUnavailable

    args = fixture(tmp_path)

    class MissingSecond(Boundary):
        def __init__(self, config, *, workspace):
            if config.sandbox.image == IMAGES[1]:
                raise IsolationUnavailable("second image unavailable")
            super().__init__(config, workspace=workspace)

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", MissingSecond)
    calls = provider(monkeypatch)
    cap = budget()
    with pytest.raises(ProbeUnavailable, match="isolation or cleanup failed"):
        run(args, verdict, budget=cap)
    assert len(calls) == 4 and cap.snapshot().trials == 3
