"""Images of the manuscript tree and links between registered documents on the Markdown surface, in the browser
(docs/adr/0030-markdown-tree-images-and-document-links.md, docs/handbook/viewer.md §Markdown 화면).

The real viewer against the in-process server (BrowserBase), on two Markdown documents of one tree - notes/plan.md (nt) and
docs/guide.md (gd) - and the LaTeX manuscript (ms):

- a tree image is an <img> from this origin's GET /api/asset; a remote, data:, out-of-tree or missing image is its alt
  text saying why, and nothing is asked of another host - not even by the SVG, whose script and external image never run;
- an SVG opened on its own, with the asset route's own headers enforced, runs no script, fetches nothing and has an opaque
  origin; the same SVG without those headers does run (the test can see what it guards);
- an image that loads above the reading line leaves the text being read where it was, also when it is drawn at a size an
  earlier load learned and the file has since changed, and when it shrinks near the document's end and the browser cuts
  the pane's offset back to the new end (ShrinkNearTheEnd);
- a move of the pane whose animation frame has not come yet when an image changes size - the page's frames held, as on
  a renderer too busy to paint - is not undone: Home and End (HeadingJump, ShrinkNearTheEnd), the browser's find in page
  (FindBeforeTheFrame), a pin's [보기] and [바뀐 곳] (ShrinkNearTheEnd), and a pin's [보기] followed by a reflow
  (JumpThenReflow); nor is Home undone after an image that loaded on the way of a heading jump (HeadingJump);
- a web font that swaps in before such a frame, its reflow at the same width cutting the pane's offset back to a shorter
  document's end, is no move: an image that loads next puts back the line read before the font, the reflow above that
  line or below it (FontSwapAbove, FontSwapBelow); Home pressed after that cut is a move all the same (FontSwapAbove),
  and so is Home after a run of raw HTML blocks opened or closed, which moves the column's height and no offset
  (HtmlRunToggle);
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
- a tree image rewritten on disk shows without a reload: the light poll asks the images near the document area again,
  one whose ETag moved on is loaded from a new address, the reading line stays, and a redraw keeps the new picture; the
  check asks only images near the area, at most MD_PIC_CHECK.max of them, and not twice within MD_PIC_CHECK.gap
  (ChangedOnDisk); on a real loopback listener, where the browser keeps its HTTP cache, the tag of the picture shown is
  read from the answer its <img> left there, and with nothing cached (the cache cleared, or off) a changed image still
  shows on the first check (ChangedOnDiskCached);
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
from helpers_browser import BrowserBase, booted, settle, watch_idle
from helpers_csp import add_test_style
from helpers_figure import BUILD1, viewer_build

DRAWN = "typeof MD!=='undefined'&&MD.shown===DOC&&!!document.querySelector('#md')&&!MD.job"
# Every tree image on screen has loaded or failed (a failed one is replaced by its alt text).
PICS_DONE = "[...document.querySelectorAll('#md .md-pic img')].every(i=>i.complete)"
# Holds the page's animation frames from window.__framesHeld on - as a renderer too busy to paint holds them - until
# window.__framesGo() lets them run (cancelAnimationFrame still cancels a held one); counts the images that load or fail
# (window.__picDone). A test lets the held work go by that count, never by a clock.
FRAMES_HELD = (
    "(()=>{const raf=window.requestAnimationFrame.bind(window),caf=window.cancelAnimationFrame.bind(window),q=new Map();"
    "let n=0;window.__framesHeld=false;window.__picDone=0;"
    "window.requestAnimationFrame=cb=>{if(!window.__framesHeld)return raf(cb);q.set(--n,cb);return n;};"
    "window.cancelAnimationFrame=id=>{if(id<0)q.delete(id);else caf(id);};"
    "window.__framesGo=()=>{window.__framesHeld=false;const l=[...q.values()];q.clear();l.forEach(cb=>raf(cb));};"
    "for(const t of ['load','error'])document.addEventListener(t,e=>{if(e.target.tagName==='IMG')window.__picDone++;},true);})()"
)
# The line element at the document area's top (mdAt): its first line, and how far above the area's top it starts, in px.
TOP_LINE = (
    "(()=>{const t=document.querySelector('#left').getBoundingClientRect().top,e=mdAt(mdLineEls(),t);"
    " return e?[+(e.dataset.line||e.dataset.lo),t-e.getBoundingClientRect().top]:[0,0];})()"
)
# How far the pane is from its end, in px.
FROM_END = "(L=>L.scrollHeight-L.clientHeight-L.scrollTop)(document.querySelector('#left'))"
# Where the first element of source line n is in the document pane, in px from 30% down it (where [보기] puts a line).
AT_DEPTH = (
    "(n=>{const r=document.querySelector('#left').getBoundingClientRect();"
    " return mdLeaves(n,n)[0].getBoundingClientRect().top-(r.top+r.height*0.30);})"
)
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


def pictures(routes) -> int:
    """How many of the held routes are an <img>'s own asks - the loads or failures their answers bring
    (window.__picDone) - and not the read of a loaded picture's tag (mdPicSeen's fetch of the same address)."""
    return sum(r.request.resource_type == "image" for r in routes)


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


# Room above an image near the reading line, the image, the heading the reading line is put on, and far below it a second
# image that a scroll to the end loads.
NEAR = (
    "# 가까운 그림\n\n"
    + "".join("위 %d 의 문단.\n\n" % i for i in range(1, 30))
    + "![가까이](img/near.png)\n\n문단 가.\n\n문단 나.\n\n## 읽는 곳\n\n여기.\n\n"
    + "".join("아래 %d 의 문단.\n\n" % i for i in range(1, 90))
    + "![멀리](img/far.png)\n\n끝.\n"
)
# Where '## 읽는 곳' and the near image are in the document pane, in px from the pane's top.
NEAR_TOP = "(()=>{const L=document.querySelector('#left').getBoundingClientRect().top,h=MD.heads.find(x=>x.title==='읽는 곳');return h.el.getBoundingClientRect().top-L;})()"
NEAR_IMG = "document.querySelector(\"#md .md-pic[data-path='notes/img/near.png'] img\")"
# One check now, whatever the last one's time: how many images it gave a new address, and how many requests it made.
CHECK = "(async()=>{MD_PIC_CHECK.last=-Infinity; const a=MD_PIC_CHECK.asked,n=await mdPicCheck(); return [n,MD_PIC_CHECK.asked-a];})()"


class ChangedOnDisk(AssetsBase):
    """A tree image rewritten on disk while its document is open shows without a reload, and the text stays in place.
    Routed: the cache-only read of an image's tag when it loads (mdPicSeen) is answered by the route, from the server."""

    PLAN = NEAR

    def setUp(self):
        super().setUp()
        (self.src / "notes" / "img" / "near.png").write_bytes(blank_png(200, 300))
        (self.src / "notes" / "img" / "far.png").write_bytes(blank_png(50, 50))

    def open_md(self, **kw):
        """The viewer on nt, drawn (far.png, lazy and far below, has not loaded: AssetsBase's wait would never end)."""
        page = self.open(0, **kw)
        until(page, DRAWN, 20)
        settle(page)
        return page

    def assets_asked(self) -> list[str]:
        """The /api/asset requests made so far, by address."""
        return [a for a in self.asked if a.startswith("/api/asset?")]

    def test_a_rewritten_image_shows_on_the_light_poll_and_the_reading_line_stays(self):
        """The reading line on '## 읽는 곳', the near image just above the document area (within one area's height); a first
        check finds the tag learned when it loaded (mdPicSeen) and changes nothing. near.png is then rewritten 200x700 (400px taller); the light poll (pollLight) asks it again, loads it from
        its address with &v=<its new tag>, and the heading stays where it was in the pane, to 2px (the browser's scroll
        anchoring off, as in ReadingSpot). A check of the unchanged image gives no new address. A redraw (the source
        edited) draws the new picture again, at its new address. Mutations: drop the light poll's mdPicCheck (polling.js)
        -> the image never changes, fails; draw a redraw's image at mdAssetUrl instead of mdPicUrl -> the old picture
        comes back, fails."""
        page = self.open_md()
        add_test_style(page, "#left,#left *{overflow-anchor:none}")
        page.evaluate(
            "(()=>{const h=MD.heads.find(x=>x.title==='읽는 곳'),L=document.querySelector('#left');"
            " L.scrollTop+=h.el.getBoundingClientRect().top-L.getBoundingClientRect().top-40;})()"
        )
        until(page, NEAR_IMG + ".complete&&" + NEAR_IMG + ".naturalHeight===300")
        settle(page)
        # Wholly above the area's top and within one area's height of it: near enough to be asked, and what its new size
        # would move is the text being read.
        pane = page.evaluate("(r=>[r.top,r.height])(document.querySelector('#left').getBoundingClientRect())")
        bottom = page.evaluate(NEAR_IMG + ".getBoundingClientRect().bottom")
        self.assertLess(bottom, pane[0])
        self.assertGreater(bottom, pane[0] - pane[1])
        # Its tag known since it loaded; the server's is the same, and nothing changed.
        self.assertEqual(page.evaluate(CHECK), [0, 1])
        top = page.evaluate(NEAR_TOP)
        (self.src / "notes" / "img" / "near.png").write_bytes(blank_png(200, 700))
        page.evaluate("MD_PIC_CHECK.last=-Infinity; void pollLight()")
        until(page, NEAR_IMG + ".naturalHeight===700", 10)
        settle(page)
        src = page.evaluate(NEAR_IMG + ".getAttribute('src')")
        self.assertRegex(src, r"^/api/asset\?doc=nt&path=notes%2Fimg%2Fnear\.png&v=[0-9a-f]{24}$")
        self.assertAlmostEqual(page.evaluate(NEAR_TOP), top, delta=2)
        self.assertEqual(page.evaluate(CHECK)[0], 0)
        self.assertEqual(page.evaluate(NEAR_IMG + ".getAttribute('src')"), src)
        self.md_append(page)
        until(page, NEAR_IMG + "&&" + NEAR_IMG + ".complete&&" + NEAR_IMG + ".naturalHeight===700", 10)
        self.assertEqual(page.evaluate(NEAR_IMG + ".getAttribute('src')"), src)

    def md_append(self, page):
        """notes/plan.md gets one more line at its end; the light poll draws it again."""
        plan = self.src / "notes" / "plan.md"
        plan.write_text(plan.read_text(encoding="utf-8") + "\n더한 줄.\n", encoding="utf-8")
        page.evaluate("void pollLight()")
        until(page, "MD.lines.some(l=>l==='더한 줄.')&&" + DRAWN, 10)

    def test_a_check_asks_only_images_near_the_area_a_few_at_a_time_and_not_too_often(self):
        """far.png, loaded by a scroll to the end and then far below the area again, is not asked; near.png is, one request
        a check (its shown tag is known since it loaded). A second check within MD_PIC_CHECK.gap asks
        nothing. With nine images on screen, one check asks at most MD_PIC_CHECK.max of them, and the next check starts
        with the three it left, so two checks ask all nine. The requests counted are the ones the route saw. Mutations:
        drop the distance test -> far.png is asked, fails; drop the count bound -> all nine are asked, fails; drop the gap
        -> the second check asks again, fails; drop the least-recently-asked order -> the second check asks the same six,
        fails; keep the turns of images no longer in the document -> near.png stays in the record, fails."""
        page = self.open_md()
        page.evaluate("document.querySelector('#left').scrollTop=document.querySelector('#left').scrollHeight")
        far = "document.querySelector(\"#md .md-pic[data-path='notes/img/far.png'] img\")"
        until(page, far + ".complete&&" + far + ".naturalWidth===50")
        page.evaluate(
            "(()=>{const h=MD.heads.find(x=>x.title==='읽는 곳'),L=document.querySelector('#left');"
            " L.scrollTop+=h.el.getBoundingClientRect().top-L.getBoundingClientRect().top-40;})()"
        )
        until(page, NEAR_IMG + ".complete&&" + NEAR_IMG + ".naturalHeight===300")
        settle(page)
        before = len(self.assets_asked())
        self.assertEqual(page.evaluate(CHECK), [0, 1])
        asked = self.assets_asked()[before:]
        self.assertEqual(len(asked), 1)
        self.assertTrue(all("near.png" in a for a in asked), asked)
        self.assertEqual(
            page.evaluate(
                "(async()=>{const a=MD_PIC_CHECK.asked; await mdPicCheck(); return MD_PIC_CHECK.asked-a;})()"
            ),
            0,
        )
        self.assertEqual(page.evaluate(CHECK), [0, 1])
        many = "# 여럿\n\n" + "".join("![%d](img/s%d.png)\n\n" % (i, i) for i in range(9))
        for i in range(9):
            (self.src / "notes" / "img" / ("s%d.png" % i)).write_bytes(blank_png(30, 30))
        (self.src / "notes" / "plan.md").write_text(many, encoding="utf-8")
        page.evaluate("void pollLight()")
        until(
            page,
            "document.querySelectorAll('#md .md-pic img').length===9&&[...document.querySelectorAll('#md .md-pic img')].every(i=>i.complete&&i.naturalWidth)",
            10,
        )
        page.evaluate("document.querySelector('#left').scrollTop=0")
        settle(page)
        self.assertEqual(  # all nine inside the area, so the order among them is the rotation's alone
            page.evaluate(
                "(()=>{const r=document.querySelector('#left').getBoundingClientRect();"
                " return [...document.querySelectorAll('#md .md-pic img')].filter(i=>{const b=i.getBoundingClientRect();"
                " return b.top>=r.top&&b.bottom<=r.bottom;}).length;})()"
            ),
            9,
        )
        before = len(self.assets_asked())
        self.assertEqual(page.evaluate(CHECK), [0, 6])
        first = {a for a in self.assets_asked()[before:]}
        self.assertEqual(len(first), 6)
        before = len(self.assets_asked())
        self.assertEqual(page.evaluate(CHECK), [0, 6])
        second = {a for a in self.assets_asked()[before:]}
        self.assertEqual(len(second), 6)
        self.assertEqual(len(first | second), 9, (sorted(first), sorted(second)))
        # near.png, asked before the rewrite and no longer in the document, has no turn kept: the record is the nine
        self.assertEqual(
            page.evaluate("[...MD_PIC_CHECK.at.get('nt').keys()].sort()"),
            sorted("notes/img/s%d.png" % i for i in range(9)),
        )


