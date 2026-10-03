"""File-identity fixtures: a second version of a file that lands in the first version's timestamp tick.

A watch that tells two versions of a file apart by (mtime_ns, size) cannot see a rewrite of the same size that lands in
the same filesystem timestamp tick. Under load that happens by itself; these helpers make it happen on purpose
(os.utime), the way the pin change token's test does (issue #121), and prove the case they claim: each helper checks that
the second version has the first one's mtime_ns and size, and that its inode is new (an atomic replacement) or the
same (an overwrite in place). Test modules import fixtures only from helpers modules, never from one another.
"""

import os
from pathlib import Path


def replace_in_same_tick(path: Path, raw: bytes) -> None:
    """Replace the file at path atomically (write a sibling, rename it over) with raw, which must be as long as the file
    is, stamped with the old version's modification time. Afterwards path has the old (mtime_ns, size) and a new inode:
    what an editor or exporter that writes a temporary file and renames it leaves behind."""
    before = path.stat()
    if len(raw) != before.st_size:
        raise ValueError("the second version must have the first one's size: %d != %d" % (len(raw), before.st_size))
    sibling = path.with_name(path.name + ".new")
    sibling.write_bytes(raw)
    os.utime(sibling, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(sibling, path)
    after = path.stat()
    if (after.st_mtime_ns, after.st_size) != (before.st_mtime_ns, before.st_size) or after.st_ino == before.st_ino:
        raise AssertionError("the replacement must keep mtime_ns and size and change the inode")


def rewrite_in_place(path: Path, raw: bytes) -> None:
    """Overwrite the file at path in place (truncate, then write: the same inode) with raw, which must be as long as the
    file is, and restore the old version's modification time. Afterwards path has the old (mtime_ns, size, inode):
    what a copy over the file leaves behind."""
    before = path.stat()
    if len(raw) != before.st_size:
        raise ValueError("the second version must have the first one's size: %d != %d" % (len(raw), before.st_size))
    path.write_bytes(raw)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = path.stat()
    if (after.st_mtime_ns, after.st_size, after.st_ino) != (before.st_mtime_ns, before.st_size, before.st_ino):
        raise AssertionError("the rewrite must keep mtime_ns, size and inode")
