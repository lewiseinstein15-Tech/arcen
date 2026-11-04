"""Artifact metadata reuses file.diff without changing legacy payloads."""

import uuid

import pytest

from arcen.sandbox.artifact_store import publish_artifact
from arcen.sandbox.patch_validation import ArtifactError
from arcen.stream.events import EVENT_TYPES, FileDiff, from_dict, to_dict

PATCH = b"diff --git a/new.txt b/new.txt\nnew file mode 100644\nindex 0000000..1234567\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+hello\n"


def test_publish_emits_existing_event_after_file_exists(tmp_path):
    events = []

    def emit(event):
        assert (tmp_path / ".arcen" / "artifacts" / session / "patch.diff").read_bytes() == PATCH
        events.append(event)

    session = str(uuid.uuid4())
    result = publish_artifact(session, PATCH, "a" * 40, emit, home=tmp_path)
    wire = to_dict(events[0])
    assert wire["type"] == "file.diff" and len(EVENT_TYPES) == 17
    assert wire["artifact"] == {
        "path": result["path"],
        "files": ["new.txt"],
        "sha256": result["sha256"],
    }
    assert to_dict(from_dict(wire)) == wire


def test_failure_emits_no_artifact_event(tmp_path):
    events = []
    with pytest.raises(ArtifactError):
        publish_artifact(str(uuid.uuid4()), b"bad", "a" * 40, events.append, home=tmp_path)
    assert events == []


def test_old_file_diff_wire_shape_unchanged():
    event = FileDiff(seq=1, path="file", patch="patch", ts=2.0)
    assert to_dict(event) == {
        "seq": 1,
        "type": "file.diff",
        "path": "file",
        "patch": "patch",
        "ts": 2.0,
    }
