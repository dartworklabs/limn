"""access.json: the instance access flag's read, stored text and write."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from limn.security.access_store import access_text, read_access, write_access


class StateCase(unittest.TestCase):
    """A test with a fresh state folder in self.state; self.put writes access.json there."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        self.path = self.state / "access.json"

    def put(self, body):
        """Write body (str or bytes) as access.json and return its path."""
        if isinstance(body, bytes):
            self.path.write_bytes(body)
        else:
            self.path.write_text(body, encoding="utf-8")
        return self.path

    def assert_unusable(self, body):
        """access.json holding body reads as unusable, with a reason naming the file."""
        got = read_access(self.put(body))
        self.assertEqual(got.managed, "unusable", body)
        self.assertIn("access.json", got.reason or "", body)
        self.assertEqual((got.at, got.by), (None, None))


class ReadAccess(StateCase):
    """read_access: absent, on, off and every shape of unusable file."""

    def test_absent_file_is_not_managed(self):
        got = read_access(self.path)
        self.assertEqual((got.managed, got.at, got.by, got.reason), ("not-managed", None, None, None))

    def test_managed_true(self):
        body = {"version": 1, "managed": True, "managed_at": "2026-11-22 09:00:00", "managed_by": "alice@example.com"}
        got = read_access(self.put(json.dumps(body)))
        self.assertEqual(
            (got.managed, got.at, got.by, got.reason),
            ("managed", "2026-11-22 09:00:00", "alice@example.com", None),
        )

    def test_managed_false(self):
        got = read_access(self.put('{"version":1,"managed":false}'))
        self.assertEqual((got.managed, got.reason), ("not-managed", None))

    def test_unknown_version_is_unusable(self):
        self.assert_unusable('{"version":2,"managed":true}')

    def test_managed_not_bool_is_unusable(self):
        for value in ('"true"', "1", "null"):
            with self.subTest(value=value):
                self.assert_unusable('{"version":1,"managed":%s}' % value)

    def test_broken_json_is_unusable(self):
        for body in (b'{"version":1,"man', b"", b"\xff\xfe\x00"):
            with self.subTest(body=body):
                self.assert_unusable(body)

    def test_not_an_object_is_unusable(self):
        for body in ("[]", '"x"'):
            with self.subTest(body=body):
                self.assert_unusable(body)

    def test_deeply_nested_json_is_unusable(self):
        """200,000 nested brackets are past the parser's depth: the RecursionError must not escape the read, which
        every header request makes (it would answer 500 internal instead of 403 access_unreadable)."""
        self.assert_unusable("[" * 200_000 + "]" * 200_000)

    @unittest.skipIf(os.geteuid() == 0, "root ignores file modes")
    def test_unreadable_file_is_unusable(self):
        self.put('{"version":1,"managed":true}')
        self.path.chmod(0o000)
        self.addCleanup(self.path.chmod, 0o600)
        got = read_access(self.path)
        self.assertEqual(got.managed, "unusable")
        self.assertIn("access.json", got.reason or "")


class WriteAccess(StateCase):
    """write_access and access_text: round trip, file mode and stored text."""

    def test_write_then_read_round_trips(self):
        write_access(self.path, True, "2026-11-22 09:00:00", "alice@example.com")
        got = read_access(self.path)
        self.assertEqual((got.managed, got.at, got.by), ("managed", "2026-11-22 09:00:00", "alice@example.com"))
        write_access(self.path, False, "2026-11-23 10:00:00", "bob@example.com")
        got = read_access(self.path)
        self.assertEqual((got.managed, got.at, got.by), ("not-managed", "2026-11-23 10:00:00", "bob@example.com"))

    def test_mode_is_0600(self):
        write_access(self.path, True, "2026-11-22 09:00:00", "alice@example.com")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_text_ends_with_newline(self):
        text = access_text(True, "2026-11-22 09:00:00", "alice@example.com")
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(
            json.loads(text),
            {"version": 1, "managed": True, "managed_at": "2026-11-22 09:00:00", "managed_by": "alice@example.com"},
        )
