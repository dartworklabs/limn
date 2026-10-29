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
from helpers_access import ALICE, BOB, member_add, member_set_role, talk_to
from helpers_browser import MISSES_44, BrowserBase, booted, nothing_follows, settle, watch_idle

WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}]}
AGENT = {"Tailscale-User-Login": "agentb@example.com", "Tailscale-User-Name": "Agent B"}
CAROL_VIEWER = {"Tailscale-User-Login": "carol@example.com", "Tailscale-User-Name": "Carol Lee"}
# Ends every save chip on the pages now, as its window would (a line's words hold their descriptions back while one stands).
END_CHIPS = "()=>NOTICES.forEach(n=>{if(n.place==='chip')endNotice(n,false);})"
# The text of page n's line (its state, without [판정 취소] and the dot before it), its buttons' words, the [판정 취소] it offers
# (the pin it takes back, or null), and whether its line is there at all.
LINE = """n => {const l = document.querySelector('#doc .pv[data-page="' + n + '"]'); if (!l) return null;
  const t = [...l.querySelector('.pv-t').childNodes].filter(n => !(n.classList && n.classList.contains('pv-cn'))).map(n => n.textContent).join(' ');
  const c = l.querySelector('button.pv-cancel');
  return {text: t.replace(/·/g, ' · ').replace(/\\s+/g, ' ').trim(), pin: l.dataset.pin || null, cancel: c ? Number(c.dataset.ref) : null,
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

    def take_held_list(self, page, timeout_ms=10000):
        """The held GET /api/pins routes, once the viewer has asked for the list at least once; stops holding.
        The page verdict line can draw before the list is asked for, so taking the routes as soon as the line is
        there could take none and let the real list through unheld (a CI flake: the line read the verdict, not
        '판정 읽는 중…')."""
        waited = 0
        while not self.held_list:
            if waited >= timeout_ms:
                self.fail("the viewer never asked for the pin list")
            page.wait_for_timeout(20)
            waited += 20
        held, self.held_list = self.held_list, None
        return held

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
        page.evaluate(
            END_CHIPS
        )  # while its save chip stands the line's words hold their descriptions back (TipAfterSave)
        settle(page)
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
        """Enter on a page line's word saves it; the button was redrawn while the request ran, and the focus goes on to the
        line's reason field - Esc there gives it to the PDF area, not to a word - unless the person moved it meanwhile."""
        page = self.on("fig")
        btn = '#doc .pv[data-page="1"] button[data-key="채택"]'
        page.focus(btn)
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        self.assertTrue(page.evaluate("()=>document.activeElement.classList.contains('pv-reason')"))
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.evaluate("document.activeElement.id"), "left")
        page.focus(btn)
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

    def test_on_a_phone_each_line_decides_its_own_rows(self):
        """390x844: a line too long for one row (page 2's, an earlier verdict on a narrow page) puts its buttons on the next
        row, at its start (.pv-stack on that line), and page 1's short line ('판정 없음') keeps its one row - per line (P2-7
        of the 0.4.33 review: one long line stacked every page's, 88px over the plot at 1440). The desktop keeps the same
        long state on one row on its wide page, and the short line too."""
        rows = """()=>[...document.querySelectorAll('#doc .pv')].map(l=>{const t=l.querySelector('.pv-t').getBoundingClientRect(),
          b=l.querySelector('.vd-btns').getBoundingClientRect(),L=l.getBoundingClientRect();
          return {below: b.top>=t.bottom-1, start: Math.abs(b.left-L.left)<=1, stack: l.classList.contains('pv-stack'), h: L.height};})"""
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        self.press_page(page, 2, "보류")
        self.press_page(page, 2, "채택")
        got = page.evaluate(rows)
        self.assertEqual(
            {k: got[1][k] for k in ("below", "start", "stack")}, {"below": True, "start": True, "stack": True}
        )
        self.assertEqual((got[0]["below"], got[0]["stack"]), (False, False))
        self.assertFalse(page.evaluate("document.querySelector('#doc').classList.contains('pv-stack')"))
        page = self.on("fig", n_open=2)
        self.press_page(page, 1, "보류")
        self.press_page(page, 1, "채택")
        page.evaluate(END_CHIPS)
        page.evaluate("()=>{PV_REASON=null; drawPageVerdicts();}")  # no reason field under it: the row alone
        settle(page)
        one = page.evaluate(rows)[0]
        self.assertEqual((one["below"], one["stack"]), (False, False))
        self.assertLessEqual(one["h"], 40)

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
        shows when opened); without a note there are no such words; the current verdict's preview leads with its badge and
        then its note (P2-9 of the 0.4.33 review: a note took the whole preview and hid which verdict it was)."""
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
        self.assertEqual(sums[1], {"text": "판정 채택새 판단", "marker": False, "shown": True})

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
                self.assertGreater(page.evaluate("K/fitK()"), 2)
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
                    self.assertTrue(
                        page.evaluate(
                            "document.querySelector('#doc .pv[data-page=\"1\"]').classList.contains('pv-stack')"
                        )
                    )
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
                page.evaluate("zoomTo(K*2.5)")
                settle(page)
                self.assertGreater(page.evaluate("K/fitK()"), 2.2)
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
            held = self.take_held_list(p)
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
            held = self.take_held_list(p)
            for r in held:
                self.route(r)
            p.wait_for_function("typeof LIGHT_TIMER!=='undefined'&&LIGHT_TIMER!==null", timeout=20000)
            settle(p)
            self.assertEqual(reading(p, line), {"text": "판정 없음", "waiting": [False, False, False]})
        with self.subTest(case="an empty list"):
            self.assertEqual(self.call("POST", "/api/pins/%d/drop" % a, {}, ALICE)[0], 200)
            p = boot("fig")
            held = self.take_held_list(p)
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
        held = self.take_held_list(page)
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


# Page 2's page (the tall portrait page of the figure), its line and the PDF area, in viewport px: the area's bottom is its
# client bottom (a sideways scroll bar is no part of what shows), and whether the line floats (.stuck).
FLOAT = """n => {const L = document.querySelector('#left'), lr = L.getBoundingClientRect(), pg = document.getElementById('p' + n),
  pv = document.querySelector('#doc .pv[data-page="' + n + '"]'), r = e => (b => ({top: b.top, bottom: b.bottom}))(e.getBoundingClientRect());
  return {area: {top: lr.top, bottom: lr.top + L.clientHeight}, page: r(pg), line: r(pv), stuck: pv.classList.contains('stuck')};}"""
# Scroll the PDF area so page n's top (top), middle (mid) or end - its bottom 100px above the area's bottom (end) - is there.
SCROLL = """([n, where]) => {const L = document.querySelector('#left'), lr = L.getBoundingClientRect(), r = document.getElementById('p' + n).getBoundingClientRect();
  L.scrollTop += where === 'top' ? r.top - lr.top : where === 'mid' ? r.top + r.height / 2 - (lr.top + L.clientHeight / 2) : r.bottom - (lr.top + L.clientHeight - 100);}"""
# What the topmost element at the middle of selector sel's first match is: its own (or inside it) - true - or another.
ON_TOP = """sel => {const e = document.querySelector(sel); if (!e) return null; const b = e.getBoundingClientRect();
  const h = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return !!h && (h === e || e.contains(h));}"""


WHAT = """sel => {const e = document.querySelector(sel), b = e.getBoundingClientRect(), h = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
  const d = x => x ? x.tagName + '.' + x.className + '#' + x.id : null; const line = document.querySelector('#doc .pv[data-page="1"]').getBoundingClientRect();
  return {hit: d(h), parents: [h && h.parentElement, h && h.parentElement && h.parentElement.parentElement].map(d), chip: [b.top, b.bottom, b.left, b.right], line: [line.top, line.bottom], mark: (m => [m.top, m.bottom])(e.closest('.mark').getBoundingClientRect())};}"""


class FloatingLine(VerdictBase):
    """The page line floats at the PDF area's bottom while its page is in view and settles under the page at its end; it
    stays under save chips, over the page's marks, and not over a selection being written or an open phone sheet."""

    def tall(self, page):
        """Page 2 drawn taller than the PDF area (150% of the print size)."""
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        got = page.evaluate(FLOAT, 2)
        self.assertGreater(got["page"]["bottom"] - got["page"]["top"], got["area"]["bottom"] - got["area"]["top"] + 200)

    def at(self, page, where):
        page.evaluate(SCROLL, [2, where])
        settle(page)
        return page.evaluate(FLOAT, 2)

    def test_the_line_floats_while_its_page_is_in_view_and_settles_at_its_end(self):
        """Page 2 taller than the area: with its top, then its middle in view the line floats 8px above the area's bottom
        (.stuck); with its end in view the line stands 8px under the page (not .stuck). Page 1's line, whose page is above,
        stands under page 1."""
        page = self.on("fig")
        self.tall(page)
        for where in ("top", "mid"):
            with self.subTest(where=where):
                got = self.at(page, where)
                self.assertAlmostEqual(got["line"]["bottom"], got["area"]["bottom"] - 8, delta=1)
                self.assertTrue(got["stuck"], got)
        got = self.at(page, "end")
        self.assertAlmostEqual(got["line"]["top"], got["page"]["bottom"] + 8, delta=1)
        self.assertFalse(got["stuck"], got)
        one = page.evaluate(FLOAT, 1)
        self.assertAlmostEqual(one["line"]["top"], one["page"]["bottom"] + 8, delta=1)

    def test_the_floating_line_is_under_save_chips_and_over_marks(self):
        """A save from the floating line puts its chip in the line's row, pressable: as high as the words, just before the
        first one and after the figure's name - above the line it covered the name and the plot (P3-14 of the 0.4.33
        review); a pin's mark lying under the floating line does not take its buttons; the save chip on that mark - drawn
        where the line floats - stays pressable over the line."""
        helpers_figure.viewer_build(
            self.fig, helpers_figure.BUILD2, helpers_figure.viewer_map(july=(0.47, 0.70, 0.07, 0.12))
        )
        page = self.on("fig")
        self.tall(page)
        self.at(page, "top")
        self.press_page(page, 2, "보류")
        line = page.evaluate(FLOAT, 2)
        self.assertTrue(line["stuck"], line)
        chip = page.evaluate(
            """()=>{const l=document.querySelector('#doc .pv[data-page="2"]'),c=l.querySelector(':scope>.nt-chip'),R=e=>e.getBoundingClientRect();
              if(!c)return null; const w=R(l.querySelector('.vd-b')),f=R(l.querySelector('.pv-fig'));
              return {top:R(c).top,bottom:R(c).bottom,left:R(c).left,right:R(c).right,wordsTop:w.top,wordsBottom:w.bottom,words:w.left,name:f.right};}"""
        )
        self.assertIsNotNone(chip)
        self.assertGreaterEqual(chip["top"], chip["wordsTop"] - 1, chip)
        self.assertLessEqual(chip["bottom"], chip["wordsBottom"] + 1, chip)
        self.assertLessEqual(chip["right"], chip["words"] - 8 + 1, chip)
        self.assertGreaterEqual(chip["left"], chip["name"], chip)
        self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="2"]>.nt-chip [data-act="notice-act"]'))
        # the July cell (drawn low on page 1 in this build) pinned from the composer at three times the print size - page 1
        # then taller than the area - its mark scrolled 30px under the floating line's top: the mark's save chip, drawn
        # over the line, stays pressable
        page.evaluate("setK(PT_PX*3,false)")
        settle(page)
        page.evaluate(
            "p=>{LAST_PTR='mouse'; pick({doc:'fig',page:1,pdf_build:META.pages_build,x0:p[0]*META.pages[0].pt_w,y0:p[1]*META.pages[0].pt_h,"
            "x1:(p[0]+p[2])*META.pages[0].pt_w,y1:(p[1]+p[3])*META.pages[0].pt_h,frac:p});}",
            [0.48, 0.72, 0.04, 0.08],
        )
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        page.fill("#note", "under the line")
        page.evaluate("savePin()")
        page.wait_for_function("!COMPOSE.saving&&$('#composer').hidden&&!!document.querySelector('.mark>.nt-chip')")
        page.evaluate(
            """()=>{const L=document.querySelector('#left'), m=document.querySelector('.mark:has(>.nt-chip)'), pv=document.querySelector('#doc .pv[data-page="1"]');
              const floats=L.getBoundingClientRect().top+L.clientHeight-8-pv.getBoundingClientRect().height;   // where the line's top floats
              L.scrollTop += m.getBoundingClientRect().top - (floats + 30);}"""
        )
        settle(page)
        got = page.evaluate(FLOAT, 1)
        self.assertTrue(got["stuck"], got)
        chip = page.evaluate(
            """()=>(b=>[b.top,b.bottom])(document.querySelector('.mark>.nt-chip [data-act="notice-act"]').getBoundingClientRect())"""
        )
        self.assertLess(chip[0], got["line"]["bottom"])  # the chip's [되돌리기] lies over the floating line
        self.assertGreater(chip[1], got["line"]["top"])
        self.assertTrue(
            page.evaluate(ON_TOP, '.mark>.nt-chip [data-act="notice-act"]'),
            page.evaluate(WHAT, '.mark>.nt-chip [data-act="notice-act"]'),
        )
        # a mark under the floating line (the page-size mark of a plain pin on page 1 reaches under it) leaves its words pressable
        self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="1"] button[data-key="채택"]'))

    def test_the_line_does_not_float_over_a_selection_being_written(self):
        """A pick on page 2 opens the composer: the line goes back under its page (not .stuck) until the selection is
        cancelled, then floats again."""
        page = self.on("fig")
        self.tall(page)
        self.assertTrue(self.at(page, "top")["stuck"])
        page.evaluate(
            "p=>{LAST_PTR='mouse'; pick({doc:'fig',page:2,pdf_build:META.pages_build,x0:50,y0:50,x1:300,y1:120,frac:[0.08,0.06,0.5,0.15]});}"
        )
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)
        got = page.evaluate(FLOAT, 2)
        self.assertFalse(got["stuck"], got)
        self.assertAlmostEqual(got["line"]["top"], got["page"]["bottom"] + 8, delta=1)
        page.keyboard.press("Escape")
        settle(page)
        self.assertTrue(page.evaluate(FLOAT, 2)["stuck"])

    def test_on_a_phone_it_floats_over_the_sheet_bar_and_not_over_an_open_sheet(self):
        """390x844 touch: the floating line stands 4px above what covers the PDF area's bottom (a compact screen keeps
        its plot) - the sheet's bar, and the status line over it when one shows; with the sheet open it does not float."""
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.evaluate("setSide(false)")
        self.tall(page)
        got = self.at(page, "top")
        cover = page.evaluate(
            """()=>{const tops=[document.querySelector('#right'),document.querySelector('#status-dock')].filter(e=>e&&e.getClientRects().length&&getComputedStyle(e).position==='fixed').map(e=>e.getBoundingClientRect().top);
              return Math.min(...tops);}"""
        )
        self.assertTrue(got["stuck"], got)
        self.assertAlmostEqual(got["line"]["bottom"], cover - 4, delta=1)
        self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="2"] button[data-key="채택"]'))
        page.evaluate("setSide(true)")
        settle(page)
        self.assertFalse(page.evaluate(FLOAT, 2)["stuck"])

    def test_beside_an_overlay_panel_the_line_keeps_left_of_it(self):
        """841x673 touch (the unfolded foldable), the panel open over the PDF area: the floating line is no wider than
        the room left of the panel and its handle's touch area, and every word is pressable."""
        page = self.on("fig", viewport={"width": 841, "height": 673}, is_mobile=True, has_touch=True)
        self.tall(page)
        self.at(page, "top")
        page.evaluate("setSide(true)")
        settle(page)
        got = page.evaluate(
            """()=>{const l=document.querySelector('#doc .pv[data-page="2"]').getBoundingClientRect(), r=document.querySelector('#right').getBoundingClientRect();
              return {body: document.body.className, right: l.right, panel: r.left};}"""
        )
        self.assertIn("mid-overlay", got["body"])
        self.assertLessEqual(got["right"], got["panel"] - 4 + 0.5, got)
        self.assertEqual(page.evaluate(MISSES_44, '#doc .pv[data-page="2"] button'), [])
        self.assertTrue(page.evaluate(FLOAT, 2)["stuck"])

    def test_only_the_reading_pages_line_floats_and_names_its_figure(self):
        """Page 1 under the reading line and page 2's top already in view: page 2's line stays in its place (below the
        area) - only page 1's line is the reading one, naming '1쪽 · Deployment calendar'. With page 2 under the reading
        line its line floats, names '2쪽 · Review flow' and carries the keys; page 1's goes back to its place, unnamed."""
        page = self.on("fig")
        self.tall(page)
        page.evaluate(
            """()=>{const L=document.querySelector('#left'), r=document.getElementById('p1').getBoundingClientRect();
              L.scrollTop += r.bottom - (L.getBoundingClientRect().top + L.clientHeight * 0.6);}"""
        )
        settle(page)
        state = """n=>{const l=document.querySelector('#doc .pv[data-page="'+n+'"]'), f=l.querySelector('.pv-fig');
          return {reading: l.classList.contains('reading'), stuck: l.classList.contains('stuck'), name: f&&!f.hidden?f.textContent:null,
            keys: [...l.querySelectorAll('button[data-kn]')].length};}"""
        two = page.evaluate(FLOAT, 2)
        self.assertLess(two["page"]["top"], two["area"]["bottom"] - 100)  # page 2's top is in view
        self.assertEqual(page.evaluate(state, 2), {"reading": False, "stuck": False, "name": None, "keys": 0})
        self.assertGreater(two["line"]["top"], two["area"]["bottom"])  # its line in its place, under page 2
        self.assertEqual(
            page.evaluate(state, 1), {"reading": True, "stuck": False, "name": "1쪽 · Deployment calendar", "keys": 3}
        )
        self.at(page, "top")
        self.assertEqual(
            page.evaluate(state, 2), {"reading": True, "stuck": True, "name": "2쪽 · Review flow", "keys": 3}
        )
        self.assertEqual(page.evaluate(state, 1), {"reading": False, "stuck": False, "name": None, "keys": 0})

    def test_focusing_a_floating_word_does_not_scroll(self):
        """A floating line's button taking the focus (Tab, or focus() as here) leaves the PDF area where it was and the
        line floating."""
        page = self.on("fig")
        self.tall(page)
        self.assertTrue(self.at(page, "mid")["stuck"])
        top = page.evaluate("document.querySelector('#left').scrollTop")
        page.evaluate("""document.querySelector('#doc .pv[data-page="2"] button[data-key="채택"]').focus()""")
        settle(page)
        self.assertEqual(page.evaluate("document.querySelector('#left').scrollTop"), top)
        self.assertTrue(page.evaluate(FLOAT, 2)["stuck"])


