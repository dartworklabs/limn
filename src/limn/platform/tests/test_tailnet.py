"""The tailnet candidate list: what the local tailscaled's status says about people, read over its LocalAPI.

The transports are exercised against real servers bound in a temporary folder (a unix socket, and a TCP port on the
loopback for the macOS route), so the Host header, the headers that must be absent, the order of the socket paths and
every failure mode happen for real. Nothing here mocks http.client.

Run: uv run pytest -q src/limn/platform/tests/test_tailnet.py
"""

import base64
import json
import os
import shutil
import socket
import socketserver
import tempfile
import threading
import time
import unittest

from limn.platform import tailnet
from limn.platform.tailnet import DirectoryCache, Sources, TailnetDirectory, TailnetUser, project_users, read_directory


def user(login, name=None, pic="https://pics.example.com/a.png"):
    """One entry of the status User map, with the four fields tailscaled gives."""
    return {"ID": 1, "LoginName": login, "DisplayName": name if name is not None else login, "ProfilePicURL": pic}


def status(users, state="Running"):
    """A status document whose User map holds users, keyed by their ID."""
    return {"BackendState": state, "User": {str(i): u for i, u in enumerate(users, 1)}}


class Projection(unittest.TestCase):
    """project_users keeps three fields of a User entry, drops what cannot be a member, and sorts."""

    def test_takes_login_name_and_pic(self):
        """The login, display name and picture are what the owner sees; the numeric ID is not carried."""
        got = project_users(status([user("alice@example.com", "Alice", "https://pics.example.com/alice.png")]))
        self.assertEqual(got, (TailnetUser("alice@example.com", "Alice", "https://pics.example.com/alice.png"),))

    def test_missing_name_falls_back_to_the_login_and_missing_pic_is_none(self):
        """An empty display name is shown as the login; an empty or non-web picture address is no picture."""
        entries = [user("a@example.com", "", ""), user("b@example.com", "B", "javascript:alert(1)")]
        got = project_users(status(entries))
        self.assertEqual(
            got, (TailnetUser("a@example.com", "a@example.com", None), TailnetUser("b@example.com", "B", None))
        )

    def test_keeps_every_string_login_and_drops_entries_without_one(self):
        """What counts as a person is the caller's rule: a login with a space or 'local' is passed on as it is, an
        entry with no string login is not."""
        entries = [user(x) for x in ["has space@example.com", "local", "", None, 7]] + [user("ok@example.com")]
        got = project_users(status(entries))
        self.assertEqual([x.login for x in got], ["has space@example.com", "local", "ok@example.com"])

    def test_sorts_by_name_ignoring_case(self):
        """The list is ordered by display name, upper and lower case alike."""
        entries = [user("c@example.com", "carol"), user("a@example.com", "Bob"), user("b@example.com", "alice")]
        got = project_users(status(entries))
        self.assertEqual([x.name for x in got], ["alice", "Bob", "carol"])

    def test_a_status_without_a_user_map_is_an_empty_list(self):
        """A document of another shape yields no users instead of an error."""
        for doc in ({}, {"User": None}, {"User": []}, {"User": {"1": "not an object"}}):
            self.assertEqual(project_users(doc), ())

    def test_partial_is_always_true(self):
        """The User map holds only the owners of the peers this node can see, so a list is never the whole tailnet."""
        self.assertIs(TailnetDirectory((), True, "x").partial, True)
        self.assertIs(tailnet.listed(()).partial, True)
        self.assertIs(tailnet.unavailable("why").partial, True)


