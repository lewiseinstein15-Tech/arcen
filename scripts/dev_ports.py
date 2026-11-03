"""Fail closed when developer ports are already owned; never signal owners."""

import socket


def check_ports(ports=(3002, 5173), *, socket_factory=socket.socket):
    sockets = []
    try:
        for port in ports:
            sock = socket_factory(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(sock)
            try:
                sock.bind(("0.0.0.0", port))
            except OSError as exc:
                raise RuntimeError(f"port {port} unavailable: {exc}") from exc
    finally:
        for sock in sockets:
            sock.close()


if __name__ == "__main__":
    try:
        check_ports()
    except RuntimeError as exc:
        raise SystemExit(f"[dev] {exc}; stop the owner yourself and retry") from exc
