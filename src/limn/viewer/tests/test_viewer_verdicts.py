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
from helpers_browser import MISSES_44, BrowserBase, booted, settle, watch_idle

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
        self.held_pick: list | None = None  # POST /api/pick routes held unanswered while not None
        self.held_list: list | None = None  # GET /api/pins (the pin list) held unanswered while not None
        patch = mock.patch.object(pick_source, "region_text", return_value="")
        patch.start()
        self.addCleanup(patch.stop)

    def route(self, route):
        """A pick on the figure or the PDF goes to the handler; the manuscript's gets the computed answer. A new pin's POST
        may be lost (fail_pin) or held (held)."""
        rq = route.request
        if urlparse(rq.url).path == "/api/pins" and rq.method == "GET" and self.held_list is not None:
            self.held_list.append(route)
            return None
        if urlparse(rq.url).path == "/api/pick" and self.held_pick is not None:
            self.held_pick.append(route)
            return None
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
        """Press word key on page n's line once and wait until the new pin is on the list; its id. A press that saves
        nothing fails at once with what happened: the pointer and click events the document saw and their targets, where
        the click went, the element under that point now, whether the button and the line are still the elements that
        were pressed, the page's save state and its status line. It is never pressed again: a press lost to the viewer
        re-laying out or replacing what was under the pointer is the bug this would hide."""
        from playwright.sync_api import (
            TimeoutError as PlaywrightTimeout,
        )  # as helpers_browser: only where a browser runs

        before = set(self.pins())
        want = len([p for p in self.pins().values() if p.get("state") == "open"]) + 1
        line, btn = '#doc .pv[data-page="%d"]' % n, '#doc .pv[data-page="%d"] button[data-key="%s"]' % (n, key)
        page.evaluate(PRESS_WATCH, [line, btn])
        box = page.locator(btn).bounding_box()
        page.locator(btn).click()
        try:
            page.wait_for_function("n=>OPEN_ALL.length>=n", arg=want, timeout=10000)
        except PlaywrightTimeout:
            at = [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2] if box else None
            self.fail("the press on %s saved nothing: %s" % (btn, page.evaluate(PRESS_SEEN, [line, btn, at])))
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
        self.assertEqual(page.locator('.pin[data-id="%d"] .tags .badge-verdict' % pin["id"]).inner_text(), "판정 채택")

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
        self.assertEqual(page.evaluate("document.querySelector('#sr-news').textContent"), "삭제 확정을 풀었습니다")
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
        as '이전 판정 1건 · 새 판정으로 대체됨' and no page-size mark either - the line accounts for both. Page 2 has none. The line reads '판정 #N 채택 · 처리 대기'
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
        self.assertEqual(line["text"], "판정 #%d 채택 · 처리 대기 이전 판정 1건 · 새 판정으로 대체됨" % second)
        self.assertEqual(page.locator('.mark[data-pin="%d"]' % first).count(), 0)
        self.assertEqual(page.locator('.mark[data-pin="%d"]' % second).count(), 0)
        page.evaluate("id=>jumpPin(id)", second)
        self.assertTrue(
            page.evaluate("document.querySelector('#doc .pv[data-page=\"1\"]').classList.contains('flash')")
        )

    def test_the_line_says_each_state_and_the_newest_number_wins(self):
        """On the PDF, in one order '판정 #N 채택 · <state>': 처리 대기, then '처리 중(Agent B)' once that agent claims it (the
        claimer named, not the author), 검토 대기 once it
        closes it; the number is a link to the card. On page 2 a newer
        verdict by someone else that a person closed reads '처리됨' with its author, and the older open one stays an
        earlier verdict - closing the newest never brings the older back."""
        page = self.on("rv")
        a = self.press_page(page, 1, "채택")
        self.assertEqual(page.evaluate(LINE, 1)["text"], "판정 #%d 채택 · 처리 대기" % a)
        self.assertEqual(self.call("POST", "/api/pins/%d/claim" % a, {}, AGENT)[0], 200)
        self.reload(page)
        self.assertEqual(page.evaluate(LINE, 1)["text"], "판정 #%d 채택 · 처리 중(Agent B)" % a)
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
        self.assertRegex(
            line["text"], r"^판정 #%d 채택 · 처리됨 · Bob .+ 이전 판정 1건 · 새 판정으로 대체됨$" % made["id"]
        )
        page.locator('#doc .pv[data-page="2"] .pv-early').click()
        page.wait_for_function("id=>document.querySelector('.pin[data-id=\"'+id+'\"].flash')", arg=older)

    def test_the_undo_withdraws_the_verdict_and_says_so_when_it_was_being_handled(self):
        """'#N 저장됨 [되돌리기]' on the line deletes the pin and opens no composer; one an agent claimed meanwhile still goes,
        and the status line says it may already have run - the whole sentence on the folded line."""
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
        self.assertIn(
            "처리 중이던 판정이라 이미 실행됐을 수 있습니다",
            page.evaluate("document.querySelector('#status .st-msg,#status').innerText"),
        )

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
        self.assertEqual(page.locator('.pin[data-id="%d"] .tags .badge-verdict' % a).inner_text(), "판정 채택")
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
        self.assertEqual(page.locator('.pin[data-id="%d"] .tags .badge-verdict' % made["id"]).inner_text(), "판정 받음")

    def test_the_earlier_verdicts_link_is_underlined_only_on_hover(self):
        """'이전 판정 N건 · 새 판정으로 대체됨' has the viewer's link look - no underline at rest, a solid one on hover - in the
        light and the dark theme."""
        page = self.on("fig")
        self.press_page(page, 1, "보류")
        self.press_page(page, 1, "채택")
        link = "#doc .pv .pv-early"
        deco = "s=>getComputedStyle(document.querySelector(s)).textDecorationLine"
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page.evaluate("t=>setTheme(t)", theme)
                page.mouse.move(1, 1)
                settle(page)
                self.assertEqual(page.evaluate("document.documentElement.dataset.theme"), theme)
                self.assertEqual(page.evaluate(deco, link), "none")
                page.hover(link)
                self.assertEqual(page.evaluate(deco, link), "underline")

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

    def test_two_verdicts_about_one_page_target_show_no_overlap_badge(self):
        """Two page verdicts on the figure's page 1 resolve to the same target: their cards carry no '#N와 같은 범위' (the
        page line orders them). An ordinary pin inside the figure keeps its overlap badge with a verdict pin."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        b = self.press_page(page, 1, "채택")
        self.assertTrue(
            any(r["id"] == a for r in self.pins()[b].get("rel", []))
        )  # the server still reports the overlap
        badges = "id=>[...document.querySelectorAll('.pin[data-id=\"'+id+'\"] .tags .badge')].map(e=>e.textContent)"
        for pid in (a, b):
            self.assertFalse([t for t in page.evaluate(badges, pid) if "범위" in t or "겹침" in t], pid)
        page.evaluate(
            "p=>{LAST_PTR='mouse'; pick({doc:'fig',page:1,pdf_build:META.pages_build,x0:p[0]*META.pages[0].pt_w,y0:p[1]*META.pages[0].pt_h,"
            "x1:(p[0]+p[2])*META.pages[0].pt_w,y1:(p[1]+p[3])*META.pages[0].pt_h,frac:p});}",
            list(helpers_figure.CELL_DRAG),
        )
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        page.locator("#btn-save").click()
        page.wait_for_function("OPEN_ALL.length===3")
        settle(page)
        (plain,) = set(self.pins()) - {a, b}
        self.assertTrue([t for t in page.evaluate(badges, plain) if "범위 안" in t], page.evaluate(badges, plain))

    def test_an_empty_memo_verdict_spends_no_line_on_it(self):
        """A verdict pin without a note has no note line ('(판정만)' is pins.md's, not the card's) - open, awaiting review and
        done; its '판정 채택' badge says it."""
        page = self.on("rv")
        a = self.press_page(page, 1, "채택")
        card = '.pin[data-id="%d"]' % a
        self.assertEqual(page.locator(card + " .note").count(), 0)
        self.assertNotIn("(판정만)", page.locator(card).inner_text())
        self.assertEqual(page.locator(card + " .tags .badge-verdict").inner_text(), "판정 채택")
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % a, {"reply": "done"}, AGENT)[0], 200)
        page.evaluate("SEC.review=true")
        self.reload(page)
        self.assertEqual(page.locator("#review-pins " + card + " .note").count(), 0)
        self.assertNotIn("(판정만)", page.locator("#review-pins " + card).inner_text())
        self.assertEqual(self.call("POST", "/api/pins/%d/confirm" % a, {}, ALICE)[0], 200)
        page.evaluate("SEC.done=true")
        self.reload(page)
        self.assertNotIn("(판정만)", page.locator('.arc-row[data-id="%d"]' % a).inner_text())


class ConfirmationRoundFixes(VerdictBase):
    """The confirmation round's fixes on #267 (each a regression test)."""

    def fail_a_verdict_save(self, page, key="채택"):
        """Open the composer, lose word key's save on the network and wait for [다시 저장]."""
        self.open_composer(page)
        self.fail_pin = 1
        page.locator('#c-verdict-row button[data-key="%s"]' % key).click()
        page.wait_for_function("document.querySelector('#btn-save').textContent.includes('다시 저장')")
        settle(page)
        self.assertEqual(self.pins(), {})

    def retry(self, page):
        """Press [다시 저장] and return the one pin it saved."""
        page.locator("#btn-save").click()
        page.wait_for_function("OPEN_ALL.length===1||REVIEW_ALL.length===1")
        settle(page)
        (pin,) = self.pins().values()
        return pin

    def test_a_retry_after_the_kind_became_a_question_saves_the_question(self):
        """A verdict save fails, the author makes the selection a question and presses [다시 저장]: a question without a
        verdict (it was saved as verdict 채택, kind_req fix)."""
        page = self.on("ms")
        self.fail_a_verdict_save(page)
        page.locator('#c-kind button[data-kind="question"]').click()
        settle(page)
        pin = self.retry(page)
        self.assertEqual((pin.get("verdict"), pin["kind_req"]), (None, "question"))

    def test_a_retry_after_the_kind_went_to_question_and_back_is_a_plain_pin(self):
        """Changing the kind drops the pending verdict even when it comes back to 수정 요청: [다시 저장] saves a plain fix pin."""
        page = self.on("ms")
        self.fail_a_verdict_save(page)
        for kind in ("question", "fix"):
            page.locator('#c-kind button[data-kind="%s"]' % kind).click()
            settle(page)
        pin = self.retry(page)
        self.assertEqual((pin.get("verdict"), pin["kind_req"]), (None, "fix"))

    def test_a_retry_after_turning_on_the_suggested_edit_has_no_verdict(self):
        """A verdict save fails, the author turns [제안 수정] on and presses [다시 저장]: no verdict is saved."""
        page = self.on("ms")
        self.fail_a_verdict_save(page)
        page.locator("#c-sg-tg").click()
        settle(page)
        pin = self.retry(page)
        self.assertIsNone(pin.get("verdict"))

    def test_a_retry_after_the_range_went_away_and_back_is_a_plain_pin(self):
        """A verdict save fails; the author picks another rung and then the first one again, so the lines are the ones the
        failed save had: [다시 저장] saves a plain pin. Any change of range is a new intent, also one back to where it was."""
        page = self.on("ms")
        self.fail_a_verdict_save(page)
        first = page.evaluate("COMPOSE.current.scope")
        page.locator("#c-levels button:not(.on)").first.click()
        settle(page)
        page.locator('#c-levels [data-level="%s"]' % first).click()
        settle(page)
        self.assertEqual(page.evaluate("COMPOSE.current.scope"), first)
        pin = self.retry(page)
        self.assertEqual((pin.get("verdict"), pin["kind_req"]), (None, "fix"))

    def test_a_retry_after_the_selection_was_discarded_and_brought_back_is_a_plain_pin(self):
        """A verdict save fails; the author writes a note, discards the selection with [취소] and brings it back with the
        status line's [되돌리기] (the same selection object): [다시 저장] saves a plain pin with the note."""
        page = self.on("ms")
        self.fail_a_verdict_save(page)
        page.fill("#note", "남길 메모")
        page.locator("#btn-cancel").click()
        settle(page)
        page.locator("#status", has_text="선택 취소됨").locator("[data-act=notice-act]").click()
        page.wait_for_function("!!COMPOSE.current&&!document.querySelector('#composer').hidden")
        settle(page)
        pin = self.retry(page)
        self.assertEqual((pin.get("verdict"), pin["note"]), (None, "남길 메모"))

    def test_a_kind_change_while_the_failed_save_was_out_leaves_no_retry(self):
        """A verdict save is still out when the author makes the selection a question and then a fix request again; the
        save then fails: no retry is left for the verdict, the banner says the save failed as a pin's and the picked
        verdict was cleared, and [다시 저장] saves a plain pin."""
        page = self.on("ms")
        self.open_composer(page)
        self.held = []
        page.locator('#c-verdict-row button[data-key="채택"]').click()
        page.wait_for_function("COMPOSE.saving")
        for kind in ("question", "fix"):
            page.evaluate("k=>setKind(k)", kind)  # what the kind row's press does (the row is busy while a save is out)
        held, self.held = self.held, None
        for r in held:
            r.abort()
        page.wait_for_function("!COMPOSE.saving&&document.querySelector('#btn-save').textContent.includes('다시 저장')")
        settle(page)
        self.assertEqual((self.pins(), page.evaluate("COMPOSE.retryVerdict")), ({}, None))
        banner = page.evaluate("document.querySelector('#c-actions .nt-banner').innerText")
        self.assertNotIn("판정 저장 실패", banner)  # the failure says the verdict is no longer asked for
        self.assertIn("핀 저장 실패", banner)
        self.assertIn("선택했던 판정은 해제됐습니다", banner)
        pin = self.retry(page)
        self.assertEqual((pin.get("verdict"), pin["kind_req"]), (None, "fix"))

    def test_moving_the_focus_during_a_line_save_keeps_it_where_it_went(self):
        """Enter on page 1's word, then - while its save runs - the focus goes to page 2's button, or to the '#N' link: when
        the save ends the focus stays there and does not jump back to page 1's button."""
        page = self.on("fig")
        one = '#doc .pv[data-page="1"] button[data-key="채택"]'
        page.focus(one)
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        for n, target in (
            (2, '#doc .pv[data-page="2"] button[data-key="보류"]'),
            (3, '#doc .pv[data-page="1"] .pv-ref'),
        ):
            with self.subTest(target=target):
                page.focus(one)
                self.held = []
                page.keyboard.press("Enter")
                page.wait_for_function("PV_BUSY.size===1")
                page.focus(target)
                self.release()
                page.wait_for_function("n=>PV_BUSY.size===0&&OPEN_ALL.length===n", arg=n)
                settle(page)
                self.assertFalse(page.evaluate("s=>document.activeElement===document.querySelector(s)", one))
                if n == 2:
                    self.assertTrue(page.evaluate("s=>document.activeElement===document.querySelector(s)", target))

    def test_overlap_badges_stay_where_no_page_line_orders_the_verdicts(self):
        """Two page verdicts on the figure's page 1 keep their overlap where no page line shows them: with page false the
        cards show '같은 범위' again, and under [모든 문서] while another document is on screen their cards keep their whole
        rel (the card of another document never had the same-range badge, which reads the document on screen's pins - only
        the overlaps are checked there)."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        b = self.press_page(page, 1, "채택")
        texts = "()=>[...document.querySelectorAll('.pin .tags .badge')].map(e=>e.textContent).filter(t=>t.includes('같은 범위'))"
        self.assertEqual(page.evaluate(texts), [])  # the line orders them
        kept = "ids=>ids.map(id=>{const p=OPEN_ALL.find(x=>x.id===id); return !!p.rel&&p.rel.length>0&&pvQuietRel(p).rel.length===p.rel.length;})"
        self.assertEqual(page.evaluate(kept, [a, b]), [False, False])
        page = self.on("ms", n_open=2)
        page.evaluate("()=>{SHOW_ALL=true; drawPins();}")
        settle(page)
        self.assertEqual(page.evaluate(kept, [a, b]), [True, True])
        self.word_files["fig"].write_text(json.dumps({**WORDS, "page": False}, ensure_ascii=False), encoding="utf-8")
        page = self.on("fig", n_open=2)
        self.assertEqual(page.locator("#doc .pv").count(), 0)
        self.assertTrue(page.evaluate(texts))


# Before a press (VerdictBase.press_page): keep the line and button pressed, and record every pointer, mouse and click event
# from now on at the window's capture phase - before any of the viewer's handlers, the document's capture-phase
# SWALLOW_CLICK (tooltip.js) among them - with its type, target, point and whether the browser made it; and whether a click
# then reached the pressed button itself.
PRESS_WATCH = """([line, btn]) => {const d = (e) => e ? e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().replace(/\\s+/g, '.') : '') + (e.dataset && e.dataset.key ? '[' + e.dataset.key + ']' : '') : null;
  const b = document.querySelector(btn);
  window.__press = {line: document.querySelector(line), btn: b, events: [], windowClicks: 0, buttonClicks: 0, d};
  if (b) b.addEventListener('click', () => {if (window.__press && window.__press.btn === b) window.__press.buttonClicks++;});
  if (!window.__pressWatch) {window.__pressWatch = true;
    for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'])
      window.addEventListener(t, (e) => {const w = window.__press; if (!w) return; w.events.push([t, w.d(e.target), Math.round(e.clientX), Math.round(e.clientY), e.isTrusted]);
        if (t === 'click' && w.btn && w.btn.contains(e.target)) w.windowClicks++;}, true);}}"""
# After a press that saved nothing: what happened to the click (PRESS_WATCH), where it went and what is there now.
PRESS_SEEN = """([line, btn, at]) => {const w = window.__press || {events: [], d: () => null}, b = document.querySelector(btn), r = b ? b.getBoundingClientRect() : null;
  const what = !w.windowClicks ? 'the click never reached the button (no click on it, even at the window)'
    : !w.buttonClicks ? 'the click reached the window on the button but was stopped before it (a capture-phase handler such as SWALLOW_CLICK)'
    : 'the click reached the button and the press saved nothing';
  return {what, events: w.events, clickAt: at, underThere: at ? w.d(document.elementFromPoint(at[0], at[1])) : null,
    buttonNow: r ? [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)] : null,
    sameButton: !!b && b === w.btn, sameLine: document.querySelector(line) === w.line, pressedConnected: !!w.btn && w.btn.isConnected,
    swallowArmed: typeof SWALLOW_CLICK !== 'undefined' && Date.now() < SWALLOW_CLICK,
    busy: PV_BUSY.size, open: OPEN_ALL.length, doc: DOC, status: (document.querySelector('#status') || {}).innerText || ''};}"""


# A card's '이전 판정' marker on screen (a card has one in its tags and one in its folded preview; one shows): its text,
# the id its link goes to and its name, or None.
OLD = """id=>{const m=[...document.querySelectorAll('.pin[data-id="'+id+'"] .vd-old,.arc-row[data-id="'+id+'"] .vd-old')].find(e=>e.getClientRects().length);
  if(!m) return null;
  return {text: m.textContent, ref: Number(m.querySelector('.vd-old-ref').dataset.ref), label: m.getAttribute('aria-label')};}"""


def ro(n):
    """'로' or '으로' after number n read in Korean (verdict.js josaRo)."""
    return "으로" if str(n)[-1] in "036" else "로"


def replaced(n):
    """The marker's words for a verdict replaced by #n."""
    return "이전 판정 · #%d%s 대체됨" % (n, ro(n))


