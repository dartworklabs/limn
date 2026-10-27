"""Verdict pins in the real viewer (docs/handbook/viewer.md §판정 핀; spec 2026-10-26-verdict-pins.md §뷰어, §검증 뷰어).

The three documents of helpers_figure.viewer_docs - a LaTeX manuscript (ms), a figure document (fig) and a view-only PDF
(rv) - each with a word file declaring 채택, 보류 and 삭제 (a confirm word), page: true on the figure and the PDF. The
composer's verdict row saves the selection and its note as a verdict; a page verdict line under each page saves a verdict
about the page's whole target and leaves the composer alone, says the newest verdict's state, and takes the place of its
page-size mark; a confirm word takes two presses bound to what it was armed on; the undo withdraws the pin; a verdict pin's
edit card keeps its verdict and target; a viewer reads the line without buttons. The figure document's and the PDF's picks
go to the real handler (the map pick; pdftotext stood in for), the manuscript's to BrowserBase's computed answer.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_verdicts.py
"""

import json
from unittest import mock
from urllib.parse import urlparse

from limn.pins.location import source as pick_source

import helpers_figure
from helpers import ps, split_resp
from helpers_access import ALICE, BOB, member_add, talk_to
from helpers_browser import MISSES_44, BrowserBase, settle

WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}]}
AGENT = {"Tailscale-User-Login": "agentb@example.com", "Tailscale-User-Name": "Agent B"}
CAROL_VIEWER = {"Tailscale-User-Login": "carol@example.com", "Tailscale-User-Name": "Carol Lee"}
# The text of page n's line, its buttons' words, and whether its line is there at all.
LINE = """n => {const l = document.querySelector('#doc .pv[data-page="' + n + '"]'); if (!l) return null;
  return {text: l.querySelector('.pv-t').textContent, pin: l.dataset.pin || null, words: [...l.querySelectorAll('button.vd-b')].map(b => b.textContent)};}"""


class VerdictBase(BrowserBase):
    """The three documents with their word files; the figure's and the PDF's picks reach the real handler."""

    def setUp(self):
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        src = ps.APP.C.src
        self.word_files = {
            "ms": src / "main.limnverdicts.json",
            "fig": self.fig.main.parent / "figures.limnverdicts.json",
            "rv": src / "reviewer.limnverdicts.json",
        }
        for key, path in self.word_files.items():
            path.write_text(json.dumps({**WORDS, "page": key != "ms"}, ensure_ascii=False), encoding="utf-8")
        member_add(ps.APP.C.state, AGENT["Tailscale-User-Login"], "agent")
        patch = mock.patch.object(pick_source, "region_text", return_value="")
        patch.start()
        self.addCleanup(patch.stop)

    def route(self, route):
        """A pick on the figure or the PDF goes to the handler; the manuscript's gets the computed answer."""
        rq = route.request
        if urlparse(rq.url).path == "/api/pick" and (json.loads(rq.post_data or "{}").get("doc") in ("fig", "rv")):
            return self.forward(route)
        return super().route(route)

    def call(self, method, path, body=None, who=ALICE):
        """One request to the handler as who (Tailscale headers, a same-origin Origin on a POST) -> (status, JSON)."""
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
        """Every pin as GET /api/pins?all=1 answers, by id."""
        return {p["id"]: p for p in self.call("GET", "/api/pins?all=1")[1]}

    def on(self, doc, n_open=0, **device):
        """The viewer showing document doc, settled."""
        page = self.open(n_open, **device)
        if doc != "ms":
            page.evaluate("k=>switchDoc(k)", doc)
            page.wait_for_function("k=>DOC===k&&META&&META.doc===k&&document.querySelector('#p1')", arg=doc)
            settle(page)
        return page

    def press_page(self, page, n, key):
        """Press word key on page n's line and wait until the new pin is on the list; its id."""
        before = set(self.pins())
        page.locator('#doc .pv[data-page="%d"] button[data-key="%s"]' % (n, key)).click()
        page.wait_for_function(
            "n=>OPEN_ALL.length>=n", arg=len([p for p in self.pins().values() if p.get("state") == "open"]) + 1
        )
        settle(page)
        (new,) = set(self.pins()) - before
        return new

    def reload(self, page):
        """The list read again (an agent's change elsewhere)."""
        page.evaluate("loadPins()")
        settle(page)


