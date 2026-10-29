"""Deterministic capture of actual provider payloads, used by H-02 golden tests."""

from types import SimpleNamespace

from arcen.agents.draft import DraftPlanner
from arcen.llm.client import Client

PLAN = '[{"title":"check", "tool":"bash", "args":{"cmd":"true"}}]'
MODELS = {"planner": "mock-planner", "executor": "mock-executor", "verifier": "mock-verifier"}


def capture_prompt_payloads():
    recorded = []

    def scenario(name, replies, run):
        pending = list(replies)

        def completion(**kwargs):
            recorded.append(
                {
                    "scenario": name,
                    "model": kwargs["model"],
                    "temperature": kwargs["temperature"],
                    "messages": kwargs["messages"],
                }
            )
            text = pending.pop(0)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

        client = Client(models=MODELS, completion_fn=completion, max_retries=0)
        run(client)
        assert not pending, f"unused replies in {name}"

    scenario("code", ["CODE", PLAN], lambda c: DraftPlanner(llm=c).open_turn("fix a test"))
    scenario(
        "research",
        ["RESEARCH", PLAN],
        lambda c: DraftPlanner(llm=c).open_turn("research the result"),
    )
    scenario("direct", ["DIRECT", "hello"], lambda c: DraftPlanner(llm=c).open_turn("hello"))
    scenario(
        "strict_retry",
        ["CODE", "not json", PLAN],
        lambda c: DraftPlanner(llm=c).open_turn("repair the script"),
    )
    scenario(
        "replan",
        [PLAN],
        lambda c: DraftPlanner(llm=c).replan(
            "repair the script", "failed", {"id": 1, "tool": "bash", "args": {"cmd": "false"}}
        ),
    )
    scenario(
        "executor", ["ok"], lambda c: c.complete("executor", [{"role": "user", "content": "step"}])
    )
    scenario(
        "verifier", ["ok"], lambda c: c.complete("verifier", [{"role": "user", "content": "check"}])
    )
    return recorded
