"""The page verdict panel beside the pages (docs/handbook/viewer.md §판정 패널, issue #329).

On a wide desktop whose PDF area leaves room right of the pages, the page verdict line is one panel in that margin - the
reading page's line, the page under the 160px reading line the section strip and the keys name - and under each page a
one-row summary. A figure document of seven portrait pages (612 x 792 pt, 816px at print size; the last two list pages that
take no verdict) on a 1920 x 1080 desktop: with the pin panel open the room beside the pages is 444px, so the panel is on;
1680 with the pin panel open leaves 204px, so the lines are under the pages as in 0.4.36. CI's 1400 x 850 desktop never
takes the panel, so every test here sets its own viewport.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_verdict_panel.py
"""

import json
from unittest import mock
from urllib.parse import urlparse

from limn.pins.location import source as pick_source

import helpers_figure
from helpers import blank_png, ps, split_resp
from helpers_access import ALICE, BOB, member_add, talk_to
from helpers_browser import MISSES_44, VIEWPORTS, BrowserBase, nothing_follows, settle

WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}]}
N_PAGES = 7  # the last two are list pages: no verdict, no summary
TAKING = 5  # the pages that take a verdict
CAROL_VIEWER = {"Tailscale-User-Login": "carol@example.com", "Tailscale-User-Name": "Carol Lee"}
WIDE = {"viewport": {"width": 1920, "height": 1080}}
# The panel as it stands: its page and pin, its rows' text, its words, where its first word stands, and what it holds.
PANEL = """() => {const p = document.getElementById('pv-panel'); if (!p) return null; const b = p.querySelector('button.vd-b'), r = p.getBoundingClientRect();
  return {page: +p.dataset.page, pin: p.dataset.pin ? +p.dataset.pin : null, text: p.innerText.replace(/\\s+/g, ' ').trim(),
    words: [...p.querySelectorAll('button.vd-b')].map(x => x.textContent), wordTop: b ? Math.round(b.getBoundingClientRect().top) : null,
    left: Math.round(r.left), top: Math.round(r.top), chip: !!p.querySelector(':scope>.nt-chip'), pop: !!p.querySelector(':scope>.pv-pop'),
    err: (p.querySelector('.pv-err:not([hidden])') || {}).textContent || ''};}"""
# What the pages' column holds besides the pages: lines under pages, summaries, the panel - and the body's class.
SHAPE = """() => ({beside: document.body.classList.contains('pv-beside'), panel: !!document.getElementById('pv-panel'),
  lines: document.querySelectorAll('#doc .pgw>.pv').length, sums: document.querySelectorAll('#doc .pv-sum').length, side: PV_SIDE})"""
# Where every page's block stands in the document (px from the column's top) and how tall it is.
BLOCKS = """() => {const d = document.querySelector('#doc').getBoundingClientRect().top;
  return [...document.querySelectorAll('#doc .pgw')].map(w => {const r = w.getBoundingClientRect(); return [Math.round((r.top - d) * 10) / 10, Math.round(r.height * 10) / 10];});}"""
# Brings page n's top to off px under the PDF area's top, as a hand on the wheel (not a jump's glide).
TO = """([n, off]) => {PV_HAND(); const L = document.querySelector('#left'); L.scrollTop += document.getElementById('p' + n).getBoundingClientRect().top - L.getBoundingClientRect().top - off;}"""
# Whether the pages have rested for ten frames (a jump's smooth scroll is over).
RESTING = """() => {const L = document.querySelector('#left'), w = window.__rest || (window.__rest = {top: -1, n: 0});
  if (L.scrollTop === w.top) w.n++; else {w.top = L.scrollTop; w.n = 0;} if (w.n < 10) return false; window.__rest = null; return true;}"""
# How far the PDF area is scrolled.
TOP = "()=>Math.round(document.querySelector('#left').scrollTop)"
# The room the PDF area leaves beside the common page now.
ROOM = "() => pvSideRoom()"
# The focused element: its action, its line's page, whether it is in the panel, the pin panel or the PDF area itself.
FOCUS = """() => {const a = document.activeElement; if (!a || a === document.body) return null; const l = a.closest('#doc .pv');
  return {act: a.dataset.act || '', id: a.id || '', page: l ? +l.dataset.page : 0, panel: !!a.closest('#pv-panel'), right: !!a.closest('#right'),
    card: (a.closest('.pin.card') || {dataset: {}}).dataset.id || null};}"""
# The contrast of an element's text with what lies under it (the first opaque background up its ancestors), per WCAG.
CONTRAST = """sel => {const rgb = s => (s.match(/[\\d.]+/g) || []).map(Number), lum = c => {const f = v => {v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;};
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);};
  return [...document.querySelectorAll(sel)].filter(e => e.getClientRects().length).map(e => {let b = e, bg = null;
    while (b && !bg) {const c = rgb(getComputedStyle(b).backgroundColor); if (c.length >= 3 && (c.length < 4 || c[3] > 0.99)) bg = c; b = b.parentElement;}
    const fg = rgb(getComputedStyle(e).color), a = lum(fg), z = lum(bg || [255, 255, 255]);
    return [e.className || e.tagName, Math.round((Math.max(a, z) + 0.05) / (Math.min(a, z) + 0.05) * 100) / 100];});}"""


class PanelBase(BrowserBase):
    """The three documents of helpers_figure.viewer_docs with their word files (page: true on the figure and the PDF), the
    figure rebuilt as seven portrait one-figure pages; picks on the figure and the PDF reach the real handler. A new pin's
    POST may be lost (fail_pin) or answered 500 (pin_500)."""

    def setUp(self):
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        src = ps.APP.C.src
        for key, path in (
            ("ms", src / "main.limnverdicts.json"),
            ("fig", self.fig.main.parent / "figures.limnverdicts.json"),
            ("rv", src / "reviewer.limnverdicts.json"),
        ):
            path.write_text(json.dumps({**WORDS, "page": key != "ms"}, ensure_ascii=False), encoding="utf-8")
        pages = [
            {
                "page": i,
                "figure": "F%02d" % i,
                "title": "[후보] PL%d · 다섯 비교 쌍의 월별 효과 %d" % (10 + i, i),
                "elements": [
                    {
                        "id": "F%02d" % i,
                        "frac": [0, 0, 1, 1],
                        "src": {"file": "src/B2_calendar.py", "lo": 12, "hi": 140},
                    }
                ],
            }
            for i in range(1, TAKING + 1)
        ]
        for i, (fig, title) in enumerate((("LIST", "목록"), ("ASK", "연구 질문")), TAKING + 1):
            root = {"id": fig, "frac": [0, 0, 1, 1]}
            pages.append({"page": i, "figure": fig, "title": title, "verdict": False, "elements": [root]})
        fmap = {"format": "limn-figure-map/1", "pdf": "figures.pdf", "pdf_sha256": "0" * 64, "pages": pages}
        d = self.pages_dir = helpers_figure.write_build(self.fig, helpers_figure.BUILD2, fmap, pages=N_PAGES)
        for i in range(1, N_PAGES + 1):
            (d / ("page-%d.png" % i)).write_bytes(blank_png(1275, 1650))
        self.fail_pin = 0
        self.pin_500 = 0
        self.held_pin: list | None = None  # POST /api/pin routes held unanswered while not None
        self.held_edit: list | None = None  # POST /api/pins/N/edit routes held unanswered while not None
        self.held_list: list | None = None  # GET /api/pins (the pin list) held unanswered while not None
        patch = mock.patch.object(pick_source, "region_text", return_value="")  # pdftotext answers no text
        patch.start()
        self.addCleanup(patch.stop)

    def route(self, route):
        rq = route.request
        path = urlparse(rq.url).path
        if path == "/api/pins" and rq.method == "GET" and self.held_list is not None:
            self.held_list.append(route)
            return None
        if rq.method == "POST" and path.endswith("/edit") and self.held_edit is not None:
            self.held_edit.append(route)
            return None
        if path == "/api/pin" and rq.method == "POST":
            if self.held_pin is not None:
                self.held_pin.append(route)
                return None
            if self.fail_pin:
                self.fail_pin -= 1
                return route.abort()
            if self.pin_500:
                self.pin_500 -= 1
                return route.fulfill(
                    status=500, headers={"content-type": "application/json"}, body='{"error": "서버 오류"}'
                )
        if path == "/api/pick" and json.loads(rq.post_data or "{}").get("doc") in ("fig", "rv"):
            return self.forward(route)
        return super().route(route)

    def call(self, method, path, body=None, who=ALICE):
        """One request to the handler as who -> (status, JSON)."""
        data = json.dumps(body).encode() if body is not None else b""
        h = {"Host": "127.0.0.1:18999", **who}
        if data:
            h.update({"Content-Type": "application/json", "Content-Length": str(len(data))})
        if method == "POST":
            h["Origin"] = "http://127.0.0.1:18999"
        raw = ("%s %s HTTP/1.1\r\n" % (method, path) + "".join("%s: %s\r\n" % kv for kv in h.items()) + "\r\n").encode()
        code, _, out = split_resp(talk_to(ps, raw + data))
        return code, json.loads(out or b"null")

    def pins(self):
        return {p["id"]: p for p in self.call("GET", "/api/pins?all=1")[1]}

    def release(self, held, status=None, page=None):
        """Answers every route of held: as the handler does, or with status and an error. Given the page, waits for the
        request the viewer sends after its pick."""
        for _ in range(200):
            if held or not page:
                break
            page.wait_for_timeout(10)
        for r in held:
            if status:
                r.fulfill(status=status, headers={"content-type": "application/json"}, body='{"error": "서버 오류"}')
            else:
                self.forward(r)

    def verdict(self, n, key, doc="fig", who=ALICE):
        """A verdict of who's on page n's whole target, made through the API as the page line makes it; its id. A key of None
        makes an ordinary pin there."""
        meta = self.call("GET", "/api/meta?doc=" + doc)[1]
        pg = meta["pages"][n - 1]
        pick = {"doc": doc, "page": n, "x0": 0, "y0": 0, "x1": pg["pt_w"], "y1": pg["pt_h"], "frac": [0, 0, 1, 1]}
        code, d = self.call("POST", "/api/pick", {**pick, "pdf_build": meta["pages_build"]}, who)
        self.assertEqual(code, 200, d)
        body = {k: d[k] for k in helpers_figure.SAVE_LINE if d.get(k) is not None}
        body.update(scope=d.get("default_level"), doc=doc, note="", kind_req="fix", assignee="agent")
        if key:
            body["verdict"] = key
        code, made = self.call("POST", "/api/pin", body, who)
        self.assertEqual(code, 200, made)
        return made["id"]

    def on(self, doc="fig", n_open=0, lang="ko", **device):
        """The viewer showing document doc on device (WIDE unless given), settled at its top."""
        page = self.open(n_open, lang=lang, **(device or WIDE))
        page.evaluate("k=>switchDoc(k)", doc)
        page.wait_for_function("k=>DOC===k&&META&&META.doc===k&&document.querySelector('#p1')", arg=doc)
        settle(page)
        return page

    def to(self, page, n, off=16):
        page.evaluate(TO, [n, off])
        settle(page)

    def resize(self, page, room):
        """The window made as wide as leaves `room` px beside the pages (the outline and the pin panel keep their widths;
        measured again once, as the panel's width may follow the window)."""
        for _ in range(3):
            got = page.evaluate(ROOM)
            if abs(got - room) < 1:
                break
            size = page.viewport_size
            page.set_viewport_size({"width": int(size["width"] + room - got), "height": size["height"]})
            settle(page)
        self.assertLess(abs(page.evaluate(ROOM) - room), 1)

    def narrowed(self, page):
        """The window made too narrow for the panel while a request is held, which settle() would wait out."""
        size = page.viewport_size
        page.set_viewport_size({"width": int(size["width"] + 320 - page.evaluate(ROOM)), "height": size["height"]})
        page.wait_for_function("()=>!PV_SIDE")


