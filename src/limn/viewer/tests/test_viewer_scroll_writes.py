"""Every scripted scroll in the viewer's JavaScript, sorted by what it does to a jump of the PDF area (docs/handbook/viewer.md §그림 쪽 도착).

A jump's settling (pdf/view-pages.ts arrivalSettle) glides the pages back to its place when they rest elsewhere, so it has to know why
they moved. A write that shows something ends the jump first (SHOWS: endJumpForScroll, no input need come before it: a search hit lands
when the PDF's text has been read). A write that keeps what is on screen across a layout change moves with the place (KEEPS). A
new scripted scroll fails here until it is put in one of these lists, so that nobody adds one the settling would undo.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_scroll_writes.py
"""

import collections
import re
import unittest
from pathlib import Path

import helpers_js

JS = Path(__file__).resolve().parents[1] / "js"
WRITE = re.compile(r"\.scroll(?:Top|Left)\s*[-+]?=(?!=)|\.scrollTo\(|\.scrollBy\(|\.scrollIntoView\(")
FUNCTION = re.compile(r"^(?:async\s+)?function\s+(\w+)")

# (file, function: <top> outside any): how many writes. endJumpForScroll comes before each of them.
SHOWS = {
    ("documents/flow-switch.ts", "showDoc"): 1,
    ("pdf/view-figure.ts", "showElementBox"): 1,
    ("pins/flow-list.ts", "jumpPin"): 1,
    ("pins/flow-list.ts", "markReveal"): 1,
    ("markdown/view.ts", "goOnToHeading"): 1,
    ("markdown/view.ts", "showLines"): 1,
    ("pdf/flow.ts", "searchBringBack"): 3,
    ("pdf/flow.ts", "searchReveal"): 2,
    ("pdf/input-selection.ts", "revealBox"): 1,
    ("verdict/view-panel.ts", "bringPage"): 1,
    ("verdict/flow-reason.ts", "showDraftLine"): 1,
    ("verdict/flow-line.ts", "<top>"): 1,
}
# They hold what is on screen where it stands while the layout changes; the settling measures the place after them.
KEEPS = {
    ("documents/flow-switch.ts", "restoreView"): 1,
    ("layout/flow.ts", "setSelectMode"): 1,
    ("markdown/view.ts", "stopHeadingJump"): 2,
    ("markdown/view.ts", "restoreReadingAnchor"): 2,
    ("markdown/view.ts", "keepReadingSpot"): 2,
    ("pdf/view-pages.ts", "fitToWidth"): 1,
    ("pdf/view-pages.ts", "zoomRestore"): 2,
    ("documents/flow-rebuild.ts", "restoreAnchor"): 2,
    ("verdict/view-panel.ts", "settleBesideTurn"): 3,
    ("verdict/flow-line.ts", "letLineBlocks"): 1,
}
# The jump's own glide.
GLIDES = {("verdict/flow-line.ts", "glideInto"): 1, ("verdict/flow-line.ts", "glideTo"): 1}
# Another scroller than the PDF area: the pin panel and its cards, a sheet, a menu, a list, the changes view, a field.
OTHERS = {
    ("pins/view-cards.ts", "openTrash"): 1,
    ("composer/flow-pick.ts", "pick"): 3,
    ("documents/flow-switch.ts", "fitNavigationSheet"): 6,
    ("documents/view-tabs.ts", "<top>"): 3,
    ("documents/view-tabs.ts", "openDocMenu"): 1,
    ("composer/view-excerpt.ts", "applyRange"): 1,
    ("layout/flow.ts", "<top>"): 1,
    ("layout/flow.ts", "fieldScrollKey"): 1,
    ("layout/flow.ts", "keepFieldInView"): 2,
    ("layout/flow.ts", "noteRowInView"): 1,
    ("layout/flow.ts", "onViewport"): 1,
    ("composer/view-levels.ts", "revealSegment"): 3,
    ("revisions/view-rendered-compare.ts", "goToChangeGroup"): 1,
    ("offline/flow.ts", "offlinePick"): 1,
    ("markdown/view.ts", "pickLines"): 2,
    ("pins/flow-list.ts", "gotoPinRef"): 1,
    ("pins/flow-list.ts", "gotoReview"): 1,
    ("pins/flow-list.ts", "jumpToCard"): 1,
    ("pins/flow-list.ts", "lazyCards"): 1,
    ("pins/flow-list.ts", "setListOrder"): 1,
    ("pins/input-mentions.ts", "mentionPlace"): 1,
    ("platform/notices.ts", "bannerNote"): 1,
    ("offline/view.ts", "offUiReveal"): 1,
    ("pdf/view-outline.ts", "outlineFollow"): 1,
    ("pdf/view-page-list.ts", "pageListKey"): 1,
    ("pdf/view-page-list.ts", "revealPageRow"): 1,
    ("pins/flow-reply.ts", "openReply"): 1,
    ("pins/flow-review-pick.ts", "confirmTicked"): 1,
    ("pins/flow-review-pick.ts", "setReviewPicking"): 1,
    ("revisions/input.ts", "mountRevisionPdf"): 1,
    ("revisions/input.ts", "restoreRevisionAnchor"): 2,
    ("revisions/flow.ts", "highlightPinLines"): 1,
    ("revisions/flow.ts", "scrollOverlayTo"): 1,
    ("verdict/view-panel.ts", "revealFocused"): 2,
}


