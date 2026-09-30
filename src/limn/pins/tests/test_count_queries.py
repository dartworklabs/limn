"""Pin count polling uses the pin owner's revision token rather than storage layout."""

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