# ---- The line's layout (the 0.4.33 review of the figure document `pl`): one row on a wide screen even with an earlier
# verdict and a reason, stacking decided per line; the words, [판정 취소] and the '#N' link answer 32px with a mouse, 8px
# apart, the confirm word 16px and a divider apart; the words' outline reads 3:1 in both themes; a line starts where its
# page does beside what lies over the area's right; on the folded-open foldable in portrait the line floats on the open
# sheet's top edge and typing the reason folds the figure's name, the save chip and the status line; a folded verdict card
# shows its badge and figure; no description box while a confirm word waits.
def open_reason(page, n, tap=False):
    """Page n's reason field after a save on its line, pressed (or tapped) so it has the focus: the line's own field, or -
    where the reason sits in a popover over the line - the one its [이유 추가] opens."""
    line = '#doc .pv[data-page="%d"]' % n
    page.wait_for_function(
        "l=>!!document.querySelector(l+' .pv-reason')||!!document.querySelector(l+' button.pv-add')", arg=line
    )
    if not page.locator(line + " .pv-reason").count():
        add = page.locator(line + " button.pv-add")
        add.tap() if tap else add.click()
        page.wait_for_selector(line + " .pv-reason")
    field = page.locator(line + " .pv-reason")
    field.tap() if tap else field.click()
    return field


FOLD_PORTRAIT = {"viewport": {"width": 882, "height": 1104}, "is_mobile": True, "has_touch": True}
# Page n's line: its box, its classes, its words' boxes, [판정 취소], the '#N' link and its area (::after), the figure's
# name, and whether its buttons share the state's row.
GEOM = """n => {const l = document.querySelector('#doc .pv[data-page="' + n + '"]'), R = e => e && e.getClientRects().length ?
    (b => ({left: b.left, top: b.top, right: b.right, bottom: b.bottom, width: b.width, height: b.height}))(e.getBoundingClientRect()) : null;
  const t = l.querySelector(':scope>.pv-t'), g = l.querySelector(':scope>.vd-btns'), ref = l.querySelector('.pv-ref'), a = ref ? getComputedStyle(ref, '::after') : null;
  const conf = l.querySelector('.vd-b.vd-confirm'), div = conf ? getComputedStyle(conf, '::before') : null;
  return {line: R(l), cls: l.className, page: R(document.getElementById('p' + n)), words: [...l.querySelectorAll('.vd-b')].map(R),
    cancel: R(l.querySelector('.pv-cancel')), early: R(l.querySelector('.pv-early')), ref: R(ref),
    refArea: a && a.content !== 'none' ? [parseFloat(a.width), parseFloat(a.height)] : null,
    divider: div && div.content !== 'none' ? parseFloat(div.width) : null, fig: R(l.querySelector(':scope>.pv-fig')),
    oneRow: !!g && g.getBoundingClientRect().top < t.getBoundingClientRect().bottom - 1};}"""
# The words' outline against the button's own fill and against the line's ground (the PDF area), as drawn: colours from
# getComputedStyle composited over what is under them - the contrast ratio of each pair.
BORDER = """() => {const b = document.querySelector('#doc .pv .vd-b');
  const probe = (prop, el) => {const c = document.createElement('canvas').getContext('2d'); c.fillStyle = '#000'; c.fillStyle = getComputedStyle(el)[prop];
    c.fillRect(0, 0, 1, 1); const d = c.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255];};
  const over = (f, g) => [0, 1, 2].map(i => f[i] * f[3] + g[i] * (1 - f[3]));
  const lum = c => {const l = c.map(v => {v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);}); return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2];};
  const cr = (a, b) => {const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);};
  let ground = [255, 255, 255]; const up = []; for (let e = b.parentElement; e; e = e.parentElement) up.push(e);
  up.reverse().forEach(e => {ground = over(probe('backgroundColor', e), ground);});   // what the page paints under the button, root first
  const fill = over(probe('backgroundColor', b), ground), edge = over(probe('borderTopColor', b), fill);
  return {fill: cr(edge, fill), ground: cr(edge, ground)};}"""


