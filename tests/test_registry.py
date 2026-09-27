"""T-005 / Test-plan T-04 — tool registry (BACKEND-SPEC Part 3).

Proves: 40 tools register; duplicate name and hand-written schema
rejected; MCP namespace not shadowed; schemas auto-generated from hints.
"""

import pytest

from arcen.tools import (
    BaseTool,
    Registry,
    RegistryError,
    SchemaRejected,
    Tool,
    load_builtin,
)
from arcen.tools.bash import BashTool
from arcen.tools.file import FileEdit
from pydantic import BaseModel


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load_builtin()


def test_40_tools_register(registry: Registry) -> None:
    # mirrors the ticket Verification: 40 tools registered
    assert len(registry) == 40
    assert "bash" in registry
    assert "file.edit" in registry
    assert registry.names() == sorted(registry.names())


def test_all_tools_satisfy_protocol(registry: Registry) -> None:
    for name in registry.names():
        tool = registry.get(name)
        assert isinstance(tool, Tool), f"{name} violates the Tool Protocol"


def test_every_schema_is_generated(registry: Registry) -> None:
    for name, schema in registry.schemas().items():
        assert schema.get("type") == "object", name
        assert "properties" in schema, name
        assert isinstance(schema.get("required", []), list)


def test_bash_schema_matches_hints(registry: Registry) -> None:
    schema = registry.schemas()["bash"]
    assert "cmd" in schema["properties"]
    assert "timeout_s" in schema["properties"]
    assert schema["required"] == ["cmd"]


def test_duplicate_name_rejected(registry: Registry) -> None:
    with pytest.raises(RegistryError, match="duplicate"):
        registry.register(BashTool())


def test_handwritten_schema_rejected() -> None:
    class Rogue(BaseTool):
        name = "rogue"
        description = "tool with a hand-written schema"
        danger = "safe"

        class Args(BaseModel):
            x: int = 1

        def schema(self) -> dict:  # hand-written — rejected
            return {"type": "object", "properties": {}}

        def _run(self, a) -> dict:
            return {}

    with pytest.raises(SchemaRejected):
        Registry().register(Rogue())


def test_mcp_namespace_shadowing_rejected() -> None:
    class Imposter(BaseTool):
        name = "mcp.github.create_issue"
        description = "shadows the MCP namespace"
        danger = "safe"

        class Args(BaseModel):
            pass

        def _run(self, a) -> dict:
            return {}

    with pytest.raises(RegistryError, match="MCP"):
        Registry().register(Imposter())


def test_bad_danger_rejected() -> None:
    class Shady(BaseTool):
        name = "shady.tool"
        description = "bad danger level"
        danger = "yolo"

        class Args(BaseModel):
            pass

        def _run(self, a) -> dict:
            return {}

    with pytest.raises(RegistryError, match="danger"):
        Registry().register(Shady())


def test_dispatch_envelope_and_never_raises(registry: Registry) -> None:
    # happy path
    out = registry.dispatch("math.eval", {"expr": "2 + 2"})
    assert out["ok"] is True and out["result"]["value"] == 4 and out["error"] is None
    # invalid args → failure as a value, not an exception
    out = registry.dispatch("bash", {"timeout_s": "not-a-number"})
    assert out["ok"] is False and out["error"]
    # unknown tool → failure as a value
    out = registry.dispatch("no.such.tool", {})
    assert out["ok"] is False and "unknown tool" in out["error"]
    # a tool that raises internally is still caught at the boundary
    out = registry.dispatch("file.read", {"path": "/definitely/not/here/xyz"})
    assert out["ok"] is False and out["error"]


def test_file_edit_roundtrip(registry: Registry, tmp_path) -> None:
    p = tmp_path / "t.txt"
    p.write_text("hello world")
    out = registry.dispatch("file.edit", {"path": str(p), "find": "world", "replace": "ARCEN"})
    assert out["ok"] is True
    assert p.read_text() == "hello ARCEN"


def test_execute_returns_envelope_directly() -> None:
    # ticket T-006 command preview: BashTool().execute({'cmd': 'echo hi'})
    out = BashTool().execute({"cmd": "echo hi"})
    assert out["ok"] is True
    assert out["result"]["stdout"] == "hi\n"
    assert out["result"]["exit"] == 0


def test_file_edit_schema_source() -> None:
    # the schema derives from the typed args model — always in sync
    schema = FileEdit().schema()
    assert set(FileEdit.Args.model_fields) == set(schema["properties"].keys())
