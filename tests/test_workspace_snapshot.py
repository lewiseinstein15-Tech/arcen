"""The optional headless workspace is input-only, bounded, and symlink-free."""

import io
import os
import tarfile

import pytest
from test_turn_isolation import FakeDocker

from arcen.sandbox.workspace import WorkspaceError, snapshot_workspace


class FakeSocket:
    def __init__(self):
        self.sent = None
        self.closed = False
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent = data

    def recv(self, count):
        return b""

    def close(self):
        self.closed = True


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
    sock = FakeSocket()
    docker.api.exec_start = lambda eid, **kwargs: sock
    reg = DockerTurnRegistry(ArcenConfig(), docker_client=docker, workspace=str(tmp_path))
    assert sock.sent == archive and sock.closed and docker.run_args["volumes"] == {}
    command, kwargs = docker.container.calls[0]
    assert kwargs["stdin"] and kwargs["user"] == "65534:65534"
    assert kwargs["workdir"] == "/workspace" and not kwargs["privileged"]
    assert command[:4] == ["timeout", "--kill-after=2s", "120s", "python"]
    assert docker.run_args["read_only"] is True
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
    with pytest.raises(WorkspaceError, match="exceeds 3 file bytes"):
        snapshot_workspace(tmp_path)


def test_failed_workspace_import_removes_container_and_fails_closed(tmp_path):
    from arcen.config import ArcenConfig
    from arcen.sandbox.turn import DockerTurnRegistry, IsolationUnavailable

    (tmp_path / "input.txt").write_text("input")
    docker = FakeDocker()
    sock = FakeSocket()
    docker.api.exec_start = lambda eid, **kwargs: sock
    docker.api.exec_inspect = lambda eid: {"ExitCode": 1}
    with pytest.raises(IsolationUnavailable, match="Workspace import failed"):
        DockerTurnRegistry(ArcenConfig(), docker_client=docker, workspace=str(tmp_path))
    assert docker.container.removed and sock.closed
    assert len(docker.container.calls) == 1  # importer only; no planned command