class ChangedOnDiskFirefox(ChangedOnDisk):
    """The same in Firefox."""

    BROWSER_ENGINE = "firefox"


# Room above an image, the image, and below it about one and a half document areas of paragraphs: read 200px before the
# document's end, the image stands wholly above the area and within one area's height of it - near enough for a check to
# ask it again (mdPicCheck), from the very end too - and once it is 880px shorter the pane's end is above that offset.
END_NEAR = (
    "# 끝 가까이\n\n"
    + "".join("위 %d 의 문단.\n\n" % i for i in range(1, 30))
    + "![줄어들 그림](img/shrink.png)\n\n"
    + "".join("아래 %d 의 문단.\n\n" % i for i in range(1, 18))
)
SHRINK_IMG = "document.querySelector(\"#md .md-pic[data-path='notes/img/shrink.png'] img\")"
LAST_LINE = line_of(END_NEAR, "아래 17 의 문단.")


class ShrinkNearTheEnd(AssetsBase):
    """An image above the reading line that gets shorter near the document's end: the browser cuts the pane's offset back
    to its new end, which is the layout's doing and no scroll - the text being read stays. A move made just before it, its
    frame not come (the page's frames held): End still ends at the end, and a pin's [보기] and [바뀐 곳] keep their line
    where the jump put it. The image is rewritten smaller on disk and a check shows it (mdPicCheck, as ChangedOnDisk), the
    browser's scroll anchoring off as in ReadingSpot - Chromium's and Firefox's alone would cut nothing (they keep the
    text by moving the offset), and a browser without it (WebKit) is what this stands in for."""

    PLAN = END_NEAR

    def setUp(self):
        super().setUp()
        (self.src / "notes" / "img" / "shrink.png").write_bytes(blank_png(200, 900))

    def read_near_the_end(self, **kw):
        """The viewer on nt, anchoring off, the image loaded at 900px, the pane about 200px before its end - the area's top
        halfway down the line it falls on, so the spot names a point inside that line (frac between 0 and 1) - and
        settled, the reading spot read there; the image wholly above the area and within one area's height of it, also
        from the end."""
        page = self.open(0, **kw)
        until(page, DRAWN, 20)
        add_test_style(page, "#left,#left *{overflow-anchor:none}")
        page.evaluate("(L=>{L.scrollTop=L.scrollHeight;})(document.querySelector('#left'))")
        until(page, SHRINK_IMG + ".complete&&" + SHRINK_IMG + ".naturalHeight===900")
        settle(page)
        page.evaluate(
            "(L=>{L.scrollTop=L.scrollHeight-L.clientHeight-200; const t=L.getBoundingClientRect().top,"
            " r=mdAt(mdLineEls(),t).getBoundingClientRect(); L.scrollTop+=Math.round(r.top+r.height/2-t);})"
            "(document.querySelector('#left'))"
        )
        settle(page)
        self.assertTrue(150 < page.evaluate(FROM_END) < 250)
        self.assertTrue(page.evaluate("MD.spot.frac>0&&MD.spot.frac<1"))
        pane = page.evaluate("(r=>[r.top,r.height])(document.querySelector('#left').getBoundingClientRect())")
        bottom = page.evaluate(SHRINK_IMG + ".getBoundingClientRect().bottom")
        self.assertLess(bottom, pane[0])
        self.assertGreater(bottom, pane[0] - pane[1] + 200)
        return page

    def shrink(self, page):
        """shrink.png rewritten 200x20, a check asked now; once the image stands at its new size (mdPicLoad has run)."""
        (self.src / "notes" / "img" / "shrink.png").write_bytes(blank_png(200, 20))
        page.evaluate("MD_PIC_CHECK.last=-Infinity; void mdPicCheck()")
        until(page, SHRINK_IMG + ".naturalHeight===20&&" + SHRINK_IMG + ".getAttribute('height')==='20'", 10)

    def test_an_image_that_shrinks_near_the_end_leaves_the_text_in_place(self):
        """Read 200px before the end, the image above the area becomes 200x20: the document is 880px shorter and the browser
        cuts the pane's offset back to the new end (680px), the top line standing 200px further on. That cut is the
        layout's, so the spot read before is put back: the line at the area's top is the one read before, as far into it,
        to 2px, and the pane stands as far before the new end. Main passes this (it never compares offsets); it guards the
        fix's own hole, #433's first one: the cut taken for a move. Two things keep it apart, either alone enough: the box
        takes the new picture's shape only in the handler, after the check before the change (mdPicSize), and that check
        (mdSpotFresh) knows a cut - the offset read before beyond the pane's new end, the pane at that end. Mutation:
        neither (no aspect ratio held, no cut check) -> at the load the offset is already cut, the check takes it for a
        move and reads the spot there, the top line L85 for L75, fails."""
        page = self.read_near_the_end()
        before, gap = page.evaluate(TOP_LINE), page.evaluate(FROM_END)
        self.shrink(page)
        settle(page)
        after = page.evaluate(TOP_LINE)
        self.assertEqual(after[0], before[0])
        self.assertAlmostEqual(after[1], before[1], delta=2)
        self.assertAlmostEqual(page.evaluate(FROM_END), gap, delta=2)

    @unittest.skipIf(sys.platform == "darwin", "End scrolls no pane on macOS: issue #414")
    def test_end_pressed_just_before_the_shrink_leaves_the_pane_at_the_end(self):
        """The same shrink on a renderer too busy to paint: the page's frames are held, End is pressed with the focus on the
        document area (as a search or a link leaves it) - the pane goes to its end, its scroll not read yet - and then the
        image shrinks. The pane stands elsewhere than where the spot was read, so the spot is read there before the image
        changes, and put back after: the pane stays at the end, also once the frames run. End's offset falls in the room
        below a line, past the element's end: the spot keeps those px too (past). The pane is at its end but the offset
        read before is not beyond it - no cut - so End is a move. Mutations: no check before the change (mdSpotFresh) ->
        the spot read before End is put back, 217px above the new end, fails; no past -> 8px above it, fails; the cut
        told by the pane at its end alone -> End taken for a cut, 217px, fails; no aspect ratio held (mdPicSize) -> the
        box takes its new shape before the load, and its cut, beyond the offset read before End, is taken for the
        layout's and End goes back with it, 217px, fails."""
        page = self.read_near_the_end(init=FRAMES_HELD)
        page.evaluate(
            "(L=>{L.tabIndex=-1; L.focus({preventScroll:true});})(document.querySelector('#left')); window.__framesHeld=true"
        )
        page.keyboard.press("End")
        until(page, FROM_END + "<1")
        # the key's scroll is not read yet
        self.assertNotEqual(page.evaluate("MD.spot.line"), page.evaluate(TOP_LINE)[0])
        self.shrink(page)
        self.assertAlmostEqual(page.evaluate(FROM_END), 0, delta=1)
        page.evaluate("window.__framesGo()")
        settle(page)
        self.assertAlmostEqual(page.evaluate(FROM_END), 0, delta=1)

    def test_a_pins_jump_just_before_the_shrink_keeps_the_pins_line_where_the_jump_put_it(self):
        """A pin on the document's last paragraph, its [보기] with the frames held (jumpPin -> mdJump): the jump puts the
        pin's line 30% down the area, some 70px before the end, and the image shrinks before the scroll's frame - the
        browser cuts the offset back to the new end. The pin's line stands where the jump put it, to 2px, also once the
        frames run. Mutations: neither the read where the jump lands (mdShowLines) nor the check before the change
        (mdSpotFresh) -> the spot read before the jump is put back, the line 160px below, fails, and either alone holds
        it; neither an aspect ratio held (mdPicSize) nor the cut check -> the offset is cut before the load and read as
        the jump's, the line 367px off, fails, and either alone holds it."""
        body = json.dumps(
            {"doc": "nt", "file": str(self.src / "notes" / "plan.md"), "lo": LAST_LINE, "hi": LAST_LINE, "note": "끝"}
        ).encode()
        code, _, out = self.talk(req("POST", "/api/pin", body, {"Content-Type": "application/json"}))
        self.assertEqual(code, 200, out)
        page = self.read_near_the_end(init=FRAMES_HELD)
        until(page, "PINS.length===1")
        page.evaluate("window.__framesHeld=true; jumpPin(%d)" % json.loads(out)["id"])
        self.at_the_jumps_depth_after_the_shrink(page)

    def test_the_changed_place_just_before_the_shrink_stays_where_the_jump_put_it(self):
        """[바뀐 곳] of a change on the document's last paragraph, with the frames held (updGoNext): its line goes 30% down
        the area, and the image shrinks before the scroll's frame. The line stands where the jump put it, to 2px, also
        once the frames run. The changed place is set on the page (UPD.lines) as a redraw that found it sets it: what is
        read here is the jump, not how a change is found (test_viewer_updates.py). Mutations as for the pin's [보기]:
        neither the read in mdShowLines nor mdSpotFresh -> 160px, fails; neither an aspect ratio held nor the cut check
        -> 58px, fails."""
        page = self.read_near_the_end(init=FRAMES_HELD)
        page.evaluate(
            "window.__framesHeld=true; UPD.lines.set('nt',{base:[],ranges:[{lo:%d,hi:%d}],at:-1}); updGoNext('nt')"
            % (LAST_LINE, LAST_LINE)
        )
        self.at_the_jumps_depth_after_the_shrink(page)

    def at_the_jumps_depth_after_the_shrink(self, page):
        """The last paragraph put 30% down the area by a jump not yet read by a frame, short of the end: once the image
        shrinks it is still there, to 2px, and once the frames run it still is."""
        at = AT_DEPTH + "(%d)" % LAST_LINE
        self.assertAlmostEqual(page.evaluate(at), 0, delta=1)
        self.assertGreater(page.evaluate(FROM_END), 0)
        self.shrink(page)
        self.assertAlmostEqual(page.evaluate(at), 0, delta=2)
        page.evaluate("window.__framesGo()")
        settle(page)
        self.assertAlmostEqual(page.evaluate(at), 0, delta=2)