class Panel(PanelBase):
    """The panel on a 1920 x 1080 desktop: when it is on, where it stands, what follows the reading page, and the line's
    keys, focus, chip, reason and failures inside it."""

    def test_room_bar_and_hysteresis_with_a_resize_the_pin_panel_and_a_zoom(self):
        """At 1920 with the pin panel open (444px of room) the lines stand beside the pages: one panel, a summary under
        each of the five pages that take a verdict, no line under a page. Made narrower, 340px (between the bars) keeps
        them beside, 320px puts them under the pages as 0.4.36 draws them, 340px keeps them there and 370px brings the
        panel back. At 1680 the pin panel decides: closed, beside; open, under. At 1920 with it closed a zoom of the pages
        past the bar puts them under, and 100% brings the panel back."""
        page = self.on()
        self.assertGreaterEqual(page.evaluate(ROOM), 360)
        self.assertEqual(
            page.evaluate(SHAPE), {"beside": True, "panel": True, "lines": 0, "sums": TAKING, "side": True}
        )
        for room, beside in ((340, True), (320, False), (340, False), (370, True)):
            with self.subTest(room=room):
                self.resize(page, room)
                got = page.evaluate(SHAPE)
                self.assertEqual(got["beside"], beside, got)
                self.assertEqual(got["lines"], 0 if beside else TAKING, got)
                self.assertEqual((got["panel"], got["sums"]), (beside, TAKING if beside else 0), got)
        page.set_viewport_size({"width": 1680, "height": 1050})
        settle(page)
        self.assertFalse(page.evaluate(SHAPE)["beside"], "1680 with the pin panel open has 204px of room")
        page.evaluate("setSide(false)")
        settle(page)
        self.assertTrue(page.evaluate(SHAPE)["beside"], "1680 with the pin panel closed")
        page.evaluate("setSide(true)")
        settle(page)
        self.assertFalse(page.evaluate(SHAPE)["beside"])
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.evaluate("setSide(false)")
        settle(page)
        self.assertTrue(page.evaluate(SHAPE)["beside"])
        for _ in range(3):
            page.evaluate("zoom(1)")
            settle(page)
        self.assertLess(page.evaluate(ROOM), 328)
        self.assertFalse(page.evaluate(SHAPE)["beside"], "a page zoomed past the bar keeps the panel")
        page.evaluate("actualSize()")
        settle(page)
        self.assertTrue(page.evaluate(SHAPE)["beside"], "back at 100% the panel did not come back")

    def test_the_page_stays_centred_while_the_margin_holds_the_panel_and_moves_left_by_what_it_lacks(self):
        """1920 with the pin panel closed: the page is centred and the panel stands 24px right of it. With the pin panel
        open the right margin is exactly the panel and its gap (304px), and the page moved left by what it lacked."""
        page = self.on()
        page.evaluate("setSide(false)")
        settle(page)
        geo = """() => {const L = document.querySelector('#left'), r = L.getBoundingClientRect(), cs = getComputedStyle(L), g = document.getElementById('p1').getBoundingClientRect(), p = document.getElementById('pv-panel').getBoundingClientRect();
          const left = r.left + L.clientLeft + parseFloat(cs.paddingLeft), right = r.left + L.clientLeft + L.clientWidth - parseFloat(cs.paddingRight);
          return {l: g.left - left, r: right - g.right, gap: p.left - g.right, w: p.width};}"""
        got = page.evaluate(geo)
        self.assertLess(abs(got["l"] - got["r"]), 1.5, got)
        self.assertEqual((round(got["gap"]), round(got["w"])), (24, 280), got)
        page.evaluate("setSide(true)")
        settle(page)
        got = page.evaluate(geo)
        self.assertLess(abs(got["r"] - 304), 1.5, got)
        self.assertGreater(got["l"], 24, got)
        self.assertEqual(round(got["gap"]), 24, got)

    def test_the_panel_follows_the_reading_page_and_is_not_redrawn_within_a_page(self):
        """Scrolled from page 1 to page 5 in 60px steps, a frame apart: at every step the panel shows the page under the
        reading line (the one the section strip names), and while that page stays the panel is not rewritten. No block
        changes its place or height as the reading page changes."""
        page = self.on()
        blocks = page.evaluate(BLOCKS)
        page.evaluate(
            """() => {window.__muts = 0; window.__pv = new MutationObserver(r => {window.__muts += r.length;});
              window.__pv.observe(document.getElementById('pv-panel'), {childList: true, subtree: true, characterData: true});}"""
        )
        steps = """async () => {const L = document.querySelector('#left'), out = []; const frame = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
          let was = PV_READ, quiet = 0;
          for (let i = 0; i < 200 && PV_READ < 5; i++) {PV_HAND(); L.scrollTop += 60; await frame(); const p = document.getElementById('pv-panel');
            out.push([pvReadingPage(), +p.dataset.page, (document.getElementById('section-page-t') || {}).textContent || '']);
            if (PV_READ === was) quiet += window.__muts; window.__muts = 0; was = PV_READ;}
          return {out, quiet};}"""
        got = page.evaluate(steps)
        wrong = [s for s in got["out"] if s[0] != s[1] or not s[2].startswith("%d " % s[0])]
        self.assertEqual(wrong, [], "steps where the panel or the strip did not show the reading page")
        self.assertEqual(got["quiet"], 0, "the panel was rewritten while its page stayed")
        self.assertEqual({s[0] for s in got["out"]}, {1, 2, 3, 4, 5})
        self.assertEqual([b[1] for b in page.evaluate(BLOCKS)], [b[1] for b in blocks], "a block changed its height")

    def test_a_key_before_the_next_frame_saves_on_the_page_under_the_reading_line(self):
        """Page 3 brought under the reading line and key 2 pressed in the same task, before the frame that would show it:
        보류 is saved on page 3 (the panel shows page 3 at once), and nothing on page 2."""
        page = self.on()
        self.to(page, 2)
        self.assertEqual(page.evaluate(PANEL)["page"], 2)
        page.evaluate(
            """() => {PV_HAND(); const L = document.querySelector('#left'); L.scrollTop += document.getElementById('p3').getBoundingClientRect().top - L.getBoundingClientRect().top - 16;
              document.body.dispatchEvent(new KeyboardEvent('keydown', {key: '2', bubbles: true}));}"""
        )
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        (pin,) = self.pins().values()
        self.assertEqual((pin["verdict"], pin["page"]), ("보류", 3))
        got = page.evaluate(PANEL)
        self.assertEqual(got["page"], 3)
        self.assertIn("판정 #%d 보류" % pin["id"], got["text"])

    def test_enter_writes_the_reason_in_the_panel_esc_drops_it_and_moving_on_writes_it(self):
        """Key 1 saves 채택 and hands the focus to 'Enter 이유 쓰기'; Enter opens the popover in the panel's flow under the
        state (the words stay); Enter writes the reason. [접기] keeps a draft the panel marks '초안 있음' across a move to
        the next page and back; Esc twice drops it; a reason typed and left by moving on is written (0.4.34-0.4.36)."""
        page = self.on()
        self.to(page, 2)
        top = page.evaluate(PANEL)["wordTop"]
        page.evaluate("searchToPage()")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        self.assertEqual(page.evaluate(FOCUS)["act"], "pv-reason-open")
        page.keyboard.press("Enter")
        page.wait_for_selector("#pv-panel>.pv-pop .pv-reason")
        place = page.evaluate(
            """() => {const p = document.getElementById('pv-panel'), pop = p.querySelector('.pv-pop').getBoundingClientRect(), t = p.querySelector('.pv-t').getBoundingClientRect(), b = p.getBoundingClientRect();
              return {under: pop.top >= t.bottom - 0.5, inside: pop.bottom <= b.bottom + 0.5 && pop.left >= b.left, pos: getComputedStyle(p.querySelector('.pv-pop')).position};}"""
        )
        self.assertEqual(place, {"under": True, "inside": True, "pos": "static"})
        self.assertEqual(page.evaluate(PANEL)["wordTop"], top, "the words moved as the popover opened")
        page.keyboard.type("패널에서 쓴 이유")
        page.keyboard.press("Enter")
        (pid,) = self.pins()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='패널에서 쓴 이유')", arg=pid)
        settle(page)
        self.assertIn("패널에서 쓴 이유", page.evaluate(PANEL)["text"])
        page.locator('#pv-panel [data-act="pv-reason-open"]').click()
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type("접어 둔 초안")
        page.locator('#pv-panel [data-act="pv-reason-fold"]').click()
        settle(page)
        self.assertIn("초안 있음", page.evaluate(PANEL)["text"])
        self.to(page, 3)
        self.to(page, 2)
        self.assertIn("초안 있음", page.evaluate(PANEL)["text"], "the folded draft was lost moving on and back")
        page.locator("#pv-panel button.pv-draft").click()
        self.assertEqual(page.locator("#pv-panel .pv-reason").input_value(), "접어 둔 초안")
        page.keyboard.press("Escape")
        settle(page)
        self.assertTrue(page.evaluate(PANEL)["pop"], "the first Esc with text closed the popover")
        page.keyboard.press("Escape")
        settle(page)
        got = page.evaluate(PANEL)
        self.assertFalse(got["pop"])
        self.assertNotIn("초안 있음", got["text"])
        self.assertEqual(self.pins()[pid]["note"], "패널에서 쓴 이유")
        page.locator("#pv-panel button.pv-note").click()
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type("옮기며 쓴 이유")
        self.to(page, 3)
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='옮기며 쓴 이유')", arg=pid)
        self.assertEqual(self.pins()[pid]["note"], "옮기며 쓴 이유")

    def test_the_save_chip_stands_in_the_panel_and_its_undo_moves_to_the_status_line_with_its_page(self):
        """A press on the panel's 보류: the chip is in the panel's flow, over no control, and the words did not move.
        Page 3 then read: the chip leaves the panel (it shows page 3's verdict), and its undo is on the status line."""
        page = self.on()
        self.to(page, 2)
        top = page.evaluate(PANEL)["wordTop"]
        page.locator('#pv-panel button[data-key="보류"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        page.wait_for_selector("#pv-panel>.nt-chip")
        settle(page)
        (pid,) = self.pins()
        self.assertEqual(page.evaluate(PANEL)["wordTop"], top)
        over = page.evaluate(
            """() => {const p = document.getElementById('pv-panel'), c = p.querySelector(':scope>.nt-chip').getBoundingClientRect();
              return [...p.querySelectorAll('button,[role=link],.pv-s,.pv-st')].filter(e => !e.closest('.nt-chip')).filter(e => {const r = e.getBoundingClientRect();
                return r.width && r.left < c.right && c.left < r.right && r.top < c.bottom && c.top < r.bottom;}).map(e => e.textContent);}"""
        )
        self.assertEqual(over, [], "controls under the chip")
        self.assertEqual(
            page.evaluate("()=>getComputedStyle(document.querySelector('#pv-panel>.nt-chip')).position"), "static"
        )
        self.to(page, 3)
        got = page.evaluate(PANEL)
        self.assertEqual(got["page"], 3)
        self.assertFalse(got["chip"], "page 2's chip stayed on the panel showing page 3")
        self.assertTrue(
            page.evaluate("id=>LINE.some(n=>n.title.includes('#'+id)&&!!n.act)", pid),
            "the undo did not move to the status line",
        )

    def test_cancel_offers_undo_in_the_panel_and_the_keyboard_follows(self):
        """Alice's 채택 on page 2: [판정 취소] by the keyboard takes it back - the panel says '판정 없음' and its
        [되돌리기] has the focus; Enter there brings the verdict back."""
        page = self.on()
        self.to(page, 2)
        page.locator('#pv-panel button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.evaluate(
            "()=>NOTICES.forEach(n=>{if(n.place==='chip')endNotice(n,false);})"
        )  # its chip's window, which would hold the line's descriptions
        settle(page)
        page.locator("#pv-panel button.pv-cancel").focus()
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.length===0")
        settle(page)
        self.assertIn("판정 없음", page.evaluate(PANEL)["text"])
        self.assertEqual(page.evaluate(FOCUS)["act"], "pv-undo")
        self.assertTrue(page.evaluate(FOCUS)["panel"])
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        self.assertIn("채택", page.evaluate(PANEL)["text"])

    def test_the_earlier_link_hands_the_focus_to_its_card(self):
        """Two verdicts on page 2 (보류, then 채택): the panel shows the newer and '이전 1건'; Enter on that link takes the
        focus to the earlier verdict's card in the pin panel."""
        first = self.verdict(2, "보류")
        self.verdict(2, "채택")
        page = self.on(n_open=2)
        self.to(page, 2)
        self.assertIn("이전 1건", page.evaluate(PANEL)["text"])
        page.locator("#pv-panel button.pv-early").focus()
        page.keyboard.press("Enter")
        settle(page)
        self.assertEqual(page.evaluate(FOCUS)["card"], str(first))

    def test_shift_tab_leaves_to_where_tab_came_from_and_tab_from_the_last_control_goes_to_the_pin_panel(self):
        """From the section strip's page button Tab goes to the panel's first word; Shift+Tab from it goes back there. Tab
        through the panel ends in the pin panel; the pages never scroll."""
        self.verdict(2, "채택")
        page = self.on(n_open=1)
        self.to(page, 2)
        top = page.evaluate("()=>document.querySelector('#left').scrollTop")
        page.locator("#section-page").focus()
        page.keyboard.press("Tab")
        got = page.evaluate(FOCUS)
        self.assertEqual((got["panel"], got["act"]), (True, "pv-save"), got)
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate(FOCUS)["id"], "section-page")
        page.keyboard.press("Tab")
        seen = []
        for _ in range(12):
            got = page.evaluate(FOCUS)
            if not got or not got["panel"]:
                break
            seen.append(got["act"])
            page.keyboard.press("Tab")
        self.assertEqual(seen[:3], ["pv-save"] * 3, seen)
        self.assertIn("pv-cancel", seen)
        got = page.evaluate(FOCUS)
        self.assertTrue(
            got and (got["right"] or got["id"] == "grip"), "Tab from the panel's last control went to %s" % got
        )
        self.assertEqual(page.evaluate("()=>document.querySelector('#left').scrollTop"), top)

    def test_summaries_under_the_pages_bold_the_reading_page_never_change_height_and_bring_their_page(self):
        """A summary under every page that takes a verdict - none under the list page - all one height; the reading
        page's is bold. Reading another page changes no block. A press on page 4's summary brings page 4 to the reading
        place: the panel shows it and has the focus, and the pages stay there."""
        pid = self.verdict(4, "채택")
        page = self.on(n_open=1)
        sums = """() => [...document.querySelectorAll('#doc .pv-sum')].map(s => [+s.dataset.page, s.getBoundingClientRect().height, getComputedStyle(s).fontWeight, s.textContent.replace(/\\s+/g, ' ')])"""
        got = page.evaluate(sums)
        self.assertEqual([s[0] for s in got], [1, 2, 3, 4, 5])
        at = "()=>{const s=document.querySelector('#doc .pv-sum[data-page=\"1\"] .pv-sum-id').getBoundingClientRect(),p=document.getElementById('p1').getBoundingClientRect();return s.left-p.left;}"
        self.assertLess(abs(page.evaluate(at) - 4), 1.5, "the summary does not start at its page's left edge")
        self.assertEqual(len({s[1] for s in got}), 1, got)
        self.assertEqual([s[2] for s in got], ["600", "400", "400", "400", "400"])
        self.assertIn("판정 #%d 채택" % pid, got[3][3])
        blocks = page.evaluate(BLOCKS)
        self.to(page, 3)
        self.assertEqual([s[2] for s in page.evaluate(sums)], ["400", "400", "600", "400", "400"])
        self.assertEqual([b[1] for b in page.evaluate(BLOCKS)], [b[1] for b in blocks])
        page.locator('#doc .pv-sum[data-page="4"]').click()
        settle(page)
        self.assertEqual(page.evaluate(PANEL)["page"], 4)
        got = page.evaluate(FOCUS)
        self.assertTrue(got["panel"] and got["page"] == 4, got)
        at = page.evaluate(
            "()=>[document.querySelector('#left').scrollTop, document.getElementById('p4').getBoundingClientRect().top - document.querySelector('#left').getBoundingClientRect().top]"
        )
        self.assertLess(abs(at[1] - 16), 1.5, at)
        nothing_follows(page)
        self.assertEqual(
            page.evaluate("()=>document.querySelector('#left').scrollTop"), at[0], "the pages moved after the press"
        )

    def test_page_list_outline_and_card_view_land_on_the_page_the_panel_shows(self):
        """The page list's page 5, an outline entry of page 3 and the [보기] of page 4's verdict card each leave that page
        under the reading line: the section strip names it and the panel shows it."""
        pid = self.verdict(4, "채택")
        page = self.on(n_open=1)

        def landed(n):
            page.wait_for_function(RESTING, polling="raf", timeout=10000)
            settle(page)
            got = (
                page.evaluate("pvReadingPage()"),
                page.evaluate(PANEL)["page"],
                page.evaluate("()=>document.getElementById('section-page-t').textContent"),
            )
            self.assertEqual(got[:2], (n, n), got)
            self.assertTrue(got[2].startswith("%d " % n), got)

        page.locator("#section-page").click()
        page.locator('#page-pop [data-act="page-go"][data-page="5"]').click()
        landed(5)
        # The fixture's stub PDF has no outline: one entry as PDF.js would give it, and the outline's own pick.
        page.evaluate("()=>{OUTLINE_ENTRIES=[{page:3,frac:0,title:'F03',level:0}]; pickOutline(0);}")
        landed(3)
        page.locator('#list .pin.card[data-id="%d"] button.b-view' % pid).click()
        landed(4)

    def test_a_document_switch_takes_the_panel_away_and_back(self):
        """The figure document with its panel; the manuscript (no page lines) has none and no summary; the view-only PDF
        (page lines, two portrait pages) has its own; back on the figure document the panel shows its reading page."""
        page = self.on()
        self.assertTrue(page.evaluate(SHAPE)["panel"])
        for doc, panel in (("ms", False), ("rv", True), ("fig", True)):
            with self.subTest(doc=doc):
                page.evaluate("k=>switchDoc(k)", doc)
                page.wait_for_function("k=>DOC===k&&META&&META.doc===k&&document.querySelector('#p1')", arg=doc)
                settle(page)
                got = page.evaluate(SHAPE)
                self.assertEqual((got["panel"], got["beside"], got["lines"]), (panel, panel, 0), got)
                self.assertEqual(got["sums"], (TAKING if doc == "fig" else 2) if panel else 0, got)
        self.assertEqual(page.evaluate(PANEL)["page"], page.evaluate("pvReadingPage()"))

    def test_text_in_the_panel_and_the_summaries_reads_four_and_a_half_to_one_in_both_themes(self):
        """Every piece of text in the panel (the name, the title, the state, the words) and in the summaries reads at least
        4.5:1 against what lies under it, light and dark."""
        self.verdict(1, "보류")
        page = self.on(n_open=1)
        sel = "#pv-panel :is(.pv-fig-id,.pv-fig-t,.pv-s,.pv-st,.vd-b .lbl,.pv-note), #doc .pv-sum :is(.pv-sum-id,.pv-sum-s)"
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page.evaluate("t=>setTheme(t)", theme)
                settle(page)
                got = page.evaluate(CONTRAST, sel)
                self.assertGreater(len(got), 6, got)
                self.assertEqual([g for g in got if g[1] < 4.5], [], got)

    def test_a_failed_save_is_said_in_the_panel_lost_or_answered_500_and_a_conflict_in_its_popover(self):
        """A press whose save is lost on the network, then one answered 500: each time the panel says '판정 저장 실패'
        under its words. A reason whose note Bob changed meanwhile (409): the popover in the panel shows his note."""
        page = self.on()
        self.to(page, 2)
        for name in ("fail_pin", "pin_500"):
            with self.subTest(how=name):
                setattr(self, name, 1)
                page.locator('#pv-panel button[data-key="채택"]').click()
                page.wait_for_function("()=>!PV_BUSY.size")
                settle(page)
                self.assertIn("판정 저장 실패", page.evaluate(PANEL)["err"])
                self.assertEqual(self.pins(), {})
        page.locator('#pv-panel button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        (pid,) = self.pins()
        page.locator('#pv-panel [data-act="pv-reason-open"]').click()
        page.keyboard.type("처음 이유")
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='처음 이유')", arg=pid)
        settle(page)
        page.locator("#pv-panel button.pv-note").click()  # the saved reason, changed: written against the rev it read
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type("내 이유")
        rev = self.pins()[pid]["rev"]
        self.assertEqual(
            self.call("POST", "/api/pins/%d/edit" % pid, {"note": "밥의 메모", "base_rev": rev}, BOB)[0], 200
        )
        page.locator('#pv-panel [data-act="pv-reason-save"]').click()
        page.wait_for_selector("#pv-panel .pv-pop-cf")
        self.assertIn("밥의 메모", page.locator("#pv-panel .pv-pop-cf-note").inner_text())


