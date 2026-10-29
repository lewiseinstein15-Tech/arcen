"""Local review records: metadata only, not an adoption authority."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from test_harness_comparison import provider
from test_probe_execution import Boundary
from test_probe_model import configured
from test_probe_workspace import repository

from arcen.harness import HarnessError, probe_container
from arcen.harness.cli import _init, main
from arcen.harness.comparison import ReviewedComparison, run_reviewed_comparison
from arcen.harness.judge import Judgment
from arcen.harness.probe_execution import ReviewedProbeResult
from arcen.harness.review import ReviewLedger


def pair_for(baseline, candidate):
    # Fabricated to test validation; such caller-supplied data is not proof.
    events = ({"type": "run.done", "status": "ok"},)
    a = ReviewedProbeResult(baseline, baseline, "a" * 40, "b" * 64, "ok", events)
    b = ReviewedProbeResult(baseline, candidate, "a" * 40, "b" * 64, "ok", events)
    return ReviewedComparison(a, b, Judgment("tie", 0.7, "example"))


def setup(tmp_path):
    store, baseline, candidate, _ = configured(tmp_path)
    adopted = _init(str(store.root))
    return store, baseline, candidate, adopted


def test_static_review_persists_and_cannot_approve_or_move_ref(tmp_path):
    store, baseline, candidate, adopted = setup(tmp_path)
    ledger = ReviewLedger(store, create=True)
    rec = ledger.request(baseline, candidate)
    assert ReviewLedger(store).get(rec.id) == rec
    assert ledger.list() == (rec,)
    with pytest.raises(HarnessError, match="paired"):
        ledger.resolve(rec.id, "approved", "alice", saw_diff=True)
    with pytest.raises(HarnessError, match="diff"):
        ledger.resolve(rec.id, "rejected", "alice")
    rejected = ledger.resolve(rec.id, "rejected", "alice", "not suitable", saw_diff=True)
    assert rejected.state == "rejected" and rejected.reviewer == "alice"
    with pytest.raises(HarnessError, match="already decided"):
        ledger.resolve(rec.id, "rejected", "bob", saw_diff=True)
    from arcen.harness.lineage import HarnessLineage

    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_real_comparison_pipeline_to_review_with_mocked_provider_and_docker(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch)
    result = run_reviewed_comparison(
        store,
        baseline,
        candidate,
        "task",
        cfg,
        lambda _: '{"winner":"tie","confidence":0.8,"reason":"no clear difference"}',
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
    )
    ledger = ReviewLedger(store, create=True)
    ledger.request(baseline, candidate)  # static and paired records may coexist
    rec = ledger.request_from_comparison(result)
    assert rec.commit == commit and rec.judge_winner == "tie"
    with pytest.raises(HarnessError, match="already exists"):
        ledger.request_from_comparison(result)
    approved = ledger.resolve(rec.id, "approved", " alice ", saw_diff=True)
    assert approved.reviewer == "alice" and approved.state == "approved"
    assert ReviewLedger(store).get(rec.id) == approved


@pytest.mark.parametrize(
    "kind",
    [
        "incomplete",
        "wrong_type",
        "failed",
        "events",
        "baseline",
        "commit",
        "snapshot",
        "winner",
        "confidence",
    ],
)
def test_bad_or_incomplete_paired_evidence_rejected(tmp_path, kind):
    store, baseline, candidate, _ = setup(tmp_path)
    pair = pair_for(baseline, candidate)
    _a, b, judgment = pair.reference, pair.candidate, pair.judgment
    if kind == "incomplete":
        pair = replace(pair, candidate=None)
    if kind == "wrong_type":
        pair = replace(pair, reference=object())
    if kind == "failed":
        pair = replace(pair, candidate=replace(b, status="failed"))
    if kind == "events":
        pair = replace(pair, candidate=replace(b, events=()))
    if kind == "baseline":
        pair = replace(pair, candidate=replace(b, baseline_id=candidate))
    if kind == "commit":
        pair = replace(pair, candidate=replace(b, commit="c" * 40))
    if kind == "snapshot":
        pair = replace(pair, candidate=replace(b, workspace_sha256="c" * 64))
    if kind == "winner":
        pair = replace(pair, judgment=replace(judgment, winner="invalid"))
    if kind == "confidence":
        pair = replace(pair, judgment=replace(judgment, confidence=float("nan")))
    ledger = ReviewLedger(store, create=True)
    with pytest.raises(HarnessError):
        ledger.request_from_comparison(pair)
    assert ledger.list() == ()


def test_concurrent_requests_and_decisions_have_single_winner(tmp_path):
    store, baseline, candidate, _ = setup(tmp_path)
    ledger = ReviewLedger(store, create=True)
    pair = pair_for(baseline, candidate)

    def request(_):
        try:
            return ledger.request_from_comparison(pair)
        except HarnessError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(request, range(8)))
    records = [x for x in results if x is not None]
    assert len(records) == 1

    def decide(i):
        try:
            return ledger.resolve(
                records[0].id, "approved" if i % 2 else "rejected", str(i), saw_diff=True
            )
        except HarnessError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(decide, range(8)))
    assert len([x for x in decisions if x is not None]) == 1
    assert ledger.get(records[0].id).state in {"approved", "rejected"}


def test_wall_clock_backwards_does_not_commit_invalid_record(tmp_path, monkeypatch):
    store, baseline, candidate, _ = setup(tmp_path)
    ledger = ReviewLedger(store, create=True)
    rec = ledger.request_from_comparison(pair_for(baseline, candidate))
    monkeypatch.setattr("arcen.harness.review.time.time", lambda: 0)
    decided = ledger.resolve(rec.id, "approved", "alice", saw_diff=True)
    assert decided.decided_at == rec.created_at
    assert ledger.get(rec.id) == decided


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE reviews SET reviewer='fake'",
        "UPDATE reviews SET state='approved', reviewer='fake', note='', decided_at=created_at",
        "UPDATE reviews SET candidate='bad'",
        "UPDATE reviews SET created_at=-1",
    ],
)
def test_tampered_records_fail_closed(tmp_path, sql):
    store, baseline, candidate, _ = setup(tmp_path)
    ledger = ReviewLedger(store, create=True)
    rec = ledger.request(baseline, candidate)
    with sqlite3.connect(ledger.path) as db:
        db.execute(sql)
    with pytest.raises(HarnessError):
        ledger.get(rec.id)
    with pytest.raises(HarnessError):
        ledger.resolve(rec.id, "rejected", "alice", saw_diff=True)


def test_schema_tampering_and_symlink_rejected(tmp_path):
    store, _baseline, _candidate, _ = setup(tmp_path)
    ledger = ReviewLedger(store, create=True)
    with sqlite3.connect(ledger.path) as db:
        db.execute("DROP INDEX one_pending_review")
    with pytest.raises(HarnessError, match="schema"):
        ReviewLedger(store)
    with pytest.raises(HarnessError, match="schema"):
        ReviewLedger(store, create=True)
    ledger.path.unlink()
    victim = tmp_path / "victim"
    victim.write_text("unchanged")
    ledger.path.symlink_to(victim)
    for create in (True, False):
        with pytest.raises(HarnessError):
            ReviewLedger(store, create=create)
    assert victim.read_text() == "unchanged"


def test_corrupt_object_and_invalid_inputs_fail_closed(tmp_path):
    store, baseline, candidate, _ = setup(tmp_path)
    ledger = ReviewLedger(store, create=True)
    rec = ledger.request_from_comparison(pair_for(baseline, candidate))
    for args in [("bogus", "alice", True), ("approved", "", True), ("approved", "alice", 1)]:
        with pytest.raises(HarnessError):
            ledger.resolve(rec.id, args[0], args[1], saw_diff=args[2])
    with pytest.raises(HarnessError):
        ledger.get("../../x")
    with pytest.raises(HarnessError):
        ledger.list(True)
    manifest = store.get_manifest(candidate)
    (store.objects / manifest.components["prompts/draft.md"]).write_bytes(b"tampered")
    with pytest.raises(HarnessError):
        ledger.resolve(rec.id, "approved", "alice", saw_diff=True)


def test_cli_show_sanitizes_and_noninteractive_decision_refuses(tmp_path, capsys):
    store, baseline, candidate, _adopted = setup(tmp_path)
    ledger = ReviewLedger(store, create=True)
    rec = ledger.request_from_comparison(pair_for(baseline, candidate))
    root = str(store.root)
    assert main(["--store", root, "review", "show", rec.id]) == 0
    output = capsys.readouterr().out
    assert "Sanitized component diff" in output and "CANDIDATE PLANNER" in output
    assert "not the currently adopted baseline" in output and "not authenticated" in output
    assert main(["--store", root, "review", "approve", rec.id, "--reviewer", "alice"]) != 0
    assert "interactive terminal" in capsys.readouterr().err
    assert ledger.get(rec.id).state == "pending"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "arcen.harness.cli",
            "--store",
            root,
            "review",
            "reject",
            rec.id,
            "--reviewer",
            "bob",
        ],
        input=f"REJECT {rec.id}\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0 and ledger.get(rec.id).state == "pending"


def test_expected_record_change_blocks_decision(tmp_path):
    store, baseline, candidate, _ = setup(tmp_path)
    ledger = ReviewLedger(store, create=True)
    rec = ledger.request_from_comparison(pair_for(baseline, candidate))
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE reviews SET workspace=? WHERE id=?", ("c" * 64, rec.id))
    with pytest.raises(HarnessError, match="changed since"):
        ledger.resolve(rec.id, "approved", "alice", saw_diff=True, expected=rec)
    assert ledger.get(rec.id).state == "pending"


def test_interactive_pty_shows_diff_and_requires_exact_confirmation(tmp_path):
    import errno
    import os
    import pty
    import select
    import time

    store, baseline, candidate, adopted = setup(tmp_path)
    ledger = ReviewLedger(store, create=True)
    rec = ledger.request_from_comparison(pair_for(baseline, candidate))

    def run(answer):
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "arcen.harness.cli",
                "--store",
                str(store.root),
                "review",
                "approve",
                rec.id,
                "--reviewer",
                "alice",
            ],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        os.write(master, (answer + "\n").encode())
        output = bytearray()
        deadline = time.monotonic() + 20
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.5)
                if not ready:
                    if proc.poll() is not None:
                        break
                    continue
                try:
                    data = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not data:
                    break
                output.extend(data)
            code = proc.wait(timeout=5)
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        return code, output.decode(errors="replace")

    code, text = run("yes")
    assert code != 0 and "Sanitized component diff" in text and "cancelled" in text
    assert ledger.get(rec.id).state == "pending"
    code, text = run(f"APPROVE {rec.id}")
    assert code == 0 and "Sanitized component diff" in text and "not adopted" in text
    assert ledger.get(rec.id).state == "approved"
    from arcen.harness.lineage import HarnessLineage

    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_terminal_control_in_note_is_neutralized(tmp_path, capsys):
    store, baseline, candidate, _ = setup(tmp_path)
    ledger = ReviewLedger(store, create=True)
    rec = ledger.request(baseline, candidate)
    ledger.resolve(rec.id, "rejected", "alice", "bad\x1b[31m\u202e", saw_diff=True)
    assert main(["--store", str(store.root), "review", "show", rec.id]) == 0
    output = capsys.readouterr().out
    assert "\x1b" not in output and "\u202e" not in output