class ComposerRow(VerdictBase):
    """The composer's verdict row: shown with words, saves the selection as a verdict, two presses for a confirm word."""

    def test_the_row_offers_the_words_in_file_order_only_where_there_are_words(self):
        """With words the row stands after the note and before the kind row, a button per word in file order, the
        confirm word in the danger colour; without a word file there is no row and no page line."""
        page = self.on("ms")
        self.open_composer(page)
        row = page.evaluate("""()=>{const r=document.querySelector('#c-verdict-row'), kids=[...document.querySelector('#composer').children].map(e=>e.id);
          return {shown: !r.hidden && r.getClientRects().length>0, words: [...r.querySelectorAll('button')].map(b=>b.textContent),
            confirm: [...r.querySelectorAll('button.vd-confirm')].map(b=>b.dataset.key), order: kids.indexOf('c-verdict-row') - kids.indexOf('c-kind-row'),
            afterNote: !!(document.querySelector('#note').compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING)};}""")
        self.assertEqual(
            row, {"shown": True, "words": ["채택", "보류", "삭제"], "confirm": ["삭제"], "order": -1, "afterNote": True}
        )
        self.assertEqual(page.locator("#popover-verdict, #sel-pop .vd-b").count(), 0)  # never in the note popover
        for f in self.word_files.values():
            f.unlink()
        page = self.on("ms")
        self.open_composer(page)
        self.assertTrue(page.evaluate("document.querySelector('#c-verdict-row').hidden"))
        page = self.on("fig")
        self.assertEqual(page.locator("#doc .pv").count(), 0)

    def test_a_word_saves_the_selection_and_its_note_as_a_verdict_pin(self):
        """채택 saves the selection with its note as a fix request carrying the verdict and no suggestion; the composer
        closes, '#N 저장됨' is offered, and the card's badge reads '판정 채택'."""
        page = self.on("ms")
        self.open_composer(page)
        page.fill("#note", "keep it")
        page.locator('#c-verdict-row button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        (pin,) = self.pins().values()
        self.assertEqual(
            (pin["verdict"], pin["note"], pin["kind_req"], "suggest" in pin), ("채택", "keep it", "fix", False)
        )
        self.assertTrue(page.evaluate("document.querySelector('#composer').hidden"))
        self.assertIn("#%d 저장됨" % pin["id"], page.evaluate("document.body.textContent"))
        self.assertEqual(page.locator('.pin[data-id="%d"] .badge-verdict' % pin["id"]).inner_text(), "판정 채택")

    def test_a_confirm_word_takes_two_presses_bound_to_what_it_armed_on(self):
        """삭제's first press saves nothing: it reads '삭제 확정' and a screen reader hears that the next press saves. Esc,
        a press elsewhere, another range and the time running out each let it go; two presses in a row save it."""
        page = self.on("ms")
        self.open_composer(page)
        btn = '#c-verdict-row button[data-key="삭제"]'

        def arm():
            page.locator(btn).click()
            settle(page)
            self.assertEqual(page.locator(btn).inner_text(), "삭제 확정")

        arm()
        self.assertEqual(self.pins(), {})
        self.assertIn("한 번 더 누르면 저장합니다", page.evaluate("document.querySelector('#sr-news').textContent"))
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.locator(btn).inner_text(), "삭제")
        self.assertFalse(page.evaluate("document.querySelector('#composer').hidden"))  # Esc only let the press go
        arm()
        page.locator("#note").click()
        settle(page)
        self.assertEqual(page.locator(btn).inner_text(), "삭제")
        arm()
        page.locator("#c-levels button:not(.on)").first.click()  # another range
        settle(page)
        self.assertEqual(page.locator(btn).inner_text(), "삭제")
        arm()
        page.wait_for_function("!VD_ARM", timeout=8000)  # 4s
        self.assertEqual(page.locator(btn).inner_text(), "삭제")
        self.assertEqual(self.pins(), {})
        arm()
        page.locator(btn).click()
        page.wait_for_function("OPEN_ALL.length===1")
        self.assertEqual([p["verdict"] for p in self.pins().values()], ["삭제"])

    def test_a_question_or_a_suggested_edit_turns_the_words_off_with_the_reason(self):
        """The kind 질문 and [제안 수정] on each turn every word off with its reason under them; back to a fix request with the
        switch off, they are on again."""
        page = self.on("ms")
        self.open_composer(page)
        state = "()=>({off:[...document.querySelectorAll('#c-verdict-row button')].every(b=>b.disabled),why:(document.querySelector('#c-verdict-row .vd-why')||{}).textContent||''})"
        page.locator('#c-kind button[data-kind="question"]').click()
        settle(page)
        s = page.evaluate(state)
        self.assertTrue(s["off"], s)
        self.assertIn("질문", s["why"])
        page.locator('#c-kind button[data-kind="fix"]').click()
        settle(page)
        self.assertEqual(page.evaluate(state), {"off": False, "why": ""})
        page.locator("#c-sg-tg").click()
        settle(page)
        s = page.evaluate(state)
        self.assertTrue(s["off"], s)
        self.assertIn("제안 수정", s["why"])

    def test_the_edit_card_of_a_verdict_pin_offers_its_note_only(self):
        """A verdict pin's edit card has no kind, range, suggestion or [위치 다시 잡기]; its note is saved and the
        verdict stays."""
        page = self.on("ms")
        self.open_composer(page)
        page.locator('#c-verdict-row button[data-key="보류"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        (pid,) = self.pins()
        page.evaluate("id=>openEdit(id)", pid)
        settle(page)
        shown = page.evaluate("""()=>Object.fromEntries(['.e-kind','.e-sg-row','.e-levels','.e-xp','.b-repick','.e-note','.b-esave']
          .map(s=>{const e=document.querySelector('.edit '+s); return [s, !!e&&e.getClientRects().length>0];}))""")
        self.assertEqual(
            shown,
            {
                ".e-kind": False,
                ".e-sg-row": False,
                ".e-levels": False,
                ".e-xp": False,
                ".b-repick": False,
                ".e-note": True,
                ".b-esave": True,
            },
        )
        page.fill(".edit .e-note", "later note")
        page.locator(".edit .b-esave").click()
        page.wait_for_function("!EDITOR.current")
        settle(page)
        pin = self.pins()[pid]
        self.assertEqual((pin["note"], pin["verdict"]), ("later note", "보류"))


class PageLine(VerdictBase):
    """The page verdict line of a figure document and a view-only PDF."""

    def test_a_page_verdict_takes_the_page_figure_and_leaves_the_composer(self):
        """On the figure, a selection with a note open: 채택 on page 1's line saves a verdict about the page's figure
        (el.path == [el.id]) with no note, and the selection and its note stay. The line says it, its page-size mark is not
        drawn and [보기] goes to the line; the same word again is a new pin, which the line now shows, with the earlier one
        as '앞선 판정 1건(처리하지 않음)' and its mark drawn as before. Page 2 has none."""
        page = self.on("fig")
        page.evaluate(
            "p=>{LAST_PTR='mouse'; pick({doc:'fig',page:1,pdf_build:META.pages_build,x0:p[0]*META.pages[0].pt_w,y0:p[1]*META.pages[0].pt_h,"
            "x1:(p[0]+p[2])*META.pages[0].pt_w,y1:(p[1]+p[3])*META.pages[0].pt_h,frac:p});}",
            list(helpers_figure.CELL_DRAG),
        )
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        page.fill("#note", "draft")
        sel = page.evaluate("JSON.stringify([COMPOSE.current.lo,COMPOSE.current.hi,COMPOSE.current.elSel.id])")
        first = self.press_page(page, 1, "채택")
        pin = self.pins()[first]
        self.assertEqual((pin["verdict"], pin["el"]["path"], pin["el"]["id"], pin["note"]), ("채택", ["B2"], "B2", ""))
        self.assertEqual(
            page.evaluate(
                "[document.querySelector('#note').value, !document.querySelector('#composer').hidden, "
                "JSON.stringify([COMPOSE.current.lo,COMPOSE.current.hi,COMPOSE.current.elSel.id])]"
            ),
            ["draft", True, sel],
        )
        line = page.evaluate(LINE, 1)
        self.assertEqual((line["pin"], line["words"]), (str(first), ["채택", "보류", "삭제"]))
        self.assertIn("처리 기다리는 판정", line["text"])
        self.assertIn("#%d 채택" % first, line["text"])
        self.assertEqual(page.locator('.mark[data-pin="%d"]' % first).count(), 0)
        self.assertIn("판정 없음", page.evaluate(LINE, 2)["text"])
        second = self.press_page(page, 1, "채택")
        line = page.evaluate(LINE, 1)
        self.assertEqual(line["pin"], str(second))
        self.assertIn("앞선 판정 1건(처리하지 않음)", line["text"])
        self.assertEqual(page.locator('.mark[data-pin="%d"]' % first).count(), 1)
        self.assertEqual(page.locator('.mark[data-pin="%d"]' % second).count(), 0)
        page.evaluate("id=>jumpPin(id)", second)
        self.assertTrue(
            page.evaluate("document.querySelector('#doc .pv[data-page=\"1\"]').classList.contains('flash')")
        )

    def test_the_line_says_each_state_and_the_newest_number_wins(self):
        """On the PDF: waiting, then 처리 중 once an agent claims it, 검토 대기 once it closes it; on page 2 a newer
        verdict by someone else that a person closed reads '처리됨' with its author, and the older open one stays an
        earlier verdict - closing the newest never brings the older back."""
        page = self.on("rv")
        a = self.press_page(page, 1, "채택")
        self.assertIn(
            "처리 기다리는 판정 · #%d 채택" % a, " ".join(page.evaluate(LINE, 1)["text"].replace("·", " · ").split())
        )
        self.assertEqual(self.call("POST", "/api/pins/%d/claim" % a, {}, AGENT)[0], 200)
        self.reload(page)
        self.assertIn("처리 중", page.evaluate(LINE, 1)["text"])
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % a, {"reply": "done"}, AGENT)[0], 200)
        self.reload(page)
        self.assertIn("검토 대기", page.evaluate(LINE, 1)["text"])
        older = self.press_page(page, 2, "보류")
        build = page.evaluate("META.pages_build")
        code, made = self.call(
            "POST",
            "/api/pin",
            {
                "doc": "rv",
                "page": 2,
                "frac": [0, 0, 1, 1],
                "pdf_build": build,
                "note": "",
                "kind_req": "fix",
                "assignee": "agent",
                "verdict": "채택",
            },
            BOB,
        )
        self.assertEqual(code, 200, made)
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % made["id"], {}, ALICE)[0], 200)
        self.reload(page)
        line = page.evaluate(LINE, 2)
        self.assertEqual(line["pin"], str(made["id"]))
        for words in ("처리됨", "#%d 채택" % made["id"], "Bob", "앞선 판정 1건(처리하지 않음)"):
            self.assertIn(words, line["text"])
        page.locator('#doc .pv[data-page="2"] .pv-early').click()
        page.wait_for_function("id=>document.querySelector('.pin[data-id=\"'+id+'\"].flash')", arg=older)

    def test_the_undo_withdraws_the_verdict_and_says_so_when_it_was_being_handled(self):
        """'#N 저장됨 [되돌리기]' on the line deletes the pin and opens no composer; one an agent claimed meanwhile still goes,
        and the status line says it may already have run."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        page.locator('#doc .pv[data-page="1"] .nt-chip [data-act="notice-act"]').click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=a)
        settle(page)
        self.assertNotIn(a, self.pins())
        self.assertTrue(page.evaluate("document.querySelector('#composer').hidden"))
        b = self.press_page(page, 1, "채택")
        self.assertEqual(self.call("POST", "/api/pins/%d/claim" % b, {}, AGENT)[0], 200)
        page.locator('#doc .pv[data-page="1"] .nt-chip [data-act="notice-act"]').click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=b)
        settle(page)
        self.assertIn("처리 중이던 판정입니다", page.evaluate("document.querySelector('#status').textContent"))

    def test_a_confirm_word_on_the_line_is_bound_to_its_page(self):
        """삭제 armed on page 1 is let go by a press on page 2's line, and two presses on one page save it."""
        page = self.on("fig")
        one, two = ('#doc .pv[data-page="%d"] button[data-key="삭제"]' % n for n in (1, 2))
        page.locator(one).click()
        settle(page)
        self.assertEqual(page.locator(one).inner_text(), "삭제 확정")
        page.locator(two).click()
        settle(page)
        self.assertEqual((page.locator(one).inner_text(), page.locator(two).inner_text()), ("삭제", "삭제 확정"))
        page.locator(two).click()
        page.wait_for_function("OPEN_ALL.length===1")
        self.assertEqual([(p["verdict"], p["el"]["id"]) for p in self.pins().values()], [("삭제", "B3")])

    def test_the_page_list_the_cards_and_the_done_row_carry_the_verdict(self):
        """The page list ends page 1's row with '#N 채택'; the card's badge reads '판정 채택', and so does the done row."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        page.evaluate("togglePageList(document.querySelector('#section-page'))")
        settle(page)
        self.assertEqual(page.locator('#page-pop-list .pl-row[data-page="1"] .pl-v').inner_text(), "#%d 채택" % a)
        self.assertEqual(page.locator('#page-pop-list .pl-row[data-page="2"] .pl-v').count(), 0)
        self.assertEqual(page.locator('.pin[data-id="%d"] .badge-verdict' % a).inner_text(), "판정 채택")
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % a, {}, ALICE)[0], 200)
        page.evaluate("SEC.done=true")
        self.reload(page)
        self.assertEqual(page.locator('.arc-row[data-id="%d"] .badge-verdict' % a).inner_text(), "판정 채택")
        self.assertIn("처리됨", page.evaluate(LINE, 1)["text"])

    def test_without_page_verdicts_the_marks_are_as_before(self):
        """page: false on the PDF: no line, and a whole-page verdict pin is drawn as its mark."""
        build = self.on("rv").evaluate("META.pages_build")
        code, made = self.call(
            "POST",
            "/api/pin",
            {
                "doc": "rv",
                "page": 1,
                "frac": [0, 0, 1, 1],
                "pdf_build": build,
                "note": "",
                "kind_req": "fix",
                "assignee": "agent",
                "verdict": "채택",
            },
        )
        self.assertEqual(code, 200, made)
        self.word_files["rv"].write_text(json.dumps({**WORDS, "page": False}, ensure_ascii=False), encoding="utf-8")
        page = self.on("rv", n_open=1)
        self.assertEqual(page.locator("#doc .pv").count(), 0)
        self.assertEqual(page.locator('.mark[data-pin="%d"]' % made["id"]).count(), 1)

    def test_the_figure_page_body_takes_only_the_page_figure(self):
        """pageVerdictBody: a rung whose element is its own path's root, else a region whose element is; a panel's region
        or a ladder without the root gives nothing, so nothing is saved; a PDF's region is kept as it is."""
        page = self.on("ms")
        out = page.evaluate("""()=>{const root={id:'B2',path:['B2'],frac:[0,0,1,1]},panel={id:'B2/p',path:['B2','B2/p'],frac:[0,0,.5,1]};
          const line={file:'f',name:'s.py',page:1,lo:3,hi:9,raw_lo:3,raw_hi:9,via:'map',score:1,frac:[0,0,1,1],quote:'',pdf_build:'b'};
          const rung=pageVerdictBody({...line,levels:[{level:'el:1',lo:4,hi:6,el:panel},{level:'fig',lo:1,hi:40,el:root}]},'figure');
          return [rung&&[rung.lo,rung.hi,rung.scope,rung.kind,rung.el.id], !!pageVerdictBody({kind:'region',page:1,frac:[0,0,1,1],el:root},'figure'),
            pageVerdictBody({kind:'region',page:1,frac:[0,0,1,1],el:panel},'figure'), pageVerdictBody({...line,levels:[{level:'el:1',lo:4,hi:6,el:panel}]},'figure'),
            pageVerdictBody({kind:'region',page:2,frac:[0,0,1,1],quote:'q',pdf_build:'b'},'pdf')];}""")
        self.assertEqual(
            out,
            [
                [1, 40, "fig", "figure", "B2"],
                True,
                None,
                None,
                {"page": 2, "frac": [0, 0, 1, 1], "quote": "q", "pdf_build": "b"},
            ],
        )


