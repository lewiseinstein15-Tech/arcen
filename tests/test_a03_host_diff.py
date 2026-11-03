"""Host diff uses immutable input archives and never executes candidate code."""

import io
import tarfile

import pytest

from arcen.sandbox.host_export import build_host_patch
from arcen.sandbox.patch_validation import ArtifactError, validate_patch


def snapshot(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for name, (data, mode) in files.items():
            info = tarfile.TarInfo(name)
            info.mode, info.size = mode, len(data)
            tar.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def test_host_diff_handles_edit_new_delete_binary_and_ignores_git():
    baseline = snapshot(
        {
            "edit": (b"before\n", 0o644),
            "gone": (b"gone\n", 0o644),
            "binary": (b"\x00old", 0o644),
            "run": (b"old\n", 0o755),
        }
    )
    candidate = snapshot(
        {
            "edit": (b"after\n", 0o644),
            "new": (b"new\n", 0o644),
            "binary": (b"\x00new", 0o644),
            "run": (b"new\n", 0o755),
            ".git/config": (b"bad", 0o644),
        }
    )
    patch = build_host_patch(baseline, candidate)
    assert set(validate_patch(patch)) == {"edit", "gone", "new", "binary", "run"}
    assert b"-before\n+after\n" in patch
    assert b"GIT binary patch" in patch
    assert b".git/config" not in patch


def test_unchanged_attributes_are_ignored_and_changes_refused():
    original = {".gitattributes": (b"* filter=evil\n", 0o644), "file": (b"one\n", 0o644)}
    changed = {".gitattributes": (b"* filter=evil\n", 0o644), "file": (b"two\n", 0o644)}
    assert validate_patch(build_host_patch(snapshot(original), snapshot(changed))) == ["file"]
    changed[".gitattributes"] = (b"changed", 0o644)
    with pytest.raises(ArtifactError, match="gitattributes"):
        build_host_patch(snapshot(original), snapshot(changed))