class LineLayout(VerdictBase):
    """The line's row, its targets and its outline."""

    def tall(self, page):
        """Page 2 drawn taller than the PDF area (150% of the print size), its top in view: its line floats."""
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        page.evaluate(SCROLL, [2, "top"])
        settle(page)

    def test_a_wide_line_with_an_earlier_verdict_and_a_reason_stays_one_row(self):
        """1440 x 900: page 1's line with an earlier verdict, [판정 취소] and a saved reason is one row no taller than 40px,
        its buttons at the row's end; the floating line cuts its figure's name and keeps it; no line stacks (P2-7: one such
        line stacked every page's, 88px over the plot)."""
        page = self.on("fig")
        self.press_page(page, 1, "보류")
        self.press_page(page, 1, "채택")
        field = open_reason(page, 1)
        field.fill("범례가 막대를 가려 보류 쪽으로 기울지만 일단 채택")
        field.press("Enter")
        page.wait_for_function(
            "()=>!document.querySelector('#doc .pv .pv-reason')&&!!document.querySelector('#doc .pv[data-page=\"1\"] .pv-note')"
        )
        page.evaluate(END_CHIPS)
        page.evaluate("document.querySelector('#left').scrollTop=0")
        settle(page)
        got = page.evaluate(GEOM, 1)
        self.assertTrue(got["oneRow"], got)
        self.assertNotIn("pv-stack", got["cls"])
        self.assertLessEqual(got["line"]["height"], 40)
        self.assertIsNotNone(got["early"])
        self.assertIsNotNone(got["cancel"])
        self.assertTrue(  # the title is cut, its identifier ('1쪽') is not
            page.evaluate(
                """()=>{const f=document.querySelector('#doc .pv[data-page="1"] .pv-fig'),i=f.querySelector('.pv-fig-id');
                  return i.getBoundingClientRect().width>0&&f.getBoundingClientRect().width>=i.getBoundingClientRect().width-0.5;}"""
            )
        )
        self.assertAlmostEqual(got["words"][-1]["right"], got["line"]["right"], delta=1)
        self.assertEqual(page.evaluate("[...document.querySelectorAll('#doc .pv.pv-stack')].length"), 0)

    def test_mouse_targets_answer_32px_8px_apart_and_the_confirm_word_stands_apart(self):
        """With a mouse the words, [판정 취소] and the earlier link are 32px tall and the '#N' link answers 32 x 32 px (they
        were 28, 24 and 14px); the words stand 8px apart and the confirm word 16px, with a divider in the gap (P2-8)."""
        page = self.on("fig")
        self.press_page(page, 1, "보류")
        self.press_page(page, 1, "채택")
        page.evaluate(END_CHIPS)
        settle(page)
        got = page.evaluate(GEOM, 1)
        self.assertEqual([round(w["height"]) for w in got["words"]], [32, 32, 32])
        self.assertEqual(round(got["cancel"]["height"]), 32)
        self.assertEqual(round(got["early"]["height"]), 32)
        self.assertEqual(got["refArea"], [32.0, 32.0])
        gaps = [round(b["left"] - a["right"]) for a, b in zip(got["words"], got["words"][1:], strict=False)]
        self.assertEqual(gaps, [8, 16])
        self.assertEqual(got["divider"], 1.0)
        # the '#N' link answers 12px over and under its words
        hit = page.evaluate(
            """()=>{const r=document.querySelector('#doc .pv[data-page="1"] .pv-ref'),b=r.getBoundingClientRect(),x=b.left+b.width/2;
              return [b.top+b.height/2-14,b.top+b.height/2+14].map(y=>{const h=document.elementFromPoint(x,y); return !!h&&(h===r||r.contains(h));});}"""
        )
        self.assertEqual(hit, [True, True])

    def test_on_a_foldable_the_confirm_words_area_keeps_16px_from_its_neighbours(self):
        """882 x 1104 touch: every word answers 44px and the confirm word's 44px area stands 16px clear of the word before
        it (their areas nearly met)."""
        page = self.on("fig", **FOLD_PORTRAIT)
        page.evaluate("setSide(false)")
        settle(page)
        self.assertEqual(page.evaluate(MISSES_44, '#doc .pv[data-page="1"] button.vd-b'), [])
        got = page.evaluate(GEOM, 1)
        hits = [
            (w["left"] + w["width"] / 2 - max(w["width"], 44) / 2, w["left"] + w["width"] / 2 + max(w["width"], 44) / 2)
            for w in got["words"]
        ]
        self.assertGreaterEqual(round(hits[2][0] - hits[1][1]), 16)
        self.assertEqual(got["divider"], 1.0)

    def test_the_words_outline_reads_3_to_1_in_both_themes(self):
        """The words' outline against the button's fill and against the line's ground, light and dark: 3:1 and more (the
        --input border read 1.5:1 on white; P3-15)."""
        page = self.on("fig")
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page.evaluate("t=>setTheme(t)", theme)
                settle(page)
                got = page.evaluate(BORDER)
                self.assertGreaterEqual(got["fill"], 3, got)
                self.assertGreaterEqual(got["ground"], 3, got)

    def test_a_line_starts_where_its_page_does_beside_what_lies_over_the_right(self):
        """1280 x 800, the panel closed: whatever lies over the PDF area's right side (pvInsetR - the closed panel's status
        box here, put there when the test's instance shows none), the line starts at its page's left edge and ends before
        it (it started 36px left of the page, P3-11)."""
        page = self.on("fig", viewport={"width": 1280, "height": 800})
        page.evaluate("setSide(false)")
        settle(page)
        # make the room on the right narrower than the page: the line is cut on its right, not pushed left
        page.evaluate(
            "()=>{window.__ir=pvInsetR; const L=document.querySelector('#left'),p=document.getElementById('p1').getBoundingClientRect(),lr=L.getBoundingClientRect();"
            "const edge=lr.left+L.clientWidth-parseFloat(getComputedStyle(L).paddingRight); const want=Math.round(edge-(p.right-40)); pvInsetR=()=>want; sizePv(); pvStick();}"
        )
        settle(page)
        got = page.evaluate(GEOM, 1)
        self.assertAlmostEqual(got["line"]["left"], got["page"]["left"], delta=1)
        self.assertAlmostEqual(got["line"]["right"], got["page"]["right"] - 40, delta=1.5)
        self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="1"] button[data-key="삭제"]'))
        page.evaluate("()=>{pvInsetR=window.__ir; sizePv();}")

    def test_the_figure_keeps_its_identifier_and_its_title_gives_way(self):
        """The reading line names its figure by an identifier that is never cut - the page and the code that heads the map
        title ('1쪽 · PL17', a leading tag such as '[후보]' moved to the title), else the figure id - and the rest of the
        title, cut first: next to the buttons '6쪽 · …' no longer said which figure a press decides (review of #302)."""
        page = self.on("fig")
        parts = """t=>{const was=META.pages[0].title; META.pages[0].title=t; const p=pvFigParts(1); META.pages[0].title=was; return [p.id,p.rest];}"""
        fig = page.evaluate("META.pages[0].figure")
        self.assertEqual(
            page.evaluate(parts, "[후보] PL17 · 다섯 비교 쌍의 월별 효과"),
            ["1쪽 · PL17", "[후보] 다섯 비교 쌍의 월별 효과"],
        )
        self.assertEqual(page.evaluate(parts, "PL5 · 비교"), ["1쪽 · PL5", "비교"])
        self.assertEqual(page.evaluate(parts, "Deployment calendar"), ["1쪽", "Deployment calendar"])
        self.assertEqual(page.evaluate(parts, ""), ["1쪽 · " + fig, ""])
        self.press_page(page, 1, "보류")
        self.press_page(page, 1, "채택")
        page.evaluate(END_CHIPS)
        page.evaluate(
            """()=>{META.pages[0].title='[후보] PL17 · 다섯 비교 쌍의 월별 효과 — 쌍마다 한 칸 그리고 아주 긴 설명이 이어진다';
              PV_REASON=null; drawPageVerdicts(); const l=document.querySelector('#doc .pv[data-page="1"]'); l.style.width='640px'; pvFit([l]);}"""
        )
        got = page.evaluate(
            """()=>{const l=document.querySelector('#doc .pv[data-page="1"]'),id=l.querySelector('.pv-fig-id'),t=l.querySelector('.pv-fig-t'),s=l.querySelector('.pv-t');
              return {stack:l.classList.contains('pv-stack'),id:id.textContent,idWhole:id.scrollWidth<=id.clientWidth+1&&id.getBoundingClientRect().right<=s.getBoundingClientRect().left,
                cut:t.scrollWidth>t.clientWidth+1};}"""
        )
        self.assertEqual(got, {"stack": False, "id": "1쪽 · PL17", "idWhole": True, "cut": True})

    def test_the_save_chip_never_covers_the_current_verdict(self):
        """A row's save chip stands just left of the buttons over the state's end; where its words would reach the figure's
        identifier or the current verdict and its state it folds to [되돌리기] (with its icon while that fits) and still
        covers none of them (review of #302: the opaque chip hid the current verdict for 6 seconds)."""
        page = self.on("fig")
        self.press_page(page, 1, "보류")
        self.press_page(page, 1, "채택")
        geom = """w=>{const l=document.querySelector('#doc .pv[data-page="1"]'); if(w){l.style.width=w+'px'; pvFit([l]);}
          const c=l.querySelector(':scope>.nt-chip'),b=e=>e.getBoundingClientRect(),v=e=>!!e&&e.getClientRects().length>0;
          const keep=[...l.querySelectorAll('.pv-fig-id,.pv-t>.pv-s,.pv-t>.pv-st')].filter(v).reduce((r,e)=>Math.max(r,b(e).right),0);
          return {short:l.classList.contains('pv-chip-short'),words:v(c.querySelector('.nt-t')),undo:v(c.querySelector('[data-act="notice-act"]')),
            clear:b(c).left>=keep,beside:Math.round(l.querySelector('.vd-b').getBoundingClientRect().left-b(c).right),stack:l.classList.contains('pv-stack')};}"""
        wide = page.evaluate(geom, 0)
        self.assertEqual(
            (wide["short"], wide["words"], wide["undo"], wide["clear"], wide["beside"]), (False, True, True, True, 8)
        )
        # narrower and narrower rows: the chip never reaches the state; where its words would, it folds
        folded = None
        for w in range(560, 300, -20):
            got = page.evaluate(geom, w)
            if got["stack"]:
                break
            self.assertTrue(got["clear"], (w, got))
            if got["short"]:
                folded = got
                break
        self.assertIsNotNone(folded)
        self.assertEqual((folded["words"], folded["undo"]), (False, True))
        self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="1"]>.nt-chip [data-act="notice-act"]'))

    def test_no_description_box_while_a_confirm_word_waits(self):
        """A confirm word's first press: the armed word ('삭제 확정') draws no description and the box that was up goes - it
        covered the line's figure name (P3-14); Esc gives the description back."""
        page = self.on("fig")
        btn = '#doc .pv[data-page="1"] button[data-key="삭제"]'
        page.hover(btn)
        page.wait_for_function("()=>!document.querySelector('#tip').hidden")
        page.locator(btn).click()
        nothing_follows(page, 500)
        self.assertEqual(page.locator(btn).text_content(), "삭제 확정")
        self.assertIsNone(page.get_attribute(btn, "data-tip"))
        self.assertTrue(page.evaluate("document.querySelector('#tip').hidden"))
        page.keyboard.press("Escape")
        settle(page)
        self.assertIsNotNone(page.get_attribute(btn, "data-tip"))


