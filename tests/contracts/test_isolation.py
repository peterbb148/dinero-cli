"""The asyncio socket-pair exception must not allow arbitrary connections or subprocesses."""

import socket
import subprocess

import pytest


def test_socket_pair_does_not_relax_external_io_guard():
    left, right = socket.socketpair()
    try:
        left.sendall(b"local")
        assert right.recv(5) == b"local"
    finally:
        left.close()
        right.close()
    with socket.socket() as client:
        for connect in (client.connect, client.connect_ex):
            with pytest.raises(AssertionError, match="external I/O"):
                connect(("127.0.0.1", 1))
    with pytest.raises(AssertionError, match="external I/O"):
        socket.getaddrinfo("example.invalid", 443)
    with pytest.raises(AssertionError, match="external I/O"):
        subprocess.Popen(["unused"])
