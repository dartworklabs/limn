"""HTTP listener activation uses real sockets and survives unavailable reverse DNS.

Only the unmanaged resolver is replaced, inside an isolated process at the HTTP adapter boundary.
The bind, listen, TCP connection and close operations run against the real operating system.
"""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(("server_type", "address"), (("Server", "127.0.0.1"), ("Server6", "::1")))
def test_listener_accepts_connections_when_reverse_dns_never_answers(server_type, address):
    """A local listener must activate even when external reverse name resolution cannot return."""
    program = '''
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler
from limn.web.handler import Server, Server6

def unavailable_reverse_dns(host):
    """Represent an external resolver that cannot answer, without faking socket binding or listening."""
    print("reverse DNS blocked after bind", flush=True)
    threading.Event().wait()
    return host

socket.getfqdn = unavailable_reverse_dns
server_type = {"Server": Server, "Server6": Server6}[sys.argv[1]]
with server_type((sys.argv[2], 0), BaseHTTPRequestHandler) as server:
    with socket.socket(server.address_family) as connection:
        connection.settimeout(1)
        connected = connection.connect_ex(server.server_address)
    print(json.dumps({"connection": connected, "name": server.server_name}), flush=True)
'''
    try:
        result = subprocess.run(
            [sys.executable, "-c", program, server_type, address],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        observed = result.stdout.strip()
        assert result.returncode == 0, result.stderr
    except subprocess.TimeoutExpired as error:
        observed = (error.stdout or b"").decode("utf-8", "replace")
    assert observed == '{"connection": 0, "name": "%s"}' % address, observed
