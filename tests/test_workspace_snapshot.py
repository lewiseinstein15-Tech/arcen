"""The optional headless workspace is input-only, bounded, and symlink-free."""

import io
import os
import tarfile

import pytest
from test_turn_isolation import FakeDocker

from arcen.sandbox.workspace import WorkspaceError, snapshot_workspace


def test_snapshot_contains_input_without_host_bind(tmp_path):
    from arcen.config import ArcenConfig
    from arcen.sandbox.turn import DockerTurnRegistry

    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "input.txt").write_text("test input")
    archive = snapshot_workspace(tmp_path)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        assert tar.extractfile("folder/input.txt").read() == b"test input"
        assert tar.getmember("folder/input.txt").uid == 65534
    docker = FakeDocker()
    imported = []
    docker.container.put_archive = lambda path, data: imported.append((path, data)) or True
    reg = DockerTurnRegistry(ArcenConfig(), docker_client=docker, workspace=str(tmp_path))
    assert imported == [("/workspace", archive)] and docker.run_args["volumes"] == {}
    reg.close()


def test_rejects_symlinks_including_directory_links(tmp_path):
    (tmp_path / "link").symlink_to("/etc")
    with pytest.raises(WorkspaceError, match="symlink"):
        snapshot_workspace(tmp_path)


def test_rejects_special_files(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(WorkspaceError, match="special file"):
        snapshot_workspace(tmp_path)


def test_entry_limit_is_enforced(tmp_path, monkeypatch):
    from arcen.sandbox import workspace

    monkeypatch.setattr(workspace, "MAX_FILES", 1)
    (tmp_path / "one").touch()
    (tmp_path / "two").touch()
    with pytest.raises(WorkspaceError, match="exceeds"):
        snapshot_workspace(tmp_path)


def test_size_limit_is_enforced(tmp_path, monkeypatch):
    from arcen.sandbox import workspace

    monkeypatch.setattr(workspace, "MAX_BYTES", 3)
    (tmp_path / "data").write_text("1234")
    with pytest.raises(WorkspaceError, match="64 MiB"):
        snapshot_workspace(tmp_path)


def test_failed_workspace_import_removes_container_and_fails_closed(tmp_path):
    from arcen.config import ArcenConfig
    from arcen.sandbox.turn import DockerTurnRegistry, IsolationUnavailable

    (tmp_path / "input.txt").write_text("input")
    docker = FakeDocker()
    docker.container.put_archive = lambda path, data: False
    with pytest.raises(IsolationUnavailable):
        DockerTurnRegistry(ArcenConfig(), docker_client=docker, workspace=str(tmp_path))
    assert docker.container.removed and not docker.container.calls
