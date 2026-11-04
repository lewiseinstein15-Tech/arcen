"""Apply checks exercise real temporary Git repositories, not Docker export."""

import json
import os
import subprocess
import uuid

import pytest

from arcen.sandbox.artifact_apply import apply_artifact
from arcen.sandbox.artifact_store import save_artifact
from arcen.sandbox.patch_validation import ArtifactError


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "file.txt").write_text("before\n")
    (root / "image.bin").write_bytes(b"\x00before\xff")
    git(root, "add", "file.txt", "image.bin")
    git(root, "commit", "-qm", "baseline")
    return root


def make_patch(root, path="file.txt", content=b"after\n"):
    original = (root / path).read_bytes()
    (root / path).write_bytes(content)
    patch = git(root, "diff", "--binary", "--no-ext-diff", "--no-textconv", "--", path)
    (root / path).write_bytes(original)
    return patch


def artifact(repo, home, path="file.txt", content=b"after\n"):
    patch = make_patch(repo, path, content)
    session = str(uuid.uuid4())
    base = git(repo, "rev-parse", "HEAD").decode().strip()
    save_artifact(session, patch, base, home=home)
    return session


def test_dry_run_then_apply_only_changes_affected_path(repo, tmp_path):
    session = artifact(repo, tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    assert apply_artifact(session, target=repo, home=tmp_path)["files"] == ["file.txt"]
    assert (repo / "file.txt").read_text() == "before\n"
    assert apply_artifact(session, target=repo, home=tmp_path, yes=True)["applied"]
    assert (repo / "file.txt").read_text() == "after\n"
    assert (repo / "image.bin").read_bytes() == b"\x00before\xff"
    assert git(repo, "rev-parse", "HEAD") == head


def test_binary_patch(repo, tmp_path):
    session = artifact(repo, tmp_path, "image.bin", b"\x00after\xff\xfe")
    apply_artifact(session, target=repo, yes=True, home=tmp_path)
    assert (repo / "image.bin").read_bytes() == b"\x00after\xff\xfe"


def test_dirty_affected_path_refused(repo, tmp_path):
    session = artifact(repo, tmp_path)
    (repo / "file.txt").write_text("local change\n")
    with pytest.raises(ArtifactError, match="uncommitted"):
        apply_artifact(session, target=repo, yes=True, home=tmp_path)
    assert (repo / "file.txt").read_text() == "local change\n"


def test_different_base_requires_override(repo, tmp_path):
    session = artifact(repo, tmp_path)
    (repo / "other.txt").write_text("unrelated\n")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-qm", "different base")
    with pytest.raises(ArtifactError, match="differs"):
        apply_artifact(session, target=repo, home=tmp_path)
    assert apply_artifact(session, target=repo, allow_different_base=True, home=tmp_path)[
        "files"
    ] == ["file.txt"]


def test_assume_unchanged_cannot_hide_dirty_file(repo, tmp_path):
    session = artifact(repo, tmp_path)
    git(repo, "update-index", "--assume-unchanged", "file.txt")
    (repo / "file.txt").write_text("unreported local change\n")
    with pytest.raises(ArtifactError, match="assume-unchanged"):
        apply_artifact(session, target=repo, yes=True, home=tmp_path)


def test_tampering_refused(repo, tmp_path):
    session = artifact(repo, tmp_path)
    path = tmp_path / ".arcen" / "artifacts" / session / "patch.diff"
    path.write_bytes(path.read_bytes().replace(b"after", b"OTHER"))
    with pytest.raises(ArtifactError, match="hash mismatch"):
        apply_artifact(session, target=repo, yes=True, home=tmp_path)


def test_metadata_file_list_tampering_refused(repo, tmp_path):
    session = artifact(repo, tmp_path)
    path = tmp_path / ".arcen" / "artifacts" / session / "meta.json"
    data = json.loads(path.read_text())
    data["files"] = []
    path.write_text(json.dumps(data))
    with pytest.raises(ArtifactError, match="file list mismatch"):
        apply_artifact(session, target=repo, yes=True, home=tmp_path)


def test_unprivate_artifact_refused(repo, tmp_path):
    session = artifact(repo, tmp_path)
    os.chmod(tmp_path / ".arcen" / "artifacts" / session / "patch.diff", 0o644)
    with pytest.raises(ArtifactError, match="not private"):
        apply_artifact(session, target=repo, home=tmp_path)


def test_new_file_dry_run_and_apply(repo, tmp_path):
    patch = b"diff --git a/new.txt b/new.txt\nnew file mode 100644\nindex 0000000..ce01362\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+hello\n"
    session = str(uuid.uuid4())
    save_artifact(session, patch, git(repo, "rev-parse", "HEAD").decode().strip(), home=tmp_path)
    apply_artifact(session, target=repo, home=tmp_path)
    assert not (repo / "new.txt").exists()
    apply_artifact(session, target=repo, home=tmp_path, yes=True)
    assert (repo / "new.txt").read_text() == "hello\n"


def test_git_filter_is_refused_without_running_filter(repo, tmp_path):
    (repo / ".gitattributes").write_text("file.txt filter=evil\n")
    git(repo, "add", ".gitattributes")
    git(repo, "commit", "-qm", "attributes")
    session = artifact(repo, tmp_path)
    marker = tmp_path / "filter-ran"
    git(repo, "config", "filter.evil.clean", f"touch {marker}; cat")
    git(repo, "config", "filter.evil.smudge", f"touch {marker}; cat")
    with pytest.raises(ArtifactError, match="Git filters"):
        apply_artifact(session, target=repo, yes=True, home=tmp_path)
    assert not marker.exists()


def test_untracked_new_file_is_not_overwritten(repo, tmp_path):
    patch = b"diff --git a/new.txt b/new.txt\nnew file mode 100644\nindex 0000000..ce01362\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+hello\n"
    session = str(uuid.uuid4())
    save_artifact(session, patch, git(repo, "rev-parse", "HEAD").decode().strip(), home=tmp_path)
    (repo / "new.txt").write_text("local\n")
    with pytest.raises(ArtifactError, match="uncommitted"):
        apply_artifact(session, target=repo, home=tmp_path, yes=True)
    assert (repo / "new.txt").read_text() == "local\n"


def test_cli_defaults_to_dry_run(repo, tmp_path, monkeypatch, capsys):
    from arcen.cli import main

    session = artifact(repo, tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["arcen", "apply", session])
    assert main() == 0
    assert "file.txt" in capsys.readouterr().out
    assert (repo / "file.txt").read_text() == "before\n"
    monkeypatch.setattr("sys.argv", ["arcen", "apply", session, "--yes"])
    assert main() == 0
    assert (repo / "file.txt").read_text() == "after\n"


def test_unrelated_git_filter_does_not_run_during_status(repo, tmp_path):
    (repo / "other.txt").write_text("tracked\n")
    (repo / ".gitattributes").write_text("other.txt filter=evil\n")
    git(repo, "add", "other.txt", ".gitattributes")
    git(repo, "commit", "-qm", "add unrelated file")
    session = artifact(repo, tmp_path)
    marker = tmp_path / "filter-ran"
    git(repo, "config", "filter.evil.clean", f"touch {marker}; cat")
    (repo / "other.txt").write_text("dirty unrelated file\n")
    apply_artifact(session, target=repo, yes=False, home=tmp_path)
    assert not marker.exists()
