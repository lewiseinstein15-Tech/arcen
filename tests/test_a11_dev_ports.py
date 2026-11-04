"""Mock socket checks never signal or terminate unrelated processes."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "dev_ports", Path(__file__).parents[1] / "scripts/dev_ports.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Socket:
    def __init__(self, occupied):
        self.occupied = occupied
        self.closed = False

    def bind(self, address):
        if address[1] in self.occupied:
            raise OSError("already in use")

    def close(self):
        self.closed = True


def test_occupied_port_refuses_and_closes_sockets():
    created = []

    def factory(*args):
        sock = Socket({5173})
        created.append(sock)
        return sock

    with pytest.raises(RuntimeError, match="port 5173 unavailable"):
        module.check_ports(socket_factory=factory)
    assert all(sock.closed for sock in created)


def test_free_ports_close_after_check():
    created = []

    def factory(*args):
        sock = Socket(set())
        created.append(sock)
        return sock

    module.check_ports(socket_factory=factory)
    assert len(created) == 2 and all(sock.closed for sock in created)


def test_script_no_longer_kills_port_owners():
    text = (Path(__file__).parents[1] / "scripts/dev.sh").read_text()
    assert "lsof" not in text and "kill -9" not in text
    assert "kill %1" in text
