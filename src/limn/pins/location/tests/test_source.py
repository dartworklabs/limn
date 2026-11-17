"""The forward SyncTeX call reads the tool's records faithfully and answers nothing when the tool fails, the name it
selects a file by holds through a symlinked checkout, a page of no size is answered with no boxes, and a range that
opens and closes one environment is answered without asking its own \\begin and \\end lines."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from limn.pins.location import source
from limn.pins.location.mapping import BOX_LIMIT

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


# ---------------------------------------------------------------- A range that is its own environment
#
# Measured over 810 `synctex view` rows and 12 floats of a real manuscript: every box that lay outside the float came
# from the float's own \begin{figure|table} or \end{figure|table} line and nothing else, because those two lines have
# no box of their own and are answered through the tool's ancestor search. Not asking them took all 12 floats to
# exactly one piece each, none of them on a page the float does not print on.

A4 = ((595.28, 841.89), (595.28, 841.89))
# A float as a manuscript writes one. A pin inside a float defaults to this whole environment, so the range's first
# line opens it and its last line closes it (mapping.rung_ladder).
FLOAT = ["\\begin{table}", "cell one \\\\", "cell two \\\\", "cell three \\\\", "\\end{table}"]
# What the tool answers for those lines, in the measured shape: the rows print where the float prints (page 2) while
# the \begin and \end lines answer body lines of page 1, a page the float does not print on.
FLOAT_ROWS = {
    1: [(1, 56.69, 635.07, 481.89, 11.5)],
    2: [(2, 56.69, 100.0, 481.89, 11.5)],
    3: [(2, 56.69, 116.0, 481.89, 11.5)],
    4: [(2, 56.69, 132.0, 481.89, 11.5)],
    5: [(1, 56.69, 700.0, 481.89, 11.5)],
}
# The three rows as one piece: joined, grown by the 2.25 pt padding their 16 pt leading over 11.5 pt boxes gives.
THE_FLOAT = (54.44, 97.75, 486.39, 48.0)
# Three lines of a paragraph, 16 pt apart like the float's rows, so they answer the same one piece on page 1.
BODY_ROWS = {line: [(1, 56.69, 100.0 + 16.0 * (line - 1), 481.89, 11.5)] for line in (1, 2, 3)}
# Boxes no padding can join: three short boxes in three columns, far apart on one page.
SCATTER_ROWS = {2: [(1, 60.0, 100.0, 20.0, 8.0)], 3: [(1, 200.0, 300.0, 20.0, 8.0)], 4: [(1, 400.0, 500.0, 20.0, 8.0)]}
SCATTERED = ["\\begin{figure}", "Alpha.", "Beta.", "Gamma.", "\\end{figure}"]


def frac(x, y, w, h, page=A4[0]):
    """A box in points as boxes_for_range answers it: fractions of its own page."""
    page_w, page_h = page
    return (x / page_w, y / page_h, w / page_w, h / page_h)


def viewing(monkeypatch, rows):
    """Stub the forward pass with `rows` (line -> boxes) and answer the list the lines are recorded in."""
    calls = []

    def view(pdf, tex, line):
        """Record the line asked for and answer its boxes."""
        calls.append(line)
        return list(rows.get(line, ()))

    monkeypatch.setattr(source, "synctex_view", view)
    return calls


def for_range(lines, lo, hi, limit=BOX_LIMIT):
    """boxes_for_range over `lines` as both the built and today's file, on a build of two A4 pages."""
    return source.boxes_for_range(Path("main.pdf"), "main.tex", None, lines, lo, hi, A4, limit)


def test_an_environment_range_does_not_ask_its_own_begin_and_end_lines(monkeypatch):
    """The range opens `table` on its first line and closes it on its last, so those two are its own delimiters: they
    carry no box of their own and the tool answers them through its ancestor search, with whatever stands where the
    \\begin stood in the source stream. Only the lines between them are asked."""
    calls = viewing(monkeypatch, FLOAT_ROWS)
    for_range(FLOAT, 1, 5)
    assert calls == [2, 3, 4]


