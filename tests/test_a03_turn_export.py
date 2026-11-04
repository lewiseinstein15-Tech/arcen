"""End-to-end mock of the server turn; no real Docker behavior is implied."""

import io
import json
import subprocess
import tarfile
import threading
import uuid

import pytest
from fake_turn_registry import FakeTurnRegistry

from arcen.config import ArcenConfig
from arcen.llm.client import LLMResponse
from arcen.sandbox.artifact_apply import apply_artifact
from arcen.sandbox.export_stream import collect_export_stream
from arcen.sandbox.patch_validation import MAX_PATCH_BYTES
from arcen.server import app as server


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def archive(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for name, value in entries.items():
            entry = tarfile.TarInfo(name)
            if value is None:
                entry.type = tarfile.SYMTYPE
                entry.linkname = "file"
                tar.addfile(entry)
            else:
                content, mode = value if isinstance(value, tuple) else (value, 0o644)
                entry.mode, entry.size = mode, len(content)
                tar.addfile(entry, io.BytesIO(content))
    return stream.getvalue()


def hardlink_archive():
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        entry = tarfile.TarInfo("hard")
        entry.type, entry.linkname = tarfile.LNKTYPE, "file"
        tar.addfile(entry)
    return stream.getvalue()


class Planner:
    def is_available(self):
        return True

    def complete(self, role, messages, **kwargs):
        if "Return ONLY the word" in messages[-1]["content"]:
            return LLMResponse(text="CODE", model="mock")
        return LLMResponse(
            text=json.dumps([{"title": "work", "tool": "bash", "args": {"cmd": "true"}}]),
            model="mock",
        )


class FakeExportRegistry(FakeTurnRegistry):
    def __init__(self, chunks):
        super().__init__()
        self.chunks = chunks
        self.killed = False

    def kill(self):
        self.killed = True

    def export_workspace(self):
        assert not self.closed
        output, stderr = collect_export_stream(self.chunks, self)
        assert not stderr
        return output


@pytest.fixture
def context(tmp_path, monkeypatch):
    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "file").write_text("before\n")
    git(repo, "add", "file")
    git(repo, "commit", "-qm", "base")
    config = ArcenConfig()
    config.session.dir = str(tmp_path / "sessions")
    state = server.ServerState(config)
    state.llm = Planner()
    session = str(uuid.uuid4())
    state.run_flags["run"] = threading.Event()
    return repo, home, state, session


def execute(context, monkeypatch, chunks):
    repo, home, state, session = context
    fake = FakeExportRegistry(chunks)
    seen = []

    def factory(config, *, snapshot):
        path = home / ".arcen" / "artifacts" / session / "baseline" / "snapshot.tar"
        assert path.read_bytes() == snapshot  # persisted before any container starts
        seen.append(snapshot)
        return fake

    monkeypatch.setattr(server, "create_turn_registry", factory)
    server.run_turn("edit file", session, "run", state, workspace=str(repo))
    return state.emitter_for(session).replay(0), fake, seen


def test_real_turn_mock_exports_host_diff_and_can_apply(context, monkeypatch):
    repo, home, _state, session = context
    candidate = archive({"file": b"after\n", "new": b"new\n", ".git/config": b"evil"})
    events, fake, seen = execute(context, monkeypatch, [(candidate, None)])
    assert fake.closed and len(seen) == 1
    artifact = next(e["artifact"] for e in events if e["type"] == "file.diff")
    assert set(artifact["files"]) == {"file", "new"}
    patch = (home / ".arcen" / "artifacts" / session / "patch.diff").read_bytes()
    assert b"-before\n+after\n" in patch and b".git" not in patch
    assert events[-1]["type"] == "run.done"
    assert (repo / "file").read_text() == "before\n"
    assert not apply_artifact(session, target=repo, home=home)["applied"]
    assert apply_artifact(session, target=repo, home=home, yes=True)["applied"]
    assert (repo / "file").read_text() == "after\n"
    assert (repo / "new").read_text() == "new\n"


