"""A-03a host extractor: malicious archives are never executed."""

import io
import tarfile

import pytest

from arcen.sandbox.host_export import extract_candidate
from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError


def archive(name, *, kind=tarfile.REGTYPE, content=b"ok", mode=0o644):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        info = tarfile.TarInfo(name)
        info.type = kind
        info.mode = mode
        info.size = len(content) if kind == tarfile.REGTYPE else 0
        info.linkname = "target" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
        tar.addfile(info, io.BytesIO(content) if info.size else None)
    return out.getvalue()


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]
)
def test_reject_special_files(tmp_path, kind):
    with pytest.raises(ArtifactError, match="unsupported"):
        extract_candidate(archive("x", kind=kind), tmp_path / "extract")


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "a/../escape", "a//b", "a/./b", "a/" + "x" * 129]
)
def test_reject_unsafe_paths(tmp_path, name):
    with pytest.raises(ArtifactError, match="path"):
        extract_candidate(archive(name), tmp_path / "extract")


def test_reject_setid(tmp_path):
    with pytest.raises(ArtifactError, match="setuid"):
        extract_candidate(archive("x", mode=0o4755), tmp_path / "extract")


def test_git_directory_is_ignored(tmp_path):
    extract_candidate(archive(".git/config", content=b"evil"), tmp_path / "extract")
    assert not (tmp_path / "extract" / ".git").exists()


def test_preserves_executable_mode(tmp_path):
    extract_candidate(archive("nested/file", mode=0o755), tmp_path / "extract")
    assert (tmp_path / "extract" / "nested" / "file").stat().st_mode & 0o777 == 0o755


def test_oversize_rejected_before_extraction(tmp_path):
    with pytest.raises(ArtifactError, match="size limit"):
        extract_candidate(b"x" * (MAX_PATCH_BYTES + 1), tmp_path / "extract")
    assert not (tmp_path / "extract").exists()


def test_special_entry_inside_git_is_still_rejected(tmp_path):
    with pytest.raises(ArtifactError, match="unsupported"):
        extract_candidate(archive(".git/link", kind=tarfile.SYMTYPE), tmp_path / "extract")


def test_file_size_cap(tmp_path, monkeypatch):
    from arcen.sandbox import host_export

    monkeypatch.setattr(host_export, "MAX_FILE_SIZE", 1)
    with pytest.raises(ArtifactError, match="file exceeds"):
        extract_candidate(archive("file", content=b"too big"), tmp_path / "extract")


def test_entry_count_cap(tmp_path, monkeypatch):
    from arcen.sandbox import host_export

    monkeypatch.setattr(host_export, "MAX_ENTRIES", 1)
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        for name in ("first", "second"):
            item = tarfile.TarInfo(name)
            tar.addfile(item)
    with pytest.raises(ArtifactError, match="entry limit"):
        extract_candidate(data.getvalue(), tmp_path / "extract")
