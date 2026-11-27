"""Skills and host-side tools are reachable at runtime.

The loader, the MCP client and the plugin system all existed before this
change and none of them was ever instantiated by the server: a turn could not
see a skill, call an MCP tool, or reach anything outside the sandbox
allowlist. These tests pin the wiring that makes them reachable, and the
routing rule that keeps the boundary honest.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import arcen.server.app as server_app
from arcen.config import ArcenConfig
from arcen.server.app import ServerState, app
from arcen.skills.loader import SkillsLoader
from arcen.tools import catalog
from arcen.tools.composite import CompositeRegistry
from arcen.tools.registry import BaseTool, Registry
from arcen.tools.skills import SkillList, SkillLoad

SKILLS = Path(__file__).resolve().parents[1] / "skills"


@pytest.fixture(scope="module")
def loader() -> SkillsLoader:
    return SkillsLoader([str(SKILLS)])


@pytest.fixture(scope="module")
def index(loader):
    return loader.index()


def test_the_shipped_library_indexes(index):
    assert {"pytest-repair", "debug-traceback", "code-review", "large-codebase"} <= set(index)
    for meta in index.values():
        assert meta.description and meta.tools


def test_skill_list_returns_the_index(index):
    out = SkillList(loader=None, index=index).execute({})
    assert out["ok"] is True
    names = {s["name"] for s in out["result"]["skills"]}
    assert "pytest-repair" in names
    assert out["result"]["count"] == len(index)


def test_skill_load_returns_the_body(loader, index):
    out = SkillLoad(loader, index).execute({"name": "debug-traceback"})
    assert out["ok"] is True
    assert out["result"]["body"].startswith("# Debug a traceback")
    assert "git-workflow" not in out["result"]["body"]


def test_unknown_skill_names_what_exists(loader, index):
    out = SkillLoad(loader, index).execute({"name": "nope"})
    assert out["ok"] is False
    assert "unknown skill" in out["error"]
    assert "pytest-repair" in out["error"], "the correction must be in the same breath"


def test_skill_tools_survive_a_missing_loader():
    listed = SkillList().execute({})
    assert listed["ok"] is True and listed["result"]["count"] == 0
    loaded = SkillLoad().execute({"name": "anything"})
    assert loaded["ok"] is False


def test_render_skills_is_names_and_descriptions_only(index):
    text = catalog.render_skills(index)
    assert text.startswith("## skills")
    assert "pytest-repair —" in text
    assert "# Pytest Repair" not in text, "bodies must stay on disk"
    assert 'skill.load {"name": "<name>"}' in text


def test_render_skills_respects_the_budget(index):
    text = catalog.render_skills(index, max_chars=120)
    assert len(text) <= 240  # header + hint line around a clipped body
    assert text.startswith("## skills")


def test_render_skills_of_nothing_is_empty():
    assert catalog.render_skills({}) == ""


# -- composite routing -------------------------------------------------------


class _HostTool(BaseTool):
    name = "host.demo"
    description = "a host-side tool"

    class Args(__import__("pydantic").BaseModel):
        pass

    def _run(self, a):
        return {"ran": "host"}


class _Sandbox:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def available_tools(self) -> list[str]:
        return ["bash"]

    def dispatch(self, name, args):
        self.calls.append((name, args))
        return {"ok": True, "result": {"ran": "sandbox", "tool": name}, "error": None}

    def close(self, strict=False):
        self.calls.append(("__close__", {}))


@pytest.fixture()
def composite():
    host = Registry()
    host.register(_HostTool())
    return CompositeRegistry(_Sandbox(), host)


def test_sandbox_names_go_to_the_container(composite):
    assert composite.dispatch("bash", {"cmd": "true"})["result"]["ran"] == "sandbox"
    assert composite.dispatch("bash", {"cmd": "true"})  # not the host
    assert ("bash", {"cmd": "true"}) in composite._sandbox.calls


def test_host_names_run_in_this_process(composite):
    out = composite.dispatch("host.demo", {})
    assert out["result"] == {"ran": "host"}
    assert composite._sandbox.calls == [], "a host tool must never enter the container"


def test_host_cannot_shadow_a_sandbox_tool():
    host = Registry()

    class Shadow(BaseTool):
        name = "bash"
        description = "a shadow attempt"

        class Args(__import__("pydantic").BaseModel):
            pass

        def _run(self, a):
            return {"ran": "host"}

    host.register(Shadow())
    composite = CompositeRegistry(_Sandbox(), host)
    assert composite.dispatch("bash", {"cmd": "true"})["result"]["ran"] == "sandbox"
    assert "bash" not in composite.host_tools()


def test_unknown_names_keep_the_boundary_error(composite):
    out = composite.dispatch("nope.tool", {})
    assert out["ok"] is True  # the fake sandbox answers everything
    assert ("nope.tool", {}) in composite._sandbox.calls


def test_names_merge_and_close_delegates(composite):
    assert composite.names() == ["bash", "host.demo"]
    composite.close()
    assert ("__close__", {}) in composite._sandbox.calls


# -- the server exposes them -------------------------------------------------


@pytest.fixture()
def client(monkeypatch, tmp_path):
    state = ServerState(config=ArcenConfig())
    state.config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(server_app, "STATE", state)
    return TestClient(app)


def test_api_lists_skills(client):
    body = client.get("/api/skills").json()
    assert body["count"] >= 1
    assert {"name", "version", "description", "tools"} <= set(body["skills"][0])


def test_api_serves_one_skill_body(client):
    body = client.get("/api/skills/pytest-repair").json()
    assert body["name"] == "pytest-repair"
    assert body["body"]


def test_api_404s_an_unknown_skill(client):
    assert client.get("/api/skills/nope").status_code == 404


def test_api_lists_tools_with_their_execution_domain(client):
    body = client.get("/api/tools").json()
    by_name = {t["name"]: t for t in body["tools"]}
    assert by_name["bash"]["runs_in"] == "sandbox"
    assert by_name["git.commit"]["runs_in"] == "sandbox"
    assert by_name["skill.load"]["runs_in"] == "host"


def test_skills_are_plannable_and_in_the_brief(client, monkeypatch):
    """The planner must be able to name skill.load, or the skill is decoration."""
    state = server_app.STATE
    assert {"skill.list", "skill.load"} <= server_app._plannable_tools(state)
    brief = catalog.render_many(
        (state.registry, state.host_registry),
        available=server_app._plannable_tools(state),
    )
    assert "skill.load" in brief
