"""Images of the manuscript tree and links between registered documents on the Markdown surface, in the browser
(docs/adr/0030-markdown-tree-images-and-document-links.md, docs/handbook/viewer.md §Markdown 화면).

The real viewer against the in-process server (BrowserBase), on two Markdown documents of one tree - notes/plan.md (nt) and
docs/guide.md (gd) - and the LaTeX manuscript (ms):

- a tree image is an <img> from this origin's GET /api/asset; a remote, data:, out-of-tree or missing image is its alt
  text saying why, and nothing is asked of another host - not even by the SVG, whose script and external image never run;
- an SVG opened on its own, with the asset route's own headers enforced, runs no script, fetches nothing and has an opaque
  origin; the same SVG without those headers does run (the test can see what it guards);
- an image that loads above the reading line leaves the text being read where it was, also when it is drawn at a size an
  earlier load learned and the file has since changed;
- a pin on an image's line outlines the image; a click on an image picks its paragraph;
- a link to another registered document goes to it, at its heading, and the browser's back returns - also before that
  document has opened, which then never opens over the entry back returned to; followed while a phone's back layer holds
  the top history entry, it adds none, and back closes the layer;
- the jump to that heading lands on it though images above it load on the way (HeadingJump); a double click on a link
  still waiting for its document adds one entry, and back between two entries of one address shows the document it names;
- where this branch meets #409's reading spot and focus and ADR-0029's text documents: an image that loads under the
  changes view leaves the text in place (one reading-spot model); badges stand before their blocks and follow their lines
  when an image loads; a reflow during a heading jump does not cut it short; a tip names the hidden characters of the path
  or '#…' it shows; a link followed from the keyboard leaves the focus on its heading; a text document opened by a link
  draws no image and no link;
- another origin's page cannot embed a tree image (Cross-Origin-Resource-Policy: same-origin), on a real loopback
  listener where the browser itself enforces the header; the viewer's own page still can;
- the image, link and SVG checks hold in Firefox too (the *Firefox classes; WebKit does not launch everywhere, and its
  scroll anchoring - absent there - is what ReadingSpot stands in for).

The pure rules are in test_md_tree_refs.py; the route's checks in src/limn/documents/tests/test_assets.py.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_markdown_assets.py
"""

import http.server
import json
import sys
import threading
import time
import unittest
from functools import partial
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from limn.administration import serve_documents as startup_documents

from helpers import blank_png, ps, req, set_config
from helpers_browser import BrowserBase, settle
from helpers_csp import add_test_style
from helpers_figure import BUILD1, viewer_build

DRAWN = "typeof MD!=='undefined'&&MD.shown===DOC&&!!document.querySelector('#md')&&!MD.job"
# Every tree image on screen has loaded or failed (a failed one is replaced by its alt text).
PICS_DONE = "[...document.querySelectorAll('#md .md-pic img')].every(i=>i.complete)"
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40" onload="fetch(\'/svg-onload\')">'
    "<style>.b{fill:#1d4ed8}</style><script>document.title='svg ran';fetch('/svg-script')</script>"
    '<image href="https://tracker.example/svg-pixel.png" width="1" height="1"/>'
    '<rect class="b" width="120" height="40"/></svg>'
)
PLAN = """# 계획

![막대](img/chart.png)

![흐름](img/flow.svg)

- 원격: ![원격](https://tracker.example/pixel.png)
- 밖: ![밖](../../outside.png)
- 데이터: ![데이터](data:image/png;base64,iVBORw0KGgo=)
- 없음: ![없음](img/gone.png)
- 가짜: ![가짜](img/fake.png)

[안내의 설치](../docs/guide.md#설치) [사진 열기](img/chart.png) [할 일](todo.txt)
"""
GUIDE = (
    "# 안내\n\n"
    + "".join("문단 %d.\n\n" % i for i in range(1, 80))
    + "## 설치\n\n설치 문단.\n\n[계획으로](../notes/plan.md)\n"
)
# A long document whose first block is an image: the reading line far below it must not move when it loads.
TALL = (
    "# 긴 문서\n\n![위 그림](img/tall.png)\n\n"
    + "".join("줄 %d 의 문단.\n\n" % i for i in range(1, 120))
    + "## 읽는 곳\n\n여기.\n"
)


# Below the image a document draws first, the heading of the reading line far down.
TALL_GUIDE = (
    "# 안내\n\n![위 그림](../notes/img/tall.png)\n\n"
    + "".join("안내 줄 %d 의 문단.\n\n" % i for i in range(1, 120))
    + "## 읽는 곳\n\n여기.\n"
)
# gd with six tall images of their own (unknown sizes) above '## 설치', the heading nt's link goes to, and room below it.
PICS_GUIDE = (
    "# 안내\n\n"
    + "".join(
        "".join("안내 %d-%d 의 문단.\n\n" % (i, j) for j in range(1, 13))
        + "![그림 %d](../notes/img/p%d.png)\n\n" % (i, i)
        for i in range(1, 7)
    )
    + "## 설치\n\n설치 문단.\n\n"
    + "".join("뒤 문단 %d.\n\n" % i for i in range(1, 60))
)
# Where the heading '설치' is in the document pane, in px from the pane's top.
SETUP_TOP = (
    "(()=>{const h=MD.heads.find(x=>x.title==='설치'),L=document.querySelector('#left');"
    " return h.el.getBoundingClientRect().top-L.getBoundingClientRect().top;})()"
)
# Where the heading '읽는 곳' is in the document pane, in px from the pane's top.
HEADING_TOP = (
    "(()=>{const h=MD.heads.find(x=>x.title==='읽는 곳'),L=document.querySelector('#left');"
    " return h.el.getBoundingClientRect().top-L.getBoundingClientRect().top;})()"
)


def until(page, js: str, timeout: float = 8.0):
    """Poll the page expression js with page.evaluate (no eval in the page, unlike wait_for_function) until it is truthy;
    its value, or AssertionError after timeout seconds."""
    end = time.monotonic() + timeout
    while True:
        got = page.evaluate(js)
        if got:
            return got
        if time.monotonic() > end:
            raise AssertionError("never true: " + js)
        page.wait_for_timeout(50)


