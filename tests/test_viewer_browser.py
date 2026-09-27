"""The real viewer in Chromium against the in-process server (helpers_browser.BrowserBase): whole feature flows.

The flows run on a desktop 1400x850 and, where the layout differs, an unfolded Fold 842x758 and a phone 384x832
(touch), in Korean and English:

- one [Reply] with its outcome preview, undo and keep-state switch, the Trash with undo, restore and permanent delete,
  collapsible sections, and cold deep links from a notification (v0.2.2, issue #8);
- pin-scoped [View changes] and the viewer role's Trash (v0.3, issue #9);
- the question nudge's focus and what the viewer role sees (v0.2.1 QA).

Pointer and touch input (panel collapse, gestures) is test_viewer_input.py; the page's structure and pure functions
are test_viewer.py. Skipped without Playwright or Chromium, a failure under LIMN_TEST_REQUIRE_BROWSER=1.

Run: uv run pytest -q tests/test_viewer_browser.py
"""

import json
import os
import re
import shutil
import subprocess
import time
from unittest import mock

from limn import revisions, startup
from limn.access import LOCAL_ACTOR
from limn.pins.lifecycle import CloseRequest
from limn.pins.view import pin_state
from limn.store import find_pin
from limn.web import parse

from helpers import SW_JS, add_pin, blank_png, minimal_pdf, ps
from helpers_access import ALICE, BOB, CAROL, REPO_NEW as NEW, REPO_OLD as OLD, actor
from helpers_browser import BrowserBase, booted, settle, watch_idle

HANGUL = re.compile(r"[가-힣]")
A, B = actor(ALICE), actor(BOB)
DEVICES = {
    "desktop": {"viewport": {"width": 1400, "height": 850}},
    "fold": {"viewport": {"width": 842, "height": 758}, "is_mobile": True, "has_touch": True},
    "phone": {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True},
}
# The viewer's words the flows look for: reply and Trash (v0.2.2), then pin-scoped changes (v0.3).
TXT = {
    "ko": {
        "reopen": "보내면 이 핀이 다시 열려 에이전트에게 갑니다",
        "keep": "보내도 상태는 그대로입니다",
        "undo": "되돌리기",
        "mention": "보내면 Bob Park에게 알림이 가고 상태는 그대로입니다",
        "trash": "휴지통 1",
        "restore": "되살리기",
        "purge": "영구 삭제",
        "new": "새 1",
        "gone": "삭제된 핀",
        "other": "이 커밋의 다른 변경 2곳",
        "whole": "커밋 전체 비교",
        "only": "핀 #%d의 변경만",
        "fallback": "커밋 전체를 비교합니다",
    },
    "en": {
        "reopen": "Sending will reopen this pin for the agent",
        "keep": "Sending keeps the state as it is",
        "undo": "Undo",
        "mention": "Sending notifies Bob Park; state stays",
        "trash": "Trash (1)",
        "restore": "Restore",
        "purge": "Delete forever",
        "new": "new 1",
        "gone": "deleted pin",
        "other": "2 other changes in this commit",
        "whole": "Whole commit",
        "only": "Only pin #%d's changes",
        "fallback": "comparing the whole commit",
    },
}
# Makes the viewer's pin list (GET /api/pins?all=1) answer 1.5s late, as on a slow CI runner; other requests are untouched.
SLOW_PIN_LIST = (
    "(()=>{const f=window.fetch;window.fetch=function(u,o){const p=f.call(this,u,o);"
    "return String(u).startsWith('/api/pins?all=1')?p.then(r=>new Promise(ok=>setTimeout(()=>ok(r),1500))):p;};})()"
)


# ---------------------------------------------------------------- BrowserBase itself


class BrowserOpenWaitsForPins(BrowserBase):
    """BrowserBase.open returns only after the viewer knows every pin. The ScopedViewer flake (CI run 36216447363):
    open(0) returned once META was set, before boot() had loaded the pin lists; showChange() of a done pin then found
    no pin and did nothing, and the test timed out waiting for the diff."""

    WHO = ALICE

    def test_a_done_pin_is_known_when_open_returns_even_if_the_pin_list_is_slow(self):
        """With the pin list 1.5s late, the done pin is already in the viewer's lists when open(0) returns."""
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 4, "page": 1, "note": "done"}, actor(ALICE)).record["id"]
        ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest(reply="fixed"))
        page = self.open(0, init=SLOW_PIN_LIST)
        self.assertTrue(page.evaluate("findAnyPin(%d)!==null" % pid))


# ---------------------------------------------------------------- one [Reply], the Trash and collapsible sections (v0.2.2, issue #8)


