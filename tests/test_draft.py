"""T-008 / T-031 / T-037 / Test-plan T-07 — DRAFT planner (BACKEND-SPEC Part 1).

Proves: goal in → think + plan events out (from the provider, with real
args); failure triggers plan.update; the T-031 intent classifier routes
DIRECT/RESEARCH/CODE so "2+2" and "what is your name" never become bash
plans; and the T-037 honest-refusal contract — a real task without a
provider refuses cleanly (no fake plan, no goal-as-bash), a malformed
plan retries once with a stricter prompt then refuses.
"""

import pytest

from arcen.agents.draft import (
    CONVERSATIONAL_REPLY,
    CODE,
    DIRECT,
    DIRECT_IDENTITY,
    DIRECT_NO_PROVIDER_ANSWER,
    NO_PLAN_ANSWER,
    NO_PROVIDER_ANSWER,
    NO_PROVIDER_THINK,
    RESEARCH,
    STRICT_PLAN_HINT,
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
    planner = DraftPlanner(llm=_FakeLLM(), emit=sink.append)
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
    planner = DraftPlanner(llm=_FakeLLM())
    events = planner.open_turn("run the test suite and fix failures")
    ids = [s["id"] for s in events[1].steps]
    assert ids == list(range(1, len(ids) + 1))


def test_failure_triggers_plan_update() -> None:
    planner = DraftPlanner(llm=_FakeLLM())
    events = planner.replan(
        goal="fix the failing test",
        reason="test bug found; fix the assertion",
        failed_step={"id": 2, "title": "run pytest -q", "tool": "bash"},
    )
    kinds = [type(e) for e in events]
    assert kinds == [Think, PlanUpdate]
    assert events[1].reason == "test bug found; fix the assertion"
    assert events[1].steps, "the corrected plan has steps"


def test_events_serialize_on_frozen_schema() -> None:
    planner = DraftPlanner(llm=None)
    for event in planner.open_turn("hello"):
        line = to_line(event)
        assert '"type":"think"' in line or '"type":"answer"' in line


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


def test_provider_failure_after_strict_retry_refuses() -> None:
    """T-037: provider down/malformed → ONE strict retry → honest refusal.

    Never a heuristic plan, never a bash step built from the goal text.
    """

    class _BrokenLLM:
        def __init__(self):
            self.calls = 0

        def complete(self, role, messages, **kwargs):
            self.calls += 1
            raise RuntimeError("provider down")

    broken = _BrokenLLM()
    planner = DraftPlanner(llm=broken)
    events = planner.open_turn("build me a calculator")
    assert [type(e) for e in events] == [Think, Answer]
    assert not any(isinstance(e, Plan) for e in events)
    assert "couldn't plan" in events[1].text
    # 1 classify (→ heuristic fallback) + 2 decompose attempts (retry once)
    assert broken.calls == 3


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


def test_research_offline_refuses_cleanly():
    """T-037: a RESEARCH task with no provider refuses — no fake web plan."""
    events = DraftPlanner(llm=None).open_turn("what is the weather")
    assert [type(e) for e in events] == [Think, Answer]
    assert not any(isinstance(e, Plan) for e in events)
    assert NO_PROVIDER_ANSWER in events[1].text


def test_code_task_without_provider_refuses_cleanly():
    """THE T-037 contract: "build me a calculator" with no provider →
    a clean configure-a-provider message. No plan, no bash attempts,
    no "command not found" — the exact laptop failure mode, dead."""
    sink: list = []
    planner = DraftPlanner(llm=None, emit=sink.append)
    events = planner.open_turn("build me a calculator")
    assert [type(e) for e in events] == [Think, Answer]
    assert events[0].text == NO_PROVIDER_THINK
    assert events[1].text == NO_PROVIDER_ANSWER
    assert "Open Settings → Provider" in events[1].text
    assert not any(isinstance(e, Plan) for e in events)
    assert not any(isinstance(e, PlanUpdate) for e in events)
    assert len(sink) == 2  # both events reached the stream


def test_code_task_without_provider_never_runs_bash():
    """The refusal turn contains no command event — nothing executes."""
    from arcen.stream.events import Command

    sink: list = []
    planner = DraftPlanner(llm=None, emit=sink.append)
    planner.open_turn("list files in this dir")
    assert not any(isinstance(e, Command) for e in sink)


def test_direct_without_provider_refuses_honestly():
    """A non-greeting DIRECT question without a provider can't be answered
    from a model — the old text claimed coding still worked offline; the
    new one points at Settings."""
    events = DraftPlanner(llm=None).open_turn("what is 2+2")
    assert [type(e) for e in events] == [Think, Answer]
    assert events[1].text == DIRECT_NO_PROVIDER_ANSWER


def test_malformed_plan_retries_stricter_then_refuses():
    """Provider up but the plan is garbage twice → refusal, and the retry
    prompt carries the strict hint."""

    class _GarbageLLM:
        def __init__(self):
            self.decompose_prompts: list[str] = []

        def complete(self, role, messages, **kwargs):
            content = messages[-1]["content"]
            if "Return ONLY the word" in content:
                return LLMResponse(text=CODE, model="m")
            self.decompose_prompts.append(content)
            return LLMResponse(text="I think a calculator needs buttons.", model="m")

    llm = _GarbageLLM()
    events = DraftPlanner(llm=llm).open_turn("build me a calculator")
    assert [type(e) for e in events] == [Think, Answer]
    assert not any(isinstance(e, Plan) for e in events)
    assert NO_PLAN_ANSWER in events[1].text
    assert len(llm.decompose_prompts) == 2  # exactly one strict retry
    assert STRICT_PLAN_HINT in llm.decompose_prompts[1]
    assert STRICT_PLAN_HINT not in llm.decompose_prompts[0]


def test_malformed_plan_recovers_on_strict_retry():
    """First plan garbage, strict retry returns a real plan → the turn
    plans normally (the retry is a second chance, not a dead end)."""

    class _FlakyLLM:
        def __init__(self):
            self.n = 0

        def complete(self, role, messages, **kwargs):
            content = messages[-1]["content"]
            if "Return ONLY the word" in content:
                return LLMResponse(text=CODE, model="m")
            self.n += 1
            if self.n == 1:
                return LLMResponse(text="oops", model="m")
            return LLMResponse(
                text='[{"title": "write calc.py", "tool": "file.write", '
                '"args": {"path": "calc.py", "content": "print(2+2)"}}]',
                model="m",
            )

    events = DraftPlanner(llm=_FlakyLLM()).open_turn("build me a calculator")
    assert [type(e) for e in events] == [Think, Plan]
    assert events[1].steps[0]["tool"] == "file.write"


def test_llm_plan_parses_real_tool_args():
    """T-037: the plan carries the LLM's tool args — the executor runs
    the planned command, never the raw goal text."""

    class _ArgsLLM:
        def complete(self, role, messages, **kwargs):
            content = messages[-1]["content"]
            if "Return ONLY the word" in content:
                return LLMResponse(text=CODE, model="m")
            return LLMResponse(
                text='[{"title": "run the suite", "tool": "bash", '
                '"args": {"cmd": "pytest -q"}}]',
                model="m",
            )

    events = DraftPlanner(llm=_ArgsLLM()).open_turn("run the test suite")
    step = events[1].steps[0]
    assert step["args"] == {"cmd": "pytest -q"}
    assert step["args"]["cmd"] != "run the test suite"


def test_empty_llm_plan_counts_as_malformed():
    """An empty JSON array is not a plan — same retry-then-refuse path."""

    class _EmptyPlanLLM:
        def complete(self, role, messages, **kwargs):
            content = messages[-1]["content"]
            if "Return ONLY the word" in content:
                return LLMResponse(text=CODE, model="m")
            return LLMResponse(text="[]", model="m")

    events = DraftPlanner(llm=_EmptyPlanLLM()).open_turn("build me a calculator")
    assert [type(e) for e in events] == [Think, Answer]
    assert "couldn't plan" in events[1].text


def test_replan_without_usable_plan_refuses():
    """Provider dies mid-turn → replan refuses honestly, no fake steps."""

    class _DiedMidTurn:
        def complete(self, role, messages, **kwargs):
            raise RuntimeError("provider died")

    events = DraftPlanner(llm=_DiedMidTurn()).replan(
        goal="fix the failing test",
        reason="step 2 failed",
        failed_step={"id": 2, "title": "run pytest -q", "tool": "bash"},
    )
    assert [type(e) for e in events] == [Think, Answer]
    assert "couldn't plan" in events[1].text
    assert not any(isinstance(e, PlanUpdate) for e in events)


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


def test_code_task_with_provider_plans_normally():
    """The provider path is untouched: a real task gets a real plan."""
    planner = DraftPlanner(llm=_FakeLLM())
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
