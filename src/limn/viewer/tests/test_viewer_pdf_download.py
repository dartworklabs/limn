"""[PDF 내려받기] in [더보기], in the real viewer (docs/handbook/viewer.md §조작 한눈에).

The row saves the PDF of the build on screen through the browser's own download, named after the document by the
server (GET /pdf?download=1, docs/handbook/api.md). Chromium starts a download outside Playwright's request routing, so
the viewer is served here by a real HTTP server on an ephemeral loopback port, not by BrowserBase's in-process route.
Driven on the desktop's menu under [⋯] and the phone's bottom sheet, on the three kinds of document: a LaTeX
manuscript, a figure document and a view-only PDF.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_pdf_download.py
"""

import threading
from pathlib import Path

import helpers_figure
from helpers import minimal_pdf, ps
from helpers_browser import BrowserBase, booted, settle, watch_idle

DEVICES = {
    "desktop": {"viewport": {"width": 1400, "height": 850}},
    "phone": {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True},
}
# The documents helpers_figure.viewer_docs serves, by key, with the file name each is saved under (its label + .pdf).
SAVED_AS = {"ms": "본문.pdf", "fig": "그림.pdf", "rv": "리뷰어.pdf"}


class PdfDownloadRow(BrowserBase):
    """The [PDF 내려받기] row of [더보기] saves the build on screen under the document's label."""

    def setUp(self):
        """The manuscript, the figure document and the view-only PDF, each with a finished two-page build on screen; the
        manuscript's PDF copy is a real one (the others hold what helpers_figure writes)."""
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(ps.APP.set_docs, None)
        build = Path(self.ms.dir / (self.ms.dir / "pages.cur").read_text().strip())
        (build / self.ms.pdf_name).write_bytes(minimal_pdf("manuscript"))
        self.httpd = ps.Server(("127.0.0.1", 0), ps.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def open_real(self, **device):
        """The viewer from the real server in a new context, booted and settled, with no pins expected."""
        context = self.browser.new_context(**device)
        self.addCleanup(context.close)
        watch_idle(context)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:%d/?lang=ko" % self.httpd.server_address[1])
        page.wait_for_function(booted(0), timeout=20000)
        settle(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def open_more(self, page, device):
        """[⋯] pressed (tapped on the phone) and the menu or sheet open."""
        button = page.locator("#btn-more")
        button.tap() if device == "phone" else button.click()
        page.wait_for_selector("#more[open]")

    def switch(self, page, key):
        """The viewer on document key, settled."""
        page.evaluate("async k=>await switchDoc(k)", key)
        page.wait_for_function("k=>DOC===k", arg=key, timeout=8000)
        settle(page)

    def test_the_row_saves_the_pdf_of_the_build_on_screen_under_the_documents_label(self):
        """Pressing the row starts a download whose name is the document's label + .pdf and whose bytes are that
        build's PDF; the menu closes."""
        for device in DEVICES:
            page = self.open_real(**DEVICES[device])
            for key, name in SAVED_AS.items():
                with self.subTest(device=device, doc=key):
                    self.switch(page, key)
                    self.open_more(page, device)
                    row = page.locator("#m-download")
                    self.assertTrue(row.is_visible())
                    with page.expect_download() as info:
                        row.tap() if device == "phone" else row.click()
                    got = info.value
                    self.assertEqual(got.suggested_filename, name)
                    doc = {"ms": self.ms, "fig": self.fig, "rv": self.rv}[key]
                    pages = (doc.dir / "pages.cur").read_text().strip()
                    self.assertEqual(Path(got.path()).read_bytes(), (doc.dir / pages / doc.pdf_name).read_bytes())
                    settle(page)
                    self.assertFalse(page.evaluate("document.getElementById('more').open"))

    def test_the_row_asks_for_the_build_that_is_on_screen_now(self):
        """After a newer build replaces the one on screen, the next download is that build's PDF."""
        newer = "pages-20260925110000"
        folder = self.ms.dir / newer
        folder.mkdir()
        (folder / self.ms.pdf_name).write_bytes(minimal_pdf("newer"))
        page = self.open_real(**DEVICES["desktop"])
        self.switch(page, "ms")
        page.evaluate("n=>{META.pages_build=n;}", newer)
        self.open_more(page, "desktop")
        with page.expect_download() as info:
            page.locator("#m-download").click()
        self.assertEqual(Path(info.value.path()).read_bytes(), minimal_pdf("newer"))

    def test_the_row_is_off_while_no_build_is_on_screen(self):
        """With no build on screen there is no PDF to save: the row is disabled."""
        page = self.open_real(**DEVICES["desktop"])
        page.evaluate("()=>{META.pages_build=''; drawMeta();}")
        self.assertTrue(page.locator("#m-download").is_disabled())
        page.evaluate("()=>{META.pages_build='pages-20260925100000'; drawMeta();}")
        self.assertFalse(page.locator("#m-download").is_disabled())
