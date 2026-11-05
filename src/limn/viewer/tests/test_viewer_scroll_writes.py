"""Every scripted scroll in the viewer's JavaScript, sorted by what it does to a jump of the PDF area (docs/handbook/viewer.md §그림 쪽 도착).

A jump's settling (pages.js arrivalSettle) glides the pages back to its place when they rest elsewhere, so it has to know why
they moved. A write that shows something ends the jump first (SHOWS: pvShow, no input need come before it: a search hit lands
when the PDF's text has been read). A write that keeps what is on screen across a layout change moves with the place (KEEPS). A
new scripted scroll fails here until it is put in one of these lists, so that nobody adds one the settling would undo.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_scroll_writes.py
"""

import collections
import re
import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "js"
WRITE = re.compile(r"\.scroll(?:Top|Left)\s*[-+]?=(?!=)|\.scrollTo\(|\.scrollBy\(|\.scrollIntoView\(")
FUNCTION = re.compile(r"^(?:async\s+)?function\s+(\w+)")

# (file, function: <top> outside any): how many writes. pvShow comes before each of them.
SHOWS = {
    ("doc-switch.js", "showDoc"): 1,
    ("figure.js", "showElementBox"): 1,
    ("list.js", "jumpPin"): 1,
    ("md-surface.js", "mdGoOn"): 1,
    ("md-surface.js", "mdJump"): 1,
    ("search.js", "searchBringBack"): 3,
    ("search.js", "searchReveal"): 2,
    ("selection.js", "revealBox"): 1,
    ("verdict-panel.js", "pvBring"): 1,
    ("verdict-reason.js", "pvShowLine"): 1,
    ("verdict.js", "<top>"): 1,
}
# They hold what is on screen where it stands while the layout changes; the settling measures the place after them.
KEEPS = {
    ("doc-switch.js", "restoreView"): 1,
    ("layout.js", "setSelMode"): 1,
    ("md-surface.js", "mdGoStop"): 1,
    ("md-surface.js", "mdRestore"): 2,
    ("md-surface.js", "mdSpotKeep"): 2,
    ("pages.js", "fitW"): 1,
    ("pages.js", "zoomRestore"): 2,
    ("rebuild.js", "restoreAnchor"): 2,
    ("verdict-panel.js", "pvSideSettle"): 3,
    ("verdict.js", "pvLetBlocks"): 1,
}
# The jump's own glide.
GLIDES = {("verdict.js", "pvGlideInto"): 1, ("verdict.js", "pvGlideTo"): 1}
# Another scroller than the PDF area: the pin panel and its cards, a sheet, a menu, a list, the changes view, a field.
OTHERS = {
    ("cards.js", "openTrash"): 1,
    ("composer.js", "pick"): 3,
    ("doc-switch.js", "navSheetFit"): 6,
    ("doc-tabs.js", "<top>"): 3,
    ("doc-tabs.js", "openDocMenu"): 1,
    ("excerpt.js", "applyRange"): 1,
    ("layout.js", "<top>"): 1,
    ("layout.js", "keepFieldInView"): 2,
    ("layout.js", "noteRowInView"): 1,
    ("layout.js", "onViewport"): 1,
    ("levels.js", "segReveal"): 3,
    ("md-compare.js", "mdcGo"): 1,
    ("md-surface.js", "mdPick"): 2,
    ("list.js", "gotoPinRef"): 1,
    ("list.js", "gotoReview"): 1,
    ("list.js", "jumpToCard"): 1,
    ("list.js", "lazyCards"): 1,
    ("list.js", "setListOrder"): 1,
    ("mentions.js", "mentionPlace"): 1,
    ("notices.js", "bannerNote"): 1,
    ("outline.js", "outlineFollow"): 1,
    ("page-list.js", "pageListKey"): 1,
    ("page-list.js", "revealPageRow"): 1,
    ("reply.js", "openReply"): 1,
    ("revision-zoom.js", "mountRevisionPdf"): 1,
    ("revision-zoom.js", "restoreRevisionAnchor"): 2,
    ("revisions.js", "revHighlight"): 1,
    ("revisions.js", "scrollOverlayTo"): 1,
    ("verdict-panel.js", "pvPanelReveal"): 2,
}


def writes():
    """Every scripted scroll: (file, function, the source of that function up to the write)."""
    for path in sorted(JS.glob("*.js")):
        where, before = "<top>", ""
        for line in path.read_text(encoding="utf-8").splitlines():
            named = FUNCTION.match(line)
            if named:
                where, before = named.group(1), ""
            elif line and not line[0].isspace() and not line.startswith(("//", "/*", " *", "}")):
                where, before = "<top>", ""
            code = "" if line.lstrip().startswith("//") else line.split("   //")[0]
            for write in WRITE.finditer(code):
                yield path.name, where, before + code[: write.start()]
            before += code + "\n"


class ScrollWrites(unittest.TestCase):
    """The lists above against the JavaScript."""

    def test_every_scripted_scroll_is_in_a_list(self):
        """A write not listed - new, or moved to another function - says which list to put it in."""
        found = collections.Counter((name, where) for name, where, _ in writes())
        self.assertEqual(
            dict(found),
            {**SHOWS, **KEEPS, **GLIDES, **OTHERS},
            "put the scripted scroll in SHOWS (pvShow first), KEEPS, GLIDES or OTHERS",
        )

    def test_a_write_that_shows_something_ends_the_jump_first(self):
        """pvShow stands before each write of SHOWS, in its function."""
        for name, where, before in writes():
            if (name, where) in SHOWS:
                with self.subTest(write="%s %s" % (name, where)):
                    self.assertIn("pvShow(", before)

    def test_the_lists_do_not_overlap(self):
        """A write is of one kind."""
        keys = [*SHOWS, *KEEPS, *GLIDES, *OTHERS]
        self.assertEqual(len(keys), len(set(keys)))
