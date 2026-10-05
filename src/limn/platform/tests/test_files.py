"""Keep atomic state-file replacement clean and private on success and failure, and let the bundled-library name
guard (vendor_file) answer only a file of its folder with an admitted suffix."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hypothesis import given, settings, strategies as st

from limn.platform import files


class AtomicWrite(unittest.TestCase):
    """A failed write leaves the old state file intact and no partial temporary file behind."""

    def setUp(self):
        """Create a private state directory and an existing file to protect during replacement."""
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "tokens.json"
        self.path.write_text("old", encoding="utf-8")

    def tearDown(self):
        """Remove the temporary state directory."""
        self.tmp.cleanup()

    def test_fsync_failure_closes_descriptor_and_removes_partial_file(self):
        """An fsync error propagates while the original survives and the secret temp file is removed."""
        descriptors = []

        def fail_fsync(fd):
            """Capture the descriptor passed to fsync before simulating a storage failure."""
            descriptors.append(fd)
            raise OSError("fsync failed")

        with (
            mock.patch.object(files.os, "fsync", side_effect=fail_fsync),
            self.assertRaisesRegex(OSError, "fsync failed"),
        ):
            files.atomic_write(self.path, "new secret", mode=0o600)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(self.path.parent.glob(".tokens.json.tmp*")), [])
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

    def test_replace_failure_preserves_original_and_temporary_file_mode(self):
        """A replacement error propagates after a private temp write and leaves no temp file."""
        observed = []

        def fail_replace(src, dst):
            """Observe the completed temp file before simulating a failed atomic replacement."""
            temp = Path(src)
            observed.append((temp.read_text(encoding="utf-8"), temp.stat().st_mode & 0o777, Path(dst)))
            raise OSError("replace failed")

        with (
            mock.patch.object(files.os, "replace", side_effect=fail_replace),
            self.assertRaisesRegex(OSError, "replace failed"),
        ):
            files.atomic_write(self.path, "new secret", mode=0o600)
        self.assertEqual(observed, [("new secret", 0o600, self.path)])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(self.path.parent.glob(".tokens.json.tmp*")), [])

    def test_success_replaces_content_with_requested_private_mode(self):
        """A successful replacement writes the requested bytes at mode 0600."""
        files.atomic_write(self.path, "new secret\n", mode=0o600)
        self.assertEqual(self.path.read_bytes(), b"new secret\n")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_chmod_failure_closes_unwrapped_descriptor(self):
        """An error before the fd becomes a file object still closes it and removes its temp file."""
        descriptors = []

        def fail_chmod(fd, mode):
            """Capture the private temporary descriptor before simulating a mode-setting error."""
            descriptors.append(fd)
            raise OSError("chmod failed")

        with (
            mock.patch.object(files.os, "fchmod", side_effect=fail_chmod),
            self.assertRaisesRegex(OSError, "chmod failed"),
        ):
            files.atomic_write(self.path, "new secret", mode=0o600)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(self.path.parent.glob(".tokens.json.tmp*")), [])
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])


# A bundled library's folder for VendorLeafNames: two files it serves, a record it does not, a slice under a subfolder, a
# link to a served file beside it, a link to a file outside the folder and a link to the record; and a file beside the folder.
FONT_SUFFIXES = (".woff2", ".css")
NAME_PARTS = st.sampled_from(
    ["a", "b", "x", "font", ".", "..", "/", "%2e", "%2f", "\\", "woff2", "css", "md", "-", "_", " ", "\x00"]
)


def library(root: Path) -> Path:
    """Make the folder and its neighbours under root; return the folder."""
    base = root / "lib"
    (base / "sub").mkdir(parents=True)
    (base / "a.woff2").write_bytes(b"wOF2")
    (base / "font.css").write_text("@font-face{}", encoding="utf-8")
    (base / "README.md").write_text("record", encoding="utf-8")
    (base / "sub" / "b.woff2").write_bytes(b"wOF2")
    (root / "secret.css").write_text("secret", encoding="utf-8")
    (base / "same.woff2").symlink_to(base / "a.woff2")
    (base / "out.css").symlink_to(root / "secret.css")
    (base / "record.css").symlink_to(base / "README.md")
    return base


class VendorLeafNames(unittest.TestCase):
    """vendor_file(base, name, suffixes) is the name guard of GET /vendor/<library>/<name>: a request's name is either
    one regular file directly in base whose real name ends in an admitted suffix, or None."""

    def setUp(self):
        """A library folder (library()) in a fresh temporary directory."""
        self.tmp = tempfile.TemporaryDirectory()
        self.base = library(Path(self.tmp.name))

    def tearDown(self):
        """Remove the temporary directory."""
        self.tmp.cleanup()

    def test_a_leaf_name_with_an_admitted_suffix_is_its_file(self):
        """The served files by their names, and a link to one of them inside the folder, are that file."""
        for name, want in (("a.woff2", "a.woff2"), ("font.css", "font.css"), ("same.woff2", "a.woff2")):
            with self.subTest(name=name):
                self.assertEqual(files.vendor_file(self.base, name, FONT_SUFFIXES), self.base / want)

    def test_every_other_name_is_none(self):
        """A suffix not admitted (the record, a .mjs asked of the font folder), a subpath, a path out of the folder, an
        encoded name, a link out of the folder or to a record, a missing file or folder, and a non-string are None."""
        for name in (
            "README.md",
            "a.woff2.md",
            "sub/b.woff2",
            "../secret.css",
            "..%2fsecret.css",
            "%61.woff2",
            ".font.css",
            "out.css",
            "record.css",
            "missing.css",
            "font.CSS",
            "",
            None,
            b"a.woff2",
        ):
            with self.subTest(name=name):
                self.assertIsNone(files.vendor_file(self.base, name, FONT_SUFFIXES))
        self.assertIsNone(files.vendor_file(self.base, "a.woff2", (".mjs",)))
        self.assertIsNone(files.vendor_file(self.base / "nowhere", "a.woff2", FONT_SUFFIXES))

    @settings(max_examples=300, deadline=None)
    @given(st.lists(NAME_PARTS, max_size=6).map("".join) | st.text(max_size=24))
    def test_any_name_is_a_served_file_of_the_folder_or_none(self, name):
        """Whatever the name, the answer is None or a regular file whose parent is the folder itself and whose real
        suffix is admitted - never a file in a subfolder, outside the folder or with another suffix."""
        got = files.vendor_file(self.base, name, FONT_SUFFIXES)
        if got is not None:
            self.assertEqual(got.parent, self.base.resolve())
            self.assertIn(got.suffix, FONT_SUFFIXES)
            self.assertTrue(got.is_file())
            self.assertNotIn("/", name)
