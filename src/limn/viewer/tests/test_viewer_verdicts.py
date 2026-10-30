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
# The text of page n's line (its state, without [판정 취소], [이유 추가] or a draft's mark and the dot before them), its
# buttons' words, the [판정 취소] it offers
# (the pin it takes back, or null), and whether its line is there at all.
LINE = """n => {const l = document.querySelector('#doc .pv[data-page="' + n + '"]'); if (!l) return null;
  const t = [...l.querySelector('.pv-t').childNodes].filter(n => !(n.classList && (n.classList.contains('pv-cn') || n.classList.contains('pv-un') || n.classList.contains('pv-ra')))).map(n => n.textContent).join(' ');
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
        drawn and [보기] goes to the line; another word is a new pin, which the line now shows, with the earlier one as
        '이전 판정 1건 · 새 판정으로 대체됨' and no page-size mark either - the line accounts for both. Page 2 has none. The line
        reads '판정 #N 채택 · 처리 대기'; its current word is pressed and says a press takes it back, the others that a press
        saves them as the page's verdict."""
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
        self.assertEqual(
            line["tips"],
            [
                "지금 판정입니다 · 다시 누르면 이 판정을 거둡니다(판정 취소)",
                "누르면 이 쪽의 판정으로 저장합니다 · 다시 누르면 거둡니다",
                "누르면 이 쪽의 판정으로 저장합니다 · 다시 누르면 거둡니다",
            ],
        )
        self.assertEqual(page.locator('.mark[data-pin="%d"]' % first).count(), 0)
        self.assertIn("판정 없음", page.evaluate(LINE, 2)["text"])
        second = self.press_page(page, 1, "보류")
        line = page.evaluate(LINE, 1)
        self.assertEqual(line["pin"], str(second))
        self.assertEqual(line["text"], "판정 #%d 보류 · 처리 대기 이전 판정 1건 · 새 판정으로 대체됨" % second)
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
        """Enter on a page line's word saves it, opening no popover; the focus goes to the line's way to the reason ('Enter 이유
        쓰기' - Enter on the now pressed word would take it back), and Enter there opens it - unless the person moved the
        focus meanwhile."""
        page = self.on("fig")
        btn = '#doc .pv[data-page="1"] button[data-key="채택"]'
        page.focus(btn)
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 1))
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-reason-open"])
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop .pv-reason')
        page.keyboard.press("Escape")
        settle(page)
        page.focus('#doc .pv[data-page="1"] button[data-key="보류"]')  # 채택 is pressed now: Enter there takes it back
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
        """390x844: a line too narrow for a verdict's state beside its words is stacked whatever it shows - '판정 없음' too - so
        a press that brings a longer state never stacks it under the finger (RC review: a phone's line went 44 -> 131px and its
        words moved). The decision stays per line (P2-7 of the 0.4.33 review: one long line stacked every page's): the desktop
        keeps a long state on one row on its wide page."""
        rows = """()=>[...document.querySelectorAll('#doc .pv')].map(l=>{const t=l.querySelector('.pv-t').getBoundingClientRect(),
          b=l.querySelector('.vd-btns').getBoundingClientRect(),L=l.getBoundingClientRect();
          return {below: b.top>=t.bottom-1, start: Math.abs(b.left-L.left)<=1, stack: l.classList.contains('pv-stack'), h: L.height};})"""
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        before = page.evaluate(rows)
        self.assertEqual([(r["below"], r["stack"]) for r in before], [(True, True)] * 2)
        self.press_page(page, 2, "보류")
        got = page.evaluate(rows)
        self.assertEqual(
            {k: got[1][k] for k in ("below", "start", "stack")}, {"below": True, "start": True, "stack": True}
        )
        self.assertFalse(page.evaluate("document.querySelector('#doc').classList.contains('pv-stack')"))
        page = self.on("fig", n_open=1)
        self.press_page(page, 1, "보류")
        self.press_page(page, 1, "채택")
        page.evaluate(END_CHIPS)
        page.evaluate("()=>{PV_REASON=null; drawPageVerdicts();}")  # no reason popover: the row alone
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
        for n, target, word in (
            (2, '#doc .pv[data-page="2"] button[data-key="보류"]', "보류"),
            (3, '#doc .pv[data-page="1"] .pv-ref', "채택"),  # a word that is not current: the current one is taken back
        ):
            with self.subTest(target=target):
                one = '#doc .pv[data-page="1"] button[data-key="%s"]' % word
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
        page.evaluate(
            "id=>verdictUndo(id)()", b
        )  # undo b's save - what its chip's (or the status line's) [되돌리기] runs
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
            for size, more, word in (
                ((1440, 900), {}, "보류"),
                (
                    (390, 844),
                    {"is_mobile": True, "has_touch": True},
                    "채택",
                ),  # 보류 is current now: it would be taken back
            ):
                with self.subTest(doc=doc, size=size):
                    n = len(self.pins())
                    page = self.on(doc, n_open=n, viewport={"width": size[0], "height": size[1]}, **more)
                    self.press_page(page, 1, word)

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
        """A page with a verdict: Enter on 채택, and while its save runs the focus is still on that button (its presses are
        taken - the last one is applied after the save - so it is neither disabled nor waiting); Tab moves it to the next
        word. Then Enter on 보류 and, during the save, the focus goes to the '#N' link: the save renumbers the link, and the
        focus stays on it."""
        page = self.on("fig")
        self.press_page(page, 1, "보류")
        one = '#doc .pv[data-page="1"] button[data-key="채택"]'
        page.focus(one)
        self.held = []
        page.keyboard.press("Enter")
        page.wait_for_function("PV_BUSY.size===1")
        self.assertTrue(page.evaluate("s=>document.activeElement===document.querySelector(s)", one))
        self.assertIsNone(page.evaluate("s=>document.querySelector(s).getAttribute('aria-disabled')", one))
        page.keyboard.press("Tab")
        self.release()
        page.wait_for_function("PV_BUSY.size===0&&OPEN_ALL.length===2")
        settle(page)
        self.assertEqual(
            page.evaluate("[document.activeElement.dataset.act, document.activeElement.dataset.key]"),
            ["pv-save", "보류"],
        )
        page.focus('#doc .pv[data-page="1"] button[data-key="보류"]')  # 채택 is pressed now: Enter there takes it back
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
        self.assertIn(  # its text - shown where the room holds it (pvChipPlace), else folded to [되돌리기]
            "#%d 저장됨 · 보류" % a,
            page.evaluate("document.querySelector('#doc .pv[data-page=\"1\"] .nt-chip').textContent"),
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
        self.assertAlmostEqual(got["line"]["bottom"], cover - page.evaluate(TOUCH_GAP), delta=1)
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
FOLD_PORTRAIT = {"viewport": {"width": 882, "height": 1104}, "is_mobile": True, "has_touch": True}
# How far a floating line stands over what covers the PDF area's bottom on touch: 4px - over the status line's whole 44px
# reach while it shows (its [x] and its action answer 44px up from the sheet's top edge).
TOUCH_GAP = "()=>{const d=document.querySelector('#status-dock'); return d&&d.getClientRects().length?44-d.getBoundingClientRect().height+4:4;}"
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
        # no other line stacks for this one's sake: a stacked line is one narrower than a verdict's state beside its words
        self.assertEqual(
            page.evaluate(
                """()=>[...document.querySelectorAll('#doc .pv.pv-stack')].filter(l=>l.getBoundingClientRect().width>=l.querySelector('.vd-btns').getBoundingClientRect().width+pvStateNeed(l)+24).length"""
            ),
            0,
        )

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
        """The save chip lies over its line in room no control or state word takes - never over the figure's identifier,
        the current verdict and its state, a text action or a word - folding its words, then its icon, where the room is
        short; with no room for [되돌리기] the undo is on the status line. Rows narrower and narrower (review of #302 and the
        RC review: the chip hid the current verdict, then [이유 추가] and [판정 취소])."""
        page = self.on("fig", viewport={"width": 1920, "height": 1080})
        page.evaluate("setK(PT_PX*2,false); ZOOMED=true")  # a line wide enough for the chip with its words
        settle(page)
        self.press_page(page, 1, "보류")
        self.press_page(page, 1, "채택")
        geom = """w=>{const l=document.querySelector('#doc .pv[data-page="1"]'); if(w){l.style.width=w+'px'; pvFit([l]);}
          const c=l.querySelector(':scope>.nt-chip'),b=e=>e.getBoundingClientRect(),v=e=>!!e&&e.getClientRects().length>0;
          if(!c)return {chip:false,line:LINE.some(n=>n.undo&&!!n.act)};
          const cb=b(c),hit=[...l.querySelectorAll('button,[role=link],.pv-s,.pv-st,.pv-fig-id,.pv-arm')].filter(e=>!c.contains(e)&&v(e))
            .filter(e=>{const r=b(e); return r.left<cb.right+4&&r.right>cb.left-4&&r.top<cb.bottom&&r.bottom>cb.top;}).map(e=>e.className.toString());
          return {chip:true,covers:hit,short:l.classList.contains('pv-chip-short'),words:v(c.querySelector('.nt-t')),undo:v(c.querySelector('[data-act="notice-act"]'))};}"""
        seen = set()
        for w in [0] + list(
            range(1400, 280, -2)
        ):  # every 2px: a folded chip 8px wider than measured covered the identifier at 744-760px only
            got = page.evaluate(geom, w)
            if got["chip"]:
                self.assertEqual(got["covers"], [], (w, got))
                self.assertTrue(got["undo"], (w, got))
                seen.add("short" if got["short"] else "full")
            else:
                self.assertTrue(got["line"], (w, got))  # the undo went to the status line
                seen.add("line")
                break
        self.assertTrue({"full", "line"} <= seen, seen)

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
        self.assertAlmostEqual(got["line"]["bottom"], cover - page.evaluate(TOUCH_GAP), delta=1)
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


# ---- The RC review of 0.4.34's line layout (six testers and a Codex review of the combined RC).
# A visualViewport that a test lowers (the keyboard) without the layout giving way - an iPad's Safari: window.__setKb(px).
VV_INIT = r"""(()=>{const real=window.visualViewport; if(!real)return; window.__kb=0; const f=new EventTarget();
 for(const k of ['width','offsetLeft','offsetTop','pageLeft','pageTop','scale'])Object.defineProperty(f,k,{get:()=>real[k]});
 Object.defineProperty(f,'height',{get:()=>real.height-window.__kb});
 real.addEventListener('resize',()=>f.dispatchEvent(new Event('resize'))); real.addEventListener('scroll',()=>f.dispatchEvent(new Event('scroll')));
 Object.defineProperty(window,'visualViewport',{get:()=>f,configurable:true});
 window.__setKb=px=>{window.__kb=px; f.dispatchEvent(new Event('resize'));};})();"""
# The contrast of selector sel's text and border against what is painted under it (its ancestors' backgrounds composited).
CONTRAST = r"""sel=>{const e=document.querySelector(sel); if(!e)return null;
 const P=(el,prop)=>{const c=document.createElement('canvas').getContext('2d'); c.fillStyle='#000'; c.fillStyle=getComputedStyle(el)[prop]; c.fillRect(0,0,1,1); const d=c.getImageData(0,0,1,1).data; return [d[0],d[1],d[2],d[3]/255];};
 const over=(f,g)=>[0,1,2].map(i=>f[i]*f[3]+g[i]*(1-f[3])),lum=c=>{const l=c.map(v=>{v/=255; return v<=0.04045?v/12.92:Math.pow((v+0.055)/1.055,2.4);}); return 0.2126*l[0]+0.7152*l[1]+0.0722*l[2];};
 const cr=(a,b)=>{const x=lum(a),y=lum(b); return (Math.max(x,y)+0.05)/(Math.min(x,y)+0.05);};
 let g=[255,255,255]; const up=[]; for(let x=e;x;x=x.parentElement)up.push(x); up.reverse().forEach(x=>{g=over(P(x,'backgroundColor'),g);});
 return {text:cr(over(P(e,'color'),g),g),border:cr(over(P(e,'borderTopColor'),g),g)};}"""
# How tall a column through the middle of selector sel answers it (elementFromPoint), 30px over and under its box searched.
VHIT = """sel=>{const e=document.querySelector(sel); if(!e)return null; const b=e.getBoundingClientRect(),x=b.left+b.width/2; let top=null,bot=null;
  for(let y=Math.floor(b.top)-30;y<=b.bottom+30;y++){const h=document.elementFromPoint(x,y); if(h&&(h===e||e.contains(h))){if(top===null)top=y; bot=y;}} return top===null?0:bot-top+1;}"""
# What the save chip on page n's line lies over: the line's controls and state words under its box (4px around).
CHIP_OVER = """n=>{const l=document.querySelector('#doc .pv[data-page="'+n+'"]'),c=l&&l.querySelector(':scope>.nt-chip'); if(!c)return null; const cb=c.getBoundingClientRect();
  return [...l.querySelectorAll('button,[role=link],.pv-s,.pv-st,.pv-fig-id,.pv-arm,.pv-pop')].filter(e=>!c.contains(e)&&e.getClientRects().length)
    .filter(e=>{const r=e.getBoundingClientRect(); return r.left<cb.right+4&&r.right>cb.left-4&&r.top<cb.bottom&&r.bottom>cb.top;}).map(e=>e.className.toString());}"""


class RcLayoutFixes(VerdictBase):
    """The RC review's layout findings: the popover's first tap, a chip that never moves or covers anything, no page jump
    on [이유 추가], the popover's side, the armed word's contrast, the status line's hit area, a keyboard over the page, the
    pencil, the armed wait in full, the destructive actions' spacing, 44px touch hits, the field's edge, no layout read per
    scroll."""

    def tall(self, page, n=2):
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        page.evaluate(SCROLL, [n, "top"])
        settle(page)

    def test_the_popovers_buttons_take_the_first_tap_with_the_keyboard_up(self):
        """Fold portrait: a tap on the popover's [저장] takes the focus out of the field; the fold the field made (pv-typing:
        no status line, no figure name) holds until the tap's click has run, so [저장] is where the finger came down and the
        first tap saves (it moved 24-85px and the click fell on the popover)."""
        page = self.on("fig", **FOLD_PORTRAIT)
        page.evaluate("setSide(false)")
        settle(page)
        self.tall(page)
        page.evaluate("lineNote('a message on the status line',NOTICE_KIND.INFO)")
        pid = self.press_page(page, 2, "보류")
        page.evaluate(END_CHIPS)
        open_reason(page, 2, tap=True)
        page.keyboard.type("첫 탭에 저장")
        settle(page)
        page.evaluate(
            """()=>{window.__at={}; const s=()=>{const b=document.querySelector('#doc .pv [data-act="pv-reason-save"]'); return b?Math.round(b.getBoundingClientRect().top):null;};
              document.addEventListener('pointerdown',()=>{window.__at.down=s();},true); document.addEventListener('click',()=>{window.__at.click=s(); window.__at.typing=document.body.classList.contains('pv-typing');},true);}"""
        )
        box = page.locator('#doc .pv[data-page="2"] [data-act="pv-reason-save"]').bounding_box()
        page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='첫 탭에 저장')", arg=pid)
        at = page.evaluate("window.__at")
        self.assertEqual((at["down"], at["typing"]), (at["click"], True), at)
        settle(page)
        self.assertFalse(page.evaluate("document.body.classList.contains('pv-typing')"))  # let go after the click

    def test_the_save_chip_never_moves_the_words(self):
        """A phone's floating line and a desktop page at a small zoom: the words stand where they stood before the press and
        the chip came - the chip is laid over the line, never in its flow, and the line's height is the same with it and
        without it (it added a row, 131 -> 251px, and a tap on the old 삭제 spot hit its [되돌리기])."""
        for word, (
            device,
            zoom,
        ) in zip(  # a word per run: the pages keep the first run's verdict, and a press on it takes it back
            ("보류", "채택"),
            (({"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}, 1.5), ({}, 0.6)),
            strict=True,
        ):
            with self.subTest(device=device.get("viewport"), zoom=zoom):
                page = self.on("fig", **device)
                if device:
                    page.evaluate("setSide(false)")
                    settle(page)
                page.evaluate("z=>{setK(PT_PX*z,false); ZOOMED=true}", zoom)
                settle(page)
                page.evaluate(SCROLL, [2, "top"])
                settle(page)
                words = """()=>[...document.querySelectorAll('#doc .pv[data-page="2"] .vd-b')].map(b=>{const r=b.getBoundingClientRect(); return [Math.round(r.left+r.width/2),Math.round(r.top+r.height/2)];})"""
                before = page.evaluate(words)
                self.press_page(page, 2, word)
                with_chip = page.evaluate(words)
                height = page.evaluate(
                    """()=>document.querySelector('#doc .pv[data-page="2"]').getBoundingClientRect().height"""
                )
                page.evaluate(END_CHIPS)
                settle(page)
                self.assertEqual(
                    page.evaluate(
                        """()=>document.querySelector('#doc .pv[data-page="2"]').getBoundingClientRect().height"""
                    ),
                    height,
                )
                for (bx, by), (ax, ay) in zip(before, with_chip, strict=True):
                    self.assertEqual(by, ay)  # same row
                    self.assertLessEqual(abs(ax - bx), 16)  # the pressed word's check may widen it a little

    def test_the_chip_covers_no_control_and_a_hover_holds_it_4_more_seconds(self):
        """After a save the chip covers no control, state word or focus ring - [이유 추가] and [판정 취소] answer their own
        presses - on a desktop and a folded-open foldable; a mouse resting on it holds it at most 4s past its window."""
        for word, device in (
            ("보류", {}),
            ("채택", FOLD_PORTRAIT),
        ):  # a word per run: a press on the current word takes it back
            with self.subTest(device=device.get("viewport")):
                page = self.on("fig", **device)
                page.evaluate("setSide(false)")
                settle(page)
                self.press_page(page, 1, word)
                if page.evaluate("!!document.querySelector('#doc .pv[data-page=\"1\"]>.nt-chip')"):
                    self.assertEqual(page.evaluate(CHIP_OVER, 1), [])
                for sel in ('[data-act="pv-reason-open"]', ".pv-cancel"):
                    self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="1"] ' + sel), sel)
        page = self.on("fig")
        page.evaluate("setK(PT_PX*2,false); ZOOMED=true")
        settle(page)
        self.press_page(page, 2, "보류")
        chip = '#doc .pv[data-page="2"]>.nt-chip'
        page.hover(chip)
        page.mouse.move(
            *[v + 2 for v in (page.locator(chip).bounding_box()["x"], page.locator(chip).bounding_box()["y"])]
        )
        page.evaluate(
            "()=>NOTICES.forEach(n=>{if(n.place==='chip'){n.at=Date.now()-NOTICE_MS-4100; n.hover=true; armNotice(n);}})"
        )
        page.wait_for_function("()=>!document.querySelector('#doc .pv>.nt-chip')", timeout=2000)

    def test_opening_the_reason_from_the_line_keeps_the_page_where_it_is(self):
        """[이유 추가] pressed after a click save (the chip up): the PDF area does not scroll and the reading page stays (it
        jumped 583-1358px and a following digit saved on another page)."""
        page = self.on("fig")
        self.tall(page)
        self.press_page(page, 2, "보류")
        top = page.evaluate("document.querySelector('#left').scrollTop")
        page.locator('#doc .pv[data-page="2"] [data-act="pv-reason-open"]').click()
        page.wait_for_selector('#doc .pv[data-page="2"] .pv-pop')
        settle(page)
        self.assertEqual(page.evaluate("document.querySelector('#left').scrollTop"), top)
        self.assertEqual(page.evaluate("PV_READ"), 2)

    def test_a_popover_near_the_top_opens_under_its_line(self):
        """An in-place line 40px under the PDF area's top: its popover opens under it, wholly inside what the area shows,
        five lines of reason in view (it opened above, under the top bar, its last line alone in view)."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        page.evaluate(
            """()=>{const A=document.querySelector('#left'),l=document.querySelector('#doc .pv[data-page="1"]'); A.scrollTop+=l.getBoundingClientRect().top-(A.getBoundingClientRect().top+40);}"""
        )
        settle(page)
        self.press_page(page, 1, "보류")
        page.evaluate(END_CHIPS)
        field = open_reason(page, 1)
        field.type("하나")
        for k in range(4):
            field.press("Shift+Enter")
            field.type("줄 %d" % (k + 2))
        settle(page)
        got = page.evaluate(
            """()=>{const l=document.querySelector('#doc .pv[data-page="1"]'),p=l.querySelector('.pv-pop'),f=p.querySelector('.pv-reason'),A=document.querySelector('#left').getBoundingClientRect();
              return {below:l.classList.contains('pv-pop-below'),inside:p.getBoundingClientRect().top>=A.top&&p.getBoundingClientRect().bottom<=A.bottom,whole:f.scrollHeight<=f.clientHeight+1};}"""
        )
        self.assertEqual(got, {"below": True, "inside": True, "whole": True})

    def test_the_armed_word_and_its_wait_read_4_5_to_1(self):
        """The armed '삭제 확정' and '4초 안에 한 번 더 누르면 저장' on the line, light and dark: 4.5:1 and more (3.6 and 4.2:1 in
        the light theme)."""
        page = self.on("fig")
        page.locator('#doc .pv[data-page="1"] button[data-key="삭제"]').click()
        settle(page)
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page.evaluate("t=>setTheme(t)", theme)
                page.mouse.move(1, 1)
                settle(page)
                self.assertGreaterEqual(
                    page.evaluate(CONTRAST, '#doc .pv[data-page="1"] .vd-b.vd-confirm.armed')["text"], 4.5
                )
                self.assertGreaterEqual(page.evaluate(CONTRAST, '#doc .pv[data-page="1"] .pv-arm')["text"], 4.5)

    def test_on_touch_the_status_lines_hits_stay_off_the_floating_words(self):
        """Phone and fold portrait with the status line up: the floating line stands over the 44px its [x] answers, so the
        bottom of a word answers the word, not the status line's [x] (its 44px reached 16px into the words)."""
        for device in (
            {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True},
            FOLD_PORTRAIT,
        ):
            with self.subTest(device=device["viewport"]):
                page = self.on("fig", **device)
                page.evaluate("setSide(false)")
                settle(page)
                self.tall(page)
                page.evaluate("lineNote('a message on the status line',NOTICE_KIND.INFO)")
                settle(page)
                got = page.evaluate(
                    """()=>{const w=document.querySelector('#doc .pv[data-page="2"] .vd-b'),r=w.getBoundingClientRect(),d=document.querySelector('#status-dock').getBoundingClientRect();
                      const h=document.elementFromPoint(r.left+r.width/2,r.bottom-1); return {gap:Math.round(d.top-document.querySelector('#doc .pv[data-page="2"]').getBoundingClientRect().bottom),own:!!h&&w.contains(h)};}"""
                )
                self.assertEqual(got, {"gap": page.evaluate(TOUCH_GAP), "own": True})

    def test_a_keyboard_over_the_page_keeps_the_line_and_its_popover_above_it(self):
        """A keyboard laid over the page without the layout giving way (the visual viewport 45% shorter): the floating line
        and the reason popover stand above it, on the fold in portrait and in landscape (they were under it)."""
        for word, device in (  # a word per run: a press on the current word takes it back
            ("보류", FOLD_PORTRAIT),
            ("채택", {"viewport": {"width": 1104, "height": 882}, "is_mobile": True, "has_touch": True}),
        ):
            with self.subTest(device=device["viewport"]):
                page = self.on("fig", init=VV_INIT, **device)
                page.evaluate("setSide(false)")
                settle(page)
                self.tall(page)
                self.press_page(page, 2, word)
                page.evaluate(END_CHIPS)
                open_reason(page, 2, tap=True)
                kb = int(device["viewport"]["height"] * 0.45)
                page.evaluate("k=>window.__setKb(k)", kb)
                settle(page)
                top = device["viewport"]["height"] - kb
                got = page.evaluate(
                    """()=>{const l=document.querySelector('#doc .pv[data-page="2"]'); return [l.getBoundingClientRect().bottom,l.querySelector('.pv-pop').getBoundingClientRect().bottom];}"""
                )
                self.assertLessEqual(got[0], top + 0.5, got)
                self.assertLessEqual(got[1], top + 0.5, got)

    def test_a_long_reasons_pencil_and_the_armed_wait_stay_whole(self):
        """A reason longer than its room is cut before its pencil, which stays in view; a confirm word's wait is said in
        full on a line with an earlier verdict and a reason - what does not bear on the second press gives way."""
        page = self.on("fig", viewport={"width": 1920, "height": 1080})
        self.press_page(page, 1, "보류")
        self.press_page(page, 1, "채택")
        page.evaluate(END_CHIPS)
        field = open_reason(page, 1)
        field.fill("아주 긴 이유를 써 둔다 " * 12)
        field.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] button.pv-note')
        settle(page)
        got = page.evaluate(
            """()=>{const b=document.querySelector('#doc .pv[data-page="1"] button.pv-note'),i=b.querySelector('.ic').getBoundingClientRect(),r=b.getBoundingClientRect(),t=b.querySelector('.pv-note-t');
              const h=document.elementFromPoint(i.left+i.width/2,i.top+i.height/2); return {pencil:i.right<=r.right+0.5&&!!h&&b.contains(h),cut:t.scrollWidth>t.clientWidth};}"""
        )
        self.assertEqual(got, {"pencil": True, "cut": True})
        page.locator('#doc .pv[data-page="1"] button[data-key="삭제"]').click()
        settle(page)
        self.assertTrue(
            page.evaluate(
                """()=>{const a=document.querySelector('#doc .pv[data-page="1"] .pv-arm'); return !!a&&a.scrollWidth<=a.clientWidth+1;}"""
            )
        )

    def test_the_destructive_actions_stand_apart(self):
        """[판정 취소] stands 16px and more from the reason's button before it; the popover's [지우기] 16px from [닫기] with a
        divider (they stood 4px apart)."""
        page = self.on("fig", viewport={"width": 1920, "height": 1080})
        self.press_page(page, 1, "보류")
        page.evaluate(END_CHIPS)
        field = open_reason(page, 1)
        field.fill("이유")
        field.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] button.pv-note')
        settle(page)
        gap = page.evaluate(
            """()=>{const n=document.querySelector('#doc .pv[data-page="1"] button.pv-note').getBoundingClientRect(),c=document.querySelector('#doc .pv[data-page="1"] .pv-cancel').getBoundingClientRect(); return Math.round(c.left-n.right);}"""
        )
        self.assertGreaterEqual(gap, 16)
        page.locator('#doc .pv[data-page="1"] button.pv-note').click()
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop [data-act="pv-reason-clear"]')
        got = page.evaluate(
            """()=>{const c=document.querySelector('#doc .pv-pop [data-act="pv-reason-clear"]'),n=c.nextElementSibling,d=getComputedStyle(c,'::before');
              return {gap:Math.round(n.getBoundingClientRect().left-c.getBoundingClientRect().right),divider:d.content!=='none'&&parseFloat(d.width)===1};}"""
        )
        self.assertEqual(got, {"gap": 16, "divider": True})

    def test_touch_hits_answer_44px_and_the_fields_edge_reads_3_to_1(self):
        """Fold portrait: the line's '#N', the status line's [되돌리기] and [x] answer 44px tall; the reason field's edge reads
        3:1 and more in both themes (1.5:1)."""
        page = self.on("fig", **FOLD_PORTRAIT)
        page.evaluate("setSide(false)")
        settle(page)
        self.tall(page)
        self.press_page(page, 2, "보류")
        page.evaluate("()=>NOTICES.forEach(n=>{if(n.place==='chip')offerToLine(n);})")  # the undo on the status line
        settle(page)
        self.assertGreaterEqual(page.evaluate(VHIT, '#doc .pv[data-page="2"] .pv-ref'), 44)
        self.assertGreaterEqual(page.evaluate(VHIT, "#status-dock #status button.nt-act"), 44)
        self.assertGreaterEqual(page.evaluate(VHIT, "#status-dock #status button.nt-x"), 44)
        open_reason(page, 2, tap=True)
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page.evaluate("t=>setTheme(t)", theme)
                settle(page)
                self.assertGreaterEqual(
                    page.evaluate(CONTRAST, '#doc .pv[data-page="2"] .pv-pop .pv-reason')["border"], 3
                )

    def test_no_chip_check_reads_the_layout_per_scroll_event(self):
        """Fifty scroll events in one frame run the chips' bar check at most once a frame, and with no chip up it reads no
        layout (it read the select bar's box on every event)."""
        page = self.on("fig")
        got = page.evaluate(
            """async()=>{let calls=0,reads=0; const o=window.chipsClearOfBar; window.chipsClearOfBar=function(){calls++; return o.apply(this,arguments);};
              const bar=document.querySelector('#sel-bar'),r=bar.getBoundingClientRect.bind(bar); bar.getBoundingClientRect=()=>{reads++; return r();};
              const L=document.querySelector('#left'); for(let i=0;i<50;i++)L.dispatchEvent(new Event('scroll'));
              await new Promise(f=>requestAnimationFrame(()=>requestAnimationFrame(f))); window.chipsClearOfBar=o; return {calls,reads};}"""
        )
        self.assertLessEqual(got["calls"], 2)
        self.assertEqual(got["reads"], 0)

    def test_what_a_press_adds_gives_way_on_a_tight_row(self):
        """A tight row on the wide band (a page at 1280 x 800 with the panel open is 620px): the earlier link gives its place
        to what a press adds. A 560px line, key saves of 보류 then 채택: the state, 'Enter 이유 쓰기' (its key mark whole) and
        [판정 취소] hold one row, the earlier link out. Beside the earlier link the line stacked under the press (the RC's
        merge of its layout and logic fixes). The take-back's [되돌리기] is test_reason_add_yields_to_the_lines_undo_..."""
        page = self.on("fig")
        page.evaluate("w=>{setK(w/META.pages[1].pt_w,false); ZOOMED=true}", 560)
        settle(page)
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        row = """n=>{const l=document.querySelector('#doc .pv[data-page="'+n+'"]'),k=l.querySelector('.pv-kbd'),e=l.querySelector('.pv-early'),v=x=>!!x&&x.getClientRects().length>0;
          return {stack:l.classList.contains('pv-stack'),h:Math.round(l.getBoundingClientRect().height),key:v(k)?k.textContent:null,early:v(e)};}"""
        for i, key in enumerate("21"):
            page.keyboard.press(key)
            page.wait_for_function("n=>OPEN_ALL.length>=n", arg=i + 1)
            settle(page)
            page.evaluate(END_CHIPS)
            settle(page)
            page.wait_for_timeout(900)
        got = page.evaluate(row, 2)
        self.assertEqual((got["stack"], got["early"], got["key"]), (False, False, "Enter"), got)
        self.assertLessEqual(got["h"], 40)

    def test_reason_add_yields_to_the_lines_undo_at_1280_with_a_three_digit_pin(self):
        """1280 x 800, panel open, a page as wide as the pl document's there (620px), pin numbers past 100. Key saves of 보류,
        채택, 보류, then 보류 again takes the third back: while the line offers its [되돌리기], [이유 추가] steps out (as for an
        armed word's wait) - one row, the earlier link kept where it still fits, and the focus the key save left on 'Enter 이유 쓰기' is on the
        [되돌리기]. When the offer ends [이유 추가] and the link are back, still one row. With [이유 추가] beside the undo the
        row was within 2px of stacking."""
        (ps.APP.C.state / "pins.seq").write_text("99\n", encoding="utf-8")
        page = self.on("fig", viewport={"width": 1280, "height": 800})
        page.evaluate("setSide(true)")
        page.evaluate("w=>{setK(w/META.pages[1].pt_w,false); ZOOMED=true}", 620)
        settle(page)
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        row = """n=>{const l=document.querySelector('#doc .pv[data-page="'+n+'"]'),v=x=>!!x&&x.getClientRects().length>0,a=document.activeElement;
          return {stack:l.classList.contains('pv-stack'),h:Math.round(l.getBoundingClientRect().height),add:v(l.querySelector('.pv-add')),
            undo:v(l.querySelector('.pv-undo')),early:v(l.querySelector('.pv-early')),focus:a&&a.dataset?a.dataset.act||a.className:null,
            ref:l.querySelector('.pv-ref').textContent};}"""
        for i, key in enumerate("212"):
            page.keyboard.press(key)
            page.wait_for_function("n=>OPEN_ALL.length>=n", arg=i + 1)
            settle(page)
            page.evaluate(END_CHIPS)
            settle(page)
            page.wait_for_timeout(900)
        self.assertEqual(page.evaluate(row, 2)["focus"], "pv-reason-open")  # 'Enter 이유 쓰기' after the key save
        page.keyboard.press("2")  # the current word: the third verdict is taken back, the line offers [되돌리기]
        page.wait_for_function("()=>!!document.querySelector('#doc .pv[data-page=\"2\"] .pv-undo')")
        settle(page)
        got = page.evaluate(row, 2)
        self.assertGreaterEqual(int(got["ref"].lstrip("#")), 100, got)
        self.assertEqual(
            {k: got[k] for k in ("stack", "add", "undo", "focus")},
            {"stack": False, "add": False, "undo": True, "focus": "pv-undo"},
        )
        self.assertLessEqual(got["h"], 40)
        page.evaluate("()=>{NOTICES.forEach(n=>endNotice(n,false)); drawPageVerdicts();}")  # the offer ends
        settle(page)
        got = page.evaluate(row, 2)
        self.assertEqual(
            {k: got[k] for k in ("stack", "add", "undo")}, {"stack": False, "add": True, "undo": False}, got
        )
        self.assertLessEqual(got["h"], 40)


