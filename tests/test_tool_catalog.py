"""The planner's tool catalog is derived from the registry, not hand-written.

Two failure modes this guards, both of which shipped before:

* the prompt listed a fixed set of tool names, so a tool added later (or one
  contributed by an MCP server or a plugin) could never be planned — the
  model was told it did not exist;
* the prompt advertised tools the isolated executor cannot dispatch, so the
  model planned a step that was guaranteed to fail.

The catalog is the single source for both, and these tests pin its contract.
"""

from __future__ import annotations

import pytest

from arcen.agents.draft import DraftPlanner
from arcen.llm.client import LLMResponse
from arcen.tools import catalog
from arcen.tools.registry import BaseTool, Registry, load_builtin


@pytest.fixture()
def registry() -> Registry:
    return load_builtin()


def test_every_registered_tool_is_advertised(registry) -> None:
    names = [entry["name"] for entry in catalog.entries(registry)]
    assert names == registry.names()
    assert "bash" in names and "file.write" in names


def test_required_and_optional_arguments_are_split(registry) -> None:
    bash = next(e for e in catalog.entries(registry) if e["name"] == "bash")
    assert "cmd:str" in bash["required"]
    assert "cwd:str" in bash["optional"]


def test_capability_filter_hides_what_the_executor_cannot_run(registry) -> None:
    entries = catalog.entries(registry, available=["bash", "file.read"])
    assert [e["name"] for e in entries] == ["bash", "file.read"]
    assert "file.write" not in catalog.names(registry, available=["bash"])


def test_render_marks_required_arguments(registry) -> None:
    text = catalog.render(registry, available=["file.edit"])
    assert "(* = required)" in text
    assert "args: *find:str, *path:str, *replace:str" in text


def test_render_respects_the_character_budget(registry) -> None:
    tight = catalog.render(registry, max_chars=400)
    assert len(tight) <= 400
    # the degradation keeps tool names: a nameless catalog is useless
    assert "bash" in tight


def test_render_reports_tools_it_had_to_hide(registry) -> None:
    text = catalog.render(registry, max_tools=3)
    hidden = len(registry.names()) - 3
    assert f"(+{hidden} more tools not shown" in text


def test_render_of_an_empty_selection_is_empty(registry) -> None:
    assert catalog.render(registry, available=[]) == ""


def test_render_tolerates_a_registry_that_cannot_enumerate() -> None:
    """A dispatch-only proxy is not a reason to kill the turn."""

    class Opaque:
        def dispatch(self, name, args):
            return {"ok": True, "result": None, "error": None}

    assert catalog.render(Opaque()) == ""


def test_a_broken_tool_does_not_break_the_catalog() -> None:
    class Exploding(BaseTool):
        name = "boom.tool"
        description = "always raises while describing itself"
        Args = None  # type: ignore[assignment]

        def schema(self) -> dict:
            raise RuntimeError("no schema")

    registry = Registry()
    registry.register(_ok_tool())
    registry._tools["boom.tool"] = Exploding()
    assert [e["name"] for e in catalog.entries(registry)] == ["demo.tool"]


def _ok_tool() -> BaseTool:
    from pydantic import BaseModel

    class ArgsModel(BaseModel):
        path: str

    class Demo(BaseTool):
        name = "demo.tool"
        description = "does nothing"
        Args = ArgsModel

        def _run(self, args):
            return {"path": args.path}

    return Demo()


class _CatalogLLM:
    """Records the hint it was planned with; answers with one step."""

    def __init__(self, tool: str) -> None:
        self.tool = tool
        self.prompts: list[str] = []

    def complete(self, role, messages, **kwargs):
        self.prompts.append(messages[0]["content"])
        return LLMResponse(
            text=f'[{{"title": "step", "tool": "{self.tool}", "args": {{}}}}]',
            model="mock",
            tokens={"input": 1, "output": 1},
            cost_usd=0.0,
        )


def test_planner_prompt_carries_the_catalog(registry) -> None:
    llm = _CatalogLLM("file.read")
    planner = DraftPlanner(
        llm=llm,
        tool_catalog=catalog.render(registry, available=["file.read", "bash"]),
        tool_names={"file.read", "bash"},
    )
    planner.open_turn("read the config")
    plan_prompt = llm.prompts[-1]  # the first call is the intent classifier
    assert "## available tools" in plan_prompt
    assert "file.read [safe]" in plan_prompt
    assert "file.write" not in plan_prompt, "a filtered tool must not be advertised"


def test_planner_accepts_a_tool_outside_the_builtin_set(registry) -> None:
    """An MCP-bridged or plugin tool is plannable once it is advertised."""
    llm = _CatalogLLM("mcp.github.create_issue")
    planner = DraftPlanner(
        llm=llm,
        tool_catalog="mcp.github.create_issue [sandboxed] — open an issue",
        tool_names={"mcp.github.create_issue"},
    )
    plan = planner.open_turn("file the bug")
    assert plan[-1].steps[0]["tool"] == "mcp.github.create_issue"


def test_planner_still_nulls_a_tool_it_was_not_offered() -> None:
    llm = _CatalogLLM("warp.drive")
    planner = DraftPlanner(llm=llm, tool_catalog="bash [sandboxed] — shell", tool_names={"bash"})
    plan = planner.open_turn("teleport")
    assert plan[-1].steps[0]["tool"] is None
