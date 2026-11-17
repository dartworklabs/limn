"""The forward SyncTeX call reads the tool's records faithfully and answers nothing when the tool fails."""

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