# A control's touch area along its left edge, middle and right edge: how tall a column through each answers it (elementFromPoint,
# 40px over and under its box searched), [left, middle, right].
EDGE_HITS = """sel=>{const e=document.querySelector(sel); if(!e||!e.getClientRects().length)return null; const b=e.getBoundingClientRect();
  return [b.left+1,b.left+b.width/2,b.right-1].map(x=>{let top=null,bot=null; for(let y=Math.floor(b.top)-40;y<=Math.ceil(b.bottom)+40;y++){const h=document.elementFromPoint(x,y);
    if(h&&(h===e||e.contains(h))){if(top===null)top=y; bot=y;}} return top===null?0:bot-top+1;});}"""
# Page n's words, as their centres.
WORDS_AT = """n=>[...document.querySelectorAll('#doc .pv[data-page="'+n+'"] .vd-b')].map(b=>{const r=b.getBoundingClientRect(); return [Math.round(r.left+r.width/2),Math.round(r.top+r.height/2)];})"""


class RcLayoutFixes2(VerdictBase):
    """The RC retest's layout findings: touch areas along both edges, a line's first save moving no word (a phone's line in
    its place, a narrow desktop line), a sheet's banner clear of the tool bar, the new reading page kept in place."""

    def test_touch_areas_answer_44px_along_both_edges(self):
        """Phone and fold portrait, the status line up with a save's [되돌리기] and the floating line over it: a column
        through the left edge, the middle and the right edge of [되돌리기], [x] and the line's '#N' each answers 44px and more
        ([x]'s centred area took the right 6px of [되돌리기], and the 1px borders answered only the box)."""
        for word, device in (
            ("보류", {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}),
            ("채택", FOLD_PORTRAIT),
        ):
            with self.subTest(device=device["viewport"]):
                page = self.on("fig", **device)
                page.evaluate("setSide(false)")
                settle(page)
                page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
                settle(page)
                page.evaluate(SCROLL, [2, "top"])
                settle(page)
                self.press_page(page, 2, word)
                page.evaluate(
                    "()=>NOTICES.forEach(n=>{if(n.place==='chip')offerToLine(n);})"
                )  # the undo on the status line
                settle(page)
                for sel in (
                    "#status-dock #status button.nt-act",
                    "#status-dock #status button.nt-x",
                    '#doc .pv[data-page="2"] .pv-ref',
                ):
                    got = page.evaluate(EDGE_HITS, sel)
                    self.assertTrue(got and min(got) >= 44, (sel, got))

    def test_a_first_save_moves_no_word_of_a_phones_line_in_its_place(self):
        """390x844, page 1's line in its place under the page: its state's row is as tall from the start as a text action
        makes it, so the first verdict's [이유 추가] and [판정 취소] do not push the words down (they dropped 25px)."""
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.evaluate("setSide(false)")
        settle(page)
        page.evaluate(
            """()=>{const A=document.querySelector('#left'),l=document.querySelector('#doc .pv[data-page="1"]'),ar=A.getBoundingClientRect(); A.scrollTop+=l.getBoundingClientRect().top-(ar.top+ar.height*0.3);}"""
        )
        settle(page)
        self.assertFalse(
            page.evaluate("""document.querySelector('#doc .pv[data-page="1"]').classList.contains('stuck')""")
        )
        before = page.evaluate(WORDS_AT, 1)
        self.press_page(page, 1, "보류")
        after = page.evaluate(WORDS_AT, 1)
        self.assertEqual([y for _, y in after], [y for _, y in before])

    def test_a_narrow_desktop_line_is_stacked_before_its_first_save(self):
        """A mouse, the pages at a small zoom: a line narrower than the state a press brings beside its words is stacked
        while it still says '판정 없음', so the first save leaves every word where it was (it went from one row to three under
        the press, 91px, the words 59px down and 100-330px left)."""
        page = self.on("fig")
        for zoom in (
            0.9,
            0.8,
            0.7,
            0.6,
            0.5,
            0.45,
            0.4,
            0.35,
        ):  # the largest zoom at which page 2's line is narrower than that state
            page.evaluate("z=>{setK(PT_PX*z,false); ZOOMED=true}", zoom)
            settle(page)
            if page.evaluate(
                """()=>document.querySelector('#doc .pv[data-page="2"]').classList.contains('pv-stack')"""
            ):
                break
        page.evaluate(  # page 2 under the reading line, well inside it: its line names its figure before and after the press
            """()=>{const A=document.querySelector('#left'),ar=A.getBoundingClientRect(),p=document.getElementById('p2').getBoundingClientRect(); A.scrollTop+=p.top+p.height/2-(ar.top+readingDepth(A));}"""
        )
        settle(page)
        need = page.evaluate(
            """()=>{const l=document.querySelector('#doc .pv[data-page="2"]'); return {w:l.getBoundingClientRect().width,stack:l.classList.contains('pv-stack'),need:pvStateNeed(l)};}"""
        )
        self.assertGreater(need["need"], 150, need)
        self.assertTrue(need["stack"], need)
        before = page.evaluate(WORDS_AT, 2)
        top = page.evaluate("document.querySelector('#left').scrollTop")
        page.mouse.click(*before[0])  # where the person's mouse is: no scroll before the press
        page.wait_for_function("()=>OPEN_ALL.length===1")
        page.evaluate(END_CHIPS)
        settle(page)
        self.assertEqual(page.evaluate("document.querySelector('#left').scrollTop"), top)
        after = page.evaluate(WORDS_AT, 2)
        self.assertEqual(page.evaluate("PV_READ"), 2)
        self.assertEqual([y for _, y in after], [y for _, y in before])
        for (bx, _), (ax, _) in zip(before, after, strict=True):
            self.assertLessEqual(abs(ax - bx), 16)  # the pressed word's check may widen it a little

    def test_a_sheets_banner_is_scrolled_clear_of_the_tool_bar(self):
        """390x844, the sheet open and its list scrolled: a banner put on top of the list is scrolled into view under the
        sheet's stuck tool bar, its first line readable (it stood under the bar, '핀 #1 메모를 저장하지 않았습니다' hidden)."""
        page = self.on("fig", n_open=0, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        for k in range(10):
            page.evaluate(
                "k=>{LAST_PTR='touch'; pick({doc:'fig',page:1,pdf_build:META.pages_build,x0:20,y0:20+k*8,x1:200,y1:26+k*8,frac:[0.05,0.05+k*0.02,0.4,0.015]});}",
                k,
            )
            page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
            page.fill("#note", "목록을 길게 %d" % k)
            page.evaluate("savePin()")
            page.wait_for_function("!COMPOSE.saving&&$('#composer').hidden")
        page.evaluate("setSide(true)")
        settle(page)
        page.evaluate("()=>{const r=document.querySelector('#right'); r.scrollTop=r.scrollHeight;}")
        settle(page)
        self.assertGreater(page.evaluate("document.querySelector('#right').scrollTop"), 40)
        page.evaluate(
            "()=>bannerNote(NOTICE_HOST.LIST,'핀 #1 메모를 저장하지 않았습니다 · 그사이 다른 곳에서 메모가 바뀌었습니다 — 지금 메모: 에이전트가 덧붙인 메모',NOTICE_KIND.WARN,{label:'내 메모로 덮어쓰기',fn:()=>{}})"
        )
        settle(page)
        got = page.evaluate(
            """()=>{const n=document.querySelector('#list>.nt-banner'),r=n.getBoundingClientRect(),bar=document.querySelector('#bar1').getBoundingClientRect(),h=document.elementFromPoint(r.left+r.width/2,r.top+4);
              return {below:r.top>=bar.bottom,top:!!h&&n.contains(h)};}"""
        )
        self.assertEqual(got, {"below": True, "top": True})

    def test_the_new_reading_page_stays_put_when_the_line_above_loses_its_name(self):
        """390x844: the lines are stacked and the reading line's figure name has a row of its own. The pages scroll so page 2
        becomes the reading page: page 1's line, above it, keeps that row's place (empty) - and page 2, under the reader's
        eyes, stays where it was on screen with no scroll of the area (the line lost the row, 23px, and moved page 2 up by
        as much; a two-finger zoom over page 2 then missed its anchor, ActualSize.test_each_page_keeps_its_own_line_badge_
        and_zoom_anchor failing 4 runs in 15 - and a scroll making up for it trapped a slow scroll at the page's end)."""
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.evaluate("setSide(false)")
        page.evaluate(
            "()=>{setK(K*2.5,false); ZOOMED=true; document.querySelector('#left').scrollTop=0;}"
        )  # page 1 taller than the reading depth
        settle(page)
        page.evaluate("pvStick()")
        settle(page)
        self.assertEqual(page.evaluate("PV_READ"), 1)
        got = page.evaluate(
            """()=>{const L=document.querySelector('#left'),p2=document.getElementById('p2'),l1=document.querySelector('#doc .pv[data-page="1"]');
              L.scrollTop+=p2.getBoundingClientRect().top-(L.getBoundingClientRect().top+20); const y=p2.getBoundingClientRect().top,h=l1.getBoundingClientRect().height;
              const st=L.scrollTop; pvStick(); return {read:PV_READ,stack:l1.classList.contains('pv-stack'),shrank:h-l1.getBoundingClientRect().height,moved:p2.getBoundingClientRect().top-y,scrolled:L.scrollTop-st};}"""
        )
        self.assertEqual((got["read"], got["stack"]), (2, True), got)
        self.assertLess(abs(got["shrank"]), 0.5, got)  # the name's row keeps its place on the line above
        self.assertLess(abs(got["moved"]), 0.5, got)
        self.assertEqual(got["scrolled"], 0, got)


class LateFont(VerdictBase):
    """A web font arriving after the lines were measured (Codex review of the RC: the bundled interface font after the
    fallback face): the width of a fresh verdict's state is measured again and the lines fit themselves again."""

    def setUp(self):
        super().setUp()
        self.held_font: list | None = None  # a late face's file, held unanswered while a list

    def route(self, route):
        """Hold the late face's file (a slice of the bundled font asked for again under '?late') until release_font()."""
        rq = urlparse(route.request.url)
        if self.held_font is not None and rq.path.endswith(".woff2") and "late" in rq.query:
            self.held_font.append(route)
            return None
        return super().route(route)

    def release_font(self):
        held, self.held_font = self.held_font or [], None
        for r in held:
            super().route(r)

    def test_a_font_that_comes_late_measures_the_state_again(self):
        """The lines take a face whose file is still on its way: the fallback measures the state first; once the face is
        in, the kept width is the face's and every line is fitted to it. Kept from the fallback, a line near the threshold
        kept the fallback's rows, so the first save could still move its words."""
        page = self.on("fig")
        self.held_font = []
        page.evaluate(
            r"""()=>{const f=performance.getEntriesByType('resource').map(e=>e.name).find(n=>/\/vendor\/pretendard\/.*\.woff2/.test(n));
              const s=document.createElement('style'); s.textContent="@font-face{font-family:'Late Face';src:url('"+f+(f.includes('?')?'&':'?')+"late') format('woff2')}"+
                "#doc .pv{font-family:'Late Face',monospace}"; document.head.appendChild(s);}"""
        )
        page.wait_for_function("()=>document.fonts.status==='loading'")
        page.evaluate("sizePv()")
        before = page.evaluate("""()=>pvStateNeed(document.querySelector('#doc .pv[data-page="1"]'))""")
        self.release_font()
        page.wait_for_function(
            "()=>document.fonts.status==='loaded'&&[...document.fonts].some(f=>f.family.includes('Late Face')&&f.status==='loaded')"
        )
        settle(page)
        got = page.evaluate(
            """()=>{const l=document.querySelector('#doc .pv[data-page="1"]'),kept=PV_NEED.w,rows=[...document.querySelectorAll('#doc .pv')].map(x=>x.className).join();
              PV_NEED={key:'',w:0}; const fresh=pvStateNeed(l); sizePv(); return {kept,fresh,same:rows===[...document.querySelectorAll('#doc .pv')].map(x=>x.className).join()};}"""
        )
        self.assertNotEqual(before, got["fresh"])  # the fallback and the face set the state at different widths
        self.assertEqual((got["kept"], got["same"]), (got["fresh"], True))


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
        page.evaluate("setK(PT_PX*2,false); ZOOMED=true")  # page 2's line wide enough to hold a chip (pvChipPlace)
        settle(page)
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


# The words of page n's [이유 추가] / 'Enter 이유 쓰기' button, spaces folded.
ADD_TEXT = """n=>{const b=document.querySelector('#doc .pv[data-page="'+n+'"] button.pv-add'); return b?b.textContent.replace(/\\s+/g,' ').trim():null;}"""
# Where the focus is: the page of the line that holds it (0 for none) and its control's data-act.
FOCUS_AT = """()=>{const a=document.activeElement,l=a&&a.closest&&a.closest('#doc .pv'); return [l?Number(l.dataset.page):0, a&&a.dataset?a.dataset.act||null:null];}"""


def open_reason(page, n, tap=False):
    """Press (or tap, on a touch screen) the reason of page n's line - [이유 추가], its saved reason or its kept draft - and
    wait for the popover; returns its field, which has the focus."""
    line = '#doc .pv[data-page="%d"]' % n
    opener = page.locator(line + ' [data-act="pv-reason-open"]')
    opener.tap() if tap else opener.click()
    field = page.locator(line + " .pv-pop .pv-reason")
    field.wait_for()
    return field


class Reason(VerdictBase):
    """A reason with a verdict, in place: after a page-line save a popover over that line takes an optional text; Enter
    saves it as the pin's note, Esc or moving on leaves the verdict alone. A key save opens it with the focus; a click save
    leaves [이유 추가] on the reading line."""

    def note(self, pid):
        return self.pins()[pid]["note"]

    def test_after_a_click_the_field_waits_and_enter_saves_the_reason(self):
        """A click on 채택: the pin is saved at once (note ''), no field opens - the line offers [이유 추가]. Pressed, the
        popover opens over the line with the focus ('이유 (선택)'); typed into and Enter, the text is the pin's note, shown
        on the line (a check and its first line) and on its card; the popover goes."""
        page = self.on("fig")
        pid = self.press_page(page, 1, "채택")
        self.assertEqual(self.note(pid), "")
        self.assertIsNone(page.evaluate(REASON, 1))
        self.assertEqual(page.locator('#doc .pv[data-page="1"] button.pv-add').inner_text(), "이유 추가")
        open_reason(page, 1)
        got = page.evaluate(REASON, 1)
        self.assertEqual((got["focused"], got["placeholder"]), (True, "이유 (선택)"))
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

    def test_after_a_key_enter_opens_the_field_and_digits_typed_are_text(self):
        """2 on the reading page saves 보류 and opens nothing - the line offers 'Enter 이유 쓰기'. Enter opens the popover with
        the focus; '3번 패널 범례' typed there is text, its leading digit too, and Enter saves it as the new pin's note."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        page.keyboard.press("2")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 2))
        self.assertEqual(page.evaluate(ADD_TEXT, 2), "Enter 이유 쓰기")
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="2"] .pv-pop .pv-reason')
        self.assertTrue(page.evaluate(REASON, 2)["focused"])
        page.keyboard.type("3번 패널 범례")
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.some(p=>p.note)")
        settle(page)
        (pin,) = self.pins().values()
        self.assertEqual((pin["verdict"], pin["note"]), ("보류", "3번 패널 범례"))

    def test_esc_skips_the_reason(self):
        """1, Enter, then Esc: the popover goes and the focus stays on its own page - on the line's 'Enter 이유 쓰기', not the
        PDF area (from which Tab went to the first page's line) - and the pin has no note."""
        page = self.on("fig")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop .pv-reason')
        self.assertTrue(page.evaluate(REASON, 1)["focused"])
        page.keyboard.press("Escape")
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 1))
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-reason-open"])
        (pin,) = self.pins().values()
        self.assertEqual(pin["note"], "")

    def test_a_confirm_word_saves_on_its_second_press_and_enter_opens_the_field(self):
        """3 arms 삭제 - nothing saved; 3 again saves, opening nothing; Enter opens the field with the focus."""
        page = self.on("fig")
        page.keyboard.press("3")
        settle(page)
        self.assertEqual(len(self.pins()), 0)
        page.keyboard.press("3")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 1))
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop .pv-reason')
        self.assertTrue(page.evaluate(REASON, 1)["focused"])

    def test_the_undo_takes_the_field_with_the_pin(self):
        """채택 clicked, a reason typed but not saved, then the chip's [되돌리기]: the pin is withdrawn and the popover goes
        with it - nothing is written to the dropped pin (the draft is kept for the status line's [되돌리기], ReasonDrafts)."""
        page = self.on("fig")
        pid = self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.type("나중에")
        page.locator('#doc .pv[data-page="1"]>.nt-chip [data-act="notice-act"]').click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=pid)
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 1))
        self.assertNotIn(pid, self.pins())
        _, trash = self.call("GET", "/api/pins/dropped")
        self.assertEqual([p.get("note") for p in trash["dropped"] if p["id"] == pid], [""])

    def test_on_a_phone_the_field_waits_for_a_tap_and_stays_above_the_keyboard(self):
        """390x844: a tap on 채택 does not raise the keyboard (no field opens); [이유 추가] tapped and the keyboard up (the
        layout 300px shorter), the field and the line's words are on screen and pressable."""
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.evaluate("setSide(false)")
        page.evaluate("setK(PT_PX*1.2,false); ZOOMED=true")
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        self.press_page(page, 2, "채택")
        self.assertIsNone(page.evaluate(REASON, 2))
        page.tap('#doc .pv[data-page="2"] button.pv-add')
        page.wait_for_selector('#doc .pv[data-page="2"] .pv-pop .pv-reason')
        page.set_viewport_size({"width": 390, "height": 544})
        settle(page)
        self.assertTrue(page.evaluate(REASON, 2)["focused"])
        self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="2"] .pv-reason'))
        self.assertTrue(page.evaluate(ON_TOP, '#doc .pv[data-page="2"] button[data-key="보류"]'))

    def test_a_second_save_moves_the_draft_to_the_new_verdict(self):
        """'첫째 이유' typed for 채택 (no Enter), then 보류 on the same line: nothing is written to the 채택 pin - the draft
        moves to the new verdict, whose popover holds it and says where it goes ('판정 #2 보류 이유 · #1 채택에서 옮김',
        '저장 안 됨'); Enter writes it to 보류 and the status line says so, result first."""
        page = self.on("fig")
        one = self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.type("첫째 이유")
        two = self.press_page(page, 1, "보류")
        got = page.evaluate(POP, 1)
        self.assertEqual(
            (got["value"], got["to"], got["state"]),
            ("첫째 이유", "판정 #%d 보류 이유 · #%d 채택에서 옮김" % (two, one), "저장 안 됨"),
        )
        self.assertEqual(
            page.evaluate("""()=>document.querySelector('#doc .pv[data-page="1"] .pv-reason').dataset.pin"""), str(two)
        )
        self.assertEqual(self.note(one), "")
        page.click('#doc .pv[data-page="1"] .pv-reason')
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=two)
        settle(page)
        self.assertEqual((self.note(one), self.note(two)), ("", "첫째 이유"))
        self.assertTrue(
            page.evaluate(
                "id=>LINE.some(n=>n.title==='이유 저장됨 · 판정 #'+id+' 보류'&&n.desc==='Deployment calendar')", two
            )
        )

    def test_reading_another_page_closes_the_field_and_keeps_its_text(self):
        """2 on page 2 and '범례' typed: no line shows key marks while the field holds text. Scrolled so page 1 is read:
        the popover closes, '범례' is page 2's pin's note ('이유 저장됨 · 판정 #1 보류 — Review flow'), the focus is on the
        PDF area and page 1's line has the keys."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        page.keyboard.press("2")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="2"] .pv-pop .pv-reason')
        page.keyboard.type("범례")
        settle(page)
        self.assertEqual(page.evaluate("document.querySelectorAll('#doc .pv button[data-kn]').length"), 0)
        page.evaluate(SCROLL, [1, "top"])
        page.wait_for_function("OPEN_ALL.some(p=>p.note)")
        settle(page)
        (pin,) = self.pins().values()
        self.assertEqual(pin["note"], "범례")
        self.assertIsNone(page.evaluate(REASON, 2))
        self.assertTrue(page.evaluate("LINE.some(n=>n.title==='이유 저장됨 · 판정 #1 보류'&&n.desc==='Review flow')"))
        self.assertEqual(page.evaluate("document.activeElement.id"), "left")
        self.assertEqual(
            page.evaluate("document.querySelectorAll('#doc .pv[data-page=\"1\"] button[data-kn]').length"), 3
        )

    def test_another_document_closes_the_field_and_coming_back_does_not_reopen_it(self):
        """'다른 문서로' typed (no Enter), then the PDF document and back: the text is the pin's note, and the figure's
        page 1 line has no field."""
        page = self.on("fig")
        pid = self.press_page(page, 1, "채택")
        open_reason(page, 1)
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
        open_reason(page, 1)
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
        self.assertAlmostEqual(got["line"]["bottom"], cover - page.evaluate(TOUCH_GAP), delta=1)
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
        server answers, with its own [판정 취소]; the pin is in the Trash; the status line says, result first, '판정 #b 채택
        취소 · 지금 판정 #a 보류 — Deployment calendar' with [되돌리기], which brings #b back as the current verdict."""
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
                "title": "판정 #%d 채택 취소 · 지금 판정 #%d 보류" % (b, a),
                "desc": "Deployment calendar",
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
                "id=>LINE.some(n=>n.title==='판정 #'+id+' 채택 취소 · 남은 판정 없음'&&n.desc==='Review flow')",
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
            all(
                t and (t.startswith("누르면 이 쪽의 판정으로 저장합니다") or t.startswith("지금 판정입니다"))
                for t in page.evaluate(LINE, 1)["tips"]
            )
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
        open_reason(page, n)
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
        self.assertTrue(page.evaluate("id=>LINE.some(n=>n.title==='이유 저장됨 · 판정 #'+id+' 채택')", pid))
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
        line says '이유 저장 실패 · 서버에 닿지 않습니다 — <문서>' with [다시 시도]; pressed with the network back, the reason is the
        note and the status line says it was saved. A refusal (400) says so without [다시 시도]."""
        page = self.on("fig")
        fig = page.evaluate("docInfo('fig').name")
        pid = self.typed(page, 1, "다시 보낼 이유")
        self.lose_edit = 1
        page.evaluate("k=>switchDoc(k)", "ms")
        page.wait_for_function("DOC==='ms'&&META&&META.doc==='ms'")
        settle(page)
        self.assertEqual(self.note(pid), "")
        self.assertIn(
            {"title": "이유 저장 실패 · 서버에 닿지 않습니다", "desc": fig, "act": "다시 시도", "kind": "err"},
            page.evaluate(STATUS),
        )
        self.assertEqual(page.evaluate(DRAFTS), {"fig:%d" % pid: "다시 보낼 이유"})  # kept in this tab meanwhile
        page.locator("#status [data-act=notice-act]").filter(has_text="다시 시도").click()
        page.wait_for_function("id=>LINE.some(n=>n.title==='이유 저장됨 · 판정 #'+id+' 채택')", arg=pid)
        settle(page)
        self.assertEqual(self.note(pid), "다시 보낼 이유")
        self.assertFalse(page.evaluate("LINE.some(n=>n.title.startsWith('이유 저장 실패'))"))
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function("DOC==='fig'&&META&&META.doc==='fig'&&document.querySelector('#p1')")
        settle(page)
        self.typed(page, 2, "거절될 이유")
        self.refuse_edit = 1
        page.evaluate("k=>switchDoc(k)", "ms")
        page.wait_for_function("DOC==='ms'&&META&&META.doc==='ms'")
        settle(page)
        self.assertIn(
            {"title": "이유 저장 실패 · 안 됩니다", "desc": fig, "act": None, "kind": "err"},
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
        page.wait_for_function("id=>LINE.some(n=>n.title==='이유 저장됨 · 판정 #'+id+' 채택')", arg=pid)
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
        page.wait_for_function("id=>LINE.some(n=>n.title==='이유 저장됨 · 판정 #'+id+' 채택')", arg=pid)
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
        self.assertIn("판정 #%d 채택 취소 · 남은 판정 없음" % pid, titles)


# The open reason popover of page n's line: its field's text and focus, what it says of the draft (pv-pop-st) and of the keys
# (pv-pop-h), whom it is for (pv-pop-to), and its box against the line's - or null when none is open.
POP = """n=>{const l=document.querySelector('#doc .pv[data-page="'+n+'"]'), p=l&&l.querySelector('.pv-pop'); if(!p) return null;
  const f=p.querySelector('.pv-reason'), t=s=>{const e=p.querySelector(s); return e?e.textContent.replace(/\\s+/g,' ').trim():null;};
  const b=p.getBoundingClientRect(), lb=l.getBoundingClientRect();
  return {value: f.value, focused: document.activeElement===f, state: t('.pv-pop-st'), hint: t('.pv-pop-h'), to: t('.pv-pop-to'),
    clear: !!p.querySelector('[data-act="pv-reason-clear"]'), top: b.top, bottom: b.bottom, line: {top: lb.top, bottom: lb.bottom}};}"""
# The reason drafts this tab keeps (sessionStorage), by '<doc>:<pin id>': their text.
DRAFTS = """()=>{const o={}; for(let i=0;i<sessionStorage.length;i++){const k=sessionStorage.key(i); if(!k.startsWith('limnReason:'))continue;
  const d=JSON.parse(sessionStorage.getItem(k)).d||{}; Object.keys(d).forEach(x=>{o[x]=d[x].text;});} return o;}"""
KEY_MARKS = "n=>document.querySelectorAll('#doc .pv[data-page=\"'+n+'\"] button[data-kn]').length"


class ReasonKeys(VerdictBase):
    """The keys and the reason (the 0.4.34 RC's rule): no save opens the popover. Before it opens, 1-5 are the line's verdict
    keys (1 then 2 saves 보류); the line offers 'Enter 이유 쓰기' and Enter opens it with the focus; once open, every digit
    typed is text ('12월 값이 튐'), also one an input method composes."""

    def test_digits_before_enter_change_the_verdict_and_after_it_are_text(self):
        """1 saves 채택 and opens nothing; 2 saves 보류 (the 채택 pin keeps no note); Enter opens 보류's popover with the focus,
        the line's words carrying no key marks; '12월 값이 튐' is typed whole - no verdict is made - and Enter saves it."""
        page = self.on("fig")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 1))
        self.assertEqual(page.evaluate(ADD_TEXT, 1), "Enter 이유 쓰기")
        page.keyboard.press("2")
        page.wait_for_function("OPEN_ALL.length>=2")
        settle(page)
        pins = sorted(self.pins().values(), key=lambda p: p["id"])
        self.assertEqual([(p["verdict"], p["note"]) for p in pins], [("채택", ""), ("보류", "")])
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop .pv-reason')
        self.assertTrue(page.evaluate(REASON, 1)["focused"])
        self.assertEqual(page.evaluate(KEY_MARKS, 1), 0)
        page.keyboard.type("12월 값이 튐")
        settle(page)
        self.assertEqual(len(self.pins()), 2)
        self.assertEqual(page.evaluate(REASON, 1)["value"], "12월 값이 튐")
        self.assertNotIn("숫자", page.evaluate(POP, 1)["hint"])
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=pins[1]["id"])
        settle(page)
        self.assertEqual({p["verdict"]: p["note"] for p in self.pins().values()}, {"채택": "", "보류": "12월 값이 튐"})

    def test_esc_then_a_digit_changes_the_verdict_and_the_draft_follows(self):
        """1, Enter and '옮길 이유' typed; Esc lets the focus go (the draft stays) and 2 then saves 보류: the 채택 pin gets
        nothing and the popover, now for 보류, holds the draft and says where it came from."""
        page = self.on("fig")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop .pv-reason')
        page.keyboard.type("옮길 이유")
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.evaluate(KEY_MARKS, 1), 3)
        page.keyboard.press("2")
        page.wait_for_function("OPEN_ALL.length>=2")
        settle(page)
        one, two = sorted(self.pins())
        got = page.evaluate(POP, 1)
        self.assertEqual(
            (got["value"], got["to"]), ("옮길 이유", "판정 #%d 보류 이유 · #%d 채택에서 옮김" % (two, one))
        )
        self.assertEqual(page.evaluate(DRAFTS), {"fig:%d" % two: "옮길 이유"})
        self.assertEqual(self.pins()[one]["note"], "")

    def test_a_digit_in_an_empty_field_is_text_and_one_composed_too(self):
        """1 and Enter: in the empty field 2 is text (no verdict is made), and a keydown of 3 an input method is composing
        changes nothing either."""
        page = self.on("fig")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop .pv-reason')
        page.keyboard.press("2")
        page.evaluate(
            """()=>document.querySelector('#doc .pv-reason').dispatchEvent(new KeyboardEvent('keydown',{key:'3',bubbles:true,cancelable:true,isComposing:true}))"""
        )
        settle(page)
        self.assertEqual([p["verdict"] for p in self.pins().values()], ["채택"])
        self.assertEqual(page.evaluate(REASON, 1), {"focused": True, "value": "2", "placeholder": "이유 (선택)"})


