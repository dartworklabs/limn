"""GET /pdf?download=1: the PDF of a build as an attachment named after the document (docs/handbook/api.md §화면·PDF·정적 파일).

The option only adds `Content-Disposition: attachment`; the bytes, the cache headers, the ETag and the access rules are
those of the plain /pdf. The file name is `<document label>.pdf`, made safe for a file system, with the label's own
characters kept in `filename*` (RFC 6266/8187) beside a plain-ASCII `filename`. The switch follows the shared rule of
the other query switches (limn.web.parse.parse_flag): on only for exactly "1", anything else is off and never refused.
Driven through the handler of the server copy.

Run: uv run pytest -q src/limn/builds/tests/test_pdf_download.py
"""

import json
from urllib.parse import unquote

from hypothesis import given, strategies as st

from limn.builds import input as build_input
from limn.platform import files
from limn.web.reply import attachment_disposition

from helpers import ps, req, set_config, split_resp
from helpers_access import ALICE, TS_HOST, AccessBase, talk_to

OLD, NEW = "pages-20261001120000", "pages-20261001120500"
KOREAN = "리뷰어 응답 · 최종본"


class PdfDownload(AccessBase):
    """GET /pdf with and without ?download=1 for the server copy's single document, with two builds kept."""

    def setUp(self):
        """Two page folders, each with its own PDF; the document is labelled in Korean."""
        super().setUp()
        self.D = ps.APP.docs[0]
        self.D.name = KOREAN
        for name in (OLD, NEW):
            d = self.D.dir / name
            d.mkdir(parents=True)
            (d / self.D.pdf_name).write_bytes(b"%PDF-1.4 " + name.encode())
        files.atomic_write(self.D.dir / "pages.cur", NEW)

    def get(self, path, headers=None):
        """(status, headers, body) of one GET through the handler as the loopback agent."""
        return split_resp(talk_to(ps, req("GET", path, headers=headers)))

    def test_download_adds_only_an_attachment_header(self):
        """The same 200 as the plain route - bytes, type, cache, ETag - plus Content-Disposition: attachment."""
        for query in ("", "?build=%s" % OLD):
            with self.subTest(query=query):
                plain = self.get("/pdf" + query)
                sep = "&" if query else "?"
                code, hdrs, body = self.get("/pdf%s%sdownload=1" % (query, sep))
                self.assertEqual(code, 200)
                self.assertEqual(body, plain[2])
                self.assertNotIn("content-disposition", plain[1])
                self.assertTrue(hdrs["content-disposition"].startswith("attachment;"), hdrs)
                for same in ("content-type", "cache-control", "etag"):
                    self.assertEqual(hdrs[same], plain[1][same])

    def test_the_file_name_is_the_label_with_the_utf8_form_beside_an_ascii_fallback(self):
        """A Korean label stays Korean in filename* (percent-encoded UTF-8) and has a plain ASCII filename beside it."""
        hdrs = self.get("/pdf?download=1")[1]
        value = hdrs["content-disposition"]
        value.encode("ascii")
        self.assertIn('filename="document.pdf"', value)
        star = value.split("filename*=UTF-8''", 1)[1]
        self.assertEqual(unquote(star), KOREAN + ".pdf")

    def test_an_ascii_label_is_one_plain_filename(self):
        """No filename* when it would say the same as filename."""
        self.D.name = "Cover letter"
        value = self.get("/pdf?download=1")[1]["content-disposition"]
        self.assertEqual(value, 'attachment; filename="Cover letter.pdf"')

    def test_a_label_that_is_not_a_safe_file_name_is_made_one(self):
        """Path separators, quotes, controls and a leading dot never reach the file name; nothing is left of an empty one."""
        for label, want in (
            ('a/b\\c:d*e?f"g<h>i|j', "a_b_c_d_e_f_g_h_i_j.pdf"),
            ("..hidden", "hidden.pdf"),
            ("tab\there", "tab here.pdf"),
            ("   ", "document.pdf"),
            ("CON", "_CON.pdf"),
        ):
            with self.subTest(label=label):
                self.D.name = label
                value = self.get("/pdf?download=1")[1]["content-disposition"]
                self.assertEqual(value, 'attachment; filename="%s"' % want)

    def test_a_switch_that_is_not_exactly_one_is_ignored_not_refused(self):
        """?download=0, true, yes, 2, an empty value and a repeated one are the plain inline answer: 200, no header.
        The shared switch rule never refuses a query (parse_flag)."""
        plain = self.get("/pdf")
        for query in ("download=0", "download=true", "download=yes", "download=2", "download=", "download=1x", "dl=1"):
            with self.subTest(query=query):
                code, hdrs, body = self.get("/pdf?" + query)
                self.assertEqual((code, body), (200, plain[2]))
                self.assertNotIn("content-disposition", hdrs)

    def test_a_missing_or_gone_pdf_is_the_same_404_without_a_download_header(self):
        """The contract 404s (pdf_build_gone, pdf_missing) are unchanged and name no attachment."""
        code, hdrs, body = self.get("/pdf?build=pages-19990101000000&download=1")
        self.assertEqual(code, 404)
        self.assertEqual(json.loads(body)["reason"], "pdf_build_gone")
        self.assertNotIn("content-disposition", hdrs)
        self.assertNotIn(b"%PDF", body)
        (self.D.dir / NEW / self.D.pdf_name).unlink()
        code, hdrs, body = self.get("/pdf?download=1")
        self.assertEqual((code, json.loads(body)["reason"]), (404, "pdf_missing"))
        self.assertNotIn("content-disposition", hdrs)

    def test_a_matching_if_none_match_is_still_304(self):
        """The conditional answer is the plain route's: 304 with the same ETag, no body."""
        etag = self.get("/pdf?download=1")[1]["etag"]
        code, hdrs, body = self.get("/pdf?download=1", {"If-None-Match": etag})
        self.assertEqual((code, body, hdrs["etag"]), (304, b"", etag))

    def test_the_access_rules_are_those_of_the_plain_pdf(self):
        """A request the plain /pdf refuses is refused the same way with ?download=1, and no PDF byte or header leaks."""
        cases = (
            {"Host": "evil.example"},
            {"Origin": "https://evil.example"},
            {"Host": TS_HOST},  # a tailnet host with no identity
        )
        for headers in cases:
            with self.subTest(headers=headers):
                plain = self.get("/pdf", headers)
                code, hdrs, body = self.get("/pdf?download=1", headers)
                self.assertEqual((code, body), (plain[0], plain[2]))
                self.assertEqual(code, 403)
                self.assertNotIn("content-disposition", hdrs)
                self.assertNotIn(b"%PDF", body)
        code, hdrs, body = self.get("/pdf?download=1", dict(ALICE, Host=TS_HOST))
        self.assertEqual(code, 200)
        self.assertIn("attachment", hdrs["content-disposition"])

    def test_an_allowlist_that_leaves_someone_out_refuses_the_download_too(self):
        """With --allow naming only Bob, Alice is refused the plain PDF and the download alike."""
        set_config(allow=frozenset({"bob@example.com"}))
        plain = self.get("/pdf", ALICE)
        code, hdrs, body = self.get("/pdf?download=1", ALICE)
        self.assertEqual((code, body), (plain[0], plain[2]))
        self.assertEqual(code, 403)
        self.assertNotIn("content-disposition", hdrs)