class ShrinkNearTheEndFirefox(ShrinkNearTheEnd):
    """The same in Firefox."""

    BROWSER_ENGINE = "firefox"


# Paragraphs of narrow letters, which a monospace fallback face sets on about twice as many lines as the bundled face
# (Pretendard) does, and one-line paragraphs, whose height no face changes (the column's line height is a number,
# md-surface.css). Above the reading line an image, then the narrow paragraphs, then the short ones, read in near the
# end: the font's reflow is all above the line.
LATE_FACE = (
    "# Font\n\n![image](img/tall.png)\n\n"
    + "".join("Narrow %d: " % i + "il " * 300 + "\n\n" for i in range(1, 9))
    + "".join("Short %d.\n\n" % i for i in range(1, 60))
)
# The short paragraphs first, the narrow ones below them and the image at the document's end: read in the short ones
# about 200px before the end, the font's reflow is all below the reading line, and so is the image.
LATE_FACE_BELOW = (
    "# Font\n\n"
    + "".join("Short %d.\n\n" % i for i in range(1, 40))
    + "".join("Narrow %d: " % i + "il " * 100 + "\n\n" for i in range(1, 4))
    + "![image](img/tall.png)\n"
)
# The line element at the document area's top: its first line, how far down it the top is as a share of its height (the
# reading spot's frac), and that height in px.
TOP_SHARE = (
    "(()=>{const t=document.querySelector('#left').getBoundingClientRect().top,e=mdAt(mdLineEls(),t),"
    "r=e.getBoundingClientRect(); return [+(e.dataset.line||e.dataset.lo),(t-r.top)/r.height,r.height];})()"
)
# How far down #md the reading spot's element starts, in px.
SPOT_IN_MD = "MD.spot.el.getBoundingClientRect().top-document.querySelector('#md').getBoundingClientRect().top"
# The pane's scroll offset, in px.
PANE_TOP = "document.querySelector('#left').scrollTop"


