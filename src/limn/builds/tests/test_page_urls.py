"""Page images and the PDF at URLs that name their build, cached for a year (docs/handbook/api.md §화면·PDF·정적 파일).

/pages/<build>/page-NN.png and /pdf?build=<build> always mean the same bytes - a build folder is never written again and
its name is never reused - so they are served `private, max-age=31536000, immutable`. The old /pages/page-NN.png (the
build on screen) keeps working with its ten-minute cache. Every page and PDF answer carries an ETag, and a matching
If-None-Match is answered 304 without a body. Driven through the handler of the server copy.

Run: uv run pytest -q src/limn/builds/tests/test_page_urls.py
"""

import json

from limn.builds import artifacts as build, input as build_input
from limn.platform import files

from helpers import Base, blank_png, ps, req, split_resp

YEAR = "private, max-age=31536000, immutable"
TEN_MINUTES = "private, max-age=600"
OLD, NEW = "pages-20261001120000", "pages-20261001120500"


class PageUrls(Base):
    """GET /pages/... and GET /pdf for the server copy's single document, with two builds kept."""

    def setUp(self):
        """Two page folders (the previous and the one on screen), each with its own page image and PDF."""
        super().setUp()
        build_doc = ps.APP.docs[0]
        self.D = build_doc
        for name, w in ((OLD, 30), (NEW, 40)):
            d = build_doc.dir / name
            d.mkdir(parents=True)
            (d / "page-1.png").write_bytes(blank_png(w, 20))
            (d / build_doc.pdf_name).write_bytes(b"%PDF-1.4 " + name.encode())
        files.atomic_write(build_doc.dir / "pages.cur", NEW)

    def get(self, path: str, headers: dict | None = None):
        """(status, headers, body) of one GET through the handler."""
        return split_resp(self.talk(req("GET", path, headers=headers)))

    def test_a_page_url_naming_its_build_is_cached_for_a_year(self):
        """/pages/<build>/page-1.png answers that build's image - the previous one too - immutable for a year."""
        for name, w in ((NEW, 40), (OLD, 30)):
            with self.subTest(build=name):
                code, hdrs, body = self.get("/pages/%s/page-1.png" % name)
                self.assertEqual(code, 200)
                self.assertEqual(body, blank_png(w, 20))
                self.assertEqual(hdrs["cache-control"], YEAR)
                self.assertEqual(hdrs["content-type"], "image/png")
                self.assertTrue(hdrs.get("etag", "").startswith('"'), hdrs)

    def test_the_old_page_url_still_answers_the_build_on_screen_for_ten_minutes(self):
        """/pages/page-1.png is the build on screen, cached privately for ten minutes as before, now with an ETag."""
        code, hdrs, body = self.get("/pages/page-1.png")
        self.assertEqual((code, body, hdrs["cache-control"]), (200, blank_png(40, 20), TEN_MINUTES))
        self.assertIn("etag", hdrs)

    def test_a_gone_build_is_404_naming_the_build_on_screen(self):
        """A page URL naming a build whose folder is gone is 404 pdf_build_gone with pages_build, never another
        build's image under a URL cached for a year."""
        code, hdrs, body = self.get("/pages/pages-19990101000000/page-1.png")
        self.assertEqual(code, 404)
        d = json.loads(body)
        self.assertEqual((d["reason"], d["pdf_build_gone"], d["pages_build"]), ("pdf_build_gone", True, NEW))
        self.assertEqual(hdrs["cache-control"], "no-store")

    def test_a_missing_page_or_a_bad_name_is_not_found(self):
        """A build that has no such page, a name that is not a page image, and a component that is not a build name
        in a deeper path: 404, or the old route's answer for the basename (the build on screen, ten minutes)."""
        self.assertEqual(self.get("/pages/%s/page-9.png" % NEW)[0], 404)
        self.assertEqual(self.get("/pages/%s/main.pdf" % NEW)[0], 404)
        code, hdrs, body = self.get("/pages/../%s/page-1.png" % OLD)
        self.assertEqual((code, hdrs["cache-control"]), (200, TEN_MINUTES))
        code, hdrs, _ = self.get("/pages/x/page-1.png")
        self.assertEqual((code, hdrs["cache-control"]), (200, TEN_MINUTES))

    def test_the_legacy_pages_folder_is_never_cached_for_a_year(self):
        """The legacy folder name `pages` is a build name but not a timestamped one: ten minutes, not immutable."""
        legacy = self.D.dir / "pages"
        legacy.mkdir()
        (legacy / "page-1.png").write_bytes(blank_png(10, 10))
        code, hdrs, _ = self.get("/pages/pages/page-1.png")
        self.assertEqual((code, hdrs["cache-control"]), (200, TEN_MINUTES))

    def test_the_pdf_of_a_named_build_is_cached_for_a_year_and_the_unnamed_one_for_ten_minutes(self):
        """/pdf?build=<build> is immutable for a year; /pdf (the build on screen) keeps ten minutes; both have an ETag."""
        code, hdrs, body = self.get("/pdf?build=%s&v=x" % OLD)
        self.assertEqual((code, body, hdrs["cache-control"]), (200, b"%PDF-1.4 " + OLD.encode(), YEAR))
        self.assertIn("etag", hdrs)
        code, hdrs, body = self.get("/pdf")
        self.assertEqual((code, body, hdrs["cache-control"]), (200, b"%PDF-1.4 " + NEW.encode(), TEN_MINUTES))
        self.assertIn("etag", hdrs)

    def test_a_matching_if_none_match_is_304_without_a_body(self):
        """The ETag sent back (alone, weak, or in a list) is 304 with the same ETag and Cache-Control and no body;
        another tag is the full 200."""
        path = "/pages/%s/page-1.png" % NEW
        etag = self.get(path)[1]["etag"]
        for sent in (etag, "W/" + etag, '"other", ' + etag, "*"):
            with self.subTest(sent=sent):
                code, hdrs, body = self.get(path, {"If-None-Match": sent})
                self.assertEqual((code, body, hdrs["etag"], hdrs["cache-control"]), (304, b"", etag, YEAR))
        code, _, body = self.get(path, {"If-None-Match": '"other"'})
        self.assertEqual((code, body), (200, blank_png(40, 20)))
        pdf_etag = self.get("/pdf")[1]["etag"]
        self.assertEqual(self.get("/pdf", {"If-None-Match": pdf_etag})[0], 304)

    def test_the_same_file_in_another_build_has_another_etag(self):
        """An ETag names the build folder too: the same bytes in two builds are two tags."""
        for name in (OLD, NEW):
            (self.D.dir / name / "page-1.png").write_bytes(blank_png(5, 5))
        self.assertNotEqual(
            self.get("/pages/%s/page-1.png" % OLD)[1]["etag"], self.get("/pages/%s/page-1.png" % NEW)[1]["etag"]
        )

    def test_other_answers_keep_their_cache_headers(self):
        """JSON answers stay no-store and carry no ETag."""
        code, hdrs, _ = self.get("/api/meta?light=1")
        self.assertEqual((code, hdrs["cache-control"], "etag" in hdrs), (200, "no-store", False))


class PagePath(Base):
    """build_input.page_path: the build and page a /pages/ path names."""

    def test_the_two_shapes_and_everything_else(self):
        """/pages/<page> is the build on screen; /pages/<build>/<page> names a build; any other middle is the old
        route's basename rule; a name that is not a page image is None."""
        self.assertEqual(build_input.page_path("/pages/page-01.png"), (None, "page-01.png"))
        self.assertEqual(build_input.page_path("/pages/%s/page-01.png" % NEW), (NEW, "page-01.png"))
        self.assertEqual(build_input.page_path("/pages/pages/page-1.png"), ("pages", "page-1.png"))
        self.assertEqual(build_input.page_path("/pages/a/b/page-1.png"), (None, "page-1.png"))
        self.assertEqual(build_input.page_path("/pages/%s/x.png" % NEW), None)
        self.assertTrue(build.valid_build_name(NEW))