class ViewerFlows(BrowserBase):
    WHO = ALICE

    def setUp(self):
        super().setUp()
        for h in (ALICE, BOB, CAROL):
            ps.record_person(actor(h))
        self.open_id = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "문단 줄이기"}, A).record[
            "id"
        ]
        self.rv = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "식 번호 확인"}, A).record["id"]
        ps.close_pin(self.rv, dict(LOCAL_ACTOR), CloseRequest(reply="식 번호를 고쳤습니다", ref="PR #9"))
        self.dn = add_pin({"file": str(self.main), "lo": 12, "hi": 13, "page": 2, "note": "오타"}, A).record["id"]
        ps.close_pin(self.dn, A, CloseRequest(reply="고침"))

    def state(self, pid):
        return pin_state(find_pin(ps.snapshot_pins(), pid))

    def wait_state(self, pid, want):
        """Let the page settle, so every request it has sent was answered by the in-process server (which serves routed
        requests on this thread, only while Playwright runs), then check that pin pid is in state want on the server."""
        settle(self._page)
        self.assertEqual(self.state(pid), want)

    def page_for(self, device, lang, n_open=1):
        page = self._page = self.open(n_open, lang=lang, **DEVICES[device])
        page.evaluate("setSide(true); OPEN_CARDS.add(%d); OPEN_CARDS.add(%d); drawPins()" % (self.open_id, self.rv))
        settle(page)
        return page

    def toast(self, page, text):
        return page.locator("#toasts .toast").filter(has_text=text).first

    def english_only(self, page, sel):
        text = page.inner_text(sel)
        self.assertFalse(HANGUL.search(text), (sel, text))

    def run_matrix(self, fn):
        for device in DEVICES:
            for lang in ("ko", "en"):
                with self.subTest(device=device, lang=lang):
                    self.setUp_fresh()
                    fn(self.page_for(device, lang), device, lang)

    def setUp_fresh(self):
        self.tearDown()
        self.setUp()

    # -- 1. one Reply: the rule, the preview, keep state, undo

    def test_reply_reopens_with_preview_and_undo(self):
        def flow(page, device, lang):
            t = TXT[lang]
            card = '#review-pins .pin[data-id="%d"]' % self.rv
            acts = page.evaluate(
                "[...document.querySelectorAll('%s .acts [data-act]')].map(e=>e.dataset.act)" % card.replace('"', '\\"')
            )
            self.assertNotIn("rv-reopen", acts)
            self.assertIn("reply-open", acts)
            self.assertIn("confirm", acts)
            page.click(card + " .acts [data-act=reply-open]")
            page.fill(card + " textarea.r-text", "식 번호가 아직 틀립니다")
            page.wait_for_selector(card + " .r-outcome:not([hidden])")
            self.assertEqual(page.inner_text(card + " .r-outcome .r-out-t"), t["reopen"])
            keep = page.locator(card + " [data-act=reply-flip]")
            self.assertTrue(keep.is_visible())
            self.assertEqual(keep.get_attribute("aria-checked"), "false")
            if lang == "en":
                self.english_only(page, card + " .reply-box")
            page.click(card + " [data-act=reply-send]")
            tst = self.toast(page, t["undo"])
            tst.wait_for(state="visible")
            self.assertEqual(self.state(self.rv), "review")  # nothing sent while undo is possible
            tst.get_by_role("button", name=t["undo"]).click()
            page.wait_for_selector(card + " textarea.r-text")
            self.assertEqual(page.input_value(card + " textarea.r-text"), "식 번호가 아직 틀립니다")
            settle(page)  # a request the undo failed to cancel would have been answered by now
            self.assertEqual(self.state(self.rv), "review")
            page.click(card + " [data-act=reply-send]")
            tst = self.toast(page, t["undo"])
            tst.wait_for(state="visible")
            tst.locator("button.btn-icon").click()  # dismissing the toast sends at once
            self.wait_state(self.rv, "open")
            last = find_pin(ps.snapshot_pins(), self.rv)["thread"][-1]
            self.assertEqual((last.get("ev"), last["text"]), ("reopen", "식 번호가 아직 틀립니다"))
            page.wait_for_function("OPEN_ALL.some(p=>p.id===%d)" % self.rv, timeout=8000)

        self.run_matrix(flow)

    def test_keep_state_sends_a_comment(self):
        def flow(page, device, lang):
            t = TXT[lang]
            card = '#review-pins .pin[data-id="%d"]' % self.rv
            page.click(card + " .acts [data-act=reply-open]")
            page.fill(card + " textarea.r-text", "내일 다시 볼게요")
            page.click(card + " [data-act=reply-flip]")
            self.assertEqual(page.get_attribute(card + " [data-act=reply-flip]", "aria-checked"), "true")
            self.assertEqual(page.inner_text(card + " .r-outcome .r-out-t"), t["keep"])
            page.click(card + " [data-act=reply-send]")
            self.toast(page, t["undo"]).locator("button.btn-icon").click()
            settle(page)  # the reply the dismissed toast sends has been answered
            last = find_pin(ps.snapshot_pins(), self.rv)["thread"][-1]
            self.assertEqual((last.get("ev"), last["text"], self.state(self.rv)), (None, "내일 다시 볼게요", "review"))

        self.run_matrix(flow)

    def test_mention_preview_keeps_state(self):
        page = self.page_for("desktop", "ko")
        card = '#review-pins .pin[data-id="%d"]' % self.rv
        page.click(card + " .acts [data-act=reply-open]")
        page.click(card + " textarea.r-text")
        page.keyboard.type("@Bob Park 이 수정 괜찮나요")
        settle(page)
        self.assertEqual(page.inner_text(card + " .r-outcome .r-out-t"), TXT["ko"]["mention"])
        flip = page.locator(card + " [data-act=reply-flip]")  # the rare override is [다시 열기] here
        self.assertEqual((flip.inner_text(), flip.get_attribute("aria-checked")), ("다시 열기", "false"))
        flip.click()
        self.assertEqual(
            page.inner_text(card + " .r-outcome .r-out-t"),
            "보내면 이 핀이 다시 열려 에이전트에게 가고, Bob Park에게 알림이 갑니다",
        )
        page.click(card + " [data-act=reply-send]")
        self.toast(page, "되돌리기").locator("button.btn-icon").click()
        self.wait_state(self.rv, "open")

    def test_done_row_offers_reply_not_reopen(self):
        def flow(page, device, lang):
            page.click("#done-toggle")
            row = '#done-list .arc-row[data-id="%d"]' % self.dn
            page.wait_for_selector(row)
            acts = page.evaluate("[...document.querySelectorAll('#done-list [data-act]')].map(e=>e.dataset.act)")
            self.assertNotIn("rv-reopen", acts)
            self.assertIn("reply-open", acts)
            page.click(row + " [data-act=reply-open]")
            page.fill(row + " textarea.r-text", "다시 보니 문장이 어색합니다")
            self.assertEqual(page.inner_text(row + " .r-outcome .r-out-t"), TXT[lang]["reopen"])
            page.click(row + " [data-act=reply-send]")
            self.toast(page, TXT[lang]["undo"]).locator("button.btn-icon").click()
            self.wait_state(self.dn, "open")

        self.run_matrix(flow)

    def test_hidden_page_sends_at_once_and_drops_the_undo(self):
        page = self.page_for("desktop", "ko")
        card = '#review-pins .pin[data-id="%d"]' % self.rv
        page.click(card + " .acts [data-act=reply-open]")
        page.fill(card + " textarea.r-text", "숨기기 전에 보냄")
        page.click(card + " [data-act=reply-send]")
        self.toast(page, "되돌리기").wait_for(state="visible")
        page.evaluate("window.dispatchEvent(new Event('pagehide'))")
        self.wait_state(self.rv, "open")
        settle(page)
        self.assertEqual(self.toast(page, "되돌리기").count(), 0)  # an undo that could no longer work is gone

    def test_newer_toasts_pushing_it_out_send_it(self):
        page = self.page_for("desktop", "ko")
        card = '#review-pins .pin[data-id="%d"]' % self.rv
        page.click(card + " .acts [data-act=reply-open]")
        page.fill(card + " textarea.r-text", "밀려나면 보냄")
        page.click(card + " [data-act=reply-send]")
        page.evaluate("for(let i=0;i<6;i++)toast('다른 알림 '+i,'ok')")
        self.wait_state(self.rv, "open")

    def test_outcome_line_follows_a_state_change_while_typing(self):
        page = self.page_for("desktop", "ko")
        card = '#pins .pin[data-id="%d"]' % self.open_id
        page.click(card + " .acts [data-act=reply-open]")
        page.fill("textarea.r-text", "이 문장도 봐 주세요")
        self.assertFalse(page.is_visible(".r-outcome"))  # open pin: a reply never changes it
        ps.close_pin(self.open_id, dict(LOCAL_ACTOR), CloseRequest(reply="줄였습니다"))  # the agent closes it meanwhile
        page.evaluate("loadPins()")
        page.wait_for_selector('#review-pins .pin[data-id="%d"] .r-outcome:not([hidden])' % self.open_id)
        self.assertEqual(page.inner_text(".r-outcome .r-out-t"), TXT["ko"]["reopen"])
        self.assertEqual(page.input_value("textarea.r-text"), "이 문장도 봐 주세요")

    def test_jumping_to_a_card_expands_its_collapsed_section(self):
        for device in ("desktop", "phone"):
            with self.subTest(device=device):
                page = self.page_for(device, "ko")
                page.click("#open-toggle")
                self.assertFalse(page.is_visible("#pins"))
                page.evaluate("revealCard(%d); jumpToCard(%d)" % (self.open_id, self.open_id))
                page.wait_for_selector('#pins .pin[data-id="%d"]' % self.open_id, state="visible")
                self.assertEqual(page.get_attribute("#open-toggle", "aria-expanded"), "true")

    def test_delete_toast_undo_restores(self):
        page = self.page_for("desktop", "ko")
        page.click('#pins .pin[data-id="%d"] [data-act=drop]' % self.open_id)
        self.toast(page, "되돌리기").get_by_role("button", name="되돌리기").click()
        page.wait_for_function("OPEN_ALL.some(p=>p.id===%d)" % self.open_id, timeout=5000)
        self.assertIsNotNone(find_pin(ps.snapshot_pins(), self.open_id))
        self.assertEqual(ps.read_jsonl(ps.C.dropped)[0], [])

    # -- 2. Trash

    def open_trash(self, page, device):
        if device == "desktop":
            page.click("#trash-link")
        else:
            page.click("#btn-more")
            page.click("#m-trash")
        page.wait_for_selector("#trash[open]")

    def test_delete_undo_and_trash_restore(self):
        def flow(page, device, lang):
            t = TXT[lang]
            page.click('#pins .pin[data-id="%d"] [data-act=drop]' % self.open_id)
            page.wait_for_function("!document.querySelector('#pins .pin[data-id=\"%d\"]')" % self.open_id, timeout=3000)
            self.toast(page, t["undo"]).wait_for(state="visible")
            settle(page)  # the drop has been answered
            self.assertIsNone(find_pin(ps.snapshot_pins(), self.open_id))
            page.wait_for_function("DROPPED.length===1", timeout=5000)
            self.assertFalse(page.locator("#sec-dropped").count())
            if device == "desktop":
                self.assertEqual(page.inner_text("#trash-link").strip(), t["trash"])
            self.open_trash(page, device)
            row = '#trash .arc-row[data-id="%d"]' % self.open_id
            page.wait_for_selector(row)
            self.assertFalse(page.locator(row + " [data-act=purge]").count())  # not the owner
            if lang == "en":  # the UI, not the Korean note a person wrote
                for sel in ("#trash-h", "#trash-note", row + " .arc-l1"):
                    self.english_only(page, sel)
            page.click(row + " [data-act=restore]")
            page.wait_for_function("OPEN_ALL.some(p=>p.id===%d)" % self.open_id, timeout=5000)
            self.assertIsNotNone(find_pin(ps.snapshot_pins(), self.open_id))

        self.run_matrix(flow)

    def test_owner_deletes_forever_with_undo(self):
        ps.C.people_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "people": [
                        {"login": "alice@example.com", "name": "Alice Kim", "role": "owner"},
                        {"login": "bob@example.com", "name": "Bob Park"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        ps.drop_pin(self.open_id, B)
        page = self.page_for("desktop", "ko", n_open=0)
        page.click("#trash-link")
        row = '#trash .arc-row[data-id="%d"]' % self.open_id
        page.wait_for_selector(row + " [data-act=purge]")
        page.click(row + " [data-act=purge]")
        tst = self.toast(page, "되돌리기")
        tst.get_by_role("button", name="되돌리기").click()
        settle(page)
        self.assertEqual([r["id"] for r in ps.read_jsonl(ps.C.dropped)[0]], [self.open_id])
        page.click(row + " [data-act=purge]")
        self.toast(page, "되돌리기").locator("button.btn-icon").click()
        settle(page)  # the permanent delete the dismissed toast sends has been answered
        self.assertEqual(ps.read_jsonl(ps.C.dropped)[0], [])

    def test_ref_to_deleted_pin_in_a_thread(self):
        ps.reply_pin(self.open_id, "#%d 와 같은 문제" % self.dn, B)
        ps.drop_pin(self.dn, A)
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                page = self.page_for("desktop", lang)
                ref = page.locator('#pins .pin[data-id="%d"] .pin-ref.gone' % self.open_id)
                self.assertEqual(ref.inner_text().replace("\n", " "), "#%d %s" % (self.dn, TXT[lang]["gone"]))
                ref.click()
                page.wait_for_selector('#trash[open] .arc-row[data-id="%d"]' % self.dn)

    # -- 3. Collapsible sections

    def test_sections_toggle_remember_and_count_new(self):
        def flow(page, device, lang):
            heads = page.evaluate(
                "[...document.querySelectorAll('.sec-tg')].map(b=>[b.id,b.getAttribute('aria-expanded')])"
            )
            self.assertEqual(heads, [["open-toggle", "true"], ["review-toggle", "true"], ["done-toggle", "false"]])
            self.assertFalse(page.is_visible("#done-list"))
            page.click("#open-toggle")
            self.assertEqual(page.get_attribute("#open-toggle", "aria-expanded"), "false")
            self.assertFalse(page.is_visible("#pins"))
            page.focus("#review-toggle")
            page.keyboard.press("Enter")
            self.assertEqual(page.get_attribute("#review-toggle", "aria-expanded"), "false")
            page.keyboard.press(" ")
            self.assertEqual(page.get_attribute("#review-toggle", "aria-expanded"), "true")
            add_pin({"file": str(self.main), "lo": 20, "hi": 21, "page": 2, "note": "새 핀"}, B).record["id"]
            page.evaluate("loadPins()")
            page.wait_for_selector("#open-toggle .sec-new:not([hidden])")
            self.assertEqual(page.inner_text("#open-toggle .sec-new"), TXT[lang]["new"])
            page.reload()
            page.wait_for_function("typeof OPEN_ALL!=='undefined'&&OPEN_ALL.length>=2&&META", timeout=20000)
            page.evaluate("setSide(true)")  # compact: the sheet starts collapsed after a reload
            self.assertEqual(page.get_attribute("#open-toggle", "aria-expanded"), "false")  # remembered
            page.click("#open-toggle")
            self.assertTrue(page.is_visible("#pins"))
            self.assertFalse(page.is_visible("#open-toggle .sec-new"))
            if lang == "en":
                for sel in ("#open-toggle", "#review-toggle", "#done-toggle"):
                    self.english_only(page, sel)

        self.run_matrix(flow)


class ColdDeepLink(BrowserBase):
    """A notification click with no tab open loads /#doc=<key>&pin=<n> cold (the service worker's openWindow). On an
    instance with several documents the boot rewrote the hash to #doc=<key> before reading pin=, so the pin was lost."""

    WHO = ALICE

    def setUp(self):
        super().setUp()
        src = ps.C.src
        (src / "hl.tex").write_text((src / "main.tex").read_text(encoding="utf-8"), encoding="utf-8")
        ps.set_docs(startup.make_docs(["ms=본문:main.tex", "hl=하이라이트:hl.tex"], src, ps.C.paths))
        for D in ps.DOCS:
            pages = D.dir / "pages-20260925100000"
            pages.mkdir(parents=True, exist_ok=True)
            for i in (1, 2):
                (pages / ("page-%d.png" % i)).write_bytes(blank_png(1275, 1650))
            (D.dir / "pages.cur").write_text(pages.name)
            (D.dir / "built_at.txt").write_text("2026-09-25 10:00:00")
            (D.dir / "head.txt").write_text("abc1234")
        ms, hl = ps.DOCS
        for lo in range(4, 30, 2):
            add_pin(
                {"file": str(src / "main.tex"), "lo": lo, "hi": lo + 1, "page": 1, "note": "본문 %d" % lo}, A
            ).record["id"]
        for lo in range(4, 24, 2):
            add_pin(
                {"file": str(src / "hl.tex"), "lo": lo, "hi": lo + 1, "page": 1, "note": "하이라이트 %d" % lo},
                A,
                doc=hl,
            ).record["id"]
        self.target = add_pin(
            {"file": str(src / "hl.tex"), "lo": 30, "hi": 31, "page": 2, "note": "여기로 와야 함"}, A, doc=hl
        ).record["id"]
        self.gone = add_pin(
            {"file": str(src / "hl.tex"), "lo": 32, "hi": 33, "page": 2, "note": "되살릴 핀"}, A, doc=hl
        ).record["id"]
        ps.drop_pin(self.gone, B)
        self.addCleanup(ps.set_docs, None)

    def cold(self, hash_, device):
        context = self.browser.new_context(**DEVICES[device])
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=ko" + hash_)
        page.wait_for_function("typeof OPEN_ALL!=='undefined'&&OPEN_ALL.length>=20&&META", timeout=20000)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def assert_card_shown(self, page, pid, device):
        page.wait_for_function(
            "DOC==='hl'&&OPEN_CARDS.has(%d)&&!!document.querySelector('.pin[data-id=\"%d\"]')" % (pid, pid),
            timeout=8000,
        )
        if device == "desktop":  # the card is scrolled into the panel
            page.wait_for_function(
                """(()=>{const c=document.querySelector('.pin[data-id="%d"]').getBoundingClientRect(),
                l=document.getElementById('list').getBoundingClientRect(); return c.height>0&&c.top>=l.top-1&&c.bottom<=l.bottom+1;})()"""
                % pid,
                timeout=5000,
            )

    def test_cold_link_opens_the_pin_in_another_document(self):
        for device in ("desktop", "phone"):
            with self.subTest(device=device):
                page = self.cold("#doc=hl&pin=%d" % self.target, device)
                self.assert_card_shown(page, self.target, device)
                self.assertEqual(page.evaluate("location.hash"), "#doc=hl")  # the one-shot pin= is consumed

    def test_cold_restore_link_restores_and_opens(self):
        page = self.cold("#doc=hl&pin=%d&act=restore" % self.gone, "desktop")
        page.wait_for_function("OPEN_ALL.some(p=>p.id===%d)" % self.gone, timeout=8000)
        self.assertIsNotNone(find_pin(ps.snapshot_pins(), self.gone))
        self.assert_card_shown(page, self.gone, "desktop")
        self.assertEqual(page.evaluate("location.hash"), "#doc=hl")

    def test_service_worker_carries_the_restore_action_into_a_new_window(self):
        self.assertIn("e.action==='restore'?'&act=restore':''", SW_JS)


class PreviewEqualsServer(BrowserBase):
    """The real input pipeline: text + autocomplete state -> the outcome line -> the request body -> the server decision."""

    WHO = ALICE
    LEE = {"login": "sl@example.com", "name": "Robin Lee"}
    PARK = {"login": "sp@example.com", "name": "Robin Park"}

    def setUp(self):
        super().setUp()
        for p in (A, self.LEE, self.PARK):
            ps.record_person(p)
        self.pins = []
        for i in range(5):
            pid = add_pin(
                {"file": str(self.main), "lo": 4 + 2 * i, "hi": 5 + 2 * i, "page": 1, "note": "검토 %d" % i}, A
            ).record["id"]
            ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest(reply="고침 %d" % i))
            self.pins.append(pid)

    def run_case(self, page, pid, pick, text):
        card = '#review-pins .pin[data-id="%d"]' % pid
        page.evaluate("OPEN_CARDS.add(%d); drawPins()" % pid)
        page.click(card + " .acts [data-act=reply-open]")
        ta = card + " textarea.r-text"
        if pick:
            page.click(ta)
            page.keyboard.type("@Rob")
            page.wait_for_selector("#mention-pop:not([hidden])")
            page.click("#mention-pop button:has-text('%s')" % pick)
        page.fill(ta, text)
        settle(page)
        preview = page.inner_text(card + " .r-outcome .r-out-t")
        page.click(card + " [data-act=reply-send]")
        page.locator("#toasts .toast").first.locator("button.btn-icon").click()
        settle(page)  # the reply the dismissed toast sends has been answered
        r = find_pin(ps.snapshot_pins(), pid)
        last = r["thread"][-1]
        return preview, not r.get("done"), [ps.known_people()[lg]["name"] for lg in last.get("mentions") or []]

    def test_preview_matches_the_server_for_ambiguous_partial_and_edited_names(self):
        page = self.open(0)
        cases = [
            ("Robin Lee", "@Robin Lee 확인 부탁"),  # autocompleted, kept
            ("Robin Lee", "@Robin 확인 부탁"),  # autocompleted, then edited down to the ambiguous first word
            (None, "@Robin Park 봐 주세요"),  # typed in full, no autocomplete
            ("Robin Park", "@Robin 이것도요"),  # picked Park, edited to the first word
            (None, "@Robin 누구든 봐 주세요"),
        ]  # ambiguous, never picked
        for pid, (pick, text) in zip(self.pins, cases, strict=True):
            with self.subTest(pick=pick, text=text):
                preview, reopened, notified = self.run_case(page, pid, pick, text)
                said_reopen = preview.startswith("보내면 이 핀이 다시 열려")
                self.assertEqual(said_reopen, reopened, (preview, reopened, notified))
                for name in notified:
                    self.assertIn(name, preview)
                if not reopened:
                    self.assertTrue(notified, preview)


class ReplyKeyboardAndFailure(BrowserBase):
    WHO = ALICE

    def setUp(self):
        super().setUp()
        ps.record_person(A)
        self.rv = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "식"}, A).record["id"]
        ps.close_pin(self.rv, dict(LOCAL_ACTOR), CloseRequest(reply="고침"))

    def box(self, page):
        card = '#review-pins .pin[data-id="%d"]' % self.rv
        page.evaluate("OPEN_CARDS.add(%d); drawPins()" % self.rv)
        page.click(card + " .acts [data-act=reply-open]")
        return card

    def test_ctrl_enter_moves_focus_to_undo(self):
        page = self.open(0)
        card = self.box(page)
        page.fill(card + " textarea.r-text", "키보드로 보냄")
        page.focus(card + " textarea.r-text")
        page.keyboard.press("Control+Enter")
        page.wait_for_function(
            "document.activeElement&&document.activeElement.closest('.toast')&&document.activeElement.textContent==='되돌리기'"
        )
        page.keyboard.press("Enter")
        page.wait_for_selector(card + " textarea.r-text")
        self.assertEqual(page.input_value(card + " textarea.r-text"), "키보드로 보냄")
        settle(page)
        self.assertEqual(pin_state(find_pin(ps.snapshot_pins(), self.rv)), "review")

    def test_offline_failure_reopens_the_box_with_the_draft_and_an_error(self):
        page = self.open(0)
        page.route("**/api/pins/*/reply", lambda r: r.abort())
        card = self.box(page)
        page.fill(card + " textarea.r-text", "오프라인에서 쓴 글")
        page.click(card + " [data-act=reply-send]")
        page.locator("#toasts .toast").first.locator("button.btn-icon").click()
        page.wait_for_selector(card + " .reply-box .r-err:not([hidden])", timeout=5000)
        self.assertEqual(page.input_value(card + " textarea.r-text"), "오프라인에서 쓴 글")
        self.assertEqual(pin_state(find_pin(ps.snapshot_pins(), self.rv)), "review")

    def test_override_is_a_switch(self):
        page = self.open(0)
        card = self.box(page)
        page.fill(card + " textarea.r-text", "x")
        sw = page.locator(card + " [data-act=reply-flip]")
        self.assertEqual((sw.get_attribute("role"), sw.get_attribute("aria-checked")), ("switch", "false"))
        self.assertIn("상태 유지", sw.inner_text())
        sw.click()
        self.assertEqual(sw.get_attribute("aria-checked"), "true")