def answer_the_image(test, page, check):
    """The page's frames held: every held asset answer let go (tall.png's box from 8rem to 900px), check() once it stands
    at its size, before any frame, and again once the frames run and the page settles."""
    test.holding = False
    held, test.hold[:] = list(test.hold), []
    test.assertTrue(held)
    page.evaluate("window.__picDone=0")
    for r in held:
        r.fulfill(**test.answer(r.request))
    until(page, "window.__picDone>=1&&!!document.querySelector('#md .md-pic-ok')")
    check()
    page.evaluate("window.__framesGo()")
    settle(page)
    check()


def home_before_the_frame(test, page):
    """The page's frames held: Home pressed with the focus on the document area (as a search or a link leaves it), the pane
    at its top and its scroll not read yet - the spot still the line read before."""
    line = page.evaluate("MD.spot.line")
    test.assertGreater(line, 0)
    page.evaluate("(L=>{L.tabIndex=-1; L.focus({preventScroll:true});})(document.querySelector('#left'))")
    page.keyboard.press("Home")
    until(page, PANE_TOP + "===0")
    test.assertEqual(page.evaluate("MD.spot.line"), line)


class FontSwap(AssetsBase):
    """A web font that swaps in before a scroll's frame - the page's frames held, as on a renderer too busy to paint -
    sets paragraphs on fewer lines at the same width: the document gets shorter and, read 200px before its end, the
    browser cuts the pane's offset back to the new end. The reflow and its cut are no person's move, and the line read
    before the font stays the reading spot until an image that loads next puts it back (FontSwapAbove, FontSwapBelow).
    The bundled face's answers are held from the start, the column's fallback face is monospace (wider than Pretendard
    whatever the machine's sans-serif is: Chromium's own fallback on a Linux host set these letters much as Pretendard
    does, and no reflow followed) and the browser's scroll anchoring is off (as ShrinkNearTheEnd); tall.png is held
    too."""

    # The test's own style: the browser's scroll anchoring off, the column's fallback face monospace.
    STYLE = '#left,#left *{overflow-anchor:none} #md{font-family:"Pretendard Variable",monospace}'

    def read_before_the_font(self):
        """The viewer on nt, the face and tall.png held, the pane halfway down the line about 200px before its end and
        the spot read there by the scroll's frame; the page, and that line as TOP_SHARE gives it."""
        self.faces: list = []
        self.holding_faces = True

        def route(r):
            if self.holding_faces and urlparse(r.request.url).path.endswith(".woff2"):
                self.faces.append(r)
                return None
            return self.route(r)

        self.holding = True
        context = self.browser.new_context(viewport={"width": 1400, "height": 850})
        self.addCleanup(context.close)
        context.add_init_script(FRAMES_HELD)
        watch_idle(context)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.route("**/*", route)
        page.goto("http://viewer.test/?lang=en", wait_until="domcontentloaded")  # the load event would wait on the face
        until(page, DRAWN + "&&" + booted(0), 20)
        add_test_style(page, self.STYLE)
        until(page, "document.fonts.status==='loading'")
        # tall.png is lazy: asked once it comes near the area, and not if the pane leaves it first
        page.evaluate("document.querySelector('#md .md-pic img').scrollIntoView({block:'nearest'})")
        end = time.monotonic() + 10
        while not self.hold:
            self.assertLess(time.monotonic(), end, "tall.png was never asked for")
            page.wait_for_timeout(50)
        page.evaluate(
            "(L=>{L.scrollTop=L.scrollHeight-L.clientHeight-200; const t=L.getBoundingClientRect().top,"
            " r=mdAt(mdLineEls(),t).getBoundingClientRect(); L.scrollTop+=Math.round(r.top+r.height/2-t);})"
            "(document.querySelector('#left'))"
        )
        # two frames: the scroll's has read the spot there
        page.evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
        before = page.evaluate(TOP_SHARE)
        self.assertTrue(150 < page.evaluate(FROM_END) < 250)
        self.assertEqual(page.evaluate("MD.spot.line"), before[0])
        self.assertTrue(0.2 < before[1] < 0.8)
        self.assertGreater(before[0], line_of(self.PLAN, "Short 1."))
        return page, before

    def let_the_font_go(self, page, before):
        """The frames held, the face let go: once it is laid out the document is shorter, the pane cut back to its new
        end and another line at the area's top, the spot not read since."""
        page.evaluate("window.__framesHeld=true")
        held, self.faces[:] = list(self.faces), []
        self.holding_faces = False
        self.assertTrue(held)
        for r in held:
            r.fulfill(**self.answer(r.request))
        until(page, "document.fonts.status==='loaded'", 10)
        until(page, FROM_END + "<1")
        self.assertNotEqual(page.evaluate(TOP_SHARE)[0], before[0])
        self.assertEqual(page.evaluate("MD.spot.line"), before[0])

    def let_the_image_go(self, page, before):
        """tall.png answered before any frame (its box from 8rem to 900px): the line read before the font is back at the
        area's top, also once the frames run."""
        answer_the_image(self, page, lambda: self.at_the_line_read_before(page, before))

    def at_the_line_read_before(self, page, before):
        """The line read before the font at the area's top, the top as far down it (its share of the line's height now),
        to 2px."""
        now = page.evaluate(TOP_SHARE)
        self.assertEqual(now[0], before[0])
        self.assertAlmostEqual(now[1] * now[2], before[1] * now[2], delta=2)


