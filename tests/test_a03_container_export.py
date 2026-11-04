"""Fixed exporter and fake Docker stream; does not prove real Docker behavior."""

import io
import os
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

from arcen.sandbox.export_stream import CONTAINER_EXPORTER, export_workspace
from arcen.sandbox.host_export import extract_candidate
from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError


class Container:
    id = "fake"
    killed = False

    def kill(self):
        self.killed = True


class API:
    def __init__(self, output, code=0):
        self.output = output
        self.code = code
        self.command = None
        self.options = None

    def exec_create(self, container, cmd, **kwargs):
        assert container == "fake"
        self.command, self.options = cmd, kwargs
        return {"Id": "fixed"}

    def exec_start(self, exec_id, **kwargs):
        assert exec_id == "fixed" and kwargs == {"stream": True, "demux": True}
        return iter(self.output)

    def exec_inspect(self, exec_id):
        return {"ExitCode": self.code}


def test_fixed_isolated_exec_and_bounded_stream():
    api, container = API([(b"tar", None)]), Container()
    assert export_workspace(SimpleNamespace(api=api), container) == b"tar"
    assert api.command[:6] == [
        "timeout",
        "--kill-after=2s",
        "120s",
        "/usr/local/bin/python",
        "-I",
        "-c",
    ]
    assert api.command[-1] == CONTAINER_EXPORTER
    assert api.options["workdir"] == "/workspace"
    assert api.options["user"] == "65534:65534" and api.options["privileged"] is False


@pytest.mark.parametrize("code,stderr", [(1, b""), (None, b""), (0, b"error")])
def test_failed_exec_returns_no_archive(code, stderr):
    api = API([(b"partial", stderr)], code)
    with pytest.raises(ArtifactError, match="export failed"):
        export_workspace(SimpleNamespace(api=api), Container())


def test_oversize_kills_container():
    container = Container()
    api = API([(b"x" * (MAX_PATCH_BYTES + 1), None)])
    with pytest.raises(ArtifactError, match="exceeded"):
        export_workspace(SimpleNamespace(api=api), container)
    assert container.killed


def test_fixed_script_omits_git_and_preserves_unsafe_links_for_extractor(tmp_path):
    workspace = tmp_path / "work"
    workspace.mkdir()
    (workspace / "file").write_text("content")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("ignored")
    (workspace / "link").symlink_to("file")
    os.link(workspace / "file", workspace / "hard")
    result = subprocess.run(
        [sys.executable, "-I", "-c", CONTAINER_EXPORTER],
        cwd=workspace,
        capture_output=True,
        check=True,
    )
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tar:
        names = tar.getnames()
        assert ".git" not in names and not any(name.startswith(".git/") for name in names)
        assert tar.getmember("link").issym()
        assert tar.getmember("hard").islnk() or tar.getmember("file").islnk()
    with pytest.raises(ArtifactError, match="unsupported entry"):
        extract_candidate(result.stdout, tmp_path / "extracted")
