"""A-01: discovery and verification use the same fake sandbox as work."""

import json

import pytest

from arcen.agents.temper import verify_sandbox_tests
from arcen.stream.events import to_dict


class Sandbox:
    def __init__(self, command, code=0, error=None):
        self.command = command
        self.code = code
        self.error = error
        self.calls = []

    def dispatch(self, name, args):
        self.calls.append((name, args))
        if len(self.calls) == 1:
            return {
                "ok": True,
                "result": {"exit": 0, "stdout": json.dumps({"command": self.command})},
            }
        return {
            "ok": self.code == 0,
            "error": self.error,
            "result": {
                "exit": self.code,
                "stdout": "\n".join(f"line {i}" for i in range(60)),
                "stderr": "",
            },
        }


def run(fake):
    events = []
    status = verify_sandbox_tests(fake, step=3, target="task", emit=events.append)
    return status, [to_dict(e) for e in events]


def test_no_tests_unverified_not_pass():
    fake = Sandbox(None)
    status, events = run(fake)
    assert status == "unverified"
    assert [e["type"] for e in events] == ["verify.start"]
    assert events[0]["status"] == "unverified"
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    "command", ["python -m pytest -q", "npm test", "cargo test", "go test ./..."]
)
def test_passing_test_has_bounded_evidence(command):
    fake = Sandbox(command)
    status, events = run(fake)
    assert status == "pass"
    assert events[-1]["type"] == "step.pass"
    evidence = events[-1]["evidence"]
    assert evidence["command"] == command and evidence["exit_code"] == 0
    assert len(evidence["output_tail"].splitlines()) == 50
    assert evidence["output_tail"].splitlines()[0] == "line 10"
    assert [args["cmd"] for _, args in fake.calls][1:] == [command]


def test_failing_test_fails():
    status, events = run(Sandbox("cargo test", 1))
    assert status == "fail" and events[-1]["type"] == "step.fail"
    assert events[-1]["evidence"]["exit_code"] == 1


def test_timeout_fails_with_reason():
    status, events = run(Sandbox("go test ./...", 124, "timed out"))
    assert status == "fail" and "timed out" in events[-1]["reason"]


def test_untrusted_discovery_output_cannot_be_run():
    fake = Sandbox("rm -rf /workspace")
    status, events = run(fake)
    assert status == "fail" and len(fake.calls) == 1
    assert events[-1]["type"] == "step.fail"


def test_discovery_inspects_workspace_without_executing_it(tmp_path):
    import subprocess
    import sys

    from arcen.agents.temper import _DISCOVER_TESTS

    # Isolated Python ignores a hostile workspace sitecustomize module.
    (tmp_path / "sitecustomize.py").write_text("raise RuntimeError('must not be imported')")
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _DISCOVER_TESTS],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(proc.stdout) == {"command": None}
    (tmp_path / "test_example.py").write_text("this is never imported")
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _DISCOVER_TESTS],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(proc.stdout) == {"command": "python -m pytest -q"}


@pytest.mark.parametrize(
    "manifest,testfile,expected",
    [
        ("package.json", "src/app.test.ts", "npm test"),
        ("Cargo.toml", "src/lib.rs", "cargo test"),
        ("go.mod", "main_test.go", "go test ./..."),
    ],
)
def test_discovery_requires_a_test_file(tmp_path, manifest, testfile, expected):
    import subprocess
    import sys

    from arcen.agents.temper import _DISCOVER_TESTS

    (tmp_path / manifest).write_text(
        '{"scripts":{"test":"example"}}' if manifest == "package.json" else ""
    )

    def discover():
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _DISCOVER_TESTS],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(proc.stdout)["command"]

    assert discover() is None
    path = tmp_path / testfile
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#[test] fn test_x() {}" if testfile.endswith(".rs") else "")
    assert discover() == expected


def test_non_bash_work_with_no_tests_is_unverified(tmp_path, monkeypatch):
    import threading

    import arcen.server.app as server
    from arcen.config import ArcenConfig
    from arcen.llm.client import LLMResponse

    class Planner:
        def complete(self, role, messages, **kwargs):
            if "Return ONLY the word" in messages[-1]["content"]:
                return LLMResponse(text="CODE", model="fake")
            return LLMResponse(
                text=json.dumps([{"title": "read", "tool": "file.read", "args": {"path": "x"}}]),
                model="fake",
            )

    class NonBashSandbox(Sandbox):
        def dispatch(self, name, args):
            if name == "file.read":
                self.calls.append((name, args))
                return {"ok": True, "result": {"content": "work"}}
            self.calls.append((name, args))
            return {"ok": True, "result": {"exit": 0, "stdout": '{"command": null}'}}

        def close(self, *, strict=False):
            pass

    config = ArcenConfig()
    config.session.dir = str(tmp_path)
    state = server.ServerState(config)
    state.llm = Planner()
    fake = NonBashSandbox(None)
    monkeypatch.setattr(server, "create_turn_registry", lambda *a, **kw: fake)
    state.run_flags["run"] = threading.Event()
    server.run_turn("read file", "session-a01", "run", state)
    events = state.emitters["session-a01"].replay(0)
    assert not any(e["type"] == "step.pass" for e in events)
    assert events[-1]["verification_status"] == "unverified"
    assert [name for name, _ in fake.calls] == ["file.read", "bash"]