class FontSwapAbove(FontSwap):
    """The font's reflow and the image above the reading line (the review's case)."""

    PLAN = LATE_FACE

    def test_an_image_after_a_fonts_reflow_above_puts_back_the_line_read_before_it(self):
        """The narrow paragraphs above get thousands of px shorter and the pane is cut back to the new end, some lines
        on. tall.png then loads above: the check before its box changes (mdSpotFresh) finds the offset read before
        beyond what the pane can scroll now and the pane at its end - the cut - and keeps the spot, and the put-back
        after the change (mdSpotBack) brings that line back, as far down it, to 2px. Mutation: no cut check (the offset
        compared alone, the branch before the fix) -> the cut offset is taken for a move and read, the top line five
        short paragraphs on (L127 for L117), fails; in Firefox with its own fallback face as well (the review's L123,
        frac 0.41 for 0.68)."""
        page, before = self.read_before_the_font()
        self.let_the_font_go(page, before)
        self.let_the_image_go(page, before)

    @unittest.skipIf(sys.platform == "darwin", "Home scrolls no pane on macOS: issue #414")
    def test_home_after_a_fonts_cut_is_not_undone_by_the_image(self):
        """The same cut, then Home before any frame: the pane stands at its top, no longer at the end the font cut it
        back to, so the check before tall.png's change takes that for the key's move and reads the spot there - the pane
        stays at the top, also once the frames run. Mutations: the cut told by the offset read beyond the pane's end
        alone, without the pane standing at that end -> the spot read before the font is kept and put back, the pane
        4,385px down, fails; the height check of the branch before (#md's height compared with the spot's: a font's
        reflow, the offset not trusted) -> the same, fails."""
        page, before = self.read_before_the_font()
        self.let_the_font_go(page, before)
        home_before_the_frame(self, page)
        answer_the_image(self, page, lambda: self.assertAlmostEqual(page.evaluate(PANE_TOP), 0, delta=1))


class FontSwapBelow(FontSwap):
    """The font's reflow and the image below the reading line: the spot's element keeps its place in #md. The pane's
    room after the document (60vh, frame.css) is taken away, so that what the font shortens within the area's height
    below the line is enough to cut the offset: with the room, hardly a screen's text is left below a line read near the
    end."""

    PLAN = LATE_FACE_BELOW
    STYLE = FontSwap.STYLE + " #left{padding-bottom:0}"

    def test_an_image_after_a_fonts_reflow_below_puts_back_the_line_read_before_it(self):
        """The narrow paragraphs below get some hundreds of px shorter: the pane is cut back to the new end, some lines
        before the one read, which keeps its place in #md. tall.png then loads at the end, the room to put that line
        back: the cut check keeps the spot and the put-back brings it back, to 2px. Mutation: no cut check -> the cut
        offset is read as a move and an earlier line put back (L61 for L63), fails."""
        page, before = self.read_before_the_font()
        self.assertLess(before[0], line_of(LATE_FACE_BELOW, "Narrow 1:"))
        at = page.evaluate(SPOT_IN_MD)
        self.let_the_font_go(page, before)
        self.assertAlmostEqual(page.evaluate(SPOT_IN_MD), at, delta=0.5)
        self.let_the_image_go(page, before)


class FontSwapAboveFirefox(FontSwapAbove):
    """The same in Firefox."""

    BROWSER_ENGINE = "firefox"


class FontSwapBelowFirefox(FontSwapBelow):
    """The same in Firefox."""

    BROWSER_ENGINE = "firefox"


# A tall image, twelve paragraphs, a run of twenty raw HTML blocks - one closed placeholder (mdHtmlRunEl), some 1,600px
# taller open - and more paragraphs below it.
HTML_RUN = (
    "# Fold\n\n![image](img/tall.png)\n\n"
    + "".join("Paragraph %d.\n\n" % i for i in range(1, 13))
    + "".join("<div>raw %d</div>\n\n" % i for i in range(1, 21))
    + "".join("After %d.\n\n" % i for i in range(1, 81))
)


class HtmlRunToggle(AssetsBase):
    """A run of raw HTML blocks opened or closed (mdHtmlRun) below the reading line: #md gets some 1,600px taller or
    shorter at the same width and the pane's offset stays, so no scroll's frame reads the spot again. Home is then
    pressed before any frame (the page's frames held) and tall.png, above the line read before, loads: the pane stays at
    the top. The browser's scroll anchoring is left as it is."""

    PLAN = HTML_RUN

    @unittest.skipIf(sys.platform == "darwin", "Home scrolls no pane on macOS: issue #414")
    def test_home_after_a_run_is_opened_is_not_undone_by_an_image(self):
        """The run opened, then Home and tall.png's load before any frame: the check before the image's change
        (mdSpotFresh) finds the pane elsewhere than where the spot was read, and that offset not cut back to an end, so
        it reads the spot at the top and the pane stays there. Mutation: the height check of the branch before (#md's
        height compared with the spot's: a height the page changed without reading the spot again taken for a web
        font's reflow) -> the spot read before Home is kept and put back, the pane 1,452px down, fails, in both engines;
        the branch before the height check passes it (the review's case)."""
        self.home_after_the_run(open_first=False)

    @unittest.skipIf(sys.platform == "darwin", "Home scrolls no pane on macOS: issue #414")
    def test_home_after_a_run_is_closed_is_not_undone_by_an_image(self):
        """The same with the run opened first, the spot read there, and then closed: #md gets shorter, no offset is cut
        (the pane is far from its end) and Home stays at the top. Same mutation -> 1,452px, fails."""
        self.home_after_the_run(open_first=True)

    def home_after_the_run(self, open_first):
        """tall.png held from the start; the run opened first when open_first; the run's button 40px under the area's
        top and the spot read there by the scroll's frame; the button pressed - the run opens or closes, #md's height
        moves, the offset and the spot stay; then Home and tall.png's answer before any frame: the pane at its top."""
        self.holding = True
        page = self.open(0, init=FRAMES_HELD)
        until(page, DRAWN, 20)
        end = time.monotonic() + 10
        while not self.hold:  # tall.png asked, and held
            self.assertLess(time.monotonic(), end, "tall.png was never asked for")
            page.wait_for_timeout(50)
        settle(page)
        button = page.locator("#md .md-html-sum")
        self.assertEqual(button.count(), 1)
        if open_first:
            button.click()
            until(page, "document.querySelector('#md .md-html-sum').getAttribute('aria-expanded')==='true'")
        page.evaluate(
            "(L=>{const b=document.querySelector('#md .md-html-sum');"
            " L.scrollTop+=b.getBoundingClientRect().top-L.getBoundingClientRect().top-40;})(document.querySelector('#left'))"
        )
        settle(page)
        top, height, line = page.evaluate(
            "[document.querySelector('#left').scrollTop,document.querySelector('#md').getBoundingClientRect().height,"
            "MD.spot.line]"
        )
        self.assertGreater(top, 0)
        self.assertLess(line, line_of(HTML_RUN, "<div>raw 1<"))
        button.click()
        until(
            page,
            "document.querySelector('#md .md-html-sum').getAttribute('aria-expanded')==='%s'"
            % ("false" if open_first else "true"),
        )
        settle(page)
        self.assertGreater(
            abs(page.evaluate("document.querySelector('#md').getBoundingClientRect().height") - height), 1000
        )
        self.assertEqual(page.evaluate(PANE_TOP), top)
        self.assertEqual(page.evaluate("MD.spot.line"), line)
        page.evaluate("window.__framesHeld=true")
        home_before_the_frame(self, page)
        answer_the_image(self, page, lambda: self.assertAlmostEqual(page.evaluate(PANE_TOP), 0, delta=1))


class HtmlRunToggleFirefox(HtmlRunToggle):
    """The same in Firefox."""

    BROWSER_ENGINE = "firefox"


