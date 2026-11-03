"""A-03: validated artifact storage, not an integrated export test."""

import hashlib
import json
import os
import uuid

import pytest

from arcen.sandbox.artifact_store import save_artifact
from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError

PATCH = b"diff --git a/new.txt b/new.txt\nnew file mode 100644\nindex 0000000..1234567\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+hello\n"
BASE = "a" * 40


def test_saves_private_patch_and_metadata(tmp_path):
    session = str(uuid.uuid4())
    result = save_artifact(session, PATCH, BASE, home=tmp_path)
    patch = tmp_path / ".arcen" / "artifacts" / session / "patch.diff"
    metadata = json.loads((patch.parent / "meta.json").read_text())
    assert patch.read_bytes() == PATCH
    assert os.stat(patch).st_mode & 0o777 == 0o600
    assert metadata == {
        "base_commit": BASE,
        "files": ["new.txt"],
        "size": len(PATCH),
        "sha256": hashlib.sha256(PATCH).hexdigest(),
    }
    assert result["path"] == str(patch)


def test_existing_artifact_is_not_overwritten(tmp_path):
    session = str(uuid.uuid4())
    save_artifact(session, PATCH, BASE, home=tmp_path)
    with pytest.raises(ArtifactError, match="already exists"):
        save_artifact(session, PATCH, BASE, home=tmp_path)


@pytest.mark.parametrize("session", ["../escape", "a", str(uuid.uuid4()).upper()])
def test_invalid_session_never_creates_files(tmp_path, session):
    with pytest.raises(ArtifactError, match="session"):
        save_artifact(session, PATCH, BASE, home=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_oversized_patch_creates_no_artifact(tmp_path):
    with pytest.raises(ArtifactError, match="exceeds"):
        save_artifact(str(uuid.uuid4()), b"x" * (MAX_PATCH_BYTES + 1), BASE, home=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_refuses_symlink_artifact_directory(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".arcen").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        save_artifact(str(uuid.uuid4()), PATCH, BASE, home=tmp_path)
    assert list(outside.iterdir()) == []


def test_failed_metadata_write_removes_partial_artifact(tmp_path, monkeypatch):
    from arcen.sandbox import artifact_store

    original = artifact_store._write_private

    def failing(directory, name, data):
        if name == "meta.json":
            raise OSError("simulated write failure")
        original(directory, name, data)

    monkeypatch.setattr(artifact_store, "_write_private", failing)
    session = str(uuid.uuid4())
    with pytest.raises(OSError, match="simulated write failure"):
        save_artifact(session, PATCH, BASE, home=tmp_path)
    assert not (tmp_path / ".arcen" / "artifacts" / session).exists()


def _baseline(tmp_path, session, base=BASE):
    from arcen.sandbox.baseline_store import save_baseline
    from arcen.sandbox.workspace import snapshot_workspace

    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    (workspace / "file").write_text("baseline")
    return save_baseline(
        session, snapshot_workspace(workspace, exclude_git=True), base, home=tmp_path
    )


def test_publish_into_private_baseline_session(tmp_path):
    from arcen.sandbox.baseline_store import load_baseline

    session = str(uuid.uuid4())
    baseline = _baseline(tmp_path, session)
    result = save_artifact(session, PATCH, BASE, home=tmp_path, require_baseline=True)
    assert (baseline.parent / "patch.diff").read_bytes() == PATCH
    assert load_baseline(session, home=tmp_path)[1] == BASE
    assert result["files"] == ["new.txt"]
    with pytest.raises(ArtifactError, match="already exists"):
        save_artifact(session, PATCH, BASE, home=tmp_path, require_baseline=True)
    assert (baseline.parent / "patch.diff").read_bytes() == PATCH


def test_baseline_base_mismatch_saves_no_patch(tmp_path):
    session = str(uuid.uuid4())
    baseline = _baseline(tmp_path, session)
    with pytest.raises(ArtifactError, match="does not match"):
        save_artifact(session, PATCH, "b" * 40, home=tmp_path, require_baseline=True)
    assert sorted(p.name for p in baseline.parent.iterdir()) == ["baseline"]


def test_partial_failure_preserves_baseline_and_existing_metadata(tmp_path):
    session = str(uuid.uuid4())
    baseline = _baseline(tmp_path, session)
    meta = baseline.parent / "meta.json"
    meta.write_text("existing")
    with pytest.raises(ArtifactError, match="already exists"):
        save_artifact(session, PATCH, BASE, home=tmp_path, require_baseline=True)
    assert meta.read_text() == "existing"
    assert not (baseline.parent / "patch.diff").exists()
    assert (baseline / "snapshot.tar").exists()


def test_tampered_baseline_refuses_publication(tmp_path):
    session = str(uuid.uuid4())
    baseline = _baseline(tmp_path, session)
    (baseline / "snapshot.tar").write_bytes(b"tampered")
    with pytest.raises(ArtifactError, match="mismatch"):
        save_artifact(session, PATCH, BASE, home=tmp_path, require_baseline=True)
    assert not (baseline.parent / "patch.diff").exists()
