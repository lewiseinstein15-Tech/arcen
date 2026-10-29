"""Blinded metadata, randomized position mapping and strict judge responses."""

from __future__ import annotations

import json

import pytest

from arcen.harness import HarnessError
from arcen.harness.judge import Judgment, Trajectory, compare

REF = "reference-identifier-123"
CAND = "candidate-identifier-456"
SECRET = "private-secret-value"


def trajectories():
    ref = Trajectory(
        REF,
        (
            {"type": "run.start", "harness_ref": REF, "goal": "secret"},
            {"type": "answer", "text": "result from " + REF + " " + SECRET},
            {
                "type": "command.done",
                "ok": True,
                "result": {"exit": 0, "stdout": "private raw output"},
            },
            {"type": "step.pass", "checks": ["check passed"]},
            {"type": "run.done", "status": "ok"},
        ),
    )
    candidate = Trajectory(
        CAND,
        (
            {"type": "think", "text": "editor rationale should never be sent"},
            {"type": "answer", "text": "improved result " + CAND},
            {"type": "run.done", "status": "ok"},
        ),
    )
    return ref, candidate


@pytest.mark.parametrize(
    ("order", "winner", "expected"),
    [
        (0, "A", "reference"),
        (0, "B", "candidate"),
        (1, "A", "candidate"),
        (1, "B", "reference"),
        (1, "tie", "tie"),
    ],
)
def test_blind_order_and_winner_mapping(order, winner, expected):
    ref, candidate = trajectories()
    assert REF not in repr(ref) and SECRET not in repr(ref)

    def judge(request):
        raw = json.dumps(request)
        for forbidden in (
            REF,
            CAND,
            SECRET,
            "harness_ref",
            "editor rationale",
            "private raw output",
        ):
            assert forbidden not in raw
        assert "[redacted]" in raw
        assert set(request) == {"task", "trajectory_a", "trajectory_b", "instructions"}
        return json.dumps({"winner": winner, "confidence": 0.8, "reason": "reason " + CAND})

    result = compare(
        "Assess " + REF, ref, candidate, judge, sensitive_values=(SECRET,), shuffle=lambda n: order
    )
    assert result == Judgment(expected, 0.8, "reason [redacted]")


@pytest.mark.parametrize(
    "response",
    [
        "{}",
        '{"winner":"A","winner":"B","confidence":0.5,"reason":"ok"}',
        '{"winner":"candidate","confidence":0.5,"reason":"ok"}',
        '{"winner":"A","confidence":true,"reason":"ok"}',
        '{"winner":"A","confidence":NaN,"reason":"ok"}',
        '{"winner":"A","confidence":1.1,"reason":"ok"}',
        '{"winner":"A","confidence":0.5,"reason":""}',
        '{"winner":"A","confidence":0.5,"reason":"ok","extra":1}',
    ],
)
def test_malformed_judge_results_are_rejected(response):
    ref, candidate = trajectories()
    with pytest.raises(HarnessError):
        compare("task", ref, candidate, lambda request: response, shuffle=lambda n: 0)


def test_unusable_or_oversized_inputs_never_reach_callback():
    ref, candidate = trajectories()

    def called(_):
        pytest.fail("judge must not run")

    for bad in (
        Trajectory("short", ({"type": "answer", "text": "x"},)),
        Trajectory(REF, ({"type": "think", "text": "x"},)),
        Trajectory(REF, ({"type": "answer", "text": "x" * 4097},)),
    ):
        with pytest.raises(HarnessError):
            compare("task", bad, candidate, called, shuffle=lambda n: 0)
    with pytest.raises(HarnessError):
        compare("task", ref, ref, called)
    with pytest.raises(HarnessError):
        compare("task", ref, candidate, called, shuffle=lambda n: 2)


def test_known_secret_patterns_are_redacted():
    ref = Trajectory(REF, ({"type": "answer", "text": "sk-abcdefghijklmnop"},))
    candidate = Trajectory(CAND, ({"type": "answer", "text": "fine"},))

    def judge(request):
        assert "sk-abcdefghijklmnop" not in json.dumps(request)
        return '{"winner":"tie","confidence":0.3,"reason":"same"}'

    assert compare("task", ref, candidate, judge, shuffle=lambda n: 0).winner == "tie"
