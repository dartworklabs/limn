"""The Content-Security-Policy of Limn's HTML pages (limn.web.csp, docs/adr/0026-viewer-csp.md).

The policy allows a page's inline scripts and styles by their hashes, so the one property that matters is that the
hashes in the header are those of the bytes the browser receives. The oracle here is independent of limn.web.csp:
html.parser reads the served body the way an HTML tokenizer does (script and style text as raw text up to the closing
tag) and hashlib hashes what it read. The browser side - that the policy blocks nothing the viewer does and blocks what
it should - is viewer/tests/test_viewer_csp.py and the gate every browser test passes (tests/support/helpers_csp.py).

Run: uv run pytest -q src/limn/web/tests/test_csp.py
"""

import base64
import hashlib
import unittest
from html.parser import HTMLParser

from limn.viewer import assemble
from limn.web import csp

from helpers import VIEWER_FILES, ps, req, serve_viewer, set_config, split_resp
from helpers_access import ALICE, CAROL, AccessBase, talk_to


class _Inline(HTMLParser):
    """The text of every inline <script> and <style> of a page, as the tokenizer gives it (CDATA content)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.found: list[tuple[str, str]] = []
        self._open: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._open, self._text = tag, []

    def handle_data(self, data):
        if self._open is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == self._open:
            self.found.append((tag, "".join(self._text)))
            self._open = None


def served_hashes(body: bytes) -> dict[str, set[str]]:
    """{'script-src': {...}, 'style-src': {...}} - the hash sources of the inline elements of a served body."""
    parser = _Inline()
    parser.feed(body.decode("utf-8"))
    parser.close()
    out: dict[str, set[str]] = {"script-src": set(), "style-src": set()}
    for tag, text in parser.found:
        digest = base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()
        out[tag + "-src"].add("'sha256-%s'" % digest)
    return out


def directives(policy: str) -> dict[str, list[str]]:
    """A policy as {directive: [source, ...]}."""
    out = {}
    for part in policy.split(";"):
        name, *sources = part.split()
        out[name] = sources
    return out


def header_hashes(policy: str) -> dict[str, set[str]]:
    """The hash sources the policy allows, per directive."""
    d = directives(policy)
    return {k: {s for s in d[k] if s.startswith("'sha256-")} for k in ("script-src", "style-src")}


class ViewerPagePolicy(AccessBase):
    """GET / carries the policy of the very page it serves."""

    def page(self, headers=ALICE):
        """GET / as a browser: (status, response headers, body bytes)."""
        return split_resp(talk_to(ps, req("GET", "/", b"", dict(headers, Accept="text/html"))))

    def test_the_header_allows_exactly_the_inline_scripts_and_styles_of_the_served_bytes(self):
        """Three inline scripts (theme, language, the viewer) and one stylesheet, each hash in the header, no other."""
        code, hdrs, body = self.page()
        self.assertEqual(code, 200)
        got = served_hashes(body)
        self.assertEqual((len(got["script-src"]), len(got["style-src"])), (3, 1))
        self.assertEqual(header_hashes(hdrs["content-security-policy"]), got)

    def test_the_directives(self):
        """What the viewer is allowed beyond its hashes: its own origin, and https: images for avatars. No plugin, no
        <base>, no form target, no frame, not framed. Nothing allows unsafe-inline or unsafe-eval."""
        _, hdrs, _ = self.page()
        policy = hdrs["content-security-policy"]
        d = directives(policy)
        self.assertEqual(d["default-src"], ["'self'"])
        self.assertEqual([s for s in d["script-src"] if not s.startswith("'sha256-")], ["'self'"])
        self.assertEqual([s for s in d["style-src"] if not s.startswith("'sha256-")], ["'self'"])
        self.assertEqual(d["img-src"], ["'self'", "https:"])
        for name in ("object-src", "base-uri", "form-action", "frame-src", "frame-ancestors"):
            self.assertEqual(d[name], ["'none'"], name)
        self.assertNotIn("unsafe", policy)
        self.assertEqual(hdrs["x-frame-options"], "DENY")

    def test_the_policy_is_the_runs(self):
        """The run fills the interface language into a script and the accent into the stylesheet, so another run's page
        has other hashes - and each run's header still matches its own bytes."""
        _, first, body1 = self.page()
        set_config(ui_lang="en")
        serve_viewer("Other", "#16a34a")
        _, second, body2 = self.page()
        self.assertNotEqual(first["content-security-policy"], second["content-security-policy"])
        self.assertEqual(header_hashes(second["content-security-policy"]), served_hashes(body2))
        self.assertEqual(header_hashes(first["content-security-policy"]), served_hashes(body1))

    def test_the_refusal_page_carries_its_own_policy(self):
        """A browser refused at GET / reads a page with its own inline script and style; they are hashed the same way."""
        set_config(members_only=True)
        code, hdrs, body = self.page(CAROL)
        self.assertEqual(code, 403)
        self.assertEqual(header_hashes(hdrs["content-security-policy"]), served_hashes(body))
        self.assertEqual(directives(hdrs["content-security-policy"])["frame-ancestors"], ["'none'"])

    def test_every_other_response_says_only_frame_ancestors(self):
        """JSON, pins.md, a vendored module and the service worker carry FRAME_ONLY: the policy is the page's."""
        for path in ("/api/version", "/pins.md", "/vendor/pdfjs/pdf.min.mjs?v=1", "/sw.js"):
            code, hdrs, _ = split_resp(talk_to(ps, req("GET", path, b"", ALICE)))
            self.assertEqual(code, 200, path)
            self.assertEqual(hdrs["content-security-policy"], csp.FRAME_ONLY, path)