class ViewerRole(VerdictBase):
    """A viewer reads the line and makes no verdict."""

    WHO = CAROL_VIEWER

    def test_a_viewer_reads_the_line_without_buttons(self):
        """The line's words are there and no button is, on the line or in the composer."""
        member_add(ps.APP.C.state, CAROL_VIEWER["Tailscale-User-Login"], "viewer")
        page = self.on("fig")
        line = page.evaluate(LINE, 1)
        self.assertEqual(line["words"], [])
        self.assertIn("판정 없음", line["text"])
        self.assertEqual(page.locator("#c-verdict-row button").count(), 0)


class Touch(VerdictBase):
    """On touch screens the words answer 44px, and five words fit one line at 320px."""

    def test_five_words_fit_at_320_and_every_word_answers_44px(self):
        """320x720 with five words: one line, no word cut, nothing past the row; every button of the row and of a page line
        answers a 44px press (390x844)."""
        five = {**WORDS, "verdicts": WORDS["verdicts"] + [{"key": "수정"}, {"key": "이동"}]}
        self.word_files["ms"].write_text(json.dumps(five, ensure_ascii=False), encoding="utf-8")
        page = self.on("ms", viewport={"width": 320, "height": 720}, is_mobile=True, has_touch=True)
        page.evaluate("LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60})")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)
        page.locator("#c-verdict-row").scroll_into_view_if_needed()
        row = page.evaluate("""()=>{const r=document.querySelector('#c-verdict-row .vd-btns'), bs=[...r.querySelectorAll('button')], R=r.getBoundingClientRect();
          return {n:bs.length, lines:new Set(bs.map(b=>Math.round(b.getBoundingClientRect().top))).size,
            cut:bs.filter(b=>{const l=b.querySelector('.lbl'); return l.scrollWidth>l.clientWidth+0.5;}).length,
            past:bs.filter(b=>b.getBoundingClientRect().right>R.right+0.5).length};}""")
        self.assertEqual(row, {"n": 5, "lines": 1, "cut": 0, "past": 0})
        self.assertEqual(page.evaluate(MISSES_44, "#c-verdict-row button"), [])
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.locator('#doc .pv[data-page="1"]').scroll_into_view_if_needed()
        settle(page)
        self.assertEqual(page.evaluate(MISSES_44, '#doc .pv[data-page="1"] button'), [])

    def test_with_the_keyboard_up_the_row_under_the_note_stays_on_screen(self):
        """Phones and tablet sheets, the note focused and the keyboard up (the layout 300px shorter): the location line,
        the note and the verdict row under it are whole on screen (the tablet sheet's lift reaches the row; the sheet scrolls
        on as far as the note stays under the location line)."""
        shown = """sel => {const e = document.querySelector(sel), r = e.getBoundingClientRect(), x = r.left + r.width / 2; let n = 0;
          for (let y = Math.max(0, Math.ceil(r.top)); y < Math.min(innerHeight, r.bottom); y++) {const t = document.elementFromPoint(x, y); if (t && (t === e || e.contains(t))) n++;}
          return n === Math.ceil(r.bottom) - Math.ceil(r.top);}"""
        for w, h in ((320, 720), (390, 844), (768, 1024), (673, 841)):
            with self.subTest(w=w, h=h):
                page = self.on("ms", viewport={"width": w, "height": h}, is_mobile=True, has_touch=True)
                page.evaluate("LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60})")
                page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
                settle(page)
                page.focus("#note")
                page.set_viewport_size({"width": w, "height": h - 300})
                settle(page)
                self.assertEqual(
                    [page.evaluate(shown, s) for s in ("#c-loc", "#note", "#c-verdict-row")], [True, True, True]
                )
