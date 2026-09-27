"""T-008 / Test-plan T-07 — DRAFT planner (BACKEND-SPEC Part 1).

Proves: goal in → think + plan events out; failure triggers plan.update;
LLM path parses JSON steps; offline fallback never blocks.
"""

import pytest

from arcen.agents.draft import DraftPlanner
from arcen.llm.client import Client, LLMResponse
from arcen.stream.events import Plan, PlanUpdate, Think, to_line


def _collect():
    sink: list = []
    return sink


def test_goal_in_think_and_plan_out() -> None:
    sink = _collect()
    planner = DraftPlanner(llm=None, emit=sink.append)
    events = planner.open_turn("fix the failing test in tests/")
    types = [type(e) for e in events]
    assert types == [Think, Plan]
    assert events[0].agent == "DRAFT"
    assert "fix the failing test" in events[0].text
    assert events[1].agent == "DRAFT"
    assert events[1].steps, "plan must have steps"
    for step in events[1].steps:
        assert set(step) >= {"id", "title", "tool"}


def test_plan_steps_are_sequential_ids() -> None:
    planner = DraftPlanner(llm=None)
    events = planner.open_turn("hello")
    ids = [s["id"] for s in events[1].steps]
    assert ids == list(range(1, len(ids) + 1))


def test_failure_triggers_plan_update() -> None:
    planner = DraftPlanner(llm=None)
    events = planner.replan(
        goal="fix the failing test",
        reason="test bug found; fix the assertion",
        failed_step={"id": 2, "title": "run pytest -q", "tool": "bash"},
    )
    kinds = [type(e) for e in events]
    assert kinds == [Think, PlanUpdate]
    assert events[1].reason == "test bug found; fix the assertion"
    assert any("diagnose" in s["title"] for s in events[1].steps)


def test_events_serialize_on_frozen_schema() -> None:
    planner = DraftPlanner(llm=None)
    for event in planner.open_turn("hello"):
        line = to_line(event)
        assert '"type":"think"' in line or '"type":"plan"' in line


class _FakeLLM:
    """Minimal stand-in matching arcen.llm.Client's surface."""

    def complete(self, role, messages, **kwargs):
        assert role == "planner"
        self.role_used = role
        return LLMResponse(
            text='[{"title": "read failing test", "tool": "file.read"},'
            ' {"title": "run pytest -q", "tool": "bash"},'
            ' {"title": "apply minimal fix", "tool": "file.edit"}]',
            model="mock-model",
            tokens={"input": 10, "output": 5},
            cost_usd=0.0,
        )


def test_llm_mode_parses_json_steps() -> None:
    fake = _FakeLLM()
    planner = DraftPlanner(llm=fake)
    events = planner.open_turn("fix the failing test")
    plan = events[1]
    assert isinstance(plan, Plan)
    assert [s["tool"] for s in plan.steps] == ["file.read", "bash", "file.edit"]


def test_llm_mode_unknown_tool_nulled() -> None:
    class _BadToolLLM(_FakeLLM):
        def complete(self, role, messages, **kwargs):
            return LLMResponse(
                text='[{"title": "teleport", "tool": "warp.drive"}]',
                model="mock",
                tokens={"input": 1, "output": 1},
                cost_usd=0.0,
            )

    planner = DraftPlanner(llm=_BadToolLLM())
    events = planner.open_turn("do magic")
    assert events[1].steps[0]["tool"] is None


def test_llm_failure_degrades_to_heuristic() -> None:
    class _BrokenLLM:
        def complete(self, role, messages, **kwargs):
            raise RuntimeError("provider down")

    planner = DraftPlanner(llm=_BrokenLLM())
    events = planner.open_turn("hello")
    # still a valid turn: think + plan, offline shape
    assert [type(e) for e in events] == [Think, Plan]
    assert events[1].steps


def test_max_steps_cap() -> None:
    class _LongLLM(_FakeLLM):
        def complete(self, role, messages, **kwargs):
            steps = ",".join(f'{{"title": "s{i}", "tool": "bash"}}' for i in range(50))
            return LLMResponse(text=f"[{steps}]", model="m", tokens={"input": 1, "output": 1}, cost_usd=0.0)

    planner = DraftPlanner(llm=_LongLLM(), max_steps=5)
    events = planner.open_turn("big goal")
    assert len(events[1].steps) == 5


def test_real_client_mocked_provider_end_to_end() -> None:
    """The real Client with a mocked completion_fn drives DRAFT."""
    calls: list = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        from types import SimpleNamespace

        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='[{"title": "act", "tool": "bash"}]'))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    client = Client(completion_fn=fake_completion)
    planner = DraftPlanner(llm=client)
    events = planner.open_turn("wire it")
    assert events[1].steps[0]["title"] == "act"
    # identity block was sent to the provider
    assert "DRAFT" in calls[0]["messages"][0]["content"]
