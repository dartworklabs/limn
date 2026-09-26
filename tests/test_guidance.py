"""limn.guidance - the token-file wording agents read, tested directly with paths and flags, no files or server.

The HTTP side (the 401 a headerless local request gets with the loopback agent off, the pins.md agent-auth line) is
pinned in test_token_file.py and test_errors.py; here the strings are checked on their own (coding rule R1). The
module's import purity is checked in test_pins_lifecycle.py with the other text modules pins.md uses.

Run: uv run pytest -q tests/test_guidance.py
"""
import unittest
from pathlib import PurePosixPath

from limn.guidance import TOKEN_FILE_EXAMPLE, UNAUTHENTICATED, loopback_refused_text, shell_path, token_file_curl

HOME = PurePosixPath("/home/u")


class ShellPath(unittest.TestCase):
    """shell_path: one shell word, ~/ only for a plain rest under home."""

    def test_tilde_quoted_or_plain(self):
        """Under home and plain: ~/rest. Outside home: the path. A space: quoted. No home: the absolute path."""
        self.assertEqual(shell_path(HOME / ".config/limn/p.token", HOME), "~/.config/limn/p.token")
        self.assertEqual(shell_path(PurePosixPath("/srv/p.token"), HOME), "/srv/p.token")
        self.assertEqual(shell_path(HOME / "my dir/p.token", HOME), "'/home/u/my dir/p.token'")
        self.assertEqual(shell_path(HOME / "p.token", None), "/home/u/p.token")


class LoopbackRefused(unittest.TestCase):
    """The 401 text: the v0.2 text first, then where this machine's agent finds its token."""

    def test_known_existing_file(self):
        """The server's own file that exists: the curl form with its shell path and no creation hint."""
        text = loopback_refused_text(HOME / ".config/limn/paper.token", True, HOME)
        self.assertTrue(text.startswith(UNAUTHENTICATED + " "))
        self.assertTrue(text.endswith(token_file_curl("~/.config/limn/paper.token")))

    def test_known_missing_file_names_the_instance(self):
        """A missing file adds how the owner makes it, named after the file's stem."""
        text = loopback_refused_text(HOME / ".config/limn/paper.token", False, HOME)
        self.assertTrue(text.endswith(" 파일이 없으면 소유자가 `limn token create paper --save` 로 만듭니다."))

    def test_unknown_file_shows_the_convention(self):
        """No file configured: the conventional path and a placeholder instance name."""
        text = loopback_refused_text(None, False, HOME)
        self.assertIn(token_file_curl(TOKEN_FILE_EXAMPLE), text)
        self.assertIn("`limn token create <인스턴스> --save`", text)

    def test_curl_names_the_file_and_never_a_token(self):
        """The curl form reads the file at call time through $(cat ...)."""
        self.assertEqual(token_file_curl("~/t"), "`curl -H \"Authorization: Bearer $(cat ~/t)\" …`")


if __name__ == "__main__":
    unittest.main()
