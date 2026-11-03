"""A-03 bounded collection tests use only a fake container."""

import pytest

from arcen.sandbox.export_stream import collect_export_stream
from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError


class FakeContainer:
    def __init__(self):
        self.killed = False

    def kill(self):
        self.killed = True


def test_returns_complete_output_at_limit():
    runtime = FakeContainer()
    assert collect_export_stream([(b"abc", b"x"), (b"de", None)], runtime, limit=6) == (
        b"abcde",
        b"x",
    )
    assert not runtime.killed


def test_oversize_stops_container_without_returning_partial_data(tmp_path):
    runtime = FakeContainer()
    destination = tmp_path / "patch.diff"
    with pytest.raises(ArtifactError, match="exceeded 5 bytes"):
        patch, _ = collect_export_stream([(b"abc", None), (b"def", None)], runtime, limit=5)
        destination.write_bytes(patch)
    assert runtime.killed
    assert not destination.exists()


def test_stderr_counts_toward_limit():
    runtime = FakeContainer()
    with pytest.raises(ArtifactError, match="exceeded"):
        collect_export_stream([(b"ab", b"cd")], runtime, limit=3)
    assert runtime.killed


def test_malformed_chunks_fail_closed():
    runtime = FakeContainer()
    with pytest.raises(ArtifactError, match="invalid"):
        collect_export_stream([(b"ok", "not bytes")], runtime)
    assert runtime.killed


def test_no_limit_above_five_megabytes():
    with pytest.raises(ValueError, match="immutable cap"):
        collect_export_stream([], FakeContainer(), limit=MAX_PATCH_BYTES + 1)


def test_real_oversized_chunk_is_rejected_without_saving(tmp_path):
    runtime = FakeContainer()
    with pytest.raises(ArtifactError, match="exceeded"):
        patch, _ = collect_export_stream([(b"x" * (MAX_PATCH_BYTES + 1), None)], runtime)
        (tmp_path / "patch.diff").write_bytes(patch)
    assert runtime.killed and not (tmp_path / "patch.diff").exists()


def test_stream_failure_stops_container_without_returning_partial_bytes():
    runtime = FakeContainer()

    def broken():
        yield b"partial", None
        raise OSError("transport failure")

    with pytest.raises(ArtifactError, match="stream failed"):
        collect_export_stream(broken(), runtime)
    assert runtime.killed
