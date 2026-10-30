"""Campaign progress is informational, privacy-bounded and non-authoritative."""

from __future__ import annotations

import json

import pytest
from test_harness_comparison import provider
from test_manual_campaign import budget, run, setup
from test_probe_execution import Boundary
from test_probe_model import SECRET

from arcen.harness import HarnessError, probe_container
from arcen.harness.progress import Progress, _validate


def test_manual_campaign_emits_ordered_metadata_only_events(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch)
    events = []
    result = run(args, on_progress=events.append)
    assert result.stop_reason is None and len(result.completed) == 2
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert [e["type"] for e in events] == [
        "harness.campaign.start",
        "harness.policy",
        "harness.policy",
        "harness.probe.start",
        "harness.probe.done",
        "harness.probe.start",
        "harness.probe.done",
        "harness.judge",
        "harness.review",
        "harness.probe.start",
        "harness.probe.done",
        "harness.judge",
        "harness.review",
        "harness.campaign.done",
    ]
    assert events[0]["candidate_count"] == 2
    assert events[-1] == {
        "seq": len(events),
        "type": "harness.campaign.done",
        "status": "completed",
        "reason": None,
        "completed": 2,
    }
    assert all(e["state"] == "pending" for e in events if e["type"] == "harness.review")
    payload = json.dumps(events)
    for forbidden in (SECRET, "inspect project", "CANDIDATE PLANNER", str(args[4])):
        assert forbidden not in payload
    for event in events:
        _validate(event)


def test_observer_errors_cannot_cancel_or_retry_probes(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    observed = []

    def bad_sink(event):
        observed.append(event["seq"])
        event["candidate_id"] = "tampered locally"
        raise RuntimeError(SECRET)

    result = run(args, on_progress=bad_sink)
    assert result.stop_reason is None and len(result.completed) == 2
    assert len(calls) == 6 and observed == list(range(1, len(observed) + 1))
    assert all(bound.closed for bound in Boundary.instances[-3:])


def test_stopped_campaign_reports_status_without_claiming_approval(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch)
    events = []
    result = run(args, budget=budget(max_trials=2), on_progress=events.append)
    assert result.stop_reason == "budget_closed" and len(result.completed) == 1
    assert events[-1]["reason"] == "budget_closed" and events[-1]["completed"] == 1
    assert events[-1]["status"] == "stopped"
    assert sum(e["type"] == "harness.review" for e in events) == 1


def test_invalid_sink_rejected_before_git_or_provider(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(
        "arcen.harness.manual_campaign.snapshot_git_commit", lambda *_: pytest.fail("git called")
    )
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("Docker called")
    )
    with pytest.raises(HarnessError, match="progress sink"):
        run(args, on_progress=42)
    assert args[-1].list() == ()


def test_event_schema_rejects_private_extra_fields():
    event = {
        "seq": 1,
        "type": "harness.probe.start",
        "candidate_id": "a" * 64,
        "role": "candidate",
        "task": "private",
    }
    with pytest.raises(HarnessError):
        _validate(event)
    out = []
    p = Progress(out.append)
    p.emit("harness.probe.start", candidate_id="a" * 64, role="candidate", task="private")
    assert out == []  # even an internal mistake is not sent to observers


def test_legacy_wire_registry_remains_frozen():
    from arcen.stream.events import EVENT_TYPES, UnknownEventError, from_dict

    assert len(EVENT_TYPES) == 17 and "harness.campaign.start" not in EVENT_TYPES
    with pytest.raises(UnknownEventError):
        from_dict({"type": "harness.campaign.start", "seq": 1, "candidate_count": 1})