class ErrorOnAJumpThenEnd(AssetsBase):
    """An image that fails during a jump to a heading (mdGoHeading) - its file broken on disk, found by the page's check
    (mdPicCheck) - gives way to its alt text and makes the document some 2,800px shorter, cutting the pane's offset back to
    the new end. End is then pressed, and another image's held answer let go before any frame (the page's frames held):
    the pane stays at the end. Found by the review of #435's third round."""

    PLAN = "# Start\n\n![late](img/late.png)\n\n![shrink](img/shrink.png)\n\n" + "".join(
        "Paragraph %d.\n\n" % i for i in range(1, 20)
    )

    def route(self, route):
        """late.png's answer held while self.hold_late; every other request as AssetsBase answers it."""
        if getattr(self, "hold_late", False) and "late.png" in route.request.url:
            self.hold.append(route)
            return None
        return super().route(route)

    @unittest.skipIf(sys.platform == "darwin", "End scrolls no pane on macOS: issue #414")
    def test_end_after_an_image_failed_on_a_jump_is_not_undone_by_the_next_image(self):
        """The pane 200px above its end; the heading jump starts and shrink.png fails on the way (the alt text in its place,
        the offset cut back to the shorter end); End; late.png loads: the pane is still at the end, before the frames run
        and after. The failed image's handler reads the spot where the jump left the pane (mdPicMoved), so End is a move
        from that spot, not the browser's cut. Mutation: no reading after an image's change during a jump (the image
        handlers' mdSpotBack only when no jump) -> the spot keeps the offset read before the cut, End's offset is taken
        for the cut, and late.png's load puts the pane back 200px above the end; fails in both engines."""
        img = self.src / "notes" / "img"
        (img / "late.png").write_bytes(blank_png(200, 900))
        (img / "shrink.png").write_bytes(blank_png(200, 3000))
        self.hold_late = True
        page = self.open(0, init=FRAMES_HELD)
        until(page, DRAWN, 20)
        until(page, "!!document.querySelector('#md .md-pic-ok')")
        page.evaluate("(L=>{L.scrollTop=L.scrollHeight-L.clientHeight-200;})(document.querySelector('#left'))")
        settle(page)
        before = page.evaluate("document.querySelector('#left').scrollHeight")
        (img / "shrink.png").write_bytes(blank_png(200, 3000)[:33])  # a PNG cut short: the browser cannot draw it
        page.evaluate("window.__framesHeld=true; MD_PIC_CHECK.last=-Infinity; mdGoHeading(0); void mdPicCheck()")
        until(page, "!document.querySelector('#md .md-pic[data-path=\"notes/img/shrink.png\"]')")
        self.assertTrue(page.evaluate("!!MD.goTo"), "the jump had ended before the image failed")
        self.assertGreater(before - page.evaluate("document.querySelector('#left').scrollHeight"), 2000)
        page.evaluate("(L=>{L.tabIndex=-1; L.focus({preventScroll:true});})(document.querySelector('#left'))")
        page.keyboard.press("End")
        until(page, FROM_END + "<1")
        self.assertFalse(page.evaluate("!!MD.goTo"), "End did not end the jump")
        self.hold_late = False
        self.holding = True  # answer_the_image lets go of the held late.png
        answer_the_image(self, page, lambda: self.assertAlmostEqual(page.evaluate(FROM_END), 0, delta=2))


class ErrorOnAJumpThenEndFirefox(ErrorOnAJumpThenEnd):
    """The same in Firefox."""

    BROWSER_ENGINE = "firefox"


MANY = 300  # more than MD_PIC_KEEP (256), the most entries the page's other image records keep


