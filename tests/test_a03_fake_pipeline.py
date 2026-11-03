"""Manual fake-stream pipeline; does not exercise container exec or server wiring."""

import subprocess
import uuid

import pytest

from arcen.sandbox.artifact_apply import apply_artifact
from arcen.sandbox.artifact_store import publish_artifact
from arcen.sandbox.export_stream import collect_export_stream
from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError
from arcen.stream.events import to_dict


class FakeContainer:
    def __init__(self, chunks):
        self.chunks = chunks
        self.killed = False

    def stream(self):
        yield from self.chunks

    def kill(self):
        self.killed = True


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def test_fake_stream_to_saved_event_to_dry_run_and_apply(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "a.txt").write_text("before\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD").decode().strip()
    (repo / "a.txt").write_text("after\n")
    patch = git(repo, "diff", "--binary", "--no-ext-diff", "--no-textconv")
    (repo / "a.txt").write_text("before\n")
    runtime = FakeContainer([(patch[:30], None), (patch[30:], None)])
    output, stderr = collect_export_stream(runtime.stream(), runtime)
    assert not stderr
    session, events = str(uuid.uuid4()), []
    saved = publish_artifact(session, output, base, events.append, home=tmp_path)
    assert to_dict(events[0])["artifact"]["sha256"] == saved["sha256"]
    assert apply_artifact(session, target=repo, home=tmp_path)["files"] == ["a.txt"]
    assert (repo / "a.txt").read_text() == "before\n"
    assert apply_artifact(session, target=repo, home=tmp_path, yes=True)["applied"]
    assert (repo / "a.txt").read_text() == "after\n"
    assert git(repo, "rev-parse", "HEAD").decode().strip() == base


def test_fake_oversize_kills_and_never_creates_artifact(tmp_path):
    session, events = str(uuid.uuid4()), []
    runtime = FakeContainer([(b"x" * (MAX_PATCH_BYTES + 1), None)])
    with pytest.raises(ArtifactError, match="exceeded"):
        output, _ = collect_export_stream(runtime.stream(), runtime)
        publish_artifact(session, output, "a" * 40, events.append, home=tmp_path)
    assert runtime.killed and not events and not (tmp_path / ".arcen").exists()
