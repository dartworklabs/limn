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
  const t = [...l.querySelector('.pv-t').childNodes].map(n => n.textContent).join(' ');
  return {text: t.replace(/·/g, ' · ').replace(/\\s+/g, ' ').trim(), pin: l.dataset.pin || null,
    words: [...l.querySelectorAll('button.vd-b')].map(b => b.textContent), tips: [...l.querySelectorAll('button.vd-b')].map(b => b.dataset.tip)};}"""


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
        self.fail_pin = 0  # how many POST /api/pin to lose on the network (route.abort)
        self.held: list | None = (
            None  # POST /api/pin routes held unanswered while not None (release with self.release())
        )
        patch = mock.patch.object(pick_source, "region_text", return_value="")
        patch.start()
        self.addCleanup(patch.stop)

    def route(self, route):
        """A pick on the figure or the PDF goes to the handler; the manuscript's gets the computed answer. A new pin's POST
        may be lost (fail_pin) or held (held)."""
        rq = route.request
        if urlparse(rq.url).path == "/api/pin" and rq.method == "POST":
            if self.fail_pin:
                self.fail_pin -= 1
                return route.abort()
            if self.held is not None:
                self.held.append(route)
                return None
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

    def release(self):
        """Answer every held POST /api/pin and stop holding."""
        held, self.held = self.held or [], None
        for r in held:
            self.forward(r)

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
        """With words the row stands after the note and before the kind row: '판정 바로 저장' and a button per word in file
        order, the confirm word in the danger colour, each saying that a press saves the selection and note at once; without a
        word file there is no row and no page line."""
        page = self.on("ms")
        self.open_composer(page)
        row = page.evaluate("""()=>{const r=document.querySelector('#c-verdict-row'), kids=[...document.querySelector('#composer').children].map(e=>e.id);
          return {shown: !r.hidden && r.getClientRects().length>0, words: [...r.querySelectorAll('button')].map(b=>b.textContent),
            lead: r.querySelector('.vd-l').textContent, tip: r.querySelector('button').dataset.tip,
            confirm: [...r.querySelectorAll('button.vd-confirm')].map(b=>b.dataset.key), order: kids.indexOf('c-verdict-row') - kids.indexOf('c-kind-row'),
            afterNote: !!(document.querySelector('#note').compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING)};}""")
        want = {"shown": True, "words": ["채택", "보류", "삭제"], "confirm": ["삭제"], "order": -1, "afterNote": True}
        want.update(lead="판정 바로 저장", tip="누르면 지금 선택과 메모를 채택 판정 핀으로 바로 저장합니다")
        self.assertEqual(row, want)
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
        self.assertEqual(s["why"], "질문에는 판정을 붙이지 않습니다 — 아래에서 [수정 요청]을 고릅니다")
        page.locator('#c-kind button[data-kind="fix"]').click()
        settle(page)
        self.assertEqual(page.evaluate(state), {"off": False, "why": ""})
        page.locator("#c-sg-tg").click()
        settle(page)
        s = page.evaluate(state)
        self.assertTrue(s["off"], s)
        self.assertEqual(s["why"], "판정을 저장하려면 [제안 수정]을 끕니다")

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
        as '이전 판정 1건 · 새 판정이 앞섬' and its mark drawn as before. Page 2 has none. The line reads '판정 #N 채택 · 처리 대기'
        and its buttons say a press saves a new verdict pin for the page."""
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
        self.assertEqual(line["text"], "판정 #%d 채택 · 처리 대기" % first)
        self.assertEqual(set(line["tips"]), {"누르면 이 쪽에 새 판정 핀을 저장합니다"})
        self.assertEqual(page.locator('.mark[data-pin="%d"]' % first).count(), 0)
        self.assertIn("판정 없음", page.evaluate(LINE, 2)["text"])
        second = self.press_page(page, 1, "채택")
        line = page.evaluate(LINE, 1)
        self.assertEqual(line["pin"], str(second))
        self.assertEqual(line["text"], "판정 #%d 채택 · 처리 대기 이전 판정 1건 · 새 판정이 앞섬" % second)
        self.assertEqual(page.locator('.mark[data-pin="%d"]' % first).count(), 1)
        self.assertEqual(page.locator('.mark[data-pin="%d"]' % second).count(), 0)
        page.evaluate("id=>jumpPin(id)", second)
        self.assertTrue(
            page.evaluate("document.querySelector('#doc .pv[data-page=\"1\"]').classList.contains('flash')")
        )

    def test_the_line_says_each_state_and_the_newest_number_wins(self):
        """On the PDF, in one order '판정 #N 채택 · <state>': 처리 대기, then 처리 중 once an agent claims it, 검토 대기 once it
        closes it; the number is a link to the card. On page 2 a newer
        verdict by someone else that a person closed reads '처리됨' with its author, and the older open one stays an
        earlier verdict - closing the newest never brings the older back."""
        page = self.on("rv")
        a = self.press_page(page, 1, "채택")
        self.assertEqual(page.evaluate(LINE, 1)["text"], "판정 #%d 채택 · 처리 대기" % a)
        self.assertEqual(self.call("POST", "/api/pins/%d/claim" % a, {}, AGENT)[0], 200)
        self.reload(page)
        self.assertEqual(page.evaluate(LINE, 1)["text"], "판정 #%d 채택 · 처리 중" % a)
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % a, {"reply": "done"}, AGENT)[0], 200)
        self.reload(page)
        self.assertEqual(page.evaluate(LINE, 1)["text"], "판정 #%d 채택 · 검토 대기" % a)
        page.locator('#doc .pv[data-page="1"] .pv-ref').click()
        page.wait_for_function("id=>document.querySelector('.pin[data-id=\"'+id+'\"].flash')", arg=a)
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
        self.assertRegex(line["text"], r"^판정 #%d 채택 · 처리됨 · Bob .+ 이전 판정 1건 · 새 판정이 앞섬$" % made["id"])
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
        """Every touch size, the note focused and the keyboard up (the layout 300px shorter): the location line, the note
        and the verdict row under it are whole on screen (the tablet sheet's lift reaches the row; the panel scrolls on as far
        as the note stays under the location line, which sticks at the top of the sheet or, on the mid bands, of the panel -
        at 841x673 it went 20px under the nav bar)."""
        shown = """sel => {const e = document.querySelector(sel), r = e.getBoundingClientRect(), x = r.left + r.width / 2; let n = 0;
          for (let y = Math.max(0, Math.ceil(r.top)); y < Math.min(innerHeight, r.bottom); y++) {const t = document.elementFromPoint(x, y); if (t && (t === e || e.contains(t))) n++;}
          return n === Math.ceil(r.bottom) - Math.ceil(r.top);}"""
        for w, h in ((320, 720), (390, 844), (344, 882), (768, 1024), (673, 841), (841, 673), (1024, 768)):
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


