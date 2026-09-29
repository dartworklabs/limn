"""Checked manuscript reads reject path substitution without leaking file descriptors."""

import pytest

from limn.files import file_in_tree, tex_lines


def test_checked_file_refuses_leaf_symlink_substitution(tmp_path):
    """A checked regular file cannot later expose an outside secret through a symlink."""
    root = tmp_path / "manuscript"
    root.mkdir()
    source = root / "main.tex"
    source.write_text("safe\n", encoding="utf-8")
    secret = tmp_path / "secret"
    secret.write_text("secret\n", encoding="utf-8")
    checked = file_in_tree(str(source), root, tmp_path / "state")
    assert tex_lines(checked) == ["safe"]
    source.unlink()
    source.symlink_to(secret)
    assert tex_lines(checked) == []


def test_raw_path_cannot_reach_manuscript_read_sink(tmp_path):
    """A caller must acquire checked scope before reading even an existing regular path."""
    source = tmp_path / "secret"
    source.write_text("secret", encoding="utf-8")
    with pytest.raises(TypeError):
        tex_lines(source)


@pytest.mark.parametrize("replacement", ["outside", "hidden", "state"])
def test_directory_substitution_never_reads_excluded_content(tmp_path, replacement):
    """Replacing an ancestor after validation cannot redirect reads into excluded trees."""
    root = tmp_path / "manuscript"
    folder = root / "chapter"
    folder.mkdir(parents=True)
    source = folder / "main.tex"
    source.write_text("safe", encoding="utf-8")
    state = root / "state"
    target = {"outside": tmp_path / "outside", "hidden": root / ".hidden", "state": state}[replacement]
    target.mkdir()
    (target / "main.tex").write_text("secret", encoding="utf-8")
    checked = file_in_tree(str(source), root, state)
    source.unlink()
    folder.rmdir()
    folder.symlink_to(target, target_is_directory=True)
    for _ in range(20):
        assert tex_lines(checked) == []


def test_initial_internal_symlink_reads_canonical_file(tmp_path):
    """An initially safe link is resolved once; later link retargeting grants no new authority."""
    source = tmp_path / "main.tex"
    source.write_text("one\ntwo\n", encoding="utf-8")
    link = tmp_path / "alias.tex"
    link.symlink_to(source)
    checked = file_in_tree(str(link), tmp_path, tmp_path / "state")
    assert tex_lines(checked) == ["one", "two"]
    assert checked.snapshot()[1] == source.stat().st_mtime
    link.unlink()
    link.symlink_to("/etc/passwd")
    assert tex_lines(checked) == ["one", "two"]


def test_unreadable_or_removed_source_returns_empty_snapshot(tmp_path):
    """Invalid UTF-8 and deleted files preserve the nonthrowing source-read contract."""
    source = tmp_path / "main.tex"
    source.write_bytes(b"\xff")
    checked = file_in_tree(str(source), tmp_path, tmp_path / "state")
    assert checked.snapshot() == ([], 0.0)
    source.unlink()
    assert checked.snapshot() == ([], 0.0)


def test_checked_file_cannot_be_constructed_from_a_raw_path():
    """The public capability constructor cannot bless arbitrary filesystem authority."""
    from limn.files import ManuscriptFile

    with pytest.raises(TypeError):
        ManuscriptFile()


@pytest.mark.parametrize("ancestor", [False, True])
def test_symlink_swap_during_open_is_refused(tmp_path, monkeypatch, ancestor):
    """No-follow opens stop a swap after policy checks but before the actual OS open."""
    from limn import files

    root = tmp_path / "manuscript"
    folder = root / "chapter"
    folder.mkdir(parents=True)
    source = folder / "main.tex"
    source.write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "main.tex").write_text("secret", encoding="utf-8")
    checked = file_in_tree(str(source), root, tmp_path / "state")
    original_open = files.os.open
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        """Replace one real filesystem entry precisely at the OS adapter boundary."""
        nonlocal swapped
        if not swapped and path == ("chapter" if ancestor else "main.tex"):
            swapped = True
            source.unlink()
            if ancestor:
                folder.rmdir()
                folder.symlink_to(outside, target_is_directory=True)
            else:
                source.symlink_to(outside / "main.tex")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(files.os, "open", swap_then_open)
    assert tex_lines(checked) == []
    assert swapped


def test_read_and_stat_close_every_descriptor(tmp_path, monkeypatch):
    """Success and read failure both release directory and source descriptors immediately."""
    from limn import files

    source = tmp_path / "main.tex"
    source.write_text("safe", encoding="utf-8")
    checked = file_in_tree(str(source), tmp_path, tmp_path / "state")
    original_open = files.os.open
    opened = []

    def remember_open(*args, **kwargs):
        """Observe real OS descriptors to verify their lifetime after the sink returns."""
        descriptor = original_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(files.os, "open", remember_open)
    assert tex_lines(checked) == ["safe"]
    assert checked.metadata().st_size == 4
    source.write_bytes(b"\xff")
    assert tex_lines(checked) == []
    for descriptor in opened:
        with pytest.raises(OSError):
            files.os.fstat(descriptor)


def test_only_checked_factory_constructs_capabilities():
    """Python's constructor seal is backed by a source guard against bypass constructors."""
    import ast
    from pathlib import Path

    root = Path(__file__).parents[1] / "src" / "limn"
    for path in root.rglob("*.py"):
        if path.name.startswith("test_") or path == root / "files.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            assert not (isinstance(node.func, ast.Name) and node.func.id == "ManuscriptFile"), (
                f"{path}:{node.lineno}: use file_in_tree"
            )
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"__new__", "__setattr__"}:
                assert not any(isinstance(arg, ast.Name) and arg.id == "ManuscriptFile" for arg in node.args), (
                    f"{path}:{node.lineno}: do not bypass checked construction"
                )