class ReasonDrafts(VerdictBase):
    """An unsaved reason is never lost without a word (0.4.34 P1-2): drafts are kept per pin in this tab (sessionStorage);
    leaving the page with one asks first (beforeunload); with text Esc takes two presses, the first saying what the second
    does; [되돌리기] of a cancel or of the save chip brings the draft back with the pin; and a write that fails - refused, too
    long - keeps it."""

    def setUp(self):
        super().setUp()
        self.edits: list = []  # every POST /api/pins/N/edit body the viewer sent
        self.refuse_edit = 0  # how many to answer 400

    def route(self, route):
        rq = route.request
        path = urlparse(rq.url).path
        if rq.method == "POST" and path.startswith("/api/pins/") and path.endswith("/edit"):
            self.edits.append(json.loads(rq.post_data or "{}"))
            if self.refuse_edit:
                self.refuse_edit -= 1
                return route.fulfill(
                    status=400, headers={"content-type": "application/json"}, body='{"error": "안 됩니다"}'
                )
        return super().route(route)

    def keyed(self, page, text):
        """1 on page 1 (채택), Enter to open its reason popover, and text typed into its field; the pin's id."""
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length>=1")
        settle(page)
        (pid,) = self.pins()
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop .pv-reason')
        page.keyboard.type(text)
        settle(page)
        return pid

    def back_to_fig(self, page):
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function("DOC==='fig'&&META&&META.doc==='fig'&&document.querySelector('#p1')")
        settle(page)

    def test_esc_with_text_takes_two_presses(self):
        """'두 번 눌러야' typed, Esc: the field keeps the text and lets the focus go, saying the next Esc drops it; the draft
        is kept. Esc again: the field goes, the draft with it, and the pin has no note."""
        page = self.on("fig")
        pid = self.keyed(page, "두 번 눌러야")
        page.keyboard.press("Escape")
        settle(page)
        got = page.evaluate(POP, 1)
        self.assertEqual((got["value"], got["focused"]), ("두 번 눌러야", False))
        self.assertIn("Esc 한 번 더", got["hint"])
        self.assertEqual(page.evaluate(DRAFTS), {"fig:%d" % pid: "두 번 눌러야"})
        page.keyboard.press("Escape")
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertEqual(page.evaluate(DRAFTS), {})
        self.assertEqual(self.pins()[pid]["note"], "")

    def test_on_touch_close_takes_two_presses_with_text(self):
        """390x844: [이유 추가] tapped and '닫기 전' typed; [닫기] keeps the popover and says the next press drops it; the
        second drops it, and its draft."""
        page = self.on("fig", viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.evaluate("setSide(false)")
        settle(page)
        pid = self.press_page(page, 1, "채택")
        page.tap('#doc .pv[data-page="1"] button.pv-add')
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop .pv-reason')
        page.keyboard.type("닫기 전")
        page.tap('#doc .pv[data-page="1"] [data-act="pv-reason-close"]')
        settle(page)
        got = page.evaluate(POP, 1)
        self.assertEqual((got["value"], got["hint"]), ("닫기 전", "[닫기]를 한 번 더 누르면 이 이유를 버립니다"))
        page.tap('#doc .pv[data-page="1"] [data-act="pv-reason-close"]')
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertEqual(page.evaluate(DRAFTS), {})
        self.assertEqual(self.pins()[pid]["note"], "")

    def test_a_reload_asks_first_and_brings_the_draft_back(self):
        """A draft typed, then a reload: the browser asks first (beforeunload); after it no popover opens by itself (one
        restored far from the reading page opened out of sight) - the line marks the draft '초안 있음' and the status line
        says so with [보기], which puts the focus on that mark; Enter there opens the popover with the draft, marked
        '저장 안 됨', and Enter saves it."""
        page = self.on("fig")
        dialogs = []
        page.on("dialog", lambda d: (dialogs.append(d.type), d.accept()))
        pid = self.keyed(page, "새로 읽어도 남는 이유")
        page.reload()
        page.wait_for_function(booted(1), timeout=20000)
        self.back_to_fig(page)
        self.assertEqual(dialogs, ["beforeunload"])
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertTrue(
            page.evaluate("()=>LINE.some(n=>n.title==='저장 안 된 이유 초안 1건 · 줄의 [초안 있음]이 엽니다')")
        )
        page.locator("#status [data-act=notice-act]").filter(has_text="보기").click()
        page.wait_for_function("()=>document.activeElement&&document.activeElement.classList.contains('pv-draft')")
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop .pv-reason')
        got = page.evaluate(POP, 1)
        self.assertEqual((got["value"], got["state"], got["focused"]), ("새로 읽어도 남는 이유", "저장 안 됨", True))
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=pid)
        settle(page)
        self.assertEqual(self.pins()[pid]["note"], "새로 읽어도 남는 이유")
        self.assertEqual(page.evaluate(DRAFTS), {})

    def test_a_cancels_undo_brings_the_draft_back(self):
        """A draft typed, [판정 취소]: the popover goes with the verdict. The status line's [되돌리기]: the verdict and its
        popover with the draft are back."""
        page = self.on("fig")
        pid = self.keyed(page, "취소해도 돌아올 이유")
        page.locator(CANCEL % 1).click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=pid)
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        page.locator("#status [data-act=notice-act]").filter(has_text="되돌리기").click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id)", arg=pid)
        settle(page)
        self.assertEqual(page.evaluate(POP, 1)["value"], "취소해도 돌아올 이유")

    def test_the_save_chips_undo_offers_the_verdict_and_draft_back(self):
        """A draft typed, the save chip's [되돌리기]: the verdict is withdrawn and the status line offers [되돌리기], which
        brings the verdict and its draft back."""
        page = self.on("fig")
        pid = self.keyed(page, "칩으로 거둔 이유")
        page.locator('#doc .pv[data-page="1"]>.nt-chip [data-act="notice-act"]').click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=pid)
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        page.locator("#status [data-act=notice-act]").filter(has_text="되돌리기").click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id)", arg=pid)
        settle(page)
        self.assertEqual(page.evaluate(POP, 1)["value"], "칩으로 거둔 이유")

    def test_a_refused_write_on_moving_on_keeps_the_draft(self):
        """A draft typed and the manuscript opened, its write refused (400): the status line says so; back on the figure
        the line marks the draft '저장 안 됨', and pressing it opens the popover with the text."""
        page = self.on("fig")
        pid = self.keyed(page, "거절돼도 남는 이유")
        self.refuse_edit = 1
        page.evaluate("k=>switchDoc(k)", "ms")
        page.wait_for_function("DOC==='ms'&&META&&META.doc==='ms'")
        settle(page)
        self.assertTrue(page.evaluate("()=>LINE.some(n=>n.title.startsWith('이유 저장 실패'))"))
        self.assertEqual(page.evaluate(DRAFTS), {"fig:%d" % pid: "거절돼도 남는 이유"})
        self.back_to_fig(page)
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-open"]').click()
        settle(page)
        got = page.evaluate(POP, 1)
        self.assertEqual((got["value"], got["focused"], got["state"]), ("거절돼도 남는 이유", True, "저장 안 됨"))
        self.assertEqual(self.pins()[pid]["note"], "")

    def test_a_kept_draft_moves_to_a_new_verdict_on_its_line(self):
        """A draft kept after a refused write (the popover closed) and 보류 pressed on its line: the draft goes with the new
        verdict - the line marks it there - and nothing is written to 채택."""
        page = self.on("fig")
        one = self.keyed(page, "따라갈 이유")
        self.refuse_edit = 1
        page.evaluate("k=>switchDoc(k)", "ms")
        page.wait_for_function("DOC==='ms'&&META&&META.doc==='ms'")
        settle(page)
        self.back_to_fig(page)
        two = self.press_page(page, 1, "보류")
        self.assertEqual(page.evaluate(DRAFTS), {"fig:%d" % two: "따라갈 이유"})
        self.assertEqual(page.locator('#doc .pv[data-page="1"] button.pv-draft').inner_text(), "초안 있음")
        self.assertEqual(self.pins()[one]["note"], "")

    def test_a_too_long_reason_says_so_and_keeps_it(self):
        """Bob writes a note on the verdict meanwhile, so the reason can only be added (note_append, 2,000 characters at
        most); a 2,100-character draft and the manuscript opened: nothing is sent, the status line says it is too long
        (result first: '이유 저장 실패 · 덧붙일 이유는 2,000자까지입니다(지금 2,100자) — <대상>'), and the draft is kept."""
        page = self.on("fig")
        pid = self.keyed(page, "")
        page.keyboard.insert_text("가" * 2100)
        settle(page)
        rev = self.pins()[pid]["rev"]
        code, _ = self.call("POST", "/api/pins/%d/edit" % pid, {"note": "밥의 메모", "base_rev": rev}, BOB)
        self.assertEqual(code, 200)
        self.reload(page)
        page.evaluate("k=>switchDoc(k)", "ms")
        page.wait_for_function("DOC==='ms'&&META&&META.doc==='ms'")
        settle(page)
        self.assertEqual(self.edits, [])
        self.assertTrue(
            page.evaluate(
                "()=>LINE.some(n=>n.title==='이유 저장 실패 · 덧붙일 이유는 2,000자까지입니다(지금 2,100자)')"
            )
        )
        self.assertEqual(len(page.evaluate(DRAFTS)["fig:%d" % pid]), 2100)
        self.assertEqual(self.pins()[pid]["note"], "밥의 메모")


