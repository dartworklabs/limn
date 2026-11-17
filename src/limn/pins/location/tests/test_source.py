"""The forward SyncTeX call reads the tool's records faithfully and answers nothing when the tool fails, the name it
selects a file by holds through a symlinked checkout, and a page of no size is answered with no boxes."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from limn.pins.location import source

SAMPLE = "Output:x.pdf\nPage:2\nx:144.0\ny:218.4\nh:72.0\nv:220.4\nW:228.6\nH:8.86\n"

# Captured from the real `synctex view` (version 1.5) for one body line of a two-column article.
# The Output path is shortened; the line order, field order and trailing lines are as printed.
REAL = """This is SyncTeX command line utility, version 1.5
SyncTeX result begin
Output:/tmp/main.pdf
Page:1
x:112.404106
y:421.644287
h:71.999985
v:423.581451
W:228.642578
H:8.855677
before:
offset:-1
middle:
after:
Output:/tmp/main.pdf
Page:1
x:91.676262
y:433.599457
h:71.999985
v:435.536621
W:228.642578
H:8.855677
before:
offset:-1
middle:
after:
SyncTeX result end
"""


def stub_output(monkeypatch, stdout):
    monkeypatch.setattr(source.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=stdout))


def test_synctex_view_reads_page_and_box(monkeypatch):
    stub_output(monkeypatch, SAMPLE)
    assert source.synctex_view(Path("x.pdf"), "x.tex", 30) == [(2, 72.0, 211.54, 228.6, 8.86)]


def test_synctex_view_is_empty_when_the_tool_is_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(source.subprocess, "run", boom)
    assert source.synctex_view(Path("x.pdf"), "x.tex", 30) == []


def test_synctex_view_is_empty_when_the_tool_times_out(monkeypatch):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired("synctex", 10)

    monkeypatch.setattr(source.subprocess, "run", slow)
    assert source.synctex_view(Path("x.pdf"), "x.tex", 30) == []


def test_synctex_view_returns_real_records_in_printed_order_with_top_edge(monkeypatch):
    stub_output(monkeypatch, REAL)
    boxes = source.synctex_view(Path("main.pdf"), "main.tex", 7)
    assert boxes == [
        (1, 71.999985, pytest.approx(414.725774), 228.642578, 8.855677),
        (1, 71.999985, pytest.approx(426.680944), 228.642578, 8.855677),
    ]
    assert boxes[0][2] < boxes[1][2]


def test_synctex_view_keeps_records_out_of_document_order(monkeypatch):
    later_first = REAL.replace("v:423.581451", "v:999.0", 1)
    stub_output(monkeypatch, later_first)
    ys = [b[2] for b in source.synctex_view(Path("main.pdf"), "main.tex", 7)]
    assert ys == pytest.approx([990.144323, 426.680944])


def test_synctex_view_is_empty_for_a_line_with_no_boxes(monkeypatch):
    stub_output(
        monkeypatch, "This is SyncTeX command line utility, version 1.5\nSyncTeX result begin\nSyncTeX result end\n"
    )
    assert source.synctex_view(Path("main.pdf"), "main.tex", 3) == []


def test_synctex_view_skips_a_record_missing_a_field_and_keeps_its_neighbour(monkeypatch):
    broken = "Output:x.pdf\nPage:1\nx:1\ny:2\nh:72.0\nv:100.0\nW:50.0\n"  # no H
    stub_output(monkeypatch, broken + SAMPLE)
    assert source.synctex_view(Path("x.pdf"), "x.tex", 30) == [(2, 72.0, 211.54, 228.6, 8.86)]


def test_synctex_view_skips_a_record_with_an_unparsable_number(monkeypatch):
    broken = "Output:x.pdf\nPage:1\nh:72.0\nv:oops\nW:50.0\nH:8.0\n"
    stub_output(monkeypatch, broken + SAMPLE)
    assert source.synctex_view(Path("x.pdf"), "x.tex", 30) == [(2, 72.0, 211.54, 228.6, 8.86)]


def test_build_copy_name_is_the_file_inside_the_build_copy(tmp_path):
    """A file below the build root is selected by its path inside the copy, which is the name the build recorded."""
    src, build = tmp_path / "ms", tmp_path / "state" / "build"
    (src / "sections").mkdir(parents=True)
    file = src / "sections" / "part.tex"
    file.write_text("x", encoding="utf-8")
    assert source.build_copy_name(build, src, file) == str(build / "sections" / "part.tex")


def test_build_copy_name_reaches_through_a_symlinked_checkout(tmp_path):
    """The build root as the run registered it may be a link to where the files are (a temporary folder under
    macOS's /var -> /private/var): both sides of the prefix test are resolved, so the name SyncTeX knows is still
    found. Without that the file falls back to its checkout path, SyncTeX is asked for a name no build recorded, and
    the mark vanishes with no signal while the pick itself still answers lines."""
    real, build = tmp_path / "real", tmp_path / "state" / "build"
    (real / "sections").mkdir(parents=True)
    file = real / "sections" / "part.tex"
    file.write_text("x", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(real)
    assert source.build_copy_name(build, link, file) == str(build / "sections" / "part.tex")
    assert source.build_copy_name(build, real, link / "sections" / "part.tex") == str(build / "sections" / "part.tex")


def test_build_copy_name_falls_back_to_the_checkout_path_outside_the_build_root(tmp_path):
    """The copy holds the build root's tree, so a file beside that root has no name in it: the checkout path is the
    closest name there is, and losing a mark is a smaller cost than failing the pick."""
    src, build = tmp_path / "ms", tmp_path / "state" / "build"
    src.mkdir(parents=True)
    beside = tmp_path / "shared.tex"
    beside.write_text("x", encoding="utf-8")
    assert source.build_copy_name(build, src, beside) == str(beside)


def test_boxes_for_range_answers_nothing_when_no_page_has_a_size(monkeypatch):
    """A page width or height of zero means a broken page list, not a mark to draw: every other box path fails soft,
    so a build whose pages all read that way answers no boxes instead of dividing - and spawns no process to do it."""
    calls = []
    monkeypatch.setattr(source, "synctex_view", lambda *a: calls.append(a) or [])
    for pages in ([(0.0, 800.0)], [(600.0, 0.0)], [(-1.0, 800.0)], []):
        assert source.boxes_for_range(Path("main.pdf"), "main.tex", None, ["text"], 1, 1, pages, 8) == ()
    assert calls == []


def test_boxes_for_range_drops_the_boxes_of_a_page_it_has_no_size_for(monkeypatch):
    """SyncTeX names a page the page list does not size - a .synctex.gz older than the page images, a manifest that
    sized a page at zero: those boxes cannot become fractions of anything, so they are left out while the pages that
    do have a size still answer."""
    rows = [(1, 10.0, 20.0, 30.0, 10.0), (2, 10.0, 20.0, 30.0, 10.0), (3, 10.0, 20.0, 30.0, 10.0)]
    monkeypatch.setattr(source, "synctex_view", lambda *a: rows)
    pieces = source.boxes_for_range(Path("main.pdf"), "main.tex", None, ["text"], 1, 1, [(100.0, 100.0), (0.0, 0.0)], 8)
    assert [page for page, _ in pieces] == [1]