def writes():
    """Every scripted scroll: (file, function, the source of that function up to the write)."""
    paths = sorted(JS.rglob("*.ts"))
    for path, text in zip(paths, helpers_js.module_texts(paths), strict=True):
        where, before = "<top>", ""
        for line in text.splitlines():
            named = FUNCTION.match(line)
            if named:
                where, before = named.group(1), ""
            elif (
                line and not line[0].isspace() and not line.startswith(("//", "/*", " *", "}", ")"))
            ):  # ')' closes a parameter list over lines
                where, before = "<top>", ""
            code = "" if line.lstrip().startswith("//") else line.split("   //")[0]
            for write in WRITE.finditer(code):
                yield path.relative_to(JS).as_posix(), where, before + code[: write.start()]
            before += code + "\n"


class ScrollWrites(unittest.TestCase):
    """The lists above against the JavaScript."""

    def test_every_scripted_scroll_is_in_a_list(self):
        """A write not listed - new, or moved to another function - says which list to put it in."""
        found = collections.Counter((name, where) for name, where, _ in writes())
        self.assertEqual(
            dict(found),
            {**SHOWS, **KEEPS, **GLIDES, **OTHERS},
            "put the scripted scroll in SHOWS (endJumpForScroll first), KEEPS, GLIDES or OTHERS",
        )

    def test_a_write_that_shows_something_ends_the_jump_first(self):
        """endJumpForScroll stands before each write of SHOWS, in its function."""
        for name, where, before in writes():
            if (name, where) in SHOWS:
                with self.subTest(write="%s %s" % (name, where)):
                    self.assertIn("endJumpForScroll(", before)

    def test_a_scripted_scroll_asks_for_motion_as_the_setting_is_now(self):
        """Every scripted scroll's behavior is at once ('auto', 'instant') or scrollMotion() - itself or through armGlide,
        which returns it - read at the scroll, never a smooth one fixed in the code or a value kept from load: a reduced
        motion setting changed with the page open reaches every scroll (#418). The CSS sets no smooth scroll-behavior,
        which a script's 'auto' would follow. Mutation: goToChangeGroup's literal 'smooth' (before #418), or a const read at load,
        fails."""
        allowed = ("'auto'", "'instant'", "scrollMotion()", "armGlide(", "land?'auto':scrollMotion()")
        paths = sorted(JS.rglob("*.ts"))
        for path, text in zip(paths, helpers_js.module_texts(paths), strict=True):
            for m in re.finditer(r"\bbehavior\s*:\s*", text):
                rest = helpers_js.squash(m.string[m.end() : m.end() + 120], fragment=True)[:40]
                with self.subTest(file=path.relative_to(JS).as_posix(), at=rest):
                    self.assertTrue(rest.startswith(allowed), rest)
        for path in sorted((JS.parent / "css").glob("*.css")):
            with self.subTest(file=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"scroll-behavior\s*:\s*smooth")

    def test_the_lists_do_not_overlap(self):
        """A write is of one kind."""
        keys = [*SHOWS, *KEEPS, *GLIDES, *OTHERS]
        self.assertEqual(len(keys), len(set(keys)))