class SupersededMarker(VerdictBase):
    """A verdict pin that is not the current verdict of its target says so on its card: '이전 판정 · #N로 대체됨', #N a link to
    the current verdict's card. The order is the page line's (verdictOrder)."""

    def drop_with_the_card(self, page, pid):
        """Delete pin pid with its card's [삭제] and wait until it is gone."""
        page.locator('.pin[data-id="%d"] [data-act="drop"]' % pid).click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=pid)
        settle(page)

    def test_the_marker_follows_new_deleted_and_undone_verdicts(self):
        """On the figure's page 1: one verdict has no marker; a newer one marks the older '이전 판정 · #N로 대체됨'; undoing the
        newer save takes the marker away; another newer one brings it back, pointing at it; deleting that one takes it away.
        The line and the marker name the same current verdict."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        self.assertIsNone(page.evaluate(OLD, a))
        b = self.press_page(page, 1, "채택")
        old = page.evaluate(OLD, a)
        self.assertEqual((old["text"], old["ref"]), (replaced(b), b))
        self.assertIn("#%d" % b, old["label"])
        self.assertIsNone(page.evaluate(OLD, b))
        self.assertEqual(page.evaluate(LINE, 1)["pin"], str(b))  # the line's current verdict is the marker's
        page.locator('#doc .pv[data-page="1"] .nt-chip [data-act="notice-act"]').click()  # undo b's save
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=b)
        settle(page)
        self.assertIsNone(page.evaluate(OLD, a))
        c = self.press_page(page, 1, "채택")
        self.assertEqual(page.evaluate(OLD, a)["ref"], c)
        self.drop_with_the_card(page, c)
        self.assertIsNone(page.evaluate(OLD, a))

    def test_the_number_goes_to_the_current_verdicts_card(self):
        """The marker's '#N' opens and flashes the current verdict's card."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        b = self.press_page(page, 1, "채택")
        page.locator('.pin[data-id="%d"] .vd-old-ref:visible' % a).click()
        page.wait_for_function(
            "id=>[...document.querySelectorAll('.pin.flash')].some(e=>e.dataset.id===String(id))", arg=b
        )

    def test_without_a_page_line_the_marker_still_shows(self):
        """page false on the figure: no line, and the older verdict's card still says it is superseded."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        b = self.press_page(page, 1, "채택")
        self.word_files["fig"].write_text(json.dumps({**WORDS, "page": False}, ensure_ascii=False), encoding="utf-8")
        page = self.on("fig", n_open=2)
        self.assertEqual(page.locator("#doc .pv").count(), 0)
        self.assertEqual(page.evaluate(OLD, a)["ref"], b)

    def test_another_documents_cards_carry_it_under_all_documents(self):
        """Under [모든 문서], with the LaTeX manuscript on screen, the figure's older verdict card is marked."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        b = self.press_page(page, 1, "채택")
        page = self.on("ms", n_open=2)
        page.evaluate("()=>{SHOW_ALL=true; drawPins();}")
        settle(page)
        self.assertEqual(page.evaluate(OLD, a)["ref"], b)

    def test_a_folded_card_on_a_phone_shows_it(self):
        """On a phone the cards are folded and only their preview line shows: the older verdict's preview is its badge and
        the marker, one marker on screen, its '#N' a link to the current card that answers 44px (the preview does not clip
        it)."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        b = self.press_page(page, 1, "채택")
        page = self.on("fig", n_open=2, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.evaluate("()=>{setSide(true); drawPins();}")
        settle(page)
        got = page.evaluate(
            """id=>{const c=document.querySelector('.pin[data-id="'+id+'"]'), s=c.querySelector('.sum');
              const m=[...c.querySelectorAll('.vd-old')].filter(e=>e.getClientRects().length);
              return {folded: !c.classList.contains('open'), shown: m.length, inSum: m.length===1&&s.contains(m[0]),
                badge: !!s.querySelector('.badge-verdict'), ref: m.length?Number(m[0].querySelector('.vd-old-ref').dataset.ref):null,
                noteCue: !!s.querySelector('.sum-has')};}""",
            a,
        )
        self.assertEqual(got, {"folded": True, "shown": 1, "inSum": True, "badge": True, "ref": b, "noteCue": False})
        page.evaluate("id=>document.querySelector('.pin[data-id=\"'+id+'\"]').scrollIntoView({block:'center'})", a)
        self.assertEqual(page.evaluate(MISSES_44, '.pin[data-id="%d"] .sum .vd-old-ref' % a), [])
        page.locator('.pin[data-id="%d"] .sum .vd-old-ref' % a).click()
        page.wait_for_function(
            "id=>[...document.querySelectorAll('.pin.flash')].some(e=>e.dataset.id===String(id))", arg=b
        )

    def test_a_folded_older_verdict_with_a_note_previews_its_badges(self):
        """A superseded verdict with a note: folded, its preview is its badge, the marker and the words '메모 있음' (the note
        shows when opened); without a note there are no such words; the current verdict's preview is still its note."""
        page = self.on("ms")
        made = []
        for key, note in (("보류", "옛 판단"), ("채택", "새 판단")):
            self.open_composer(page)
            page.fill("#note", note)
            page.locator('#c-verdict-row button[data-key="%s"]' % key).click()
            page.wait_for_function("n=>OPEN_ALL.length===n", arg=len(made) + 1)
            settle(page)
            (new,) = set(self.pins()) - set(made)
            made.append(new)
        a, b = made
        page = self.on("ms", n_open=2, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.evaluate("()=>{setSide(true); drawPins();}")
        settle(page)
        sums = page.evaluate(
            """ids=>ids.map(id=>{const s=document.querySelector('.pin[data-id="'+id+'"] .sum');
              return {text: s.textContent, marker: !!s.querySelector('.vd-old'), shown: s.getClientRects().length>0};})""",
            [a, b],
        )
        self.assertEqual(sums[0], {"text": "판정 보류" + replaced(b) + "메모 있음", "marker": True, "shown": True})
        self.assertEqual(sums[1], {"text": "새 판단", "marker": False, "shown": True})

    def test_a_done_row_with_the_marker_keeps_its_facts_on_two_lines(self):
        """A superseded verdict's done row at 320, 344 and 390 px (touch), in the ~300 px panel at 841 x 673 and at 1400 px:
        the first line is the number, its verdict badge and the marker (one block, the marker under the badge where the
        line is short) with [답글] at the row's end beside the number - never on a line of its own; the second line is
        '2쪽 영역' (as every card names a page) and the time, on one line; the panel does not scroll sideways."""
        page = self.on("rv")
        a = self.press_page(page, 2, "보류")
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % a, {"reply": "보류 절로 옮겼습니다"}, ALICE)[0], 200)
        self.reload(page)
        b = self.press_page(page, 2, "채택")
        touch = {"is_mobile": True, "has_touch": True}
        for w, h, more in ((320, 720, touch), (344, 882, touch), (390, 844, touch), (841, 673, touch), (1400, 850, {})):
            with self.subTest(width=w):
                page = self.on("rv", n_open=1, viewport={"width": w, "height": h}, **more)
                page.evaluate("()=>{SEC.done=true; setSide(true); drawPins();}")
                settle(page)
                self.assertEqual(page.evaluate(OLD, a)["ref"], b)
                got = page.evaluate(
                    r"""id=>{const r=document.querySelector('.arc-row[data-id="'+id+'"]'), R=r.getBoundingClientRect(), p=document.querySelector('#right');
                      const box=s=>r.querySelector(s).getBoundingClientRect(), mid=x=>x.top+x.height/2, n=box('.n'), k=box('.b-reply'), m=box('.vd-old'), v=box('.badge-verdict');
                      const l1=r.querySelector('.arc-l1'), l2=r.querySelector('.arc-l1b'), two=l2?[...l2.children].map(e=>mid(e.getBoundingClientRect())):[];
                      return {head: [...r.querySelectorAll('.arc-l1 .arc-head>*')].map(e=>e.classList.contains('n')?'n':e.classList.contains('badge-verdict')?'verdict':e.classList.contains('vd-old')?'marker':e.tagName.toLowerCase()),
                        replyBesideNumber: k.top<=mid(n)&&mid(n)<=k.bottom, markerLeftOfReply: m.right<=k.left+0.5, badgeLeftOfReply: v.right<=k.left+0.5,
                        atEnd: Math.abs(k.right-R.right)<=1, second: l2?l2.textContent.replace(/\s+/g,' ').trim():null,
                        secondOneLine: two.length>0&&Math.max(...two)-Math.min(...two)<=2, below: !!l2&&l2.getBoundingClientRect().top>=l1.getBoundingClientRect().bottom-0.5,
                        sideways: p.scrollWidth-p.clientWidth};}""",
                    a,
                )
                self.assertEqual(got["head"], ["svg", "n", "verdict", "marker"])
                self.assertTrue(got["second"].startswith("2쪽 영역"), got["second"])
                flags = (
                    "replyBesideNumber",
                    "markerLeftOfReply",
                    "badgeLeftOfReply",
                    "atEnd",
                    "secondOneLine",
                    "below",
                )
                self.assertEqual(
                    {k: got[k] for k in flags + ("sideways",)}, {**{k: True for k in flags}, "sideways": 0}, got
                )

    def test_a_closed_latex_verdict_on_lines_that_now_hold_other_text_is_its_own_target(self):
        """A LaTeX verdict is closed (awaiting review: the server no longer re-matches its lines), then two lines are added
        above it, so its line numbers now hold other text, and a new verdict is saved on those numbers: the two are not
        about the same lines - no marker on the old one, and the new one is current for nothing else."""
        self.PICK = {"lo": 10, "hi": 12, "raw_lo": 10, "raw_hi": 12, "levels": [], "default_level": "raw"}
        page = self.on("ms")
        self.open_composer(page)
        page.locator('#c-verdict-row button[data-key="보류"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        (a,) = self.pins()
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % a, {"reply": "done"}, AGENT)[0], 200)
        self.main.write_text("% added\n% added\n" + self.main.read_text(encoding="utf-8"), encoding="utf-8")
        self.reload(page)
        self.open_composer(page)
        page.locator('#c-verdict-row button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        (b,) = set(self.pins()) - {a}
        old, new = self.pins()[a], self.pins()[b]
        self.assertEqual((old["lo"], old["hi"]), (new["lo"], new["hi"]))  # the same numbers...
        self.assertNotEqual(old["anchor"], new["anchor"])  # ...on other text
        page.evaluate("SEC.review=true")
        self.reload(page)
        self.assertIsNone(page.evaluate(OLD, a))
        self.assertEqual(
            page.evaluate("ids=>ids.map(id=>verdictSuperseder({id,verdict:'x',doc:DOC||DEFAULT_DOC}))", [a, b]),
            [None, None],
        )

    def test_undoing_a_confirm_of_a_pin_deleted_elsewhere_does_not_bring_it_back(self):
        """[확인] on the newest verdict awaiting review, another window deletes that pin, the list is read again, and the
        confirm's [되돌리기] is pressed: the deleted pin does not come back into the order - the line and the older card
        keep the older verdict - and the status line says it was deleted elsewhere."""
        page = self.on("rv")
        older = self.press_page(page, 1, "보류")
        newer = self.press_page(page, 1, "채택")
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % newer, {"reply": "done"}, AGENT)[0], 200)
        self.reload(page)
        page.evaluate("()=>{SEC.review=true; setSide(true); drawPins();}")
        page.locator('#review-pins .pin[data-id="%d"] [data-act="confirm"]' % newer).click()
        settle(page)
        self.assertEqual(self.call("POST", "/api/pins/%d/drop" % newer, {}, ALICE)[0], 200)
        self.reload(page)
        page.evaluate(
            "id=>{const n=[...document.querySelectorAll('.nt-row,.nt-chip,.nt-banner,#status')].find(e=>e.textContent.includes('핀 #'+id+' 확인'));"
            " n.querySelector('[data-act=notice-act]').click();}",
            newer,
        )
        settle(page)
        got = page.evaluate(
            "id=>({review: REVIEW_ALL.some(p=>p.id===id), confirming: CONFIRMING.has(id), order: [...verdictOrder(DOC).cur.keys()].includes(id)})",
            newer,
        )
        self.assertEqual(got, {"review": False, "confirming": False, "order": False})
        self.assertEqual(page.evaluate(LINE, 1)["pin"], str(older))
        self.assertIsNone(page.evaluate(OLD, older))
        self.assertIn(
            "핀 #%d 은 그사이 다른 곳에서 지워졌습니다" % newer,
            page.evaluate("document.querySelector('#status').innerText"),
        )
        self.assertNotIn(newer, self.pins())

    def test_undoing_a_confirm_still_brings_the_pin_back_as_the_list_has_it(self):
        """The same undo when nothing happened elsewhere: the pin goes back to the review list and is the line's verdict."""
        page = self.on("rv")
        self.press_page(page, 1, "보류")
        newer = self.press_page(page, 1, "채택")
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % newer, {"reply": "done"}, AGENT)[0], 200)
        self.reload(page)
        page.evaluate("()=>{SEC.review=true; setSide(true); drawPins();}")
        page.locator('#review-pins .pin[data-id="%d"] [data-act="confirm"]' % newer).click()
        settle(page)
        self.reload(page)
        page.evaluate(
            "id=>{const n=[...document.querySelectorAll('.nt-row,.nt-chip,.nt-banner,#status')].find(e=>e.textContent.includes('핀 #'+id+' 확인'));"
            " n.querySelector('[data-act=notice-act]').click();}",
            newer,
        )
        settle(page)
        self.assertTrue(page.evaluate("id=>REVIEW_ALL.some(p=>p.id===id)&&!CONFIRMING.has(id)", newer))
        self.assertEqual(page.evaluate(LINE, 1)["pin"], str(newer))

    def test_the_first_press_after_opening_a_document_saves(self):
        """Opening the figure document or the PDF and pressing a page line's word at once - the first press, no retry - at
        1440 x 900 with a mouse and at 390 x 844 on touch: the verdict is saved."""
        for doc in ("fig", "rv"):
            for size, more in (((1440, 900), {}), ((390, 844), {"is_mobile": True, "has_touch": True})):
                with self.subTest(doc=doc, size=size):
                    n = len(self.pins())
                    page = self.on(doc, n_open=n, viewport={"width": size[0], "height": size[1]}, **more)
                    self.press_page(page, 1, "보류")

    def test_a_confirmed_verdict_deleted_elsewhere_in_its_undo_window_leaves_the_order(self):
        """The newest verdict awaiting review is confirmed with [확인]; during the undo window another window deletes it and
        the list is read again: the page line and the older verdict's card go back to the older verdict - nothing names the
        deleted pin."""
        page = self.on("rv")
        older = self.press_page(page, 1, "보류")
        newer = self.press_page(page, 1, "채택")
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % newer, {"reply": "done"}, AGENT)[0], 200)
        self.reload(page)
        page.evaluate("()=>{SEC.review=true; setSide(true); drawPins();}")
        self.assertEqual(page.evaluate(OLD, older)["ref"], newer)
        page.locator('#review-pins .pin[data-id="%d"] [data-act="confirm"]' % newer).click()
        settle(page)
        self.assertTrue(page.evaluate("id=>CONFIRMING.has(id)", newer))
        self.assertEqual(self.call("POST", "/api/pins/%d/drop" % newer, {}, ALICE)[0], 200)
        self.reload(page)
        self.assertTrue(page.evaluate("id=>CONFIRMING.has(id)", newer))  # still in its undo window
        self.assertEqual(page.evaluate(LINE, 1)["pin"], str(older))
        self.assertIsNone(page.evaluate(OLD, older))

    def test_latex_verdicts_on_the_same_lines_and_the_review_and_done_rows(self):
        """Two composer verdicts on the same lines of the LaTeX manuscript: the older is marked, in its open card, then as
        a review card and a done row; a verdict on other lines has no target in common and no marker."""
        page = self.on("ms")
        made = []
        for key in ("보류", "채택"):
            self.open_composer(page)
            page.locator('#c-verdict-row button[data-key="%s"]' % key).click()
            page.wait_for_function("n=>OPEN_ALL.length===n", arg=len(made) + 1)
            settle(page)
            (new,) = set(self.pins()) - set(made)
            made.append(new)
        a, b = made
        self.assertEqual(page.evaluate(OLD, a)["ref"], b)
        self.assertIsNone(page.evaluate(OLD, b))
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % a, {"reply": "done"}, AGENT)[0], 200)
        page.evaluate("SEC.review=true")
        self.reload(page)
        self.assertEqual(page.evaluate(OLD, a)["ref"], b)  # the review card
        self.assertEqual(self.call("POST", "/api/pins/%d/confirm" % a, {}, ALICE)[0], 200)
        page.evaluate("SEC.done=true")
        self.reload(page)
        self.assertEqual(page.evaluate(OLD, a)["ref"], b)  # the done row
        self.PICK = {"lo": 20, "hi": 21, "raw_lo": 20, "raw_hi": 21, "levels": [], "default_level": "raw"}
        self.open_composer(page)
        page.locator('#c-verdict-row button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===2")
        settle(page)
        (c,) = set(self.pins()) - {a, b}
        self.assertIsNone(page.evaluate(OLD, c))
        self.assertIsNone(page.evaluate(OLD, b))


class PressAcrossARedraw(VerdictBase):
    """The pin list redraws on every poll; a page line whose words did not change keeps its buttons."""

    def test_a_press_held_while_the_list_redraws_still_saves(self):
        """The mouse goes down on a page-line word, the marks and lines redraw (a poll's answer), the mouse comes up: the
        press saves a verdict. Buttons rewritten between down and up would send the click to the line and lose it."""
        page = self.on("fig")
        box = page.locator('#doc .pv[data-page="1"] button[data-key="보류"]').bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.evaluate("marks()")
        page.mouse.up()
        page.wait_for_function("OPEN_ALL.length===1", timeout=5000)
        settle(page)
        self.assertEqual([p.get("verdict") for p in self.pins().values()], ["보류"])


# What a verdict pin's body is when another person saves it again (the server sets the rest).
PIN_FIELDS = (
    "file",
    "name",
    "page",
    "lo",
    "hi",
    "raw_lo",
    "raw_hi",
    "via",
    "score",
    "frac",
    "quote",
    "pdf_build",
    "scope",
    "kind",
    "el",
    "doc",
    "kind_req",
    "assignee",
    "verdict",
    "note",
)


class FunctionalUiFixes(VerdictBase):
    """The independent functional UI test's findings on 4945e1b (each a regression test)."""

    def bob_again(self, pid, key):
        """Bob saves a verdict word key about the same target as pin pid, through the API; its id."""
        body = {k: v for k, v in self.pins()[pid].items() if k in PIN_FIELDS}
        code, data = self.call("POST", "/api/pin", {**body, "verdict": key}, BOB)
        self.assertEqual(code, 200, data)
        return data["id"]

    def test_a_zoomed_page_line_stays_in_view_with_a_mouse(self):
        """1440 x 900 with a mouse, the PDF zoomed with Ctrl+= five times: scrolled sideways to 30% and to the end, page 1's
        line - its words and its buttons - stays whole inside the PDF area (the pages' column is as wide as the page)."""
        for doc in ("rv", "fig"):
            with self.subTest(doc=doc):
                page = self.on(doc, viewport={"width": 1440, "height": 900})
                self.press_page(page, 1, "보류")
                page.locator("#left").hover()
                for _ in range(5):
                    page.keyboard.press("Control+Equal")
                settle(page)
                self.assertGreater(page.evaluate("W/fitWidth()"), 2)
                page.evaluate(
                    """()=>{const l=document.querySelector('#doc .pv[data-page="1"]'), L=document.querySelector('#left');
                      L.scrollTop+=l.getBoundingClientRect().top-L.getBoundingClientRect().top-300;}"""
                )
                for frac in (0.3, 1.0):
                    page.evaluate(
                        "f=>{const L=document.querySelector('#left'); L.scrollLeft=(L.scrollWidth-L.clientWidth)*f;}",
                        frac,
                    )
                    settle(page)
                    got = page.evaluate(
                        """()=>{const L=document.querySelector('#left'), r=L.getBoundingClientRect(), l=document.querySelector('#doc .pv[data-page="1"]');
                          const inside=e=>{const b=e.getBoundingClientRect(); return b.width>0&&b.left>=r.left-0.5&&b.right<=r.left+L.clientWidth+0.5;};
                          return {scrolled: L.scrollLeft>0, words: inside(l.querySelector('.pv-t')), buttons: [...l.querySelectorAll('button.vd-b')].every(inside)};}"""
                    )
                    self.assertEqual(got, {"scrolled": True, "words": True, "buttons": True}, (doc, frac))

    def test_a_press_held_while_a_newer_verdict_arrives_still_saves(self):
        """Alice's mouse goes down on page 1's 보류 while Bob saves a newer verdict there and her list is read again (the
        line's words change: a new number, Bob's name); the mouse comes up: her verdict is saved."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        box = page.locator('#doc .pv[data-page="1"] button[data-key="보류"]').bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        b = self.bob_again(a, "채택")
        page.evaluate("loadPins()")
        page.wait_for_function(
            "id=>(document.querySelector('#doc .pv[data-page=\"1\"]')||{}).dataset.pin===String(id)", arg=b
        )
        page.mouse.up()
        page.wait_for_function("OPEN_ALL.length===3", timeout=8000)
        settle(page)
        (mine,) = set(self.pins()) - {a, b}
        self.assertEqual(self.pins()[mine]["verdict"], "보류")

    def test_a_press_across_the_minute_tick_still_saves(self):
        """The mouse goes down on a word of a line that shows Bob's verdict and its relative time; the time is drawn again
        (the minute tick and a redraw with a new time); the mouse comes up: the press saves."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        b = self.bob_again(a, "보류")
        self.reload(page)
        box = page.locator('#doc .pv[data-page="1"] button[data-key="채택"]').bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.evaluate(
            "id=>{const p=OPEN_ALL.find(x=>x.id===id); OPEN_ALL=OPEN_ALL.map(x=>x===p?{...p,at:'2026-01-01 00:00:00'}:x); tickRel(); marks();}",
            b,
        )
        page.mouse.up()
        page.wait_for_function("OPEN_ALL.length===3", timeout=8000)

    def test_the_line_number_link_answers_44px_and_is_named_like_the_cards(self):
        """On touch (390 x 844, 841 x 673; Korean and English) page 1's '#N' link answers 44 x 44 px - also on a long line
        whose buttons stand on a row of their own under it (390) - and so do the buttons; its name is the card marker's
        link's: '지금 판정 #N 카드로 갑니다'."""
        page = self.on("fig")
        first = self.press_page(page, 1, "채택")
        a = self.bob_again(first, "보류")  # Bob's newer verdict, claimed by an agent: a long line with an earlier link
        self.assertEqual(self.call("POST", "/api/pins/%d/claim" % a, {}, AGENT)[0], 200)
        for (w, h), lang in (((390, 844), "ko"), ((841, 673), "ko"), ((390, 844), "en")):
            with self.subTest(size=(w, h), lang=lang):
                page = self.on(
                    "fig", n_open=2, lang=lang, viewport={"width": w, "height": h}, is_mobile=True, has_touch=True
                )
                ref = '#doc .pv[data-page="1"] .pv-ref'
                page.evaluate("s=>document.querySelector(s).scrollIntoView({block:'center'})", ref)
                settle(page)
                if w == 390:
                    self.assertTrue(page.evaluate("document.querySelector('#doc').classList.contains('pv-stack')"))
                self.assertEqual(page.evaluate(MISSES_44, ref), [])
                self.assertEqual(page.evaluate(MISSES_44, '#doc .pv[data-page="1"] button.vd-b'), [])
                name = page.evaluate("s=>document.querySelector(s).getAttribute('aria-label')", ref)
                self.assertEqual(
                    name,
                    "지금 판정 #%d 카드로 갑니다" % a if lang == "ko" else "Goes to the current verdict #%d's card" % a,
                )

    def test_tab_during_a_line_save_keeps_the_focus_and_a_renumbered_link_keeps_it(self):
        """A page with a verdict: Enter on 채택, and while its save runs the focus is still on that button (busy, not
        disabled); Tab moves it to the next word. Then Enter again and, during the save, the focus goes to the '#N' link: the
        save renumbers the link, and the focus stays on it."""
        page = self.on("fig")
        self.press_page(page, 1, "보류")
        one = '#doc .pv[data-page="1"] button[data-key="채택"]'
        page.focus(one)
        self.held = []
        page.keyboard.press("Enter")
        page.wait_for_function("PV_BUSY.size===1")
        self.assertTrue(page.evaluate("s=>document.activeElement===document.querySelector(s)", one))
        self.assertEqual(page.evaluate("s=>document.querySelector(s).getAttribute('aria-disabled')", one), "true")
        page.keyboard.press("Tab")
        self.release()
        page.wait_for_function("PV_BUSY.size===0&&OPEN_ALL.length===2")
        settle(page)
        self.assertEqual(
            page.evaluate("[document.activeElement.dataset.act, document.activeElement.dataset.key]"),
            ["pv-save", "보류"],
        )
        page.focus(one)
        self.held = []
        page.keyboard.press("Enter")
        page.wait_for_function("PV_BUSY.size===1")
        page.focus('#doc .pv[data-page="1"] .pv-ref')
        before = page.evaluate("document.activeElement.dataset.ref")
        self.release()
        page.wait_for_function("PV_BUSY.size===0&&OPEN_ALL.length===3")
        settle(page)
        got = page.evaluate("[document.activeElement.classList.contains('pv-ref'), document.activeElement.dataset.ref]")
        self.assertTrue(got[0], got)
        self.assertNotEqual(got[1], before)

    def test_the_retry_banner_says_when_the_verdict_was_dropped(self):
        """A verdict save fails, then the kind goes to 질문 and back, or [제안 수정] is turned on and off: the banner no longer
        says '판정 저장 실패' - it says the save failed as a pin's and that the verdict was dropped - and [다시 저장] saves a plain
        pin."""
        for how in ("kind", "switch"):
            with self.subTest(how=how):
                page = self.on("ms")
                self.open_composer(page)
                self.fail_pin = 1
                page.locator('#c-verdict-row button[data-key="채택"]').click()
                page.wait_for_function("document.querySelector('#btn-save').textContent.includes('다시 저장')")
                settle(page)
                self.assertIn(
                    "판정 저장 실패", page.evaluate("document.querySelector('#c-actions .nt-banner').innerText")
                )
                if how == "kind":
                    for kind in ("question", "fix"):
                        page.locator('#c-kind button[data-kind="%s"]' % kind).click()
                        settle(page)
                else:
                    for _ in range(2):
                        page.locator("#c-sg-tg").click()
                        settle(page)
                text = page.evaluate("document.querySelector('#c-actions .nt-banner').innerText")
                self.assertNotIn("판정 저장 실패", text)
                self.assertIn("핀 저장 실패", text)
                self.assertIn("선택했던 판정은 해제됐습니다 — 판정으로 저장하려면 판정 버튼을 다시 누릅니다", text)
                page.locator("#btn-save").click()
                page.wait_for_function("OPEN_ALL.length>=1")
                settle(page)
                self.assertTrue(all(p.get("verdict") is None for p in self.pins().values()))
                for pid in list(self.pins()):
                    self.call("POST", "/api/pins/%d/drop" % pid, {}, ALICE)

    def test_a_second_pick_turns_the_buttons_off_with_the_reason(self):
        """A selection is open and a second drag starts: while its place is being found the verdict buttons are disabled
        (not only greyed) and the line under them says '위치를 찾는 중입니다'; Enter on one saves nothing."""
        page = self.on("ms")
        self.open_composer(page)
        self.held_pick = []
        page.evaluate(
            "()=>{LAST_PTR='mouse'; pick({page:1,x0:10,y0:80,x1:200,y1:120});}"
        )  # not awaited: its answer is held
        page.wait_for_function("COMPOSE.picking")
        got = page.evaluate(
            "()=>({off:[...document.querySelectorAll('#c-verdict-row button')].map(b=>b.disabled),why:(document.querySelector('#c-verdict-row .vd-why')||{}).textContent||''})"
        )
        self.assertEqual(got, {"off": [True] * 3, "why": "위치를 찾는 중입니다"})
        page.locator('#c-verdict-row button[data-key="채택"]').focus()
        page.keyboard.press("Enter")
        held, self.held_pick = self.held_pick, None
        for r in held:
            self.route(r)
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)
        self.assertEqual(self.pins(), {})
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#c-verdict-row button')].map(b=>b.disabled)"), [False] * 3
        )

    def test_the_line_draws_no_page_mark_for_any_verdict_it_accounts_for(self):
        """On the PDF, two verdicts on page 1: neither draws a page-size mark - the line accounts for the earlier one too -
        and an ordinary pin's mark is drawn as before."""
        page = self.on("rv")
        a = self.press_page(page, 1, "보류")
        b = self.press_page(page, 1, "채택")
        settle(page)
        self.assertEqual([page.locator('.mark[data-pin="%d"]' % i).count() for i in (a, b)], [0, 0])
        self.assertEqual(page.evaluate("ids=>ids.map(id=>pvShows({id}))", [a, b]), [True, True])

    def test_a_narrow_english_panel_wraps_the_armed_words_without_cutting_them(self):
        """English, five words, the panel at its least width: with 삭제 armed ('Confirm 삭제') no word is cut short - the group
        wraps - and the panel does not scroll sideways."""
        five = [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}, {"key": "수정"}, {"key": "이동"}]
        self.word_files["ms"].write_text(
            json.dumps({**WORDS, "verdicts": five, "page": False}, ensure_ascii=False), encoding="utf-8"
        )
        page = self.on("ms", lang="en", viewport={"width": 1440, "height": 900})
        page.evaluate("setSideWidth(0)")
        self.open_composer(page)
        page.locator('#c-verdict-row button[data-key="삭제"]').click()
        settle(page)
        got = page.evaluate(
            """()=>{const bs=[...document.querySelectorAll('#c-verdict-row button')], p=document.querySelector('#right');
              return {cut: bs.filter(b=>{const l=b.querySelector('.lbl'); return l.scrollWidth>l.clientWidth+0.5||b.scrollWidth>b.clientWidth+0.5;}).map(b=>b.dataset.key),
                armed: document.querySelector('#c-verdict-row button.armed').textContent, sideways: p.scrollWidth-p.clientWidth,
                panel: Math.round(p.getBoundingClientRect().width)};}"""
        )
        self.assertLessEqual(got["panel"], 300, got)
        self.assertEqual((got["cut"], got["sideways"]), ([], 0), got)
        self.assertIn("삭제", got["armed"])

    def test_the_armed_word_lets_go_when_the_time_runs_out_and_says_so(self):
        """삭제 armed on a page line: when its time runs out it reads 삭제 again and a screen reader hears it was let go."""
        page = self.on("fig")
        btn = '#doc .pv[data-page="1"] button[data-key="삭제"]'
        page.locator(btn).click()
        settle(page)
        self.assertEqual(page.locator(btn).inner_text(), "삭제 확정")
        page.evaluate("clearTimeout(VD_ARM.timer); disarmVerdict(true,true)")  # what the timer's end runs (armVerdict)
        settle(page)
        self.assertEqual(page.locator(btn).inner_text(), "삭제")
        self.assertEqual(page.evaluate("document.querySelector('#sr-news').textContent"), "삭제 확정을 풀었습니다")
        self.assertIn("disarmVerdict(true,true)", page.evaluate("String(armVerdict)"))

    def test_a_new_build_lets_an_armed_word_go(self):
        """삭제 armed on a page line, then the PDF is drawn again from a new build: the press is let go - one more press arms
        it again and saves nothing."""
        page = self.on("fig")
        btn = '#doc .pv[data-page="1"] button[data-key="삭제"]'
        page.locator(btn).click()
        settle(page)
        self.assertEqual(page.locator(btn).inner_text(), "삭제 확정")
        page.evaluate("META.pages_build=META.pages_build+'-next'; drawPageVerdicts()")
        settle(page)
        self.assertEqual(page.locator(btn).inner_text(), "삭제")
        page.locator(btn).click()
        settle(page)
        self.assertEqual((page.locator(btn).inner_text(), self.pins()), ("삭제 확정", {}))

    def test_the_save_chip_shows_the_word(self):
        """A page line's save and the composer's verdict save: the chip reads '#N 저장됨 · <낱말>'."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        self.assertIn(
            "#%d 저장됨 · 보류" % a,
            page.evaluate("document.querySelector('#doc .pv[data-page=\"1\"] .nt-chip').innerText"),
        )
        page = self.on("ms")
        self.open_composer(page)
        page.locator('#c-verdict-row button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        (b,) = set(self.pins()) - {a}
        self.assertIn("#%d 저장됨 · 채택" % b, page.evaluate("document.body.innerText"))


SIZES = (
    ((1440, 900), {}),
    ((390, 844), {"is_mobile": True, "has_touch": True}),
    ((320, 720), {"is_mobile": True, "has_touch": True}),
    ((768, 1024), {"is_mobile": True, "has_touch": True}),
    ((1024, 768), {"is_mobile": True, "has_touch": True}),
    ((344, 882), {"is_mobile": True, "has_touch": True}),
    ((673, 841), {"is_mobile": True, "has_touch": True}),
    ((841, 673), {"is_mobile": True, "has_touch": True}),
)

# The save chip's [되돌리기] on screen: whether a press at its middle lands on it, and the chip's words and box.
CHIP_UNDO = """id=>{const c=document.querySelector('.mark[data-pin="'+id+'"] .nt-chip'); if(!c) return null;
  const b=c.querySelector('[data-act=notice-act]'), r=b.getBoundingClientRect(), x=r.left+r.width/2, y=r.top+r.height/2, h=document.elementFromPoint(x,y);
  const t=c.querySelector('.nt-t');
  return {pressable: !!h&&b.contains(h), under: h?h.className||h.tagName:null, cut: t.scrollWidth>t.clientWidth+0.5, undoWhole: b.scrollWidth<=b.clientWidth+0.5};}"""


class RetestFixes(VerdictBase):
    """The functional re-test's findings on 5bc3c6b (each a regression test)."""

    def test_the_save_chips_undo_can_be_pressed_at_every_size(self):
        """A composer verdict save on a selection in the lower right of the page: at all eight sizes the chip's [되돌리기],
        scrolled to the middle of the screen, is where a press lands on it - on the unfolded foldable (841 x 673) the longer
        verdict chip ran under the panel laid over the PDF area, also when it was drawn below the fold and scrolled up
        beside the panel, and then under the touch area the panel's handle reaches into the PDF area with at its middle -
        and the action is never cut (the words may be)."""
        self.PICK = {"frac": [0.55, 0.8, 0.4, 0.05]}  # low on the page: below the fold when the chip is drawn
        for (w, h), more in SIZES:
            with self.subTest(size=(w, h)):
                page = self.on("ms", n_open=len(self.pins()), viewport={"width": w, "height": h}, **more)
                self.open_composer(page)
                before = set(self.pins())
                page.locator('#c-verdict-row button[data-key="채택"]').click()
                page.wait_for_function("n=>OPEN_ALL.length===n", arg=len(before) + 1)
                settle(page)
                (pid,) = set(self.pins()) - before
                # drawn again while the mark is below the fold (a list read redraws the chips), then scrolled up to
                page.evaluate("()=>{document.querySelector('#left').scrollTop=0; drawChips();}")
                page.evaluate(
                    "id=>{const c=document.querySelector('.mark[data-pin=\"'+id+'\"] .nt-chip'); if(c)c.scrollIntoView({block:'center',inline:'nearest'});}",
                    pid,
                )  # the chip at the middle of the screen: where the panel's handle answers presses on touch
                settle(page)
                got = page.evaluate(CHIP_UNDO, pid)
                self.assertIsNotNone(got, "no chip on the mark")
                self.assertTrue(got["pressable"] and got["undoWhole"], got)

    def test_the_save_chip_follows_a_zoom_and_a_sideways_scroll(self):
        """At 841 x 673 (touch, the panel over the PDF area) and 1440 x 900 (mouse): after a verdict save the PDF is zoomed
        to about 2.5x and scrolled sideways to its start, middle and end, the chip brought into view each time: its
        [되돌리기] is where a press lands - placed again after the zoom and while the PDF area scrolls, never left where the
        fitted page had it (off the PDF area, under the panel or its handle)."""
        self.PICK = {"frac": [0.55, 0.8, 0.4, 0.05]}
        for (w, h), more in (((841, 673), {"is_mobile": True, "has_touch": True}), ((1440, 900), {})):
            with self.subTest(size=(w, h)):
                page = self.on("ms", n_open=len(self.pins()), viewport={"width": w, "height": h}, **more)
                self.open_composer(page)
                before = set(self.pins())
                page.locator('#c-verdict-row button[data-key="채택"]').click()
                page.wait_for_function("n=>OPEN_ALL.length===n", arg=len(before) + 1)
                settle(page)
                (pid,) = set(self.pins()) - before
                page.evaluate("zoomTo(W*2.5)")
                settle(page)
                self.assertGreater(page.evaluate("W/fitWidth()"), 2.2)
                for frac in (0, 0.5, 1):
                    page.evaluate(
                        """([id,f])=>{const L=document.querySelector('#left'); L.scrollLeft=(L.scrollWidth-L.clientWidth)*f;
                          const c=document.querySelector('.mark[data-pin="'+id+'"] .nt-chip');
                          L.scrollTop+=c.getBoundingClientRect().top-L.getBoundingClientRect().top-L.clientHeight/2;}""",
                        [pid, frac],
                    )
                    settle(page)
                    got = page.evaluate(CHIP_UNDO, pid)
                    self.assertIsNotNone(got, "no chip on the mark")
                    self.assertTrue(got["pressable"] and got["undoWhole"], (frac, got))

    def test_the_page_line_after_a_failed_first_list_an_empty_one_and_a_switch(self):
        """The first pin list fails: the line keeps reading '판정 읽는 중…' with its buttons waiting (never '판정 없음'), and the
        list read again shows the page's verdict. With no pins at all the list arriving makes it '판정 없음' with live
        buttons. A switch to the PDF before the first list arrives: its line reads too, until the list comes."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        waiting = "s=>[...document.querySelectorAll(s+' button.vd-b')].map(b=>b.getAttribute('aria-disabled')==='true')"

        def reading(p, _line):
            """The line's words (as LINE reads them) and whether each button waits."""
            return {"text": p.evaluate(LINE, 1)["text"], "waiting": p.evaluate(waiting, line)}

        line = '#doc .pv[data-page="1"]'

        def boot(doc):
            context = self.browser.new_context(viewport={"width": 1400, "height": 850})
            self.addCleanup(context.close)
            watch_idle(context)
            p = context.new_page()
            p.route("**/*", self.route)
            self.held_list = []
            p.goto("http://viewer.test/?lang=ko#doc=%s" % doc)
            p.wait_for_function(
                "k=>DOC===k&&!!document.querySelector('#doc .pv[data-page=\"1\"] button.vd-b')", arg=doc, timeout=20000
            )
            return p

        with self.subTest(case="the first list fails"):
            p = boot("fig")
            held, self.held_list = self.held_list, None
            for r in held:
                r.fulfill(status=500, headers={"content-type": "application/json"}, body='{"error": "boom"}')
            p.wait_for_function("typeof LIGHT_TIMER!=='undefined'&&LIGHT_TIMER!==null", timeout=20000)
            settle(p)
            self.assertEqual(reading(p, line), {"text": "판정 읽는 중…", "waiting": [True, True, True]})
            p.evaluate("loadPins()")
            p.wait_for_function("OPEN_ALL.length===1", timeout=10000)
            settle(p)
            self.assertEqual(
                reading(p, line), {"text": "판정 #%d 보류 · 처리 대기" % a, "waiting": [False, False, False]}
            )
        with self.subTest(case="a switch before the first list"):
            p = boot("fig")
            p.evaluate("()=>{switchDoc('rv');}")
            # the list is still held, so the page never settles: wait for the PDF's first line itself
            p.wait_for_function(
                "DOC==='rv'&&META&&META.doc==='rv'&&!!document.querySelector('#doc .pv[data-page=\"1\"] button.vd-b')",
                timeout=20000,
            )
            self.assertEqual(reading(p, line), {"text": "판정 읽는 중…", "waiting": [True, True, True]})
            held, self.held_list = self.held_list, None
            for r in held:
                self.route(r)
            p.wait_for_function("typeof LIGHT_TIMER!=='undefined'&&LIGHT_TIMER!==null", timeout=20000)
            settle(p)
            self.assertEqual(reading(p, line), {"text": "판정 없음", "waiting": [False, False, False]})
        with self.subTest(case="an empty list"):
            self.assertEqual(self.call("POST", "/api/pins/%d/drop" % a, {}, ALICE)[0], 200)
            p = boot("fig")
            held, self.held_list = self.held_list, None
            for r in held:
                self.route(r)
            p.wait_for_function("typeof LIGHT_TIMER!=='undefined'&&LIGHT_TIMER!==null", timeout=20000)
            settle(p)
            self.assertEqual(reading(p, line), {"text": "판정 없음", "waiting": [False, False, False]})

    def test_the_page_line_waits_for_the_first_pin_list(self):
        """Opening the figure document while its pin list is still on its way: the line reads '판정 읽는 중…' and its
        buttons wait (aria-disabled; a press saves nothing), not '판정 없음' with live buttons; once the list arrives it
        shows the page's verdict and the buttons work."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        context = self.browser.new_context(viewport={"width": 1400, "height": 850})
        self.addCleanup(context.close)
        watch_idle(context)
        page = context.new_page()
        page.route("**/*", self.route)
        self.held_list = []
        page.goto("http://viewer.test/?lang=ko#doc=fig")
        line = '#doc .pv[data-page="1"]'
        page.wait_for_function("s=>DOC==='fig'&&!!document.querySelector(s+' button.vd-b')", arg=line, timeout=20000)
        self.assertEqual(page.evaluate(LINE, 1)["text"], "판정 읽는 중…")
        self.assertEqual(
            page.evaluate(
                "s=>[...document.querySelectorAll(s+' button.vd-b')].map(b=>b.getAttribute('aria-disabled'))", line
            ),
            ["true", "true", "true"],
        )
        page.evaluate("s=>document.querySelector(s+' button[data-key=\"채택\"]').click()", line)
        held, self.held_list = self.held_list, None
        for r in held:
            self.route(r)
        page.wait_for_function(booted(1), timeout=20000)
        settle(page)
        self.assertEqual(set(self.pins()), {a})  # the press while reading saved nothing
        self.assertEqual(page.evaluate(LINE, 1)["text"], "판정 #%d 보류 · 처리 대기" % a)
        self.assertEqual(
            page.evaluate(
                "s=>[...document.querySelectorAll(s+' button.vd-b')].map(b=>b.getAttribute('aria-disabled'))", line
            ),
            [None, None, None],
        )

    def test_an_agent_role_is_offered_no_delete_or_restore_of_a_verdict_pin(self):
        """A person with the agent role sees a verdict card without [삭제] (D16: the server refuses it) and an ordinary card
        with it; in the Trash a verdict pin has no [되살리기] for them, an ordinary one does."""
        page = self.on("fig")
        v = self.press_page(page, 1, "보류")
        self.open_composer(page)
        page.fill("#note", "보통 핀")
        page.locator("#btn-save").click()
        page.wait_for_function("OPEN_ALL.length===2")
        (plain,) = set(self.pins()) - {v}
        member_add(ps.APP.C.state, "dave@example.com", "agent")
        dave = {"Tailscale-User-Login": "dave@example.com", "Tailscale-User-Name": "Dave"}
        with mock.patch.object(type(self), "WHO", dave):
            page = self.on("fig", n_open=2)
            page.evaluate("()=>{setSide(true); drawPins();}")
            settle(page)
            drops = page.evaluate(
                "ids=>ids.map(id=>!!document.querySelector('.pin[data-id=\"'+id+'\"] [data-act=drop]'))", [v, plain]
            )
            self.assertEqual(drops, [False, True])
        for pid in (v, plain):
            self.assertEqual(self.call("POST", "/api/pins/%d/drop" % pid, {}, ALICE)[0], 200)
        with mock.patch.object(type(self), "WHO", dave):
            page = self.on("fig")
            page.evaluate(
                "()=>{const t=document.querySelector('#trash'); if(t&&!t.open)t.open=true; if(typeof drawTrash==='function')drawTrash();}"
            )
            page.wait_for_function("n=>document.querySelectorAll('#trash .arc-row').length>=n", arg=2, timeout=10000)
            restores = page.evaluate(
                "ids=>ids.map(id=>!!document.querySelector('#trash .arc-row[data-id=\"'+id+'\"] [data-act=restore]'))",
                [v, plain],
            )
            self.assertEqual(restores, [False, True])

    def test_a_lone_wrapped_word_keeps_its_own_width(self):
        """English, five words, the panel at its least width, 삭제 armed: the group wraps and a word alone on the second
        row keeps its own width at the row's start - not stretched across it."""
        five = [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}, {"key": "수정"}, {"key": "이동"}]
        self.word_files["ms"].write_text(
            json.dumps({**WORDS, "verdicts": five, "page": False}, ensure_ascii=False), encoding="utf-8"
        )
        page = self.on("ms", lang="en", viewport={"width": 1440, "height": 900})
        page.evaluate("setSideWidth(0)")
        self.open_composer(page)
        page.locator('#c-verdict-row button[data-key="삭제"]').click()
        settle(page)
        got = page.evaluate(
            """()=>{const g=document.querySelector('#c-verdict-row .vd-btns'), G=g.getBoundingClientRect(), bs=[...g.children];
              const rows=new Map(); bs.forEach(b=>{const t=Math.round(b.getBoundingClientRect().top); rows.set(t,(rows.get(t)||[]).concat([b]));});
              const last=[...rows.values()].pop(), b=last[0].getBoundingClientRect(), l=last[0].querySelector('.lbl');
              return {rows: rows.size, lastCount: last.length, startsAtLeft: Math.abs(b.left-G.left)<=1, natural: b.width<=l.scrollWidth+2*12+4, groupWidth: Math.round(G.width), width: Math.round(b.width)};}"""
        )
        self.assertGreater(got["rows"], 1, got)
        self.assertTrue(got["startsAtLeft"] and got["natural"], got)

    def test_press_page_tells_a_swallowed_click_from_one_that_never_reached_the_button(self):
        """The helper's own check: a click the viewer's SWALLOW_CLICK stops (a long touch press's tooltip window) fails with
        'stopped before it', not 'never reached the button'."""
        page = self.on("fig")
        page.evaluate("SWALLOW_CLICK=Date.now()+60000")
        with self.assertRaises(AssertionError) as caught:
            self.press_page(page, 1, "보류")
        self.assertIn("was stopped before it", str(caught.exception))