class FoldablePortrait(VerdictBase):
    """882 x 1104 touch (the folded-open foldable in portrait, the tablet sheet band)."""

    def tall(self, page):
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        page.evaluate(SCROLL, [2, "top"])
        settle(page)

    def test_the_line_floats_on_the_open_sheets_top_edge(self):
        """With the pin sheet open the reading line floats on its top edge (the status line over it when one shows), every
        word pressable - it went under its page and the sheet covered it (P2-9). The phone still does not float over its
        open sheet (FloatingLine)."""
        page = self.on("fig", **FOLD_PORTRAIT)
        page.evaluate("setSide(false)")
        self.tall(page)
        page.evaluate("setSide(true)")
        settle(page)
        self.assertIn("band-tablet-sheet", page.evaluate("document.body.className"))
        got = page.evaluate(FLOAT, 2)
        cover = page.evaluate(
            """()=>Math.min(...[document.querySelector('#right'),document.querySelector('#status-dock')].filter(e=>e&&e.getClientRects().length&&getComputedStyle(e).position==='fixed').map(e=>e.getBoundingClientRect().top))"""
        )
        self.assertTrue(got["stuck"], got)
        self.assertAlmostEqual(got["line"]["bottom"], cover - 4, delta=1)
        for key in ("채택", "보류", "삭제"):
            self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="2"] button[data-key="%s"]' % key))

    def test_typing_the_reason_folds_the_name_the_chip_and_the_status_line(self):
        """A tap saves 보류 and the reason field waits; while it is typed in (body.pv-typing) the line drops its figure's
        name, its save chip shows only [되돌리기] and the status line over the sheet steps aside - line, field, chip and
        sheet took the 55% the keyboard leaves (P2-9). Leaving the field brings them back."""
        page = self.on("fig", **FOLD_PORTRAIT)
        page.evaluate("setSide(false)")
        self.tall(page)
        page.evaluate("lineNote('a message on the status line',NOTICE_KIND.INFO)")
        settle(page)
        page.locator('#doc .pv[data-page="2"] button[data-key="보류"]').tap()
        page.wait_for_selector('#doc .pv[data-page="2"]>.nt-chip')
        shown = """()=>{const l=document.querySelector('#doc .pv[data-page="2"]'),v=e=>!!e&&e.getClientRects().length>0;
          return {typing:document.body.classList.contains('pv-typing'),name:v(l.querySelector('.pv-fig')),chipWords:v(l.querySelector('.nt-chip .nt-t')),
            undo:v(l.querySelector('.nt-chip [data-act="notice-act"]')),dock:v(document.querySelector('#status-dock'))};}"""
        self.assertEqual(
            page.evaluate(shown), {"typing": False, "name": True, "chipWords": True, "undo": True, "dock": True}
        )
        open_reason(page, 2, tap=True)
        page.keyboard.type("폴더블에서 친 이유")
        settle(page)
        self.assertEqual(
            page.evaluate(shown), {"typing": True, "name": False, "chipWords": False, "undo": True, "dock": False}
        )
        page.keyboard.press("Escape")
        settle(page)
        got = page.evaluate(shown)
        self.assertEqual((got["typing"], got["name"]), (False, True))

    def test_a_reason_field_taken_away_while_typed_in_lets_the_fold_go(self):
        """The pin is deleted elsewhere while its reason is typed: the next list takes the field out of the page with no
        focus event of its own (Chromium sends no focusout for a removed element), and the line and the status line come
        back - body.pv-typing is read again after every drawing of the lines (review of #302)."""
        page = self.on("fig", **FOLD_PORTRAIT)
        page.evaluate("setSide(false)")
        self.tall(page)
        page.evaluate("lineNote('a message on the status line',NOTICE_KIND.INFO)")
        new = self.press_page(page, 2, "보류")
        page.evaluate(END_CHIPS)
        open_reason(page, 2, tap=True)
        page.keyboard.type("곧 사라질 이유")
        settle(page)
        self.assertTrue(page.evaluate("document.body.classList.contains('pv-typing')"))
        # whatever this browser sends when a focused element leaves the page, nothing reaches the viewer's own listeners: the
        # drawing of the lines alone has to let the fold go
        page.evaluate("window.addEventListener('focusout',e=>e.stopImmediatePropagation(),true)")
        self.assertEqual(self.call("POST", "/api/pins/%d/drop" % new, {})[0], 200)
        page.evaluate("loadPins()")
        page.wait_for_function("()=>!document.querySelector('#doc .pv .pv-reason')")
        settle(page)
        got = page.evaluate(
            """()=>({typing:document.body.classList.contains('pv-typing'),dock:document.querySelector('#status-dock').getClientRects().length>0,
              name:document.querySelector('#doc .pv[data-page="2"] .pv-fig').getClientRects().length>0})"""
        )
        self.assertEqual(got, {"typing": False, "dock": True, "name": True})

    def test_a_folded_verdict_card_shows_its_badge_and_figure_before_its_reason(self):
        """The sheet's folded card of a verdict with a reason leads with '판정 채택' and the figure's name, the reason on a
        line under them - the reason took the whole preview (P2-9)."""
        page = self.on("fig", **FOLD_PORTRAIT)
        page.evaluate("setSide(false)")
        settle(page)
        page.locator('#doc .pv[data-page="1"] button[data-key="채택"]').tap()
        open_reason(page, 1, tap=True)
        page.keyboard.type("범례가 막대를 가린다")
        page.keyboard.press("Enter")
        page.wait_for_function("()=>OPEN_ALL.some(p=>p.note==='범례가 막대를 가린다')")
        page.evaluate("setSide(true)")
        settle(page)
        got = page.evaluate(
            """()=>{const s=document.querySelector('#pins .pin .sum'),v=e=>!!e&&e.getClientRects().length>0,n=s.querySelector('.sum-note');
              return {badge:v(s.querySelector('.badge-verdict')),target:v(s.querySelector('.vd-target'))?s.querySelector('.vd-target').textContent:null,
                note:v(n)?n.textContent:null,below:v(n)&&n.getBoundingClientRect().top>=s.querySelector('.badge-verdict').getBoundingClientRect().bottom-1};}"""
        )
        self.assertEqual(
            got, {"badge": True, "target": "Deployment calendar", "note": "범례가 막대를 가린다", "below": True}
        )


class Keys(VerdictBase):
    """1-5 press the words on the line of the page under the reading line: a confirm word twice; never in a text field, a
    dialog or while a selection is being written."""

    def reading(self, page, n):
        """The viewer showing page n's top at the PDF area's top: the reading line is on page n."""
        page.evaluate(SCROLL, [n, "top"])
        settle(page)
        self.assertEqual(page.evaluate("PV_KEYS"), n)

    def count(self):
        return len(self.pins())

    def test_keys_press_the_reading_pages_words_and_say_so(self):
        """Page 2 under the reading line: its buttons carry the keys (data-kn 1-3, aria-keyshortcuts, '단축키 N' in the
        tip, the confirm word's '(두 번)'), page 1's none. 2 saves 보류 about page 2's figure (B3)."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        self.reading(page, 2)
        keys = """n=>[...document.querySelectorAll('#doc .pv[data-page="'+n+'"] button.vd-b')].map(b=>[b.dataset.kn||null,b.getAttribute('aria-keyshortcuts'),b.dataset.tip])"""
        self.assertEqual([k[:2] for k in page.evaluate(keys, 2)], [["1", "1"], ["2", "2"], ["3", "3"]])
        self.assertTrue(page.evaluate(keys, 2)[0][2].endswith("단축키 1"))
        self.assertTrue(page.evaluate(keys, 2)[2][2].endswith("단축키 3 (두 번)"))
        self.assertEqual([k[:2] for k in page.evaluate(keys, 1)], [[None, None]] * 3)
        before = set(self.pins())
        page.keyboard.press("2")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        (new,) = set(self.pins()) - before
        pin = self.pins()[new]
        self.assertEqual((pin["verdict"], pin["page"], pin["el"]["path"]), ("보류", 2, ["B3"]))

    def test_a_confirm_word_takes_its_key_twice(self):
        """3 (삭제, a confirm word) arms the button - '삭제 확정' - and saves nothing; 3 again saves 삭제."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        self.reading(page, 2)
        page.keyboard.press("3")
        settle(page)
        self.assertEqual(self.count(), 0)
        self.assertEqual(
            page.evaluate(
                """()=>document.querySelector('#doc .pv[data-page="2"] button[data-key="삭제"] .lbl').textContent"""
            ),
            "삭제 확정",
        )
        page.keyboard.press("3")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        self.assertEqual([p["verdict"] for p in self.pins().values()], ["삭제"])

    def test_keys_rest_in_a_text_field_a_dialog_and_while_writing(self):
        """1 typed into the page field, pressed with the help open, and pressed with a selection's composer open saves
        nothing; the key hints go while the composer is open."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        self.reading(page, 2)
        page.focus("#jump")
        page.keyboard.press("1")
        settle(page)
        self.assertEqual(page.input_value("#jump"), "1")
        page.evaluate("document.querySelector('#jump').value=''; document.activeElement.blur(); openHelp()")
        settle(page)
        page.keyboard.press("1")
        settle(page)
        page.evaluate("document.querySelector('#help').close()")
        page.evaluate(
            "p=>{LAST_PTR='mouse'; pick({doc:'fig',page:2,pdf_build:META.pages_build,x0:50,y0:50,x1:300,y1:120,frac:[0.08,0.06,0.5,0.15]});}"
        )
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        page.evaluate("document.activeElement.blur()")
        settle(page)
        self.assertEqual(page.evaluate("PV_KEYS"), 0)
        self.assertEqual(page.evaluate("document.querySelectorAll('#doc .pv button[data-kn]').length"), 0)
        page.keyboard.press("1")
        settle(page)
        self.assertEqual(self.count(), 0)

    def test_a_key_right_after_a_scroll_acts_on_the_new_reading_page(self):
        """3 arms 삭제 on page 1; the area scrolls to page 2 and 3 comes before the next frame: nothing is saved - page 1's
        armed word is not confirmed - and the key arms page 2's 삭제."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        self.reading(page, 1)
        page.keyboard.press("3")
        settle(page)
        self.assertEqual(page.evaluate("VD_ARM&&VD_ARM.page"), 1)
        got = page.evaluate(
            """([s])=>{const L=document.querySelector('#left'), lr=L.getBoundingClientRect(), r=document.getElementById('p2').getBoundingClientRect();
              L.scrollTop += r.top - lr.top;   // no frame runs before the key
              const keysWere = PV_KEYS;
              document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'3',bubbles:true,cancelable:true}));
              return {armed: VD_ARM&&VD_ARM.page, keysWere};}""",
            [0],
        )
        self.assertEqual(got, {"armed": 2, "keysWere": 1})
        settle(page)
        self.assertEqual(self.count(), 0)
        label = """n=>document.querySelector('#doc .pv[data-page="'+n+'"] button[data-key="삭제"] .lbl').textContent"""
        self.assertEqual([page.evaluate(label, 1), page.evaluate(label, 2)], ["삭제", "삭제 확정"])

    def test_a_keys_armed_word_goes_when_the_reading_page_changes(self):
        """3 arms 삭제 on page 1; scrolling page 2 under the reading line lets it go - 3 then arms page 2, saving nothing."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        self.reading(page, 1)
        page.keyboard.press("3")
        settle(page)
        self.reading(page, 2)
        self.assertIsNone(page.evaluate("VD_ARM"))
        page.keyboard.press("3")
        settle(page)
        self.assertEqual((self.count(), page.evaluate("VD_ARM&&VD_ARM.page")), (0, 2))


class FigureTarget(VerdictBase):
    """On a figure document a verdict is about the figure, el.path[0] (ADR-0022): the composer saves it so and the page line
    counts legacy element verdicts so; a verdict card names its figure."""

    def element_verdict(self, key):
        """An element verdict pin (the July cell, el.path B2 > B2/calendar > B2/calendar/m07) as an older viewer saved it,
        made through the handler by Alice; its id."""
        meta = self.call("GET", "/api/meta?doc=fig")[1]
        w, h = meta["pages"][0]["pt_w"], meta["pages"][0]["pt_h"]
        x, y, dw, dh = helpers_figure.CELL_DRAG
        code, d = self.call(
            "POST",
            "/api/pick",
            {
                "doc": "fig",
                "page": 1,
                "x0": x * w,
                "y0": y * h,
                "x1": (x + dw) * w,
                "y1": (y + dh) * h,
                "frac": [x, y, x + dw, y + dh],
                "pdf_build": meta["pages_build"],
            },
        )
        self.assertEqual(code, 200, d)
        body = {k: d[k] for k in helpers_figure.SAVE_LINE if d.get(k) is not None}
        body.update(scope=d["default_level"], doc="fig", note="", verdict=key)
        self.assertEqual(body["el"]["path"][0], "B2")
        self.assertGreater(len(body["el"]["path"]), 1)
        code, out = self.call("POST", "/api/pin", body)
        self.assertEqual(code, 200, out)
        return out["id"]

    def test_the_composers_verdict_on_an_element_is_the_figures(self):
        """The July cell picked with a note, 채택 in the composer: the pin is about the figure - el.path ['B2'] - with the
        note, and page 1's line shows it. The row's lead names the figure ('· Deployment calendar 전체')."""
        page = self.on("fig")
        page.evaluate(
            "p=>{LAST_PTR='mouse'; pick({doc:'fig',page:1,pdf_build:META.pages_build,x0:p[0]*META.pages[0].pt_w,y0:p[1]*META.pages[0].pt_h,"
            "x1:(p[0]+p[2])*META.pages[0].pt_w,y1:(p[1]+p[3])*META.pages[0].pt_h,frac:p});}",
            list(helpers_figure.CELL_DRAG),
        )
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        self.assertEqual(page.evaluate("COMPOSE.current.elSel.path.length"), 3)
        # the lead names the figure whose verdict it is - the page's, whatever element of it is selected
        self.assertEqual(
            page.evaluate("document.querySelector('#c-verdict-l').textContent"),
            "판정 바로 저장 · Deployment calendar 전체",
        )
        page.fill("#note", "the July cell is off")
        page.locator('#c-verdict-row button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        (pin,) = self.pins().values()
        self.assertEqual(
            (pin["verdict"], pin["note"], pin["el"]["id"], pin["el"]["path"]),
            ("채택", "the July cell is off", "B2", ["B2"]),
        )
        self.assertEqual(page.evaluate(LINE, 1)["pin"], str(pin["id"]))

    def test_the_line_counts_an_element_verdict_as_its_figures(self):
        """An older element verdict on the July cell is page 1's verdict on its line; a newer 채택 from the line supersedes
        it - the line shows the new one with '이전 판정 1건', the element verdict's card reads '이전 판정 · #N로 대체됨'."""
        old = self.element_verdict("보류")
        page = self.on("fig", n_open=1)
        self.assertEqual(page.evaluate(LINE, 1)["pin"], str(old))
        self.assertTrue(page.evaluate(LINE, 1)["text"].startswith("판정 #%d 보류" % old))
        new = self.press_page(page, 1, "채택")
        line = page.evaluate(LINE, 1)
        self.assertEqual(line["pin"], str(new))
        self.assertIn("이전 판정 1건", line["text"])
        self.assertIn(
            "#%d" % new,
            page.evaluate("id=>document.querySelector('#list .pin.card[data-id=\"'+id+'\"] .vd-old').textContent", old),
        )

    def test_a_verdict_card_names_its_figure(self):
        """A verdict about page 1's figure names 'Deployment calendar' (its map title) on its card; one about page 2's
        'Review flow'; an older element verdict names its figure too."""
        old = self.element_verdict("보류")
        page = self.on("fig", n_open=1)
        one = self.press_page(page, 1, "채택")
        two = self.press_page(page, 2, "보류")
        name = "id=>{const e=document.querySelector('#list .pin.card[data-id=\"'+id+'\"] .tags .vd-target'); return e&&e.textContent;}"
        self.assertEqual(
            [page.evaluate(name, i) for i in (one, two, old)],
            ["Deployment calendar", "Review flow", "Deployment calendar"],
        )


