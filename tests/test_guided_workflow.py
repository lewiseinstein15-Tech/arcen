"""Single-terminal guided flow; provider and Docker are deliberately mocked."""

from __future__ import annotations

import json
import sqlite3
import sys

import litellm
import pytest
from test_manual_cli import setup, tty
from test_manual_editor_cli import scripted
from test_probe_execution import Boundary
from test_probe_model import response

from arcen.harness import probe_container
from arcen.harness.campaign_journal import CampaignJournal
from arcen.harness.cli import main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.lineage import HarnessLineage
from arcen.harness.review import ReviewLedger
from arcen.harness.task_bank import TaskBank


def fixture(tmp_path, capsys):
    store, adopted, baseline, _, task, config, repo, old_campaign, _, _ = setup(tmp_path, capsys)
    commit = CampaignJournal(store).get(old_campaign).commit
    task_id = TaskBank(store, create=True).add("guided-task", task.read_text()).digest
    budget = DurableBudget.create(
        store, max_trials=2, max_model_calls=6, max_judge_calls=1, admission_seconds=120
    )
    args = [
        "--store",
        str(store.root),
        "workflow",
        "run",
        "--baseline",
        baseline,
        "--task-id",
        task_id,
        "--config",
        str(config),
        "--repo",
        str(repo),
        "--commit",
        commit,
        "--budget",
        budget.id,
    ]
    return store, adopted, baseline, task_id, budget, args


def db_count(store):
    with sqlite3.connect(store.root / "campaigns.sqlite3") as db:
        return db.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]


def providers(monkeypatch):
    editor_calls = scripted(monkeypatch)
    editor = litellm.completion
    trial_calls = []

    def complete(**kwargs):
        if len(editor_calls) < 2:
            return editor(**kwargs)
        trial_calls.append(kwargs)
        result = (
            "CODE"
            if len(trial_calls) % 2
            else json.dumps([{"title": "check", "tool": "bash", "args": {"cmd": "true"}}])
        )
        return response(result)

    monkeypatch.setattr(litellm, "completion", complete)
    return editor_calls, trial_calls


def test_full_flow_has_distinct_human_gates_and_never_adopts(tmp_path, monkeypatch, capsys):
    store, adopted, baseline, task_id, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    editor_calls, trial_calls = providers(monkeypatch)
    seen = {}

    def answer(prompt):
        if prompt.startswith("Type EDIT "):
            assert not editor_calls and not trial_calls
            return f"EDIT {baseline}"
        if prompt.startswith("Type SELECT"):
            assert len(editor_calls) == 2 and not trial_calls
            out = capsys.readouterr().out
            seen["candidate"] = next(
                line.split()[3]
                for line in out.splitlines()
                if line.startswith("Unadopted invariant candidate:")
            )
            return "SELECT " + seen["candidate"]
        if prompt.startswith("Type RUN "):
            assert not trial_calls
            seen["campaign"] = prompt.split()[2]
            return "RUN " + seen["campaign"]
        if prompt.startswith("Choose A"):
            assert len(trial_calls) == 4
            return "TIE"
        pytest.fail("unexpected prompt: " + prompt)

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "No adoption occurred" in out and "review show" in out
    record = CampaignJournal(store).get(seen["campaign"])
    assert record.state == "completed" and record.task_sha256 == task_id
    assert record.candidates == (seen["candidate"],) and record.budget_id == budget.id
    reviews = ReviewLedger(store).list()
    assert len(reviews) == 1 and reviews[0].state == "pending"
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    usage = budget.snapshot()
    assert (usage.trials, usage.model_calls, usage.judge_calls) == (2, 6, 1)


