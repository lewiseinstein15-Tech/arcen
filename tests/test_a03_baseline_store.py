import hashlib
import io
import json
import tarfile
import uuid

import pytest

from arcen.sandbox.baseline_store import save_baseline
from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError
from arcen.sandbox.workspace import snapshot_workspace


def test_snapshot_skips_git_when_requested(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("untrusted git")
    (tmp_path / "file").write_text("baseline")
    snapshot = snapshot_workspace(tmp_path, exclude_git=True)
    with tarfile.open(fileobj=io.BytesIO(snapshot)) as tar:
        assert tar.getnames() == ["file"]


def test_baseline_saved_private_and_not_overwritten(tmp_path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    (workspace / "file").write_text("original")
    snapshot = snapshot_workspace(workspace, exclude_git=True)
    session = str(uuid.uuid4())
    dest = save_baseline(session, snapshot, "a" * 40, home=home)
    assert dest.name == "baseline"
    assert (dest.stat().st_mode & 0o777) == 0o700
    assert (dest / "snapshot.tar").read_bytes() == snapshot
    assert (dest / "snapshot.tar").stat().st_mode & 0o777 == 0o600
    assert json.loads((dest / "baseline.json").read_text()) == {
        "base_commit": "a" * 40,
        "sha256": hashlib.sha256(snapshot).hexdigest(),
        "size": len(snapshot),
    }
    with pytest.raises(ArtifactError, match="already exists"):
        save_baseline(session, snapshot, "a" * 40, home=home)


def test_oversized_baseline_saves_nothing(tmp_path):
    with pytest.raises(ArtifactError, match="size limit"):
        save_baseline(str(uuid.uuid4()), b"x" * (MAX_PATCH_BYTES + 1), "a" * 40, home=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_reload_detects_baseline_tampering(tmp_path):
    from arcen.sandbox.baseline_store import load_baseline

    workspace, home = tmp_path / "workspace", tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    (workspace / "file").write_text("original")
    snapshot = snapshot_workspace(workspace, exclude_git=True)
    session = str(uuid.uuid4())
    destination = save_baseline(session, snapshot, "a" * 40, home=home)
    assert load_baseline(session, home=home) == (snapshot, "a" * 40)
    path = destination / "snapshot.tar"
    path.write_bytes(path.read_bytes().replace(b"original", b"modified"))
    with pytest.raises(ArtifactError, match="hash mismatch"):
        load_baseline(session, home=home)