class PanelEdges(PanelBase):
    """What the one panel changes for the line's rules: the same place on the screen is another page's button after a scroll,
    only the reading page is shown, and every line goes and comes when the room crosses its bar."""

    def test_a_page_that_takes_no_verdict_says_so_and_a_key_saves_nothing(self):
        """A list page read: the panel names it and says it takes no verdict, without words, its block has no summary, and
        a key saves nothing. The next list page read: the panel names that one, as the section strip does (both read no
        verdict page, and the panel kept the first one's name). A page with a verdict read: the words are back."""
        page = self.on()
        for n in (TAKING + 1, N_PAGES):
            with self.subTest(page=n):
                self.to(page, n)
                got = page.evaluate(PANEL)
                self.assertEqual((got["page"], got["words"]), (n, []), got)
                self.assertTrue(got["text"].startswith("%d쪽" % n), got)
                self.assertIn("이 쪽은 판정을 받지 않습니다", got["text"])
                self.assertTrue(page.locator("#section-page-t").inner_text().startswith("%d " % n))
        page.evaluate("searchToPage()")
        page.keyboard.press("1")
        settle(page)
        self.assertEqual(self.pins(), {})
        self.to(page, TAKING)
        got = page.evaluate(PANEL)
        self.assertEqual((got["page"], len(got["words"])), (TAKING, 3), got)

    def test_a_focus_on_the_panel_stays_with_its_page_when_the_reading_page_changes(self):
        """The focus on a word of page 1, page 3 (Alice's 채택) read: the focus is on the PDF area, and Space does not take
        page 3's verdict back. On page 3's word, page 4 read: Enter saves nothing. On page 3's [판정 취소], which page 4 does
        not have: the focus is on the PDF area, not on nothing. The same when a redraw shows the new page before the frame."""
        mine = self.verdict(3, "채택")
        page = self.on(n_open=1)
        cases = (
            (1, 3, '#pv-panel button[data-key="채택"]', "Space"),
            (3, 4, '#pv-panel button[data-key="보류"]', "Enter"),
            (3, 4, "#pv-panel button.pv-cancel", None),
        )
        for was, now, control, key in cases:
            with self.subTest(control=control):
                self.to(page, was)
                page.locator(control).focus()
                self.to(page, now)
                got = page.evaluate(FOCUS)
                self.assertEqual((got or {}).get("id"), "left", got)
                if key:
                    page.keyboard.press(key)
                    settle(page)
                self.assertEqual(page.evaluate("OPEN_ALL.map(p=>p.id)"), [mine])
        self.to(page, 3)
        page.locator("#pv-panel button.pv-cancel").focus()
        page.evaluate(
            """() => {PV_HAND(); const L = document.querySelector('#left'); L.scrollTop += document.getElementById('p4').getBoundingClientRect().top - L.getBoundingClientRect().top - 16;
              drawPageVerdicts();}"""
        )
        self.assertEqual((page.evaluate(FOCUS) or {}).get("id"), "left")

    def scroll_keys(self, page, n, keys):
        """Page n read, a key save on it: what each of keys moves the PDF area by, in order, with the focus after it. The
        pages are put back at page n's top before each key, and the saved verdict stays."""
        self.to(page, n)
        page.evaluate("searchToPage()")
        page.keyboard.press("1")
        page.wait_for_function("n=>!PV_BUSY.has(pvSlot(n))", arg=n)
        settle(page)
        out = []
        for key in keys:
            self.to(page, n)
            page.locator('#doc .pv[data-page="%d"] [data-act="pv-reason-open"]' % n).focus()
            top = page.evaluate(TOP)
            page.keyboard.press(key)
            page.wait_for_function(RESTING, polling="raf", timeout=10000)
            settle(page)
            out.append(page.evaluate(TOP) - top)
            self.assertIsNotNone(page.evaluate(FOCUS), "%s left the focus on nothing" % key)
        return out

    def test_scroll_keys_on_the_panel_move_the_pages_as_they_do_on_a_line(self):
        """1680 x 1050 has the same PDF area with the pin panel open (lines under the pages) and closed (the panel): with the
        focus on 'Enter 이유 쓰기' after a key save, PageDown, PageUp, the arrows and End move the pages by the same distance
        in either. Home goes back to the top. The panel stood out of the area's scroll chain and they moved nothing."""
        page = self.on(viewport={"width": 1680, "height": 1050})
        self.assertFalse(page.evaluate(SHAPE)["beside"])
        keys = ("PageDown", "ArrowDown", "PageUp", "ArrowUp", "End")
        under = self.scroll_keys(page, 2, keys)
        page.evaluate("setSide(false)")
        settle(page)
        self.assertTrue(page.evaluate(SHAPE)["beside"])
        beside = self.scroll_keys(page, 3, keys)
        self.assertEqual(beside[:2], under[:2])
        self.assertEqual(beside[2:4], under[2:4])
        self.assertGreater(beside[0], 400, beside)
        self.assertGreater(beside[1], 0, beside)
        self.assertLess(beside[2], -400, beside)
        self.assertGreater(beside[4], 0, beside)
        self.to(page, 3)
        page.locator('#pv-panel [data-act="pv-reason-open"]').focus()
        page.keyboard.press("Home")
        page.wait_for_function(RESTING, polling="raf", timeout=10000)
        self.assertEqual(page.evaluate(TOP), 0)

    def test_after_a_key_save_page_down_reaches_the_next_page_and_the_next_digit_lands_there(self):
        """A keyboard pass: digit, PageDown until the next page is read, digit - each verdict on its own page, the focus never
        on nothing, handed to the PDF area when the reading page changes. It piled every verdict on one page."""
        page = self.on(viewport={"width": 1680, "height": 1050})
        page.evaluate("setSide(false)")
        settle(page)
        self.to(page, 2)
        page.evaluate("searchToPage()")
        for n, digit in ((2, "1"), (3, "2"), (4, "1")):
            with self.subTest(page=n):
                self.assertEqual(page.evaluate("pvReadingPage()"), n)
                page.keyboard.press(digit)
                page.wait_for_function("n=>!PV_BUSY.has(pvSlot(n))", arg=n)
                settle(page)
                for _ in range(4):
                    if page.evaluate("pvReadingPage()") != n:
                        break
                    page.keyboard.press("PageDown")
                    page.wait_for_function(RESTING, polling="raf", timeout=10000)
                    settle(page)
                    self.assertIsNotNone(page.evaluate(FOCUS), "PageDown left the focus on nothing")
                self.assertEqual(page.evaluate("pvReadingPage()"), n + 1)
        got = sorted((p["page"], p["verdict"]) for p in self.pins().values())
        self.assertEqual(got, [(2, "채택"), (3, "보류"), (4, "채택")])

    def test_a_wheel_over_the_panel_and_a_key_after_pressing_its_text_move_the_pages(self):
        """The wheel with the pointer on the panel moves the pages; so does PageDown after a press on its plain text, which
        leaves the focus on nothing."""
        page = self.on()
        self.to(page, 2)
        box = page.locator("#pv-panel .pv-fig-id").bounding_box()
        page.mouse.move(box["x"] + 4, box["y"] + 4)
        top = page.evaluate(TOP)
        page.mouse.wheel(0, 300)
        page.wait_for_function(RESTING, polling="raf", timeout=10000)
        self.assertEqual(page.evaluate(TOP) - top, 300)
        page.mouse.click(box["x"] + 4, box["y"] + 4)
        top = page.evaluate(TOP)
        page.keyboard.press("PageDown")
        page.wait_for_function(RESTING, polling="raf", timeout=10000)
        self.assertGreater(page.evaluate(TOP) - top, 400)

    def test_the_reason_field_keeps_its_own_keys_and_space_presses_a_word(self):
        """In the reason field Home, End and the arrows move the caret and Space is a space: the pages stay. Space on a word
        of the panel presses it (the word's rule), and the pages stay."""
        page = self.on()
        self.to(page, 2)
        page.locator('#pv-panel button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.locator('#pv-panel [data-act="pv-reason-open"]').click()
        top = page.evaluate(TOP)
        page.keyboard.type("가나")
        for key in ("Home", "End", "ArrowLeft", "Space"):
            page.keyboard.press(key)
        page.wait_for_function(RESTING, polling="raf", timeout=10000)
        self.assertEqual(page.locator("#pv-panel .pv-reason").input_value(), "가 나")
        self.assertEqual(page.evaluate(TOP), top)
        self.assertTrue(page.evaluate("()=>pvIsReasonField(document.activeElement)"))
        page.locator('#pv-panel [data-act="pv-reason-close"]').click()
        page.locator('#pv-panel [data-act="pv-reason-close"]').click()
        settle(page)
        page.locator('#pv-panel button[data-key="보류"]').focus()
        page.keyboard.press("Space")
        page.wait_for_function("OPEN_ALL.some(p=>p.verdict==='보류')")
        settle(page)
        self.assertEqual(page.evaluate(TOP), top)

    def test_a_summary_wider_than_a_small_page_never_moves_it_or_the_panel(self):
        """Page 3 a small figure (144pt, 192px at print size), narrower than what its summary says: the summary is as wide
        as the page and cut, the page stands where a page of that width stands, and neither a verdict nor a kept draft
        moves it or the panel."""
        (self.pages_dir / "page-3.png").write_bytes(blank_png(300, 1650))
        page = self.on()
        self.to(page, 3)
        read = """() => {const p = document.getElementById('p3').getBoundingClientRect(), s = document.querySelector('#doc .pv-sum[data-page="3"]'), t = s.querySelector('.pv-sum-s');
          return {left: Math.round(p.left), panel: Math.round(document.getElementById('pv-panel').getBoundingClientRect().left), w: Math.round(s.getBoundingClientRect().width), page: Math.round(p.width), cut: t.scrollWidth > t.clientWidth};}"""
        before = page.evaluate(read)
        self.assertEqual(before["w"], before["page"], before)
        self.assertEqual(before["page"], 192, before)
        page.locator('#pv-panel button[data-key="보류"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.locator('#pv-panel [data-act="pv-reason-open"]').click()
        page.keyboard.type("작은 쪽의 초안")
        page.locator('#pv-panel [data-act="pv-reason-fold"]').click()
        settle(page)
        after = page.evaluate(read)
        self.assertTrue(after.pop("cut"), "the summary fits: it proves nothing")
        before.pop("cut")
        self.assertEqual(after, before)

    def test_a_confirm_word_armed_on_one_page_is_not_confirmed_on_the_next_at_the_same_place(self):
        """삭제 pressed once on page 2, page 3 read, the same place on the screen pressed: the button there is page 3's, so
        the press only arms it there - nothing is saved on either page until its own second press."""
        page = self.on()
        self.to(page, 2)
        word = page.locator('#pv-panel button[data-key="삭제"]')
        word.click()
        settle(page)
        self.assertEqual(page.evaluate("()=>VD_ARM&&VD_ARM.page"), 2)
        box = word.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self.to(page, 3)
        now = word.bounding_box()  # no longer armed: narrower, the same row
        self.assertEqual(now["y"], box["y"], "the word moved between pages")
        self.assertTrue(now["x"] < x < now["x"] + now["width"], "the place pressed is not on page 3's word")
        page.mouse.click(x, y)
        settle(page)
        self.assertEqual(self.pins(), {}, "a second press on another page saved the verdict")
        self.assertEqual(page.evaluate("()=>VD_ARM&&VD_ARM.page"), 3)
        page.mouse.click(x, y)
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        (pin,) = self.pins().values()
        self.assertEqual((pin["verdict"], pin["page"]), ("삭제", 3))

    def test_the_lines_moving_keep_the_reason_field_with_its_caret_both_ways(self):
        """A reason being typed in the panel when the room falls past its bar: the field on the line under the page has the
        focus, the text and the caret, and digits typed on stay text - and the same on the way back. No verdict is saved."""
        page = self.on()
        self.to(page, 2)
        page.locator('#pv-panel button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.locator('#pv-panel [data-act="pv-reason-open"]').click()
        page.keyboard.type("가나다")
        page.keyboard.press("ArrowLeft")
        for room, beside, more in ((320, False, "1"), (370, True, "2")):
            with self.subTest(beside=beside):
                self.resize(page, room)
                self.assertEqual(page.evaluate(SHAPE)["beside"], beside)
                self.assertTrue(
                    page.evaluate("()=>pvIsReasonField(document.activeElement)"), "the field lost the focus"
                )
                page.keyboard.type(more)
        self.assertEqual(page.locator("#doc .pv-pop .pv-reason").input_value(), "가나12다")
        self.assertEqual(len(self.pins()), 1, "a digit typed on became a verdict")

    def test_the_lines_moving_keep_the_save_chip_and_the_reading_spot(self):
        """A chip in the panel when the room falls past its bar stands on the page's line, its undo still there; page 3,
        read from a third of the way down, stays where it is in both directions."""
        page = self.on()
        self.to(page, 3, off=-300)
        page.locator('#pv-panel button[data-key="보류"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        page.wait_for_selector("#pv-panel>.nt-chip")
        settle(page)
        at = "()=>Math.round(document.getElementById('p3').getBoundingClientRect().top-document.querySelector('#left').getBoundingClientRect().top)"
        was = page.evaluate(at)
        self.resize(page, 320)
        self.assertFalse(page.evaluate(SHAPE)["beside"])
        self.assertTrue(
            page.evaluate("()=>!!document.querySelector('#doc .pgw>.pv[data-page=\"3\"]>.nt-chip')"),
            "the chip was lost",
        )
        self.assertLess(abs(page.evaluate(at) - was), 3)
        self.resize(page, 370)
        self.assertTrue(page.evaluate(SHAPE)["beside"])
        self.assertTrue(page.evaluate(PANEL)["chip"], "the chip did not come back to the panel")
        self.assertLess(abs(page.evaluate(at) - was), 3)

    def test_a_draft_on_another_page_shows_on_its_summary_and_its_view_brings_it_to_the_panel(self):
        """A folded draft on page 3, page 1 read: the panel does not show page 3, so its summary says '초안 있음'; [보기] on
        the status line's way (pvShowLine) brings page 3 to the panel with the focus on the mark."""
        page = self.on()
        self.to(page, 3)
        page.locator('#pv-panel button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.locator('#pv-panel [data-act="pv-reason-open"]').click()
        page.keyboard.type("쓰다 둔 이유")
        page.locator('#pv-panel [data-act="pv-reason-fold"]').click()
        settle(page)
        self.to(page, 1)
        self.assertIn("초안 있음", page.locator('#doc .pv-sum[data-page="3"]').inner_text())
        self.assertNotIn("초안 있음", page.locator('#doc .pv-sum[data-page="2"]').inner_text())
        page.evaluate("pvShowLine(3)")
        settle(page)
        self.assertEqual(page.evaluate(PANEL)["page"], 3)
        self.assertEqual(page.evaluate("()=>document.activeElement.classList.contains('pv-draft')"), True)

    def test_the_pressed_words_context_stands_under_the_panel_and_brings_no_scroll_bar(self):
        """The pressed word hovered: its context shows under the panel, whole, and the panel keeps its size and does not
        scroll: a scroller clipped it there and a scroll bar narrowed the rows."""
        self.verdict(1, "채택")
        page = self.on(n_open=1)
        page.evaluate("()=>{const p=document.getElementById('pv-panel'); window.__w=p.clientWidth;}")
        page.locator('#pv-panel button[data-key="채택"]').hover()
        settle(page)
        got = page.evaluate(
            """()=>{const p=document.getElementById('pv-panel'),h=p.querySelector('.pv-onhint'),r=p.getBoundingClientRect(),b=h.getBoundingClientRect(),m=document.elementFromPoint(b.left+b.width/2,b.top+b.height/2);
              return {shown:b.height>0&&b.top>=r.bottom,top:!!m,overflow:getComputedStyle(p).overflowY,same:p.clientWidth===window.__w};}"""
        )
        self.assertEqual(got, {"shown": True, "top": True, "overflow": "visible", "same": True})

    def test_a_panel_taller_than_the_area_scrolls_inside_and_keeps_its_last_control_reachable(self):
        """A 400px window with the reason popover open: the panel is no taller than the PDF area shows and scrolls, so [저장]
        can be reached; closed again, its chip gone, it no longer scrolls."""
        page = self.on(viewport={"width": 1920, "height": 400})
        self.assertTrue(page.evaluate(SHAPE)["beside"])
        page.locator('#pv-panel button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.locator('#pv-panel [data-act="pv-reason-open"]').click()
        settle(page)
        got = page.evaluate(
            """()=>{const p=document.getElementById('pv-panel'),L=document.querySelector('#left').getBoundingClientRect(),r=p.getBoundingClientRect();
              return {tall:p.classList.contains('pv-tall'),inside:r.bottom<=L.bottom,scrolls:p.scrollHeight>p.clientHeight};}"""
        )
        self.assertEqual(got, {"tall": True, "inside": True, "scrolls": True})
        page.locator('#pv-panel [data-act="pv-reason-save"]').scroll_into_view_if_needed()
        self.assertTrue(page.locator('#pv-panel [data-act="pv-reason-save"]').is_visible())
        page.evaluate(
            "()=>{document.activeElement.blur(); pvReasonEnd(false); NOTICES.forEach(n=>{if(n.place==='chip')endNotice(n,false);});}"
        )
        settle(page)
        self.assertFalse(page.evaluate("()=>document.getElementById('pv-panel').classList.contains('pv-tall')"))

    def test_the_summary_and_the_panel_speak_english(self):
        """In English the summary reads 'p. 1 · No verdict', its name says what a press does, and the panel's own words are
        the state's."""
        page = self.on(lang="en")
        s = page.locator('#doc .pv-sum[data-page="1"]')
        self.assertIn("No verdict", s.inner_text())
        self.assertEqual(s.get_attribute("aria-label"), "p. 1 · PL11 · No verdict · show in the verdict panel")
        self.assertIn("No verdict", page.evaluate(PANEL)["text"])


class PanelViewer(PanelBase):
    """A viewer reads the panel and makes no verdict."""

    WHO = CAROL_VIEWER

    def test_a_viewer_reads_the_panel_without_words(self):
        """The panel says the page's verdict and has no word; the summary still says it and still brings its page."""
        member_add(ps.APP.C.state, CAROL_VIEWER["Tailscale-User-Login"], "viewer")
        pid = self.verdict(2, "채택")
        page = self.on(n_open=1)
        page.locator('#doc .pv-sum[data-page="2"]').click()
        settle(page)
        got = page.evaluate(PANEL)
        self.assertEqual((got["page"], got["words"]), (2, []), got)
        self.assertIn("판정 #%d 채택" % pid, got["text"])


WORD = '#doc .pv[data-page="%d"] button[data-key="%s"]'
LINE_ACT = '#doc .pv[data-page="%d"] [data-act="%s"]'
FIELD = "#doc .pv-pop .pv-reason"
LAYOUTS = (("beside", WIDE), ("under", {"viewport": {"width": 1400, "height": 850}}))


class TheLinesMove(PanelBase):
    """The room crossing its bar with something in hand: every line goes and comes, and nothing the person has goes with them.
    Page 5's top stands 150px under the area's top, so the reading line is 10px into it, and the 4px each block changes by
    puts that line on page 4 unless the spot is kept first."""

    def typed(self, page, n=5, text="쓰다 만 이유"):
        """Alice's 채택 on page n by the panel, a reason typed with the caret one back from its end; the pin's id."""
        page.evaluate(TO, [n, 150])
        settle(page)
        self.assertEqual(page.evaluate("pvReadingPage()"), n)
        page.locator(WORD % (n, "채택")).click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.locator(LINE_ACT % (n, "pv-reason-open")).click()
        page.keyboard.type(text)
        page.keyboard.press("ArrowLeft")
        (pid,) = self.pins()
        return pid

    def holds(self, page, pid, beside, text, n=5):
        """The popover crossed: where the lines are now, the field has the focus and the text, nothing was written, the page
        read is the same and no write is out. Digits typed on go into the text."""
        self.assertEqual(page.evaluate(SHAPE)["beside"], beside)
        self.assertTrue(page.evaluate("()=>pvIsReasonField(document.activeElement)"), "the field lost the focus")
        self.assertEqual(page.locator(FIELD).input_value(), text)
        self.assertEqual(page.evaluate("pvReadingPage()"), n)
        self.assertEqual(self.pins()[pid]["note"], "", "the half text was written")

    def test_a_resize_keeps_the_reason_and_the_page_where_it_stands_both_ways(self):
        """Across the bar and back: the field, its text and caret, nothing written, digits stay text, and page 5 does not move
        on the screen (it moved by 40px with the anchor at the area's top)."""
        page = self.on()
        pid = self.typed(page)
        at = "()=>Math.round(document.getElementById('p5').getBoundingClientRect().top-document.querySelector('#left').getBoundingClientRect().top)"
        was = page.evaluate(at)
        text = "쓰다 만 이유"
        for room, beside, digit in ((320, False, "7"), (370, True, "8")):
            with self.subTest(beside=beside):
                self.resize(page, room)
                self.holds(page, pid, beside, text, 5)
                self.assertLess(abs(page.evaluate(at) - was), 2)
                page.keyboard.type(digit)
                text = text[:-1] + digit + text[-1]
                page.keyboard.press("ArrowLeft")
                page.keyboard.press("ArrowRight")
                self.assertEqual(page.locator(FIELD).input_value(), text)
        self.assertEqual(len(self.pins()), 1, "a digit became a verdict")

    def test_a_zoom_keeps_the_reason_both_ways(self):
        """A zoom step across the bar, and 100% back: the same. The lines moved inside the zoom, before it put its place back,
        so the reading page was another one and the text was written."""
        page = self.on()
        pid = self.typed(page, 4)
        page.evaluate("zoom(1)")
        settle(page)
        self.assertLess(page.evaluate(ROOM), 328)
        self.holds(page, pid, False, "쓰다 만 이유", 4)
        page.evaluate("actualSize()")
        settle(page)
        self.holds(page, pid, True, "쓰다 만 이유", 4)

    def test_the_pin_panel_keeps_the_reason_both_ways(self):
        """1680 with the pin panel closed, the panel opened over a reason being typed, and closed again: the same."""
        page = self.on(viewport={"width": 1680, "height": 1050})
        page.evaluate("setSide(false)")
        settle(page)
        pid = self.typed(page)
        page.evaluate("setSide(true)")
        settle(page)
        self.holds(page, pid, False, "쓰다 만 이유")
        page.evaluate("setSide(false)")
        settle(page)
        self.holds(page, pid, True, "쓰다 만 이유")

    def test_a_popover_waiting_for_its_number_crosses_and_binds_to_its_verdict(self):
        """A digit's save held, Enter, text typed; the bar crossed; the save answers: one verdict, and the text goes on it."""
        page = self.on()
        page.evaluate(TO, [5, 150])
        settle(page)
        page.evaluate("searchToPage()")
        self.held_pin = []
        page.keyboard.press("2")
        page.wait_for_function("()=>PV_BUSY.size===1")
        page.keyboard.press("Enter")
        page.wait_for_selector(FIELD)
        page.keyboard.type("기다린 이유")
        self.narrowed(page)
        self.assertTrue(page.evaluate("()=>pvIsReasonField(document.activeElement)"), "the field lost the focus")
        held, self.held_pin = self.held_pin, None
        self.release(held, page=page)
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.some(p=>p.note==='기다린 이유')")
        self.assertEqual([(p["page"], p["verdict"]) for p in self.pins().values()], [(5, "보류")])

    def test_a_write_out_crosses_and_its_answer_closes_the_field(self):
        """Enter sent the reason and the answer is held; the bar crossed: the field waits on, with the focus; the answer writes
        the note once and closes it."""
        page = self.on()
        pid = self.typed(page)
        self.held_edit = []
        page.keyboard.press("Enter")
        page.wait_for_function("()=>document.querySelector('#doc .pv-reason').readOnly")
        self.narrowed(page)
        self.assertTrue(page.evaluate("()=>pvIsReasonField(document.activeElement)&&document.activeElement.readOnly"))
        held, self.held_edit = self.held_edit, None
        self.release(held, page=page)
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=pid)
        settle(page)
        self.assertEqual(page.locator(FIELD).count(), 0)
        self.assertEqual(self.pins()[pid]["note"], "쓰다 만 이유")
        self.assertIsNotNone(page.evaluate(FOCUS))


class FastKeys(PanelBase):
    """A person who does not wait for the answer: in the panel and under the pages alike."""

    def test_enter_on_a_word_while_a_digits_save_is_out_is_the_reason(self):
        """The focus on the first word, 2 saves 보류 and its answer is held, Enter: the reason opens for that save instead of
        pressing the word under the focus. One verdict, with the text on it."""
        for name, device in LAYOUTS:
            with self.subTest(layout=name):
                page = self.on(**device)
                n = 2 if name == "beside" else 3
                self.to(page, n)
                page.locator(WORD % (n, "채택")).focus()
                self.held_pin = []
                page.keyboard.press("2")
                page.wait_for_function("()=>PV_BUSY.size===1")
                page.keyboard.press("Enter")
                page.wait_for_selector(FIELD)
                text = "빠른 이유 " + name
                page.keyboard.type(text)
                page.keyboard.press("Enter")
                held, self.held_pin = self.held_pin, None
                self.release(held, page=page)
                page.wait_for_function("t=>OPEN_ALL.some(p=>p.note===t)", arg=text)
                settle(page)
                got = [(p["verdict"], p["note"]) for p in self.pins().values() if p["page"] == n]
                self.assertEqual(got, [("보류", text)])

    def test_enter_on_the_way_to_the_reason_right_after_a_new_save_writes_on_the_new_verdict(self):
        """보류 saved, then 삭제 (two presses): its POST answered, the list not read again yet, so the line still shows 보류. Enter on
        'Enter 이유 쓰기' waits for the new verdict, and the reason goes on 삭제, not on 보류."""
        for name, device in LAYOUTS:
            with self.subTest(layout=name):
                page = self.on(**device)
                n = 4 if name == "beside" else 5
                self.to(page, n)
                page.evaluate("searchToPage()")
                page.keyboard.press("2")
                page.wait_for_function("n=>(pageVerdictPins().get(n)||[]).length===1", arg=n)
                settle(page)
                self.assertEqual(page.evaluate(FOCUS)["act"], "pv-reason-open")
                pins = len(self.pins())
                page.keyboard.press("3")
                settle(page)
                self.held_list = []
                page.keyboard.press("3")
                for _ in range(300):
                    if len(self.pins()) > pins and self.held_list:
                        break
                    page.wait_for_timeout(10)
                self.assertEqual(len(self.pins()), pins + 1, "the save did not land")
                page.locator(LINE_ACT % (n, "pv-reason-open")).first.focus()
                page.keyboard.press("Enter")
                page.wait_for_selector(FIELD)
                text = "새 판정의 이유 " + name
                page.keyboard.type(text)
                held, self.held_list = self.held_list, None
                self.release(held)
                page.wait_for_function("n=>(pageVerdictPins().get(n)||[]).length===2", arg=n)
                settle(page)
                page.keyboard.press("Enter")
                page.wait_for_function("t=>OPEN_ALL.some(p=>p.note===t)", arg=text)
                got = {p["verdict"]: p["note"] for p in self.pins().values() if p["page"] == n}
                self.assertEqual(got, {"보류": "", "삭제": text})

    def test_a_press_on_the_way_to_the_reason_right_after_a_click_save_waits_for_the_new_verdict(self):
        """The same with the mouse, where no digit's save stands for it: 보류 pressed, then 채택 with the list not read again yet.
        [이유 추가], still 보류's on screen, opens the reason for 채택."""
        page = self.on()
        self.to(page, 2)
        page.locator(WORD % (2, "보류")).click()
        page.wait_for_function("n=>(pageVerdictPins().get(n)||[]).length===1", arg=2)
        settle(page)
        self.held_list = []
        page.locator(WORD % (2, "채택")).click()
        for _ in range(300):
            if len(self.pins()) == 2 and self.held_list:
                break
            page.wait_for_timeout(10)
        self.assertEqual(len(self.pins()), 2, "the save did not land")
        page.locator(LINE_ACT % (2, "pv-reason-open")).first.click()
        page.wait_for_selector(FIELD)
        page.keyboard.type("마우스의 이유")
        held, self.held_list = self.held_list, None
        self.release(held)
        page.wait_for_function("n=>(pageVerdictPins().get(n)||[]).length===2", arg=2)
        settle(page)
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.some(p=>p.note==='마우스의 이유')")
        got = {p["verdict"]: p["note"] for p in self.pins().values()}
        self.assertEqual(got, {"보류": "", "채택": "마우스의 이유"})

    def test_the_field_keeps_the_focus_while_its_write_is_out_and_after_a_failure(self):
        """Enter with the write held: the focus stays in the field, which waits; a digit is no verdict. Answered 500: the text
        and the focus are there. Enter again held, and the page left: the focus is on the PDF area, never on nothing."""
        for name, device in LAYOUTS:
            with self.subTest(layout=name):
                page = self.on(**device)
                n = 2 if name == "beside" else 3
                self.to(page, n)
                page.locator(WORD % (n, "채택")).click()
                page.wait_for_function("n=>(pageVerdictPins().get(n)||[]).length===1", arg=n)
                settle(page)
                page.locator(LINE_ACT % (n, "pv-reason-open")).click()
                text = "이유 " + name
                page.keyboard.type(text)
                self.held_edit = []
                page.keyboard.press("Enter")
                page.wait_for_function("()=>document.querySelector('#doc .pv-reason').readOnly")
                self.assertTrue(
                    page.evaluate("()=>pvIsReasonField(document.activeElement)"), "the write dropped the focus"
                )
                before = len(self.pins())
                page.keyboard.press("2")
                self.assertEqual(len(self.pins()), before)
                held = self.held_edit
                self.release(held, 500, page)
                self.held_edit = []
                page.wait_for_function("()=>!document.querySelector('#doc .pv-reason').readOnly")
                settle(page)
                self.assertTrue(
                    page.evaluate("()=>pvIsReasonField(document.activeElement)"),
                    "the failure left the field without the focus",
                )
                self.assertEqual(page.locator(FIELD).input_value(), text)
                page.keyboard.press("Enter")
                page.wait_for_function("()=>document.querySelector('#doc .pv-reason').readOnly")
                page.evaluate(TO, [n + 1, 16])
                page.wait_for_function("()=>document.activeElement===document.querySelector('#left')")
                held, self.held_edit = self.held_edit, None
                self.release(held, page=page)
                page.wait_for_function("t=>OPEN_ALL.some(p=>p.note===t)", arg=text)
                self.assertIsNotNone(page.evaluate(FOCUS), "the focus is on nothing")

    def test_a_digit_before_a_jumps_first_scroll_acts_on_no_page(self):
        """An outline jump to page 5 and a digit in the same task, before the first scroll event: the glide guard says so on
        the status line and nothing is saved on the page being left."""
        page = self.on()
        self.to(page, 2)
        page.evaluate(
            """()=>{OUTLINE_ENTRIES=[{page:5,frac:0,title:'F05',level:0}]; pickOutline(0);
              document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'1',bubbles:true}));}"""
        )
        settle(page)
        self.assertEqual(self.pins(), {})
        self.assertTrue(page.evaluate("()=>LINE.some(n=>n.title.includes('쪽으로 가는 중'))"))


class Undo(PanelBase):
    """The [되돌리기] of a take-back on another page than the one being read."""

    def taken_back(self, page, n):
        """A reason being written on page n's 채택, taken back from its line; the pin's id."""
        self.to(page, n)
        page.locator(WORD % (n, "채택")).click()
        page.wait_for_function("n=>(pageVerdictPins().get(n)||[]).length===1", arg=n)
        settle(page)
        page.locator(LINE_ACT % (n, "pv-reason-open")).click()
        page.keyboard.type("앞 쪽의 초안")
        page.locator(LINE_ACT % (n, "pv-cancel")).click()
        page.wait_for_function("n=>!(pageVerdictPins().get(n)||[]).length", arg=n)
        settle(page)
        return page.evaluate("()=>LINE.find(n=>!!n.act&&n.title.includes('취소')).n")

    def test_restoring_a_verdict_of_another_page_leaves_the_field_on_this_one(self):
        """A's take-back undone while B's reason is typed: B's field keeps the focus and its text and nothing is written on B;
        A is back with its draft marked on its summary, and no session for it is open. Digits typed on stay text."""
        page = self.on()
        undo = self.taken_back(page, 2)
        self.to(page, 3)
        page.locator(WORD % (3, "보류")).click()
        page.wait_for_function("n=>(pageVerdictPins().get(n)||[]).length===1", arg=3)
        settle(page)
        page.locator(LINE_ACT % (3, "pv-reason-open")).click()
        page.keyboard.type("이 쪽의 글")
        page.evaluate("n=>noticeAct(n)", undo)
        page.wait_for_function("n=>(pageVerdictPins().get(n)||[]).length===1", arg=2)
        settle(page)
        self.assertTrue(page.evaluate("()=>pvIsReasonField(document.activeElement)"), "the field lost the focus")
        self.assertEqual(page.evaluate("()=>PV_REASON&&PV_REASON.page"), 3)
        page.keyboard.type("7")
        self.assertEqual(page.locator(FIELD).input_value(), "이 쪽의 글7")
        self.assertEqual({p["page"]: p["note"] for p in self.pins().values()}, {2: "", 3: ""})
        self.assertIn("초안 있음", page.locator('#doc .pv-sum[data-page="2"]').inner_text())

    def test_with_no_field_open_the_draft_stays_its_own_and_the_next_verdict_does_not_take_it(self):
        """A's take-back undone on B with no field open: no invisible session for A; a verdict on B then writes nothing on A,
        and A's draft waits on its summary and opens on A."""
        page = self.on()
        undo = self.taken_back(page, 2)
        self.to(page, 3)
        page.evaluate("n=>noticeAct(n)", undo)
        page.wait_for_function("n=>(pageVerdictPins().get(n)||[]).length===1", arg=2)
        settle(page)
        self.assertIsNone(page.evaluate("()=>PV_REASON&&PV_REASON.page"))
        page.locator(WORD % (3, "보류")).click()
        page.wait_for_function("n=>(pageVerdictPins().get(n)||[]).length===1", arg=3)
        settle(page)
        self.assertEqual({p["page"]: p["note"] for p in self.pins().values()}, {2: "", 3: ""})
        self.assertIn("초안 있음", page.locator('#doc .pv-sum[data-page="2"]').inner_text())
        self.to(page, 2)
        page.locator("#pv-panel button.pv-draft").click()
        self.assertEqual(page.locator(FIELD).input_value(), "앞 쪽의 초안")


class Reach(PanelBase):
    """What the keyboard reaches from the panel, and where it comes back."""

    def test_shift_tab_from_a_summarys_press_goes_back_to_it_and_tab_comes_back(self):
        """A summary pressed: the focus is in the panel; Shift+Tab goes back to that summary, in view; Tab comes to the panel."""
        page = self.on()
        self.to(page, 2, off=-500)
        page.locator('#doc .pv-sum[data-page="2"]').click()
        settle(page)
        self.assertTrue(page.evaluate(FOCUS)["panel"])
        page.keyboard.press("Shift+Tab")
        settle(page)
        self.assertEqual(
            page.evaluate("()=>document.activeElement.dataset.page+document.activeElement.className.split(' ')[0]"),
            "2pv-sum",
        )
        self.assertTrue(page.locator('#doc .pv-sum[data-page="2"]').is_visible())
        self.assertTrue(
            page.evaluate(
                "()=>{const r=document.activeElement.getBoundingClientRect(),L=document.querySelector('#left').getBoundingClientRect();return r.top>=L.top&&r.bottom<=L.bottom;}"
            )
        )
        page.keyboard.press("Tab")
        self.assertTrue(page.evaluate(FOCUS)["panel"])

    def test_the_reading_pages_marks_are_reached_from_the_panel_and_left_as_from_a_line(self):
        """An ordinary pin on page 2: Shift+Tab from the panel's first control goes to its mark, Tab from the mark comes back,
        and Shift+Tab from the mark leaves the pages. They were reachable by nothing."""
        self.verdict(2, None)
        page = self.on(n_open=1)
        self.to(page, 2)
        page.locator("#section-page").focus()
        page.keyboard.press("Tab")
        self.assertTrue(page.evaluate(FOCUS)["panel"])
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate("()=>document.activeElement.dataset.act"), "mark-jump")
        page.keyboard.press("Tab")
        self.assertTrue(page.evaluate(FOCUS)["panel"])
        page.keyboard.press("Shift+Tab")
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate(FOCUS)["id"], "section-page")

    def test_esc_on_the_panel_hands_the_focus_to_the_pdf_area_and_lets_a_confirm_word_go_first(self):
        """Esc on a word: the PDF area has the focus, and Tab comes back. With a confirm word armed the first Esc lets it go."""
        page = self.on()
        self.to(page, 2)
        page.locator('#pv-panel button[data-key="삭제"]').click()
        settle(page)
        page.keyboard.press("Escape")
        self.assertIsNone(page.evaluate("()=>VD_ARM"))
        self.assertTrue(page.evaluate(FOCUS)["panel"])
        page.keyboard.press("Escape")
        self.assertEqual(page.evaluate(FOCUS)["id"], "left")
        page.keyboard.press("Tab")
        self.assertTrue(page.evaluate(FOCUS)["panel"])

    def test_a_chips_undo_by_key_leaves_the_focus_on_the_page_and_a_digit_on_a_lines_undo_too(self):
        """[되돌리기] of a save chip pressed by Enter: the verdict goes and the focus is on the panel, not on nothing. Then a
        take-back's [되돌리기] with the focus on it and a digit whose save is held: the focus is on the word being saved."""
        page = self.on()
        self.to(page, 2)
        page.evaluate("searchToPage()")
        page.keyboard.press("1")
        page.wait_for_selector("#pv-panel>.nt-chip")
        settle(page)
        page.locator('#pv-panel>.nt-chip [data-act="notice-act"]').focus()
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.length===0")
        settle(page)
        got = page.evaluate(FOCUS)
        self.assertTrue(got and got["panel"], got)
        page.locator('#pv-panel button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.evaluate("()=>NOTICES.forEach(n=>{if(n.place==='chip')endNotice(n,false);})")
        settle(page)
        page.locator("#pv-panel button.pv-cancel").focus()
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.length===0")
        page.wait_for_selector('#pv-panel [data-act="pv-undo"]')
        settle(page)
        self.held_pin = []
        page.keyboard.press("2")
        page.wait_for_function("()=>PV_BUSY.size===1")
        got = page.evaluate(FOCUS)
        self.assertEqual((got or {}).get("act"), "pv-save", got)
        held, self.held_pin = self.held_pin, None
        self.release(held, page=page)

    def test_the_reading_line_is_exact_at_a_pages_end(self):
        """Page 2's last pixels 0.64px under the reading line: the page read is page 2, for the strip, the panel and the keys."""
        (self.pages_dir / "page-2.png").write_bytes(blank_png(1275, 1651))
        page = self.on()
        page.evaluate(
            """()=>{PV_HAND(); const L=document.querySelector('#left'),r=document.getElementById('p2').getBoundingClientRect(),y=L.getBoundingClientRect().top+readingDepth(L);
              L.scrollTop+=Math.floor(r.bottom-y);}"""
        )
        settle(page)
        off = page.evaluate(
            "()=>{const L=document.querySelector('#left');return document.getElementById('p2').getBoundingClientRect().bottom-L.getBoundingClientRect().top-readingDepth(L);}"
        )
        self.assertTrue(0 < off < 1, off)
        self.assertEqual(page.evaluate(PANEL)["page"], 2)
        self.assertTrue(page.locator("#section-page-t").inner_text().startswith("2 "))


class Look(PanelBase):
    """The panel's own rows."""

    def test_every_row_starts_at_one_edge_and_the_words_stand_still_between_pages(self):
        """The state, the reason and [판정 취소] start at one left edge; [이유 추가] too. A page with a pressed word and one
        without have their words in the same places. The popover has no frame of its own in the panel."""
        page = self.on()
        self.to(page, 3)
        words = "()=>[...document.querySelectorAll('#pv-panel button.vd-b')].map(b=>Math.round(b.getBoundingClientRect().left))"
        empty = page.evaluate(words)
        self.to(page, 2)
        page.locator('#pv-panel button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        self.assertEqual(page.evaluate(words), empty, "the pressed word's check moved the words")
        edge = """()=>[...document.querySelectorAll('#pv-panel .pv-t>.pv-s,#pv-panel .pv-t button:is(.pv-add,.pv-note,.pv-cancel)')].filter(e=>e.getClientRects().length).map(e=>Math.round(e.getBoundingClientRect().left))"""
        got = page.evaluate(edge)
        self.assertGreaterEqual(len(got), 3, got)
        self.assertEqual(len(set(got)), 1, got)
        page.locator('#pv-panel [data-act="pv-reason-open"]').click()
        page.keyboard.type("이유")
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.some(p=>p.note==='이유')")
        settle(page)
        got = page.evaluate(edge)
        self.assertEqual(len(set(got)), 1, got)
        page.locator('#pv-panel [data-act="pv-reason-open"]').first.click()
        got = page.evaluate(
            "()=>{const c=getComputedStyle(document.querySelector('#pv-panel>.pv-pop'));return [c.borderTopWidth,c.boxShadow,c.paddingLeft];}"
        )
        self.assertEqual(got, ["0px", "none", "0px"])

    def test_a_page_with_no_verdict_keeps_no_room_for_a_title(self):
        """A list page: its notice stands right under its name."""
        page = self.on()
        self.to(page, N_PAGES)
        got = page.evaluate(
            "()=>{const p=document.getElementById('pv-panel');return [getComputedStyle(p.querySelector('.pv-fig-t')).display, p.querySelector('.pv-s').getBoundingClientRect().top-p.querySelector('.pv-fig-id').getBoundingClientRect().bottom];}"
        )
        self.assertEqual(got[0], "none")
        self.assertLess(got[1], 32, got)


class WideTouch(PanelBase):
    """A touch screen wide enough for the panel."""

    DEVICE = {
        "viewport": {"width": 1920, "height": 1080},
        "is_mobile": True,
        "has_touch": True,
        "device_scale_factor": 1,
    }

    def test_the_rows_keep_apart_and_the_words_stay_while_a_reason_is_typed(self):
        """The title's two rows end above the words; a reason started moves no word; the '#N' link and a summary answer 44px."""
        page = self.on(**self.DEVICE)
        self.assertTrue(page.evaluate(SHAPE)["beside"])
        self.to(page, 2)
        page.locator('#pv-panel button[data-key="채택"]').tap()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.evaluate("()=>NOTICES.forEach(n=>{if(n.place==='chip')endNotice(n,false);})")
        settle(page)
        got = page.evaluate(
            "()=>{const p=document.getElementById('pv-panel');return p.querySelector('.vd-btns').getBoundingClientRect().top-p.querySelector('.pv-fig').getBoundingClientRect().bottom;}"
        )
        self.assertGreaterEqual(got, 0, "the title lies over the words")
        self.assertEqual(page.evaluate(MISSES_44, "#pv-panel .pv-ref"), [])
        self.to(page, 2, off=-500)
        self.assertEqual(page.evaluate(MISSES_44, '#doc .pv-sum[data-page="2"]'), [])
        self.to(page, 2)
        top = page.evaluate(PANEL)["wordTop"]
        page.locator('#pv-panel [data-act="pv-reason-open"]').tap()
        page.wait_for_selector("#pv-panel .pv-reason")
        settle(page)
        self.assertEqual(page.evaluate(PANEL)["wordTop"], top, "starting a reason moved the words")

    def test_a_summary_shows_its_press_and_a_long_press_only_describes(self):
        """Pressed, a summary is marked; a long press shows what it says and its release does not go to the page."""
        page = self.on(**self.DEVICE)
        self.to(page, 1, off=-500)
        s = page.locator('#doc .pv-sum[data-page="1"]')
        box = s.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        self.assertIn("inset", s.evaluate("e=>getComputedStyle(e).boxShadow"))
        page.mouse.move(x, y + 200)
        page.mouse.up()
        top = page.evaluate(TOP)
        cdp = page.context.new_cdp_session(page)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        page.wait_for_function("()=>!document.querySelector('#tip').hidden", timeout=3000)
        self.assertIn("판정 없음", page.evaluate("()=>document.querySelector('#tip').textContent"))
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        nothing_follows(page)
        self.assertEqual(page.evaluate(TOP), top, "the long press's release brought the page")


class Fallback(PanelBase):
    """Where the room is short, the lines stand under the pages exactly as 0.4.36 draws them."""

    LINES = """() => [...document.querySelectorAll('#doc .pgw')].map(b => [getComputedStyle(b).display,
      [...b.children].map(c => c.className.replace(/\\s*\\b(flash|pv-far)\\b/g, '') + '|' + (c.classList.contains('pv') ? c.style.width + '|' + c.textContent : ''))])"""

    def test_a_narrow_window_has_the_lines_under_the_pages_as_before_and_a_wide_one_put_back_draws_the_same(self):
        """1400 x 850 (CI's desktop): no panel, no summary, a line under each page. The same viewer opened at 1920 and made
        1400 again draws every block, line and width as the one opened at 1400."""
        self.verdict(2, "채택")
        narrow = self.on(n_open=1, viewport={"width": 1400, "height": 850})
        self.assertEqual(
            narrow.evaluate(SHAPE), {"beside": False, "panel": False, "lines": TAKING, "sums": 0, "side": False}
        )
        want = narrow.evaluate(self.LINES)
        wide = self.on(n_open=1)
        self.assertTrue(wide.evaluate(SHAPE)["beside"])
        wide.set_viewport_size({"width": 1400, "height": 850})
        settle(wide)
        wide.evaluate("()=>{document.querySelector('#left').scrollTop=0;}")
        settle(wide)
        self.assertEqual(
            wide.evaluate(SHAPE), {"beside": False, "panel": False, "lines": TAKING, "sums": 0, "side": False}
        )
        self.assertEqual(wide.evaluate(self.LINES), want)

    def test_the_foldable_and_the_phone_never_take_the_panel(self):
        """The unfolded foldable (both orientations), a tablet and a phone: lines under the pages, no panel."""
        for name in ("fold inner 841x673", "fold inner 673x841", "tablet 1024x768", "phone 390x844"):
            with self.subTest(device=name):
                page = self.on(**VIEWPORTS[name])
                got = page.evaluate(SHAPE)
                self.assertEqual((got["panel"], got["beside"], got["sums"]), (False, False, 0), got)
                self.assertEqual(got["lines"], TAKING, got)
