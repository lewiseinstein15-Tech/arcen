"""Composition from campaign metadata: local evidence, not adoption authority."""

from __future__ import annotations

import sqlite3
import sys

import pytest
from test_harness_comparison import provider
from test_harness_probe import changed
from test_manual_campaign import run, setup
from test_manual_cli import tty
from test_probe_execution import Boundary

from arcen.harness import probe_container
from arcen.harness.campaign_journal import CampaignJournal
from arcen.harness.cli import _init, main
from arcen.harness.evidence_composition import prepare_recorded_composition
from arcen.harness.lineage import HarnessLineage
from arcen.harness.resolver import HarnessError
from arcen.harness.task_bank import TaskBank


def completed(tmp_path, monkeypatch, *, conflict=False):
    args = setup(tmp_path)
    store, baseline, candidates, cfg, repo, commit, ledger = args
    adopted = _init(str(store.root))
    if conflict:
        base = store.get_manifest(baseline)
        path = "prompts/draft.md"
        original = store.get_blob(base.components[path])
        candidates = (
            changed(store, base, path, original + b"one\n"),
            changed(store, base, path, original + b"two\n"),
        )
        args = (store, baseline, candidates, cfg, repo, commit, ledger)
    task_id = TaskBank(store, create=True).add("task", "inspect project").digest
    journal = CampaignJournal(store, create=True)
    plan = journal.plan(baseline, candidates, "inspect project", commit)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    result = run(args, journal=journal, campaign_id=plan.id)
    assert result.stop_reason is None and len(calls) == 6
    record = journal.get(plan.id)
    assert record.state == "completed" and len(record.reviews) == 2
    cli = [
        "--store",
        str(store.root),
        "campaign",
        "compose",
        record.id,
        "--task-id",
        task_id,
        "--review",
        record.reviews[0],
        "--review",
        record.reviews[1],
    ]
    return store, adopted, baseline, task_id, journal, ledger, record, calls, cli


def test_recorded_composition_displays_evidence_and_creates_only_unadopted_candidate(
    tmp_path, monkeypatch, capsys
):
    store, adopted, baseline, task_id, journal, ledger, record, calls, cli = completed(
        tmp_path, monkeypatch
    )
    tty(monkeypatch)
    before_records = ledger.list()
    before_calls = len(calls)
    before_journal = journal.get(record.id)
    import litellm

    monkeypatch.setattr(litellm, "completion", lambda **_: pytest.fail("unexpected provider"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("unexpected Docker")
    )
    seen = {}

    def confirm(prompt):
        output = capsys.readouterr().out
        assert "unsigned" in output and "full trajectories are not retained" in output
        assert "recorded winner=tie" in output and all(x in output for x in record.reviews)
        assert "inspect project" in output
        seen["prompt"] = prompt
        return f"COMPOSE {record.id}"

    monkeypatch.setattr("builtins.input", confirm)
    assert main(cli) == 0
    out = capsys.readouterr().out
    composite = next(
        line.split()[3]
        for line in out.splitlines()
        if line.startswith("Unadopted composite candidate:")
    )
    assert (
        "not behaviorally tested" in out and "No plan, trial, approval or adoption occurred" in out
    )
    base = store.get_manifest(baseline)
    result = store.get_manifest(composite)
    assert result.components["prompts/draft.md"] != base.components["prompts/draft.md"]
    assert result.components["prompts/forge.md"] != base.components["prompts/forge.md"]
    assert ledger.list() == before_records and journal.get(record.id) == before_journal
    assert len(calls) == before_calls
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    assert (
        prepare_recorded_composition(store, record.id, task_id, record.reviews).campaign == record
    )


def test_noninteractive_or_cancel_has_no_side_effect(tmp_path, monkeypatch, capsys):
    store, _, _, _, journal, _, record, calls, cli = completed(tmp_path, monkeypatch)
    before = set(store.objects.iterdir())
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(cli) == 1 and "interactive terminal" in capsys.readouterr().err
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "CANCEL")
    assert main(cli) == 1 and "cancelled" in capsys.readouterr().err
    assert (
        before == set(store.objects.iterdir())
        and journal.get(record.id) == record
        and len(calls) == 6
    )


