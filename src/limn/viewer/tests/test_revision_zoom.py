"""Comparison PDF zoom against real Git history, cached PDFs and PDF.js."""

import json
import subprocess

from helpers import extract_js_fn, ps, run_node
from helpers_browser import BrowserBase


def comparison_pdf():
    """Build twenty valid PDF pages with alternating portrait and landscape boxes."""
    pages = 20
    kids = " ".join("%d 0 R" % (3 + i) for i in range(pages))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, pages)).encode(),
    ]
    for number in range(pages):
        width, height = (612, 792) if number % 2 == 0 else (792, 612)
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R >>" % (width, height, pages + 3)
            ).encode()
        )
    objects.append(b"<< /Length 24 >>\nstream\n0 0 1 rg 50 50 80 80 re f\nendstream")
    output, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    output += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(output)


class RevisionZoom(BrowserBase):
    """Read a ready comparison without invoking an external TeX compiler."""

    def setUp(self):
        """Create two real revisions and seed their finished comparison cache."""
        super().setUp()
        self.commits = []
        self.caches = {}

        def git(*args):
            """Run Git in the disposable manuscript repository."""
            return subprocess.check_output(["git", *args], cwd=self.main.parent, text=True).strip()

        git("init", "-q")
        git("config", "user.name", "Alice")
        git("config", "user.email", "alice@example.com")
        for number in range(3):
            with self.main.open("a", encoding="utf-8") as stream:
                stream.write("\n%% Revision %d\n" % number)
            git("add", "main.tex")
            git("commit", "-qm", "Revision %d" % number)
            self.commits.append(git("rev-parse", "HEAD"))
        for commit in self.commits[1:]:
            status, _, body = self.talk(
                ("GET /api/revision-build?commit=%s HTTP/1.1\r\nHost: localhost\r\n\r\n" % commit).encode()
            )
            self.assertEqual(status, 200, body)
            cache = ps.APP.C.state / "revisions" / json.loads(body)["job_id"]
            self.caches[commit] = cache
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "revision.pdf").write_bytes(comparison_pdf())
            (cache / "status.json").write_text(json.dumps({"state": "ready", "warnings": []}), encoding="utf-8")

    def comparison(self, **device):
        """Open the comparison and wait for an actual rendered canvas."""
        page = self.open(0, **device)
        if page.locator("#view-revisions").is_visible():
            page.click("#view-revisions")
        else:
            page.click("#btn-pos")
            page.locator("#nav-sheet [data-mode=revisions]").click()
        page.wait_for_selector('.revision-page[data-state="ready"] canvas')
        return page

    def test_buttons_fit_bounds_and_no_refetch(self):
        """Zoom stays bounded, rerenders and leaves manuscript settings alone."""
        page = self.comparison()
        self.assertEqual(page.locator("#revision-zoom").count(), 1)
        before = page.evaluate("({w:W,prefs:{...localStorage}})")
        requests = []
        page.on("request", lambda request: requests.append(request.url))
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "100%")
        width = page.locator(".revision-page").first.bounding_box()["width"]
        page.click("#revision-zoom-in")
        page.wait_for_selector('.revision-page[data-state="ready"] canvas')
        self.assertAlmostEqual(page.locator(".revision-page").first.bounding_box()["width"] / width, 1.2, places=2)
        for _ in range(12):
            if page.locator("#revision-zoom-in").is_enabled():
                page.click("#revision-zoom-in")
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "500%")
        self.assertFalse(page.locator("#revision-zoom-in").is_enabled())
        page.click("#revision-fit")
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "100%")
        for _ in range(6):
            if page.locator("#revision-zoom-out").is_enabled():
                page.click("#revision-zoom-out")
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "50%")
        self.assertFalse(page.locator("#revision-zoom-out").is_enabled())
        self.assertEqual(page.evaluate("({w:W,prefs:{...localStorage}})"), before)
        self.assertFalse(any("revision-pdf?" in url or "revision-build?" in url for url in requests))

    def test_input_preservation_and_commit_reset(self):
        """Shortcuts affect the visible PDF; source switches preserve its scale."""
        page = self.comparison()
        page.locator("#revision-pdf").click(position={"x": 100, "y": 100})
        page.keyboard.press("Control+Equal")
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "120%")
        page.click("#revision-source-tab")
        self.assertFalse(page.locator("#revision-zoom").is_visible())
        page.keyboard.press("Control+Equal")
        page.click("#revision-pdf-tab")
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "120%")
        page.locator("#revision-pdf").dispatch_event(
            "wheel", {"ctrlKey": True, "deltaY": -100, "clientX": 200, "clientY": 350}
        )
        page.wait_for_function("document.querySelector('#revision-zoom-value').textContent==='144%'")
        page.select_option("#revision-select", self.commits[1])
        page.wait_for_selector('.revision-page[data-state="ready"] canvas')
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "100%")
        page.click("#revision-zoom-in")
        page.click("#view-manuscript")
        page.click("#view-revisions")
        page.wait_for_selector('.revision-page[data-state="ready"] canvas')
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "100%")

    def test_resize_and_scroll_edges(self):
        """Fit follows available width and enlarged pages expose both edges."""
        page = self.comparison(viewport={"width": 1400, "height": 850})
        width = page.locator(".revision-page").first.bounding_box()["width"]
        page.set_viewport_size({"width": 1200, "height": 850})
        page.wait_for_function("document.querySelector('.revision-page').clientWidth < %s" % width)
        page.click("#revision-zoom-in")
        page.set_viewport_size({"width": 1300, "height": 850})
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "120%")
        page.evaluate("revisionZoomTo(5)")
        page.wait_for_selector('.revision-page[data-state="ready"] canvas')
        self.assertTrue(
            page.evaluate("""() => {
          const box=document.querySelector('#revision-pdf'),pg=document.querySelector('.revision-page:last-child');
          box.scrollLeft=0; const left=pg.getBoundingClientRect().left>=box.getBoundingClientRect().left;
          box.scrollLeft=box.scrollWidth; box.scrollTop=box.scrollHeight;
          const r=pg.getBoundingClientRect(),b=box.getBoundingClientRect();
          return left && r.right<=b.right && r.bottom<=b.bottom;
        }""")
        )
        page.wait_for_selector('.revision-page[data-page="20"][data-state="ready"] canvas')
        self.assertTrue(
            page.locator(".revision-page canvas").evaluate_all("cs=>cs.every(c=>c.width*c.height<=16777216)")
        )

    def test_scroll_eviction_and_rapid_zoom_exit(self):
        """The last page loads, distant canvases release pixels and canceled work stays silent."""
        page = self.comparison()
        self.assertAlmostEqual(
            page.locator('.revision-page[data-page="2"]').evaluate("e=>e.clientHeight/e.clientWidth"),
            612 / 792,
            places=2,
        )
        page.evaluate(
            "window.firstComparisonCanvas=document.querySelector('.revision-page canvas');document.querySelector('#revision-pdf').scrollTop=1e9"
        )
        page.wait_for_selector('.revision-page[data-page="20"][data-state="ready"] canvas')
        page.wait_for_function("window.firstComparisonCanvas.width===0")
        self.assertLess(page.locator(".revision-page canvas").count(), 6)
        page.evaluate("for(let i=0;i<20;i++)revisionZoomTo(i%2?5:.5);revisionZoomTo(2)")
        page.wait_for_selector('.revision-page[data-state="ready"] canvas')
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "200%")
        self.assertEqual(page.locator("#revision-pdf").get_by_text("소스 diff를 확인").count(), 0)
        page.evaluate("revisionZoomTo(5);setViewMode('manuscript')")
        self.assertEqual(page.locator(".revision-page canvas").count(), 0)
        self.assertTrue(page.evaluate("REV_PDF.tasks.size===0"))

    def test_phone_pinch_anchor_and_touch_controls(self):
        """Two-finger pinch anchors the page and phone controls retain full hit areas."""
        page = self.comparison(viewport={"width": 384, "height": 832}, has_touch=True, is_mobile=True)
        for selector in ("#revision-zoom-in", "#revision-zoom-out", "#revision-fit"):
            bounds = page.locator(selector).bounding_box()
            self.assertGreaterEqual(bounds["width"], 44)
            self.assertGreaterEqual(bounds["height"], 44)
            self.assertLessEqual(bounds["x"] + bounds["width"], 384)
        box = page.locator("#revision-pdf").bounding_box()
        y = box["y"] + 100
        fraction = page.locator(".revision-page").first.evaluate(
            "(el,p)=>{const r=el.getBoundingClientRect();return [(p.x-r.left)/r.width,(p.y-r.top)/r.height]}",
            {"x": 150, "y": y},
        )
        page.locator("#revision-pdf").dispatch_event(
            "touchstart",
            {
                "touches": [
                    {"identifier": 1, "clientX": 100, "clientY": y},
                    {"identifier": 2, "clientX": 200, "clientY": y},
                ]
            },
        )
        page.locator("#revision-pdf").dispatch_event(
            "touchmove",
            {
                "touches": [
                    {"identifier": 1, "clientX": 50, "clientY": y},
                    {"identifier": 2, "clientX": 250, "clientY": y},
                ]
            },
        )
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "200%")
        after = page.locator(".revision-page").first.evaluate(
            "(el,p)=>{const r=el.getBoundingClientRect();return [(p.x-r.left)/r.width,(p.y-r.top)/r.height]}",
            {"x": 150, "y": y},
        )
        for old, new in zip(fraction, after, strict=True):
            self.assertAlmostEqual(old, new, places=2)
        page.locator("#revision-pdf").dispatch_event("touchend", {"touches": []})
        page.click("#revision-fit")
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "100%")

    def test_safari_gesture_and_input_field_routing(self):
        """Safari-style gesture events stay local; fields keep native shortcuts."""
        page = self.comparison()
        page.locator("#revision-select").focus()
        page.keyboard.press("Control+Equal")
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "100%")
        page.evaluate("""() => {
          const box=document.querySelector('#revision-pdf'),r=box.getBoundingClientRect();
          for(const [type,scale] of [['gesturestart',1],['gesturechange',2],['gestureend',2]]){
            const event=new Event(type,{bubbles:true,cancelable:true});
            Object.assign(event,{scale,clientX:r.left+100,clientY:r.top+100});box.dispatchEvent(event);
          }
        }""")
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "200%")

    def test_shared_zoom_buttons_route_to_visible_comparison(self):
        """Existing zoom actions must not change an invisible manuscript."""
        page = self.comparison()
        width = page.evaluate("W")
        page.locator('[data-act="zoom-in"]:visible').first.click()
        self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "120%")
        self.assertEqual(page.evaluate("W"), width)
        page.click("#revision-source-tab")
        page.locator('[data-act="zoom-in"]:visible').first.click()
        self.assertEqual(page.evaluate("W"), width)

    def test_invalid_pdf_releases_loading_worker(self):
        """A failed PDF parse disables zoom and releases the worker owner."""
        (self.caches[self.commits[-1]] / "revision.pdf").write_bytes(b"%PDF-1.4\nInvalid PDF\n")
        page = self.open(0)
        page.click("#view-revisions")
        page.wait_for_function("document.querySelector('#revision-status').textContent.includes('소스 diff에서')")
        self.assertFalse(page.locator("#revision-zoom-in").is_enabled())
        self.assertTrue(page.evaluate("REV_PDF.loading===null&&REV_PDF.doc===null"))

    def test_resize_preserves_the_reading_point_at_the_new_center(self):
        """Width and height-only resize keep the same page point visibly centered."""
        page = self.comparison(viewport={"width": 1400, "height": 850})
        page.evaluate("revisionZoomTo(2);document.querySelector('#revision-pdf').scrollTop=5000")
        page.wait_for_function("RZ.anchor&&RZ.anchor.el.dataset.page==='4'")
        point = page.evaluate("({page:RZ.anchor.el.dataset.page,fx:RZ.anchor.fx,fy:RZ.anchor.fy})")
        for size in ({"width": 1400, "height": 400}, {"width": 600, "height": 350}):
            page.set_viewport_size(size)
            page.wait_for_function(
                """p=>{
              const box=document.querySelector('#revision-pdf'),b=box.getBoundingClientRect();
              const pg=box.querySelector(`[data-page="${p.page}"]`),r=pg.getBoundingClientRect();
              return Math.abs(r.left+r.width*p.fx-(b.left+box.clientWidth/2))<2 &&
                Math.abs(r.top+r.height*p.fy-(b.top+box.clientHeight/2))<2;
            }""",
                arg=point,
                timeout=3000,
            )
            self.assertEqual(page.locator("#revision-zoom-value").inner_text(), "200%")


def test_ratio_properties():
    """Generated finite ratios clamp monotonically and idempotently."""
    source = extract_js_fn("revisionRatio")
    result = json.loads(
        run_node(
            source
            + """
      let seed=161; const ratios=[-Infinity,Infinity,NaN,0,.5,1,5];
      for(let i=0;i<500;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;ratios.push(seed/4294967296*20-10);}
      const values=ratios.map(revisionRatio);
      console.log(JSON.stringify({bounded:values.every(v=>Number.isFinite(v)&&v>=.5&&v<=5),
        idempotent:values.every(v=>revisionRatio(v)===v),
        monotone:ratios.filter(Number.isFinite).sort((a,b)=>a-b).map(revisionRatio).every((v,i,a)=>!i||v>=a[i-1])}));
    """
        )
    )
    assert result == {"bounded": True, "idempotent": True, "monotone": True}