def test_importer_extracts_inside_workdir_as_a_regular_user(tmp_path):
    import subprocess
    import sys

    from arcen.sandbox.workspace import CONTAINER_IMPORTER

    source = tmp_path / "source"
    source.mkdir()
    (source / "folder").mkdir()
    (source / "folder" / "input.txt").write_text("hello")
    archive = snapshot_workspace(source)
    destination = tmp_path / "container-workspace"
    destination.mkdir()
    result = subprocess.run(
        [sys.executable, "-c", CONTAINER_IMPORTER, str(len(archive))],
        input=archive,
        cwd=destination,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert (destination / "folder" / "input.txt").read_text() == "hello"
    assert (source / "folder" / "input.txt").read_text() == "hello"


def test_importer_rejects_parent_escape(tmp_path):
    import subprocess
    import sys

    from arcen.sandbox.workspace import CONTAINER_IMPORTER

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        entry = tarfile.TarInfo("../outside")
        entry.size = 4
        archive.addfile(entry, io.BytesIO(b"evil"))
    data = raw.getvalue()
    target = tmp_path / "container-workspace"
    target.mkdir()
    result = subprocess.run(
        [sys.executable, "-c", CONTAINER_IMPORTER, str(len(data))],
        input=data,
        cwd=target,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert not (tmp_path / "outside").exists()


def test_importer_rejects_archive_symlink(tmp_path):
    import subprocess
    import sys

    from arcen.sandbox.workspace import CONTAINER_IMPORTER

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        entry = tarfile.TarInfo("link")
        entry.type = tarfile.SYMTYPE
        entry.linkname = "/etc"
        archive.addfile(entry)
    data = raw.getvalue()
    result = subprocess.run(
        [sys.executable, "-c", CONTAINER_IMPORTER, str(len(data))],
        input=data,
        cwd=tmp_path,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert not (tmp_path / "link").exists()


@pytest.mark.parametrize("transport", ["tcp", "unix"])
def test_real_docker_sdk_stream_protocol_against_fake_engine(tmp_path, transport):
    """Use docker-py's real socket transport; the engine itself is a fake.

    This exercises HTTP upgrade, SocketIO unwrapping, stdin streaming and exit
    inspection without claiming to test Docker isolation or a real daemon.
    """
    import json
    import struct
    import subprocess
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from socketserver import ThreadingMixIn, UnixStreamServer
    from types import SimpleNamespace

    docker = pytest.importorskip("docker")
    if not hasattr(docker, "APIClient"):
        pytest.skip("Docker SDK not installed")
    from arcen.sandbox.workspace import CONTAINER_IMPORTER, import_workspace

    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("snapshot over the Docker SDK")
    destination = tmp_path / "fake-container-workspace"
    destination.mkdir()
    archive = snapshot_workspace(source)
    state = {"exit": None, "created": None, "payload": b""}

    class FakeEngine(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            if self.path.endswith("/containers/container-id/exec"):
                state["created"] = json.loads(body)
                payload = b'{"Id":"exec-id"}'
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path.endswith("/exec/exec-id/start"):
                self.send_response(101)
                self.send_header("Connection", "Upgrade")
                self.send_header("Upgrade", "tcp")
                self.end_headers()
                chunks = bytearray()
                while len(chunks) < len(archive):
                    chunk = self.connection.recv(min(4096, len(archive) - len(chunks)))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                state["payload"] = bytes(chunks)
                proc = subprocess.run(
                    [sys.executable, "-c", CONTAINER_IMPORTER, str(len(archive))],
                    input=bytes(chunks),
                    cwd=destination,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                state["exit"] = proc.returncode
                if proc.stderr:
                    self.connection.sendall(
                        struct.pack(">BxxxL", 2, len(proc.stderr)) + proc.stderr
                    )
                self.close_connection = True
            else:
                self.send_error(404)

        def do_GET(self):
            if not self.path.endswith("/exec/exec-id/json"):
                self.send_error(404)
                return
            payload = json.dumps({"ExitCode": state["exit"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    if transport == "unix":

        class ThreadingUnixServer(ThreadingMixIn, UnixStreamServer):
            daemon_threads = True

        sock_path = tmp_path / "docker.sock"
        server = ThreadingUnixServer(str(sock_path), FakeEngine)
        base_url = f"unix://{sock_path}"
    else:
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeEngine)
        base_url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = docker.APIClient(base_url=base_url, version="1.45")
    try:
        import_workspace(SimpleNamespace(api=client), SimpleNamespace(id="container-id"), archive)
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
    assert state["payload"] == archive
    assert state["created"]["AttachStdin"] is True
    assert state["created"]["User"] == "65534:65534"
    assert state["created"]["Privileged"] is False
    assert (destination / "input.txt").read_text() == "snapshot over the Docker SDK"


def test_broken_import_stream_removes_container_without_executing_plan(tmp_path):
    from arcen.config import ArcenConfig
    from arcen.sandbox.turn import DockerTurnRegistry, IsolationUnavailable

    (tmp_path / "input.txt").write_text("input")
    docker = FakeDocker()

    class BrokenSocket(FakeSocket):
        def sendall(self, data):
            raise ConnectionError("transport broke")

    sock = BrokenSocket()
    docker.api.exec_start = lambda eid, **kwargs: sock
    with pytest.raises(IsolationUnavailable, match="Workspace import failed"):
        DockerTurnRegistry(ArcenConfig(), docker_client=docker, workspace=str(tmp_path))
    assert docker.container.removed and sock.closed
    assert len(docker.container.calls) == 1


def test_running_importer_is_not_treated_as_success(tmp_path):
    from arcen.config import ArcenConfig
    from arcen.sandbox.turn import DockerTurnRegistry, IsolationUnavailable

    (tmp_path / "input.txt").write_text("input")
    docker = FakeDocker()
    sock = FakeSocket()
    docker.api.exec_start = lambda eid, **kwargs: sock
    docker.api.exec_inspect = lambda eid: {"ExitCode": None}
    with pytest.raises(IsolationUnavailable, match="Workspace import failed"):
        DockerTurnRegistry(ArcenConfig(), docker_client=docker, workspace=str(tmp_path))
    assert docker.container.removed and sock.closed
