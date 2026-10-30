"""Manual task bank and --task-id workflow; Docker/provider are mocked."""

from __future__ import annotations

import hashlib
import sys

import pytest
from test_harness_comparison import provider
from test_manual_cli import setup, tty
from test_manual_editor_cli import editor_args, scripted
from test_probe_execution import Boundary

from arcen.harness import probe_container
from arcen.harness.campaign_journal import CampaignJournal
from arcen.harness.cli import _init, main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.lineage import HarnessLineage
from arcen.harness.review import ReviewLedger
from arcen.harness.task_bank import TaskBank


def import_task(store, path, capsys):
    assert main(["--store", str(store.root), "task", "import", "example", str(path)]) == 0
    out = capsys.readouterr().out
    assert "stored unencrypted" in out
    return next(line.split()[2] for line in out.splitlines() if line.startswith("Stored task:"))


def test_ls_missing_store_is_read_only_and_import_show_doctor(tmp_path, capsys):
    root = tmp_path / "store"
    _init(str(root))
    assert main(["--store", str(root), "task", "ls"]) == 0
    assert "No stored tasks" in capsys.readouterr().out
    assert not (root / "tasks.sqlite3").exists()
    task = tmp_path / "task.txt"
    task.write_text("Review the project.\n")
    assert main(["--store", str(root), "task", "import", "review", str(task)]) == 0
    out = capsys.readouterr().out
    digest = next(line.split()[2] for line in out.splitlines() if line.startswith("Stored task:"))
    assert main(["--store", str(root), "task", "ls"]) == 0
    assert digest in capsys.readouterr().out
    assert main(["--store", str(root), "task", "show", digest]) == 0
    assert "Review the project." in capsys.readouterr().out
    assert main(["--store", str(root), "doctor"]) == 0
    assert "tasks=1" in capsys.readouterr().out


