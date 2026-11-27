"""Isolated file operations: helper semantics and dispatch wiring.

The helper runs inside the container in production. Here it is executed
directly against a temp root to prove its path confinement and result shapes;
the Docker boundary itself is covered by test_turn_isolation.py.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from test_turn_isolation import FakeDocker

from arcen.config import ArcenConfig
from arcen.sandbox.isolated_ops import HELPER, build_argv, validate
from arcen.sandbox.turn import DockerTurnRegistry


def run(root, name, args):
    argv = build_argv(name, args, root=str(root))
    completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=30)
    return json.loads(completed.stdout)


def run_raw(root, name, args):
    """Bypass host validation to exercise the helper's own guards."""
    argv = ["python3", "-c", HELPER, name, str(root), json.dumps(args)]
    completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=30)
    return json.loads(completed.stdout)


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "README.md").write_text("# demo\n")
    return tmp_path


def test_read_returns_content_and_line_window(root):
    payload = run(root, "file.read", {"path": "src/app.py"})
    assert payload["ok"] is True
    assert payload["result"]["content"] == "def add(a, b):\n    return a + b\n"
    assert payload["result"]["total_lines"] == 2

    window = run(root, "file.read", {"path": "src/app.py", "offset_line": 1, "limit_lines": 1})
    assert window["result"]["content"] == "    return a + b\n"
    assert window["result"]["truncated"] is False


def test_list_and_glob_stay_inside_root(root):
    listed = run(root, "file.list", {"path": "src"})
    assert [entry["name"] for entry in listed["result"]["entries"]] == ["app.py"]
    assert listed["result"]["entries"][0]["type"] == "file"

    globbed = run(root, "file.glob", {"pattern": "**/*.py"})
    assert globbed["result"]["matches"] == [str((root / "src" / "app.py").resolve())]


def test_search_reports_path_line_and_text(root):
    found = run(root, "search.text", {"pattern": "return a \\+ b", "glob": "*.py"})
    assert found["ok"] is True
    assert found["result"]["count"] == 1
    match = found["result"]["matches"][0]
    assert match["line"] == 2 and "return a + b" in match["text"]


def test_edit_replaces_exactly_and_reports_ambiguity(root):
    edited = run(root, "file.edit", {"path": "src/app.py", "find": "a + b", "replace": "b + a"})
    assert edited["ok"] is True
    assert edited["result"]["replacements"] == 1
    assert "return b + a" in (root / "src" / "app.py").read_text()

    missing = run(root, "file.edit", {"path": "src/app.py", "find": "nope", "replace": "x"})
    assert missing["ok"] is False and "not found" in missing["error"]

    (root / "dup.txt").write_text("x x")
    ambiguous = run(root, "file.edit", {"path": "dup.txt", "find": "x", "replace": "y", "count": 1})
    assert ambiguous["ok"] is False and "ambiguous" in ambiguous["error"]


def test_write_creates_parents_and_reports_bytes(root):
    written = run(root, "file.write", {"path": "pkg/sub/mod.py", "content": "x = 1\n"})
    assert written["ok"] is True
    assert written["result"] == {"path": str((root / "pkg/sub/mod.py").resolve()), "bytes": 6}
    assert (root / "pkg/sub/mod.py").read_text() == "x = 1\n"