class FakeApi:
    """A LocalAPI stand-in on a real server. `behavior(request_head)` returns (status line, body) or None to never answer.
    `heads` collects every request head the server read, as text."""

    def __init__(self, server, behavior):
        self.server = server
        self.behavior = behavior
        self.heads = []
        self.release = threading.Event()
        api = self

        class Handler(socketserver.BaseRequestHandler):
            """Read one request head, record it, answer per the behavior."""

            def handle(self):
                """One connection: the head up to the blank line, then the behavior's answer."""
                data = b""
                self.request.settimeout(5)
                try:
                    while b"\r\n\r\n" not in data:
                        chunk = self.request.recv(4096)
                        if not chunk:
                            return
                        data += chunk
                    head = data.decode("latin-1")
                    api.heads.append(head)
                    answer = api.behavior(head)
                    if answer is None:
                        api.release.wait(5)
                        return
                    api.send(self.request, answer)
                except OSError:
                    return

        self.server.RequestHandlerClass = Handler
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @staticmethod
    def send(conn, answer):
        """Write an answer: (status line, body bytes), or (status line, an iterator of body pieces with a length)."""
        line, body = answer
        if type(body) is bytes:
            conn.sendall(
                ("HTTP/1.1 %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % (line, len(body))).encode() + body
            )
            return
        length, pieces = body
        conn.sendall(("HTTP/1.1 %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % (line, length)).encode())
        for piece in pieces:
            conn.sendall(piece)

    def close(self):
        """Stop the server and release any handler still waiting."""
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


class ServerCase(unittest.TestCase):
    """A temporary folder for sockets and, per test, the servers it started."""

    def setUp(self):
        """A short folder (unix socket paths are length-limited), a clean cache, and the list of servers to stop."""
        # Deliberately /tmp: a unix socket path is limited to 104 bytes on macOS, and the default temp folder is longer.
        self.dir = tempfile.mkdtemp(prefix="tn", dir="/tmp")
        self.apis = []
        self.cache = DirectoryCache()

    def tearDown(self):
        """Stop every server and remove the folder."""
        for api in self.apis:
            api.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def unix_api(self, name, behavior):
        """A fake LocalAPI on a unix socket called name in the temporary folder; returns (path, api)."""
        path = os.path.join(self.dir, name)
        server = socketserver.ThreadingUnixStreamServer(path, socketserver.BaseRequestHandler)
        server.daemon_threads = True
        api = FakeApi(server, behavior)
        self.apis.append(api)
        return path, api

    def sources(self, *paths, max_body=1 << 20, mac_dir=None):
        """Sources that look at these socket paths only, and at a macOS folder that does not exist by default."""
        return Sources(tuple(paths), mac_dir or os.path.join(self.dir, "no-such-mac-dir"), max_body)


def ok(doc):
    """A behavior that answers 200 with the document as JSON."""
    body = json.dumps(doc).encode()
    return lambda head: ("200 OK", body)


class UnixTransport(ServerCase):
    """The Linux route: HTTP over tailscaled's unix socket, without a subprocess."""

    def test_reads_status_over_a_unix_socket(self):
        """A running node's users come back, listed and partial, without a reason."""
        path, _ = self.unix_api("s", ok(status([user("bob@example.com", "Bob")])))
        got = read_directory(100.0, self.cache, 1.0, sources=self.sources(path))
        self.assertEqual(got.users, (TailnetUser("bob@example.com", "Bob", "https://pics.example.com/a.png"),))
        self.assertIs(got.partial, True)
        self.assertIsNone(got.reason)

    def test_sends_the_local_tailscaled_host_header(self):
        """tailscaled answers only a request whose Host is local-tailscaled.sock, and the path is the status route."""
        path, api = self.unix_api("s", ok(status([])))
        read_directory(100.0, self.cache, 1.0, sources=self.sources(path))
        lines = api.heads[0].split("\r\n")
        self.assertEqual(lines[0], "GET /localapi/v0/status HTTP/1.1")
        self.assertIn("Host: local-tailscaled.sock", lines)

    def test_sends_no_origin_or_referer(self):
        """tailscaled answers 403 when either header is present, so neither is sent."""
        path, api = self.unix_api("s", ok(status([])))
        read_directory(100.0, self.cache, 1.0, sources=self.sources(path))
        names = [x.split(":", 1)[0].lower() for x in api.heads[0].split("\r\n")[1:] if ":" in x]
        self.assertNotIn("origin", names)
        self.assertNotIn("referer", names)

    def test_tries_socket_paths_in_order(self):
        """A path that does not exist is skipped, and the first live one answers even when a later one also would."""
        first, _ = self.unix_api("one", ok(status([user("first@example.com")])))
        second, _ = self.unix_api("two", ok(status([user("second@example.com")])))
        missing = os.path.join(self.dir, "missing")
        got = read_directory(100.0, self.cache, 1.0, sources=self.sources(missing, first, second))
        self.assertEqual([x.login for x in got.users], ["first@example.com"])

    def test_a_stale_socket_file_falls_through_to_the_next_path(self):
        """A socket file nobody listens on refuses the connection; the next candidate is tried."""
        stale = os.path.join(self.dir, "stale")
        dead = socket.socket(socket.AF_UNIX)
        dead.bind(stale)
        dead.close()  # the file stays, nothing listens
        live, _ = self.unix_api("live", ok(status([user("live@example.com")])))
        got = read_directory(100.0, self.cache, 1.0, sources=self.sources(stale, live))
        self.assertEqual([x.login for x in got.users], ["live@example.com"])

    def test_the_answer_is_remembered_for_a_few_seconds(self):
        """Two reads inside the cache window reach tailscaled once; a later read asks again."""
        path, api = self.unix_api("s", ok(status([user("a@example.com")])))
        src = self.sources(path)
        read_directory(100.0, self.cache, 1.0, sources=src)
        read_directory(101.0, self.cache, 1.0, sources=src)
        self.assertEqual(len(api.heads), 1)
        read_directory(100.0 + tailnet.CACHE_SECONDS + 1, self.cache, 1.0, sources=src)
        self.assertEqual(len(api.heads), 2)


class Failures(ServerCase):
    """Every failure is an empty list with a reason; none raises."""

    def assert_none(self, got, reason=None):
        """An unavailable answer: no users, partial, a reason (the given one when named)."""
        self.assertEqual(got.users, ())
        self.assertIs(got.partial, True)
        self.assertTrue(got.reason)
        if reason is not None:
            self.assertEqual(got.reason, reason)

    def test_no_socket_anywhere(self):
        """Nothing to talk to is the ordinary case of a machine without tailscale."""
        got = read_directory(
            100.0, self.cache, 1.0, sources=self.sources(os.path.join(self.dir, "a"), os.path.join(self.dir, "b"))
        )
        self.assert_none(got, "tailscaled_not_found")

    def test_a_socket_nobody_listens_on_is_unreachable(self):
        """A leftover socket file is a failure to reach, not a missing install."""
        stale = os.path.join(self.dir, "stale")
        dead = socket.socket(socket.AF_UNIX)
        dead.bind(stale)
        dead.close()
        self.assert_none(read_directory(100.0, self.cache, 1.0, sources=self.sources(stale)), "tailscaled_unreachable")

    def test_server_never_answers_times_out(self):
        """A server that accepts and stays silent is cut off at the timeout."""
        path, _ = self.unix_api("s", lambda head: None)
        started = time.monotonic()
        got = read_directory(100.0, self.cache, 0.05, sources=self.sources(path))
        self.assertLess(time.monotonic() - started, 1.0)
        self.assert_none(got, "tailscaled_timeout")

    def test_a_slow_body_meets_the_total_deadline(self):
        """Bytes that keep arriving do not extend the budget: the whole read ends at the timeout."""

        def drip(head):
            """200 with a body that trickles out far longer than the budget."""
            return ("200 OK", (10_000, (time.sleep(0.02) or b"x" for _ in range(10_000))))

        path, _ = self.unix_api("s", drip)
        started = time.monotonic()
        got = read_directory(100.0, self.cache, 0.3, sources=self.sources(path))
        self.assertLess(time.monotonic() - started, 1.5)
        self.assert_none(got, "tailscaled_timeout")

    def test_two_hundred_with_non_json_body(self):
        """A 200 whose body is not JSON (the macOS CLI prints English there) is a bad answer, not an exception."""
        path, _ = self.unix_api("s", lambda head: ("200 OK", b"The Tailscale CLI failed to start"))
        self.assert_none(read_directory(100.0, self.cache, 1.0, sources=self.sources(path)), "tailscaled_bad_response")

    def test_two_hundred_with_json_that_is_not_a_status_object(self):
        """A JSON list or string is not a status document."""
        for body in (b"[]", b'"x"', b"null", b"\xff\xfe"):
            path, _ = self.unix_api("s%d" % len(self.apis), lambda head, body=body: ("200 OK", body))
            self.assert_none(
                read_directory(100.0, self.cache, 1.0, sources=self.sources(path)), "tailscaled_bad_response"
            )

    def test_deeply_nested_json_is_a_bad_answer(self):
        """About 200 KB of '[' is inside the body limit but past the parser's depth: RecursionError must not escape."""
        path, _ = self.unix_api("s", lambda head: ("200 OK", b"[" * 200_000))
        self.assert_none(read_directory(100.0, self.cache, 1.0, sources=self.sources(path)), "tailscaled_bad_response")

    def test_a_body_that_stalls_mid_read_is_cut_within_twice_the_timeout(self):
        """Headers and a few bytes, then silence: the per-read timeout ends it, inside the documented 2x bound."""
        gate = threading.Event()
        self.addCleanup(gate.set)

        def stall(head):
            """200 announcing 100 bytes, sending 3, then waiting."""
            return ("200 OK", (100, (x for x in (b"abc", gate.wait(5) and b""))))

        path, _ = self.unix_api("s", stall)
        started = time.monotonic()
        got = read_directory(100.0, self.cache, 0.3, sources=self.sources(path))
        self.assertLess(time.monotonic() - started, 0.3 * 2 + 0.3)
        self.assert_none(got, "tailscaled_timeout")

    def test_body_over_the_limit_stops_reading(self):
        """A body longer than the limit is refused without reading the rest of it."""

        def endless(head):
            """200 announcing 10 MB and sending it in 64 KB pieces."""
            pieces = (b"x" * 65536 for _ in range(160))
            return ("200 OK", (10_000_000, pieces))

        path, _ = self.unix_api("s", endless)
        got = read_directory(100.0, self.cache, 1.0, sources=self.sources(path, max_body=100_000))
        self.assert_none(got, "tailscaled_too_large")

    def test_backend_state_not_running(self):
        """A stopped or logged-out node has no trustworthy User map, so there is no list."""
        for state in ("Stopped", "NeedsLogin", "Starting", None):
            path, _ = self.unix_api("s%d" % len(self.apis), ok(status([user("a@example.com")], state)))
            self.assert_none(
                read_directory(100.0, self.cache, 1.0, sources=self.sources(path)), "tailscaled_not_running"
            )

    def test_http_401_and_403(self):
        """A refusal is reported as such and never read as a list."""
        for line in ("401 Unauthorized", "403 Forbidden"):
            path, _ = self.unix_api("s%d" % len(self.apis), lambda head, line=line: (line, b"denied"))
            self.assert_none(read_directory(100.0, self.cache, 1.0, sources=self.sources(path)), "tailscaled_refused")

    def test_other_statuses_are_a_bad_answer(self):
        """A 500 or a redirect is not a status document."""
        path, _ = self.unix_api("s", lambda head: ("500 Internal Server Error", b"{}"))
        self.assert_none(read_directory(100.0, self.cache, 1.0, sources=self.sources(path)), "tailscaled_bad_response")

    def test_two_runs_do_not_share_a_cached_directory(self):
        """Each run owns its cache: a second run inside the first one's window reads the daemon itself, and sees what
        the daemon says now rather than the first run's answer."""
        path, api = self.unix_api("s", ok(status([user("a@example.com")])))
        src = self.sources(path)
        mine, theirs = DirectoryCache(), DirectoryCache()
        read_directory(100.0, mine, 1.0, sources=src)
        read_directory(101.0, theirs, 1.0, sources=src)
        self.assertEqual(len(api.heads), 2)
        read_directory(102.0, mine, 1.0, sources=src)
        self.assertEqual(len(api.heads), 2)

    def test_a_failure_is_remembered_too(self):
        """A node that is down costs one attempt per cache window, not one per request."""
        path, api = self.unix_api("s", lambda head: ("403 Forbidden", b""))
        src = self.sources(path)
        read_directory(100.0, self.cache, 1.0, sources=src)
        read_directory(102.0, self.cache, 1.0, sources=src)
        self.assertEqual(len(api.heads), 1)


class MacTransport(ServerCase):
    """The macOS route: the port is the target name of a symlink, the token is in a file beside it, and the call is
    HTTP Basic with an empty user over TCP on the loopback."""

    def mac_api(self, behavior, token="0123456789abcdef0123", stale_port=None):
        """A TCP fake on 127.0.0.1 plus a folder laid out like /Library/Tailscale; returns (mac_dir, api)."""
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), socketserver.BaseRequestHandler)
        server.daemon_threads = True
        port = server.server_address[1]
        api = FakeApi(server, behavior)
        self.apis.append(api)
        mac = os.path.join(self.dir, "mac")
        os.makedirs(mac, exist_ok=True)
        os.symlink(str(stale_port or port), os.path.join(mac, "ipnport"))
        with open(os.path.join(mac, "sameuserproof-%d" % (stale_port or port)), "w", encoding="ascii") as f:
            f.write(token + "\n")
        return mac, api

    def test_reads_status_with_basic_auth_and_the_local_host(self):
        """The token is the Basic password with an empty user, and Host is still local-tailscaled.sock."""
        token = "0123456789abcdef0123"
        mac, api = self.mac_api(ok(status([user("mac@example.com", "Mac")])), token)
        got = read_directory(100.0, self.cache, 1.0, sources=self.sources(mac_dir=mac))
        self.assertEqual([x.login for x in got.users], ["mac@example.com"])
        lines = api.heads[0].split("\r\n")
        self.assertIn("Host: local-tailscaled.sock", lines)
        wanted = "Authorization: Basic " + base64.b64encode((":" + token).encode()).decode()
        self.assertIn(wanted, lines)
        names = [x.split(":", 1)[0].lower() for x in lines[1:] if ":" in x]
        self.assertNotIn("origin", names)
        self.assertNotIn("referer", names)

    def test_a_stale_port_is_an_ordinary_failure(self):
        """The files outlive the app: a port nobody listens on is 'unreachable', not an error."""
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
        probe.close()
        mac, _ = self.mac_api(ok(status([])), stale_port=dead_port)
        got = read_directory(100.0, self.cache, 1.0, sources=self.sources(mac_dir=mac))
        self.assertEqual((got.users, got.reason), ((), "tailscaled_unreachable"))

    def test_a_link_that_is_not_a_port_or_a_missing_token_is_a_failure(self):
        """A symlink naming something else, or a token file that is gone, never raises."""
        mac = os.path.join(self.dir, "mac")
        os.makedirs(mac)
        os.symlink("not-a-port", os.path.join(mac, "ipnport"))
        got = read_directory(100.0, self.cache, 1.0, sources=self.sources(mac_dir=mac))
        self.assertEqual((got.users, got.reason), ((), "tailscaled_unreachable"))
        os.unlink(os.path.join(mac, "ipnport"))
        os.symlink("41112", os.path.join(mac, "ipnport"))
        self.cache = DirectoryCache()
        got = read_directory(100.0, self.cache, 1.0, sources=self.sources(mac_dir=mac))
        self.assertEqual((got.users, got.reason), ((), "tailscaled_unreachable"))

    def test_a_non_ascii_digit_link_is_not_a_port(self):
        """'²' passes str.isdigit but not int(): it is a bad port, an unreachable answer, not an exception."""
        mac = os.path.join(self.dir, "mac")
        os.makedirs(mac)
        os.symlink("\u00b2", os.path.join(mac, "ipnport"))
        got = read_directory(100.0, self.cache, 1.0, sources=self.sources(mac_dir=mac))
        self.assertEqual((got.users, got.reason), ((), "tailscaled_unreachable"))

    def test_an_unreadable_token_file_is_unreachable(self):
        """A token file the service user may not read (mode 0640 root:admin on the real machine) is a failure."""
        mac, api = self.mac_api(ok(status([])))
        port = os.readlink(os.path.join(mac, "ipnport"))
        token = os.path.join(mac, "sameuserproof-" + port)
        os.chmod(token, 0)
        try:
            got = read_directory(100.0, self.cache, 1.0, sources=self.sources(mac_dir=mac))
        finally:
            os.chmod(token, 0o600)
        self.assertEqual((got.users, got.reason), ((), "tailscaled_unreachable"))
        self.assertEqual(api.heads, [])

    def test_a_token_that_fails_the_pattern_is_never_sent(self):
        """A token with spaces or too short is refused before any request, so it cannot reach a header."""
        for token in ("short", "has space in it 123456", "x" * 65, ""):
            mac, api = self.mac_api(ok(status([])), token=token)
            got = read_directory(100.0, DirectoryCache(), 1.0, sources=self.sources(mac_dir=mac))
            self.assertEqual((got.users, got.reason), ((), "tailscaled_unreachable"), token)
            self.assertEqual(api.heads, [])
            shutil.rmtree(mac)

    def test_the_unix_socket_is_preferred_when_it_exists(self):
        """Linux paths come first; the macOS files are looked at only when none of them answered."""
        path, _ = self.unix_api("s", ok(status([user("unix@example.com")])))
        mac, mac_api = self.mac_api(ok(status([user("mac@example.com")])))
        got = read_directory(100.0, self.cache, 1.0, sources=self.sources(path, mac_dir=mac))
        self.assertEqual([x.login for x in got.users], ["unix@example.com"])
        self.assertEqual(mac_api.heads, [])


if __name__ == "__main__":
    unittest.main()