def test_noninteractive_and_insufficient_budget_refuse_before_editor(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, args = fixture(tmp_path, capsys)
    calls, trials = providers(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(args) == 1 and "interactive terminal" in capsys.readouterr().err
    tty(monkeypatch)
    low = DurableBudget.create(
        store, max_trials=1, max_model_calls=6, max_judge_calls=1, admission_seconds=120
    )
    args[args.index("--budget") + 1] = low.id
    assert main(args) == 1 and "two trial admissions" in capsys.readouterr().err
    assert not calls and not trials and db_count(store) == 1


def test_invalid_commit_task_and_repo_refused_before_model(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, args = fixture(tmp_path, capsys)
    calls, trials = providers(monkeypatch)
    tty(monkeypatch)
    for option, value, message in [
        ("--commit", "HEAD", "full lowercase"),
        ("--task-id", "0" * 64, "unknown task"),
        ("--repo", str(tmp_path / "missing"), "repository directory"),
    ]:
        bad = args.copy()
        bad[bad.index(option) + 1] = value
        assert main(bad) == 1 and message in capsys.readouterr().err
    assert not calls and not trials and db_count(store) == 1


def test_cancel_or_unknown_selection_never_plans_or_runs(tmp_path, monkeypatch, capsys):
    store, adopted, baseline, _, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = providers(monkeypatch)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (
            f"EDIT {baseline}" if prompt.startswith("Type EDIT") else "SELECT " + "0" * 64
        ),
    )
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("unexpected Docker")
    )
    assert main(args) == 1
    assert "generated objects may remain" in capsys.readouterr().err
    assert len(calls) == 2 and not trials and db_count(store) == 1
    assert budget.snapshot().trials == 0
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_cancel_run_keeps_plan_ready_and_never_starts_trial(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = providers(monkeypatch)
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("unexpected Docker")
    )
    seen = {}

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        if prompt.startswith("Type SELECT"):
            out = capsys.readouterr().out
            candidate = next(
                line.split()[3]
                for line in out.splitlines()
                if line.startswith("Unadopted invariant candidate:")
            )
            return "SELECT " + candidate
        if prompt.startswith("Type RUN"):
            seen["campaign"] = prompt.split()[2]
            return "CANCEL"
        pytest.fail("unexpected prompt")

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    assert CampaignJournal(store).get(seen["campaign"]).state == "ready"
    assert len(calls) == 2 and not trials and budget.snapshot().trials == 0
    assert not (store.root / "reviews.sqlite3").exists()


def test_tampered_task_after_editor_never_plans(tmp_path, monkeypatch, capsys):
    store, _, baseline, task_id, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = providers(monkeypatch)

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        out = capsys.readouterr().out
        candidate = next(
            line.split()[3]
            for line in out.splitlines()
            if line.startswith("Unadopted invariant candidate:")
        )
        (store.objects / task_id).write_bytes(b"changed")
        return "SELECT " + candidate

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "integrity" in capsys.readouterr().err
    assert len(calls) == 2 and not trials and budget.snapshot().trials == 0 and db_count(store) == 1


def test_nonexistent_or_symlink_repo_commit_preflight_before_editor(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = providers(monkeypatch)
    bad = args.copy()
    bad[bad.index("--commit") + 1] = "f" * 40
    assert main(bad) == 1 and "preflight failed" in capsys.readouterr().err
    repo = args[args.index("--repo") + 1]
    link = tmp_path / "repo-link"
    link.symlink_to(repo, target_is_directory=True)
    bad = args.copy()
    bad[bad.index("--repo") + 1] = str(link)
    assert main(bad) == 1 and "preflight failed" in capsys.readouterr().err
    assert not calls and not trials and db_count(store) == 1


def test_editor_cancellation_has_no_provider_and_no_plan(tmp_path, monkeypatch, capsys):
    store, _, _, _, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = providers(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "CANCEL")
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    assert not calls and not trials and db_count(store) == 1
    assert budget.snapshot().model_calls == 0


def test_budget_stopped_after_editor_refuses_plan(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = providers(monkeypatch)

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        out = capsys.readouterr().out
        candidate = next(
            line.split()[3]
            for line in out.splitlines()
            if line.startswith("Unadopted invariant candidate:")
        )
        budget.stop()
        return "SELECT " + candidate

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1
    assert capsys.readouterr().err
    assert len(calls) == 2 and not trials and db_count(store) == 1
    assert budget.snapshot().trials == 0


def test_docker_failure_after_editor_does_not_fallback_or_adopt(tmp_path, monkeypatch, capsys):
    from arcen.sandbox.turn import IsolationUnavailable

    store, adopted, baseline, _, budget, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls, trials = providers(monkeypatch)
    seen = {}

    def unavailable(*_args, **_kwargs):
        raise IsolationUnavailable("private daemon error")

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", unavailable)

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        if prompt.startswith("Type SELECT"):
            out = capsys.readouterr().out
            candidate = next(
                line.split()[3]
                for line in out.splitlines()
                if line.startswith("Unadopted invariant candidate:")
            )
            return "SELECT " + candidate
        if prompt.startswith("Type RUN"):
            seen["campaign"] = prompt.split()[2]
            return "RUN " + seen["campaign"]
        pytest.fail("unexpected prompt")

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1
    output = capsys.readouterr()
    assert "reference_isolation_failed" in output.out
    assert "private daemon error" not in output.out + output.err
    assert len(calls) == 2 and not trials
    assert CampaignJournal(store).get(seen["campaign"]).state == "failed"
    assert budget.snapshot().model_calls == 2
    assert ReviewLedger(store).list() == ()
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_identical_generated_candidates_are_only_listed_once(tmp_path, monkeypatch, capsys):
    import difflib

    store, _, baseline, _, _, args = fixture(tmp_path, capsys)
    tty(monkeypatch)
    calls = []

    def identical(**kwargs):
        calls.append(kwargs)
        request = json.loads(kwargs["messages"][-1]["content"])
        path = "prompts/draft.md"
        old = request["components"][path]
        patch = "".join(
            difflib.unified_diff(
                old.splitlines(True),
                (old + "\nSame edit.\n").splitlines(True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
        return response(json.dumps({"path": path, "diff": patch}))

    monkeypatch.setattr(litellm, "completion", identical)

    def answer(prompt):
        if prompt.startswith("Type EDIT"):
            return f"EDIT {baseline}"
        out = capsys.readouterr().out
        candidates = [
            line.split()[3]
            for line in out.splitlines()
            if line.startswith("Unadopted ") and "candidate:" in line
        ]
        assert len(candidates) == 2 and candidates[0] == candidates[1]
        choices = out.split("Choose or compose generated candidates", 1)[1]
        assert choices.count(candidates[0]) == 1
        return "CANCEL"

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1
    assert "generated objects may remain" in capsys.readouterr().err
    assert len(calls) == 2 and db_count(store) == 1
