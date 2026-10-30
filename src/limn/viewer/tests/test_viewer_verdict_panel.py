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
from helpers_browser import VIEWPORTS, BrowserBase, nothing_follows, settle

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
        patch = mock.patch.object(pick_source, "region_text", return_value="")  # pdftotext answers no text
        patch.start()
        self.addCleanup(patch.stop)

    def route(self, route):
        rq = route.request
        path = urlparse(rq.url).path
        if path == "/api/pin" and rq.method == "POST":
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

    def verdict(self, n, key, doc="fig", who=ALICE):
        """A verdict of who's on page n's whole target, made through the API as the page line makes it; its id."""
        meta = self.call("GET", "/api/meta?doc=" + doc)[1]
        pg = meta["pages"][n - 1]
        pick = {"doc": doc, "page": n, "x0": 0, "y0": 0, "x1": pg["pt_w"], "y1": pg["pt_h"], "frac": [0, 0, 1, 1]}
        code, d = self.call("POST", "/api/pick", {**pick, "pdf_build": meta["pages_build"]}, who)
        self.assertEqual(code, 200, d)
        body = {k: d[k] for k in helpers_figure.SAVE_LINE if d.get(k) is not None}
        body.update(scope=d.get("default_level"), doc=doc, note="", verdict=key, kind_req="fix", assignee="agent")
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
        self.assertEqual(s.get_attribute("aria-label"), "Show p. 1 in the verdict panel")
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
