"""Keep atomic state-file replacement clean and private on success and failure."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from limn import files


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
