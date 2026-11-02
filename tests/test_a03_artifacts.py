"""A-03: patches are derived from bounded, untrusted archive data."""

import io
import tarfile

import pytest

from arcen.sandbox.artifacts import ArtifactError, archive_files, build_patch


def archive(entries):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for name, data, kind in entries:
            item = tarfile.TarInfo(name)
            if kind == "symlink":
                item.type = tarfile.SYMTYPE
                item.linkname = "/etc/passwd"
                tar.addfile(item)
            elif kind == "dir":
                item.type = tarfile.DIRTYPE
                tar.addfile(item)
            else:
                item.size = len(data)
                item.mode = 0o644
                tar.addfile(item, io.BytesIO(data))
    return out.getvalue()


def test_patch_contains_edits_without_touching_original(tmp_path):
    original = tmp_path / "source"
    original.write_text("before\n")
    before = archive([("source", b"before\n", "file")])
    after = archive([("workspace/source", b"after\n", "file"), ("workspace/new", b"new\n", "file")])
    patch, paths = build_patch(before, after)
    assert original.read_text() == "before\n"
    assert paths == ["new", "source"]
    assert b"diff --git a/source b/source" in patch and b"+after" in patch
    assert b"diff --git a/new b/new" in patch


@pytest.mark.parametrize(
    "name", ["workspace/../escape", "/workspace/escape", "workspace/a\\b", "workspace/a\nfile"]
)
def test_untrusted_unsafe_paths_rejected(name):
    with pytest.raises(ArtifactError):
        archive_files(archive([(name, b"bad", "file")]), prefix="workspace")


def test_output_symlinks_are_rejected():
    with pytest.raises(ArtifactError):
        archive_files(archive([("workspace/link", b"", "symlink")]), prefix="workspace")


def test_git_metadata_is_excluded():
    entries = archive(
        [("workspace/.git/config", b"secret", "file"), ("workspace/code", b"safe", "file")]
    )
    assert list(archive_files(entries, prefix="workspace")) == ["code"]


def test_binary_delete_and_add_patch_applies_only_when_explicit(tmp_path):
    import subprocess

    before = archive([("bin", b"\0old\xff", "file"), ("gone", b"bye\n", "file")])
    after = archive(
        [("workspace/bin", b"\0new\xff", "file"), ("workspace/new", b"hello\n", "file")]
    )
    patch, paths = build_patch(before, after)
    assert paths == ["bin", "gone", "new"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "bin").write_bytes(b"\0old\xff")
    (tmp_path / "gone").write_bytes(b"bye\n")
    subprocess.run(["git", "-C", str(tmp_path), "apply", "--check", "-"], input=patch, check=True)
    assert not (tmp_path / "new").exists()
    subprocess.run(["git", "-C", str(tmp_path), "apply", "-"], input=patch, check=True)
    assert (tmp_path / "bin").read_bytes() == b"\0new\xff"
    assert not (tmp_path / "gone").exists()
    assert (tmp_path / "new").read_bytes() == b"hello\n"


def test_duplicate_archive_member_is_rejected():
    with pytest.raises(ArtifactError):
        archive_files(
            archive([("workspace/a", b"1", "file"), ("workspace/a", b"2", "file")]),
            prefix="workspace",
        )
