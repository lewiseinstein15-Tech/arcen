"""T-008 / T-031 / Test-plan T-07 — DRAFT planner (BACKEND-SPEC Part 1).

Proves: goal in → think + plan events out; failure triggers plan.update;
LLM path parses JSON steps; offline fallback never blocks; the T-031
intent classifier routes DIRECT/RESEARCH/CODE (LLM-first, heuristic
fallback) so "2+2" and "what is your name" never become bash plans.
"""

import pytest

from arcen.agents.draft import (
    CONVERSATIONAL_REPLY,
    CODE,
    DIRECT,
    DIRECT_IDENTITY,
    RESEARCH,
    UNKNOWN,
    DraftPlanner,
    classify_intent,
)
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


# -- T-031: the intent classifier --------------------------------------------

def _is_classify(messages) -> bool:
    """True when the prompt is the T-031 classification call."""
    return "Return ONLY the word" in messages[-1]["content"]


class _ClassifierLLM:
    """Returns the classification word it was told to return; records calls."""

    def __init__(self, word: str):
        self.word = word
        self.calls: list[list[dict]] = []

    def complete(self, role, messages, **kwargs):
        self.calls.append(messages)
        return LLMResponse(text=self.word, model="mock", tokens={"input": 1, "output": 1})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # the ticket matrix, verbatim
        ("hello", DIRECT),
        ("hi", DIRECT),
        ("2+2", DIRECT),
        ("what is 2+2?", DIRECT),
        ("what is your name", DIRECT),
        ("who built you?", DIRECT),
        ("explain closures", DIRECT),
        ("what is the weather", RESEARCH),
        ("search for ai news", RESEARCH),
        ("build me a calculator", CODE),
        ("list files in this dir", CODE),
        ("write a python script", CODE),
    ],
)
def test_classify_intent_llm_matrix(text, expected):
    llm = _ClassifierLLM(expected)
    assert classify_intent(text, llm) == expected
    # the classifier prompt asks for exactly one word, no tools
    sent = llm.calls[0][-1]["content"]
    assert "DIRECT" in sent and "RESEARCH" in sent and "CODE" in sent


def test_classify_intent_parses_noisy_reply():
    """A chatty provider that buries the word still classifies."""
    class _Chatty:
        def complete(self, role, messages, **kwargs):
            return LLMResponse(text="I would say this is DIRECT.", model="m")

    assert classify_intent("hello there friend", _Chatty()) == DIRECT


def test_classify_intent_unparseable_is_unknown():
    llm = _ClassifierLLM("maybe a task?")
    assert classify_intent("refactor the parser", llm) == UNKNOWN


def test_classify_intent_provider_error_falls_back_to_heuristic():
    class _Broken:
        def complete(self, role, messages, **kwargs):
            raise RuntimeError("provider down")

    assert classify_intent("hello", _Broken()) == DIRECT  # heuristic path
    assert classify_intent("build me a calculator", _Broken()) == CODE


def test_classify_intent_no_llm_heuristic():
    """Offline mode still classifies — deterministic, no provider."""
    assert classify_intent("hello") == DIRECT
    assert classify_intent("hi there") == DIRECT
    assert classify_intent("what is your name") == DIRECT
    assert classify_intent("2+2") == DIRECT
    assert classify_intent("what is the weather") == RESEARCH
    assert classify_intent("search for ai news") == RESEARCH
    assert classify_intent("build me a calculator") == CODE
    assert classify_intent("fix the failing test") == CODE
    assert classify_intent("") == DIRECT  # empty ping is never a bash plan


def test_unknown_intent_defaults_to_code_pipeline():
    """UNKNOWN falls through to the normal CODE planning pipeline."""
    class _UnknownThenSteps:
        def __init__(self):
            self.n = 0

        def complete(self, role, messages, **kwargs):
            self.n += 1
            if self.n == 1:  # classification: garbage
                return LLMResponse(text="no idea", model="m")
            return LLMResponse(
                text='[{"title": "act", "tool": "bash"}]', model="m"
            )

    planner = DraftPlanner(llm=_UnknownThenSteps())
    events = planner.open_turn("mysterious request")
    assert [type(e) for e in events] == [Think, Plan]


