"""Images of the manuscript tree and links between registered documents on the Markdown surface, in the browser
(docs/adr/0030-markdown-tree-images-and-document-links.md, docs/handbook/viewer.md §Markdown 화면).

The real viewer against the in-process server (BrowserBase), on two Markdown documents of one tree - notes/plan.md (nt) and
docs/guide.md (gd) - and the LaTeX manuscript (ms):

- a tree image is an <img> from this origin's GET /api/asset; a remote, data:, out-of-tree or missing image is its alt
  text saying why, and nothing is asked of another host - not even by the SVG, whose script and external image never run;
- an SVG opened on its own, with the asset route's own headers enforced, runs no script, fetches nothing and has an opaque
  origin; the same SVG without those headers does run (the test can see what it guards);
- an image that loads above the reading line leaves the text being read where it was;
- a pin on an image's line outlines the image; a click on an image picks its paragraph;
- a link to another registered document goes to it, at its heading, and the browser's back returns.

The pure rules are in test_md_tree_refs.py; the route's checks in src/limn/documents/tests/test_assets.py.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_markdown_assets.py
"""

import json
from urllib.parse import urlparse

from limn.administration import serve_documents as startup_documents

from helpers import blank_png, ps, req
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


def line_of(text: str, needle: str) -> int:
    """The 1-based line of text that holds needle."""
    return next(i for i, ln in enumerate(text.split("\n"), 1) if needle in ln)


class AssetsBase(BrowserBase):
    """BrowserBase with notes/plan.md (nt, PLAN) first, docs/guide.md (gd) and the LaTeX manuscript (ms) second and third,
    images in notes/img, and an image outside the tree."""

    PLAN = PLAN

    def setUp(self):
        self.away: list[str] = []
        self.asked: list[str] = []
        self.hold: list = []
        self.holding = False
        super().setUp()
        self.src = self.main.parent
        (self.src / "notes" / "img").mkdir(parents=True)
        (self.src / "docs").mkdir()
        (self.src / "notes" / "plan.md").write_text(self.PLAN, encoding="utf-8")
        (self.src / "docs" / "guide.md").write_text(GUIDE, encoding="utf-8")
        (self.src / "notes" / "img" / "chart.png").write_bytes(blank_png(240, 120))
        (self.src / "notes" / "img" / "tall.png").write_bytes(blank_png(200, 900))
        (self.src / "notes" / "img" / "flow.svg").write_text(SVG, encoding="utf-8")
        (self.src / "notes" / "img" / "fake.png").write_text("<html>not a png</html>", encoding="utf-8")
        (self.src.parent / "outside.png").write_bytes(blank_png(10, 10))
        docs = startup_documents.make_docs(
            ["nt=계획:notes/plan.md", "gd=안내:docs/guide.md", "ms=본문:main.tex"], self.src, ps.APP.C.paths
        )
        assert isinstance(docs, list), docs
        ps.APP.set_docs(docs)
        viewer_build(docs[2], BUILD1)

    def route(self, route):
        """Record every request; abort another host's (kept in self.away); hold /api/asset answers while self.holding."""
        u = urlparse(route.request.url)
        self.asked.append(u.path + ("?" + u.query if u.query else ""))
        if u.netloc != "viewer.test":
            self.away.append(route.request.url)
            return route.abort()
        if self.holding and u.path == "/api/asset":
            self.hold.append(route)
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
