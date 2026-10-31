"""Manual recorded-campaign conflict patches; no real Docker/provider."""

from __future__ import annotations

import difflib
from dataclasses import replace

import pytest
from test_evidence_composition import completed
from test_manual_cli import tty

from arcen.harness import evidence_composition, probe_container
from arcen.harness.cli import main
from arcen.harness.lineage import HarnessLineage


def fixture(tmp_path, monkeypatch):
    data = completed(tmp_path, monkeypatch, conflict=True)
    store, _, baseline, *_ = data
    path = "prompts/draft.md"
    original = store.get_blob(store.get_manifest(baseline).components[path]).decode()
    resolved = original + "resolved manually\n"
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(True),
            resolved.splitlines(True),
            fromfile="a/" + path,
            tofile="b/" + path,
        )
    )
    file = tmp_path / "resolved.diff"
    file.write_text(diff)
    return data, file


def test_manual_resolution_displays_patch_and_requires_second_confirmation(
    tmp_path, monkeypatch, capsys
):
    data, file = fixture(tmp_path, monkeypatch)
    store, adopted, baseline, _, journal, ledger, record, calls, cli = data
    tty(monkeypatch)
    before = set(store.objects.iterdir())
    reviews_before = ledger.list()
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("docker called")
    )
    answers = iter([f"COMPOSE {record.id}", str(file), f"RESOLVE {record.id}"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main([*cli, "--resolve-conflicts"]) == 0
    out = capsys.readouterr().out
    assert "Conflict: prompts/draft.md" in out and "replaces ALL" in out
    assert "Replacement diff" in out and "resolved manually" in out
    assert "No plan, trial, approval or adoption occurred" in out
    candidate = next(
        line.split()[3]
        for line in out.splitlines()
        if line.startswith("Unadopted composite candidate:")
    )
    manifest = store.get_manifest(candidate)
    assert b"resolved manually" in store.get_blob(manifest.components["prompts/draft.md"])
    assert before < set(store.objects.iterdir())
    assert ledger.list() == reviews_before and journal.get(record.id) == record and len(calls) == 6
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    assert candidate != baseline


@pytest.mark.parametrize("stage", ["patch_cancel", "confirmation_cancel", "invalid_patch"])
def test_cancel_or_invalid_patch_never_writes_candidate(tmp_path, monkeypatch, capsys, stage):
    data, file = fixture(tmp_path, monkeypatch)
    store, _, _, _, _, _, record, calls, cli = data
    tty(monkeypatch)
    before = set(store.objects.iterdir())
    if stage == "patch_cancel":
        answers = [f"COMPOSE {record.id}", "CANCEL"]
    elif stage == "confirmation_cancel":
        answers = [f"COMPOSE {record.id}", str(file), "CANCEL"]
    else:
        file.write_text("invalid")
        answers = [f"COMPOSE {record.id}", str(file)]
    values = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _: next(values))
    assert main([*cli, "--resolve-conflicts"]) == 1
    err = capsys.readouterr().err
    assert "cancelled" in err if stage != "invalid_patch" else "invalid replacement" in err
    assert set(store.objects.iterdir()) == before and len(calls) == 6


def test_changed_campaign_before_final_confirmation_is_refused(tmp_path, monkeypatch, capsys):
    data, file = fixture(tmp_path, monkeypatch)
    store, _, _, _, _, _, record, calls, cli = data
    tty(monkeypatch)
    before = set(store.objects.iterdir())
    real = evidence_composition.prepare_recorded_composition
    seen = []

    def changing(*args, **kwargs):
        result = real(*args, **kwargs)
        seen.append(1)
        return replace(result, task="different") if len(seen) == 3 else result

    monkeypatch.setattr(evidence_composition, "prepare_recorded_composition", changing)
    answers = iter([f"COMPOSE {record.id}", str(file), f"RESOLVE {record.id}"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main([*cli, "--resolve-conflicts"]) == 1
    assert "changed since display" in capsys.readouterr().err
    assert set(store.objects.iterdir()) == before and len(calls) == 6


def test_symlink_patch_file_rejected_before_candidate_write(tmp_path, monkeypatch, capsys):
    data, file = fixture(tmp_path, monkeypatch)
    store, _, _, _, _, _, record, calls, cli = data
    link = tmp_path / "link.diff"
    link.symlink_to(file)
    tty(monkeypatch)
    before = set(store.objects.iterdir())
    answers = iter([f"COMPOSE {record.id}", str(link)])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main([*cli, "--resolve-conflicts"]) == 1
    assert "conflict editor failed" in capsys.readouterr().err
    assert set(store.objects.iterdir()) == before and len(calls) == 6


def test_patch_is_frozen_before_final_confirmation(tmp_path, monkeypatch, capsys):
    data, file = fixture(tmp_path, monkeypatch)
    store, _, _, _, _, _, record, calls, cli = data
    tty(monkeypatch)
    prompts = []

    def respond(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return f"COMPOSE {record.id}"
        if len(prompts) == 2:
            return str(file)
        file.write_text("changed after display")
        return f"RESOLVE {record.id}"

    monkeypatch.setattr("builtins.input", respond)
    assert main([*cli, "--resolve-conflicts"]) == 0
    out = capsys.readouterr().out
    candidate = next(
        line.split()[3]
        for line in out.splitlines()
        if line.startswith("Unadopted composite candidate:")
    )
    manifest = store.get_manifest(candidate)
    assert b"resolved manually" in store.get_blob(manifest.components["prompts/draft.md"])
    assert len(calls) == 6
