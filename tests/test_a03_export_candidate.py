"""Host orchestration, not yet connected to the real Docker turn."""

import io
import tarfile
import uuid

import pytest

from arcen.sandbox.baseline_store import save_baseline
from arcen.sandbox.host_export import export_candidate
from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError
from arcen.sandbox.workspace import snapshot_workspace
from arcen.stream.events import to_dict


def archive(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, payload in entries.items():
            item = tarfile.TarInfo(name)
            item.mode = 0o644
            item.size = len(payload)
            tar.addfile(item, io.BytesIO(payload))
    return buffer.getvalue()


def baseline(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "file").write_text("before\n")
    session = str(uuid.uuid4())
    saved = save_baseline(
        session, snapshot_workspace(workspace, exclude_git=True), "a" * 40, home=tmp_path
    )
    return session, saved


def test_baseline_candidate_to_host_patch_and_existing_event(tmp_path):
    session, saved = baseline(tmp_path)
    events = []
    result = export_candidate(
        session,
        archive({"file": b"after\n", ".git/config": b"untrusted"}),
        events.append,
        home=tmp_path,
    )
    patch = (saved.parent / "patch.diff").read_bytes()
    assert b"-before\n+after\n" in patch
    assert b".git" not in patch
    assert result["base_commit"] == "a" * 40
    assert to_dict(events[0])["type"] == "file.diff"
    assert to_dict(events[0])["artifact"]["files"] == ["file"]


@pytest.mark.parametrize(
    "candidate",
    [b"x" * (MAX_PATCH_BYTES + 1), archive({"../escape": b"x"}), archive({".env": b"secret"})],
)
def test_rejected_candidate_leaves_only_host_baseline(tmp_path, candidate):
    session, saved = baseline(tmp_path)
    events = []
    with pytest.raises(ArtifactError):
        export_candidate(session, candidate, events.append, home=tmp_path)
    assert events == []
    assert sorted(p.name for p in saved.parent.iterdir()) == ["baseline"]