def test_an_environment_range_answers_no_piece_outside_the_environment(monkeypatch):
    """The same range as one piece, where the float prints. Asking the two delimiters would add the two body lines of
    page 1 they answer - a mark of three pieces, two of them on a page the float does not print on."""
    viewing(monkeypatch, FLOAT_ROWS)
    assert for_range(FLOAT, 1, 5) == ((2, pytest.approx(frac(*THE_FLOAT))),)


def test_a_range_inside_an_environment_asks_its_own_first_and_last_lines(monkeypatch):
    """The rule reads the range's own first and last line and never reaches outside it for an enclosing environment.
    A paragraph rung inside a float is the rows alone - compute_levels drops the \\begin and \\end lines from it - so
    its first and last line are rows, which are asked like any other, and it draws the float's own mark."""
    calls = viewing(monkeypatch, FLOAT_ROWS)
    pieces = for_range(FLOAT, 2, 4)
    assert calls == [2, 3, 4]
    assert pieces == ((2, pytest.approx(frac(*THE_FLOAT))),)


def test_a_range_that_does_not_close_what_it_opens_asks_every_line(monkeypatch):
    """Three ranges that are not an environment's own: one closing an environment other than the one it opens, one
    that opens an environment and never closes it (half a float, typed by hand into the range box), and one running
    from the end of a float to the start of the next. None has a pair of delimiters to drop, so each is asked for all
    of its lines and answers the mark of all of them."""
    for lines in (
        ["\\begin{figure}", "Alpha one.", "\\end{table}"],
        ["\\begin{figure}", "Alpha one.", "Beta two."],
        ["\\end{figure}", "Alpha one.", "\\begin{figure}"],
    ):
        calls = viewing(monkeypatch, BODY_ROWS)
        pieces = for_range(lines, 1, 3)
        assert calls == [1, 2, 3]
        assert pieces == ((1, pytest.approx(frac(*THE_FLOAT))),)


def test_a_range_of_delimiters_alone_answers_no_mark(monkeypatch):
    """An environment whose \\begin and \\end are all it has: dropping them leaves no line to ask, so the range gets
    no mark and the pin falls back to the rectangle that was dragged - the answer every box path gives when it has
    none. The two lines' own answer is the ancestor search's, which is what the rule exists to refuse."""
    calls = viewing(monkeypatch, FLOAT_ROWS)
    assert for_range(["\\begin{table}", "\\end{table}"], 1, 2) == ()
    assert calls == []


def test_a_one_line_environment_is_not_a_range_of_delimiters(monkeypatch):
    """A whole environment on one line is its own first and last line, but the line carries the content too: it is
    asked, because dropping it would leave the range with nothing and its boxes are the content's, not an ancestor's."""
    calls = viewing(monkeypatch, BODY_ROWS)
    assert for_range(["\\begin{figure}Alpha one.\\end{figure}"], 1, 1) != ()
    assert calls == [1]


def test_an_environment_range_gives_up_over_two_pieces(monkeypatch):
    """With the delimiters gone every float measured answers one piece, and a float that splits across a page break
    would answer two: more than two is scatter, and there the mark gives up rather than draw it. A body range keeps
    the wider limit of eight - the same three pieces are a mark for it."""
    viewing(monkeypatch, SCATTER_ROWS)
    assert for_range(SCATTERED, 1, 5) == ()
    assert len(for_range(SCATTERED, 2, 4)) == 3


def test_an_environment_range_answers_two_pieces(monkeypatch):
    """Two is the limit, not what it refuses: a float split across a page break still draws both of its pieces."""
    viewing(monkeypatch, {line: SCATTER_ROWS[line] for line in (2, 3)})
    assert len(for_range(SCATTERED, 1, 5)) == 2
