"""Manual experience notes in memory; no automatic prompt injection or adoption."""

from __future__ import annotations

import json
import time

import pytest
from test_harness_review import pair_for, setup

from arcen.harness import HarnessError
from arcen.harness.experience import ExperienceLibrary
from arcen.harness.lineage import HarnessLineage
from arcen.harness.review import ReviewLedger
from arcen.memory.store import MemoryStore


def prepare(tmp_path):
    store, baseline, candidate, adopted = setup(tmp_path)
    reviews = ReviewLedger(store, create=True)
    rec = reviews.request_from_comparison(pair_for(baseline, candidate))
    reviews.resolve(rec.id, "approved", "local-reviewer", saw_diff=True)
    memory = MemoryStore(str(tmp_path / "memory.sqlite3"))
    return (
        store,
        baseline,
        candidate,
        adopted,
        reviews,
        rec,
        memory,
        ExperienceLibrary(memory, reviews),
    )


def test_record_persist_render_decay_expiry_and_no_ref_changes(tmp_path):
    store, baseline, candidate, adopted, reviews, rec, memory, lib = prepare(tmp_path)
    result = lib.record("tool-timeout", "Check timeouts before retrying.", rec.id, reviewed=True)
    assert result["op"] == "new"
    initial = lib.active()[0]
    assert initial.text == "Check timeouts before retrying."
    assert (
        initial.review_id == rec.id
        and initial.baseline_id == baseline
        and initial.candidate_id == candidate
    )
    aged = lib.active(as_of=initial.created_at + 14 * 86400)[0]
    assert aged.score < initial.score
    assert lib.active(as_of=initial.expires_at) == ()
    assert "Check timeouts before retrying" in lib.render()
    assert "No active lessons" in lib.render(as_of=initial.expires_at)
    memory.close()
    memory = MemoryStore(str(tmp_path / "memory.sqlite3"))
    assert ExperienceLibrary(memory, reviews).active()[0].fact_id == initial.fact_id
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    memory.close()


def test_explicit_review_and_approved_pair_required_before_any_memory_write(tmp_path):
    _store, baseline, candidate, _, reviews, rec, memory, lib = prepare(tmp_path)
    pending = reviews.request_from_comparison(pair_for(baseline, candidate))
    for review_id, ack in ((rec.id, False), (pending.id, True)):
        with pytest.raises(HarnessError):
            lib.record("planning", "Review the task.", review_id, reviewed=ack)
    static = reviews.request(baseline, candidate)
    with pytest.raises(HarnessError):
        lib.record("planning", "Review the task.", static.id, reviewed=True)
    assert memory.stats()["active_facts"] == 0
    memory.close()


def test_conflicts_are_versioned_and_historical_as_of_recall(tmp_path, monkeypatch):
    _, baseline, candidate, _, reviews, first, memory, lib = prepare(tmp_path)
    clock = [time.time() + 1]
    monkeypatch.setattr("arcen.harness.experience.time.time", lambda: clock[0])
    lib.record("retry", "Retry only after reviewing the error.", first.id, reviewed=True)
    clock[0] += 10
    second = reviews.request_from_comparison(pair_for(baseline, candidate))
    reviews.resolve(second.id, "approved", "reviewer", saw_diff=True)
    update = lib.record("retry", "Do not retry automatically.", second.id, reviewed=True)
    assert update["op"] == "superseded"
    assert len(memory.history("arcen:harness:manual-lessons:v1", "retry")) == 2
    assert lib.active(as_of=clock[0] - 1)[0].text == "Retry only after reviewing the error."
    assert lib.active(as_of=clock[0])[0].text == "Do not retry automatically."
    memory.close()


def test_duplicate_record_does_not_extend_absolute_expiry(tmp_path):
    *_, rec, memory, lib = prepare(tmp_path)
    lib.record("checks", "Review the output.", rec.id, reviewed=True)
    original = lib.active()[0]
    assert lib.record("checks", "Review the output.", rec.id, reviewed=True)["op"] == "consolidated"
    assert lib.active()[0].expires_at == original.expires_at
    memory.close()