# Each word's aria-pressed on page n's line, in file order.
PRESSED = "n=>[...document.querySelectorAll('#doc .pv[data-page=\"'+n+'\"] button.vd-b')].map(b=>b.getAttribute('aria-pressed'))"
# The background of page n's word key and the colour token tok as the browser computes it.
FILL = """([n, key, tok])=>{const b=document.querySelector('#doc .pv[data-page="'+n+'"] button[data-key="'+key+'"]'), p=document.createElement('i');
  p.style.color='var('+tok+')'; document.body.appendChild(p); const c=getComputedStyle(p).color; p.remove();
  return {bg: getComputedStyle(b).backgroundColor, tok: c};}"""
WORD = '#doc .pv[data-page="%d"] button[data-key="%s"]'


class OnOff(VerdictBase):
    """The page line's words are a toggle (0.4.34 P2-3): the current verdict's word is pressed (aria-pressed, filled - a
    confirm word with the destructive fill); pressing it takes the person's own open verdict back as [판정 취소] does, with
    [되돌리기]; pressing the current word never saves a second pin of it. Someone else's or a handled verdict stays, and
    the status line says why."""

    def test_the_current_word_is_pressed_and_pressing_it_takes_it_back(self):
        """채택 saved: its word is pressed and filled with the primary colour, the others not. Pressed again: no second pin
        - the verdict goes to the Trash, the line reads '판정 없음' with no word pressed, and the status line says '판정 #a
        채택 취소 · 남은 판정 없음' with [되돌리기], which brings it back pressed."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        page.evaluate(END_CHIPS)
        page.mouse.move(1, 1)  # the fill at rest, not under the hover
        settle(page)
        self.assertEqual(page.evaluate(PRESSED, 1), ["true", "false", "false"])
        fill = page.evaluate(FILL, [1, "채택", "--primary"])
        self.assertEqual(fill["bg"], fill["tok"])
        page.locator(WORD % (1, "채택")).click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=a)
        settle(page)
        self.assertEqual(self.pins(), {})
        self.assertEqual((page.evaluate(LINE, 1)["text"], page.evaluate(PRESSED, 1)), ("판정 없음", ["false"] * 3))
        self.assertIn(
            {
                "title": "판정 #%d 채택 취소 · 남은 판정 없음" % a,
                "desc": "Deployment calendar",
                "act": "되돌리기",
                "kind": "ok",
            },
            page.evaluate(STATUS),
        )
        page.locator("#status [data-act=notice-act]").filter(has_text="되돌리기").click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id)", arg=a)
        settle(page)
        self.assertEqual(page.evaluate(PRESSED, 1), ["true", "false", "false"])

    def test_a_pressed_confirm_word_has_the_destructive_fill_and_one_press_takes_it_back(self):
        """3 twice saves 삭제: its word is pressed with the destructive fill. One more press of it - no arming - takes it
        back."""
        page = self.on("fig")
        page.keyboard.press("3")
        page.keyboard.press("3")
        page.wait_for_function("OPEN_ALL.length===1")
        page.keyboard.press("Escape")
        page.evaluate(END_CHIPS)
        settle(page)
        self.assertEqual(page.evaluate(PRESSED, 1), ["false", "false", "true"])
        fill = page.evaluate(FILL, [1, "삭제", "--destructive"])
        self.assertEqual(fill["bg"], fill["tok"])
        page.locator(WORD % (1, "삭제")).click()
        page.wait_for_function("OPEN_ALL.length===0")
        settle(page)
        self.assertEqual(self.pins(), {})

    def test_a_key_on_the_current_word_takes_it_back(self):
        """1 saves 채택 (no popover opens); 1 again takes the verdict back."""
        page = self.on("fig")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        self.assertIsNone(page.evaluate(REASON, 1))
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===0")
        settle(page)
        self.assertEqual(self.pins(), {})

    def test_a_double_press_on_the_pressed_word_takes_back_one(self):
        """Two 채택 verdicts of Alice's on page 1 (saved before 0.4.34): a double click on the pressed 채택 takes back the
        newer only - the earlier 채택, pressed now, waits out the second click - and a later press takes it back too."""
        a = verdict_as(self, ALICE, 1, "채택")
        b = verdict_as(self, ALICE, 1, "채택")
        page = self.on("fig", n_open=2)
        page.locator(WORD % (1, "채택")).dblclick()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=b)
        settle(page)
        self.assertEqual(set(self.pins()), {a})
        self.assertEqual(page.evaluate(PRESSED, 1), ["true", "false", "false"])
        page.wait_for_function("s=>!document.querySelector(s).hasAttribute('aria-disabled')", arg=WORD % (1, "채택"))
        page.locator(WORD % (1, "채택")).click()
        page.wait_for_function("OPEN_ALL.length===0")
        settle(page)
        self.assertEqual(self.pins(), {})

    def test_someone_elses_or_a_handled_current_word_stays_and_says_why(self):
        """Bob's 채택 on page 1 is pressed on Alice's line; her press saves nothing and the status line says why. Her own 보류
        on page 2, closed by an agent (검토 대기), is pressed too; a press saves nothing and says a handled verdict is taken
        back from its card."""
        b = verdict_as(self, BOB, 1, "채택")
        page = self.on("fig", n_open=1)
        self.assertEqual(page.evaluate(PRESSED, 1), ["true", "false", "false"])
        page.locator(WORD % (1, "채택")).click()
        settle(page)
        self.assertEqual(set(self.pins()), {b})
        self.assertTrue(
            page.evaluate(
                "id=>LINE.some(n=>n.title==='지금 판정 #'+id+' 채택 그대로 · 다른 사람의 판정은 여기서 거두지 않습니다')",
                b,
            )
        )
        d = self.press_page(page, 2, "보류")
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % d, {"reply": "done"}, AGENT)[0], 200)
        self.reload(page)
        page.evaluate(END_CHIPS)
        settle(page)
        self.assertEqual(page.evaluate(PRESSED, 2), ["false", "true", "false"])
        page.locator(WORD % (2, "보류")).click()
        settle(page)
        self.assertEqual(set(self.pins()), {b, d})
        self.assertTrue(page.evaluate("()=>LINE.some(n=>n.title.endsWith('처리된 판정은 카드의 [지우기]로 거둡니다'))"))


class RapidPresses(VerdictBase):
    """Presses while a page line's save is out are not dropped (0.4.34 P2-6): the line shows the word it saves pressed and
    '… 저장 중…', the last press wins, and it is applied when the save is done - the line ends on the last word pressed."""

    def test_the_last_press_wins_and_a_word_already_saved_makes_no_second_pin(self):
        """채택, then 보류 and 채택 while 채택's save is held: the line says '채택 저장 중…' with 채택 pressed; released, one pin
        - 채택 - and nothing else is saved."""
        page = self.on("fig")
        self.held = []
        page.locator(WORD % (1, "채택")).click()
        page.wait_for_function("PV_BUSY.size===1")
        page.locator(WORD % (1, "보류")).click()
        page.locator(WORD % (1, "채택")).click()
        self.assertEqual(
            page.evaluate(
                "()=>document.querySelector('#doc .pv[data-page=\"1\"] .pv-busy').textContent.replace(/\\s+/g,' ').trim()"
            ),
            "· 채택 저장 중…",
        )
        self.assertEqual(page.evaluate(PRESSED, 1), ["true", "false", "false"])
        self.release()
        page.wait_for_function("PV_BUSY.size===0&&OPEN_ALL.length===1")
        settle(page)
        self.assertEqual([p["verdict"] for p in self.pins().values()], ["채택"])

    def test_another_last_press_is_saved_after_the_save(self):
        """채택, then 보류 while it is held: the line shows 보류 pressed (the next intent); released, 보류 is saved after
        채택 and is the current verdict."""
        page = self.on("fig")
        self.held = []
        page.locator(WORD % (1, "채택")).click()
        page.wait_for_function("PV_BUSY.size===1")
        page.locator(WORD % (1, "보류")).click()
        self.assertEqual(page.evaluate(PRESSED, 1), ["false", "true", "false"])
        self.release()
        page.wait_for_function("PV_BUSY.size===0&&OPEN_ALL.length===2")
        settle(page)
        pins = sorted(self.pins().values(), key=lambda p: p["id"])
        self.assertEqual([p["verdict"] for p in pins], ["채택", "보류"])
        self.assertEqual(page.evaluate(LINE, 1)["pin"], str(pins[1]["id"]))


class ReasonEdit(VerdictBase):
    """A saved reason is changed or cleared from the line (0.4.34 P2-5): its text on the line (a check and its first line) opens the popover with
    it; Enter writes the changed text over it; [지우기] clears it with [되돌리기]; Enter on an empty field keeps it."""

    def saved(self, page, text):
        pid = self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.type(text)
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=pid)
        settle(page)
        return pid

    def test_the_saved_reason_opens_again_and_a_change_replaces_it(self):
        page = self.on("fig")
        pid = self.saved(page, "처음 이유")
        open_reason(page, 1)
        got = page.evaluate(POP, 1)
        self.assertEqual(
            (got["value"], got["state"], got["clear"], got["focused"]), ("처음 이유", "저장됨", True, True)
        )
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type("고친 이유")
        self.assertEqual(page.evaluate(POP, 1)["state"], "저장 안 됨")
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='고친 이유')", arg=pid)
        settle(page)
        self.assertEqual(self.pins()[pid]["note"], "고친 이유")
        self.assertIsNone(page.evaluate(POP, 1))

    def test_clear_takes_the_reason_away_and_its_undo_brings_it_back(self):
        page = self.on("fig")
        pid = self.saved(page, "지울 이유")
        open_reason(page, 1)
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-clear"]').click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&!p.note)", arg=pid)
        settle(page)
        self.assertEqual(self.pins()[pid]["note"], "")
        self.assertTrue(page.evaluate("id=>LINE.some(n=>n.title==='판정 #'+id+' 채택 이유 지움')", pid))
        page.locator("#status [data-act=notice-act]").filter(has_text="되돌리기").click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='지울 이유')", arg=pid)

    def test_enter_on_an_empty_field_keeps_the_saved_reason(self):
        page = self.on("fig")
        pid = self.saved(page, "남길 이유")
        open_reason(page, 1)
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.press("Delete")
        page.keyboard.press("Enter")
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertEqual(self.pins()[pid]["note"], "남길 이유")


class ReasonPopover(VerdictBase):
    """The reason is written in a popover over the line (0.4.34): it stands above the line, never pushes the page or makes
    the line taller; it marks a draft '저장 안 됨' and a written reason with a check."""

    def test_the_popover_stands_over_the_line_and_never_makes_it_taller(self):
        page = self.on("fig")
        self.press_page(page, 1, "채택")
        page.evaluate(END_CHIPS)
        settle(page)
        box = """()=>{const l=document.querySelector('#doc .pv[data-page="1"]').getBoundingClientRect(), p=document.getElementById('p2').getBoundingClientRect();
          return {h: l.height, page2: p.top};}"""
        before = page.evaluate(box)
        open_reason(page, 1)
        got = page.evaluate(POP, 1)
        self.assertLessEqual(got["bottom"], got["line"]["top"])
        self.assertEqual(page.evaluate(box), before)
        self.assertEqual(got["state"], "")
        page.keyboard.type("한 줄")
        self.assertEqual(page.evaluate(POP, 1)["state"], "저장 안 됨")
        page.keyboard.press("Enter")
        page.wait_for_function("()=>OPEN_ALL.some(p=>p.note)")
        settle(page)
        self.assertEqual(
            page.evaluate("()=>document.querySelector('#doc .pv[data-page=\"1\"] .pv-note').textContent"), "한 줄"
        )
        open_reason(page, 1)
        self.assertEqual(page.evaluate(POP, 1)["state"], "저장됨")


class ArmWait(VerdictBase):
    """An armed confirm word says how long it waits, and nothing keeps saying it waits once it has let go (0.4.34 P3-13)."""

    def test_the_wait_is_said_while_armed_and_gone_after(self):
        page = self.on("fig")
        news = "()=>document.querySelector('#sr-news').textContent"
        arm = "()=>{const a=document.querySelector('#doc .pv[data-page=\"1\"] .pv-arm'); return a?a.textContent.replace(/\\s+/g,' ').trim():null;}"
        page.locator(WORD % (1, "삭제")).click()
        self.assertEqual(page.evaluate(arm), "· 4초 안에 한 번 더 누르면 저장")
        self.assertEqual(page.evaluate(news), "삭제 — 4초 안에 한 번 더 누르면 저장합니다")
        self.assertIsNone(page.locator(WORD % (1, "삭제")).get_attribute("data-tip"))
        page.locator('#doc .pv[data-page="1"] .pv-s').click()  # a press elsewhere
        settle(page)
        self.assertIsNone(page.evaluate(arm))
        self.assertEqual(page.evaluate(news), "삭제 확정을 풀었습니다")
        page.locator(WORD % (1, "삭제")).click()
        page.wait_for_function("()=>!document.querySelector('#doc .pv .pv-arm')", timeout=6000)
        self.assertEqual(page.evaluate(news), "삭제 확정을 풀었습니다")
        page.locator(WORD % (1, "삭제")).click()
        page.locator(WORD % (1, "삭제")).click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        self.assertNotIn("한 번 더 누르면", page.evaluate(news))


class ReviewRound(VerdictBase):
    """The review of PR #304: a change of a saved reason is written against the rev it was opened at (a note changed
    elsewhere is never written over - Enter or [지우기]); [지우기] keeps the popover and its draft until it succeeds; a
    page line's pending save is scoped to its document; Tab inside the popover keeps it open and a close gives the focus
    back to what opened it; the pressed word carries a check and its context; [접기] keeps the draft behind '초안 있음';
    an editable saved reason carries a pencil and is named '저장된 이유 수정'."""

    def setUp(self):
        super().setUp()
        self.lose_edit = 0  # how many POST /api/pins/N/edit to lose on the network
        self.held_doc: str | None = None  # hold POST /api/pin of this document only (self.held collects them)

    def route(self, route):
        rq = route.request
        path = urlparse(rq.url).path
        if rq.method == "POST" and path.startswith("/api/pins/") and path.endswith("/edit") and self.lose_edit:
            self.lose_edit -= 1
            return route.abort()
        if rq.method == "POST" and path == "/api/pin" and self.held_doc:
            if json.loads(rq.post_data or "{}").get("doc") != self.held_doc:
                return self.forward(route)  # another document's save goes through at once
            self.held = self.held or []
            self.held.append(route)
            return None
        return super().route(route)

    def saved(self, page, text):
        """채택 on page 1 with text written as its reason; the pin's id."""
        pid = self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.type(text)
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=pid)
        settle(page)
        return pid

    def bob_writes(self, pid, note):
        rev = self.pins()[pid]["rev"]
        self.assertEqual(self.call("POST", "/api/pins/%d/edit" % pid, {"note": note, "base_rev": rev}, BOB)[0], 200)

    def test_a_change_never_writes_over_a_note_changed_since_it_opened(self):
        """The saved reason opened and changed; meanwhile Bob changes the note and the list is read again (the viewer
        knows the newer rev). Enter writes nothing over Bob's note: the draft is kept, the popover shows his note with
        [그 위에 쓰기], and the status line says so. [그 위에 쓰기] then writes the text over it."""
        page = self.on("fig")
        pid = self.saved(page, "처음 이유")
        open_reason(page, 1)
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type("고친 이유")
        self.bob_writes(pid, "밥이 바꾼 메모")
        self.reload(page)
        page.locator('#doc .pv[data-page="1"] .pv-reason').focus()
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop-cf')
        settle(page)
        self.assertEqual(self.pins()[pid]["note"], "밥이 바꾼 메모")
        self.assertEqual(page.evaluate(POP, 1)["value"], "고친 이유")
        self.assertIn("밥이 바꾼 메모", page.locator('#doc .pv[data-page="1"] .pv-pop-cf').inner_text())
        self.assertEqual(page.evaluate(DRAFTS), {"fig:%d" % pid: "고친 이유"})
        self.assertTrue(
            page.evaluate("()=>LINE.some(n=>n.title==='이유 저장 안 함 · 그사이 다른 곳에서 메모가 바뀌었습니다')")
        )
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-reapply"]').click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='고친 이유')", arg=pid)
        settle(page)
        self.assertEqual(self.pins()[pid]["note"], "고친 이유")
        self.assertIsNone(page.evaluate(POP, 1))

    def test_clear_never_clears_a_note_changed_since_it_opened(self):
        """The saved reason opened; Bob changes the note and the list is read again; [지우기] clears nothing - Bob's note
        stays and the popover shows it."""
        page = self.on("fig")
        pid = self.saved(page, "지울 이유")
        open_reason(page, 1)
        self.bob_writes(pid, "밥의 새 메모")
        self.reload(page)
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-clear"]').click()
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop-cf')
        settle(page)
        self.assertEqual(self.pins()[pid]["note"], "밥의 새 메모")

    def test_a_failed_clear_keeps_the_popover_and_its_draft(self):
        """The saved reason opened and edited, then [지우기] lost on the network: the note is unchanged, the popover is
        still open with the edited text and the draft is kept; the status line says the clear failed with [다시 시도],
        which clears it once the network is back."""
        page = self.on("fig")
        pid = self.saved(page, "남을 이유")
        open_reason(page, 1)
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type("편집 중")
        self.lose_edit = 1
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-clear"]').click()
        page.wait_for_function("()=>LINE.some(n=>n.title.startsWith('이유 지우기 실패'))")
        settle(page)
        self.assertEqual(self.pins()[pid]["note"], "남을 이유")
        self.assertEqual(page.evaluate(POP, 1)["value"], "편집 중")
        self.assertEqual(page.evaluate(DRAFTS), {"fig:%d" % pid: "편집 중"})
        page.locator("#status [data-act=notice-act]").filter(has_text="다시 시도").click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&!p.note)", arg=pid)
        settle(page)
        self.assertEqual(self.pins()[pid]["note"], "")
        self.assertIsNone(page.evaluate(POP, 1))

    def test_a_held_save_on_one_document_does_not_hold_another_documents_line(self):
        """채택 on the figure's page 1 held unanswered; the PDF opened and 보류 pressed on its page 1: it saves at once,
        not queued behind the figure's save; released, the figure's save ends without taking the PDF's away."""
        page = self.on("fig")
        self.held_doc = "fig"
        page.locator(WORD % (1, "채택")).click()
        page.wait_for_function("()=>PV_BUSY.size===1")
        for _ in range(
            200
        ):  # the figure's pin request itself is held (a save whose pick answers after a switch saves nothing)
            if self.held:
                break
            page.wait_for_timeout(25)
        self.assertEqual(len(self.held or []), 1)
        page.evaluate("k=>switchDoc(k)", "rv")
        page.wait_for_function(
            "DOC==='rv'&&META&&META.doc==='rv'&&document.querySelector('#doc .pv[data-page=\"1\"] button[data-key]:not([aria-disabled])')"
        )
        page.wait_for_timeout(300)  # the figure's save is still held: the network never idles (no settle)
        page.locator(WORD % (1, "보류")).click()
        page.wait_for_function("()=>OPEN_ALL.some(p=>p.doc==='rv'&&p.verdict==='보류')", timeout=10000)
        self.held_doc = None
        self.release()
        page.wait_for_function("()=>PV_BUSY.size===0", timeout=10000)
        settle(page)
        self.assertEqual(
            sorted((p["doc"], p["verdict"]) for p in self.pins().values()), [("fig", "채택"), ("rv", "보류")]
        )

    def test_tab_stays_inside_and_a_close_gives_the_focus_back(self):
        """[이유 추가] opens an empty popover with the focus; Tab moves to its buttons and it stays open (a labelled group).
        [닫기] closes it and the focus is back on the line's [이유 추가]."""
        page = self.on("fig")
        self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.press("Tab")
        settle(page)
        self.assertIsNotNone(page.evaluate(POP, 1))
        self.assertTrue(page.evaluate("()=>!!document.activeElement.closest('#doc .pv-pop')"))
        self.assertEqual(
            page.evaluate(
                "()=>{const p=document.querySelector('#doc .pv-pop'); return [p.getAttribute('role'), document.getElementById(p.getAttribute('aria-labelledby')).textContent];}"
            ),
            ["group", "판정 #1 채택 이유"],
        )
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-close"]').focus()
        page.keyboard.press("Enter")
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertTrue(page.evaluate("()=>document.activeElement.classList.contains('pv-add')"))

    def test_the_pressed_word_has_a_check_and_says_how_to_take_it_back(self):
        """채택 saved: its word carries a check, is described by '지금 채택 판정 · 다시 누르면 판정 취소', which shows over the
        words right after the press and on the keyboard's focus - the line's height does not change."""
        page = self.on("fig")
        self.press_page(page, 1, "채택")
        page.evaluate(END_CHIPS)
        settle(page)
        b = WORD % (1, "채택")
        got = page.evaluate(
            """s=>{const b=document.querySelector(s), d=document.getElementById(b.getAttribute('aria-describedby'));
              return {check: !!b.querySelector('.ic-check'), desc: d && d.textContent};}""",
            b,
        )
        self.assertEqual(got, {"check": True, "desc": "지금 채택 판정 · 다시 누르면 판정 취소"})
        hint = "()=>{const h=document.querySelector('#doc .pv[data-page=\"1\"] .pv-onhint'); return getComputedStyle(h).display!=='none';}"
        h0 = page.evaluate("()=>document.querySelector('#doc .pv[data-page=\"1\"]').getBoundingClientRect().height")
        self.assertTrue(page.evaluate(hint))  # right after the press
        page.wait_for_function(
            "()=>!document.querySelector('#doc .pv[data-page=\"1\"]').classList.contains('pv-onshow')", timeout=6000
        )
        page.mouse.move(1, 1)
        self.assertFalse(page.evaluate(hint))
        page.focus(b)
        page.keyboard.press("Shift+Tab")
        page.keyboard.press("Tab")
        self.assertTrue(page.evaluate(hint))
        self.assertEqual(
            page.evaluate("()=>document.querySelector('#doc .pv[data-page=\"1\"]').getBoundingClientRect().height"), h0
        )

    def test_fold_keeps_the_draft_behind_a_mark_that_opens_it(self):
        """'접어 둘 이유' typed, [접기]: the popover goes, nothing is written, the draft is kept and the line shows '초안 있음'
        with the focus; pressed, the popover is back with the text."""
        page = self.on("fig")
        pid = self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.type("접어 둘 이유")
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-fold"]').click()
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertEqual(self.pins()[pid]["note"], "")
        self.assertEqual(page.evaluate(DRAFTS), {"fig:%d" % pid: "접어 둘 이유"})
        self.assertEqual(
            page.evaluate(
                "()=>[document.activeElement.className.includes('pv-draft'), document.activeElement.textContent]"
            ),
            [True, "초안 있음"],
        )
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop .pv-reason')
        self.assertEqual(page.evaluate(POP, 1)["value"], "접어 둘 이유")

    def test_an_editable_saved_reason_has_a_pencil_and_its_name(self):
        page = self.on("fig")
        self.saved(page, "연필 이유")
        got = page.evaluate(
            """()=>{const b=document.querySelector('#doc .pv[data-page="1"] button.pv-note');
              return {pencil: !!b.querySelector('.ic-pencil'), name: b.getAttribute('aria-label'), tip: b.dataset.tip};}"""
        )
        self.assertEqual(
            got, {"pencil": True, "name": "연필 이유 — 저장된 이유 수정, 판정 #1", "tip": "저장된 이유 수정"}
        )