def line_of(text: str, needle: str) -> int:
    """The 1-based line of text that holds needle."""
    return next(i for i, ln in enumerate(text.split("\n"), 1) if needle in ln)


class AssetsBase(BrowserBase):
    """BrowserBase with notes/plan.md (nt, PLAN) first, docs/guide.md (gd) and the LaTeX manuscript (ms) second and third,
    images in notes/img, and an image outside the tree."""

    PLAN = PLAN
    GUIDE = GUIDE
    # notes/todo.txt registered as a fourth document, the text document td, when set (its lines).
    TODO: str | None = None

    def setUp(self):
        self.away: list[str] = []
        self.asked: list[str] = []
        self.hold: list = []
        self.holding = False
        self.held_meta: list = []
        self.hold_meta: str | None = None
        self.source_held: list = []
        self.hold_source = False
        super().setUp()
        self.src = self.main.parent
        (self.src / "notes" / "img").mkdir(parents=True)
        (self.src / "docs").mkdir()
        (self.src / "notes" / "plan.md").write_text(self.PLAN, encoding="utf-8")
        (self.src / "docs" / "guide.md").write_text(self.GUIDE, encoding="utf-8")
        (self.src / "notes" / "img" / "chart.png").write_bytes(blank_png(240, 120))
        (self.src / "notes" / "img" / "tall.png").write_bytes(blank_png(200, 900))
        (self.src / "notes" / "img" / "flow.svg").write_text(SVG, encoding="utf-8")
        (self.src / "notes" / "img" / "fake.png").write_text("<html>not a png</html>", encoding="utf-8")
        (self.src.parent / "outside.png").write_bytes(blank_png(10, 10))
        specs = ["nt=계획:notes/plan.md", "gd=안내:docs/guide.md", "ms=본문:main.tex"]
        if self.TODO is not None:
            (self.src / "notes" / "todo.txt").write_text(self.TODO, encoding="utf-8")
            specs.append("td=할 일:notes/todo.txt")
        docs = startup_documents.make_docs(specs, self.src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        ps.APP.set_docs(docs)
        viewer_build(docs[2], BUILD1)

    def route(self, route):
        """Record every request; abort another host's (kept in self.away); hold /api/asset answers while self.holding,
        gd's /api/source answers while self.hold_source (in self.source_held), and /api/meta answers for the document
        self.hold_meta (in self.held_meta)."""
        u = urlparse(route.request.url)
        self.asked.append(u.path + ("?" + u.query if u.query else ""))
        if u.netloc != "viewer.test":
            self.away.append(route.request.url)
            return route.abort()
        if self.hold_source and u.path == "/api/source" and parse_qs(u.query).get("doc") == ["gd"]:
            self.source_held.append(route)
            return None
        if self.holding and u.path == "/api/asset":
            self.hold.append(route)
            return None
        if self.hold_meta and u.path == "/api/meta" and parse_qs(u.query).get("doc") == [self.hold_meta]:
            self.held_meta.append(route)
            return None
        return super().route(route)

    def open_md(self, **kw):
        """The viewer on the first document, drawn, its tree images done."""
        page = self.open(0, **kw)
        page.wait_for_function(DRAWN, timeout=20000)
        page.wait_for_function(PICS_DONE, timeout=10000)
        settle(page)
        return page


class TreeImages(AssetsBase):
    """What an image's source loads, and what it never does."""

    def test_tree_images_load_from_the_asset_route_and_the_rest_say_why_not(self):
        """The PNG and the SVG of the tree are <img> elements loaded from /api/asset?doc=nt&path=...; the remote, out-of-tree,
        data:, missing and fake images are their alt text with the reason in the tip; no other host was asked, and the
        SVG's script, onload and external image never ran."""
        page = self.open_md()
        imgs = page.evaluate(
            "[...document.querySelectorAll('#md img')].map(i=>[i.getAttribute('src'),i.naturalWidth>0,i.alt])"
        )
        self.assertEqual(
            imgs,
            [
                ["/api/asset?doc=nt&path=notes%2Fimg%2Fchart.png", True, "막대"],
                ["/api/asset?doc=nt&path=notes%2Fimg%2Fflow.svg", True, "흐름"],
            ],
        )
        tips = dict(
            page.evaluate("[...document.querySelectorAll('#md .md-img')].map(e=>[e.textContent,e.dataset.tip])")
        )
        self.assertEqual(
            tips,
            {
                "그림: 원격": "원격 그림은 불러오지 않습니다 · https://tracker.example/pixel.png",
                "그림: 밖": "원고 밖의 그림은 불러오지 않습니다 · ../../outside.png",
                "그림: 데이터": "이 그림은 불러오지 않습니다 · data:image/png;base64,iVBORw0KGgo=",
                "그림: 없음": "그림을 불러오지 못했습니다 · notes/img/gone.png",
                "그림: 가짜": "그림을 불러오지 못했습니다 · notes/img/fake.png",
            },
        )
        self.assertEqual(self.away, [])
        self.assertFalse([p for p in self.asked if p.startswith("/svg-")], self.asked)
        self.assertNotEqual(page.title(), "svg ran")

    def test_a_link_to_a_tree_image_opens_it_and_an_unregistered_file_stays_text(self):
        """[사진 열기](img/chart.png) is a new-tab link to /api/asset; [할 일](todo.txt) is inert text naming why."""
        page = self.open_md()
        got = page.evaluate(
            "({a:[...document.querySelectorAll('#md a.md-asset')].map(a=>[a.getAttribute('href'),a.target,a.rel]),"
            "rel:[...document.querySelectorAll('#md .md-rel')].map(e=>e.dataset.tip)})"
        )
        self.assertEqual(
            got["a"], [["/api/asset?doc=nt&path=notes%2Fimg%2Fchart.png", "_blank", "noopener noreferrer"]]
        )
        self.assertEqual(got["rel"], ["등록된 문서가 아니라 열지 않습니다 · todo.txt"])

    def test_a_pin_on_an_image_line_outlines_the_image_and_a_click_on_it_picks_its_paragraph(self):
        """A pin on the chart's line draws a solid outline in the open colour round the image; clicking the image picks its
        line, the default rung being its paragraph (md:paragraph)."""
        n = line_of(PLAN, "![막대]")
        body = json.dumps(
            {"doc": "nt", "file": str(self.src / "notes" / "plan.md"), "lo": n, "hi": n, "note": "그림"}
        ).encode()
        code, _, _ = self.talk(req("POST", "/api/pin", body, {"Content-Type": "application/json"}))
        self.assertEqual(code, 200)
        page = self.open(1)
        page.wait_for_function(DRAWN, timeout=20000)
        page.wait_for_function(PICS_DONE, timeout=10000)
        page.wait_for_function("!!document.querySelector('#md .md-pin .md-pic img')", timeout=8000)
        style = page.evaluate(
            "(()=>{const s=getComputedStyle(document.querySelector('#md .md-pin .md-pic img'));"
            " return [s.outlineStyle,s.outlineWidth];})()"
        )
        self.assertEqual(style, ["solid", "3px"])
        page.locator("#md .md-pic img").first.click()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo>0", timeout=5000)
        got = page.evaluate("[COMPOSE.current.lo,COMPOSE.current.hi,COMPOSE.current.scope]")
        self.assertEqual(got[:2], [n, n])


class ReadingSpot(AssetsBase):
    """An image that loads above the reading line leaves the text being read in place."""

    PLAN = TALL

    def test_an_image_above_the_reading_line_does_not_move_the_text(self):
        """The asset answer is held; the reading line is put on '## 읽는 곳', far below the image's kept place; then the
        image (900px tall, far more than its 8rem place) arrives. The heading stays where it was in the pane, to 2px.
        The browser's own scroll anchoring is off (overflow-anchor: none), as in a browser without it: Chromium's alone
        would hold the heading here and hide whether the viewer does (mdPicLoad)."""
        self.holding = True
        page = self.open(0)
        page.wait_for_function(DRAWN, timeout=20000)
        add_test_style(page, "#left,#left *{overflow-anchor:none}")
        settle(page)
        top = page.evaluate(
            "(()=>{const h=MD.heads.find(x=>x.title==='읽는 곳'),L=document.querySelector('#left');"
            " L.scrollTop+=h.el.getBoundingClientRect().top-L.getBoundingClientRect().top-40;"
            " return h.el.getBoundingClientRect().top-L.getBoundingClientRect().top;})()"
        )
        settle(page)
        self.assertTrue(self.hold, "the image was never asked for")
        page.wait_for_timeout(200)
        self.holding = False
        for r in self.hold:
            r.fulfill(**self.answer(r.request))
        page.wait_for_function(PICS_DONE + "&&!!document.querySelector('#md .md-pic-ok')", timeout=8000)
        settle(page)
        after = page.evaluate(
            "(()=>{const h=MD.heads.find(x=>x.title==='읽는 곳'),L=document.querySelector('#left');"
            " return h.el.getBoundingClientRect().top-L.getBoundingClientRect().top;})()"
        )
        self.assertAlmostEqual(after, top, delta=2)
        self.assertGreater(page.evaluate("document.querySelector('#md .md-pic img').height"), 300)


class ReadingSpotChangedImage(AssetsBase):
    """An image drawn at the size an earlier load learned, whose file has changed since, still leaves the text in place."""

    PLAN = TALL
    GUIDE = TALL_GUIDE

    def test_a_changed_image_drawn_at_its_known_size_does_not_move_the_text(self):
        """nt loads notes/img/tall.png at 200x900, so its size is known (MD_PIC_SIZE); the file is then replaced by a
        400x3600 image and gd, which shows the same image above its reading line, is opened: its box is drawn at the
        known 200x900. With the new answer held, the reading line is put on gd's '## 읽는 곳'; once the image arrives it
        takes its new size (400x3600), and the heading stays where it was in the pane, to 2px - drawn at the old size and
        left so, the image would grow to 200x1800 and push the heading 900px down. Scroll anchoring is off as in
        ReadingSpot."""
        page = self.open_md()
        self.assertEqual(page.evaluate("(s=>s&&[s.w,s.h])(MD_PIC_SIZE.get('notes/img/tall.png'))"), [200, 900])
        (self.src / "notes" / "img" / "tall.png").write_bytes(blank_png(400, 3600))
        add_test_style(page, "#left,#left *{overflow-anchor:none}")
        self.holding = True
        page.evaluate("void switchDoc('gd')")
        until(page, "DOC==='gd'&&" + DRAWN, 20)
        self.assertEqual(
            page.evaluate(
                "(i=>[i.parentElement.classList.contains('md-pic-ok'),i.getAttribute('width'),i.getAttribute('height')])"
                "(document.querySelector('#md .md-pic img'))"
            ),
            [True, "200", "900"],
        )
        end = time.monotonic() + 8
        while not self.hold:
            self.assertLess(time.monotonic(), end, "the image was never asked for")
            page.wait_for_timeout(50)
        settle(page)
        top = page.evaluate(
            "(()=>{const h=MD.heads.find(x=>x.title==='읽는 곳'),L=document.querySelector('#left');"
            " L.scrollTop+=h.el.getBoundingClientRect().top-L.getBoundingClientRect().top-40;"
            " return h.el.getBoundingClientRect().top-L.getBoundingClientRect().top;})()"
        )
        settle(page)
        page.wait_for_timeout(200)
        self.holding = False
        for r in self.hold:
            r.fulfill(**self.answer(r.request))
        until(page, PICS_DONE + "&&document.querySelector('#md .md-pic img').naturalWidth===400")
        settle(page)
        self.assertAlmostEqual(page.evaluate(HEADING_TOP), top, delta=2)
        self.assertEqual(
            page.evaluate(
                "(i=>[i.getAttribute('width'),i.getAttribute('height'),MD_PIC_SIZE.get('notes/img/tall.png').h])"
                "(document.querySelector('#md .md-pic img'))"
            ),
            ["400", "3600", 3600],
        )


class HeadingJump(AssetsBase):
    """A link's jump to another document's heading lands there, though images above it load on the way."""

    GUIDE = PICS_GUIDE

    def test_images_that_load_during_the_jump_do_not_stop_it_short(self):
        """nt's [안내의 설치] opens gd and scrolls smoothly (the default) to '## 설치', below six 900px images whose asset
        answers are held and let go every 60ms while the jump runs. Each load would put back the reading spot the scroll was
        passing and stop the jump far short of the heading (thousands of px); the jump goes on to the heading's new place
        and lands it 8px under the pane's top. A load seen while the heading was still far from there shows the answers
        did arrive mid-jump. The browser's scroll anchoring is left as it is."""
        for i in range(1, 7):
            (self.src / "notes" / "img" / ("p%d.png" % i)).write_bytes(blank_png(200, 900))
        page = self.open_md()
        page.evaluate(
            "window.__far=0; document.addEventListener('load',e=>{if(e.target.tagName!=='IMG'||DOC!=='gd')return;"
            " const h=MD.heads.find(x=>x.title==='설치'),L=document.querySelector('#left');"
            " if(h)__far=Math.max(__far,Math.abs(h.el.getBoundingClientRect().top-L.getBoundingClientRect().top-8));},true)"
        )
        self.holding = True
        page.locator("#md a.md-doclink").first.click()
        until(page, "DOC==='gd'&&" + DRAWN, 20)
        last, still = None, 0
        end = time.monotonic() + 15
        while still < 8:
            self.assertLess(time.monotonic(), end, "the pane never came to rest")
            page.wait_for_timeout(60)
            held, self.hold[:] = list(self.hold), []
            for r in held:
                r.fulfill(**self.answer(r.request))
            top = page.evaluate("document.querySelector('#left').scrollTop")
            still = still + 1 if top == last and not held else 0
            last = top
        self.assertGreater(page.evaluate("__far"), 200, "no image arrived during the jump")
        self.assertGreater(page.evaluate("document.querySelectorAll('#md .md-pic-ok').length"), 0)
        self.assertAlmostEqual(page.evaluate(SETUP_TOP), 8, delta=3)
        self.assertEqual(page.evaluate("document.querySelector('#section-current').textContent"), "설치")

    # Home with the focus on the page body scrolls the pane on the Linux hosts CI runs; on macOS it scrolls nothing at
    # all, so the hand this test needs the guard to see never arrives (measured twice: #left stayed where the jump left
    # it). The viewer promises no scrolling of its own for that key - it only reads a scroll the browser did - so there
    # is nothing to fix in the pane here; issue #414 collects what these host keys do differently on macOS.
    @unittest.skipIf(sys.platform == "darwin", "Home scrolls no pane on macOS: issue #414")
    def test_a_scrolling_key_with_the_focus_on_the_page_ends_the_jump(self):
        """The same jump, its images held: Home pressed while the focus is on the page's body (no key event reaches the pane)
        scrolls the pane back to its top, and that ends the jump - the images let go afterwards do not take the pane back
        down to the heading."""
        for i in range(1, 7):
            (self.src / "notes" / "img" / ("p%d.png" % i)).write_bytes(blank_png(200, 900))
        page = self.open_md()
        self.holding = True
        page.locator("#md a.md-doclink").first.click()
        until(page, "DOC==='gd'&&" + DRAWN, 20)
        until(page, "!!MD.goTo")
        page.evaluate("document.activeElement&&document.activeElement.blur()")
        self.assertTrue(page.evaluate("document.activeElement===document.body"))
        page.keyboard.press("Home")
        until(page, "document.querySelector('#left').scrollTop===0")
        self.assertFalse(page.evaluate("!!MD.goTo"))
        for _ in range(10):
            page.wait_for_timeout(60)
            held, self.hold[:] = list(self.hold), []
            for r in held:
                r.fulfill(**self.answer(r.request))
        settle(page)
        self.assertLess(page.evaluate("document.querySelector('#left').scrollTop"), 50)

    def test_a_scrolling_key_right_after_the_link_also_stops_the_asked_scroll(self):
        """Home pressed with the focus on the page's body as soon as the linked document is drawn - before the jump's
        smooth scroll has taken its first frame: the scroll asked for does not start afterwards, and the images let go
        later do not move the pane either (Firefox ran the asked scroll after the key's own, 1,798px down)."""
        for i in range(1, 7):
            (self.src / "notes" / "img" / ("p%d.png" % i)).write_bytes(blank_png(200, 900))
        page = self.open_md()
        self.holding = True
        page.locator("#md a.md-doclink").first.click()
        until(page, "DOC==='gd'&&" + DRAWN + "&&!!MD.goTo", 20)
        page.evaluate("document.activeElement&&document.activeElement.blur()")
        page.keyboard.press("Home")
        for _ in range(10):
            page.wait_for_timeout(60)
            held, self.hold[:] = list(self.hold), []
            for r in held:
                r.fulfill(**self.answer(r.request))
        settle(page)
        self.assertFalse(page.evaluate("!!MD.goTo"))
        self.assertLess(page.evaluate("document.querySelector('#left').scrollTop"), 50)


class SvgOnItsOwn(AssetsBase):
    """An SVG of the tree opened as a page (a new tab, a link to it) is inert under the asset route's own headers."""

    def enforce(self, route, strip=False):
        """Fulfil a viewer.test request with the handler's answer and every header it sent - the policy enforced, not
        reported (or left out, strip=True: the control)."""
        u = urlparse(route.request.url)
        self.asked.append(u.path)
        if u.netloc != "viewer.test":
            self.away.append(route.request.url)
            return route.abort()
        raw = (
            "GET %s HTTP/1.1\r\nHost: 127.0.0.1:18999\r\nTailscale-User-Login: %s\r\nTailscale-User-Name: %s\r\n\r\n"
            % (
                u.path + ("?" + u.query if u.query else ""),
                self.WHO["Tailscale-User-Login"],
                self.WHO["Tailscale-User-Name"],
            )
        ).encode("latin-1")
        code, hdrs, data = self.talk(raw)
        keep = {k: v for k, v in hdrs.items() if k not in ("content-length", "connection", "date", "server")}
        if strip:
            keep.pop("content-security-policy", None)
        return route.fulfill(status=code, headers=keep, body=data)

    def visit(self, strip):
        """A fresh page that opens notes/img/flow.svg on its own; (title, origin, requests other than the SVG)."""
        context = self.browser.new_context()
        self.addCleanup(context.close)
        # What the policy refuses there (the external image, Firefox's favicon request) is what the test provokes: the CSP
        # gate counts those reports as expected (helpers_csp).
        context.add_init_script("window.__limnCspExpected = true;")
        page = context.new_page()
        page.route("**/*", lambda r: self.enforce(r, strip))
        self.asked = []
        page.goto("http://viewer.test/api/asset?doc=nt&path=notes%2Fimg%2Fflow.svg")
        page.wait_for_timeout(500)
        return page.title(), page.evaluate("self.origin"), [p for p in self.asked if p != "/api/asset"]

    def test_an_svg_opened_on_its_own_runs_nothing_and_fetches_nothing(self):
        """Under the route's headers: no script ran (the title is not 'svg ran'), the origin is opaque ('null', the sandbox),
        and nothing was fetched - neither the script's nor the onload's request nor the external image. Without the policy
        the same file does run its script: the check sees what it guards."""
        title, origin, asked = self.visit(strip=False)
        self.assertNotEqual(title, "svg ran")
        self.assertEqual(origin, "null")
        self.assertEqual(asked, [])
        self.assertEqual(self.away, [])
        title, origin, asked = self.visit(strip=True)
        self.assertEqual(title, "svg ran")
        self.assertNotEqual(origin, "null")


class DocumentLinks(AssetsBase):
    """A link to another registered document goes there, at its heading, and back returns."""

    def test_a_link_goes_to_the_document_at_its_heading_and_back_returns(self):
        """Clicking [안내의 설치](../docs/guide.md#설치) on nt shows gd with '설치' at the reading line and #doc=gd in the
        address; the browser's back shows nt again; a link back from gd works the same way."""
        page = self.open_md()
        page.locator("#md a.md-doclink").first.click()
        page.wait_for_function("DOC==='gd'&&" + DRAWN, timeout=10000)
        page.wait_for_function("document.querySelector('#section-current').textContent==='설치'", timeout=8000)
        self.assertTrue(page.evaluate("location.hash").endswith("doc=gd"))
        page.go_back()
        page.wait_for_function("DOC==='nt'&&" + DRAWN, timeout=10000)
        page.locator("#md").wait_for()
        page.evaluate("document.querySelector('#left').scrollTop=0")
        page.wait_for_function("DOC==='nt'", timeout=5000)
        page.go_forward()
        page.wait_for_function("DOC==='gd'&&" + DRAWN, timeout=10000)
        page.locator("#md a.md-doclink").first.click()
        page.wait_for_function("DOC==='nt'&&" + DRAWN, timeout=10000)

    def test_back_before_the_linked_document_opens_stays_and_keeps_the_entry(self):
        """The link from nt to gd is followed while gd's meta answer is held, so gd has not opened; back returns the address
        to nt, which is still on screen. When gd's answer then arrives it opens nothing: nt stays, the entry back returned
        to still says #doc=nt, the history has no entry more or less, and forward still goes to gd."""
        page = self.open_md()
        self.hold_meta = "gd"
        depth = page.evaluate("history.length")
        page.locator("#md a.md-doclink").first.click()
        until(page, "location.hash.endsWith('doc=gd')")
        end = time.monotonic() + 8
        while not self.held_meta:
            self.assertLess(time.monotonic(), end, "gd's meta was never asked for")
            page.wait_for_timeout(50)
        self.assertEqual(page.evaluate("[DOC,history.length]"), ["nt", depth + 1])
        page.go_back()
        until(page, "location.hash.endsWith('doc=nt')")
        page.wait_for_timeout(100)
        self.hold_meta = None
        for r in self.held_meta:
            r.fulfill(**self.answer(r.request))
        page.wait_for_timeout(600)
        settle(page)
        self.assertEqual(
            page.evaluate("[DOC,MD.shown,location.hash.replace(/^.*doc=/,''),history.length]"),
            ["nt", "nt", "nt", depth + 1],
        )
        page.go_forward()
        until(page, "DOC==='gd'&&" + DRAWN, 10)
        self.assertTrue(page.evaluate("location.hash").endswith("doc=gd"))

    def test_a_double_click_on_a_pending_link_adds_one_entry_and_back_keeps_address_and_document_together(self):
        """The link from nt to gd is double-clicked while gd's meta answer is held: one history entry and one meta request,
        not two (two #doc=gd entries would let back move between equal addresses, with no hashchange, while the traversal
        ended the switch). Back returns the address to nt; once gd's answer arrives nt is on screen and in the address, and
        forward opens gd."""
        page = self.open_md()
        self.hold_meta = "gd"
        depth = page.evaluate("history.length")
        page.locator("#md a.md-doclink").first.dblclick()
        until(page, "location.hash.endsWith('doc=gd')")
        end = time.monotonic() + 8
        while not self.held_meta:
            self.assertLess(time.monotonic(), end, "gd's meta was never asked for")
            page.wait_for_timeout(50)
        page.wait_for_timeout(200)
        self.assertEqual(page.evaluate("[DOC,history.length]"), ["nt", depth + 1])
        self.assertEqual(len(self.held_meta), 1)
        page.go_back()
        until(page, "location.hash.endsWith('doc=nt')")
        page.wait_for_timeout(100)
        self.hold_meta = None
        for r in self.held_meta:
            r.fulfill(**self.answer(r.request))
        page.wait_for_timeout(600)
        settle(page)
        self.assertEqual(
            page.evaluate("[DOC,MD.shown,location.hash.replace(/^.*doc=/,''),history.length]"),
            ["nt", "nt", "nt", depth + 1],
        )
        page.go_forward()
        until(page, "DOC==='gd'&&" + DRAWN, 10)
        self.assertTrue(page.evaluate("location.hash").endswith("doc=gd"))

    def test_back_between_two_entries_of_one_address_shows_the_document_it_names(self):
        """Two entries that both say #doc=gd above nt's (as two follows of one link would leave them, the second while the
        address already named gd): back from the one to the other fires popstate but no hashchange. gd, which the address
        names, opens - nt is not left on screen under it."""
        page = self.open_md()
        page.evaluate("for(let i=0;i<2;i++)history.pushState(null,'',location.pathname+location.search+'#doc=gd')")
        self.assertEqual(page.evaluate("DOC"), "nt")
        page.go_back()
        until(page, "DOC==='gd'&&" + DRAWN, 10)
        self.assertTrue(page.evaluate("location.hash").endswith("doc=gd"))


# The phone of the back-layer test, and the page without CloseWatcher: the layer is then one history entry (gestures.js armBack).
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
NO_CLOSE_WATCHER = "delete window.CloseWatcher;"


class LinksUnderTheBackLayer(AssetsBase):
    """A link followed while a phone's back layer is open adds no history entry: the layer's entry stays the top one."""

    PLAN = "# 계획\n\n[안내로](../docs/guide.md)\n\n" + "".join("문단 %d.\n\n" % i for i in range(1, 40))

    def test_a_link_followed_under_the_open_sheet_adds_no_entry_and_back_closes_the_sheet(self):
        """On a phone without CloseWatcher the open sheet is one history entry (limnLayer). The link to gd, followed with
        the sheet open, shows gd without a history entry of its own: the length is the same and the top entry is still the
        layer's. Back then closes the sheet and leaves gd on screen - with an entry of the link's on top, back would have
        returned to nt and left the sheet open."""
        page = self.open(0, init=NO_CLOSE_WATCHER, **PHONE)
        until(page, DRAWN, 20)
        page.locator("#btn-side").tap()
        until(page, "SIDE_OPEN&&BACK&&BACK.kind==='history'&&!!(history.state&&history.state.limnLayer)")
        settle(page)
        depth = page.evaluate("history.length")
        page.locator("#md a.md-doclink").first.tap()
        until(page, "DOC==='gd'&&" + DRAWN, 10)
        settle(page)
        self.assertEqual(
            page.evaluate("[history.length,!!(history.state&&history.state.limnLayer),SIDE_OPEN,BACK&&BACK.kind]"),
            [depth, True, True, "history"],
        )
        page.go_back()
        until(page, "!SIDE_OPEN&&!BACK")
        settle(page)
        self.assertEqual(page.evaluate("[DOC,MD.shown,location.hash.replace(/^.*doc=/,'')]"), ["gd", "gd", "gd"])


class CrossOriginEmbed(AssetsBase):
    """Another origin's page cannot embed a tree image: the asset answer's Cross-Origin-Resource-Policy: same-origin, which
    the browser enforces on a real loopback listener (the routed pages of the other classes fulfil answers without it)."""

    def listen(self, handler) -> int:
        """Serve handler on a fresh 127.0.0.1 port for this test; the port."""
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(5)

        self.addCleanup(stop)
        return server.server_port

    def embed(self, page_url: str, image_url: str) -> int:
        """In a fresh context, closed after, the page at page_url puts an <img> of image_url in itself: its natural width
        once it has loaded or failed (0: not drawn)."""
        with self.browser.new_context() as context:
            page = context.new_page()
            page.set_default_timeout(8000)
            page.goto(page_url)
            return page.evaluate(
                "u=>new Promise(done=>{const i=document.createElement('img'); i.onload=i.onerror=()=>done(i.naturalWidth);"
                " i.src=u; document.body.append(i);})",
                image_url,
            )

    def test_another_origins_page_cannot_embed_a_tree_image_but_the_viewer_can(self):
        """Limn on 127.0.0.1:P, a plain page on another port Q. The viewer's own page (http://127.0.0.1:P/) draws
        notes/img/tall.png (200px wide; the document it opens shows other images, so its own requests are told apart); a
        page on port Q of the same host (127.0.0.1:Q) and of another host (localhost:Q) draw nothing, though the server
        answered each 200 - the browser refused the answer, not the server. With the header dropped from the same answers
        (the control), both pages draw it: the check sees what it guards. Firefox counts the two ports of 127.0.0.1 as one
        site, so there `same-site` would let the first page through; Chromium refuses it either way."""
        set_config(ps, auth="local", local_user="reader")
        answered: list[tuple[str, int]] = []
        drop: list[bool] = []

        class Listener(ps.Handler):
            """The production handler, noting each answer for the image, and dropping the resource policy when drop."""

            def send_response(self, code, message=None):
                if "tall.png" in self.path:
                    answered.append((self.path, code))
                super().send_response(code, message)

            def send_header(self, keyword, value):
                if drop and keyword.lower() == "cross-origin-resource-policy":
                    return
                super().send_header(keyword, value)

        limn = self.listen(Listener)
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        (other / "index.html").write_text("<!doctype html><title>Another site</title><p>x</p>", encoding="utf-8")
        port = self.listen(partial(http.server.SimpleHTTPRequestHandler, directory=str(other)))
        image = "http://127.0.0.1:%d/api/asset?doc=nt&path=notes%%2Fimg%%2Ftall.png" % limn
        pages = {"same host": "http://127.0.0.1:%d/" % port, "other host": "http://localhost:%d/" % port}
        self.assertEqual(self.embed("http://127.0.0.1:%d/" % limn, image), 200)
        for name, url in pages.items():
            with self.subTest(page=name):
                del answered[:]
                self.assertEqual(self.embed(url, image), 0)
                self.assertEqual([code for _, code in answered], [200])
        drop.append(True)
        for name, url in pages.items():
            with self.subTest(page=name, control="no resource policy"):
                self.assertEqual(self.embed(url, image), 200)


# An in-document link at the top to '## 끝', far below, with room under it: a jump the column's reflow must not cut short.
FAR_ANCHOR = (
    "# 위\n\n[끝으로](#끝)\n\n"
    + "".join(
        ("앞 문단 %d 은 폭이 바뀌면 다시 접히는 긴 문장으로 이어지고 또 이어진다. " % i) * 4 + "\n\n"
        for i in range(1, 160)
    )
    + "## 끝\n\n끝 문단.\n\n"
    + "".join("뒤 문단 %d.\n\n" % i for i in range(1, 60))
)
# Hidden characters (U+202E, the right-to-left override) in an image's alt text and source and in a link's '#…'.
RLO = "\u202e"
HIDDEN = "# 계획\n\n![가%s나](img/g%sone.png)\n\n[안내의 설치](../docs/guide.md#%s설치)\n" % (RLO, RLO, RLO)
# A text document whose lines look like an image and a link of Markdown.
TODO_TEXT = "할 일\n![막대](img/chart.png)\n[안내](../docs/guide.md#설치)\n"
TOP_OF = (
    "(t=>{const h=MD.heads.find(x=>x.title===t),L=document.querySelector('#left');"
    " return h.el.getBoundingClientRect().top-L.getBoundingClientRect().top;})"
)


def rest(page, timeout: float = 15.0):
    """Wait until the document pane's scroll offset has stood still for eight 60ms looks."""
    last, still, end = None, 0, time.monotonic() + timeout
    while still < 8:
        if time.monotonic() > end:
            raise AssertionError("the pane never came to rest")
        page.wait_for_timeout(60)
        top = page.evaluate("document.querySelector('#left').scrollTop")
        still = still + 1 if top == last else 0
        last = top


class OneReadingSpot(AssetsBase):
    """An image's load and #409's reading spot are one model (mdSpotBack puts back what mdSpotRead read, as mdSpotKeep does
    after a reflow): an image that loads while the column is hidden under the changes view leaves the text in place too."""

    PLAN = TALL

    def test_an_image_that_loads_under_the_changes_view_leaves_the_text_in_place(self):
        """The image's answer is held; the reading line is put on '## 읽는 곳'; the changes view is opened (the column is
        hidden, nothing can be measured) and the image (900px, far more than its 8rem place) arrives meanwhile. Back on the
        text at the same width, the heading is where it was, to 2px: the load marks the spot to be put back once the column
        is shown (again) - put back while hidden it moves nothing, and at the same width mdSpotKeep would keep nothing."""
        self.holding = True
        page = self.open(0)
        until(page, DRAWN, 20)
        add_test_style(page, "#left,#left *{overflow-anchor:none}")
        settle(page)
        top = page.evaluate(
            "(()=>{const h=MD.heads.find(x=>x.title==='읽는 곳'),L=document.querySelector('#left');"
            " L.scrollTop+=h.el.getBoundingClientRect().top-L.getBoundingClientRect().top-40;"
            " return h.el.getBoundingClientRect().top-L.getBoundingClientRect().top;})()"
        )
        settle(page)
        self.assertTrue(self.hold, "the image was never asked for")
        page.evaluate("setViewMode(VIEW_MODE.REVISIONS)")
        settle(page)
        self.assertFalse(page.evaluate("mdColumnShown()"))
        self.holding = False
        for r in self.hold:
            r.fulfill(**self.answer(r.request))
        until(page, PICS_DONE + "&&!!document.querySelector('#md .md-pic-ok')")
        settle(page)
        page.evaluate("setViewMode(VIEW_MODE.MANUSCRIPT)")
        settle(page)
        self.assertAlmostEqual(page.evaluate(HEADING_TOP), top, delta=2)
        self.assertGreater(page.evaluate("document.querySelector('#md .md-pic img').height"), 300)

    def test_badges_stand_before_their_blocks_and_follow_their_lines_when_the_image_loads(self):
        """Pins on the image's line and on a paragraph below it, the image held: each badge layer stands just before the
        block of its line (#409: Tab and a screen reader meet it there), and once the image takes its 900px the badges have
        followed their lines (the column's ResizeObserver), to 1px."""
        img, para = line_of(TALL, "![위 그림]"), line_of(TALL, "줄 3 의 문단.")
        for n in (img, para):
            body = json.dumps(
                {"doc": "nt", "file": str(self.src / "notes" / "plan.md"), "lo": n, "hi": n, "note": "핀"}
            ).encode()
            self.assertEqual(self.talk(req("POST", "/api/pin", body, {"Content-Type": "application/json"}))[0], 200)
        self.holding = True
        page = self.open(2)
        until(page, DRAWN + "&&document.querySelectorAll('#md .md-badge').length===2", 20)
        settle(page)
        place = (
            "[...document.querySelectorAll('#md .md-badge')].map(b=>{const p=PINS.find(x=>x.id===+b.dataset.id),"
            "e=mdLeaves(p.lo,p.lo)[0],box=b.parentElement;"
            " return [p.lo,box.nextElementSibling===mdTopBlock(document.querySelector('#md'),e),"
            "Math.round(b.getBoundingClientRect().top-e.getBoundingClientRect().top)];})"
        )
        before = page.evaluate(place)
        self.assertEqual([x[:2] for x in before], [[img, True], [para, True]])
        self.holding = False
        for r in self.hold:
            r.fulfill(**self.answer(r.request))
        until(page, PICS_DONE + "&&!!document.querySelector('#md .md-pic-ok')")
        page.wait_for_timeout(300)
        settle(page)
        after = page.evaluate(place)
        self.assertEqual([x[:2] for x in after], [[img, True], [para, True]])
        for (_, _, d0), (_, _, d1) in zip(before, after, strict=True):
            self.assertAlmostEqual(d1, d0, delta=1)
        self.assertTrue(page.evaluate("!!document.querySelector('#md .md-fig .md-pin .md-pic img')"))


class JumpAcrossReflow(AssetsBase):
    """A heading jump in flight is not cut short by the column's reflow: #409's mdSpotKeep would put back the reading spot
    the scroll was passing; it lets the jump go on to its heading's new place instead (mdGoOn)."""

    PLAN = FAR_ANCHOR

    def test_a_reflow_during_the_jump_lands_on_the_heading(self):
        """On a 1024x768 tablet, reading a little way down, [끝으로] is followed; once the smooth scroll is 1,000px on its
        way, [핀 N] collapses the panel beside the document and the column widens, its long paragraphs taking fewer lines.
        The pane comes to rest with '## 끝' 8px under its top and the jump ended - put back on the spot it was passing, the
        scroll stopped there, short of the heading, and the jump stayed in flight."""
        page = self.open(0, viewport={"width": 1024, "height": 768}, is_mobile=True, has_touch=True)
        until(page, DRAWN, 20)
        page.evaluate("document.querySelector('#left').scrollTop=300")
        settle(page)
        self.assertTrue(page.evaluate("SIDE_OPEN&&SMOOTH==='smooth'&&!!MD.spot&&!!MD.spot.el"))
        w0 = page.evaluate("document.querySelector('#md').getBoundingClientRect().width")
        page.evaluate("document.querySelector('#md a.md-anchor').click()")
        until(page, "document.querySelector('#left').scrollTop>1300")
        self.assertTrue(page.evaluate("!!MD.goTo"))
        page.evaluate("document.getElementById('btn-side').click()")
        rest(page)
        self.assertGreater(page.evaluate("document.querySelector('#md').getBoundingClientRect().width"), w0 + 50)
        self.assertAlmostEqual(page.evaluate(TOP_OF + "('끝')"), 8, delta=3)
        self.assertFalse(page.evaluate("!!MD.goTo"))


class HiddenCharsInTips(AssetsBase):
    """A tip that shows a source's text again - an image's path, a link's '#…', both decoded once - names its hidden
    characters (ccPlain, ADR-0029 D5); the alt text is drawn text, as the paragraph around it is (no marking yet)."""

    PLAN = HIDDEN

    def test_a_tip_names_a_right_to_left_override_and_the_drawn_alt_text_keeps_it(self):
        """The image the server refuses (no such file) and the link to gd's '#\u202e설치': their tips and tip URLs say
        '⟨U+202E⟩' and hold no U+202E; the alt text standing in for the image still holds the character itself."""
        page = self.open_md()
        until(page, "!!document.querySelector('#md .md-img')")
        got = page.evaluate(
            "(()=>{const i=document.querySelector('#md .md-img'),a=document.querySelector('#md a.md-doclink');"
            " return {tip:[i.dataset.tip,i.dataset.tipUrl,a.dataset.tip,a.dataset.tipUrl],alt:i.textContent};})()"
        )
        for t in got["tip"]:
            self.assertNotIn(RLO, t)
        self.assertIn("⟨U+202E⟩", got["tip"][0])
        self.assertIn("⟨U+202E⟩", got["tip"][1])
        self.assertTrue(got["tip"][2].endswith("#⟨U+202E⟩설치"), got["tip"][2])
        self.assertIn(RLO, got["alt"])


class FocusAfterALink(AssetsBase):
    """A document link followed from the keyboard goes away with its document: the focus is put where it led, the heading
    it names (as #409's focusPlace keeps the focus at the place after the composer closes), not left on the document area."""

    TODO = TODO_TEXT

    def test_enter_on_a_link_leaves_the_focus_on_its_heading(self):
        """Enter on nt's [안내의 설치]: once gd is drawn the focus is on its '## 설치' heading, and Tab goes on to gd's next
        link [계획으로] - left on the document area, Tab would start again at gd's first link, far above the heading."""
        page = self.open_md()
        page.locator("#md a.md-doclink[data-doc='gd']").focus()
        page.keyboard.press("Enter")
        until(page, "DOC==='gd'&&" + DRAWN, 20)
        until(page, "document.activeElement===MD.heads.find(x=>x.title==='설치').el")
        page.keyboard.press("Tab")
        self.assertTrue(page.evaluate("document.activeElement.matches('#md a.md-doclink[data-doc=nt]')"))

    def test_a_text_document_opens_with_its_lines_as_text_and_the_focus_on_the_document(self):
        """nt's [할 일](todo.txt) opens the registered text document td: its lines that read as an image and a link stay
        text (no image, no link, nothing asked of /api/asset for td), no heading is waited for, and the focus is on the
        document area."""
        page = self.open_md()
        page.locator("#md a.md-doclink[data-doc='td']").focus()
        page.keyboard.press("Enter")
        until(page, "DOC==='td'&&" + DRAWN, 20)
        settle(page)
        got = page.evaluate(
            "[document.querySelectorAll('#md img,#md a,#md .md-pic,#md .md-img').length,"
            " document.querySelector('#md').textContent.includes('![막대](img/chart.png)'), MD.headTo,"
            " document.activeElement===document.getElementById('left')]"
        )
        self.assertEqual(got, [0, True, None, True])
        self.assertEqual([a for a in self.asked if a.startswith("/api/asset") and "doc=td" in a], [])

    def test_a_draft_typed_into_while_the_source_is_on_its_way_keeps_the_focus(self):
        """gd has a draft (a note begun on its first paragraph, left by switching to nt). Enter on nt's link to gd brings the
        draft back while gd's source is held; the note is typed into; when the source arrives and gd is drawn, the focus
        stays in the note with its text - the link's arrival does not take it to the heading."""
        page = self.open_md()
        page.evaluate("void switchDoc('gd')")
        until(page, "DOC==='gd'&&" + DRAWN, 20)
        settle(page)
        page.locator("#md p").first.click()
        page.locator("#note").fill("kept draft")
        page.evaluate("void switchDoc('nt')")
        until(page, "DOC==='nt'&&" + DRAWN, 20)
        settle(page)
        self.hold_source = True
        page.locator("#md a.md-doclink[data-doc='gd']").focus()
        page.keyboard.press("Enter")
        until(page, "DOC==='gd'&&!!COMPOSE.current&&!document.querySelector('#md')")
        page.locator("#note").focus()
        page.keyboard.type(" and more")
        self.assertTrue(self.source_held, "gd's source was not held")
        self.hold_source = False
        for r in self.source_held:
            r.fulfill(**self.answer(r.request))
        until(page, "DOC==='gd'&&" + DRAWN, 20)
        settle(page)
        self.assertEqual(
            page.evaluate("[document.activeElement.id, document.getElementById('note').value]"),
            ["note", "kept draft and more"],
        )


class TreeImagesFirefox(TreeImages):
    """The tree images, the alt texts and their reasons, the image link and the image's pin in Firefox."""

    BROWSER_ENGINE = "firefox"


class ReadingSpotFirefox(ReadingSpot):
    """The reading spot an image's load puts back, in Firefox (its own scroll anchoring off, as in Chromium)."""

    BROWSER_ENGINE = "firefox"


class HeadingJumpFirefox(HeadingJump):
    """A heading jump that images interrupt on the way, in Firefox."""

    BROWSER_ENGINE = "firefox"


class SvgOnItsOwnFirefox(SvgOnItsOwn):
    """The SVG opened on its own, inert under the asset route's headers, in Firefox."""

    BROWSER_ENGINE = "firefox"


class DocumentLinksFirefox(DocumentLinks):
    """Links between documents and the browser's back, in Firefox."""

    BROWSER_ENGINE = "firefox"


class CrossOriginEmbedFirefox(CrossOriginEmbed):
    """The resource policy enforced by Firefox's own networking."""

    BROWSER_ENGINE = "firefox"