class RestoreLinkRunsOnce(BrowserBase):
    WHO = ALICE

    def test_reload_does_not_restore_again(self):
        ps.record_person(A)
        pid = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "지운 핀"}, A).record["id"]
        keep = add_pin({"file": str(self.main), "lo": 12, "hi": 13, "page": 1, "note": "남은 핀"}, A).record["id"]
        ps.drop_pin(pid, B)
        context = self.browser.new_context(viewport={"width": 1400, "height": 850})
        self.addCleanup(context.close)
        watch_idle(context)
        page = context.new_page()
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=ko#pin=%d&act=restore" % pid)
        page.wait_for_function("typeof OPEN_ALL!=='undefined'&&OPEN_ALL.some(p=>p.id===%d)" % pid, timeout=20000)
        self.assertNotIn("act=restore", page.evaluate("location.href"))
        ps.drop_pin(pid, A)  # dropped again elsewhere
        page.reload()
        # boot() ends by acting on a pin link (openPinFromLink); a second restore it sent would be answered by settle()
        page.wait_for_function(booted(1) + "&&OPEN_ALL.some(p=>p.id===%d)" % keep, timeout=20000)
        settle(page)
        self.assertIsNone(find_pin(ps.snapshot_pins(), pid))


class TrashOfAnotherDocument(ColdDeepLink):
    def test_opening_the_trash_at_another_documents_pin_keeps_the_list_filter(self):
        page = self.cold("#doc=ms", "desktop")
        page.evaluate("openTrash(%d)" % self.gone)
        page.wait_for_selector('#trash .arc-row[data-id="%d"]' % self.gone)
        self.assertFalse(page.evaluate("SHOW_ALL"))
        page.click("#trash [data-act=trash-close]")
        self.assertFalse(page.evaluate("SHOW_ALL"))

    # the parent's tests run in ColdDeepLink already
    test_cold_link_opens_the_pin_in_another_document = None
    test_cold_restore_link_restores_and_opens = None
    test_service_worker_carries_the_restore_action_into_a_new_window = None