@pytest.mark.parametrize(
    "candidate",
    [
        archive({"link": None}),
        hardlink_archive(),
        archive({"../escape": b"bad"}),
        archive({"/absolute": b"bad"}),
        archive({".env.local": b"must-not-save"}),
        archive({"new-executable": (b"program", 0o755)}),
        b"x" * (MAX_PATCH_BYTES + 1),
    ],
)
def test_invalid_candidate_fails_closed_and_never_publishes_patch(context, monkeypatch, candidate):
    repo, home, _state, session = context
    events, fake, _ = execute(context, monkeypatch, [(candidate, None)])
    assert fake.closed
    assert events[-1]["type"] == "run.error" and events[-1]["code"] == "ARTIFACT_EXPORT_FAILED"
    assert not any(e["type"] == "file.diff" for e in events)
    assert not (home / ".arcen" / "artifacts" / session / "patch.diff").exists()
    assert (repo / "file").read_text() == "before\n"
    if len(candidate) > MAX_PATCH_BYTES:
        assert fake.killed and "size limit" in events[-1]["message"]


def test_fake_turn_deleted_new_binary_and_unchanged_executable_mode(context, monkeypatch):
    repo, home, _state, session = context
    (repo / "gone").write_text("delete\n")
    (repo / "image.bin").write_bytes(b"\x00old\xff")
    (repo / "tool").write_text("old\n")
    (repo / "tool").chmod(0o755)
    git(repo, "add", "gone", "image.bin", "tool")
    git(repo, "commit", "-qm", "more baseline files")
    candidate = archive(
        {
            "file": b"before\n",
            "image.bin": b"\x00new\xff",
            "tool": (b"new\n", 0o755),
            "added": b"new file\n",
        }
    )
    events, fake, _ = execute(
        context, monkeypatch, [(candidate[:100], None), (candidate[100:], None)]
    )
    assert fake.closed and events[-1]["type"] == "run.done"
    result = apply_artifact(session, target=repo, home=home)
    assert set(result["files"]) == {"gone", "image.bin", "tool", "added"}
    assert (repo / "gone").exists() and not (repo / "added").exists()
    patch = (home / ".arcen" / "artifacts" / session / "patch.diff").read_bytes()
    assert b"GIT binary patch" in patch
    assert b"old mode" not in patch and b"new mode" not in patch
    assert apply_artifact(session, target=repo, home=home, yes=True)["applied"]
    assert not (repo / "gone").exists()
    assert (repo / "image.bin").read_bytes() == b"\x00new\xff"
    assert (repo / "tool").read_text() == "new\n"
    assert (repo / "tool").stat().st_mode & 0o777 == 0o755
    assert (repo / "added").read_text() == "new file\n"


def test_fake_turn_executable_mode_change_is_rejected(context, monkeypatch):
    repo, home, _state, session = context
    candidate = archive({"file": (b"after\n", 0o755)})
    events, fake, _ = execute(context, monkeypatch, [(candidate, None)])
    assert fake.closed and events[-1]["code"] == "ARTIFACT_EXPORT_FAILED"
    assert not (home / ".arcen" / "artifacts" / session / "patch.diff").exists()
    assert (repo / "file").read_text() == "before\n"


def test_same_workspace_session_cannot_replace_its_baseline_or_patch(context, monkeypatch):
    repo, home, state, session = context
    candidate = archive({"file": b"first\n"})
    events, fake, _ = execute(context, monkeypatch, [(candidate, None)])
    assert fake.closed and events[-1]["type"] == "run.done"
    artifact = home / ".arcen" / "artifacts" / session
    patch_before = (artifact / "patch.diff").read_bytes()
    baseline_before = (artifact / "baseline" / "snapshot.tar").read_bytes()
    calls = []
    monkeypatch.setattr(server, "create_turn_registry", lambda *a, **kw: calls.append(True))
    server.run_turn("second", session, "run", state, workspace=str(repo))
    assert calls == []
    assert state.emitter_for(session).replay(0)[-1]["code"] == "SANDBOX_UNAVAILABLE"
    assert (artifact / "patch.diff").read_bytes() == patch_before
    assert (artifact / "baseline" / "snapshot.tar").read_bytes() == baseline_before