class LineDetails(VerdictBase):
    """One save chip at a time, a failed save said under its line, 44px words on a phone, and pages that take no verdict."""

    def test_only_the_newest_save_chip_shows(self):
        """채택 on page 1's line, then 보류 on page 2's: one chip on the pages, on page 2's line; page 1's undo went to the
        status line, still offered, and names the figure in its title ('#N 채택 판정 저장됨 · Deployment calendar')."""
        page = self.on("fig")
        one = self.press_page(page, 1, "채택")
        self.press_page(page, 2, "보류")
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#doc .nt-chip')].map(c=>c.parentElement.dataset.page)"), ["2"]
        )
        self.assertTrue(page.evaluate("id=>LINE.some(n=>n.undo&&!!n.act&&n.title.includes('#'+id))", one))
        # ...naming the figure in its title, which the folded line shows ('#N 채택 판정 저장됨 · Deployment calendar +1')
        self.assertTrue(
            page.evaluate("id=>LINE.some(n=>n.title==='#'+id+' 채택 판정 저장됨 · Deployment calendar')", one),
            page.evaluate("LINE.map(n=>n.title)"),
        )

    def test_a_failed_save_is_said_under_the_line_that_was_pressed(self):
        """The network loses page 1's save: its line says '판정 저장 실패 — …' under its buttons, page 2's says nothing;
        the next press that saves takes it away."""
        page = self.on("fig")
        self.fail_pin = 1
        page.locator('#doc .pv[data-page="1"] button[data-key="채택"]').click()
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-err:not([hidden])')
        settle(page)
        self.assertTrue(
            page.evaluate(
                """()=>document.querySelector('#doc .pv[data-page="1"] .pv-err:not([hidden])').textContent"""
            ).startswith("판정 저장 실패 — ")
        )
        self.assertEqual(
            page.evaluate("""()=>document.querySelectorAll('#doc .pv[data-page="2"] .pv-err:not([hidden])').length"""),
            0,
        )
        self.press_page(page, 1, "채택")
        self.assertEqual(page.evaluate("""()=>document.querySelectorAll('#doc .pv .pv-err:not([hidden])').length"""), 0)

    def test_a_phones_verdict_words_are_44px_tall(self):
        """390x844: every word on a page line and in the composer's row is drawn 44px tall."""
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        heights = "sel=>[...document.querySelectorAll(sel)].map(b=>Math.round(b.getBoundingClientRect().height))"
        self.assertEqual(page.evaluate(heights, '#doc .pv[data-page="1"] button.vd-b'), [44, 44, 44])
        page.evaluate(
            "LAST_PTR='touch'; pick({doc:'fig',page:2,pdf_build:META.pages_build,x0:50,y0:50,x1:300,y1:120,frac:[0.08,0.06,0.5,0.15]})"
        )
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)
        self.assertEqual(page.evaluate(heights, "#c-verdict-row button.vd-b"), [44, 44, 44])

    def test_a_page_the_map_says_takes_no_verdict_has_no_line_and_no_composer_words(self):
        """The map marks page 2 "verdict": false: meta says so, page 2 has no line while page 1 keeps its, a selection on
        page 2 offers no verdict words (one on page 1 does), and a key there saves nothing and says '이 쪽은 판정을 받지
        않습니다' on the status line."""
        fmap = helpers_figure.viewer_map()
        fmap["pages"][1]["verdict"] = False
        helpers_figure.viewer_build(self.fig, helpers_figure.BUILD2, fmap)
        meta = self.call("GET", "/api/meta?doc=fig")[1]
        self.assertEqual([p.get("verdict") for p in meta["pages"]], [None, False])
        self.assertEqual([p.get("title") for p in meta["pages"]], ["Deployment calendar", "Review flow"])
        page = self.on("fig")
        self.assertIsNotNone(page.evaluate(LINE, 1))
        self.assertIsNone(page.evaluate(LINE, 2))
        pick2 = "LAST_PTR='mouse'; pick({doc:'fig',page:2,pdf_build:META.pages_build,x0:50,y0:50,x1:300,y1:120,frac:[0.08,0.06,0.5,0.15]})"
        page.evaluate(pick2)
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)
        self.assertTrue(page.evaluate("document.querySelector('#c-verdict-row').hidden"))
        page.keyboard.press("Escape")
        page.evaluate(
            "p=>{LAST_PTR='mouse'; pick({doc:'fig',page:1,pdf_build:META.pages_build,x0:p[0]*META.pages[0].pt_w,y0:p[1]*META.pages[0].pt_h,"
            "x1:(p[0]+p[2])*META.pages[0].pt_w,y1:(p[1]+p[3])*META.pages[0].pt_h,frac:p});}",
            list(helpers_figure.CELL_DRAG),
        )
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)
        self.assertFalse(page.evaluate("document.querySelector('#c-verdict-row').hidden"))
        page.keyboard.press("Escape")
        settle(page)
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        self.assertEqual(page.evaluate("PV_KEYS"), 0)
        page.keyboard.press("1")
        settle(page)
        self.assertEqual(self.pins(), {})
        self.assertTrue(page.evaluate("LINE.some(n=>n.title==='이 쪽은 판정을 받지 않습니다')"))


REASON = """n=>{const f=document.querySelector('#doc .pv[data-page="'+n+'"] .pv-reason');
  return f?{focused: document.activeElement===f, value: f.value, placeholder: f.placeholder}:null;}"""


class Reason(VerdictBase):
    """A reason with a verdict, in place: after a page-line save one optional line of text on that line; Enter saves it as
    the pin's note, Esc or moving on leaves the verdict alone."""

    def note(self, pid):
        return self.pins()[pid]["note"]

    def test_after_a_click_the_field_waits_and_enter_saves_the_reason(self):
        """A click on 채택: the pin is saved at once (note ''), the line offers '이유 (선택)…' without taking the focus;
        typed into and Enter, the text is the pin's note, shown on the line and on its card; the field goes."""
        page = self.on("fig")
        pid = self.press_page(page, 1, "채택")
        self.assertEqual(self.note(pid), "")
        got = page.evaluate(REASON, 1)
        self.assertEqual((got["focused"], got["placeholder"]), (False, "이유 (선택) — Enter 저장 · Esc 건너뜀"))
        page.click('#doc .pv[data-page="1"] .pv-reason')
        page.keyboard.type("축 이름이 길다")
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=pid)
        settle(page)
        self.assertEqual(self.note(pid), "축 이름이 길다")
        self.assertIsNone(page.evaluate(REASON, 1))
        self.assertEqual(
            page.evaluate("""()=>document.querySelector('#doc .pv[data-page="1"] .pv-note').textContent"""),
            "축 이름이 길다",
        )
        self.assertIn(
            "축 이름이 길다",
            page.evaluate("id=>document.querySelector('#list .pin.card[data-id=\"'+id+'\"] .note').textContent", pid),
        )

    def test_after_a_key_the_field_has_the_focus_and_digits_typed_are_text(self):
        """2 on the reading page: the field has the focus; '3번 패널 범례' typed there is text (no verdict key) and Enter saves
        it as the new pin's note."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        page.keyboard.press("2")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        self.assertTrue(page.evaluate(REASON, 2)["focused"])
        page.keyboard.type("3번 패널 범례")
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.some(p=>p.note)")
        settle(page)
        (pin,) = self.pins().values()
        self.assertEqual((pin["verdict"], pin["note"]), ("보류", "3번 패널 범례"))

    def test_esc_skips_the_reason(self):
        """1 then Esc: the field goes, the focus is on the PDF area (a Space there saves nothing), the pin has no note."""
        page = self.on("fig")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        self.assertTrue(page.evaluate(REASON, 1)["focused"])
        page.keyboard.press("Escape")
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 1))
        self.assertEqual(page.evaluate("document.activeElement.id"), "left")
        page.keyboard.press(" ")
        settle(page)
        (pin,) = self.pins().values()
        self.assertEqual(pin["note"], "")

    def test_a_confirm_word_offers_the_field_after_its_second_press(self):
        """3 arms 삭제 - no field yet; 3 again saves, and the field has the focus."""
        page = self.on("fig")
        page.keyboard.press("3")
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 1))
        page.keyboard.press("3")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        self.assertTrue(page.evaluate(REASON, 1)["focused"])

    def test_the_undo_takes_the_field_with_the_pin(self):
        """채택 clicked, a reason typed but not saved, then the chip's [되돌리기]: the pin is withdrawn and the field goes with
        it - nothing is written to the dropped pin."""
        page = self.on("fig")
        pid = self.press_page(page, 1, "채택")
        page.click('#doc .pv[data-page="1"] .pv-reason')
        page.keyboard.type("나중에")
        page.locator('#doc .pv[data-page="1"]>.nt-chip [data-act="notice-act"]').click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=pid)
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 1))
        self.assertNotIn(pid, self.pins())
        _, trash = self.call("GET", "/api/pins/dropped")
        self.assertEqual([p.get("note") for p in trash["dropped"] if p["id"] == pid], [""])

    def test_on_a_phone_the_field_waits_for_a_tap_and_stays_above_the_keyboard(self):
        """390x844: a tap on 채택 does not raise the keyboard (the field waits); tapped and the keyboard up (the layout 300px
        shorter), the field and the line's words are on screen and pressable."""
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.evaluate("setSide(false)")
        page.evaluate("setK(PT_PX*1.2,false); ZOOMED=true")
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        self.press_page(page, 2, "채택")
        self.assertFalse(page.evaluate(REASON, 2)["focused"])
        page.tap('#doc .pv[data-page="2"] .pv-reason')
        page.set_viewport_size({"width": 390, "height": 544})
        settle(page)
        self.assertTrue(page.evaluate(REASON, 2)["focused"])
        self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="2"] .pv-reason'))
        self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="2"] button[data-key="보류"]'))

    def test_a_second_save_keeps_the_first_reason_with_the_first_pin(self):
        """'첫째 이유' typed for 채택 (no Enter), then 보류 on the same line: the first text is saved as the first pin's note
        - said on the status line '이유 저장됨 · Deployment calendar' - and the field, now the second pin's, is empty; '둘째'
        and Enter go to the second pin only."""
        page = self.on("fig")
        one = self.press_page(page, 1, "채택")
        page.click('#doc .pv[data-page="1"] .pv-reason')
        page.keyboard.type("첫째 이유")
        two = self.press_page(page, 1, "보류")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=one)
        settle(page)
        self.assertEqual(page.evaluate(REASON, 1)["value"], "")
        self.assertEqual(
            page.evaluate("""()=>document.querySelector('#doc .pv[data-page="1"] .pv-reason').dataset.id"""), str(two)
        )
        self.assertTrue(page.evaluate("LINE.some(n=>n.title==='이유 저장됨 · Deployment calendar')"))
        page.click('#doc .pv[data-page="1"] .pv-reason')
        page.keyboard.type("둘째")
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=two)
        settle(page)
        self.assertEqual((self.note(one), self.note(two)), ("첫째 이유", "둘째"))

    def test_reading_another_page_closes_the_field_and_keeps_its_text(self):
        """2 on page 2 and '범례' typed: no line shows key marks while the field has the focus. Scrolled so page 1 is read:
        the field closes, '범례' is page 2's pin's note ('이유 저장됨 · Review flow'), the focus is on the PDF area and page 1's
        line has the keys."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        page.keyboard.press("2")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        page.keyboard.type("범례")
        settle(page)
        self.assertEqual(page.evaluate("document.querySelectorAll('#doc .pv button[data-kn]').length"), 0)
        page.evaluate(SCROLL, [1, "top"])
        page.wait_for_function("OPEN_ALL.some(p=>p.note)")
        settle(page)
        (pin,) = self.pins().values()
        self.assertEqual(pin["note"], "범례")
        self.assertIsNone(page.evaluate(REASON, 2))
        self.assertTrue(page.evaluate("LINE.some(n=>n.title==='이유 저장됨 · Review flow')"))
        self.assertEqual(page.evaluate("document.activeElement.id"), "left")
        self.assertEqual(
            page.evaluate("document.querySelectorAll('#doc .pv[data-page=\"1\"] button[data-kn]').length"), 3
        )

    def test_another_document_closes_the_field_and_coming_back_does_not_reopen_it(self):
        """'다른 문서로' typed (no Enter), then the PDF document and back: the text is the pin's note, and the figure's
        page 1 line has no field."""
        page = self.on("fig")
        pid = self.press_page(page, 1, "채택")
        page.click('#doc .pv[data-page="1"] .pv-reason')
        page.keyboard.type("다른 문서로")
        page.evaluate("k=>switchDoc(k)", "rv")
        page.wait_for_function("DOC==='rv'&&META&&META.doc==='rv'")
        settle(page)
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function("DOC==='fig'&&META&&META.doc==='fig'&&document.querySelector('#p1')")
        settle(page)
        self.assertEqual(self.note(pid), "다른 문서로")
        self.assertIsNone(page.evaluate(REASON, 1))

    def test_a_rebuild_keeps_the_field_and_its_text(self):
        """A reason being typed when a new build of the figure comes: the field and its text stay; Enter saves it."""
        page = self.on("fig")
        pid = self.press_page(page, 1, "채택")
        page.click('#doc .pv[data-page="1"] .pv-reason')
        page.keyboard.type("새 빌드 전")
        helpers_figure.viewer_build(self.fig, helpers_figure.BUILD2, helpers_figure.viewer_map())
        page.evaluate("refreshDoc()")
        page.wait_for_function("b=>META.pages_build===b", arg=helpers_figure.BUILD2)
        settle(page)
        self.assertEqual(page.evaluate(REASON, 1)["value"], "새 빌드 전")
        page.click('#doc .pv[data-page="1"] .pv-reason')
        page.keyboard.press("End")
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=pid)
        self.assertEqual(self.note(pid), "새 빌드 전")

    def test_where_the_keyboard_is_measured_the_line_is_not_raised_twice(self):
        """A phone browser that measures the keyboard (visualViewport: --kb 300px, the page 300px shorter) instead of
        resizing the layout: the floating line stands 4px over the sheet's bar, which rides on the keyboard, and wholly
        above the keyboard."""
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.evaluate("setSide(false)")
        page.evaluate(
            "()=>{const R=document.documentElement.style,h=document.documentElement.clientHeight; R.setProperty('--kb','300px'); R.setProperty('--vvh',(h-300)+'px');}"
        )
        settle(page)  # the PDF area 300px shorter re-fits the pages first; the zoom chosen after it stays (ZOOMED)
        page.evaluate("setK(PT_PX*1.2,false); ZOOMED=true")
        settle(page)
        page.evaluate(SCROLL, [2, "mid"])
        settle(page)
        got = page.evaluate(FLOAT, 2)
        cover = page.evaluate(
            """()=>Math.min(...[document.querySelector('#right'),document.querySelector('#status-dock')].filter(e=>e&&e.getClientRects().length&&getComputedStyle(e).position==='fixed').map(e=>e.getBoundingClientRect().top))"""
        )
        self.assertTrue(got["stuck"], got)
        self.assertAlmostEqual(got["line"]["bottom"], cover - 4, delta=1)
        self.assertLessEqual(got["line"]["bottom"], 844 - 300)

    def test_the_floating_edge_shows_in_the_light_theme(self):
        """The floating line's 1px separator is the strong border, not the PDF area's own grey."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        page.evaluate(SCROLL, [2, "mid"])
        settle(page)
        got = page.evaluate(
            """()=>{const l=document.querySelector('#doc .pv.stuck'), cs=getComputedStyle(document.documentElement);
              const probe=document.createElement('i'); probe.style.color='var(--border-strong)'; document.body.appendChild(probe);
              const c=getComputedStyle(probe).color; probe.remove(); return {shadow:getComputedStyle(l).boxShadow, strong:c, bg:getComputedStyle(document.body).backgroundColor};}"""
        )
        self.assertIn(got["strong"], got["shadow"])
        self.assertNotEqual(got["strong"], got["bg"])


