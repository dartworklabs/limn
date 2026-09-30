"""Ambiguous HTTP input is refused before attribution or feature side effects."""

import json

from helpers import Base, ps, req, set_config, split_resp
from helpers_access import BOB, member_add


class RequestBoundary(Base):
    """Real socket requests expose parsing failures and leave instance files unchanged."""

    def state_files(self):
        """Snapshot persistent bytes so rejected requests cannot hide attribution writes."""
        return {p.relative_to(ps.APP.C.state): p.read_bytes() for p in ps.APP.C.state.rglob("*") if p.is_file()}

    def assert_rejected(self, raw, reason, status=400):
        """The request and an appended valid write produce one refusal and no writes."""
        before = self.state_files()
        trailing = req(
            "POST",
            "/api/pin",
            json.dumps({"file": str(self.main), "lo": 4, "hi": 5}).encode(),
            {"Content-Type": "application/json"},
        )
        response = self.talk(raw + trailing)
        code, headers, body = split_resp(response)
        self.assertEqual((code, json.loads(body)["reason"]), (status, reason))
        self.assertEqual(headers["connection"], "close")
        self.assertEqual(response.count(b"HTTP/1.1 "), 1)
        self.assertEqual(self.state_files(), before)

    def test_json_ambiguity_never_records_a_person(self):
        """Duplicate nested/escaped keys and nonstandard constants do not update people."""
        for body in (
            b'{"note":"a","note":"b"}',
            b'{"x":{"a":1,"\\u0061":2}}',
            b'{"x":NaN}',
            b'{"x":1e999}',
            b'{"x":"\\ud800"}',
        ):
            with self.subTest(body=body):
                self.assert_rejected(
                    req("POST", "/api/pin", body, {**BOB, "Content-Type": "application/json"}), "bad_json"
                )

    def test_every_dispatch_shape_checks_query_before_writes(self):
        """GET, document POST, pin action and other POST share the strict query boundary."""
        for method, path in (
            ("GET", "/api/pins"),
            ("POST", "/api/pin"),
            ("POST", "/api/pins/1/close"),
            ("POST", "/api/clear"),
        ):
            set_config(auth="local", local_user="owner")
            for query in ("doc=a&doc=a", "doc=&doc=a", "doc=a&%64oc=b", "doc=%ff", "doc=%"):
                with self.subTest(method=method, path=path, query=query):
                    self.assert_rejected(req(method, path + "?" + query), "bad_query")

    def test_singleton_security_headers_reject_identical_or_conflicting_values(self):
        """Header case and equal values cannot evade singleton framing/identity checks."""
        values = {
            "Host": "127.0.0.1:18999",
            "Origin": "http://localhost",
            "Content-Type": "application/json",
            "Tailscale-User-Login": "bob@example.com",
            "Tailscale-User-Name": "Bob",
            "Tailscale-User-Profile-Pic": "https://example.com/p.png",
            "Content-Length": "0",
            "Authorization": "Basic YTpi",
        }
        for name, value in values.items():
            for second in (value, "different"):
                with self.subTest(name=name, second=second):
                    head = "GET /api/pins HTTP/1.1\r\n"
                    if name != "Host":
                        head += "Host: localhost\r\n"
                    head += f"{name}: {value}\r\n{name.lower()}: {second}\r\n\r\n"
                    reason = (
                        "bad_content_length"
                        if name == "Content-Length"
                        else "bad_bearer"
                        if name == "Authorization"
                        else "duplicate_header"
                    )
                    self.assert_rejected(head.encode(), reason, 401 if name == "Authorization" else 400)

    def test_configured_proxy_identity_headers_are_singletons(self):
        """Custom trusted-proxy user/name/email names receive the same ambiguity guard."""
        set_config(
            auth="trusted-proxy", proxy_user_header="X-Account", proxy_name_header="X-Name", proxy_email_header="X-Mail"
        )
        for name in ("X-Account", "X-Name", "X-Mail"):
            with self.subTest(name=name):
                raw = f"GET /api/pins HTTP/1.1\r\nHost: localhost\r\n{name}: a\r\n{name}: b\r\n\r\n".encode()
                self.assert_rejected(raw, "duplicate_header")

    def test_viewer_role_refusal_precedes_json_and_query_errors(self):
        """A viewer still gets the existing role refusal before malformed write payloads."""
        member_add(ps.APP.C.state, "bob@example.com", "viewer")
        self.assert_rejected(
            req("POST", "/api/pin?doc=a&doc=b", b"{", {**BOB, "Content-Type": "application/json"}), "viewer_only", 403
        )

    def test_malformed_html_query_still_renders_a_complete_error_page(self):
        """Error localization does not rethrow the invalid query it is reporting."""
        code, headers, body = split_resp(self.talk(req("GET", "/?lang=%ff", headers={"Accept": "text/html"})))
        self.assertEqual(code, 400)
        self.assertIn("text/html", headers["content-type"])
        self.assertIn(b"</html>", body)

    def test_raw_non_ascii_query_bytes_are_rejected_before_writes(self):
        """A URI query must percent-encode Unicode; Latin-1 request decoding cannot bless invalid UTF-8."""
        raw = b"GET /api/pins?unknown=\xff HTTP/1.1\r\nHost: localhost\r\n\r\n"
        self.assert_rejected(raw, "bad_query")

    def test_content_length_with_thousands_of_digits_is_bounded_without_conversion(self):
        """Oversized decimal framing returns 413 rather than a Python integer-conversion failure."""
        raw = b"POST /api/pin HTTP/1.1\r\nHost: localhost\r\nContent-Length: " + b"9" * 5000 + b"\r\n\r\n"
        self.assert_rejected(raw, "body_too_large", 413)

    def test_zero_padded_content_length_preserves_normal_requests(self):
        """Thousands of insignificant zeros remain legal for zero or a small complete body."""
        for number, body in ((b"0", b""), (b"2", b"{}")):
            raw = (
                b"GET /api/pins HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: "
                + b"0" * 5000
                + number
                + b"\r\n\r\n"
                + body
            )
            with self.subTest(number=number):
                code, _, payload = split_resp(self.talk(raw))
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(payload), [])