def test_write_drops_stale_bytecode_so_a_same_size_rewrite_takes_effect(root):
    (root / "mod.py").write_text("value = 1\n")
    assert (
        subprocess.run(
            [sys.executable, "-c", "import mod; print(mod.value)"],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        == "1"
    )
    run(root, "file.write", {"path": "mod.py", "content": "value = 2\n"})
    assert (
        subprocess.run(
            [sys.executable, "-c", "import mod; print(mod.value)"],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        == "2"
    )


def test_write_refuses_a_directory_and_oversized_content(root):
    on_dir = run(root, "file.write", {"path": "src", "content": "x"})
    assert on_dir["ok"] is False and "not a regular file" in on_dir["error"]
    with pytest.raises(ValueError, match="too large to write"):
        validate("file.write", {"path": "a", "content": "x" * 96_001})
    big = run_raw(root, "file.write", {"path": "big.txt", "content": "x" * 96_001})
    assert big["ok"] is False and "larger than 96000" in big["error"]
    assert not (root / "big.txt").exists()


@pytest.mark.parametrize("path", ["../escape", "/etc/passwd", "src/../../escape"])
def test_paths_outside_the_root_are_refused(root, path):
    payload = run(root, "file.read", {"path": path})
    assert payload["ok"] is False
    assert "escapes the isolated workspace" in payload["error"]
    write = run(root, "file.write", {"path": path, "content": "x"})
    assert write["ok"] is False
    assert "escapes the isolated workspace" in write["error"]


def test_validate_rejects_unknown_keys_types_and_oversized_arguments(root):
    with pytest.raises(ValueError, match="unknown argument"):
        validate("file.read", {"path": "a", "shell": "rm -rf /"})
    with pytest.raises(ValueError, match="must be an integer"):
        validate("file.read", {"path": "a", "limit_lines": "10"})
    with pytest.raises(ValueError, match="too large"):
        validate("file.edit", {"path": "a", "find": "x", "replace": "y" * 1_100_000})
    with pytest.raises(ValueError, match="not an isolated file operation"):
        validate("file.append", {"path": "a"})
    with pytest.raises(ValueError, match="unknown argument"):
        validate("file.write", {"path": "a", "content": "x", "mode": "append"})


def test_dispatch_runs_file_tools_inside_the_container():
    docker = FakeDocker()
    docker.output = [(b'{"ok": true, "result": {"content": "hi"}, "error": null}', b"")]
    reg = DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    response = reg.dispatch("file.read", {"path": "src/app.py"})
    assert response == {"ok": True, "result": {"content": "hi"}, "error": None}
    command, kwargs = docker.container.calls[-1]
    assert command[0] == "python3" and command[1] == "-c" and command[3] == "file.read"
    assert command[4] == "/workspace"
    assert kwargs["workdir"] == "/workspace" and kwargs["user"] == "65534:65534"


def test_dispatch_runs_file_write_inside_the_container():
    docker = FakeDocker()
    docker.output = [
        (b'{"ok": true, "result": {"path": "/workspace/a.py", "bytes": 6}, "error": null}', b"")
    ]
    reg = DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    response = reg.dispatch("file.write", {"path": "a.py", "content": "x = 1\n"})
    assert response["ok"] is True and response["result"]["bytes"] == 6
    command, kwargs = docker.container.calls[-1]
    assert command[3] == "file.write" and command[4] == "/workspace"
    assert kwargs["user"] == "65534:65534"


def test_dispatch_denies_tools_outside_the_allowlist_without_exec():
    docker = FakeDocker()
    reg = DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    for name in ("file.append", "file.delete", "code.eval"):
        response = reg.dispatch(name, {"path": "/etc/passwd"})
        assert not response["ok"] and "not yet available" in response["error"]
    assert docker.container.calls == []


def test_dispatch_rejects_malformed_helper_output():
    docker = FakeDocker()
    docker.output = [(b"Traceback: not json", b"")]
    reg = DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    response = reg.dispatch("file.read", {"path": "x"})
    assert not response["ok"] and "malformed output" in response["error"]
    assert "Traceback" in response["result"]["stdout"]


# -- git: the sandbox must accept what the planner was told it accepts ------
# The catalog is rendered from the HOST tool schema (git.add takes `root`),
# while execution happens in the container. When the two drift the model
# follows the catalog and gets "unknown argument(s): root" — a tool that is
# advertised and unusable. This table is the contract between them.

GIT_TOOLS = (
    "git.status",
    "git.diff",
    "git.log",
    "git.show",
    "git.add",
    "git.commit",
    "git.branch",
    "git.checkout",
)


@pytest.mark.parametrize("name", GIT_TOOLS)
def test_sandbox_accepts_every_argument_the_host_schema_advertises(name):
    from arcen.tools.registry import load_builtin

    tool = load_builtin().get(name)
    advertised = set(tool.Args.model_fields)
    from arcen.sandbox.isolated_ops import _ARG_KEYS

    missing = advertised - _ARG_KEYS[name]
    assert not missing, f"{name}: advertised but refused inside the sandbox: {sorted(missing)}"


def test_git_round_trip_inside_the_helper(root):
    # there is no git.init tool: initialising is a bash step, the ops act on
    # an existing repository
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    assert run(root, "git.branch", {"name": "main", "create": True})["ok"] is True
    added = run(root, "git.add", {"paths": ["src/app.py", "README.md"], "root": "."})
    assert added["ok"] is True, added
    assert added["result"]["status"]["staged"], "staging must be visible in the status"

    committed = run(root, "git.commit", {"message": "add demo files"})
    assert committed["ok"] is True, committed
    assert committed["result"]["summary"] == "add demo files"

    log = run(root, "git.log", {"limit": 5})
    assert log["ok"] is True
    assert log["result"]["commits"][0]["subject"] == "add demo files"

    status = run(root, "git.status", {"root": "."})
    assert status["result"]["clean"] is True


def test_git_root_outside_the_workspace_is_refused(root):
    payload = run(root, "git.status", {"root": "/etc"})
    assert payload["ok"] is False
    assert "escapes the isolated workspace" in payload["error"]
