"""T-008 / Test-plan T-07 — DRAFT planner (BACKEND-SPEC Part 1).

Proves: goal in → think + plan events out; failure triggers plan.update;
LLM path parses JSON steps; offline fallback never blocks.
"""

import pytest

from arcen.agents.draft import CONVERSATIONAL_REPLY, DraftPlanner, is_conversational
from arcen.llm.client import Client, LLMResponse
from arcen.stream.events import Answer, Plan, PlanUpdate, Think, to_line


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
    events = planner.open_turn("run the test suite and fix failures")
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
    for event in planner.open_turn("run the test suite and fix failures"):
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
    events = planner.open_turn("run the test suite and fix failures")
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


# -- BUG 2 fix: the conversational short-circuit ------------------------------

def test_is_conversational_matches_the_bug2_contract() -> None:
    # the four assertions the fix requires, verbatim
    assert is_conversational("hello") is True
    assert is_conversational("hi there") is True
    assert is_conversational("build me a calculator") is False
    assert is_conversational("what is 2+2") is False


def test_is_conversational_greetings_with_punctuation() -> None:
    assert is_conversational("hello!") is True
    assert is_conversational("hi there.") is True
    assert is_conversational("yo!") is True
    assert is_conversational("How are you?") is True
    assert is_conversational("WHO ARE YOU") is True
    assert is_conversational("what's up") is True
    # real tasks never match, even task-adjacent phrasing
    assert is_conversational("ok now build the app") is False
    assert is_conversational("fix the failing test") is False
    assert is_conversational("") is False


def test_open_turn_greeting_short_circuits_to_answer() -> None:
    """'hello' → think + answer. NO plan, NO tools — the BUG 2 failure."""
    sink: list = []
    planner = DraftPlanner(llm=None, emit=sink.append)
    events = planner.open_turn("hello")
    kinds = [type(e) for e in events]
    assert kinds == [Think, Answer]
    assert "greeting" in events[0].text
    # the reply is warm prose, 1-2 sentences — not a plan, not a tool call
    reply = events[1].text
    assert reply == CONVERSATIONAL_REPLY
    assert "bash" not in reply.lower()
    assert not any(isinstance(e, Plan) for e in events)
    # both events reached the emit sink
    assert len(sink) == 2


def test_open_turn_greeting_with_llm_uses_provider_reply() -> None:
    class _ChatLLM:
        def complete(self, role, messages):
            return LLMResponse(text="Hey Lewis — good to see you. What are we building?", model="test")

    planner = DraftPlanner(llm=_ChatLLM())
    events = planner.open_turn("hi there")
    assert [type(e) for e in events] == [Think, Answer]
    assert events[1].text.startswith("Hey Lewis")


def test_open_turn_task_still_plans_normally() -> None:
    planner = DraftPlanner(llm=None)
    events = planner.open_turn("what is 2+2")  # a task, not a greeting
    assert [type(e) for e in events] == [Think, Plan]
    assert events[1].steps, "real questions still get a plan"
