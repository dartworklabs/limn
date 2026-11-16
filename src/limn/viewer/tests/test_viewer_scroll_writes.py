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

import helpers_js

JS = Path(__file__).resolve().parents[1] / "js"
WRITE = re.compile(r"\.scroll(?:Top|Left)\s*[-+]?=(?!=)|\.scrollTo\(|\.scrollBy\(|\.scrollIntoView\(")
FUNCTION = re.compile(r"^(?:async\s+)?function\s+(\w+)")

# (file, function: <top> outside any): how many writes. pvShow comes before each of them.
SHOWS = {
    ("doc-switch.ts", "showDoc"): 1,
    ("figure.ts", "showElementBox"): 1,
    ("list.ts", "jumpPin"): 1,
    ("list.ts", "markReveal"): 1,
    ("md-surface.ts", "mdGoOn"): 1,
    ("md-surface.ts", "mdShowLines"): 1,
    ("search.ts", "searchBringBack"): 3,
    ("search.ts", "searchReveal"): 2,
    ("selection.ts", "revealBox"): 1,
    ("verdict-panel.ts", "pvBring"): 1,
    ("verdict-reason.ts", "pvShowLine"): 1,
    ("verdict.ts", "<top>"): 1,
}
# They hold what is on screen where it stands while the layout changes; the settling measures the place after them.
KEEPS = {
    ("doc-switch.ts", "restoreView"): 1,
    ("layout.ts", "setSelMode"): 1,
    ("md-surface.ts", "mdGoStop"): 2,
    ("md-surface.ts", "mdRestore"): 2,
    ("md-surface.ts", "mdSpotKeep"): 2,
    ("pages.ts", "fitW"): 1,
    ("pages.ts", "zoomRestore"): 2,
    ("rebuild.ts", "restoreAnchor"): 2,
    ("verdict-panel.ts", "pvSideSettle"): 3,
    ("verdict.ts", "pvLetBlocks"): 1,
}
# The jump's own glide.
GLIDES = {("verdict.ts", "pvGlideInto"): 1, ("verdict.ts", "pvGlideTo"): 1}
# Another scroller than the PDF area: the pin panel and its cards, a sheet, a menu, a list, the changes view, a field.
OTHERS = {
    ("cards.ts", "openTrash"): 1,
    ("composer.ts", "pick"): 3,
    ("doc-switch.ts", "navSheetFit"): 6,
    ("doc-tabs.ts", "<top>"): 3,
    ("doc-tabs.ts", "openDocMenu"): 1,
    ("excerpt.ts", "applyRange"): 1,
    ("layout.ts", "<top>"): 1,
    ("layout.ts", "fieldScrollKey"): 1,
    ("layout.ts", "keepFieldInView"): 2,
    ("layout.ts", "noteRowInView"): 1,
    ("layout.ts", "onViewport"): 1,
    ("levels.ts", "segReveal"): 3,
    ("md-compare.ts", "mdcGo"): 1,
    ("offline.ts", "offlinePick"): 1,
    ("md-surface.ts", "mdPick"): 2,
    ("list.ts", "gotoPinRef"): 1,
    ("list.ts", "gotoReview"): 1,
    ("list.ts", "jumpToCard"): 1,
    ("list.ts", "lazyCards"): 1,
    ("list.ts", "setListOrder"): 1,
    ("mentions.ts", "mentionPlace"): 1,
    ("notices.ts", "bannerNote"): 1,
    ("offline-ui.ts", "offUiReveal"): 1,
    ("outline.ts", "outlineFollow"): 1,
    ("page-list.ts", "pageListKey"): 1,
    ("page-list.ts", "revealPageRow"): 1,
    ("reply.ts", "openReply"): 1,
    ("review-pick.ts", "rvConfirm"): 1,
    ("review-pick.ts", "rvPick"): 1,
    ("revision-zoom.ts", "mountRevisionPdf"): 1,
    ("revision-zoom.ts", "restoreRevisionAnchor"): 2,
    ("revisions.ts", "revHighlight"): 1,
    ("revisions.ts", "scrollOverlayTo"): 1,
    ("verdict-panel.ts", "pvPanelReveal"): 2,
}


def writes():
    """Every scripted scroll: (file, function, the source of that function up to the write)."""
    paths = sorted(JS.glob("*.ts"))
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

    def test_a_scripted_scroll_asks_for_motion_as_the_setting_is_now(self):
        """Every scripted scroll's behavior is at once ('auto', 'instant') or scrollMotion() - itself or through pvGlideArm,
        which returns it - read at the scroll, never a smooth one fixed in the code or a value kept from load: a reduced
        motion setting changed with the page open reaches every scroll (#418). The CSS sets no smooth scroll-behavior,
        which a script's 'auto' would follow. Mutation: mdcGo's literal 'smooth' (before #418), or a const read at load,
        fails."""
        allowed = ("'auto'", "'instant'", "scrollMotion()", "pvGlideArm(", "land?'auto':scrollMotion()")
        paths = sorted(JS.glob("*.ts"))
        for path, text in zip(paths, helpers_js.module_texts(paths), strict=True):
            for m in re.finditer(r"\bbehavior\s*:\s*", text):
                rest = helpers_js.squash(m.string[m.end() : m.end() + 120], fragment=True)[:40]
                with self.subTest(file=path.name, at=rest):
                    self.assertTrue(rest.startswith(allowed), rest)
        for path in sorted((JS.parent / "css").glob("*.css")):
            with self.subTest(file=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"scroll-behavior\s*:\s*smooth")

    def test_the_lists_do_not_overlap(self):
        """A write is of one kind."""
        keys = [*SHOWS, *KEEPS, *GLIDES, *OTHERS]
        self.assertEqual(len(keys), len(set(keys)))