def test_interactive_new_requires_terminal_and_confirmation_before_write(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "store"
    _init(str(root))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(["--store", str(root), "task", "new", "review"]) == 1
    assert "interactive terminal" in capsys.readouterr().err
    tty(monkeypatch)
    answers = iter(["Inspect the project", "no"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(["--store", str(root), "task", "new", "review"]) == 1
    assert "cancelled" in capsys.readouterr().err
    assert not (root / "tasks.sqlite3").exists()
    digest = hashlib.sha256(b"Inspect the project").hexdigest()
    answers = iter(["Inspect the project", f"STORE {digest}"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(["--store", str(root), "task", "new", "review"]) == 0
    assert digest in capsys.readouterr().out


def test_campaign_plan_and_run_from_task_id_preserves_hash_and_review_gate(
    tmp_path, monkeypatch, capsys
):
    store, adopted, baseline, candidate, task, config, repo, old_campaign, budget_id, _ = setup(
        tmp_path, capsys
    )
    digest = import_task(store, task, capsys)
    commit = CampaignJournal(store).get(old_campaign).commit
    assert (
        main(
            [
                "--store",
                str(store.root),
                "campaign",
                "plan",
                "--baseline",
                baseline,
                "--candidate",
                candidate,
                "--task-id",
                digest,
                "--commit",
                commit,
                "--budget",
                budget_id,
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    campaign = next(
        line.split()[2] for line in out.splitlines() if line.startswith("Campaign plan:")
    )
    assert CampaignJournal(store).get(campaign).task_sha256 == digest
    tty(monkeypatch)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    answers = iter([f"RUN {campaign}", "TIE"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    arguments = [
        "--store",
        str(store.root),
        "campaign",
        "run",
        campaign,
        "--task-id",
        digest,
        "--config",
        str(config),
        "--repo",
        str(repo),
        "--budget",
        budget_id,
    ]
    assert main(arguments) == 0
    assert "No adoption occurred" in capsys.readouterr().out
    assert len(calls) == 4 and len(ReviewLedger(store).list()) == 1
    assert CampaignJournal(store).get(campaign).state == "completed"
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_tampered_or_wrong_task_id_refused_before_confirmation_and_provider(
    tmp_path, monkeypatch, capsys
):
    store, _, _, _, task, _, _, campaign, budget_id, run_args = setup(tmp_path, capsys)
    digest = import_task(store, task, capsys)
    bad = task.with_name("other.txt")
    bad.write_text("Different task")
    assert main(["--store", str(store.root), "task", "import", "other", str(bad)]) == 0
    other_out = capsys.readouterr().out
    other = next(
        line.split()[2] for line in other_out.splitlines() if line.startswith("Stored task:")
    )
    tty(monkeypatch)
    calls = provider(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected prompt"))
    index = run_args.index("--task-file")
    run_args[index : index + 2] = ["--task-id", other]
    assert main(run_args) == 1
    assert "does not match" in capsys.readouterr().err
    (store.objects / digest).write_bytes(b"tampered")
    run_args[index + 1] = digest
    assert main(run_args) == 1
    assert "integrity" in capsys.readouterr().err
    assert not calls and DurableBudget(store, budget_id).snapshot().trials == 0
    assert CampaignJournal(store).get(campaign).state == "ready"


def test_editor_can_use_task_id_only_after_explicit_confirmation(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, task, config, _, _, budget_id, _ = setup(tmp_path, capsys)
    digest = import_task(store, task, capsys)
    arguments = editor_args(store, baseline, task, config, budget_id)
    index = arguments.index("--task-file")
    arguments[index : index + 2] = ["--task-id", digest]
    tty(monkeypatch)
    calls = scripted(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: f"EDIT {baseline}")
    assert main(arguments) == 0
    assert len(calls) == 2 and "Unadopted invariant candidate:" in capsys.readouterr().out
    assert TaskBank(store).read(digest) == task.read_text()


@pytest.mark.parametrize("command", ["editor", "plan", "run"])
def test_task_file_and_id_are_mutually_exclusive(command, tmp_path, capsys):
    root = str(tmp_path / "store")
    common = ["--store", root]
    if command == "editor":
        args = [
            "editor",
            "propose",
            "--baseline",
            "unused",
            "--config",
            "unused",
            "--budget",
            "unused",
        ]
    elif command == "plan":
        args = [
            "campaign",
            "plan",
            "--baseline",
            "unused",
            "--candidate",
            "unused",
            "--commit",
            "unused",
            "--budget",
            "unused",
        ]
    else:
        args = [
            "campaign",
            "run",
            "unused",
            "--config",
            "unused",
            "--repo",
            "unused",
            "--budget",
            "unused",
        ]
    with pytest.raises(SystemExit) as exc:
        main(common + args + ["--task-file", "task", "--task-id", "0" * 64])
    assert exc.value.code == 2
    assert "not allowed" in capsys.readouterr().err


def test_task_show_sanitizes_control_characters_without_changing_data(tmp_path, capsys):
    root = tmp_path / "store"
    _init(str(root))
    task = tmp_path / "task.txt"
    task.write_text("Inspect\x1b[2J\u202ehidden")
    assert main(["--store", str(root), "task", "import", "display", str(task)]) == 0
    out = capsys.readouterr().out
    digest = next(line.split()[2] for line in out.splitlines() if line.startswith("Stored task:"))
    assert main(["--store", str(root), "task", "show", digest]) == 0
    shown = capsys.readouterr().out
    assert "\x1b" not in shown and "\u202e" not in shown
    assert digest == hashlib.sha256(task.read_bytes()).hexdigest()


def test_import_known_secret_refused_without_creating_database(tmp_path, capsys):
    root = tmp_path / "store"
    _init(str(root))
    task = tmp_path / "task.txt"
    task.write_text("token sk-abcdefghijklmnop")
    assert main(["--store", str(root), "task", "import", "secret", str(task)]) == 1
    assert "sk-abcdefghijklmnop" not in capsys.readouterr().err
    assert not (root / "tasks.sqlite3").exists()


def test_doctor_rejects_corrupted_task_blob(tmp_path, capsys):
    root = tmp_path / "store"
    _init(str(root))
    task = tmp_path / "task.txt"
    task.write_text("A task")
    assert main(["--store", str(root), "task", "import", "sample", str(task)]) == 0
    out = capsys.readouterr().out
    digest = next(line.split()[2] for line in out.splitlines() if line.startswith("Stored task:"))
    (root / "objects" / "sha256" / digest).write_bytes(b"wrong")
    assert main(["--store", str(root), "doctor"]) == 1
    assert "integrity" in capsys.readouterr().err