class DownloadInput(AccessBase):
    """build_input.parse_download: the exact-value switch of GET /pdf."""

    def test_on_only_for_a_single_one(self):
        """Anything but a first value of exactly "1" is off; the query is never refused."""
        self.assertTrue(build_input.parse_download({"download": ["1"]}))
        for q in ({}, {"download": ["0"]}, {"download": ["true"]}, {"download": [""]}, {"build": ["1"]}):
            with self.subTest(q=q):
                self.assertFalse(build_input.parse_download(q))


@given(st.text(max_size=80))
def test_the_header_is_one_safe_ascii_line_for_any_label(label):
    """Whatever the label, the value is ASCII on one line, and what it names is a plain file name ending in .pdf that
    holds no separator, no control character and no leading dot or space (hypothesis)."""
    value = attachment_disposition(label)
    value.encode("ascii")
    assert "\r" not in value and "\n" not in value
    assert value.startswith("attachment; filename=")
    name = unquote(value.split("filename*=UTF-8''", 1)[1]) if "filename*=" in value else value.split('"')[1]
    assert name.endswith(".pdf") and len(name) > len(".pdf")
    assert not any(c in name for c in '/\\:*?"<>|') and all(ord(c) >= 32 and ord(c) != 127 for c in name)
    assert name == name.strip() and not name.startswith(".")