class ReasonAgentRole(VerdictBase):
    """A person with the agent role makes no verdict, so no reason field either."""

    WHO = AGENT

    def test_the_agent_role_has_no_words_and_no_reason_field(self):
        """Alice's verdict on page 1: the agent-role person reads it on the line, with no word and no reason field."""
        meta = self.call("GET", "/api/meta?doc=fig")[1]
        w, h = meta["pages"][0]["pt_w"], meta["pages"][0]["pt_h"]
        code, d = self.call(
            "POST",
            "/api/pick",
            {
                "doc": "fig",
                "page": 1,
                "x0": 0,
                "y0": 0,
                "x1": w,
                "y1": h,
                "frac": [0, 0, 1, 1],
                "pdf_build": meta["pages_build"],
            },
        )
        body = {k: d[k] for k in helpers_figure.SAVE_LINE if d.get(k) is not None}
        body.update(scope=d["default_level"], doc="fig", note="", verdict="채택")
        self.assertEqual(self.call("POST", "/api/pin", body)[0], 200)
        page = self.on("fig", n_open=1)
        self.assertEqual(page.evaluate(LINE, 1)["words"], [])
        self.assertIsNone(page.evaluate(REASON, 1))
        page.keyboard.press("1")
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 1))
        self.assertEqual(len(self.pins()), 1)


def verdict_as(case, who, page_n, key, doc="fig"):
    """A verdict pin on figure page page_n's whole figure, made by who through the API (the page line's pick and body);
    its id."""
    meta = case.call("GET", "/api/meta?doc=%s" % doc)[1]
    pg = meta["pages"][page_n - 1]
    pick = {"doc": doc, "page": page_n, "x0": 0, "y0": 0, "x1": pg["pt_w"], "y1": pg["pt_h"], "frac": [0, 0, 1, 1]}
    code, d = case.call("POST", "/api/pick", {**pick, "pdf_build": meta["pages_build"]}, who)
    case.assertEqual(code, 200, d)
    body = {k: d[k] for k in helpers_figure.SAVE_LINE if d.get(k) is not None}
    body.update(scope=d["default_level"], doc=doc, note="", kind_req="fix", assignee="agent", verdict=key)
    code, made = case.call("POST", "/api/pin", body, who)
    case.assertEqual(code, 200, made)
    return made["id"]


CANCEL = '#doc .pv[data-page="%d"] button.pv-cancel'
STATUS = """()=>LINE.map(n=>({title:n.title,desc:n.desc,act:n.act?n.act.label:null,kind:n.kind}))"""


