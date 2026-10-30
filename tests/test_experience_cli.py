"""Offline manual experience CLI: no prompt injection, model calls or adoption."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys

import pytest
from test_harness_experience import prepare
from test_manual_cli import tty

from arcen.harness.cli import main
from arcen.harness.experience import ExperienceLibrary
from arcen.harness.experience_cli_store import open_cli_experience
from arcen.harness.lineage import HarnessLineage


def setup_cli(tmp_path):
    store, baseline, candidate, adopted, ledger, pending, memory, _ = prepare(tmp_path)
    memory.close()
    approved = ledger.get(pending.id)
    assert approved.state == "approved"
    args = [
        "--store",
        str(store.root),
        "experience",
        "record",
        "careful-check",
        "--review",
        approved.id,
    ]
    return store, baseline, candidate, adopted, ledger, approved, args


def answer_record(
    monkeypatch, review, text="Check the output before retrying.", topic="careful-check"
):
    values = iter([text, f"SAVE {topic} {review.id}"])
    monkeypatch.setattr("builtins.input", lambda _: next(values))


def test_record_list_show_are_local_and_no_ref_changes(tmp_path, monkeypatch, capsys):
    import litellm

    store, _, _, adopted, ledger, review, args = setup_cli(tmp_path)
    assert main(["--store", str(store.root), "experience", "list"]) == 0
    assert "No stored" in capsys.readouterr().out
    assert not (store.root / "experience.sqlite3").exists()
    assert not (store.root / "experience.lock").exists()
    tty(monkeypatch)
    monkeypatch.setattr(litellm, "completion", lambda **_: pytest.fail("provider called"))
    answer_record(monkeypatch, review)
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "plaintext" in out and "No model call" in out and "operation=new" in out
    assert (store.root / "experience.sqlite3").stat().st_mode & 0o777 == 0o600
    assert (store.root / "experience.lock").stat().st_mode & 0o777 == 0o600
    assert main(["--store", str(store.root), "experience", "list"]) == 0
    listing = capsys.readouterr().out
    assert (
        "careful-check" in listing
        and review.id in listing
        and "never automatically used" in listing
    )
    assert main(["--store", str(store.root), "experience", "show", "careful-check"]) == 0
    assert "Check the output before retrying." in capsys.readouterr().out
    with open_cli_experience(store, ledger) as lib:
        assert isinstance(lib, ExperienceLibrary) and lib.active()[0].review_id == review.id
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_noninteractive_cancel_and_bad_secrets_never_create_database(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, _, args = setup_cli(tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(args) == 1 and "interactive terminal" in capsys.readouterr().err
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "secret sk-abcdefghijklmnop")
    assert main(args) == 1
    output = capsys.readouterr()
    assert "detected secret" in output.err and "sk-abcdefghijklmnop" not in output.out + output.err
    answers = iter(["Review results.", "CANCEL"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    assert not (store.root / "experience.sqlite3").exists()
    assert not (store.root / "experience.lock").exists()


def test_unapproved_review_and_bad_topic_refused_before_input(tmp_path, monkeypatch, capsys):
    store, baseline, candidate, _, ledger, _, args = setup_cli(tmp_path)
    tty(monkeypatch)
    pending = ledger.request(baseline, candidate)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected prompt"))
    args[args.index("--review") + 1] = pending.id
    assert main(args) == 1 and "approved paired" in capsys.readouterr().err
    args[args.index("record") + 1] = "../escape"
    assert main(args) == 1 and "invalid lesson topic" in capsys.readouterr().err
    assert not (store.root / "experience.sqlite3").exists()


def test_same_topic_consolidates_or_supersedes_and_retains_history(tmp_path, monkeypatch, capsys):
    store, _, _, _, ledger, review, args = setup_cli(tmp_path)
    tty(monkeypatch)
    for text, op in [
        ("First observation.", "new"),
        ("First observation.", "consolidated"),
        ("Second observation.", "superseded"),
    ]:
        answer_record(monkeypatch, review, text)
        assert main(args) == 0 and f"operation={op}" in capsys.readouterr().out
    with open_cli_experience(store, ledger) as library:
        lessons = library.active()
        history = library.memory.history("arcen:harness:manual-lessons:v1", "careful-check")
        assert len(lessons) == 1 and lessons[0].text == "Second observation."
        assert len(history) == 2 and history[0]["invalid_at"] is not None
    assert main(["--store", str(store.root), "experience", "show", "careful-check"]) == 0
    assert "Second observation." in capsys.readouterr().out


def test_review_change_while_confirming_is_refused_without_database(tmp_path, monkeypatch, capsys):
    store, _, _, _, ledger, review, args = setup_cli(tmp_path)
    tty(monkeypatch)

    def answer(prompt):
        if prompt == "Observation: ":
            return "Review the evidence."
        with sqlite3.connect(ledger.path) as db:
            db.execute("UPDATE reviews SET note='changed' WHERE id=?", (review.id,))
        return f"SAVE careful-check {review.id}"

    monkeypatch.setattr("builtins.input", answer)
    assert main(args) == 1 and "review changed" in capsys.readouterr().err
    assert not (store.root / "experience.sqlite3").exists()


def test_expiration_hides_but_does_not_delete(tmp_path, monkeypatch, capsys):
    store, _, _, _, ledger, review, args = setup_cli(tmp_path)
    tty(monkeypatch)
    answer_record(monkeypatch, review)
    assert main(args) == 0
    capsys.readouterr()
    with open_cli_experience(store, ledger) as library:
        lesson = library.active()[0]
    monkeypatch.setattr("arcen.harness.experience.time.time", lambda: lesson.expires_at + 1)
    assert main(["--store", str(store.root), "experience", "list"]) == 0
    assert "No active" in capsys.readouterr().out
    with sqlite3.connect(store.root / "experience.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1


def test_lock_prevents_another_process_read_or_write(tmp_path, monkeypatch, capsys):
    store, _, _, _, ledger, review, args = setup_cli(tmp_path)
    tty(monkeypatch)
    answer_record(monkeypatch, review)
    assert main(args) == 0
    capsys.readouterr()
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    with open_cli_experience(store, ledger):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from arcen.harness.cli import main; import sys; sys.exit(main(sys.argv[1:]))",
                "--store",
                str(store.root),
                "experience",
                "list",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert completed.returncode == 1 and "busy" in completed.stderr
    assert main(["--store", str(store.root), "experience", "list"]) == 0
    assert "careful-check" in capsys.readouterr().out


def test_symlink_db_and_lock_are_rejected_without_touching_victim(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, review, args = setup_cli(tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("safe")
    (store.root / "experience.sqlite3").symlink_to(victim)
    assert main(["--store", str(store.root), "experience", "list"]) == 1
    assert "regular file" in capsys.readouterr().err and victim.read_text() == "safe"
    (store.root / "experience.sqlite3").unlink()
    (store.root / "experience.lock").symlink_to(victim)
    tty(monkeypatch)
    answer_record(monkeypatch, review)
    assert main(args) == 1 and "lock" in capsys.readouterr().err
    assert victim.read_text() == "safe" and not (store.root / "experience.sqlite3").exists()


def test_unrecognized_or_corrupted_database_refused_before_migration(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, review, args = setup_cli(tmp_path)
    path = store.root / "experience.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated (data TEXT)")
    tty(monkeypatch)
    answer_record(monkeypatch, review)
    assert main(args) == 1 and "database identity" in capsys.readouterr().err
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("unrelated",)
        ]


def test_corrupt_schema_or_forged_review_provenance_refused(tmp_path, monkeypatch, capsys):
    store, _, _, _, ledger, review, args = setup_cli(tmp_path)
    tty(monkeypatch)
    answer_record(monkeypatch, review)
    assert main(args) == 0
    capsys.readouterr()
    path = store.root / "experience.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE facts SET sources='[]'")
    assert main(["--store", str(store.root), "experience", "list"]) == 1
    assert "provenance mismatch" in capsys.readouterr().err
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE stray (data TEXT)")
    assert main(["--store", str(store.root), "experience", "list"]) == 1
    assert "database schema" in capsys.readouterr().err
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM stray").fetchone()[0] == 0
    assert ledger.get(review.id).state == "approved"


def test_control_characters_cannot_be_stored_or_displayed(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, _, args = setup_cli(tmp_path)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "hello\x1b[2J\u202eexit")
    assert main(args) == 1 and "invalid or oversized" in capsys.readouterr().err
    assert not (store.root / "experience.sqlite3").exists()


def test_interrupted_observation_never_initializes_database(tmp_path, monkeypatch, capsys):
    store, _, _, _, _, _, args = setup_cli(tmp_path)
    tty(monkeypatch)

    def interrupt(_):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    assert main(args) == 1 and "cancelled" in capsys.readouterr().err
    assert not (store.root / "experience.sqlite3").exists()