# ---------------------------------------------------------------- pin-scoped [View changes] and the viewer's Trash controls (v0.3, issue #9)


class ScopedViewer(BrowserBase):
    """The viewer's [View changes] for a pin on desktop, fold and phone in Korean and English."""

    WHO = ALICE

    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        ps.record_person(A)
        self.repo = self.main.parent.parent
        self.main.write_text(OLD, encoding="utf-8")
        for args in (("init", "--quiet"), ("config", "user.email", "t@example.com"), ("config", "user.name", "T")):
            self.git(*args)
        self.commit("first")
        self.p1 = add_pin({"file": str(self.main), "lo": 4, "hi": 4, "page": 1, "note": "alpha"}, A).record["id"]
        self.p2 = add_pin({"file": str(self.main), "lo": 11, "hi": 11, "page": 1, "note": "beta"}, A).record["id"]
        self.p3 = add_pin({"file": str(self.main), "lo": 18, "hi": 18, "page": 1, "note": "gamma"}, A).record["id"]
        self.write(NEW)
        self.fix = self.commit("fix three pins")
        loc = dict(LOCAL_ACTOR)
        ps.close_pin(
            self.p1,
            loc,
            CloseRequest(
                reply="alpha", ref=self.fix[:8], changes=(parse.CloseChange(str(self.main.resolve()), 4, 5).record(),)
            ),
        )
        ps.close_pin(self.p2, loc, CloseRequest(reply="beta", ref=self.fix[:8]))
        ps.close_pin(self.p3, loc, CloseRequest(reply="gamma", ref=self.fix[:8]))
        self.p4 = add_pin({"file": str(self.main), "lo": 8, "hi": 8, "page": 1, "note": "filler"}, A).record["id"]
        self.write(NEW.replace("Filler two.", "Filler two, reworded."))
        self.solo = self.commit("fix the filler pin")
        ps.close_pin(self.p4, loc, CloseRequest(reply="filler", ref=self.solo[:8]))
        self.builds = []
        self.fail_scoped = False
        patcher = mock.patch.object(revisions, "revision_compile", side_effect=self.fake_compile)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_compile(self, spec, jobdir, timeout):
        self.builds.append((spec.head, spec.scope))
        if spec.scope and self.fail_scoped:
            return revisions.StepFailed("compile_failed")
        (jobdir / "revision.pdf").write_bytes(minimal_pdf("pin" if spec.scope else "whole"))
        return revisions.ComparisonBuilt([])

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def write(self, text):
        self.main.write_text(text, encoding="utf-8")
        t = time.time() + 5
        os.utime(self.main, (t, t))

    def commit(self, msg):
        self.git("add", "ms")
        self.git("commit", "--quiet", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()

    def open_change(self, device, lang, pid):
        page = self._page = self.open(0, lang=lang, **DEVICES[device])
        page.evaluate("showChange(%d)" % pid)
        page.wait_for_function(
            "REVISION_SOURCE_COMMIT&&document.querySelectorAll('#revision-diff .rd-line').length>0", timeout=15000
        )
        settle(page)
        return page

    def visible(self, page, sel):
        return page.evaluate(
            "(()=>{const e=document.querySelector(%s);return !!e&&!e.closest('[hidden]')&&e.getClientRects().length>0;})()"
            % json.dumps(sel)
        )

    def fits(self, page, sel, device):
        box = page.evaluate(
            "(()=>{const r=document.querySelector(%s).getBoundingClientRect();return [r.left,r.right,r.height,innerWidth];})()"
            % json.dumps(sel)
        )
        self.assertGreaterEqual(box[0], 0, sel)
        self.assertLessEqual(box[1], box[3] + 0.5, sel)
        if device != "desktop":
            self.assertGreaterEqual(box[2], 44, sel)  # touch target

    def english_only(self, page, sel):
        text = page.inner_text(sel)
        self.assertFalse(HANGUL.search(text), (sel, text))

    def wait_pdf(self, page):
        page.wait_for_function("document.querySelectorAll('#revision-pdf .revision-page').length>0", timeout=15000)

    def test_pin_view_folds_other_changes_and_toggles_the_whole_commit_pdf(self):
        """The two controls on desktop/fold/phone x ko/en: fold toggle, [Whole commit] toggle, cached rebuilds, touch sizes."""
        for device in DEVICES:
            for lang in ("ko", "en"):
                with self.subTest(device=device, lang=lang):
                    self.tearDown()
                    self.setUp()
                    self.flow(device, lang)

    def flow(self, device, lang):
        t = TXT[lang]
        page = self.open_change(device, lang, self.p2)
        diff = page.inner_text("#revision-diff")
        self.assertIn("blueberries", diff)
        self.assertNotIn("pears", diff)
        self.assertNotIn("Gamma", diff)
        tog = "#revision-other-toggle"
        self.assertTrue(self.visible(page, tog))
        self.assertEqual(page.get_attribute(tog, "aria-expanded"), "false")
        self.assertIn(t["other"], page.inner_text(tog))
        self.assertFalse(self.visible(page, "#revision-other"))
        self.fits(page, tog, device)
        page.click(tog)
        self.assertEqual(page.get_attribute(tog, "aria-expanded"), "true")
        other = page.inner_text("#revision-other")
        self.assertIn("pears", other)
        self.assertIn("Gamma", other)
        self.assertNotIn("blueberries", other)
        page.click(tog)
        self.assertFalse(self.visible(page, "#revision-other"))
        if lang == "en":
            self.english_only(page, "#revision-source")
        # the comparison PDF: this pin's hunks only, one toggle to the whole commit
        page.click("#revision-pdf-tab")
        self.wait_pdf(page)
        self.assertEqual(self.builds[-1][0], self.fix)
        self.assertEqual(len(self.builds[-1][1]), 1)
        whole = "#revision-whole"
        self.assertTrue(self.visible(page, whole))
        self.assertEqual(page.get_attribute(whole, "aria-pressed"), "false")
        self.assertIn(t["whole"], page.inner_text(whole))
        self.assertIn(t["only"] % self.p2, page.inner_text("#revision-status"))
        self.fits(page, whole, device)
        page.click(whole)
        page.wait_for_function("document.getElementById('revision-whole').getAttribute('aria-pressed')==='true'")
        self.wait_pdf(page)
        page.wait_for_function(
            "!/%s/.test(document.getElementById('revision-status').textContent)" % re.escape(t["only"] % self.p2)
        )
        self.assertEqual(self.builds[-1], (self.fix, ()))
        page.click(whole)
        self.wait_pdf(page)
        self.assertEqual(page.get_attribute(whole, "aria-pressed"), "false")
        page.wait_for_function(
            "document.getElementById('revision-status').textContent.includes(%s)" % json.dumps(t["only"] % self.p2)
        )
        self.assertEqual(len(self.builds), 2)  # both comparisons are cached; toggling back builds nothing
        # the approximate-page note stays
        self.assertTrue(self.visible(page, "#revision-pin"))
        if lang == "en":
            self.english_only(page, "#revision-controls")
            self.english_only(page, "#revision-status")
            self.english_only(page, "#revision-pin")

    def test_a_commit_that_is_the_pins_own_has_no_extra_controls(self):
        """A pin that owns its whole commit sees the 0.2.2 view: no fold toggle, no PDF toggle, the whole-commit build."""
        for device in ("desktop", "phone"):
            with self.subTest(device=device):
                self.tearDown()
                self.setUp()
                page = self.open_change(device, "ko", self.p4)
                self.assertIn("reworded", page.inner_text("#revision-diff"))
                self.assertFalse(self.visible(page, "#revision-other-toggle"))
                page.click("#revision-pdf-tab")
                self.wait_pdf(page)
                self.assertFalse(self.visible(page, "#revision-whole"))
                self.assertEqual(self.builds, [(self.solo, ())])

    def test_a_subset_that_fails_to_compile_falls_back_to_the_whole_commit(self):
        """When the scoped build fails the viewer builds the whole commit once, says so in one line, and hides the toggle."""
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                self.tearDown()
                self.setUp()
                self.fail_scoped = True
                page = self.open_change("desktop", lang, self.p3)
                page.click("#revision-pdf-tab")
                self.wait_pdf(page)
                self.assertEqual([len(b[1]) for b in self.builds], [1, 0])
                self.assertIn(TXT[lang]["fallback"], page.inner_text("#revision-status"))
                self.assertFalse(self.visible(page, "#revision-whole"))
                if lang == "en":
                    self.english_only(page, "#revision-status")

    def test_switching_to_another_commit_shows_it_whole_without_pin_scope(self):
        """Review M1 (viewer): the pin's scope applies only to the commit picked for it. Choosing another commit in
        the list shows that commit whole - no &pin= on the diff or the PDF - and choosing the pin's commit again
        scopes it again."""
        page = self.open_change("desktop", "ko", self.p2)
        urls = []
        page.on("request", lambda r: urls.append(r.url))
        page.select_option("#revision-select", self.solo)  # another commit: the list opens its PDF
        self.wait_pdf(page)
        self.assertFalse(self.visible(page, "#revision-whole"))
        self.assertEqual(self.builds[-1], (self.solo, ()))
        page.click("#revision-source-tab")
        page.wait_for_function("REVISION_SOURCE_COMMIT===%s" % json.dumps(self.solo), timeout=15000)
        self.assertIn("reworded", page.inner_text("#revision-diff"))
        self.assertFalse(self.visible(page, "#revision-other-toggle"))
        seen = [u for u in urls if "/api/revision-" in u and self.solo in u]
        self.assertTrue(seen)
        self.assertFalse([u for u in seen if "pin=" in u], seen)
        page.select_option("#revision-select", self.fix)  # back to the pin's own commit: scoped again
        self.wait_pdf(page)
        page.wait_for_function("!document.getElementById('revision-whole').hidden", timeout=15000)
        self.assertEqual(self.builds[-1][0], self.fix)
        self.assertEqual(len(self.builds[-1][1]), 1)
        page.click("#revision-source-tab")
        page.wait_for_function(
            "REVISION_SOURCE_COMMIT===%s&&!document.getElementById('revision-other-toggle').hidden"
            % json.dumps(self.fix),
            timeout=15000,
        )
        self.assertNotIn("pears", page.inner_text("#revision-diff"))

    def test_other_changes_start_folded_for_the_next_pin(self):
        """Opening [View changes] for another pin starts with the other changes folded and only that pin's hunks."""
        page = self.open_change("desktop", "ko", self.p2)
        page.click("#revision-other-toggle")
        page.evaluate("showChange(%d)" % self.p1)
        page.wait_for_function("document.getElementById('revision-diff').textContent.includes('pears')", timeout=15000)
        self.assertEqual(page.get_attribute("#revision-other-toggle", "aria-expanded"), "false")
        self.assertFalse(self.visible(page, "#revision-other"))
        self.assertNotIn("blueberries", page.inner_text("#revision-diff"))


class ViewerTrashControls(BrowserBase):
    """A viewer can open the Trash and read it, but sees no [되살리기]/[영구 삭제] (the server refuses both with 403 anyway)."""

    WHO = CAROL

    def setUp(self):
        super().setUp()
        ps.record_person(A)
        ps.C.people_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "people": [
                        {"login": "alice@example.com", "name": "Alice Kim", "role": "owner"},
                        {"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "남은 핀"}, A).record["id"]
        self.gone = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "지운 핀"}, A).record["id"]
        ps.drop_pin(self.gone, A)

    def test_viewer_role_sees_no_restore_or_purge_in_the_trash(self):
        """E2E finding: a viewer reads the Trash but gets no [Restore]/[Delete forever] (server refuses with 403 anyway)."""
        for device in DEVICES:
            for lang in ("ko", "en"):
                with self.subTest(device=device, lang=lang):
                    page = self.open(1, lang=lang, **DEVICES[device])
                    page.wait_for_function("DROPPED.length===1", timeout=10000)
                    page.evaluate("openTrash()")
                    page.wait_for_selector('#trash-list .arc-row[data-id="%d"]' % self.gone)
                    row = '#trash-list .arc-row[data-id="%d"]' % self.gone
                    self.assertIn("지운 핀", page.inner_text(row))  # reading stays
                    shown = page.evaluate(
                        "[...document.querySelectorAll('#trash [data-act]')].filter(e=>e.getClientRects().length)"
                        ".map(e=>e.dataset.act)"
                    )
                    self.assertFalse({"restore", "purge"} & set(shown), shown)
                    self.assertEqual(
                        page.locator(row + " .b-restore").count() + page.locator(row + " .b-purge").count(), 0
                    )
                    page.evaluate("document.getElementById('trash').close()")


# ---------------------------------------------------------------- the question nudge and the viewer role (v0.2.1 QA)


class QuestionNudgeFocus(BrowserBase):
    def test_ctrl_enter_saves_after_send_as_question(self):
        page = self.open(0)
        self.open_composer(page)
        page.click("#note")
        page.keyboard.type("이 값은 어디서 왔나요?")
        page.wait_for_selector("#c-qhint:not([hidden])")
        page.click('#c-qhint [data-act="kind"]')
        self.assertEqual(page.evaluate("document.activeElement.id"), "note")
        self.assertEqual(page.evaluate("KIND_NEW"), "question")
        page.keyboard.press("Control+Enter")
        page.wait_for_function("OPEN_ALL.length===1", timeout=8000)
        rows = ps.snapshot_pins()
        self.assertEqual([(r["note"], r.get("kind_req")) for r in rows], [("이 값은 어디서 왔나요?", "question")])

    def test_ctrl_enter_from_the_kind_buttons_still_saves(self):
        page = self.open(0)
        self.open_composer(page)
        page.click("#note")
        page.keyboard.type("표현 다듬기")
        page.click('#c-kind [data-kind="question"]')
        page.keyboard.press("Control+Enter")
        page.wait_for_function("OPEN_ALL.length===1", timeout=8000)


class ViewerRoleUi(BrowserBase):
    WHO = CAROL
    STATE_CHANGING = ("edit", "drop", "close", "reply-open", "rv-reopen", "confirm", "reopen", "restore", "unclaim")

    def setUp(self):
        super().setUp()
        ps.record_person(actor(ALICE))
        ps.C.people_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "people": [
                        {"login": "alice@example.com", "name": "Alice Kim"},
                        {"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "문단 줄이기"}, actor(ALICE)
        ).record["id"]
        ps.reply_pin(pid, "답글", actor(ALICE))
        rid = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "검토할 핀"}, actor(ALICE)).record[
            "id"
        ]
        ps.close_pin(rid, dict(LOCAL_ACTOR), CloseRequest(reply="고침"))

    def visible_acts(self, page):
        return page.evaluate(
            "[...document.querySelectorAll('[data-act]')].filter(e=>e.getClientRects().length&&!e.disabled)"
            ".map(e=>e.dataset.act)"
        )

    def test_viewer_sees_no_state_changing_controls(self):
        for name, device in (
            ("desktop", {"viewport": {"width": 1400, "height": 850}}),
            ("phone", {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True}),
        ):
            with self.subTest(device=name):
                page = self.open(1, **device)
                page.evaluate("setSide(true); OPEN_CARDS.add(1); drawPins()")
                settle(page)
                acts = self.visible_acts(page)
                self.assertIn("view", acts)  # reading still works
                self.assertEqual(sorted(set(acts) & set(self.STATE_CHANGING + ("rebuild",))), [], acts)
                self.open_composer(page)
                self.assertFalse(page.is_visible("#btn-save"))
                self.assertFalse(page.is_visible("#note"))
                self.assertTrue(page.is_visible("#c-viewer"))
                self.assertTrue(page.is_visible("#c-loc"))  # the location is still shown (read)
                n = len(ps.snapshot_pins())
                page.keyboard.press("Control+Enter")
                page.evaluate("savePin()")
                settle(page)
                self.assertEqual(len(ps.snapshot_pins()), n)

    def test_viewer_notice_is_translated(self):
        page = self.open(1, lang="en")
        self.open_composer(page)
        text = page.inner_text("#c-viewer")
        self.assertFalse(re.search(r"[가-힣]", text), text)

    def test_editor_still_sees_them(self):
        type(self).WHO = ALICE
        try:
            page = self.open(1)
            page.evaluate("OPEN_CARDS.add(1); drawPins()")
            acts = self.visible_acts(page)
            for a in ("edit", "close", "reply-open", "rebuild"):
                self.assertIn(a, acts)
        finally:
            type(self).WHO = CAROL