class Cancel(VerdictBase):
    """[판정 취소] on the page line (#295): a person's own open verdict is taken back where it was pressed, the line shows the
    earlier verdict as current at once (ADR-0021 D4), and the status line's [되돌리기] brings it back. Only one's own, open;
    a double press takes back one."""

    def setUp(self):
        super().setUp()
        self.held_drop: list | None = None  # POST /api/pins/N/drop routes held unanswered while not None

    def route(self, route):
        rq = route.request
        if rq.method == "POST" and urlparse(rq.url).path.endswith("/drop") and self.held_drop is not None:
            self.held_drop.append(route)
            return None
        return super().route(route)

    def test_cancel_brings_the_earlier_verdict_back_at_once_and_the_undo_restores_it(self):
        """보류 then 채택 on page 1: the line offers [판정 취소] on #채택. Pressed, the line reads the 보류 as current before the
        server answers, with its own [판정 취소]; the pin is in the Trash; the status line says '판정 #b 채택 취소됨 ·
        Deployment calendar — 지금 판정은 #a 보류입니다' with [되돌리기], which brings #b back as the current verdict."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        b = self.press_page(page, 1, "채택")
        line = page.evaluate(LINE, 1)
        self.assertEqual((line["pin"], line["cancel"]), (str(b), b))
        self.assertTrue(line["text"].startswith("판정 #%d 채택 · 처리 대기" % b), line)
        self.held_drop = []
        page.locator(CANCEL % 1).click()
        page.wait_for_function(
            "id=>document.querySelector('#doc .pv[data-page=\"1\"]').dataset.pin===String(id)", arg=a
        )
        line = page.evaluate(LINE, 1)
        self.assertEqual((line["text"], line["cancel"]), ("판정 #%d 보류 · 처리 대기" % a, a))
        page.wait_for_function("()=>document.querySelector('#doc .pv[data-page=\"1\"] .pv-cancel')")
        held, self.held_drop = self.held_drop, None
        self.assertEqual(len(held), 1)
        for r in held:
            self.forward(r)
        settle(page)
        self.assertEqual(set(self.pins()), {a})
        _, trash = self.call("GET", "/api/pins/dropped")
        self.assertIn(b, [p["id"] for p in trash["dropped"]])
        self.assertIn(
            {
                "title": "판정 #%d 채택 취소됨 · Deployment calendar" % b,
                "desc": "지금 판정은 #%d 보류입니다" % a,
                "act": "되돌리기",
                "kind": "ok",
            },
            page.evaluate(STATUS),
        )
        page.locator("#status [data-act=notice-act]").filter(has_text="되돌리기").click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id)", arg=b)
        settle(page)
        line = page.evaluate(LINE, 1)
        self.assertEqual((line["pin"], line["cancel"]), (str(b), b))
        self.assertEqual(set(self.pins()), {a, b})

    def test_the_last_verdict_cancelled_leaves_no_verdict_and_says_so(self):
        """One verdict on page 2, taken back: the line reads '판정 없음' and the status line says no verdict is left."""
        page = self.on("fig")
        a = self.press_page(page, 2, "채택")
        page.locator(CANCEL % 2).click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=a)
        settle(page)
        line = page.evaluate(LINE, 2)
        self.assertEqual((line["text"], line["cancel"], line["pin"]), ("판정 없음", None, None))
        self.assertTrue(
            page.evaluate(
                "id=>LINE.some(n=>n.title==='판정 #'+id+' 채택 취소됨 · Review flow'&&n.desc==='남은 판정이 없습니다')",
                a,
            )
        )

    def test_only_ones_own_open_verdict_offers_it(self):
        """Bob's newer verdict on page 1: no [판정 취소]. On page 2 Alice's own verdict claimed by an agent still offers it,
        and taking it back says its run may have started; one the agent has closed (검토 대기) offers none."""
        page = self.on("fig")
        self.press_page(page, 1, "보류")
        verdict_as(self, BOB, 1, "채택")
        self.reload(page)
        self.assertEqual(page.evaluate(LINE, 1)["cancel"], None)
        c = self.press_page(page, 2, "채택")
        self.assertEqual(self.call("POST", "/api/pins/%d/claim" % c, {}, AGENT)[0], 200)
        self.reload(page)
        self.assertEqual(page.evaluate(LINE, 2)["cancel"], c)
        page.locator(CANCEL % 2).click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=c)
        settle(page)
        self.assertTrue(page.evaluate("LINE.some(n=>n.title==='처리 중이던 판정이라 이미 실행됐을 수 있습니다')"))
        d = self.press_page(page, 2, "보류")
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % d, {"reply": "done"}, AGENT)[0], 200)
        self.reload(page)
        line = page.evaluate(LINE, 2)
        self.assertEqual((line["text"], line["cancel"]), ("판정 #%d 보류 · 검토 대기" % d, None))

    def test_a_double_press_takes_back_one_verdict(self):
        """Two of Alice's verdicts on page 1 and a double click on [판정 취소]: only the newer goes; the earlier one's
        [판정 취소], now under the pointer, waits out the second click and takes it back only when pressed again."""
        page = self.on("fig")
        a = self.press_page(page, 1, "보류")
        b = self.press_page(page, 1, "채택")
        page.locator(CANCEL % 1).dblclick()
        settle(page)
        self.assertEqual(set(self.pins()), {a})
        line = page.evaluate(LINE, 1)
        self.assertEqual((line["pin"], line["cancel"]), (str(a), a))
        self.assertIsNone(page.locator(CANCEL % 1).get_attribute("aria-disabled"))
        page.locator(CANCEL % 1).click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=a)
        settle(page)
        self.assertEqual(self.pins(), {})
        self.assertEqual(page.evaluate(LINE, 1)["text"], "판정 없음")
        self.assertNotIn(b, self.pins())

    def test_a_failed_cancel_puts_the_verdict_back_on_the_line(self):
        """The drop lost on the network: the line shows the verdict again, the status line says '판정 취소 실패' with
        [다시 시도], which takes it back."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        page.route("**/api/pins/%d/drop" % a, lambda r: r.abort())
        page.locator(CANCEL % 1).click()
        page.wait_for_function("()=>LINE.some(n=>n.title==='판정 취소 실패')")
        settle(page)
        line = page.evaluate(LINE, 1)
        self.assertEqual((line["pin"], line["cancel"]), (str(a), a))
        page.unroute("**/api/pins/%d/drop" % a)
        page.locator("#status [data-act=notice-act]").filter(has_text="다시 시도").click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=a)
        settle(page)
        self.assertEqual(self.pins(), {})

    def test_the_card_of_a_verdict_calls_its_delete_지우기(self):
        """A verdict pin's card names its [삭제] '지우기' - the word file's '삭제' is a verdict - with a description that says
        the earlier verdict comes back; an ordinary card keeps [삭제]. In the wide panel the name keeps one line in its cell;
        in the compact one the icon carries it (the name in aria-label)."""
        page = self.on("fig")
        v = self.press_page(page, 1, "보류")
        self.open_composer(page)
        page.fill("#note", "보통 핀")
        page.locator("#btn-save").click()
        page.wait_for_function("OPEN_ALL.length===2")
        settle(page)
        (plain,) = set(self.pins()) - {v}
        drop = """id=>{const b=document.querySelector('.pin[data-id="'+id+'"] [data-act=drop]'), l=b.querySelector('.lbl'), r=l.getBoundingClientRect();
          return {label:l.textContent, name:b.getAttribute('aria-label'), tip:b.dataset.tip, fits:b.scrollWidth<=b.clientWidth+0.5,
            one:r.height<parseFloat(getComputedStyle(l).lineHeight)*1.5, shown:getComputedStyle(l).display!=='none'};}"""
        got = page.evaluate(drop, v)
        self.assertEqual(
            (got["label"], got["name"], got["shown"], got["fits"], got["one"]), ("지우기", "지우기", True, True, True)
        )
        self.assertIn("앞선 판정이 있으면 그 판정이 다시 지금 판정이 됩니다", got["tip"])
        self.assertEqual(page.evaluate(drop, plain)["label"], "삭제")
        phone = self.on("fig", n_open=2, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        phone.evaluate("id=>{setSide(true); OPEN_CARDS.add(id); drawPins();}", v)
        settle(phone)
        got = phone.evaluate(drop, v)
        self.assertEqual((got["name"], got["shown"]), ("지우기", False))

    def test_a_phones_floating_line_holds_the_cancel_back_and_the_in_place_line_offers_it(self):
        """390x844 touch, page 2 taller than the area and Alice's verdict on it: while its line floats it has no
        [판정 취소] (the line is no taller than without it); scrolled until the line stands in its place under the page, it
        offers it with its 44px. Near that point the line does not flip between the two. At 1400 the floating line keeps
        it."""
        cancel_shown = """n=>{const c=document.querySelector('#doc .pv[data-page="'+n+'"] .pv-cancel'); if(!c)return null;
          const b=c.getBoundingClientRect(); return c.getClientRects().length?{h:b.height}:false;}"""
        phone = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        phone.evaluate("setSide(false)")
        phone.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        phone.evaluate(SCROLL, [2, "top"])
        settle(phone)
        self.press_page(phone, 2, "채택")
        phone.evaluate(END_CHIPS)
        phone.evaluate("()=>{PV_REASON=null; drawPageVerdicts();}")  # the reason field closed: the line as it rests
        phone.evaluate(SCROLL, [2, "mid"])
        settle(phone)
        self.assertTrue(phone.evaluate(FLOAT, 2)["stuck"])
        self.assertIs(phone.evaluate(cancel_shown, 2), False)
        # in its place: page 2's end 300px under the area's top
        phone.evaluate(
            """()=>{const L=document.querySelector('#left'),r=document.getElementById('p2').getBoundingClientRect();
              L.scrollTop+=r.bottom-(L.getBoundingClientRect().top+300);}"""
        )
        settle(phone)
        self.assertFalse(phone.evaluate(FLOAT, 2)["stuck"])
        got = phone.evaluate(cancel_shown, 2)
        self.assertTrue(got and got["h"] >= 44, got)
        # Scrolled back through the page's end in 8px steps: one more pass settles it (no flip-flop), and whether the
        # cancel shows never flips back at one position (only whether the shorter line still floats may follow).
        states = phone.evaluate(
            """()=>{const L=document.querySelector('#left'),l=document.querySelector('#doc .pv[data-page="2"]'),out=[];
              const st=()=>[l.classList.contains('stuck'),l.classList.contains('pv-lean')];
              for(let i=0;i<120;i++){L.scrollTop-=8; pvStick(); const a=st(); pvStick(); const b=st(); pvStick(); out.push([a,b,st()]);}
              return out;}"""
        )
        self.assertTrue(all(b == c and a[1] == c[1] for a, b, c in states), states)
        self.assertEqual(states[-1][2], [True, True])
        desk = self.on("fig", n_open=1)
        desk.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        desk.evaluate(SCROLL, [2, "mid"])
        settle(desk)
        self.assertTrue(desk.evaluate(FLOAT, 2)["stuck"])
        self.assertTrue(desk.evaluate(cancel_shown, 2))

    def test_the_cancel_reads_as_a_muted_destructive_action_not_a_link(self):
        """[판정 취소] is neither the blue of the '#N' link and the earlier link nor bolder than the line's text; its colour
        leans to the danger hue and holds 4.5:1 on the line in both themes; it underlines only on hover."""
        page = self.on("fig")
        self.press_page(page, 1, "보류")
        self.press_page(page, 1, "채택")
        page.evaluate(END_CHIPS)
        settle(page)
        look = """()=>{const l=document.querySelector('#doc .pv[data-page="1"]'),c=l.querySelector('.pv-cancel'),cs=e=>getComputedStyle(e);
          const rgb=s=>{const v=s.match(/[\\d.]+/g).slice(0,3).map(Number); return s.startsWith('color(')?v.map(x=>x*255):v;}, lum=a=>{const f=v=>{v/=255; return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);};
            const [r,g,b]=a.map(f); return 0.2126*r+0.7152*g+0.0722*b;};
          let bg=l; while(bg&&cs(bg).backgroundColor.replace(/\\s/g,'').match(/rgba\\(.*,0\\)$|transparent/))bg=bg.parentElement;
          const fg=rgb(cs(c).color),bk=rgb(cs(bg).backgroundColor),L1=lum(fg),L2=lum(bk);
          return {color:cs(c).color, ref:cs(l.querySelector('.pv-ref')).color, early:cs(l.querySelector('.pv-early')).color,
            weight:cs(c).fontWeight, text:cs(l.querySelector('.pv-st')).fontWeight, line:cs(c).textDecorationLine,
            red:fg[0]>fg[2], ratio:(Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05)};}"""
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page.evaluate("t=>setTheme(t)", theme)
                settle(page)
                got = page.evaluate(look)
                self.assertNotEqual(got["color"], got["ref"])
                self.assertNotEqual(got["color"], got["early"])
                self.assertEqual(got["weight"], got["text"])
                self.assertTrue(got["red"], got)
                self.assertGreaterEqual(got["ratio"], 4.5, got)
                self.assertEqual(got["line"], "none")
        page.hover('#doc .pv[data-page="1"] .pv-cancel')
        self.assertEqual(
            page.evaluate(
                "getComputedStyle(document.querySelector('#doc .pv[data-page=\"1\"] .pv-cancel')).textDecorationLine"
            ),
            "underline",
        )

    def test_the_cancels_description_waits_for_the_save_chip_too(self):
        """Right after a save the line's [판정 취소] has no description either (its box stood over the chip); it has one
        again once the chip goes."""
        page = self.on("fig")
        self.press_page(page, 1, "채택")
        tip = "()=>document.querySelector('#doc .pv[data-page=\"1\"] .pv-cancel').getAttribute('data-tip')"
        self.assertIsNone(page.evaluate(tip))
        page.evaluate(END_CHIPS)
        settle(page)
        self.assertTrue(page.evaluate(tip))


class CancelAgentRole(VerdictBase):
    """A person whose role is now agent has no [판정 취소], even on a verdict they made before (D16: the server refuses an
    agent's drop of a verdict pin)."""

    def test_the_agent_role_is_offered_no_cancel_on_its_own_old_verdict(self):
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        self.assertEqual(page.evaluate(LINE, 1)["cancel"], a)
        member_set_role(ps.APP.C.state, ALICE["Tailscale-User-Login"], "agent")
        page = self.on("fig", n_open=1)
        line = page.evaluate(LINE, 1)
        self.assertEqual((line["pin"], line["cancel"], line["words"]), (str(a), None, []))
        self.assertEqual(page.evaluate("document.querySelectorAll('#doc .pv-cancel').length"), 0)


class TipAfterSave(VerdictBase):
    """No description box over a line's save chip (#295): while the chip stands the line's words hold their descriptions
    back, so neither the press's own focus, a resting hand's slight move nor anything that hides the box meanwhile brings
    one over the chip; the descriptions come back with the chip's leaving."""

    def test_no_box_over_the_save_chip_and_the_descriptions_come_back_after_it(self):
        page = self.on("fig")
        btn = '#doc .pv[data-page="1"] button[data-key="채택"]'
        page.hover(btn)
        page.wait_for_function("()=>!document.querySelector('#tip').hidden")  # the box shows on hover before the press
        self.press_page(page, 1, "채택")
        nothing_follows(page, 500)  # the click's focus armed the box for 300ms
        self.assertTrue(page.evaluate("document.querySelector('#tip').hidden"))
        self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="1"]>.nt-chip [data-act="notice-act"]'))
        self.assertEqual(page.evaluate(LINE, 1)["tips"], [None, None, None])
        box = page.locator(btn).bounding_box()
        page.mouse.move(
            box["x"] + box["width"] / 2 + 3, box["y"] + box["height"] / 2 + 1
        )  # a rest on the button moves a little
        nothing_follows(page, 500)
        self.assertTrue(page.evaluate("document.querySelector('#tip').hidden"))
        # Whatever hides the box meanwhile (a scroll anywhere, a redraw) does not let the next small move bring it back,
        # nor does a move to the next word, whose box would stand over the chip too.
        page.evaluate("()=>{document.querySelector('#left').dispatchEvent(new Event('scroll')); drawPageVerdicts();}")
        page.mouse.move(box["x"] + 6, box["y"] + box["height"] / 2)
        page.hover('#doc .pv[data-page="1"] button[data-key="보류"]')
        nothing_follows(page, 500)
        self.assertTrue(page.evaluate("document.querySelector('#tip').hidden"))
        page.evaluate(END_CHIPS)
        settle(page)
        self.assertTrue(
            all(t and t.startswith("누르면 이 쪽에 새 판정 핀을 저장합니다") for t in page.evaluate(LINE, 1)["tips"])
        )
        page.mouse.move(box["x"] - 200, box["y"] - 200)
        page.hover(btn)
        page.wait_for_function("()=>!document.querySelector('#tip').hidden")


class _Swallowed:
    """A route whose answer the browser never gets: forward() writes through the handler, then the test aborts it."""

    def __init__(self, route):
        self.request = route.request

    def fulfill(self, **_):
        return None