class RcFixes(VerdictBase):
    """The 0.4.34 RC's test round, the line's logic and reasons: keys and Enter (each item's number in its name's docstring),
    focus that stays on its page, a jump still gliding, queued presses across documents, a verdict taken back while its
    reason is typed, folded drafts, lost answers, conflicts shown whole, rev-guarded replaces, a restored but superseded
    verdict, the card's rival note, Tab around the popover, a card's neighbour, quiet moved undos, names that hold their
    words, the line's own [되돌리기], announced drafts and #N to its card."""

    def setUp(self):
        super().setUp()
        self.edits: list = []  # every POST /api/pins/N/edit body the viewer sent
        self.swallow: set = (
            set()
        )  # request kinds ('pin', 'edit', 'drop') whose next answer is lost after the server wrote
        self.lose: set = set()  # request kinds lost on the network before the server sees them
        self.held_doc: str | None = None  # hold POST /api/pin of this document only (self.held collects them)

    def route(self, route):
        rq = route.request
        path = urlparse(rq.url).path
        kind = (
            "pin"
            if path == "/api/pin"
            else "edit"
            if path.endswith("/edit")
            else "drop"
            if path.endswith("/drop")
            else None
        )
        if rq.method == "POST" and kind:
            if kind == "edit":
                self.edits.append(json.loads(rq.post_data or "{}"))
            if kind == "pin" and self.held_doc and json.loads(rq.post_data or "{}").get("doc") == self.held_doc:
                self.held = self.held or []
                self.held.append(route)
                return None
            if kind in self.lose:
                self.lose.discard(kind)
                return route.abort()
            if kind in self.swallow:
                self.swallow.discard(kind)
                self.forward(_Swallowed(route))
                return route.abort()
        return super().route(route)

    def keyed_open(self, page, n=1, key="1"):
        """Key `key` on page n (the reading page) saves a verdict; Enter opens its reason popover with the focus; the pin's id."""
        before = set(self.pins())
        page.keyboard.press(key)
        page.wait_for_function("n=>OPEN_ALL.length>=n", arg=len(before) + 1)
        settle(page)
        (pid,) = set(self.pins()) - before
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="%d"] .pv-pop .pv-reason' % n)
        return pid

    def saved_reason(self, page, text):
        pid = self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.type(text)
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=pid)
        settle(page)
        return pid

    def bob_note(self, pid, note):
        rev = self.pins()[pid]["rev"]
        self.assertEqual(self.call("POST", "/api/pins/%d/edit" % pid, {"note": note, "base_rev": rev}, BOB)[0], 200)

    def test_2_tab_from_the_pdf_area_goes_to_the_reading_line(self):
        """(2) Page 2 read (zoomed, taller than the area), the focus on the PDF area: Tab goes to page 2's line, and the
        pages do not scroll."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        page.evaluate("searchToPage()")
        top = page.evaluate("document.querySelector('#left').scrollTop")
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(FOCUS_AT)[0], 2)
        self.assertEqual(page.evaluate("document.querySelector('#left').scrollTop"), top)

    def test_3_a_key_while_a_jump_glides_is_not_taken(self):
        """(3) A smooth jump from page 1 to page 2 under way: 2 is not taken (nothing saved, the status line says why);
        once the pages rest, 2 saves 보류 on page 2."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        page.evaluate(
            "()=>{const L=document.querySelector('#left'),r=document.getElementById('p2').getBoundingClientRect(),lr=L.getBoundingClientRect(); L.scrollTo({top:L.scrollTop+r.top-lr.top,behavior:'smooth'});}"
        )
        page.wait_for_function("()=>PV_GLIDE")
        page.keyboard.press("2")
        page.wait_for_timeout(50)
        self.assertEqual(self.pins(), {})
        self.assertTrue(page.evaluate("()=>LINE.some(n=>n.title==='쪽으로 가는 중이라 판정 키를 받지 않았습니다')"))
        page.wait_for_function("()=>!pvAutoScrolling()", timeout=5000)
        settle(page)
        page.keyboard.press("2")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        (pin,) = self.pins().values()
        self.assertEqual((pin["verdict"], page.evaluate(LINE, 2)["pin"]), ("보류", str(pin["id"])))

    def test_4_a_press_queued_on_one_document_is_saved_after_a_switch_away_and_back(self):
        """(4) 채택 on the figure's page 1 held; 보류 pressed meanwhile (queued); the PDF opened and the figure again; then
        the held save answers: 채택 and then 보류 are both saved on the figure, 보류 current - nothing dropped silently."""
        page = self.on("fig")
        self.held_doc = "fig"
        page.locator(WORD % (1, "채택")).click()
        for _ in range(200):
            if self.held:
                break
            page.wait_for_timeout(25)
        page.locator(WORD % (1, "보류")).click()
        self.assertEqual(page.evaluate("()=>[...PV_NEXT.values()].map(x=>x.key)"), ["보류"])
        page.evaluate("k=>switchDoc(k)", "rv")
        page.wait_for_function("DOC==='rv'&&META&&META.doc==='rv'")
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function(
            "DOC==='fig'&&META&&META.doc==='fig'&&document.querySelector('#doc .pv[data-page=\"1\"]')"
        )
        self.held_doc = None
        self.release()
        page.wait_for_function("()=>OPEN_ALL.filter(p=>p.doc==='fig').length===2&&PV_BUSY.size===0", timeout=10000)
        settle(page)
        got = sorted((p["id"], p["verdict"]) for p in self.pins().values())
        self.assertEqual([v for _, v in got], ["채택", "보류"])
        self.assertEqual(page.evaluate(LINE, 1)["pin"], str(got[1][0]))

    def test_5_a_verdict_taken_back_elsewhere_keeps_the_reason_and_the_keys_typed_after(self):
        """(5) A reason being typed when the verdict is taken back in another tab: after the list is read the popover goes,
        the text is the page's draft ('초안 있음'), the status line says so, the focus is on the mark, and a 2 typed on
        makes no verdict; the next verdict saved there takes the draft."""
        page = self.on("fig")
        pid = self.keyed_open(page)
        page.keyboard.type("33개 건물에서 손해")
        self.assertEqual(self.call("POST", "/api/pins/%d/drop" % pid, {})[0], 200)
        self.reload(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertEqual(page.evaluate(DRAFTS), {"fig:p1": "33개 건물에서 손해"})
        self.assertTrue(
            page.evaluate(
                "id=>LINE.some(n=>n.title==='판정 #'+id+'이 다른 곳에서 거둬졌습니다 · 쓰던 이유는 이 쪽의 초안으로 남겼습니다')",
                pid,
            )
        )
        self.assertEqual(page.evaluate("()=>document.activeElement.textContent"), "초안 있음")
        page.keyboard.press("2")
        settle(page)
        self.assertEqual(self.pins(), {})
        page.mouse.move(1, 1)
        page.mouse.down()
        page.mouse.up()
        two = self.press_page(page, 1, "보류")
        self.assertEqual(page.evaluate(DRAFTS), {"fig:%d" % two: "33개 건물에서 손해"})

    def test_6_a_folded_draft_stays_folded_after_a_reload_and_is_never_written_by_moving_on(self):
        """(6) A draft folded with [접기], then a reload: the popover does not open - the line says '초안 있음' - and reading
        another page and back sends nothing."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        pid = self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.type("접어 둔 이유")
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-fold"]').click()
        settle(page)
        page.on("dialog", lambda d: d.accept())
        page.reload()
        page.wait_for_function(booted(1), timeout=20000)
        page.evaluate("k=>switchDoc(k)", "fig")
        page.wait_for_function("DOC==='fig'&&META&&META.doc==='fig'&&document.querySelector('#p1')")
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertEqual(page.locator('#doc .pv[data-page="1"] button.pv-draft').inner_text(), "초안 있음")
        self.assertTrue(
            page.evaluate("()=>LINE.some(n=>n.title==='저장 안 된 이유 초안 1건 · 줄의 [초안 있음]이 엽니다')")
        )
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        page.evaluate(SCROLL, [1, "top"])
        settle(page)
        self.assertEqual(self.edits, [])
        self.assertEqual(self.pins()[pid]["note"], "")

    def test_7_a_clear_whose_answer_was_lost_is_done_on_retry(self):
        """(7) [지우기] written but its answer lost: [다시 시도] reads the note, finds it empty and calls the clear done - no
        false conflict, and no [그 위에 쓰기] that would bring the reason back."""
        page = self.on("fig")
        pid = self.saved_reason(page, "지울 이유")
        open_reason(page, 1)
        self.swallow.add("edit")
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-clear"]').click()
        page.wait_for_function("()=>LINE.some(n=>n.title.startsWith('이유 지우기 실패'))")
        settle(page)
        self.assertEqual(self.pins()[pid]["note"], "")
        page.locator("#status [data-act=notice-act]").filter(has_text="다시 시도").click()
        page.wait_for_function("id=>!document.querySelector('#doc .pv-pop')", arg=pid)
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertFalse(page.evaluate("()=>LINE.some(n=>n.title.startsWith('이유 저장 안 함'))"))
        self.assertTrue(page.evaluate("id=>LINE.some(n=>n.title==='판정 #'+id+' 채택 이유 지움')", pid))

    def test_8_9_20_a_conflict_shows_the_whole_note_and_a_replace_keeps_its_rev(self):
        """(8, 20) The saved reason changed while Bob writes a two-line note: Enter shows his whole note (both lines) and the
        line shows his note too. (9) He then empties it; [그 위에 쓰기] writes the text as the whole note against the rev it
        read - never an append - and a 409 meanwhile shows the newer note again."""
        page = self.on("fig")
        pid = self.saved_reason(page, "처음 이유")
        open_reason(page, 1)
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type("내 이유")
        self.bob_note(pid, "에이전트 메모\n에이전트 덧붙임 2")
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop-cf')
        settle(page)
        box = page.locator('#doc .pv[data-page="1"] .pv-pop-cf-note').inner_text()
        self.assertIn("에이전트 덧붙임 2", box)
        self.assertEqual(page.locator('#doc .pv[data-page="1"] .pv-note').inner_text(), "에이전트 메모")
        self.bob_note(pid, "")
        self.edits = []
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-reapply"]').click()  # read: his two lines; now empty
        page.wait_for_function(
            "()=>document.querySelector('#doc .pv-pop-cf-note')&&document.querySelector('#doc .pv-pop-cf-note').textContent==='(빈 메모)'"
        )
        self.assertEqual(self.pins()[pid]["note"], "")
        self.assertTrue(all("note_append" not in b for b in self.edits), self.edits)
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-reapply"]').click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='내 이유')", arg=pid)
        self.assertEqual(self.pins()[pid]["note"], "내 이유")
        self.assertTrue(all("note_append" not in b and "base_rev" in b for b in self.edits), self.edits)

    def test_9_a_new_reason_reads_the_note_before_it_writes(self):
        """(9) A new reason for a verdict whose note Bob had written and then emptied - the list still holding his note: the
        write reads the pin first and puts the reason into the empty note, with no '(추가 hh:mm)' stamp."""
        page = self.on("fig")
        pid = self.press_page(page, 1, "채택")
        self.bob_note(pid, "밥의 메모")
        self.reload(page)
        self.bob_note(pid, "")
        page.evaluate("p=>pvReasonOpen(p,true)", 1)
        page.wait_for_selector('#doc .pv[data-page="1"] .pv-pop .pv-reason')
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type("새 이유")
        page.evaluate(
            "()=>{PV_REASON.base=''; PV_REASON.mode='add'; PV_REASON.rev=-1;}"
        )  # a new reason, as the list read it
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='새 이유')", arg=pid)
        self.assertEqual(self.pins()[pid]["note"], "새 이유")

    def test_10_a_restored_verdict_superseded_meanwhile_says_so_and_opens_no_popover(self):
        """(10) Alice's 채택 with a reason being typed, taken back; Bob then saves 보류 there; her [되돌리기] restores 채택, but
        the status line says Bob's #N 보류 is current and no popover opens over his line."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.type("취소 뒤 되살릴 이유")
        page.locator(CANCEL % 1).click()
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=a)
        settle(page)
        b = verdict_as(self, BOB, 1, "보류")
        self.reload(page)
        page.locator("#status [data-act=notice-act]").filter(has_text="되돌리기").first.click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id)", arg=a)
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertTrue(
            page.evaluate(
                "([a,b])=>LINE.some(n=>n.title==='판정 #'+a+' 채택 되살림 · 지금 판정은 Bob Park의 #'+b+' 보류')",
                [a, b],
            )
        )

    def test_11_the_cards_edit_shows_a_rival_note_and_needs_an_explicit_overwrite(self):
        """(11) A verdict card's edit with a changed note; meanwhile an agent adds to the note: [저장] writes nothing - the
        banner shows the note now, the agent's line included - and a second [저장] neither; [내 메모로 덮어쓰기] does."""
        page = self.on("fig")
        pid = self.saved_reason(page, "처음")
        page.evaluate("id=>openEdit(id)", pid)
        page.wait_for_selector(".pin.editing .e-note")
        page.fill(".pin.editing .e-note", "카드에서 고친 메모")
        code, _ = self.call("POST", "/api/pins/%d/edit" % pid, {"note_append": "에이전트 덧붙임"}, AGENT)
        self.assertEqual(code, 200)
        theirs = self.pins()[pid]["note"]
        for _ in range(2):
            page.evaluate("saveEdit()")
            settle(page)
            self.assertEqual(self.pins()[pid]["note"], theirs)
        self.assertIn(
            "에이전트 덧붙임", page.evaluate("()=>[...BANNERS.values()].map(n=>n.title+' — '+n.desc).join('\\n')")
        )
        page.locator("[data-act=notice-act]").filter(has_text="내 메모로 덮어쓰기").click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='카드에서 고친 메모')", arg=pid)

    def test_12_tab_past_the_popover_comes_back_to_its_line(self):
        """(12) Tab from the popover's last control goes to its line's first control, not the next page's line; the
        popover stays open with its draft."""
        page = self.on("fig")
        self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.type("탭 순서")
        page.evaluate(END_CHIPS)  # no save chip in the row: the next stop after the popover is the next page's line
        settle(page)
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-save"]').focus()
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pin-ref"])
        self.assertEqual(page.evaluate(POP, 1)["value"], "탭 순서")

    def test_13_a_cards_delete_by_keyboard_hands_the_focus_to_its_neighbour(self):
        """(13) Two verdict cards; [지우기] pressed with the keyboard on one: the focus goes to the other card's number."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        b = self.press_page(page, 2, "보류")
        page.evaluate(END_CHIPS)
        settle(page)
        page.focus('.pin.card[data-id="%d"] [data-act="drop"]' % a)
        page.keyboard.press("Enter")
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=a)
        self.assertEqual(page.evaluate("()=>Number(document.activeElement.closest('.pin').dataset.id)"), b)

    def test_14_a_moved_undo_is_not_read_out_again(self):
        """(14) A second save while the first's chip stands: the first's undo moves to the status line quietly - the line's
        live text never says the first save again - and the news says the second."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        b = self.press_page(page, 2, "보류")
        self.assertNotIn("#%d" % a, page.evaluate("document.querySelector('#status .st-sr').textContent"))
        self.assertIn("#%d" % b, page.evaluate("document.querySelector('#sr-news').textContent"))

    def test_15_a_verdict_whose_answer_was_lost_is_a_save_not_a_failure(self):
        """(15) The page line's verdict written but its answer lost: the list is read, the verdict is there - no
        '판정 저장 실패', one pin, its save chip - so a second press is not needed and makes no duplicate."""
        page = self.on("fig")
        self.swallow.add("pin")
        page.locator(WORD % (1, "채택")).click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        self.assertEqual([p["verdict"] for p in self.pins().values()], ["채택"])
        self.assertFalse(page.evaluate("()=>LINE.some(n=>n.title.startsWith('판정 저장 실패'))"))
        self.assertEqual(page.evaluate(PRESSED, 1), ["true", "false", "false"])

    def test_15_a_composer_verdict_whose_answer_was_lost_is_a_save(self):
        """(15) The composer's 채택 written but its answer lost: no failure banner and no [다시 저장] to duplicate it."""
        page = self.on("ms")
        self.open_composer(page)
        self.swallow.add("pin")
        page.locator('#c-verdict-row button[data-key="채택"]').click()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        self.assertEqual(len(self.pins()), 1)
        self.assertFalse(page.evaluate("()=>[...BANNERS.values()].some(n=>n.save)"))

    def test_16_a_cancel_whose_answer_was_lost_is_done_and_not_reported_as_someone_elses(self):
        """(16) [판정 취소] written but its answer lost: the take-back is said as done (no '판정 취소 실패' left), and the next
        list does not say someone deleted it. A name's particle follows its sound."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        self.swallow.add("drop")
        page.locator(CANCEL % 1).click()
        page.wait_for_function("id=>LINE.some(n=>n.title.startsWith('판정 #'+id+' 채택 취소'))", arg=a)
        self.reload(page)
        titles = [n["title"] for n in page.evaluate(STATUS)]
        self.assertFalse([t for t in titles if t.startswith("판정 취소 실패") or "삭제함" in t], titles)
        self.assertEqual(
            page.evaluate(
                "()=>['Bob','Alice','Agent B','Team L','김민수','박준','Kim 2'].map(n=>josaName(n,'이','가'))"
            ),
            ["이", "가", "가", "이", "가", "이", "가"],
        )

    def test_17_18_19_while_saving_and_the_names(self):
        """(17) While a reason is being written there is no inert [접기], and every aria-describedby in the lines points at
        something. (18) The draft mark's and [판정 취소]'s names hold their words. (19) A keyboard take-back leaves the focus
        on the line's own [되돌리기], which brings the verdict back."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.type("쓰는 중")
        page.evaluate(
            "()=>{const f=document.querySelector('#doc .pv-reason'); PV_REASON.writing=new Promise(()=>{}); pvRefill(1);}"
        )
        self.assertEqual(page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-fold"]').count(), 0)
        dangling = """()=>[...document.querySelectorAll('#doc .pv [aria-describedby]')].flatMap(e=>e.getAttribute('aria-describedby').split(' ')).filter(id=>!document.getElementById(id))"""
        self.assertEqual(page.evaluate(dangling), [])
        page.evaluate("()=>{PV_REASON.writing=null; pvReasonFold();}")
        settle(page)
        self.assertTrue(
            page.locator('#doc .pv[data-page="1"] button.pv-draft').get_attribute("aria-label").startswith("초안 있음")
        )
        self.assertIn("판정 취소", page.locator(CANCEL % 1).get_attribute("aria-label"))
        page.focus(CANCEL % 1)
        page.keyboard.press("Enter")
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=a)
        settle(page)
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-undo"])
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id)", arg=a)

    def test_19_the_line_number_by_keyboard_goes_to_its_card(self):
        """(19) Enter on the line's #N moves the focus to that pin's card."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        page.focus('#doc .pv[data-page="1"] .pv-ref')
        page.keyboard.press("Enter")
        page.wait_for_function(
            "id=>{const a=document.activeElement; return !!a&&!!a.closest&&!!a.closest('.pin[data-id=\"'+id+'\"]');}",
            arg=a,
        )


# The network's latency: every request the page makes to /api/ waits `ms` before it goes (the fast typist's 150ms server).
SLOW_API = """ms=>{const f=window.fetch; window.fetch=function(u,o){const p=typeof u==='string'?u:u.url;
  if(/\\/api\\//.test(p))return new Promise(r=>setTimeout(r,ms)).then(()=>f.call(this,u,o)); return f.call(this,u,o);};}"""


class RcRound2(VerdictBase):
    """The RC's second test round: a fast typist's key and Enter while the save is out, focus left on a page scrolled out
    of view, Tab from the pages after a press, a key take-back's focus, Shift+Tab around the popover, no description
    while writing, and a retried reason's failure that goes."""

    def setUp(self):
        super().setUp()
        self.swallow: set = set()  # request kinds ('edit') whose next answer is lost after the server wrote
        self.held_edit: list | None = None  # POST /api/pins/N/edit held unanswered while not None

    def route(self, route):
        rq = route.request
        path = urlparse(rq.url).path
        if rq.method == "POST" and path.endswith("/edit") and "edit" in self.swallow:
            self.swallow.discard("edit")
            self.forward(_Swallowed(route))
            return route.abort()
        if rq.method == "POST" and path.endswith("/edit") and self.held_edit is not None:
            self.held_edit.append(route)
            return None
        return super().route(route)

    def drop_all(self):
        for pid in list(self.pins()):
            self.call("POST", "/api/pins/%d/drop" % pid, {})

    def test_a_key_then_enter_while_the_save_is_out_writes_the_text_on_that_verdict(self):
        """(P1-A, the testers' matrix) No latency and 150ms on every request; 1, Enter 30-600ms later, the text typed 50ms a
        key and Enter: one 채택 verdict whose note is the text - an Enter while the save was out opened the popover bound to
        that verdict, a save landing while it was typed in kept its focus, and no digit typed after Enter was a verdict key."""
        for lat in (0, 150):
            for gap in (30, 80, 150, 300, 600):
                for text in ("값이 튐", "12월 값이 튐"):
                    with self.subTest(lat=lat, gap=gap, text=text):
                        self.drop_all()
                        page = self.on("fig")
                        page.evaluate(SLOW_API, lat)
                        page.keyboard.press("1")
                        page.wait_for_timeout(gap)
                        page.keyboard.press("Enter")
                        page.keyboard.type(text, delay=50)
                        page.keyboard.press("Enter")
                        page.wait_for_function("t=>OPEN_ALL.some(p=>p.note===t)", arg=text, timeout=10000)
                        settle(page)
                        self.assertEqual([(p["verdict"], p["note"]) for p in self.pins().values()], [("채택", text)])
                        page.context.close()

    def test_a_held_save_keeps_the_text_and_a_failed_one_leaves_it_as_the_pages_draft(self):
        """(P1-A) 1 with its save held, Enter, '3번 패널' typed: the popover waits for the verdict's number with the text;
        released, it is that verdict's draft. A save that fails meanwhile leaves the text as the page's draft."""
        page = self.on("fig")
        self.held = []
        page.keyboard.press("1")
        page.wait_for_function("PV_BUSY.size===1")
        page.keyboard.press("Enter")
        page.keyboard.type("3번 패널")
        self.assertEqual(page.evaluate(POP, 1)["value"], "3번 패널")
        self.assertEqual(page.evaluate(POP, 1)["to"], "채택 판정 이유 · 판정 저장 중")
        self.release()
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        (pid,) = self.pins()
        self.assertEqual(page.evaluate(DRAFTS), {"fig:%d" % pid: "3번 패널"})
        self.assertEqual((page.evaluate(POP, 1)["value"], page.evaluate(POP, 1)["focused"]), ("3번 패널", True))
        page.keyboard.press("Escape")
        page.keyboard.press("Escape")
        settle(page)
        self.drop_all()
        self.reload(page)
        self.fail_pin = 1
        page.locator(WORD % (1, "보류")).focus()
        page.keyboard.press("Escape")
        page.evaluate("searchToPage()")
        page.keyboard.press("2")
        page.keyboard.press("Enter")
        page.keyboard.type("실패해도 남는 이유")
        page.wait_for_function("()=>LINE.some(n=>n.title.startsWith('판정 저장 실패'))", timeout=10000)
        settle(page)
        self.assertEqual(page.evaluate(DRAFTS).get("fig:p1"), "실패해도 남는 이유")

    def test_focus_on_a_page_scrolled_out_of_view_goes_to_the_pages(self):
        """(P1-B) A reason saved on page 1 leaves the focus on its pencil; the pages scroll to page 2 (tall, zoomed): the
        focus goes to the PDF area, and Enter opens page 2's reason - typed text goes to page 2, page 1's note stays."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        a = self.press_page(page, 1, "채택")
        b = self.press_page(page, 2, "보류")
        page.evaluate(SCROLL, [1, "top"])
        settle(page)
        open_reason(page, 1)
        page.keyboard.type("1쪽 이유")
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=a)
        settle(page)
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-reason-open"])
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        self.assertEqual(page.evaluate("document.activeElement.id"), "left")
        page.keyboard.press("Enter")
        page.wait_for_selector('#doc .pv[data-page="2"] .pv-pop .pv-reason')
        page.keyboard.type("2쪽 이유")
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=b)
        settle(page)
        self.assertEqual((self.pins()[a]["note"], self.pins()[b]["note"]), ("1쪽 이유", "2쪽 이유"))

    def test_enter_on_an_off_screen_lines_control_before_the_focus_moved_acts_on_the_reading_page(self):
        """(P1-B, the race) The focus on page 1's pencil, the pages scrolled to page 2 and Enter at once (before a frame):
        page 1's reason does not open off-screen - page 2's does."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        a = self.press_page(page, 1, "채택")
        self.press_page(page, 2, "보류")
        page.evaluate(SCROLL, [1, "top"])
        settle(page)
        open_reason(page, 1)
        page.keyboard.type("원래 이유")
        page.keyboard.press("Enter")
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=a)
        settle(page)
        page.evaluate(
            """([n])=>{const L=document.querySelector('#left'),lr=L.getBoundingClientRect(),r=document.getElementById('p'+n).getBoundingClientRect(); L.scrollTop+=r.top-lr.top;
              document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));}""",
            [2],
        )
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertIsNotNone(page.evaluate(POP, 2))
        self.assertEqual(self.pins()[a]["note"], "원래 이유")

    def test_after_wheeling_away_a_key_and_enter_write_on_the_reading_page(self):
        """(P1-B, the testers' V1 and V2) Page 1's reason saved with the mouse leaves the focus on its pencil; the wheel takes
        the pages to page 2. Enter there opens no popover off-screen (page 2 has no verdict); 1 then Enter 30ms later saves
        채택 on page 2 and writes the text typed next as its reason - page 1's note stays."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        page.evaluate(SCROLL, [1, "top"])
        settle(page)
        a = self.press_page(page, 1, "채택")
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-open"]').click()
        page.keyboard.type("원래 이유 (A쪽)")
        page.locator('#doc .pv[data-page="1"] [data-act="pv-reason-save"]').click()
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note)", arg=a)
        settle(page)
        page.locator('#doc .pv[data-page="1"] .pv-note').focus()
        box = page.locator("#left").bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        for _ in range(80):
            if page.evaluate("pvReadingAt()") == 2:
                break
            page.mouse.wheel(0, 300)
            page.wait_for_timeout(60)
        settle(page)
        self.assertEqual(page.evaluate("document.activeElement.id"), "left")
        page.keyboard.press("Enter")
        settle(page)
        self.assertEqual(page.evaluate("()=>document.querySelectorAll('#doc .pv-pop').length"), 0)
        page.keyboard.press("1")
        page.wait_for_timeout(30)
        page.keyboard.press("Enter")
        page.keyboard.type("B쪽에 쓰려던 이유", delay=40)
        page.keyboard.press("Enter")
        page.wait_for_function("()=>OPEN_ALL.some(p=>p.note==='B쪽에 쓰려던 이유')", timeout=10000)
        settle(page)
        got = {p["id"]: (p["verdict"], p["note"]) for p in self.pins().values()}
        self.assertEqual(got.pop(a), ("채택", "원래 이유 (A쪽)"))
        self.assertEqual(list(got.values()), [("채택", "B쪽에 쓰려던 이유")])

    def test_tab_from_the_pages_goes_to_the_reading_line(self):
        """(1) Page 2 zoomed and read; a press on the page, a press on the margin beside it and the focus sent off a line
        scrolled away each leave the focus on the PDF area or on nothing: Tab goes to page 2's line, without scrolling."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        self.press_page(page, 1, "채택")
        self.press_page(page, 2, "보류")
        page.evaluate(END_CHIPS)

        def at_two():
            page.evaluate(SCROLL, [2, "top"])
            settle(page)
            page.evaluate("document.activeElement&&document.activeElement.blur()")
            return page.locator("#p2").bounding_box()

        def press_page():
            box = at_two()
            page.mouse.click(box["x"] + 20, box["y"] + 60)

        def press_margin():
            box, left = at_two(), page.locator("#left").bounding_box()
            page.mouse.click((left["x"] + box["x"]) / 2, box["y"] + 60)

        def scrolled_away():
            page.evaluate(SCROLL, [1, "top"])
            settle(page)
            page.locator('#doc .pv[data-page="1"] [data-key="채택"]').focus()
            page.evaluate(SCROLL, [2, "top"])

        for name, enter in (
            ("page", press_page),
            ("margin", press_margin),
            ("away", scrolled_away),
        ):
            with self.subTest(entry=name):
                enter()
                settle(page)
                top = page.evaluate("document.querySelector('#left').scrollTop")
                self.assertIn(
                    page.evaluate("document.activeElement.id||document.activeElement.tagName"), ("BODY", "left")
                )
                page.keyboard.press("Tab")
                self.assertEqual(page.evaluate(FOCUS_AT)[0], 2)
                self.assertEqual(page.evaluate("document.querySelector('#left').scrollTop"), top)

    def test_a_key_take_back_leaves_the_focus_on_the_lines_undo(self):
        """(3) 1 saves 채택; 1 again takes it back - the focus is on the line's [되돌리기], and Enter there restores it."""
        page = self.on("fig")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===0")
        settle(page)
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-undo"])
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.length===1")

    def test_a_cards_delete_by_keyboard_keeps_the_focus_on_its_neighbour_after_the_list_is_read(self):
        """(4) A verdict card's [지우기] by keyboard: the focus is on the other card's number, also after the list is read
        again."""
        page = self.on("fig")
        a = self.press_page(page, 1, "채택")
        b = self.press_page(page, 2, "보류")
        page.evaluate(END_CHIPS)
        settle(page)
        page.focus('.pin.card[data-id="%d"] [data-act="drop"]' % a)
        page.keyboard.press("Enter")
        page.wait_for_function("id=>!OPEN_ALL.some(p=>p.id===id)", arg=a)
        settle(page)
        self.reload(page)
        self.assertEqual(
            page.evaluate("()=>{const p=document.activeElement.closest('.pin'); return p?Number(p.dataset.id):null;}"),
            b,
        )

    def test_shift_tab_keeps_to_the_line_and_its_popover(self):
        """(5) The popover open on page 2 (read): Shift+Tab from the line's first control goes to the popover's last, not
        the previous page; the popover stays with its draft."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        self.press_page(page, 2, "보류")
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        page.evaluate(END_CHIPS)
        open_reason(page, 2)
        page.keyboard.type("뒤로 탭")
        page.focus('#doc .pv[data-page="2"] .pv-ref')
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate(FOCUS_AT), [2, "pv-reason-save"])
        self.assertEqual(page.evaluate(POP, 2)["value"], "뒤로 탭")

    def test_no_description_while_writing_and_a_retried_reason_clears_its_failure(self):
        """(6) While a reason is written (its write held) its field and group point at no description. (7) A reason whose
        answer was lost, added and then edited: [다시 시도] finds it written - its failure goes, none is left beside the
        success."""
        page = self.on("fig")
        pid = self.press_page(page, 1, "채택")
        open_reason(page, 1)
        page.keyboard.type("쓰는 중")
        self.held_edit = []
        page.keyboard.press("Enter")
        page.wait_for_function("()=>PV_REASON&&!!PV_REASON.writing")
        described = "()=>[...document.querySelectorAll('#doc .pv-pop,#doc .pv-pop .pv-reason')].map(e=>e.getAttribute('aria-describedby'))"
        self.assertEqual(page.evaluate(described), [None, None])
        held, self.held_edit = self.held_edit, None
        for r in held:
            self.forward(r)
        page.wait_for_function("id=>OPEN_ALL.some(p=>p.id===id&&p.note==='쓰는 중')", arg=pid)
        settle(page)
        failed = "()=>LINE.some(n=>n.title.startsWith('이유 저장 실패'))"
        two = self.press_page(page, 2, "보류")
        page.evaluate(END_CHIPS)
        for text, opener in (("잃은 답", None), ("고친 답", '#doc .pv[data-page="2"] .pv-note')):
            with self.subTest(text=text):
                if opener:
                    page.locator(opener).click()
                else:
                    open_reason(page, 2)
                field = page.locator('#doc .pv[data-page="2"] .pv-reason')
                field.fill(text)
                self.swallow.add("edit")
                field.press("Enter")
                page.wait_for_function(failed)
                settle(page)
                self.assertEqual(self.pins()[two]["note"], text)
                page.locator("#status [data-act=notice-act]").filter(has_text="다시 시도").click()
                page.wait_for_function("()=>!document.querySelector('#doc .pv-pop')")
                settle(page)
                self.assertFalse(page.evaluate(failed))
                self.assertEqual(self.pins()[two]["note"], text)


class RcRound3(VerdictBase):
    """The RC's third round: a pending verdict's failed save guards the keys typed on, a popover moved away from while its
    verdict's save is out is written when it answers, the focus leaves the page the reading page left, a digit take-back
    from outside the line, Tab into the pages from the section strip, and Esc on the popover's buttons."""

    def take_held(self, page, timeout_ms=10000):
        """The held POST /api/pin routes, once the save has sent one (its pick comes first); stops holding."""
        waited = 0
        while not self.held:
            if waited >= timeout_ms:
                self.fail("the save never sent its pin")
            page.wait_for_timeout(20)
            waited += 20
        held, self.held = self.held, None
        return held

    def release_held(self, page):
        """Answer the held POST /api/pin once it is sent, and stop holding."""
        for r in self.take_held(page):
            self.forward(r)

    def fail_held(self, page):
        """Lose the held POST /api/pin on the network once it is sent, and stop holding."""
        held = self.take_held(page)
        for r in held:
            r.abort()

    def wait_note(self, page, pid_note, timeout_ms=10000):
        """Waits until the server holds one pin whose note is pid_note; that pin."""
        waited = 0
        while waited < timeout_ms:
            got = [p for p in self.pins().values() if p.get("note") == pid_note]
            if got:
                return got[0]
            page.wait_for_timeout(50)
            waited += 50
        self.fail("no pin with the note %r: %r" % (pid_note, self.pins()))

    def test_a_failed_pending_save_guards_the_keys_typed_on(self):
        """(1) 1, Enter, '이유' typed while the save is out; the save fails: the text is page 1's draft, the focus is on its
        '초안 있음', and a 2 typed on is not a verdict key (said)."""
        page = self.on("fig")
        self.held = []
        page.keyboard.press("1")
        page.wait_for_function("PV_BUSY.size===1")
        page.keyboard.press("Enter")
        page.keyboard.type("이유")
        self.fail_held(page)
        page.wait_for_function("()=>LINE.some(n=>n.title.startsWith('판정 저장 실패 · 쓰던 이유는'))", timeout=10000)
        settle(page)
        self.assertEqual(page.evaluate(DRAFTS), {"fig:p1": "이유"})
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-reason-open"])
        page.keyboard.press("2")
        settle(page)
        self.assertEqual(self.pins(), {})
        self.assertTrue(
            page.evaluate("()=>LINE.some(n=>n.title.startsWith('이유 칸이 닫혀 숫자를 판정으로 받지 않았습니다'))")
        )

    def test_a_failed_pending_save_leaves_a_focus_elsewhere_where_it_is(self):
        """(1) The same with the focus moved to the section strip's page button before the save fails: it stays there and the
        keys are not guarded."""
        page = self.on("fig")
        self.held = []
        page.keyboard.press("1")
        page.wait_for_function("PV_BUSY.size===1")
        page.keyboard.press("Enter")
        page.keyboard.type("이유")
        page.focus("#section-page")
        self.fail_held(page)
        page.wait_for_function("()=>PV_BUSY.size===0", timeout=10000)
        settle(page)
        self.assertEqual(page.evaluate("document.activeElement.id"), "section-page")
        self.assertFalse(page.evaluate("PV_KEY_GUARD"))
        self.assertEqual(page.evaluate(DRAFTS), {"fig:p1": "이유"})

    def test_a_pending_reason_moved_away_from_is_written_when_its_save_answers(self):
        """(2) 1, Enter, the text and Enter while the save is held; the person moves on - to page 2, or to another document -
        before it answers: the popover closes with the text kept as page 1's draft, and once the save answers the text is
        that verdict's note. Failing instead, the draft stays and the status line says so."""
        for away, ok in (("page", True), ("doc", True), ("page", False)):
            with self.subTest(away=away, ok=ok):
                for pid in list(self.pins()):
                    self.call("POST", "/api/pins/%d/drop" % pid, {})
                page = self.on("fig")
                page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
                settle(page)
                page.evaluate(SCROLL, [1, "top"])
                settle(page)
                self.held = []
                page.keyboard.press("1")
                page.wait_for_function("PV_BUSY.size===1")
                page.keyboard.press("Enter")
                page.keyboard.type("옮긴 뒤 이유")
                page.keyboard.press("Enter")
                if away == "page":
                    page.evaluate(SCROLL, [2, "top"])
                else:
                    page.evaluate("switchDoc('rv')")
                    page.wait_for_function("DOC==='rv'&&META&&META.doc==='rv'")
                page.wait_for_function(
                    "()=>!PV_REASON&&!document.querySelector('#doc .pv-pop')"
                )  # the save is held: no settle
                self.assertEqual(page.evaluate("()=>document.querySelectorAll('#doc .pv-pop').length"), 0)
                self.assertEqual(page.evaluate(DRAFTS), {"fig:p1": "옮긴 뒤 이유"})
                if ok:
                    self.release_held(page)
                    pin = self.wait_note(page, "옮긴 뒤 이유")
                    self.assertEqual((pin["verdict"], len(self.pins())), ("채택", 1))
                    page.wait_for_function(
                        "()=>!Object.keys(JSON.parse(sessionStorage.getItem(Object.keys(sessionStorage).find(k=>k.startsWith('limnReason:')))||'{}').d||{}).length"
                    )
                else:
                    self.fail_held(page)
                    page.wait_for_function(
                        "()=>LINE.some(n=>n.title.startsWith('판정 저장 실패 · 쓰던 이유는'))", timeout=10000
                    )
                    settle(page)
                    self.assertEqual(self.pins(), {})
                    self.assertEqual(page.evaluate(DRAFTS), {"fig:p1": "옮긴 뒤 이유"})
                page.context.close()

    def test_the_focus_leaves_the_page_the_reading_page_left_even_in_view(self):
        """(3) Page 1's word focused; the pages scroll just past its end, so page 2 is read while page 1's line still shows:
        the focus goes to the PDF area, and Space - also when read before that frame - presses nothing on page 1."""
        past = """([space])=>{const L=document.querySelector('#left'),lr=L.getBoundingClientRect(),r=document.getElementById('p2').getBoundingClientRect();
          L.scrollTop+=r.top-lr.top-readingDepth(L)+12; const b=document.querySelector('#doc .pv[data-page="1"]').getBoundingClientRect();
          if(space){const t=document.activeElement; for(const k of ['keydown','keyup'])t.dispatchEvent(new KeyboardEvent(k,{key:' ',code:'Space',bubbles:true,cancelable:true}));}
          return [b.bottom>lr.top&&b.top<lr.bottom, pvReadingAt()];}"""
        a = 0
        for race in (False, True):
            with self.subTest(race=race):
                page = self.on("fig")
                page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
                settle(page)
                page.evaluate(SCROLL, [1, "top"])
                settle(page)
                a = a or self.press_page(page, 1, "채택")
                page.evaluate(END_CHIPS)
                page.evaluate(SCROLL, [1, "top"])
                settle(page)
                page.evaluate(
                    """()=>document.querySelector('#doc .pv[data-page="1"] [data-key="채택"]').focus({preventScroll:true})"""
                )
                settle(page)
                self.assertEqual(page.evaluate("PV_READ"), 1)
                self.assertEqual(page.evaluate(past, [race]), [True, 2])
                settle(page)
                self.assertEqual(page.evaluate("document.activeElement.id"), "left")
                page.keyboard.press(" ")
                settle(page)
                self.assertEqual([p["id"] for p in self.pins().values()], [a])
                self.assertEqual(page.evaluate("()=>document.querySelectorAll('#doc .pv-pop').length"), 0)
                page.context.close()

    def test_a_digit_take_back_from_outside_the_line_puts_the_focus_on_its_undo(self):
        """(4) 1 saves 채택; the focus moved to the section strip's page button, 1 takes it back: the focus is on the line's
        [되돌리기], and Enter restores the verdict (not the page list)."""
        page = self.on("fig")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.focus("#section-page")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===0")
        settle(page)
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-undo"])
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.length===1")
        self.assertTrue(page.evaluate("document.querySelector('#page-pop').hidden"))

    def test_tab_from_the_section_strip_goes_to_the_reading_line(self):
        """(5) Page 2 zoomed and read; Tab from the section strip's page button goes to page 2's line - not to page 1's,
        which scrolled there - and the pages stay where they are."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        self.press_page(page, 1, "채택")
        self.press_page(page, 2, "보류")
        page.evaluate(END_CHIPS)
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        page.focus("#section-page")
        top = page.evaluate("document.querySelector('#left').scrollTop")
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(FOCUS_AT)[0], 2)
        self.assertEqual(page.evaluate("document.querySelector('#left').scrollTop"), top)

    def test_esc_on_the_popovers_buttons_is_the_fields_esc(self):
        """(6) With a draft, Esc on [접기] lets the focus out with the popover and its text kept; Esc again drops it. Without
        one, Esc on [닫기] closes it, the focus on the line."""
        page = self.on("fig")
        self.press_page(page, 1, "채택")
        page.evaluate(END_CHIPS)
        open_reason(page, 1)
        page.keyboard.type("버튼에서 Esc")
        page.focus('#doc .pv[data-page="1"] [data-act="pv-reason-fold"]')
        page.keyboard.press("Escape")
        self.assertEqual(page.evaluate("document.activeElement.id"), "left")
        self.assertEqual(page.evaluate(POP, 1)["value"], "버튼에서 Esc")
        page.keyboard.press("Escape")
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertEqual(page.evaluate(DRAFTS), {})
        open_reason(page, 1)
        page.focus('#doc .pv[data-page="1"] [data-act="pv-reason-close"]')
        page.keyboard.press("Escape")
        settle(page)
        self.assertIsNone(page.evaluate(POP, 1))
        self.assertEqual(page.evaluate(FOCUS_AT)[0], 1)


class RcRound4(VerdictBase):
    """The RC's fourth round: no scroll of the area when the reading page changes (a jump glides to its page, a slow scroll
    passes a page's end on a phone), a key save after a digit take-back keeps the focus on its line, and a digit pressed from
    the section strip then Enter opens the reason."""

    PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}

    def tall(self, page):
        """Page 1 zoomed to more than two screens on the phone, the pages at their top, the lines stacked."""
        page.evaluate("setSide(false)")
        page.evaluate("()=>{setK(K*2.5,false); ZOOMED=true; document.querySelector('#left').scrollTop=0;}")
        settle(page)
        page.evaluate("pvStick()")
        settle(page)
        self.assertEqual(page.evaluate("PV_READ"), 1)
        self.assertTrue(
            page.evaluate("document.querySelector('#doc .pv[data-page=\"1\"]').classList.contains('pv-stack')")
        )

    def test_a_jump_glides_to_its_page_on_a_phone(self):
        """390x844: a smooth jump to page 2 crosses the reading line's change from page 1 to page 2 on the way and ends with
        page 2 at the area's top, as an instant jump puts it (a scroll making up for page 1's line losing its name row ended
        the glide where it was: an outline jump from page 4 to 40 stopped on page 5)."""
        page = self.on("fig", **self.PHONE)
        self.tall(page)
        page.evaluate("goPage(2)")
        page.wait_for_function(
            "()=>{const L=document.querySelector('#left'),t=L.scrollTop; if(window.__t===t){window.__n=(window.__n||0)+1;} else {window.__n=0; window.__t=t;} return window.__n>=10;}",
            polling=50,
            timeout=10000,
        )
        settle(page)
        got = page.evaluate(
            "()=>{const L=document.querySelector('#left'),a=L.scrollTop; document.getElementById('p2').scrollIntoView({behavior:'instant'}); const b=L.scrollTop; L.scrollTop=a; return {read:PV_READ,off:a-b};}"
        )
        self.assertEqual(got["read"], 2, got)
        self.assertLess(abs(got["off"]), 2, got)

    def test_a_slow_scroll_passes_the_pages_end_on_a_phone(self):
        """390x844: the pages scrolled 4px a frame down past page 1's end and back up: the reading page changes once each way
        and never flips back, the area never scrolls against the person, and the lines keep their heights (with a scroll
        making up for the line above, the reading page flipped between two pages 466 times in 14 slow drags and the pages
        never passed the end)."""
        page = self.on("fig", **self.PHONE)
        self.tall(page)
        page.evaluate(
            "()=>{const L=document.querySelector('#left'),p=document.getElementById('p2'); L.scrollTop+=p.getBoundingClientRect().top-L.getBoundingClientRect().top-L.clientHeight;}"
        )
        settle(page)
        walk = """async dir=>{const L=document.querySelector('#left'),l1=document.querySelector('#doc .pv[data-page="1"]'); const seq=[PV_READ],hs=new Set(); let back=0,prev=L.scrollTop;
          for(let i=0;i<300;i++){L.scrollTop+=4*dir; await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
            if((L.scrollTop-prev)*dir<-0.5)back++; prev=L.scrollTop; if(PV_READ!==seq[seq.length-1])seq.push(PV_READ); hs.add(Math.round(l1.getBoundingClientRect().height));}
          return {seq,back,heights:[...hs]};}"""
        down = page.evaluate(walk, 1)
        self.assertEqual((down["seq"], down["back"], len(down["heights"])), ([1, 2], 0, 1), down)
        up = page.evaluate(walk, -1)
        self.assertEqual((up["seq"], up["back"], len(up["heights"])), ([2, 1], 0, 1), up)

    def test_a_line_keeps_its_rows_whichever_page_is_read_at_every_zoom(self):
        """1280x900 and 390x844, page widths 260-760px in 12px steps: page 1's line has the same rows and height while page 1
        is read and while page 2 is - the identifier the reading line shows counts in the choice for every line (a line that
        stacked only as the reading line, at a zoom near its threshold, shrank when the reading page left and moved the pages
        under it)."""
        for dev in ({"viewport": {"width": 1280, "height": 900}}, self.PHONE):
            with self.subTest(dev=dev["viewport"]["width"]):
                page = self.on("fig", **dev)
                page.evaluate("setSide(false)")
                bad = page.evaluate(
                    """async()=>{const L=document.querySelector('#left'),l1=()=>document.querySelector('#doc .pv[data-page="1"]'),out=[];
                      const frame=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
                      const read=async n=>{const p=document.getElementById('p'+n); L.scrollTop+=p.getBoundingClientRect().top-L.getBoundingClientRect().top-(n===1?0:2);
                        await frame(); pvStick(); await frame(); return [PV_READ,l1().classList.contains('pv-stack'),Math.round(l1().getBoundingClientRect().height)];};
                      for(let w=260;w<=760;w+=12){setK(w/META.pages[0].pt_w,false); ZOOMED=true; await frame();
                        const a=await read(1),b=await read(2); if(a[0]!==1||b[0]!==2)continue; if(a[1]!==b[1]||a[2]!==b[2])out.push([w,a,b]);}
                      return out;}"""
                )
                self.assertEqual(bad, [])
                page.context.close()

    def test_a_key_save_after_a_digit_take_back_keeps_the_focus_on_its_line(self):
        """1 saves 채택, 1 takes it back (the focus on the line's [되돌리기]), 2 saves 보류: the line no longer offers the
        take-back's [되돌리기] and the focus is on the line's way to the reason - not on nothing, where PageDown no longer
        scrolled ([이유 추가] had stepped out beside the offer and took no focus)."""
        page = self.on("fig")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===0")
        settle(page)
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-undo"])
        page.keyboard.press("2")
        page.wait_for_function("OPEN_ALL.length===1&&!PV_BUSY.size")
        settle(page)
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-reason-open"])
        self.assertFalse(page.evaluate("!!document.querySelector('#doc .pv[data-page=\"1\"] .pv-undo')"))

    def test_a_digit_on_an_open_card_editors_button_is_the_editors(self):
        """1 saves 채택; its card's editor open with the focus on its [저장]: 2 saves nothing and leaves the focus there (it
        took the focus to the pages and saved 보류, and the Enter after it opened nothing - the editor holds Enter)."""
        page = self.on("fig")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===1")
        settle(page)
        pid = page.evaluate("OPEN_ALL[0].id")
        page.evaluate("id=>openEdit(id)", pid)
        settle(page)
        page.focus(".edit .b-esave")
        page.keyboard.press("2")
        settle(page)
        self.assertEqual(
            page.evaluate("[OPEN_ALL.length, PV_BUSY.size, document.activeElement.classList.contains('b-esave')]"),
            [1, 0, True],
        )
        self.assertEqual([p["verdict"] for p in self.pins().values()], ["채택"])

    def test_a_digit_from_the_section_strip_then_enter_opens_the_reason(self):
        """The focus on the section strip's page button (where a press on the page list leaves it), 1 with its save held,
        Enter, '패널 값' typed: the Enter opened the reason popover - not the page list - and the text is that verdict's
        note once the save answers (the Enter pressed the button again and the text went into the page field)."""
        page = self.on("fig")
        page.focus("#section-page")
        self.held = []
        page.keyboard.press("1")
        page.wait_for_function("PV_BUSY.size===1")
        self.assertEqual(page.evaluate("document.activeElement.id"), "left")
        page.keyboard.press("Enter")
        page.keyboard.type("패널 값")
        self.assertTrue(page.evaluate("document.querySelector('#page-pop').hidden"))
        self.release()
        page.keyboard.press("Enter")
        page.wait_for_function("OPEN_ALL.some(p=>p.note==='패널 값')", timeout=10000)
        settle(page)
        self.assertEqual([(p["verdict"], p["note"]) for p in self.pins().values()], [("채택", "패널 값")])


def ax_of(page, expr):
    """The role and name Chromium's accessibility tree gives the element expr evaluates to - what a screen reader says."""
    cdp = page.context.new_cdp_session(page)
    try:
        obj = cdp.send("Runtime.evaluate", {"expression": expr})["result"]
        node = cdp.send("DOM.describeNode", {"objectId": obj["objectId"]})["node"]
        cdp.send("DOM.getDocument", {"depth": 0})
        ax = cdp.send(
            "Accessibility.getPartialAXTree", {"backendNodeId": node["backendNodeId"], "fetchRelatives": False}
        )
        n = ax["nodes"][0]
        return n.get("role", {}).get("value"), n.get("name", {}).get("value")
    finally:
        cdp.detach()


# A Tab keydown (Shift+Tab with shift) sent from the element sel - every keydown listener of the viewer runs, the browser's
# own move of the focus does not -, with how many times it read the box of an element in the pages (inside #left) and
# whether the focus stayed on sel.
TAB_READS = """([sel, shift]) => {const L = document.querySelector('#left'), t = document.querySelector(sel), f = Element.prototype.getClientRects;
  t.focus({preventScroll: true}); let n = 0;
  Element.prototype.getClientRects = function () {if (this !== L && L.contains(this)) n++; return f.call(this);};
  try {t.dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', shiftKey: shift, bubbles: true, cancelable: true}));}
  finally {Element.prototype.getClientRects = f;}
  return [n, document.activeElement === t];}"""


class EdgeKeys(VerdictBase):
    """The 0.4.34 RC's keyboard follow-ups: Shift+Tab from the reading line leaves the pages the way Tab came in (#306), the
    PDF area the focus waits on during a key's save is a named region (#307), and a Tab outside the pages does not read
    the pages' controls (#308)."""

    def test_shift_tab_from_the_reading_lines_first_control_goes_back_to_the_section_strip(self):
        """Page 2 zoomed and read; Tab from the section strip's page button goes to page 2's line, and Shift+Tab from its
        first control goes back to that button - not to page 1's line, which scrolled the pages there (80 of them on 91
        pages never reached the outline) - and the pages do not move. Shift+Tab from a later control stays on the line."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        page.focus("#section-page")
        top = page.evaluate("document.querySelector('#left').scrollTop")
        page.keyboard.press("Tab")
        first = page.evaluate(FOCUS_AT)
        self.assertEqual(first[0], 2)
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(FOCUS_AT)[0], 2)
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate(FOCUS_AT), first)
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate("document.activeElement.id"), "section-page")
        self.assertEqual(page.evaluate("[document.querySelector('#left').scrollTop, PV_READ]"), [top, 2])

    def test_shift_tab_reaches_the_reading_pages_marks_before_it_leaves(self):
        """A pin marked on page 2 of the view-only PDF, page 2 zoomed and read: Tab from the section strip goes to page 2's
        line, Shift+Tab to that page's mark badge - the DOM's order on the page - and Shift+Tab from the badge back to the
        section strip, not to page 1's line; the pages do not move."""
        build = self.on("rv").evaluate("META.pages_build")
        body = {"doc": "rv", "page": 2, "frac": [0.1, 0.1, 0.4, 0.3], "pdf_build": build, "note": "표시"}
        code, made = self.call("POST", "/api/pin", {**body, "kind_req": "fix", "assignee": "agent"})
        self.assertEqual(code, 200, made)
        page = self.on("rv", n_open=1)
        page.evaluate("setK(PT_PX*1.5,false); ZOOMED=true")
        settle(page)
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        badge = '.mark[data-pin="%d"] .mark-jump' % made["id"]
        page.focus("#section-page")
        top = page.evaluate("document.querySelector('#left').scrollTop")
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(FOCUS_AT)[0], 2)
        page.keyboard.press("Shift+Tab")
        self.assertTrue(page.evaluate("s=>document.activeElement===document.querySelector(s)", badge))
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate("document.activeElement.id"), "section-page")
        self.assertEqual(page.evaluate("[document.querySelector('#left').scrollTop, PV_READ]"), [top, 2])

    def test_shift_tab_goes_back_to_where_a_digit_was_pressed_before_the_pages(self):
        """1 pressed on a document tab saves 채택 with the focus then on page 1's line: Shift+Tab from its first control goes
        back to that tab. 2 pressed on the verdict's card (after the pages in the Tab order) saves 보류: Shift+Tab from the
        line's first control goes to the section strip's page button, the stop before the pages - Enter on the line's
        '#N' is the way back to the card."""
        page = self.on("fig")
        tab = page.evaluate(
            """()=>{const b=[...document.querySelectorAll('#doc-links button')].find(x=>x.getClientRects().length&&x.tabIndex>=0);
              b.id=b.id||'vd-test-tab'; return '#'+b.id;}"""
        )
        top = page.evaluate("document.querySelector('#left').scrollTop")
        page.focus(tab)
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===1&&!PV_BUSY.size")
        settle(page)
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-reason-open"])
        page.focus('#doc .pv[data-page="1"] .pv-ref')
        page.keyboard.press("Shift+Tab")
        self.assertTrue(page.evaluate("s=>document.activeElement===document.querySelector(s)", tab))
        pid = page.evaluate("OPEN_ALL[0].id")
        page.evaluate(END_CHIPS)
        page.evaluate(
            "id=>[...document.querySelectorAll('.pin.card[data-id=\"'+id+'\"] button')].find(b=>b.getClientRects().length>0).focus()",
            pid,
        )
        page.keyboard.press("2")
        page.wait_for_function("OPEN_ALL.some(p=>p.verdict==='보류')&&!PV_BUSY.size")
        settle(page)
        page.focus('#doc .pv[data-page="1"] .pv-ref')
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate("document.activeElement.id"), "section-page")
        self.assertEqual(page.evaluate("document.querySelector('#left').scrollTop"), top)

    PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
    FIRST_STOP = """n=>{const b=[...document.querySelector('#doc .pgw[data-page="'+n+'"]').querySelectorAll(PV_TABBABLE)].find(pvTabStop);
      b.focus({preventScroll:true}); return document.activeElement===b;}"""

    def test_shift_tab_on_a_phone_goes_to_the_position_button_or_the_tool_bar_it_came_from(self):
        """390x844 by touch, page 2 zoomed and read: nothing comes before the pages (the nav bar, the outline and the section
        strip are not drawn), so Shift+Tab from page 2's first stop goes to the position button - not to page 1's line,
        which scrolled the pages back - and the pages do not move. 1 pressed on the tool bar's [더보기] saves 채택, and
        Shift+Tab from the line goes back to [더보기]."""
        page = self.on("fig", **self.PHONE)
        page.evaluate("setSide(false)")
        page.evaluate("()=>{setK(K*2.5,false); ZOOMED=true;}")
        settle(page)
        page.evaluate(SCROLL, [2, "top"])
        settle(page)
        self.assertEqual(page.evaluate("[PV_READ, pvEdgeStop(false)]"), [2, None])
        self.assertTrue(page.evaluate(self.FIRST_STOP, 2))
        top = page.evaluate("document.querySelector('#left').scrollTop")
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate("document.activeElement.id"), "btn-pos")
        self.assertEqual(page.evaluate("[document.querySelector('#left').scrollTop, PV_READ]"), [top, 2])
        page.focus("#btn-more")
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===1&&!PV_BUSY.size", timeout=10000)
        settle(page)
        page.evaluate(END_CHIPS)
        self.assertTrue(page.evaluate(self.FIRST_STOP, 2))
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate("document.activeElement.id"), "btn-more")
        self.assertEqual(page.evaluate("[document.querySelector('#left').scrollTop, PV_READ]"), [top, 2])

    def test_an_origin_in_another_document_is_not_gone_back_to(self):
        """1 pressed on a document tab of the figure document; the focus, left in the pages, moves on to the view-only PDF
        (a switch made with the focus on the line) and Tab from the PDF area takes it to that document's reading line: Shift+Tab goes to the section strip's
        page button, not to the tab the first document's digit was pressed on."""
        page = self.on("fig")
        tab = page.evaluate(
            """()=>{const b=[...document.querySelectorAll('#doc-links button')].find(x=>x.getClientRects().length&&x.tabIndex>=0);
              b.id=b.id||'vd-test-tab'; return '#'+b.id;}"""
        )
        page.focus(tab)
        page.keyboard.press("1")
        page.wait_for_function("OPEN_ALL.length===1&&!PV_BUSY.size")
        settle(page)
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-reason-open"])
        page.evaluate("switchDoc('rv')")
        page.wait_for_function("DOC==='rv'&&META&&META.doc==='rv'&&!!document.querySelector('#doc .pv')")
        settle(page)
        page.evaluate("searchToPage()")
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(FOCUS_AT)[0], 1)
        self.assertTrue(page.evaluate(self.FIRST_STOP, 1))
        page.keyboard.press("Shift+Tab")
        self.assertEqual(page.evaluate("document.activeElement.id"), "section-page")

    def test_the_pdf_area_is_a_named_region(self):
        """A digit pressed on the section strip with its save held leaves the focus on the PDF area: a region named 'PDF 쪽'
        ('PDF pages' in English), which a screen reader says - with no role and no name it read every page's text one
        after the other. The save's end still takes the focus to the line's way to the reason."""
        page = self.on("fig")
        page.focus("#section-page")
        self.held = []
        page.keyboard.press("1")
        page.wait_for_function("PV_BUSY.size===1")
        self.assertEqual(page.evaluate("document.activeElement.id"), "left")
        self.assertEqual(ax_of(page, "document.activeElement"), ("region", "PDF 쪽"))
        self.release()
        page.wait_for_function("OPEN_ALL.length===1&&!PV_BUSY.size", timeout=10000)
        settle(page)
        self.assertEqual(page.evaluate(FOCUS_AT), [1, "pv-reason-open"])
        en = self.open(0, lang="en")
        self.assertEqual(ax_of(en, "document.querySelector('#left')"), ("region", "PDF pages"))

    def test_a_tab_away_from_the_pages_edge_reads_nothing_in_the_pages(self):
        """Tab and Shift+Tab from a stop before the pages that is not the last one (the nav bar's first control) and from
        one after them that is not the first (the panel's last): no page line control is read - the Tab is not across the
        pages' edge - and the focus is left to the browser (each such Tab read every control of every line). The stop at
        the edge still takes the Tab to the reading line."""
        page = self.on("fig")
        before, after = page.evaluate(
            """()=>{const v=x=>x.getClientRects().length>0&&x.tabIndex>=0&&!x.disabled;
              const a=[...document.querySelectorAll('#doc-nav button')].find(v),b=[...document.querySelectorAll('#right button')].filter(v).pop();
              a.id=a.id||'vd-test-before'; b.id=b.id||'vd-test-after'; return ['#'+a.id,'#'+b.id];}"""
        )
        self.assertGreater(page.evaluate("document.querySelectorAll('#doc .pv button').length"), 3)
        for sel in (before, after):
            for shift in (False, True):
                with self.subTest(sel=sel, shift=shift):
                    self.assertEqual(page.evaluate(TAB_READS, [sel, shift]), [0, True])
        page.focus("#section-page")
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(FOCUS_AT)[0], 1)