def test_direct_intent_skips_plan_and_answers():
    """'2+2' → think + answer. NO plan, NO tools — the T-031 failure mode."""
    class _ChatLLM:
        def __init__(self):
            self.identities = []

        def complete(self, role, messages, **kwargs):
            if _is_classify(messages):
                return LLMResponse(text=DIRECT, model="m")
            self.identities.append(kwargs.get("identity"))
            return LLMResponse(text="4", model="m")

    sink: list = []
    llm = _ChatLLM()
    planner = DraftPlanner(llm=llm, emit=sink.append)
    events = planner.open_turn("2+2")
    assert [type(e) for e in events] == [Think, Answer]
    assert events[1].text == "4"
    assert not any(isinstance(e, Plan) for e in events)
    assert len(sink) == 2
    # the DIRECT answer uses the ARCEN identity, verbatim
    assert llm.identities[0] == DIRECT_IDENTITY


def test_direct_identity_is_arcen():
    assert "You are ARCEN" in DIRECT_IDENTITY
    assert "concisely and directly" in DIRECT_IDENTITY


def test_direct_name_question_answers_as_arcen():
    class _ChatLLM:
        def complete(self, role, messages, **kwargs):
            if _is_classify(messages):
                return LLMResponse(text=DIRECT, model="m")
            return LLMResponse(text="I'm ARCEN — your agentic engineer.", model="m")

    events = DraftPlanner(llm=_ChatLLM()).open_turn("what is your name")
    assert [type(e) for e in events] == [Think, Answer]
    assert "ARCEN" in events[1].text


def test_research_intent_plans_web_tools():
    class _ResearchLLM:
        def complete(self, role, messages, **kwargs):
            content = messages[-1]["content"]
            if "RESEARCH  —" in content:  # the classification prompt
                return LLMResponse(text=RESEARCH, model="m")
            return LLMResponse(
                text='[{"title": "search for it", "tool": "search.text"},'
                ' {"title": "read the top result", "tool": "http.get"}]',
                model="m",
            )

    planner = DraftPlanner(llm=_ResearchLLM())
    events = planner.open_turn("search for ai news")
    assert [type(e) for e in events] == [Think, Plan]
    tools = [s["tool"] for s in events[1].steps]
    assert "search.text" in tools and "http.get" in tools


def test_research_offline_heuristic_plan():
    events = DraftPlanner(llm=None).open_turn("what is the weather")
    assert [type(e) for e in events] == [Think, Plan]
    tools = [s["tool"] for s in events[1].steps]
    assert "search.text" in tools and "http.get" in tools


def test_greeting_still_gets_warm_offline_reply():
    """The BUG 2 contract survives T-031: 'hello' → think + answer."""
    sink: list = []
    planner = DraftPlanner(llm=None, emit=sink.append)
    events = planner.open_turn("hello")
    assert [type(e) for e in events] == [Think, Answer]
    assert events[1].text == CONVERSATIONAL_REPLY
    assert not any(isinstance(e, Plan) for e in events)
    assert len(sink) == 2


def test_open_turn_greeting_with_llm_uses_provider_reply() -> None:
    class _ChatLLM:
        def complete(self, role, messages, **kwargs):
            if _is_classify(messages):
                return LLMResponse(text=DIRECT, model="m")
            return LLMResponse(text="Hey Lewis — good to see you. What are we building?", model="test")

    planner = DraftPlanner(llm=_ChatLLM())
    events = planner.open_turn("hi there")
    assert [type(e) for e in events] == [Think, Answer]
    assert events[1].text.startswith("Hey Lewis")


def test_code_task_still_plans_normally() -> None:
    planner = DraftPlanner(llm=None)
    events = planner.open_turn("build me a calculator")
    assert [type(e) for e in events] == [Think, Plan]
    assert events[1].steps, "real tasks still get a plan"


def test_open_turn_task_with_llm_plans_from_provider() -> None:
    """CODE classification → the planner decomposes via the LLM (2 calls)."""

    class _PlanLLM:
        def __init__(self):
            self.n = 0

        def complete(self, role, messages, **kwargs):
            self.n += 1
            if self.n == 1:
                return LLMResponse(text=CODE, model="m")
            return LLMResponse(
                text='[{"title": "read failing test", "tool": "file.read"},'
                ' {"title": "run pytest -q", "tool": "bash"},'
                ' {"title": "apply minimal fix", "tool": "file.edit"}]',
                model="m",
            )

    llm = _PlanLLM()
    events = DraftPlanner(llm=llm).open_turn("fix the failing test")
    assert [type(e) for e in events] == [Think, Plan]
    assert [s["tool"] for s in events[1].steps] == ["file.read", "bash", "file.edit"]
    assert llm.n == 2  # classify + decompose
