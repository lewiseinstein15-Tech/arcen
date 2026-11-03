"""Host baseline capture, no real Docker required."""

import io
import subprocess
import tarfile
import uuid

import pytest

from arcen.sandbox.baseline_store import capture_workspace_baseline, load_baseline
from arcen.sandbox.patch_validation import ArtifactError
from arcen.sandbox.workspace import WorkspaceError


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.invalid")
    (path / "file").write_text("committed\n")
    git(path, "add", "file")
    git(path, "commit", "-qm", "base")
    return path


def test_captures_current_tree_without_git_and_persists_identical_input(repo, tmp_path):
    (repo / "file").write_text("dirty\n")
    (repo / "new").write_text("new\n")
    session = str(uuid.uuid4())
    snapshot, base = capture_workspace_baseline(session, repo, home=tmp_path)
    assert base == git(repo, "rev-parse", "HEAD").decode().strip()
    assert load_baseline(session, home=tmp_path) == (snapshot, base)
    with tarfile.open(fileobj=io.BytesIO(snapshot)) as tar:
        assert set(tar.getnames()) == {"file", "new"}
        assert tar.extractfile("file").read() == b"dirty\n"


def test_non_root_refused_before_persisting(repo, tmp_path):
    sub = repo / "subdir"
    sub.mkdir()
    with pytest.raises(ArtifactError, match="Git root"):
        capture_workspace_baseline(str(uuid.uuid4()), sub, home=tmp_path)
    assert not (tmp_path / ".arcen").exists()


def test_configured_filter_refused_without_executing_it(repo, tmp_path):
    marker = tmp_path / "filter-executed"
    git(repo, "config", "filter.evil.clean", f"touch {marker}; cat")
    with pytest.raises(WorkspaceError, match="filter"):
        capture_workspace_baseline(str(uuid.uuid4()), repo, home=tmp_path)
    assert not marker.exists()
    assert not (tmp_path / ".arcen").exists()


def test_symlink_refused_without_baseline(repo, tmp_path):
    (repo / "link").symlink_to("file")
    with pytest.raises(WorkspaceError, match="symlink"):
        capture_workspace_baseline(str(uuid.uuid4()), repo, home=tmp_path)
    assert not (tmp_path / ".arcen").exists()