class ManyImagesTakeTurns(AssetsBase):
    """More tree images on screen than a bounded record would hold: the checks, MD_PIC_CHECK.max a time, still ask every
    one in turn."""

    PLAN = "# 여럿\n\n" + "".join("![%d](img/m%d.png)" % (i, i) for i in range(MANY)) + "\n"

    def setUp(self):
        super().setUp()
        for i in range(MANY):
            (self.src / "notes" / "img" / ("m%d.png" % i)).write_bytes(blank_png(10, 10))

    def test_every_one_of_three_hundred_visible_images_is_asked_once_in_fifty_checks(self):
        """300 images of 10x10 in one paragraph, all inside the document area. The page's mdPicTag is wrapped to record
        the path of each check's request (cache 'no-cache'; the read of a loaded image's tag is 'only-if-cached'). Fifty
        checks of six ask all 300, each once. Mutation: keep the turns in one map bounded to MD_PIC_KEEP entries
        (mdPicKeep) -> past 256 the first images' turns are dropped, they count as never asked and are asked again, and
        the last ones never are, fails."""
        page = self.open(0)
        until(page, DRAWN, 20)
        until(
            page,
            "document.querySelectorAll('#md .md-pic img').length===%d&&[...document.querySelectorAll('#md .md-pic img')]"
            ".every(i=>i.complete&&i.naturalWidth===10)" % MANY,
            30,
        )
        settle(page)
        self.assertEqual(
            page.evaluate(
                "(()=>{const r=document.querySelector('#left').getBoundingClientRect();"
                " return [...document.querySelectorAll('#md .md-pic img')].filter(i=>{const b=i.getBoundingClientRect();"
                " return b.top>=r.top&&b.bottom<=r.bottom;}).length;})()"
            ),
            MANY,
        )
        page.evaluate(
            "(()=>{window.__asked=[]; const o=mdPicTag; mdPicTag=(u,c)=>{"
            "if(c==='no-cache')__asked.push(new URL(u,location.href).searchParams.get('path')); return o(u,c);};})()"
        )
        for _ in range(MANY // 6):
            self.assertEqual(page.evaluate(CHECK)[1], 6)
        asked = page.evaluate("__asked")
        self.assertEqual(len(asked), MANY)
        self.assertEqual(len(set(asked)), MANY, sorted({a for a in asked if asked.count(a) > 1}))


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
    # all (measured twice: #left stayed where the jump left it), so this test's premise - the pane back at its top -
    # cannot hold there. Only that premise is lost: the jump is dropped by the key's own keydown and not by the scroll
    # it causes (js/md-surface.js), so "the key ends the asked jump and the images let go later do not move the pane"
    # is still read on every host by the test right below, which asserts no scroll of its own. The viewer promises no
    # scrolling for this key - it only reads one the browser did - so there is nothing to fix in the pane; issue #414
    # collects what these host keys do differently on macOS.
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

    @unittest.skipIf(sys.platform == "darwin", "Home scrolls no pane on macOS: issue #414")
    def test_images_that_load_before_the_keys_scroll_is_read_leave_the_pane_at_the_top(self):
        """The Home of the test above on a renderer too busy to paint: the page's frames are held from just before the
        key, so its scroll to the top is not read yet (the spot is still a line below the top) when the images let go
        load. The pane stands elsewhere than where the spot was read, so the spot is read there - the very top - before
        each image changes size, and put back after: the pane stays at the top, also once the frames run. Mutation: no
        check before the change (mdSpotFresh) -> the loads take the pane back down to the line read before the key,
        398-1,230px, fails. On a busy runner that was this class's flake (1,817px, 2,947px)."""
        self.home_before_the_frame(lambda r: r.fulfill(**self.answer(r.request)))

    @unittest.skipIf(sys.platform == "darwin", "Home scrolls no pane on macOS: issue #414")
    def test_images_that_fail_before_the_keys_scroll_is_read_leave_the_pane_at_the_top(self):
        """The same with images the server does not give: each becomes its alt text (mdPicError), which puts the spot
        back the same way. Same mutation -> fails."""
        self.home_before_the_frame(lambda r: r.fulfill(status=404, body=""))

    @unittest.skipIf(sys.platform == "darwin", "Home scrolls no pane on macOS: issue #414")
    def test_an_image_that_loads_on_the_jumps_way_leaves_home_at_the_top(self):
        """The Home of the tests above after one held image has loaded on the jump's way, the frames already held: the
        jump goes on to its heading (mdGoOn) and nothing reads the spot after that change, so when the other images load
        after Home the check before each (mdSpotFresh) has the column's height moved since the spot was read - and the
        pane at its top, far from any end: the key's move. Mutation: the height check of the branch before (#md's height
        compared with the spot's) -> that change is taken for a font's reflow, the spot read before Home kept and put
        back, the pane 398-2,818px below the top, fails. Main and the branch before the height check pass it."""
        self.home_before_the_frame(lambda r: r.fulfill(**self.answer(r.request)), on_the_way=1)

    @unittest.skipIf(sys.platform == "darwin", "Home scrolls no pane on macOS: issue #414")
    def test_an_image_that_fails_on_the_jumps_way_leaves_home_at_the_top(self):
        """The same with images the server does not give (mdPicError). Same mutation -> fails."""
        self.home_before_the_frame(lambda r: r.fulfill(status=404, body=""), on_the_way=1)

    def home_before_the_frame(self, answer, on_the_way=0):
        """The jump with its images held; frames held, the first on_the_way held images answered by answer while the
        jump is still on, Home, then every other held image answered by answer before any frame."""
        for i in range(1, 7):
            (self.src / "notes" / "img" / ("p%d.png" % i)).write_bytes(blank_png(200, 900))
        page = self.open_md(init=FRAMES_HELD)
        self.holding = True
        page.locator("#md a.md-doclink").first.click()
        until(page, "DOC==='gd'&&" + DRAWN, 20)
        until(
            page, "!!MD.goTo&&document.querySelector('#left').scrollTop>200"
        )  # on its way, its spot read below the top
        page.evaluate("document.activeElement&&document.activeElement.blur(); window.__framesHeld=true")
        if on_the_way:
            self.assertGreater(len(self.hold), on_the_way)  # and some left for after Home
            held, self.hold[:] = self.hold[:on_the_way], self.hold[on_the_way:]
            page.evaluate("window.__picDone=0")
            for r in held:
                answer(r)
            until(page, "window.__picDone>=%d" % pictures(held))
            self.assertTrue(page.evaluate("!!MD.goTo"))  # still on its way: the frame that would land it is held
        page.keyboard.press("Home")
        until(page, "document.querySelector('#left').scrollTop===0")
        self.assertTrue(page.evaluate("!MD.goTo&&!!MD.spot&&!!MD.spot.el"))  # the key's scroll is not read yet
        held, self.hold[:] = list(self.hold), []
        self.assertTrue(held)
        page.evaluate("window.__picDone=0")
        for r in held:
            answer(r)
        until(page, "window.__picDone>=%d" % pictures(held))
        self.assertEqual(page.evaluate("document.querySelector('#left').scrollTop"), 0)
        page.evaluate("window.__framesGo()")
        self.holding = False  # what the grown images bring into reach loads as it comes, and so does what is still held
        held, self.hold[:] = list(self.hold), []
        for r in held:
            answer(r)
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


def listen(test, handler) -> int:
    """Serve handler on a fresh 127.0.0.1 port for test (stopped at its cleanup); the port."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def stop():
        server.shutdown()
        server.server_close()
        thread.join(5)

    test.addCleanup(stop)
    return server.server_port


# The one tree image of LIVE_PLAN, and the width it shows.
LIVE_IMG = "document.querySelector(\"#md .md-pic[data-path='notes/img/live.png'] img\")"
LIVE_W = "(i=>i&&i.complete?i.naturalWidth:0)(" + LIVE_IMG + ")"


class ChangedOnDiskCached(AssetsBase):
    """The light poll's check on a real loopback listener, where the browser keeps its HTTP cache: a routed page has none
    (Playwright's routing turns it off), so ChangedOnDisk never sees what the cache holds, or does not."""

    PLAN = "# 그림\n\n![살아 있는](img/live.png)\n\n끝.\n"

    def setUp(self):
        super().setUp()
        (self.src / "notes" / "img" / "live.png").write_bytes(blank_png(120, 40))

    def open_live(self, cache_off: bool = False):
        """The viewer on nt from a real listener (no routing), its image drawn 120px wide, the light poll's own checks held
        off (MD_PIC_CHECK.gap: only CHECK runs one) -> (page, context). cache_off: the browser's cache turned off (CDP
        Network.setCacheDisabled, as DevTools' 'Disable cache') before the page loads; Chromium only."""
        set_config(ps, auth="local", local_user="reader")
        port = listen(self, ps.Handler)
        context = self.browser.new_context(viewport={"width": 1400, "height": 850})
        self.addCleanup(context.close)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        if cache_off:
            cdp = context.new_cdp_session(page)
            cdp.send("Network.enable")
            cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        page.goto("http://127.0.0.1:%d/?lang=ko" % port)
        until(page, "typeof MD_PIC_CHECK!=='undefined'", 20)
        page.evaluate("MD_PIC_CHECK.gap=Infinity")
        until(page, DRAWN, 20)
        until(page, LIVE_W + "===120", 10)
        self.assertNotIn("&v=", page.evaluate(LIVE_IMG + ".getAttribute('src')"))
        return page, context

    def checks_until(self, page, width: int, times: int = 3) -> int:
        """Up to times checks, one after another, until the image shows width px: the checks it took (times + 1: never)."""
        for n in range(1, times + 1):
            page.evaluate(CHECK)
            try:
                until(page, LIVE_W + "===%d" % width, 3)
                return n
            except AssertionError:
                continue
        return times + 1

    def test_an_unchanged_image_is_asked_once_and_not_moved(self):
        """Once live.png has loaded, the tag of the picture it shows is known from the answer its <img> left in the cache
        (mdPicSeen): the first check asks the server once, finds the same tag and leaves the image at its address - no
        second download. Mutation: drop mdPicSeen from mdPicLoad -> the shown tag is unknown, the check moves the image to
        a new address, fails."""
        page, _ = self.open_live()
        src = page.evaluate(LIVE_IMG + ".getAttribute('src')")
        until(page, "MD_PIC_TAG.has(%s)" % json.dumps(src), 5)
        self.assertEqual(page.evaluate(CHECK), [0, 1])
        self.assertEqual(page.evaluate(LIVE_IMG + ".getAttribute('src')"), src)

    def test_an_image_changed_after_the_cache_was_cleared_still_shows(self):
        """The browser's cache cleared (CDP Network.clearBrowserCache) before the first check, then live.png rewritten 230px
        wide: the first check gives it its new address and the new picture shows. Before, the first check asked the cache
        for the shown picture's tag (cache:'force-cache'); with nothing cached the server's answer - the new tag - stood for
        the old picture and every later check matched it, so the 120px picture stayed for good (Codex's repro: three
        checks). Mutation: read the shown tag at the first check with cache:'force-cache' and no record at load (the code
        before) -> it stays 120px, fails."""
        page, context = self.open_live()
        until(page, "MD_PIC_TAG.size===1", 5)
        context.new_cdp_session(page).send("Network.clearBrowserCache")
        (self.src / "notes" / "img" / "live.png").write_bytes(blank_png(230, 40))
        self.assertEqual(self.checks_until(page, 230), 1)

    def test_with_the_cache_off_a_changed_image_shows_on_the_first_check(self):
        """The cache off before the page loads (CDP Network.setCacheDisabled, as DevTools' 'Disable cache'): the <img>
        leaves no answer to read, so the shown tag is unknown. live.png rewritten 230px wide before the first check: that
        check does not take the server's tag for the shown one but moves the image to the tag's address, and the new
        picture shows; the next check, the tag now known, moves nothing. Mutation: take an unknown shown tag from the
        server's answer (MD_PIC_TAG.get(url)||tag) -> it stays 120px, fails."""
        page, _ = self.open_live(cache_off=True)
        # nothing cached to read (a cache-only read after mdPicSeen's own fails too), and so no shown tag known
        self.assertEqual(
            page.evaluate(
                "fetch("
                + LIVE_IMG
                + ".getAttribute('src'),{cache:'only-if-cached',mode:'same-origin'}).then(()=>1,()=>0)"
            ),
            0,
        )
        self.assertEqual(page.evaluate("MD_PIC_TAG.size"), 0)
        (self.src / "notes" / "img" / "live.png").write_bytes(blank_png(230, 40))
        self.assertEqual(self.checks_until(page, 230), 1)
        self.assertEqual(page.evaluate(CHECK), [0, 1])


class ChangedOnDiskCachedFirefox(ChangedOnDiskCached):
    """The same in Firefox, where no CDP clears or turns off the cache: the check of an unchanged image."""

    BROWSER_ENGINE = "firefox"

    test_an_image_changed_after_the_cache_was_cleared_still_shows = None  # type: ignore[assignment]
    test_with_the_cache_off_a_changed_image_shows_on_the_first_check = None  # type: ignore[assignment]


class CrossOriginEmbed(AssetsBase):
    """Another origin's page cannot embed a tree image: the asset answer's Cross-Origin-Resource-Policy: same-origin, which
    the browser enforces on a real loopback listener (the routed pages of the other classes fulfil answers without it)."""

    def listen(self, handler) -> int:
        """Serve handler on a fresh 127.0.0.1 port for this test; the port."""
        return listen(self, handler)

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


# An image at the top, the reading line below it, and far below that a sentence the browser's find in page goes to.
FIND = (
    "# 찾기\n\n![위 그림](img/tall.png)\n\n"
    + "".join("줄 %d 의 문단.\n\n" % i for i in range(1, 80))
    + "찾을 문장은 여기에 있다.\n\n"
    + "".join("뒤 %d 의 문단.\n\n" % i for i in range(1, 40))
)
# Where the found sentence's paragraph is in the document pane, in px from the pane's top.
FOUND_TOP = (
    "(()=>{const p=[...document.querySelectorAll('#md p')].find(e=>e.textContent.startsWith('찾을 문장')),"
    "L=document.querySelector('#left'); return p.getBoundingClientRect().top-L.getBoundingClientRect().top;})()"
)


class FindBeforeTheFrame(AssetsBase):
    """The browser's find in page moves the pane with no input the viewer hears - only its scroll, a frame later. An image
    that loads before that frame does not take the pane back to where the spot was read before the find. Chromium's
    window.find() selects the match but scrolls only the page's root, never a scroller inside it such as the document
    area (Firefox's scrolls both, on its next refresh), so here the match is then scrolled into view, centred, as
    Chrome's own find bar reveals it: an input-less move all the same."""

    PLAN = FIND
    # Shows the selected match in Chromium (REVEAL: None where window.find() scrolls the document area itself).
    REVEAL: str | None = "getSelection().getRangeAt(0).startContainer.parentElement.scrollIntoView({block:'center'})"

    def test_a_found_sentence_stays_where_find_put_it_when_an_image_loads_before_the_frame(self):
        """The image's answer held, the reading line a little below its kept place (the browser's scroll anchoring off, as
        in ReadingSpot), the page's frames held: window.find() goes to a sentence some 2,500px below and the pane follows,
        its scroll not read yet. Then the image arrives, 900px for its 8rem place, above both: the found sentence stays
        where find put it, to 2px, also once the frames run. Mutations: no check before the change (mdSpotFresh) -> the
        spot read before the find is put back, the sentence 2,700px off, fails; read the spot where the pane stands after
        the change instead (#433's first try) -> 772px off, the image's growth, fails; no px past a line's end in the spot
        (past) -> 6-7px off, fails."""
        read = line_of(FIND, "줄 3 의")
        self.holding = True
        page = self.open(0, init=FRAMES_HELD)
        until(page, DRAWN, 20)
        add_test_style(page, "#left,#left *{overflow-anchor:none}")
        page.evaluate(
            "(()=>{const e=document.querySelector(\"#md [data-line='%d']\"),L=document.querySelector('#left');"
            " L.scrollTop+=e.getBoundingClientRect().top-L.getBoundingClientRect().top+5;})()" % read
        )
        settle(page)
        self.assertTrue(self.hold, "the image was never asked for")
        pane = page.evaluate("(r=>[r.top,r.height])(document.querySelector('#left').getBoundingClientRect())")
        self.assertLess(page.evaluate("document.querySelector('#md .md-pic').getBoundingClientRect().bottom"), pane[0])
        self.assertGreater(page.evaluate(FOUND_TOP), 2 * pane[1])
        page.evaluate("window.__framesHeld=true")
        self.assertTrue(page.evaluate("window.find('찾을 문장은')"))
        if self.REVEAL:
            page.evaluate(self.REVEAL)
        found = until(page, "(t=>t>0&&t<%d&&t)(%s)" % (pane[1] - 40, FOUND_TOP))
        # the find's scroll is not read yet
        self.assertTrue(page.evaluate("MD.spot.line===%d" % read))
        self.holding = False
        page.evaluate("window.__picDone=0")
        for r in self.hold:
            r.fulfill(**self.answer(r.request))
        until(page, "window.__picDone>=1&&!!document.querySelector('#md .md-pic-ok')")
        self.assertAlmostEqual(page.evaluate(FOUND_TOP), found, delta=2)
        page.evaluate("window.__framesGo()")
        settle(page)
        self.assertAlmostEqual(page.evaluate(FOUND_TOP), found, delta=2)
        self.assertGreater(page.evaluate("document.querySelector('#md .md-pic img').height"), 300)


class FindBeforeTheFrameFirefox(FindBeforeTheFrame):
    """The same in Firefox, whose window.find() scrolls the document area to the match itself."""

    BROWSER_ENGINE = "firefox"
    REVEAL = None


class JumpThenReflow(AssetsBase):
    """A pin's [보기] whose scroll a frame has not read yet, then the column's width changes: the reflow puts back the spot
    the jump put the pane at, not the one read before it."""

    PLAN = FAR_ANCHOR

    def test_a_reflow_right_after_a_pins_jump_keeps_the_pins_line_in_view(self):
        """A pin on '끝 문단.', far below; reading at the top of a 1440px window, the page's frames held, its [보기]
        (jumpPin -> mdJump) puts the line 30% down the area; the window is then narrowed to 1000px before any frame, the
        column narrower and its long paragraphs taking more lines (mdSpotKeep from the column's ResizeObserver). The line
        at the area's top is the one the jump put there, and the pin's line is on screen, also once the frames run. No
        image changes here, so mdSpotFresh has no say: the read where the jump lands alone holds it. Mutation: no read in
        mdShowLines -> the reflow puts back the spot read before the jump, the very top, fails."""
        n = line_of(FAR_ANCHOR, "끝 문단.")
        body = json.dumps(
            {"doc": "nt", "file": str(self.src / "notes" / "plan.md"), "lo": n, "hi": n, "note": "끝"}
        ).encode()
        code, _, out = self.talk(req("POST", "/api/pin", body, {"Content-Type": "application/json"}))
        self.assertEqual(code, 200, out)
        page = self.open(1, init=FRAMES_HELD, viewport={"width": 1440, "height": 900})
        until(page, DRAWN + "&&PINS.length===1", 20)
        settle(page)
        self.assertEqual(page.evaluate("document.querySelector('#left').scrollTop"), 0)
        w0 = page.evaluate("document.querySelector('#md').getBoundingClientRect().width")
        page.evaluate("window.__framesHeld=true; jumpPin(%d)" % json.loads(out)["id"])
        self.assertAlmostEqual(page.evaluate(AT_DEPTH + "(%d)" % n), 0, delta=1)
        top = page.evaluate(TOP_LINE)[0]
        self.assertGreater(top, 100)
        page.set_viewport_size({"width": 1000, "height": 900})
        until(
            page,
            "(w=>w<%d&&MD.spot.w===w)(document.querySelector('#md').getBoundingClientRect().width)" % (w0 - 50),
        )
        self.assertEqual(page.evaluate(TOP_LINE)[0], top)
        seen = (
            "(n=>{const r=document.querySelector('#left').getBoundingClientRect(),e=mdLeaves(n,n)[0].getBoundingClientRect();"
            " return e.top>=r.top&&e.bottom<=r.bottom;})(%d)" % n
        )
        self.assertTrue(page.evaluate(seen))
        page.evaluate("window.__framesGo()")
        settle(page)
        self.assertEqual(page.evaluate(TOP_LINE)[0], top)
        self.assertTrue(page.evaluate(seen))


class JumpThenReflowFirefox(JumpThenReflow):
    """The same in Firefox."""

    BROWSER_ENGINE = "firefox"


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