def test_conflicts_refuse_without_writing_or_running(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, _, record, calls, cli = completed(tmp_path, monkeypatch, conflict=True)
    tty(monkeypatch)
    before = set(store.objects.iterdir())
    monkeypatch.setattr("builtins.input", lambda _: f"COMPOSE {record.id}")
    assert main(cli) == 1
    output = capsys.readouterr()
    assert "Conflict: prompts/draft.md" in output.out
    assert all(x in output.out for x in record.reviews)
    assert "no composite candidate created" in output.err
    assert before == set(store.objects.iterdir()) and len(calls) == 6


def test_invalid_ids_task_and_incomplete_campaign_refuse_before_prompt(
    tmp_path, monkeypatch, capsys
):
    store, _, baseline, task_id, journal, _, record, calls, cli = completed(tmp_path, monkeypatch)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected prompt"))
    before = set(store.objects.iterdir())
    other = TaskBank(store, create=True).add("other", "different task").digest
    cases = [
        (record.id, other, record.reviews, "does not match"),
        (record.id, task_id, (record.reviews[0], record.reviews[0]), "distinct"),
        (record.id, task_id, (record.reviews[0],), "2 to 5"),
        (record.id, task_id, (record.reviews[0], "0" * 32), "not linked"),
    ]
    unstarted = journal.plan(baseline, record.candidates, "inspect project", record.commit)
    cases.append((unstarted.id, task_id, record.reviews, "completed campaign"))
    for campaign_id, task, reviews, message in cases:
        with pytest.raises(HarnessError, match=message):
            prepare_recorded_composition(store, campaign_id, task, reviews)
    assert main(cli[:-2]) == 1 and "2 to 5" in capsys.readouterr().err
    assert len(calls) == 6
    assert before <= set(store.objects.iterdir())


def test_rejected_review_and_mismatched_recorded_workspace_rejected(tmp_path, monkeypatch):
    store, _, _, task_id, _, ledger, record, _, _ = completed(tmp_path, monkeypatch)
    ledger.resolve(record.reviews[0], "rejected", "operator", saw_diff=True)
    with pytest.raises(HarnessError, match="rejected"):
        prepare_recorded_composition(store, record.id, task_id, record.reviews)
    # Restore a valid pending decision in trusted local metadata for a separate mismatch case.
    with sqlite3.connect(ledger.path) as db:
        db.execute(
            "UPDATE reviews SET state='pending',reviewer=NULL,note=NULL,decided_at=NULL WHERE id=?",
            (record.reviews[0],),
        )
        db.execute("UPDATE reviews SET workspace=? WHERE id=?", ("f" * 64, record.reviews[1]))
    with pytest.raises(HarnessError, match="workspace"):
        prepare_recorded_composition(store, record.id, task_id, record.reviews)


def test_review_change_during_confirmation_is_rechecked(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, ledger, record, calls, cli = completed(tmp_path, monkeypatch)
    tty(monkeypatch)
    before = set(store.objects.iterdir())

    def confirm(_):
        ledger.resolve(record.reviews[0], "approved", "local-user", saw_diff=True)
        return f"COMPOSE {record.id}"

    monkeypatch.setattr("builtins.input", confirm)
    assert main(cli) == 1 and "changed since display" in capsys.readouterr().err
    assert set(store.objects.iterdir()) == before and len(calls) == 6


def test_tampered_task_or_candidate_refuses_before_confirmation(tmp_path, monkeypatch, capsys):
    store, _, _, task_id, _, _, record, calls, cli = completed(tmp_path, monkeypatch)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected prompt"))
    path = store.objects / task_id
    raw = path.read_bytes()
    path.write_bytes(b"bad task")
    assert main(cli) == 1 and "integrity" in capsys.readouterr().err
    path.write_bytes(raw)
    (store.objects / record.candidates[0]).write_bytes(b"bad candidate")
    assert main(cli) == 1 and "integrity" in capsys.readouterr().err
    assert len(calls) == 6


def test_foreign_static_and_commit_mismatch_metadata_fail_closed(tmp_path, monkeypatch):
    store, _, baseline, task_id, journal, ledger, record, _, _ = completed(tmp_path, monkeypatch)
    static = ledger.request(baseline, record.candidates[0])
    # The task journal contains the association; the selected record itself
    # must still be paired and match its ordinal/candidate/commit.
    with sqlite3.connect(journal.path) as db:
        db.execute(
            "UPDATE campaign_reviews SET review_id=? WHERE campaign_id=? AND ordinal=0",
            (static.id, record.id),
        )
    with pytest.raises(HarnessError, match="metadata"):
        prepare_recorded_composition(store, record.id, task_id, (static.id, record.reviews[1]))
    with sqlite3.connect(journal.path) as db:
        db.execute(
            "UPDATE campaign_reviews SET review_id=? WHERE campaign_id=? AND ordinal=0",
            (record.reviews[0], record.id),
        )
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE reviews SET commit_id=? WHERE id=?", ("f" * 40, record.reviews[1]))
    with pytest.raises(HarnessError, match="metadata"):
        prepare_recorded_composition(store, record.id, task_id, record.reviews)


def test_subselection_from_three_candidate_campaign_preserves_review_association(
    tmp_path, monkeypatch
):
    from test_manual_campaign import budget

    args = setup(tmp_path)
    store, baseline, candidates, cfg, repo, commit, ledger = args
    base = store.get_manifest(baseline)
    third = changed(
        store,
        base,
        "prompts/temper.md",
        store.get_blob(base.components["prompts/temper.md"]) + b"careful verification\n",
    )
    candidates = (*candidates, third)
    args = (store, baseline, candidates, cfg, repo, commit, ledger)
    _init(str(store.root))
    task_id = TaskBank(store, create=True).add("task", "inspect project").digest
    journal = CampaignJournal(store, create=True)
    plan = journal.plan(baseline, candidates, "inspect project", commit)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch)
    result = run(
        args,
        budget=budget(max_trials=4, max_model_calls=8, max_judge_calls=3),
        journal=journal,
        campaign_id=plan.id,
    )
    assert result.stop_reason is None
    record = journal.get(plan.id)
    inputs = prepare_recorded_composition(
        store, record.id, task_id, (record.reviews[2], record.reviews[0])
    )
    assert [r.candidate_id for r in inputs.reviews] == [third, candidates[0]]
    assert {p.path for p in inputs.proposals} == {"prompts/draft.md", "prompts/temper.md"}
    assert inputs.proposal_reviews == (record.reviews[2], record.reviews[0])


def test_result_can_be_planned_and_compared_separately_without_adoption(
    tmp_path, monkeypatch, capsys
):
    from test_probe_model import SECRET

    from arcen.harness.durable_budget import DurableBudget

    store, adopted, baseline, task_id, journal, ledger, record, calls, cli = completed(
        tmp_path, monkeypatch
    )
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: f"COMPOSE {record.id}")
    assert main(cli) == 0
    output = capsys.readouterr().out
    composite = next(
        line.split()[3]
        for line in output.splitlines()
        if line.startswith("Unadopted composite candidate:")
    )
    cap = DurableBudget.create(
        store, max_trials=2, max_model_calls=4, max_judge_calls=1, admission_seconds=120
    )
    plan = [
        "--store",
        str(store.root),
        "campaign",
        "plan",
        "--baseline",
        baseline,
        "--candidate",
        composite,
        "--task-id",
        task_id,
        "--commit",
        record.commit,
        "--budget",
        cap.id,
    ]
    assert main(plan) == 0
    output = capsys.readouterr().out
    campaign = next(
        line.split()[2] for line in output.splitlines() if line.startswith("Campaign plan:")
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        f"provider:\n  name: custom\n  base_url: https://provider.example/v1\n  api_key: {SECRET}\n  model: mock-model\n"
    )
    run_args = [
        "--store",
        str(store.root),
        "campaign",
        "run",
        campaign,
        "--task-id",
        task_id,
        "--config",
        str(config),
        "--repo",
        str(tmp_path / "repo"),
        "--budget",
        cap.id,
    ]
    trial_calls = provider(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    answers = iter([f"RUN {campaign}", "TIE"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(run_args) == 0 and "No adoption occurred" in capsys.readouterr().out
    assert journal.get(campaign).state == "completed"
    assert len(trial_calls) == 4 and len(ledger.list()) == 3
    assert (
        len(calls) == 6
        and HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    )


def test_multicomponent_candidates_reconstruct_and_deduplicate_shared_edit(tmp_path, monkeypatch):
    from types import MappingProxyType

    from arcen.harness.composer import compose_proposals
    from arcen.harness.manifest import Manifest

    args = setup(tmp_path)
    store, baseline, _, cfg, repo, commit, ledger = args
    base = store.get_manifest(baseline)
    draft = "prompts/draft.md"
    shared = store.put_blob(store.get_blob(base.components[draft]) + b"shared check\n")
    candidates = []
    for path in ("prompts/forge.md", "prompts/temper.md"):
        components = dict(base.components)
        components[draft] = shared
        components[path] = store.put_blob(store.get_blob(base.components[path]) + b"extra check\n")
        candidates.append(
            store.put_manifest(
                Manifest(base.schema_version, base.model_pin, MappingProxyType(components))
            )
        )
    args = (store, baseline, tuple(candidates), cfg, repo, commit, ledger)
    task_id = TaskBank(store, create=True).add("task", "inspect project").digest
    journal = CampaignJournal(store, create=True)
    plan = journal.plan(baseline, tuple(candidates), "inspect project", commit)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch)
    assert run(args, journal=journal, campaign_id=plan.id).stop_reason is None
    record = journal.get(plan.id)
    inputs = prepare_recorded_composition(store, plan.id, task_id, record.reviews)
    result = compose_proposals(store, baseline, inputs.proposals)
    assert result.candidate_id and not result.conflicts
    manifest = store.get_manifest(result.candidate_id)
    assert store.get_blob(manifest.components[draft]).count(b"shared check\n") == 1
    assert set(result.changed_paths) == {draft, "prompts/forge.md", "prompts/temper.md"}
