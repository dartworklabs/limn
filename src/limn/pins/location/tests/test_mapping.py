"""The pure box math behind a pin's mark: the PDF boxes SyncTeX gives for a range's lines, filtered, padded, merged
(mapping.line_boxes, range_pad, merge_boxes), and a range of today's file read back in the file a build read
(mapping.built_range).

Run: uv run pytest -q src/limn/pins/location/tests/test_mapping.py
"""

from limn.pins.location.mapping import BOX_LIMIT, built_range, line_boxes, merge_boxes, range_pad

PAGE_W, PAGE_H = 595.28, 841.89


def test_line_boxes_drops_page_body_boxes():
    # a page body box (full text width, most of the page height) and two text lines
    rows = [(1, 72.0, 100.0, 467.0, 548.0), (1, 72.0, 231.0, 228.6, 8.86), (1, 72.0, 243.0, 228.6, 8.86)]
    assert line_boxes(rows, 595.28, 841.89) == rows[1:]


def test_line_boxes_keeps_a_wide_short_box_and_a_tall_narrow_one():
    # only a box both wide and tall is the page or column body; a full-width table row or a tall margin note stays
    wide = (1, 72.0, 100.0, 467.0, 20.0)
    tall = (1, 72.0, 100.0, 50.0, 548.0)
    assert line_boxes([wide, tall], PAGE_W, PAGE_H) == [wide, tall]


def test_line_boxes_of_nothing_is_nothing():
    assert line_boxes([], PAGE_W, PAGE_H) == []


def test_range_pad_halves_the_blank_between_lines():
    rows = [(1, 72.0, 231.0, 228.6, 8.86), (1, 72.0, 242.96, 228.6, 8.86)]
    assert range_pad(rows) == 1.55


def test_range_pad_falls_back_to_a_share_of_the_line_height():
    assert range_pad([(1, 72.0, 231.0, 228.6, 12.75)]) == 2.23


def test_range_pad_ignores_the_gap_between_columns():
    # the second column's first line sits far above the first column's last: not a blank between lines
    rows = [(1, 72.0, 665.8, 228.6, 8.86), (1, 310.6, 127.9, 228.6, 8.86), (1, 310.6, 139.86, 228.6, 8.86)]
    assert range_pad(rows) == 1.55


def test_range_pad_follows_loose_line_spacing():
    # line spacing 1.8: boxes 8.86 high, 12.66 pt of blank between lines
    rows = [(1, 72.0, 231.0, 228.6, 8.86), (1, 72.0, 252.52, 228.6, 8.86)]
    assert range_pad(rows) == 6.33


def test_range_pad_follows_large_text():
    rows = [(1, 72.0, 231.0, 228.6, 21.0), (1, 72.0, 253.0, 228.6, 21.0)]
    assert range_pad(rows) == 0.50


def test_merge_boxes_joins_a_loosely_spaced_paragraph_into_one_piece():
    rows = [(1, 72.0, 100.0 + 21.52 * i, 228.6, 8.86) for i in range(10)]
    assert len(merge_boxes(rows, 6.33, PAGE_W, PAGE_H, 8)) == 1


def test_merge_boxes_joins_one_column_and_keeps_two():
    # first column's last line, then the second column's block
    rows = [(1, 72.0, 665.8, 228.6, 8.86), (1, 310.6, 127.9, 228.6, 8.86), (1, 310.6, 139.8, 228.6, 8.86)]
    out = merge_boxes(rows, 0.0, 595.28, 841.89, 8)
    assert len(out) == 2


def test_merge_boxes_joins_stacked_lines_into_one_box():
    rows = [(1, 72.0, 231.0, 228.6, 8.86), (1, 72.0, 242.96, 200.0, 8.86)]
    assert merge_boxes(rows, 0.0, PAGE_W, PAGE_H, 8) == [(1, 72.0, 231.0, 228.6, 20.82)]


def test_merge_boxes_keeps_pages_apart():
    rows = [(1, 72.0, 700.0, 228.6, 8.86), (2, 72.0, 100.0, 228.6, 8.86)]
    assert [b[0] for b in merge_boxes(rows, 0.0, 595.28, 841.89, 8)] == [1, 2]


def test_merge_boxes_clamps_padding_to_the_page():
    out = merge_boxes([(1, 72.0, 2.0, 228.6, 8.86)], 5.0, 595.28, 841.89, 8)
    assert out[0][2] == 0.0


def test_merge_boxes_gives_up_over_the_limit():
    rows = [(1, 72.0 + 30 * i, 100.0 + 30 * i, 20.0, 8.0) for i in range(9)]
    assert merge_boxes(rows, 0.0, 595.28, 841.89, 8) == []


def test_merge_boxes_answers_a_result_exactly_at_the_limit():
    rows = [(1, 72.0 + 30 * i, 100.0 + 30 * i, 20.0, 8.0) for i in range(8)]
    assert len(merge_boxes(rows, 0.0, PAGE_W, PAGE_H, 8)) == 8


def test_merge_boxes_of_nothing_is_nothing():
    assert merge_boxes([], 1.0, PAGE_W, PAGE_H, BOX_LIMIT) == []


def test_built_range_maps_todays_lines_back():
    built = ["a", "b", "c", "d"]
    now = ["x", "a", "b", "c", "d"]  # one line added at the top
    assert built_range(built, now, 2, 4) == (1, 3)


def test_built_range_is_none_when_the_text_moved_away():
    assert built_range(["a", "b"], ["q", "r"], 1, 2) is None


def test_built_range_is_none_when_a_line_of_the_range_is_gone():
    # a line edited inside the range: the build never saw today's text, so there is no box for the whole range
    assert built_range(["a", "b", "c"], ["a", "B", "c"], 1, 3) is None


def test_built_range_is_none_when_a_line_was_added_inside_the_range():
    # the range's lines pair, but not next to one another in the build
    assert built_range(["a", "b"], ["a", "new", "b"], 1, 3) is None