@pytest.mark.parametrize(
    "topic,text",
    [
        ("../outside", "hello"),
        ("UPPER", "hello"),
        ("ok", ""),
        ("ok", " has whitespace "),
        ("ok", "line\nbreak"),
        ("ok", "line\u2028break"),
        ("ok", "abc\x1b[31m"),
        ("ok", "secret sk-abcdefghijklmnop"),
        ("ok", "a" * 2049),
        ("ok", "bad\ud800"),
    ],
)
def test_invalid_inputs_rejected_without_write(tmp_path, topic, text):
    *_, rec, memory, lib = prepare(tmp_path)
    with pytest.raises(HarnessError):
        lib.record(topic, text, rec.id, reviewed=True)
    assert memory.stats()["active_facts"] == 0
    memory.close()


def test_markdown_and_html_neutralized_for_display(tmp_path):
    *_, rec, memory, lib = prepare(tmp_path)
    lib.record("format", "<script> ![x](https://example.invalid) `code`", rec.id, reviewed=True)
    output = lib.render()
    assert "<script>" not in output and "&lt;script&gt;" in output
    assert "![x](" not in output and "\\!\\[x\\]\\(" in output
    memory.close()


def test_clock_rollback_refuses_new_write(tmp_path, monkeypatch):
    *_, rec, memory, lib = prepare(tmp_path)
    future = time.time() + 100
    monkeypatch.setattr("arcen.harness.experience.time.time", lambda: future)
    lib.record("format", "First.", rec.id, reviewed=True)
    monkeypatch.setattr("arcen.harness.experience.time.time", lambda: future - 10)
    with pytest.raises(HarnessError, match="backwards"):
        lib.record("format", "Second.", rec.id, reviewed=True)
    assert len(memory.history("arcen:harness:manual-lessons:v1", "format")) == 1
    memory.close()


@pytest.mark.parametrize("change", ["fact", "review", "source", "string-source", "duplicate"])
def test_tampering_fails_closed(tmp_path, change):
    *_, rec, memory, lib = prepare(tmp_path)
    lib.record("audit", "Check the result.", rec.id, reviewed=True)
    if change == "fact":
        memory.conn.execute("UPDATE facts SET fact='not json'")
    elif change == "review":
        data = json.loads(memory.conn.execute("SELECT fact FROM facts").fetchone()[0])
        data["candidate_id"] = "0" * 64
        memory.conn.execute("UPDATE facts SET fact=?", (json.dumps(data),))
    elif change == "source":
        memory.conn.execute("UPDATE facts SET sources='[]'")
    elif change == "string-source":
        memory.conn.execute("UPDATE facts SET sources=?", (json.dumps("review:" + rec.id),))
    else:
        memory.conn.execute(
            "INSERT INTO facts(entity,key,fact,weight,sources,created_at,last_accessed,valid_from) SELECT entity,key,fact,weight,sources,created_at,last_accessed,valid_from FROM facts"
        )
    memory.conn.commit()
    with pytest.raises(HarnessError):
        lib.active()
    memory.close()


def test_invalid_memory_decay_config_and_as_of(tmp_path):
    *_, reviews, _rec, memory, lib = prepare(tmp_path)
    for v in (-1, True, float("nan")):
        with pytest.raises(HarnessError):
            lib.active(as_of=v)
    memory.half_life_days = 0
    with pytest.raises(HarnessError, match="decay"):
        ExperienceLibrary(memory, reviews)
    memory.close()


def test_topic_limit_refuses_new_topic_but_allows_update(tmp_path, monkeypatch):
    *_, rec, memory, lib = prepare(tmp_path)
    monkeypatch.setattr("arcen.harness.experience.MAX_ACTIVE_TOPICS", 1)
    lib.record("one", "First.", rec.id, reviewed=True)
    with pytest.raises(HarnessError, match="limit"):
        lib.record("two", "Second.", rec.id, reviewed=True)
    assert lib.record("one", "Changed.", rec.id, reviewed=True)["op"] == "superseded"
    memory.close()


def test_record_cannot_predate_review_approval(tmp_path, monkeypatch):
    *_, rec, memory, lib = prepare(tmp_path)
    monkeypatch.setattr("arcen.harness.experience.time.time", lambda: rec.created_at - 1)
    with pytest.raises(HarnessError, match="predates"):
        lib.record("later", "Review evidence.", rec.id, reviewed=True)
    assert memory.stats()["active_facts"] == 0
    memory.close()
