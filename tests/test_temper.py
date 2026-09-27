"""T-010 / Test-plan T-09 — TEMPER verifier (BACKEND-SPEC Part 1).

Proves: planted broken code → step.fail; clean code → step.pass;
binary verdict with reasons; reruns before declaring failure.
"""

import pytest

from arcen.agents.temper import TemperVerifier
from arcen.stream.events import StepFail, StepPass, VerifyStart, to_line
from arcen.tools.registry import load_builtin


@pytest.fixture()
def registry() -> object:
    return load_builtin()


@pytest.fixture()
def temper(registry) -> TemperVerifier:
    return TemperVerifier(registry)


def test_clean_code_passes(temper, tmp_path) -> None:
    events = temper.verify(step=1, target=str(tmp_path), checks=["true"])
    assert [type(e) for e in events] == [VerifyStart, StepPass]
    assert events[0].agent == "TEMPER" and events[0].target == str(tmp_path)
    assert events[1].step == 1
    assert events[1].checks == ["true"]


def test_planted_broken_code_fails(temper, tmp_path) -> None:
    (tmp_path / "test_broken.py").write_text("def test_broken():\n    assert 1 == 2\n")
    events = temper.verify(
        step=2,
        target=str(tmp_path),
        checks=[f"python3 -m pytest -q {tmp_path / 'test_broken.py'}"],
    )
    assert [type(e) for e in events] == [VerifyStart, StepFail]
    fail = events[1]
    assert fail.step == 2
    assert "assert" in fail.reason.lower()
    assert fail.retry == 1  # reruns=1 → one retry observed


def test_real_pytest_check(tmp_path) -> None:
    """Full loop: write a real test file, verify pass then fail."""
    registry = load_builtin()
    temper = TemperVerifier(registry, reruns=0)
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert 2 + 2 == 4\n")
    events = temper.verify(step=1, target=str(tmp_path), checks=[f"python3 -m pytest -q {tmp_path / 'test_ok.py'}"])
    assert isinstance(events[-1], StepPass)

    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert calc_wrong(1) == 1\n")
    events = temper.verify(step=2, target=str(tmp_path), checks=[f"python3 -m pytest -q {tmp_path / 'test_bad.py'}"])
    assert isinstance(events[-1], StepFail)


def test_events_serialize_frozen_schema(temper) -> None:
    for event in temper.verify(step=3, target=".", checks=["true"]):
        line = to_line(event)
        assert '"type":"' in line


def test_rerun_flaky_check_then_pass() -> None:
    class FlakyRegistry:
        def __init__(self) -> None:
            self.calls = 0

        def dispatch(self, name, args):
            self.calls += 1
            ok = self.calls >= 2  # fails once, passes after
            return {"ok": ok, "result": None if ok else {"stderr": "flaky", "stdout": ""}, "error": None if ok else "exit 1"}

    temper = TemperVerifier(FlakyRegistry(), reruns=1)  # type: ignore[arg-type]
    events = temper.verify(step=1, target=".", checks=["flaky-check"])
    assert isinstance(events[-1], StepPass)  # flaky recovers within reruns


def test_never_passes_partial() -> None:
    class AlwaysFails:
        def dispatch(self, name, args):
            return {"ok": False, "result": {"stderr": "boom", "stdout": ""}, "error": "exit 1"}

    temper = TemperVerifier(AlwaysFails(), reruns=1)  # type: ignore[arg-type]
    events = temper.verify(step=7, target=".", checks=["a", "b"])
    fail = events[-1]
    assert isinstance(fail, StepFail)
    assert fail.retry == 1
    assert "boom" in fail.reason


def test_emit_hook_receives_all_events(registry) -> None:
    sink: list = []
    temper = TemperVerifier(registry, emit=sink.append)
    temper.verify(step=1, target=".", checks=["true"])
    assert len(sink) == 2
    assert sink[0].TYPE == "verify.start"
    assert sink[1].TYPE == "step.pass"
