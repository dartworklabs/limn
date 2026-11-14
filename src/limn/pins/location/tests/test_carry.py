"""A range of the lines a build was made from, carried over to the file as it is now (mapping.carry_range).

SyncTeX of a build numbers the lines of the source that build read. A pick against a build whose source was edited
since must answer where that text stands now, or that it stands nowhere (docs/handbook/domain.md §역매핑).

Run: uv run pytest -q src/limn/pins/location/tests/test_carry.py
"""

from hypothesis import given, strategies as st

from limn.pins.location.mapping import Carried, carry_range

BUILT = [
    "\\section{Intro}",
    "First paragraph alpha.",
    "",
    "Second paragraph beta,",
    "which runs on gamma,",
    "and ends at delta.",
    "",
    "Third paragraph epsilon.",
]


def test_lines_inserted_above_move_the_range_down_whole():
    """Two lines added above the range: the same three lines, two lines lower, standing whole."""
    now = BUILT[:1] + ["Added one.", ""] + BUILT[1:]
    assert carry_range(BUILT, now, 4, 6) == Carried(6, 8, True)
    assert now[5:8] == BUILT[3:6]


def test_lines_deleted_above_move_the_range_up_whole():
    """The first paragraph and its blank line removed: the range stands whole two lines higher."""
    now = BUILT[:1] + BUILT[3:]
    assert carry_range(BUILT, now, 4, 6) == Carried(2, 4, True)
    assert now[1:4] == BUILT[3:6]


def test_an_edit_below_the_range_leaves_it_where_it_was():
    """A change after the range moves nothing above it."""
    now = BUILT[:7] + ["Third paragraph rewritten."]
    assert carry_range(BUILT, now, 4, 6) == Carried(4, 6, True)


def test_a_line_edited_inside_the_range_is_spanned_and_the_range_is_not_whole():
    """The middle line rewritten: the range runs from its first surviving line to its last, and is not whole."""
    now = BUILT[:1] + ["Added."] + BUILT[1:4] + ["which now runs on other words,"] + BUILT[5:]
    assert carry_range(BUILT, now, 4, 6) == Carried(5, 7, False)


def test_lines_inserted_inside_the_range_are_spanned_and_the_range_is_not_whole():
    """A sentence added in the middle of the paragraph: every line survives, the range grew, so it is not whole."""
    now = BUILT[:4] + ["a clause added in the middle,"] + BUILT[4:]
    assert carry_range(BUILT, now, 4, 6) == Carried(4, 7, False)


def test_a_range_whose_lines_are_all_gone_has_no_place():
    """The paragraph deleted: nothing of the range stands, so there is no range."""
    now = BUILT[:3] + BUILT[7:]
    assert carry_range(BUILT, now, 4, 6) is None


def test_a_range_of_which_only_a_blank_line_survives_has_no_place():
    """The paragraph rewritten and the blank line after it kept: a blank line is not the text that was dragged."""
    now = BUILT[:3] + ["Entirely new words."] + BUILT[6:]
    assert carry_range(BUILT, now, 4, 7) is None


def test_identical_files_keep_the_range_whole():
    """Nothing changed: the same numbers, whole."""
    assert carry_range(BUILT, list(BUILT), 4, 6) == Carried(4, 6, True)


def test_empty_files_have_no_range():
    """No line was built, or no line is left: no range either way."""
    assert carry_range([], [], 1, 1) is None
    assert carry_range([], BUILT, 1, 2) is None
    assert carry_range(BUILT, [], 4, 6) is None


def test_a_range_outside_the_built_lines_is_cut_to_them_or_has_no_place():
    """Numbers past the end of what was built name no line; a range that starts inside is cut at the end."""
    assert carry_range(BUILT, BUILT, 20, 22) is None
    assert carry_range(BUILT, BUILT, 0, 2) == Carried(1, 2, True)
    assert carry_range(BUILT, BUILT, 8, 12) == Carried(8, 8, True)
    assert carry_range(BUILT, BUILT, 6, 4) is None


def test_a_repeated_line_is_followed_in_order_not_to_its_first_twin():
    """Two paragraphs with the same words: the second one is carried to the second one, wherever the first went."""
    built = ["Same words.", "", "Between.", "", "Same words.", "", "End."]
    now = ["New top.", ""] + built
    assert carry_range(built, now, 5, 5) == Carried(7, 7, True)


def test_edits_at_both_ends_of_a_long_file_carry_a_range_in_the_middle():
    """A file long enough for the diff's popular-line shortcut (200 lines and up), edited near the top and the bottom:
    the range in the middle, between blank lines that repeat throughout, moves by the lines added above it."""
    built = []
    for k in range(150):
        built += ["Paragraph %d first line." % k, "Paragraph %d second line." % k, ""]
    now = built[:3] + ["Inserted near the top.", ""] + built[3:440] + ["Changed near the bottom."] + built[441:]
    assert carry_range(built, now, 301, 302) == Carried(303, 304, True)
    assert now[302:304] == built[300:302]


LINE = st.sampled_from(["", "a", "b", "\\begin{x}", "\\end{x}"]) | st.text(alphabet="xyz ", max_size=6)


@given(st.lists(LINE, max_size=30), st.lists(LINE, max_size=30), st.integers(-2, 34), st.integers(-2, 34))
def test_any_answer_names_lines_of_the_file_now_and_a_whole_one_names_the_same_text(built, now, lo, hi):
    """Whatever the two files and the numbers: an answer lies inside the file as it is now and holds a non-blank line of
    the built range; a whole answer holds exactly the built range's lines."""
    got = carry_range(built, now, lo, hi)
    if got is None:
        return
    assert 1 <= got.lo <= got.hi <= len(now)
    was = built[max(1, lo) - 1 : hi]
    there = now[got.lo - 1 : got.hi]
    assert any(line.strip() and line in there for line in was)
    if got.whole:
        assert there == was


@given(
    st.lists(st.integers(0, 3), min_size=1, max_size=12),
    st.data(),
)
def test_edits_outside_a_range_of_lines_found_nowhere_else_carry_it_whole(sizes, data):
    """Lines added and removed anywhere but inside the range, the range's own lines being unlike any other: it is
    always found, whole, with the same text."""
    built = ["line %d" % k for k in range(len(sizes) + 3)]
    lo = data.draw(st.integers(1, len(built)))
    hi = data.draw(st.integers(lo, len(built)))
    head, body, tail = built[: lo - 1], built[lo - 1 : hi], built[hi:]
    keep_head = data.draw(st.lists(st.booleans(), min_size=len(head), max_size=len(head)))
    keep_tail = data.draw(st.lists(st.booleans(), min_size=len(tail), max_size=len(tail)))
    added_head = ["new above %d" % k for k in range(data.draw(st.integers(0, 3)))]
    added_tail = ["new below %d" % k for k in range(data.draw(st.integers(0, 3)))]
    now = (
        added_head
        + [line for line, keep in zip(head, keep_head, strict=True) if keep]
        + body
        + [line for line, keep in zip(tail, keep_tail, strict=True) if keep]
        + added_tail
    )
    got = carry_range(built, now, lo, hi)
    assert got is not None and got.whole
    assert now[got.lo - 1 : got.hi] == body
