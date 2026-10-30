"""Known exact credentials in reviewed Git snapshots never reach a probe."""

from __future__ import annotations

import base64

import litellm
import pytest
from test_harness_canary import setup as setup_canary
from test_manual_campaign import run as run_campaign
from test_manual_campaign import setup as setup_campaign
from test_probe_model import SECRET, configured
from test_probe_workspace import git, repository

from arcen.harness import probe_container
from arcen.harness.budget import SharedBudget
from arcen.harness.canary import run_manual_canaries
from arcen.harness.comparison import run_reviewed_comparison
from arcen.harness.probe_execution import run_reviewed_probe
from arcen.harness.probe_hygiene import SensitiveSnapshot


def commit_text(repo, text: bytes, name="src/ordinary-data.bin"):
    (repo / name).write_bytes(text)
    git(repo, "add", name)
    git(repo, "commit", "-qm", "snapshot data")
    return git(repo, "rev-parse", "HEAD")


def no_execution(monkeypatch):
    monkeypatch.setattr(litellm, "completion", lambda **_: pytest.fail("provider contacted"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("Docker created")
    )


def new_budget():
    return SharedBudget(max_trials=3, max_model_calls=6, max_judge_calls=2, admission_seconds=60)


def test_direct_reviewed_trial_blocks_provider_key_before_container_or_budget(
    tmp_path, monkeypatch
):
    store, baseline, candidate, config = configured(tmp_path)
    repo, _ = repository(tmp_path)
    commit = commit_text(repo, b"binary\x00prefix" + SECRET.encode() + b"\x00suffix")
    cap = new_budget()
    no_execution(monkeypatch)
    with pytest.raises(SensitiveSnapshot, match="known sensitive value") as error:
        run_reviewed_probe(
            store,
            baseline,
            candidate,
            "task",
            config,
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
            budget=cap,
        )
    assert SECRET not in str(error.value)
    usage = cap.snapshot()
    assert (usage.trials, usage.model_calls, usage.judge_calls) == (0, 0, 0)


def test_paired_comparison_blocks_extra_sensitive_value_before_any_callback(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    repo, _ = repository(tmp_path)
    extra = "additional-client-secret-98"
    commit = commit_text(repo, ("prefix " + extra + " suffix").encode())
    cap = new_budget()
    no_execution(monkeypatch)
    with pytest.raises(SensitiveSnapshot) as error:
        run_reviewed_comparison(
            store,
            baseline,
            candidate,
            "task",
            config,
            lambda _: pytest.fail("judge called"),
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
            reviewed_judge_inputs=True,
            sensitive_values=(extra,),
            budget=cap,
        )
    assert extra not in str(error.value)
    assert cap.snapshot().trials == 0


def test_campaign_stops_cleanly_before_trial_or_pending_review(tmp_path, monkeypatch):
    args = setup_campaign(tmp_path)
    store, baseline, candidates, config, repo, _, reviews = args
    extra = "client-private-secret-xyz"
    commit = commit_text(repo, extra.encode())
    cap = new_budget()
    events = []
    no_execution(monkeypatch)
    result = run_campaign(
        (store, baseline, candidates, config, repo, commit, reviews),
        budget=cap,
        sensitive_values=(extra,),
        on_progress=events.append,
    )
    assert result.stop_reason == "workspace_sensitive" and not result.completed
    assert cap.snapshot().trials == 0 and reviews.list() == ()
    assert events[-1]["reason"] == "workspace_sensitive"
    assert extra not in repr(events) + repr(result)


def test_journaled_sensitive_snapshot_finishes_failed_without_budget_spend(tmp_path, monkeypatch):
    from arcen.harness.campaign_journal import CampaignJournal

    args = setup_campaign(tmp_path)
    store, baseline, candidates, config, repo, _, reviews = args
    commit = commit_text(repo, SECRET.encode())
    updated = (store, baseline, candidates, config, repo, commit, reviews)
    journal = CampaignJournal(store, create=True)
    plan = journal.plan(baseline, candidates, "inspect project", commit)
    cap = new_budget()
    no_execution(monkeypatch)
    result = run_campaign(updated, budget=cap, journal=journal, campaign_id=plan.id)
    saved = journal.get(plan.id)
    assert result.stop_reason == "workspace_sensitive" and saved.state == "failed"
    assert saved.reviews == () and cap.snapshot().trials == 0
    assert SECRET.encode() not in journal.path.read_bytes()


def test_canary_returns_inconclusive_before_budget_or_docker(tmp_path, monkeypatch):
    store, baseline, candidate, config, repo, _, budget = setup_canary(tmp_path)
    commit = commit_text(repo, SECRET.encode())
    no_execution(monkeypatch)
    result = run_manual_canaries(
        store,
        baseline,
        candidate,
        config,
        repo=repo,
        commit=commit,
        budget=budget,
        reviewed_inputs=True,
    )
    assert result.outcome == "inconclusive" and result.findings[0].reference == "inconclusive"
    assert budget.snapshot().trials == 0
    assert SECRET not in repr(result)


@pytest.mark.parametrize("env_reference", [False, True])
def test_lower_level_gateway_blocks_configured_key_before_materializing(
    tmp_path, monkeypatch, env_reference
):
    from arcen.harness.probe_container import open_probe_container
    from arcen.harness.probe_workspace import snapshot_git_commit

    _, _, _, config = configured(tmp_path)
    if env_reference:
        monkeypatch.setenv("ARCEN_TEST_KEY", SECRET)
        config.provider.api_key = "$ARCEN_TEST_KEY"
    repo, _ = repository(tmp_path)
    commit = commit_text(repo, SECRET.encode())
    no_execution(monkeypatch)
    with (
        pytest.raises(SensitiveSnapshot, match="known sensitive value"),
        open_probe_container(snapshot_git_commit(repo, commit), config),
    ):
        pytest.fail("should not open")


def test_exact_byte_check_does_not_claim_to_detect_encoded_secrets(tmp_path):
    from arcen.harness.probe_hygiene import _reject_snapshot_secrets
    from arcen.harness.probe_workspace import snapshot_git_commit

    repo, _ = repository(tmp_path)
    encoded = base64.b64encode(SECRET.encode())
    commit = commit_text(repo, encoded)
    # Encoded/split/unknown credentials remain out of scope and require review.
    _reject_snapshot_secrets(snapshot_git_commit(repo, commit), (SECRET,))
