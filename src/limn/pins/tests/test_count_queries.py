"""Pin count polling uses the pin owner's revision token rather than storage layout."""

import os

from limn.pins import application


def test_change_token_is_stable_until_live_file_changes(tmp_path):
    """Unchanged bytes need no refetch; creating and replacing live pins changes the token."""
    assert hasattr(application, "change_token"), "documents still owns pins.jsonl metadata"
    path = tmp_path / "pins.jsonl"
    assert application.change_token(path) == "0"
    path.write_text('{"id":1}\n')
    before = application.change_token(path)
    assert application.change_token(path) == before
    replacement = tmp_path / "replacement"
    replacement.write_text('{"id":2}\n')
    replacement.replace(path)
    assert application.change_token(path) != before


def test_change_token_sees_a_replace_in_the_same_timestamp_tick(tmp_path):
    """A same-size replace that lands in the first write's timestamp tick still changes the token (issue #121)."""
    path = tmp_path / "pins.jsonl"
    path.write_text('{"id":1}\n')
    first = path.stat()
    before = application.change_token(path)
    replacement = tmp_path / "replacement"
    replacement.write_text('{"id":2}\n')
    os.utime(replacement, ns=(first.st_atime_ns, first.st_mtime_ns))
    replacement.replace(path)
    after = path.stat()
    assert (after.st_mtime_ns, after.st_size) == (first.st_mtime_ns, first.st_size), "the case must be the same tick"
    assert application.change_token(path) != before