class ReviewFixes(VerdictBase):
    """The 0.4.26 review's behaviour fixes (each a regression test)."""

    def test_a_retry_after_a_failed_verdict_save_keeps_the_verdict(self):
        """A verdict save lost on the network leaves [다시 저장]; pressed with the same selection it saves that verdict - it
        used to save a plain pin and lose the author's verdict."""
        page = self.on("ms")
        self.open_composer(page)
        page.fill("#note", "keep it")
        self.fail_pin = 1
        page.locator('#c-verdict-row button[data-key="채택"]').click()
        page.wait_for_function("document.querySelector('#btn-save').textContent.includes('다시 저장')")
        settle(page)
        self.assertEqual(self.pins(), {})
        page.locator("#btn-save").click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        (pin,) = self.pins().values()
        self.assertEqual((pin["verdict"], pin["note"]), ("채택", "keep it"))

    def test_a_retry_on_another_range_is_a_plain_save(self):
        """The retry's verdict is bound to the selection it was pressed on: after the range changed, [다시 저장] saves a
        plain pin of the new range."""
        page = self.on("ms")
        self.open_composer(page)
        self.fail_pin = 1
        page.locator('#c-verdict-row button[data-key="보류"]').click()
        page.wait_for_function("document.querySelector('#btn-save').textContent.includes('다시 저장')")
        settle(page)
        page.locator("#c-levels button:not(.on)").first.click()
        settle(page)
        page.locator("#btn-save").click()
        page.wait_for_function("OPEN_ALL.length===1")
        (pin,) = self.pins().values()
        self.assertNotIn("verdict", pin)

    def test_a_verdict_waiting_for_its_confirmation_is_still_the_newest(self):
        """The newest verdict awaiting review, confirmed with [확인]: during the undo window (and a list reload in it) the
        line still shows it, not the older open one."""
        page = self.on("rv")
        older = self.press_page(page, 1, "보류")
        newer = self.press_page(page, 1, "채택")
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % newer, {"reply": "done"}, AGENT)[0], 200)
        self.reload(page)
        page.evaluate("()=>{SEC.review=true; setSide(true); drawPins();}")
        page.locator('#review-pins .pin[data-id="%d"] [data-act="confirm"]' % newer).click()
        settle(page)
        self.assertTrue(page.evaluate("id=>!REVIEW_ALL.some(p=>p.id===id)&&CONFIRMING.has(id)", newer))
        for _ in range(2):
            line = page.evaluate(LINE, 1)
            self.assertEqual(line["pin"], str(newer), line)
            self.assertNotEqual(line["pin"], str(older))
            self.reload(page)

    def test_the_verdict_buttons_come_back_when_a_save_ends_on_a_new_selection(self):
        """A verdict save in flight turns the row off; a selection picked meanwhile is drawn off too, and when the request
        ends its buttons are on again (only [핀 저장] used to come back)."""
        page = self.on("ms")
        self.open_composer(page)
        self.held = []
        page.locator('#c-verdict-row button[data-key="채택"]').click()
        page.wait_for_function("COMPOSE.saving")
        page.evaluate("pick({page:1,x0:10,y0:100,x1:200,y1:150})")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking&&COMPOSE.saving")
        off = "()=>[...document.querySelectorAll('#c-verdict-row button')].map(b=>b.disabled)"
        self.assertEqual(page.evaluate(off), [True, True, True])
        self.release()
        page.wait_for_function("!COMPOSE.saving")
        settle(page)
        self.assertEqual(page.evaluate(off), [False, False, False])

    def test_a_keyboard_save_on_the_line_gives_the_focus_back(self):
        """Enter on a page line's word saves it; the button was redrawn while the request ran, and the focus comes back to
        it - unless the person moved it meanwhile."""
        page = self.on("fig")
        btn = '#doc .pv[data-page="1"] button[data-key="채택"]'
        page.focus(btn)
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        self.assertTrue(page.evaluate("s=>document.activeElement===document.querySelector(s)", btn))
        self.held = []
        page.keyboard.press("Enter")
        page.wait_for_function("PV_BUSY.size===1")
        page.focus(".pin .b-view")
        self.release()
        page.wait_for_function("PV_BUSY.size===0&&OPEN_ALL.length===2")
        settle(page)
        self.assertFalse(page.evaluate("!!document.activeElement.closest('#doc .pv')"))  # not taken back to the line

    def test_a_card_of_another_document_names_its_own_word(self):
        """Under [모든 문서] a verdict card of the PDF shows the PDF's label for its word, not the document on screen's."""
        self.word_files["rv"].write_text(
            json.dumps({**WORDS, "page": True, "verdicts": [{"key": "채택", "label": "받음"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
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
        page = self.on("ms", n_open=1)
        page.evaluate("()=>{SHOW_ALL=true; drawPins();}")
        settle(page)
        self.assertEqual(page.locator('.pin[data-id="%d"] .badge-verdict' % made["id"]).inner_text(), "판정 받음")

    def test_the_earlier_verdicts_link_is_underlined_only_on_hover(self):
        """'이전 판정 N건 · 새 판정이 앞섬' has the viewer's link look - no underline at rest, a solid one on hover - in the
        light and the dark theme."""
        dark = "try{localStorage.setItem('pinPrefs',JSON.stringify({theme:'dark'}));}catch(e){}"
        for init in (None, dark):
            with self.subTest(theme="dark" if init else "light"):
                page = self.open(0, init=init)
                page.evaluate("k=>switchDoc(k)", "fig")
                page.wait_for_function("DOC==='fig'&&document.querySelector('#doc .pv')")
                settle(page)
                self.press_page(page, 1, "보류")
                self.press_page(page, 1, "채택")
                deco = "()=>getComputedStyle(document.querySelector('#doc .pv .pv-early')).textDecorationLine"
                self.assertEqual(page.evaluate(deco), "none")
                page.hover("#doc .pv .pv-early")
                self.assertEqual(page.evaluate(deco), "underline")
                for p in self.pins():
                    self.call("POST", "/api/pins/%d/drop" % p)

    def test_on_a_phone_every_line_puts_its_buttons_on_a_row_of_their_own(self):
        """390x844: a line too long for one row (an earlier verdict) puts its buttons on the next row, at its start, and so
        does every other page's short line - one rhythm; the desktop keeps them at the end of the row."""
        rows = """()=>[...document.querySelectorAll('#doc .pv')].map(l=>{const t=l.querySelector('.pv-t').getBoundingClientRect(),
          b=l.querySelector('.vd-btns').getBoundingClientRect(),L=l.getBoundingClientRect();
          return {below: b.top>=t.bottom-1, start: Math.abs(b.left-L.left)<=1};})"""
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        self.press_page(page, 1, "보류")
        self.press_page(page, 1, "채택")
        self.assertEqual(page.evaluate(rows), [{"below": True, "start": True}] * 2)
        self.assertTrue(page.evaluate("document.querySelector('#doc').classList.contains('pv-stack')"))
        page = self.on("fig", n_open=2)
        self.assertEqual([r["below"] for r in page.evaluate(rows)], [False, False])
