"""Local terminal consistency is not evidence authentication or safety."""

from dataclasses import replace

import pytest
from test_harness_review import pair_for, setup

from arcen.harness.policy import AdoptionUnavailable, adopt_candidate
from arcen.harness.probe_execution import _has_consistent_terminal
from arcen.harness.resolver import HarnessError
from arcen.harness.review import ReviewLedger


@pytest.mark.parametrize(
    ("events", "status", "valid"),
    [
        (({"type": "run.done", "status": "ok"},), "ok", True),
        (
            ({"type": "run.start"}, {"type": "answer"}, {"type": "run.done", "status": "failed"}),
            "failed",
            True,
        ),
        (({"type": "run.start"}, {"type": "run.error"}), "error", True),
        (({"type": "future.event"}, {"type": "run.done", "status": "ok"}), "ok", True),
        ((), "ok", False),
        ([{"type": "run.done", "status": "ok"}], "ok", False),
        ((None, {"type": "run.done", "status": "ok"}), "ok", False),
        (({}, {"type": "run.done", "status": "ok"}), "ok", False),
        (({"type": []}, {"type": "run.done", "status": "ok"}), "ok", False),
        (({"type": "run.error"}, {"type": "run.done", "status": "ok"}), "ok", False),
        (
            ({"type": "run.done", "status": "failed"}, {"type": "run.done", "status": "ok"}),
            "ok",
            False,
        ),
        (({"type": "run.done", "status": "ok"}, {"type": "run.error"}), "error", False),
        (({"type": "run.done", "status": "ok"}, {"type": "answer"}), "ok", False),
        (({"type": "run.done", "status": "failed"},), "ok", False),
        (({"type": "run.error"},), "ok", False),
        (({"type": "run.done", "status": "ok"},), "error", False),
        (({"type": "run.done", "status": "ok"},), [], False),
        (({"type": []},), "ok", False),
    ],
)
def test_terminal_sequence_envelope(events, status, valid):
    assert _has_consistent_terminal(events, status) is valid


@pytest.mark.parametrize("side", ["reference", "candidate"])
@pytest.mark.parametrize(
    "events",
    [
        ({"type": "run.error"}, {"type": "run.done", "status": "ok"}),
        ({"type": "run.done", "status": "ok"}, {"type": "run.done", "status": "ok"}),
        ({"type": "run.start"}, None, {"type": "run.done", "status": "ok"}),
    ],
)
def test_paired_review_rejects_contradiction_without_record_or_adoption(tmp_path, side, events):
    store, baseline, candidate, adopted = setup(tmp_path)
    ledger = ReviewLedger(store, create=True)
    pair = pair_for(baseline, candidate)
    pair = replace(pair, **{side: replace(getattr(pair, side), events=events)})
    with pytest.raises(HarnessError, match="inconsistent paired"):
        ledger.request_from_comparison(pair)
    assert ledger.list() == ()
    from arcen.harness.lineage import HarnessLineage

    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    with pytest.raises(AdoptionUnavailable):
        adopt_candidate(store, baseline, candidate)