class PackagedPagePolicy(unittest.TestCase):
    """The packaged viewer page can be hashed for every run: whatever label, accent and interface language a run gives,
    the page's inline elements read the same to the browser and to page_policy (a page that could not be read would be
    a packaging defect, refused with ValueError)."""

    def test_every_run_of_the_packaged_page_is_hashed_as_the_browser_reads_it(self):
        for label, accent, lang in (
            ("Demo", "#2563eb", "ko"),
            ("</script><!--", "#000000", "en"),
            ("A & B", "#ffffff", None),
        ):
            with self.subTest(label=label, lang=lang):
                page = assemble.serve_viewer(VIEWER_FILES, label, accent, lang).page
                self.assertEqual(header_hashes(csp.page_policy(page)), served_hashes(page.encode()))


class InlineHashes(unittest.TestCase):
    """inline_hashes reads a page as the tokenizer does, or refuses it."""

    def test_newlines_are_normalised_as_the_tokenizer_does(self):
        """CR LF and a lone CR are LF before the browser hashes a script's text."""
        lf, _ = csp.inline_hashes("<script>a\nb\nc</script>")
        crlf, _ = csp.inline_hashes("<script>a\r\nb\rc</script>")
        self.assertEqual(lf, crlf)

    def test_repeats_are_one_source_and_order_is_kept(self):
        scripts, styles = csp.inline_hashes("<script>b</script><style>s</style><script>a</script><script>b</script>")
        self.assertEqual(len(scripts), 2)
        self.assertEqual(len(styles), 1)
        self.assertEqual(scripts, csp.inline_hashes("<script>b</script><script>a</script>")[0])

    def test_a_page_it_cannot_read_as_the_browser_does_is_refused(self):
        """A tag with attributes, a closing tag spelt otherwise inside the text, an HTML comment opener in a script:
        the browser would read another text than the pattern, so the page is refused (a packaging defect)."""
        for page in (
            '<script src="/x.js"></script>',
            "<script type=module>a</script>",
            "<script>a</SCRIPT >b</script>",
            "<script>if(a<!--b)c</script>",
            "<style>a</style ><style>b</style>",
        ):
            with self.subTest(page=page), self.assertRaises(ValueError):
                csp.inline_hashes(page)


if __name__ == "__main__":
    unittest.main()