class ChipFontWait(VerdictBase):
    """A save chip with no room on its line while a web font loads waits unseen instead of sending its undo to the status
    line for good: on CI under load a fresh state's new characters were drawn in a fallback face while their Pretendard
    slice loaded, and three browser tests lost the chip that fits once the face swaps."""

    STATE = """s=>{const l=document.querySelector('#doc .pv[data-page="2"]'); return [!!l.querySelector(':scope>.nt-chip'),
      l.classList.contains('pv-chip-wait'), LINE.some(n=>n.undo&&!!n.act)];}"""

    def saved_then_squeezed(self):
        page = self.on("fig")
        page.evaluate("setK(PT_PX*2,false); ZOOMED=true")
        settle(page)
        page.evaluate(
            "()=>{window.__fs='loaded'; Object.defineProperty(document.fonts,'status',{get:()=>window.__fs,configurable:true});}"
        )
        self.press_page(page, 2, "보류")
        self.assertEqual(page.evaluate(self.STATE, None), [True, False, False])
        w = page.evaluate(
            """()=>{window.__fs='loading'; const l=document.querySelector('#doc .pv[data-page="2"]');
              for(let w=400;w>=100;w-=10){l.style.width=w+'px'; pvFit([l]); if(l.classList.contains('pv-chip-wait'))return w;} return 0;}"""
        )
        self.assertGreater(w, 0)
        self.assertEqual(page.evaluate(self.STATE, None), [True, True, False])  # no room, fonts loading: waits unseen
        return page

    def test_a_chip_with_no_room_waits_for_the_fonts_and_is_placed_when_they_load(self):
        page = self.saved_then_squeezed()
        page.evaluate(
            "()=>{window.__fs='loaded'; document.fonts.dispatchEvent(new Event('loadingdone'));}"
        )  # sizePv: the line's width again
        page.wait_for_timeout(100)
        self.assertEqual(page.evaluate(self.STATE, None), [True, False, False])

    def test_a_chip_with_no_room_while_its_save_is_out_is_placed_when_the_save_ends(self):
        """The chip is placed while its save is still out (the list read again redraws the line before the save's end): the
        line shows the new verdict and still '· 보류 저장 중…', and on CI it had 69px for a 72px chip that had 146px a moment
        later - it went to the status line for good. Squeezed to no room while the save is out: it waits; the save's end
        redraws the lines and it is on its line."""
        page = self.on("fig")
        page.evaluate("setK(PT_PX*2,false); ZOOMED=true")
        settle(page)
        self.press_page(page, 2, "보류")
        self.assertEqual(page.evaluate(self.STATE, None), [True, False, False])
        w = page.evaluate(
            """()=>{PV_BUSY.set(pvSlot(2),'보류'); const l=document.querySelector('#doc .pv[data-page="2"]');
              for(let w=400;w>=100;w-=10){l.style.width=w+'px'; pvFit([l]); if(l.classList.contains('pv-chip-wait'))return w;} return 0;}"""
        )
        self.assertGreater(w, 0)
        self.assertEqual(page.evaluate(self.STATE, None), [True, True, False])
        page.evaluate("()=>{PV_BUSY.delete(pvSlot(2)); drawPageVerdicts();}")  # as the save's end does
        self.assertEqual(page.evaluate(self.STATE, None), [True, False, False])

    def test_a_chip_whose_fonts_never_load_goes_to_the_status_line_after_3_seconds(self):
        page = self.saved_then_squeezed()
        page.wait_for_timeout(3300)
        self.assertEqual(page.evaluate(self.STATE, None), [False, False, True])