class ReasonRaces(VerdictBase):
    """The reason field's rare orders (#294, and the review of PR #298): a document with no page lines, moving on while
    Enter's write is out, a write that fails on moving on, an answer lost after the server wrote it, a corrected draft
    after a failed Enter, and a cancel while the reason is unsent or on its way."""

    def setUp(self):
        super().setUp()
        self.edits: list = []  # every POST /api/pins/N/edit body the viewer sent
        self.held_edit: list | None = None  # those held unanswered while not None
        self.lose_edit = 0  # how many to lose on the network before the server sees them
        self.lose_answer = 0  # how many the server writes whose answer is lost on the way back
        self.refuse_edit = 0  # how many to answer 400
        self.lose_drop = 0  # how many POST /api/pins/N/drop to lose on the network

    def route(self, route):
        rq = route.request
        path = urlparse(rq.url).path
        if rq.method == "POST" and path.startswith("/api/pins/") and path.endswith("/drop") and self.lose_drop:
            self.lose_drop -= 1
            return route.abort()
        if rq.method == "POST" and path.startswith("/api/pins/") and path.endswith("/edit"):
            self.edits.append(json.loads(rq.post_data or "{}"))
            if self.lose_edit:
                self.lose_edit -= 1
                return route.abort()
            if self.lose_answer:
                self.lose_answer -= 1
                self.forward(_Swallowed(route))
                return route.abort()
            if self.refuse_edit:
                self.refuse_edit -= 1
                return route.fulfill(
                    status=400, headers={"content-type": "application/json"}, body='{"error": "안 됩니다"}'
                )
            if self.held_edit is not None:
                self.held_edit.append(route)
                return None
        return super().route(route)

    def note(self, pid):
        return self.pins()[pid]["note"]

    def typed(self, page, n, text):
        """The page's verdict saved by a click on 채택 and text typed into its reason field; the pin's id."""
        pid = self.press_page(page, n, "채택")
        page.click('#doc .pv[data-page="%d"] .pv-reason' % n)
        page.keyboard.type(text)
        return pid

    def test_a_document_without_page_lines_closes_the_field_and_keeps_its_text(self):
        """'원고로 간다' typed (no Enter), then the LaTeX manuscript, which has no page lines: the text is the pin's note,
        said on the status line, and coming back the field is gone."""
        page = self.on("fig")
        pid = self.typed(page, 1, "원고로 간다")
        page.evaluate("k=>switchDoc(k)", "ms")
        page.wait_for_function("DOC==='ms'&&META&&META.doc==='ms'")
        settle(page)
        self.assertEqual(self.note(pid), "원고로 간다")
        self.assertIsNone(page.evaluate("PV_REASON"))
        self.assertTrue(page.evaluate("id=>LINE.some(n=>n.title==='이유 저장됨 · #'+id)", pid))
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function("DOC==='fig'&&META&&META.doc==='fig'&&document.querySelector('#p1')")
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 1))

    def test_moving_on_while_enter_is_out_writes_the_reason_once(self):
        """Enter, and before its answer the person moves on - another document, another verdict on the line, the reading
        page leaving: one edit is sent, and the note is the reason once."""
        for case in ("another document", "another verdict", "another page"):
            with self.subTest(case=case):
                self.edits = []
                page = self.on("fig")
                if case == "another page":
                    page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
                    page.evaluate(SCROLL, [2, "top"])
                    settle(page)
                n = 2 if case == "another page" else 1
                pid = self.typed(page, n, "한 번만")
                self.held_edit = []
                page.keyboard.press("Enter")
                page.wait_for_function(
                    "()=>window.__limnIdle&&document.querySelector('#doc .pv-reason')&&document.querySelector('#doc .pv-reason').disabled"
                )
                if case == "another document":
                    page.evaluate("k=>switchDoc(k)", "rv")
                    page.wait_for_function("DOC==='rv'&&META&&META.doc==='rv'")
                elif case == "another verdict":
                    page.locator('#doc .pv[data-page="1"] button[data-key="보류"]').click()
                    page.wait_for_function("id=>OPEN_ALL.some(p=>p.id>id)", arg=pid, timeout=10000)
                else:
                    page.evaluate(SCROLL, [1, "top"])
                    page.wait_for_function("()=>PV_REASON===null")
                page.wait_for_timeout(200)  # anything the move-on would send has been sent (held)
                held, self.held_edit = self.held_edit, None
                self.assertEqual(len(held), 1, self.edits)
                for r in held:
                    self.forward(r)
                settle(page)
                self.assertEqual(len(self.edits), 1, self.edits)
                self.assertEqual(self.note(pid), "한 번만")
                for p in list(self.pins()):
                    self.call("POST", "/api/pins/%d/drop" % p, {})

    def test_a_failed_save_on_moving_on_keeps_the_text_for_a_retry(self):
        """The edit lost on the network as the person moves on (another document): the note stays empty, and the status
        line says '이유 저장 실패 · #N — 서버에 닿지 않습니다' with [다시 시도]; pressed with the network back, the reason is the
        note and the status line says it was saved. A refusal (400) says so without [다시 시도]."""
        page = self.on("fig")
        pid = self.typed(page, 1, "다시 보낼 이유")
        self.lose_edit = 1
        page.evaluate("k=>switchDoc(k)", "ms")
        page.wait_for_function("DOC==='ms'&&META&&META.doc==='ms'")
        settle(page)
        self.assertEqual(self.note(pid), "")
        self.assertIn(
            {"title": "이유 저장 실패 · #%d" % pid, "desc": "서버에 닿지 않습니다", "act": "다시 시도", "kind": "err"},
            page.evaluate(STATUS),
        )
        page.locator("#status [data-act=notice-act]").filter(has_text="다시 시도").click()
        page.wait_for_function("id=>LINE.some(n=>n.title==='이유 저장됨 · #'+id)", arg=pid)
        settle(page)
        self.assertEqual(self.note(pid), "다시 보낼 이유")
        self.assertFalse(page.evaluate("LINE.some(n=>n.title.startsWith('이유 저장 실패'))"))
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function("DOC==='fig'&&META&&META.doc==='fig'&&document.querySelector('#p1')")
        settle(page)
        other = self.typed(page, 2, "거절될 이유")
        self.refuse_edit = 1
        page.evaluate("k=>switchDoc(k)", "ms")
        page.wait_for_function("DOC==='ms'&&META&&META.doc==='ms'")
        settle(page)
        self.assertIn(
            {"title": "이유 저장 실패 · #%d" % other, "desc": "안 됩니다", "act": None, "kind": "err"},
            page.evaluate(STATUS),
        )

    def test_a_failed_enter_keeps_the_text_in_the_field(self):
        """Enter lost on the network: the field is open again with the text and the focus, the status line says the
        failure; Enter again saves it once."""
        page = self.on("fig")
        pid = self.typed(page, 1, "엔터 실패")
        self.lose_edit = 1
        page.keyboard.press("Enter")
        page.wait_for_function("()=>LINE.some(n=>n.title.startsWith('이유 저장 실패'))")
        settle(page)
        got = page.evaluate(REASON, 1)
        self.assertEqual((got["value"], got["focused"]), ("엔터 실패", True))
        self.assertFalse(page.evaluate("document.querySelector('#doc .pv-reason').disabled"))
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=pid)
        settle(page)
        self.assertEqual(self.note(pid), "엔터 실패")
        self.assertIsNone(page.evaluate(REASON, 1))

    def retry(self, page):
        """Press the status line's [다시 시도]."""
        page.locator("#status [data-act=notice-act]").filter(has_text="다시 시도").click()

    def test_an_answer_lost_after_the_server_wrote_the_reason_is_not_written_twice(self):
        """The reason written on moving on, its answer lost: the status line offers [다시 시도]; pressed, the pin is read
        again, holds the reason already, and nothing is sent - the note is the reason once, and it is said as saved."""
        page = self.on("fig")
        pid = self.typed(page, 1, "한 번 쓴 이유")
        self.lose_answer = 1
        page.evaluate("k=>switchDoc(k)", "ms")
        page.wait_for_function("()=>LINE.some(n=>n.title.startsWith('이유 저장 실패'))")
        settle(page)
        self.assertEqual(self.note(pid), "한 번 쓴 이유")  # the server has it
        self.retry(page)
        page.wait_for_function("id=>LINE.some(n=>n.title==='이유 저장됨 · #'+id)", arg=pid)
        settle(page)
        self.assertEqual(len(self.edits), 1, self.edits)
        self.assertEqual(self.note(pid), "한 번 쓴 이유")

    def test_a_lost_answer_under_someones_note_and_a_rev_conflict_append_nothing_twice(self):
        """Bob's note on the pin first, then the reason appended on moving on with its answer lost, then Bob edits again (a
        new rev): [다시 시도] finds '(추가 HH:MM) 이유' already there and sends nothing."""
        page = self.on("fig")
        pid = self.typed(page, 1, "덧붙인 이유")
        rev = self.pins()[pid]["rev"]
        self.assertEqual(
            self.call("POST", "/api/pins/%d/edit" % pid, {"note": "밥의 메모", "base_rev": rev}, BOB)[0], 200
        )
        self.reload(page)  # the viewer knows Bob's note: the reason goes under it (note_append)
        self.lose_answer = 1
        page.evaluate("k=>switchDoc(k)", "ms")
        page.wait_for_function("()=>LINE.some(n=>n.title.startsWith('이유 저장 실패'))")
        settle(page)
        self.assertEqual(self.call("POST", "/api/pins/%d/edit" % pid, {"note_append": "밥이 또"}, BOB)[0], 200)
        self.retry(page)
        page.wait_for_function("id=>LINE.some(n=>n.title==='이유 저장됨 · #'+id)", arg=pid)
        settle(page)
        note = self.note(pid)
        self.assertEqual(note.count("덧붙인 이유"), 1, note)
        self.assertEqual(len(self.edits), 1, self.edits)

    def test_after_a_failed_enter_the_retry_saves_the_corrected_draft(self):
        """Enter lost on the network; the field stays, and the person corrects it. The status line's [다시 시도] writes the
        draft as it is now - the field waits (disabled) while it does - and the field closes with that text saved."""
        page = self.on("fig")
        pid = self.typed(page, 1, "첫 글")
        self.lose_edit = 1
        page.keyboard.press("Enter")
        page.wait_for_function("()=>LINE.some(n=>n.title.startsWith('이유 저장 실패'))")
        settle(page)
        page.fill('#doc .pv[data-page="1"] .pv-reason', "고친 글")
        self.held_edit = []
        self.retry(page)
        page.wait_for_function(
            "()=>document.querySelector('#doc .pv-reason')&&document.querySelector('#doc .pv-reason').disabled"
        )
        page.wait_for_timeout(200)
        held, self.held_edit = self.held_edit, None
        for r in held:
            self.forward(r)
        settle(page)
        self.assertEqual(self.note(pid), "고친 글")
        self.assertIsNone(page.evaluate(REASON, 1))

    def test_a_corrected_draft_replaces_the_first_one_whose_answer_was_lost(self):
        """Enter written but its answer lost; the field stays and is corrected; Enter again: the pin is read, its note is
        the first draft from this session, and the corrected one takes its place - one reason, not two."""
        page = self.on("fig")
        pid = self.typed(page, 1, "오타 있는 글")
        self.lose_answer = 1
        page.keyboard.press("Enter")
        page.wait_for_function("()=>LINE.some(n=>n.title.startsWith('이유 저장 실패'))")
        settle(page)
        self.assertEqual(self.note(pid), "오타 있는 글")
        page.fill('#doc .pv[data-page="1"] .pv-reason', "고친 글")
        page.keyboard.press("Enter")
        page.wait_for_function("()=>!document.querySelector('#doc .pv-reason')")
        settle(page)
        self.assertEqual(self.note(pid), "고친 글")

    def test_a_failed_cancel_brings_back_the_unsent_reason(self):
        """'보내지 않은 이유' typed (no Enter), then [판정 취소] lost on the network: the verdict is back on the line and so is
        its field, with the text."""
        page = self.on("fig")
        pid = self.typed(page, 1, "보내지 않은 이유")
        self.lose_drop = 1
        page.locator(CANCEL % 1).click()
        page.wait_for_function("()=>LINE.some(n=>n.title==='판정 취소 실패')")
        settle(page)
        self.assertEqual(page.evaluate(LINE, 1)["pin"], str(pid))
        self.assertEqual(page.evaluate(REASON, 1)["value"], "보내지 않은 이유")
        self.assertEqual(self.edits, [])

    def test_cancelling_while_the_reason_is_on_its_way_says_nothing_of_it(self):
        """Enter, and [판정 취소] before the edit reaches the server: the edit then finds the pin gone, and the status line
        says the cancel only - no '이유 저장 실패'."""
        page = self.on("fig")
        pid = self.typed(page, 1, "가는 중")
        self.held_edit = []
        page.keyboard.press("Enter")
        page.wait_for_function(
            "()=>document.querySelector('#doc .pv-reason')&&document.querySelector('#doc .pv-reason').disabled"
        )
        page.locator(CANCEL % 1).click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=pid)
        page.wait_for_timeout(200)
        held, self.held_edit = self.held_edit, None
        for r in held:
            self.forward(r)
        settle(page)
        titles = [n["title"] for n in page.evaluate(STATUS)]
        self.assertFalse([t for t in titles if t.startswith("이유 저장 실패") or "지워졌습니다" in t], titles)
        self.assertIn("판정 #%d 채택 취소됨 · Deployment calendar" % pid, titles)
