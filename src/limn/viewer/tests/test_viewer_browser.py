"""The real viewer in Chromium against the in-process server (helpers_browser.BrowserBase): whole feature flows.

The flows run on a desktop 1400x850 and, where the layout differs, an unfolded Fold 842x758 and a phone 384x832
(touch), in Korean and English:

- one [Reply] with its outcome preview, undo and keep-state switch, the Trash with undo, restore and permanent delete,
  collapsible sections, and cold deep links from a notification (v0.2.2, issue #8);
- pin-scoped [View changes] and the viewer role's Trash (v0.3, issue #9);
- the question nudge's focus and what the viewer role sees (v0.2.1 QA).

Pointer and touch input (panel collapse, gestures) is test_viewer_input.py; the page's structure and pure functions
are test_viewer.py. Skipped without Playwright or Chromium, a failure under LIMN_TEST_REQUIRE_BROWSER=1.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_browser.py
"""

import json
import os
import re
import shutil
import subprocess
import time
from unittest import mock
from urllib.parse import urlparse

from limn.administration import serve_documents as startup_documents
from limn.pins.lifecycle import input as lifecycle_input
from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.listing.projection import pin_state
from limn.revisions import core as revisions, execution as revision_execution
from limn.security.access import LOCAL_ACTOR

import helpers_figure
from helpers import SW_JS, add_pin, blank_png, find_record, minimal_pdf, ps, records, trash_records
from helpers_access import ALICE, BOB, CAROL, REPO_NEW as NEW, REPO_OLD as OLD, actor
from helpers_authority import post_authority
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
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
            CloseRequest(reply="fixed"),
        )
        page = self.open(0, init=SLOW_PIN_LIST)
        self.assertTrue(page.evaluate("findAnyPin(%d)!==null" % pid))


# ---------------------------------------------------------------- one [Reply], the Trash and collapsible sections (v0.2.2, issue #8)


class ViewerFlows(BrowserBase):
    """Exercise reply, trash, undo, and list flows end to end against the real viewer."""

    WHO = ALICE

    def setUp(self):
        """Seed open, agent-review, and human-done pins with known participants for browser lifecycle flows."""
        super().setUp()
        for h in (ALICE, BOB, CAROL):
            ps.APP.people_directory.record(actor(h))
        self.open_id = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "문단 줄이기"}, A).record[
            "id"
        ]
        self.rv = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "식 번호 확인"}, A).record["id"]
        ps.APP.pin_lifecycle.close_pin(
            self.rv,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", self.rv),
            CloseRequest(reply="식 번호를 고쳤습니다", ref="PR #9"),
        )
        self.dn = add_pin({"file": str(self.main), "lo": 12, "hi": 13, "page": 2, "note": "오타"}, A).record["id"]
        ps.APP.pin_lifecycle.close_pin(
            self.dn,
            post_authority(ps.APP.pin_lifecycle.context().store, A, "close", self.dn),
            CloseRequest(reply="고침"),
        )

    def state(self, pid):
        return pin_state(find_record(ps.APP.snapshot_pins(), pid))

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
            last = find_record(ps.APP.snapshot_pins(), self.rv)["thread"][-1]
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
            last = find_record(ps.APP.snapshot_pins(), self.rv)["thread"][-1]
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
        """A concurrent close updates the reply outcome preview without discarding the text being typed."""
        page = self.page_for("desktop", "ko")
        card = '#pins .pin[data-id="%d"]' % self.open_id
        page.click(card + " .acts [data-act=reply-open]")
        page.fill("textarea.r-text", "이 문장도 봐 주세요")
        self.assertFalse(page.is_visible(".r-outcome"))  # open pin: a reply never changes it
        ps.APP.pin_lifecycle.close_pin(
            self.open_id,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", self.open_id),
            CloseRequest(reply="줄였습니다"),
        )  # the agent closes it meanwhile
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
        self.assertIsNotNone(find_record(ps.APP.snapshot_pins(), self.open_id))
        self.assertEqual(trash_records(), [])

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
            self.assertIsNone(find_record(ps.APP.snapshot_pins(), self.open_id))
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
            self.assertIsNotNone(find_record(ps.APP.snapshot_pins(), self.open_id))

        self.run_matrix(flow)

    def test_owner_deletes_forever_with_undo(self):
        """Trash purge stays undoable until the toast is dismissed, then removes the persisted trash record."""
        ps.APP.C.people_file.write_text(
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
        ps.APP.pin_trash.drop_pin(
            self.open_id, post_authority(ps.APP.pin_trash.context().store, B, "drop", self.open_id)
        )
        page = self.page_for("desktop", "ko", n_open=0)
        page.click("#trash-link")
        row = '#trash .arc-row[data-id="%d"]' % self.open_id
        page.wait_for_selector(row + " [data-act=purge]")
        page.click(row + " [data-act=purge]")
        tst = self.toast(page, "되돌리기")
        tst.get_by_role("button", name="되돌리기").click()
        settle(page)
        self.assertEqual([r["id"] for r in trash_records()], [self.open_id])
        page.click(row + " [data-act=purge]")
        self.toast(page, "되돌리기").locator("button.btn-icon").click()
        settle(page)  # the permanent delete the dismissed toast sends has been answered
        self.assertEqual(trash_records(), [])

    def test_ref_to_deleted_pin_in_a_thread(self):
        """Thread references to deleted pins show localized gone text and navigate into the corresponding trash row."""
        ps.APP.pin_lifecycle.reply_pin(
            self.open_id,
            "#%d 와 같은 문제" % self.dn,
            post_authority(ps.APP.pin_lifecycle.context().store, B, "reply", self.open_id),
        )
        ps.APP.pin_trash.drop_pin(self.dn, post_authority(ps.APP.pin_trash.context().store, A, "drop", self.dn))
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
        """Create two paginated documents with distant live and deleted targets for cold deep-link navigation."""
        super().setUp()
        src = ps.APP.C.src
        (src / "hl.tex").write_text((src / "main.tex").read_text(encoding="utf-8"), encoding="utf-8")
        ps.APP.set_docs(startup_documents.make_docs(["ms=본문:main.tex", "hl=하이라이트:hl.tex"], src, ps.APP.C.paths))
        for D in ps.APP.docs:
            pages = D.dir / "pages-20260925100000"
            pages.mkdir(parents=True, exist_ok=True)
            for i in (1, 2):
                (pages / ("page-%d.png" % i)).write_bytes(blank_png(1275, 1650))
            (D.dir / "pages.cur").write_text(pages.name)
            (D.dir / "built_at.txt").write_text("2026-09-25 10:00:00")
            (D.dir / "head.txt").write_text("abc1234")
        ms, hl = ps.APP.docs
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
        ps.APP.pin_trash.drop_pin(self.gone, post_authority(ps.APP.pin_trash.context().store, B, "drop", self.gone))
        self.addCleanup(ps.APP.set_docs, None)

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
        self.assertIsNotNone(find_record(ps.APP.snapshot_pins(), self.gone))
        self.assert_card_shown(page, self.gone, "desktop")
        self.assertEqual(page.evaluate("location.hash"), "#doc=hl")

    def test_draft_and_build_baseline_survive_document_round_trip(self):
        """A→B→A keeps the note, restores its stored draft, and resets build state to the active document."""
        page = self.cold("#doc=ms", "desktop")
        page.wait_for_function("LIGHT_TIMER&&DOC==='ms'", timeout=8000)
        self.open_composer(page)
        page.locator("#note").fill("Round trip draft")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        for key in ("hl", "ms"):
            page.evaluate("async key=>{await switchDoc(key);await pollBuild();}", key)
            page.wait_for_function("key=>DOC===key&&BUILD.lastSeq===META.build_seq", arg=key, timeout=8000)
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        self.assertEqual(page.locator("#note").input_value(), "Round trip draft")
        page.reload()
        page.wait_for_function("LIGHT_TIMER&&DOC==='ms'&&DRAFT.ready", timeout=20000)
        self.assertEqual(page.locator("#note").input_value(), "Round trip draft")

    def test_draft_stays_with_its_document_during_a_long_visit_elsewhere(self):
        """A draft survives time on B and a B reload without appearing as B's draft or losing A's selection."""
        page = self.cold("#doc=ms", "desktop")
        self.open_composer(page)
        page.locator("#note").fill("Only on A")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate("async()=>await switchDoc('hl')")
        page.wait_for_function("DOC==='hl'&&DRAFT.timer===0", timeout=8000)
        page.reload()
        page.wait_for_function("LIGHT_TIMER&&DOC==='hl'&&DRAFT.ready", timeout=20000)
        self.assertEqual(page.locator("#note").input_value(), "")
        self.assertIsNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'hl'))"))
        self.assertIsNotNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'ms'))"))
        self.open_composer(page)
        page.locator("#note").fill("Only on B")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'hl'))", timeout=8000)
        page.evaluate("async()=>await switchDoc('ms')")
        page.reload()
        page.wait_for_function("LIGHT_TIMER&&DOC==='ms'&&DRAFT.ready", timeout=20000)
        self.assertEqual(page.locator("#note").input_value(), "Only on A")
        self.assertIsNotNone(page.evaluate("COMPOSE.current"))
        page.evaluate("async()=>await switchDoc('hl')")
        page.reload()
        page.wait_for_function("LIGHT_TIMER&&DOC==='hl'&&DRAFT.ready", timeout=20000)
        self.assertEqual(page.locator("#note").input_value(), "Only on B")

    def test_inflight_save_preserves_new_selection_after_document_round_trip(self):
        """A save started on A still writes its pin but cannot clear a new A selection after A→B→A."""
        page = self.cold("#doc=ms", "desktop")
        self.open_composer(page)
        page.locator("#note").fill("Saved during round trip")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate(
            """() => {const realApi=api; api=(path,options) => {
              const result=realApi(path,options);
              if(path==='/api/pin'&&options?.method==='POST')
                return result.then(value=>new Promise(resolve=>{window.releaseSave=()=>resolve(value);}));
              return result;};}"""
        )
        page.evaluate("() => {savePin();}")
        page.wait_for_function("typeof window.releaseSave==='function'", timeout=8000)
        for key in ("hl", "ms"):
            page.evaluate("async key=>await switchDoc(key)", key)
            page.wait_for_function("key=>DOC===key", arg=key, timeout=8000)
        self.open_composer(page)
        page.locator("#note").fill("New selection after round trip")
        page.evaluate("window.newSelection=COMPOSE.current")
        page.evaluate("window.releaseSave()")
        page.wait_for_function("!COMPOSE.saving&&OPEN_ALL.some(p=>p.note==='Saved during round trip')", timeout=8000)
        self.assertTrue(page.evaluate("COMPOSE.current===window.newSelection"))
        self.assertEqual(page.locator("#note").input_value(), "New selection after round trip")
        self.assertFalse(page.locator("#composer").evaluate("node=>node.hidden"))

    def test_save_finishing_on_b_clears_only_the_saved_a_draft(self):
        """A successful A save removes its old draft after a switch, leaving B's newer draft untouched."""
        page = self.cold("#doc=ms", "desktop")
        self.open_composer(page)
        page.locator("#note").fill("Saved A draft")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate(
            """() => {const realApi=api; api=(path,options) => {
              const result=realApi(path,options);
              if(path==='/api/pin'&&options?.method==='POST')
                return result.then(value=>new Promise(resolve=>{window.releaseSave=()=>resolve(value);}));
              return result;};}"""
        )
        page.evaluate("() => {savePin();}")
        page.wait_for_function("typeof window.releaseSave==='function'", timeout=8000)
        page.evaluate("async()=>await switchDoc('hl')")
        self.open_composer(page)
        page.locator("#note").fill("New B draft")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'hl'))", timeout=8000)
        page.evaluate("window.releaseSave()")
        page.wait_for_function("!COMPOSE.saving&&OPEN_ALL.some(p=>p.note==='Saved A draft')", timeout=8000)
        self.assertIsNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'ms'))"))
        self.assertIsNotNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'hl'))"))
        self.assertEqual(page.locator("#note").input_value(), "New B draft")

    def test_append_finishing_on_b_clears_only_the_appended_a_draft(self):
        """An A append completed on B removes its old A draft and keeps B's new draft."""
        page = self.cold("#doc=ms", "desktop")
        pid = page.evaluate("() => OPEN_ALL.find(p=>p.doc==='ms').id")
        self.open_composer(page)
        page.locator("#note").fill("Appended A note")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate(
            """() => {const realApi=api; api=(path,options) => {
              const result=realApi(path,options);
              if(path.endsWith('/edit')&&options?.method==='POST')
                return result.then(value=>new Promise(resolve=>{window.releaseAppend=()=>resolve(value);}));
              return result;};}"""
        )
        page.evaluate("id=>{appendToPin(id,'Appended A note');}", pid)
        page.wait_for_function("typeof window.releaseAppend==='function'", timeout=8000)
        page.evaluate("async()=>await switchDoc('hl')")
        self.open_composer(page)
        page.locator("#note").fill("New B draft")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'hl'))", timeout=8000)
        page.evaluate("window.releaseAppend()")
        page.wait_for_function(
            "id=>OPEN_ALL.some(p=>p.id===id&&p.note.includes('Appended A note'))", arg=pid, timeout=8000
        )
        self.assertIsNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'ms'))"))
        self.assertIsNotNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'hl'))"))
        self.assertEqual(page.locator("#note").input_value(), "New B draft")

    def test_append_finishing_after_return_preserves_a_new_a_draft(self):
        """A late append keeps the newer selection and draft made after A→B→A."""
        page = self.cold("#doc=ms", "desktop")
        pid = page.evaluate("() => OPEN_ALL.find(p=>p.doc==='ms').id")
        self.open_composer(page)
        page.locator("#note").fill("Appended A note")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate(
            """() => {const realApi=api; api=(path,options) => {
              const result=realApi(path,options);
              if(path.endsWith('/edit')&&options?.method==='POST')
                return result.then(value=>new Promise(resolve=>{window.releaseAppend=()=>resolve(value);}));
              return result;};}"""
        )
        page.evaluate("id=>{appendToPin(id,'Appended A note');}", pid)
        page.wait_for_function("typeof window.releaseAppend==='function'", timeout=8000)
        for key in ("hl", "ms"):
            page.evaluate("async key=>await switchDoc(key)", key)
        self.open_composer(page)
        page.locator("#note").fill("New A draft")
        page.wait_for_function(
            "DRAFT.timer===0&&sessionStorage.getItem(draftKey(META.label,'ms')).includes('New A draft')", timeout=8000
        )
        page.evaluate("window.newSelection=COMPOSE.current;window.releaseAppend()")
        page.wait_for_function(
            "id=>OPEN_ALL.some(p=>p.id===id&&p.note.includes('Appended A note'))", arg=pid, timeout=8000
        )
        self.assertTrue(page.evaluate("COMPOSE.current===window.newSelection"))
        self.assertIn("New A draft", page.evaluate("sessionStorage.getItem(draftKey(META.label,'ms'))"))

    def test_repick_cancel_preserves_completed_composer_selection(self):
        """Opening and cancelling repick leaves a completed new-pin choice and its note in place."""
        page = self.cold("#doc=ms", "desktop")
        pid = page.evaluate("() => OPEN_ALL.find(p=>p.doc==='ms').id")
        self.open_composer(page)
        page.locator("#note").fill("Keep selected lines")
        page.evaluate("window.chosen=COMPOSE.current")
        page.evaluate("async id=>{openEdit(id);await startRepick();cancelRepick();}", pid)
        self.assertTrue(page.evaluate("COMPOSE.current===window.chosen"))
        self.assertFalse(page.locator("#composer").evaluate("node=>node.hidden"))
        self.assertEqual(page.locator("#note").input_value(), "Keep selected lines")

    def test_save_finishing_after_return_clears_untouched_restored_a_draft(self):
        """A saved pin closes the exact A draft restored by A→B→A while the POST was pending."""
        page = self.cold("#doc=ms", "desktop")
        self.open_composer(page)
        page.locator("#note").fill("Already saved A")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate(
            """() => {const realApi=api; api=(path,options) => {
              const result=realApi(path,options);
              if(path==='/api/pin'&&options?.method==='POST')
                return result.then(value=>new Promise(resolve=>{window.releaseSave=()=>resolve(value);}));
              return result;};}"""
        )
        page.evaluate("() => {savePin();}")
        page.wait_for_function("typeof window.releaseSave==='function'", timeout=8000)
        for key in ("hl", "ms"):
            page.evaluate("async key=>await switchDoc(key)", key)
        page.wait_for_function("COMPOSE.current&&!document.querySelector('#composer').hidden", timeout=8000)
        page.evaluate("window.releaseSave()")
        page.wait_for_function("OPEN_ALL.some(p=>p.note==='Already saved A')", timeout=8000)
        page.wait_for_function("!COMPOSE.current&&document.querySelector('#composer').hidden", timeout=8000)
        self.assertIsNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'ms'))"))

    def test_save_finishing_after_return_keeps_unsaved_a_note_edit(self):
        """A note edited after draft restore survives the old POST even before its debounce writes storage."""
        page = self.cold("#doc=ms", "desktop")
        self.open_composer(page)
        page.locator("#note").fill("Submitted A note")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate(
            """() => {const realApi=api; api=(path,options) => {
              const result=realApi(path,options);
              if(path==='/api/pin'&&options?.method==='POST')
                return result.then(value=>new Promise(resolve=>{window.releaseSave=()=>resolve(value);}));
              return result;};}"""
        )
        page.evaluate("() => {savePin();}")
        page.wait_for_function("typeof window.releaseSave==='function'", timeout=8000)
        for key in ("hl", "ms"):
            page.evaluate("async key=>await switchDoc(key)", key)
        page.wait_for_function("COMPOSE.current&&!document.querySelector('#composer').hidden", timeout=8000)
        page.evaluate(
            """() => {window.newSelection=COMPOSE.current;const note=$('#note');note.value='Edited after return';
              note.dispatchEvent(new Event('input',{bubbles:true}));window.releaseSave();}"""
        )
        page.wait_for_function("OPEN_ALL.some(p=>p.note==='Submitted A note')", timeout=8000)
        self.assertTrue(page.evaluate("COMPOSE.current===window.newSelection"))
        self.assertEqual(page.locator("#note").input_value(), "Edited after return")
        page.wait_for_function(
            "DRAFT.timer===0&&sessionStorage.getItem(draftKey(META.label,'ms')).includes('Edited after return')",
            timeout=8000,
        )

    def test_append_finishing_after_return_clears_untouched_restored_a_draft(self):
        """A completed append closes the exact A draft restored by A→B→A."""
        page = self.cold("#doc=ms", "desktop")
        pid = page.evaluate("() => OPEN_ALL.find(p=>p.doc==='ms').id")
        self.open_composer(page)
        page.locator("#note").fill("Already appended A")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate(
            """() => {const realApi=api; api=(path,options) => {
              const result=realApi(path,options);
              if(path.endsWith('/edit')&&options?.method==='POST')
                return result.then(value=>new Promise(resolve=>{window.releaseAppend=()=>resolve(value);}));
              return result;};}"""
        )
        page.evaluate("id=>{appendToPin(id,'Already appended A');}", pid)
        page.wait_for_function("typeof window.releaseAppend==='function'", timeout=8000)
        for key in ("hl", "ms"):
            page.evaluate("async key=>await switchDoc(key)", key)
        page.wait_for_function("COMPOSE.current&&!document.querySelector('#composer').hidden", timeout=8000)
        page.evaluate("window.releaseAppend()")
        page.wait_for_function(
            "id=>OPEN_ALL.some(p=>p.id===id&&p.note.includes('Already appended A'))", arg=pid, timeout=8000
        )
        page.wait_for_function("!COMPOSE.current&&document.querySelector('#composer').hidden", timeout=8000)
        self.assertIsNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'ms'))"))

    def test_a_discard_undo_does_not_replace_a_b_note_draft(self):
        """An old A undo cannot overwrite a note-only draft already restored for B."""
        page = self.cold("#doc=ms", "desktop")
        self.open_composer(page)
        page.locator("#note").fill("Discarded A note")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate(
            """() => sessionStorage.setItem(draftKey(META.label,'hl'),JSON.stringify({
              v:1,doc:'hl',build:'',cur:null,note:'Existing B note',mentions:[],kind:'fix',
              assign:{v:'agent',touched:false}}))"""
        )
        page.evaluate("discardSelection()")
        page.evaluate("async()=>await switchDoc('hl')")
        page.wait_for_function("DOC==='hl'&&document.querySelector('#note').value==='Existing B note'", timeout=8000)
        page.locator("#toasts .toast", has_text="선택 취소됨").locator("button", has_text="되돌리기").click()
        self.assertEqual(page.locator("#note").input_value(), "Existing B note")
        self.assertIsNotNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'hl'))"))
        self.assertIsNotNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'ms'))"))

    def test_a_discard_toast_expiry_does_not_remove_b_draft(self):
        """Ending A's discard window removes only A's held version after B has written a draft."""
        page = self.cold("#doc=ms", "desktop")
        self.open_composer(page)
        page.locator("#note").fill("Discarded A note")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate("discardSelection()")
        page.evaluate("async()=>await switchDoc('hl')")
        self.open_composer(page)
        page.locator("#note").fill("B note")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'hl'))", timeout=8000)
        page.locator("#toasts .toast", has_text="선택 취소됨").locator("button[aria-label]").click()
        self.assertIsNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'ms'))"))
        self.assertIsNotNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,'hl'))"))
        self.assertEqual(page.locator("#note").input_value(), "B note")

    def test_old_discard_toast_does_not_remove_a_new_a_draft(self):
        """An old A toast loses ownership once a later A draft has replaced its stored version."""
        page = self.cold("#doc=ms", "desktop")
        self.open_composer(page)
        page.locator("#note").fill("Old A note")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate("discardSelection()")
        for key in ("hl", "ms"):
            page.evaluate("async key=>await switchDoc(key)", key)
        page.wait_for_function("COMPOSE.current&&!document.querySelector('#composer').hidden", timeout=8000)
        page.locator("#note").fill("New A note")
        page.wait_for_function(
            "DRAFT.timer===0&&sessionStorage.getItem(draftKey(META.label,'ms')).includes('New A note')", timeout=8000
        )
        page.locator("#toasts .toast", has_text="선택 취소됨").locator("button[aria-label]").click()
        self.assertIn("New A note", page.evaluate("sessionStorage.getItem(draftKey(META.label,'ms'))"))

    def test_old_discard_toast_does_not_remove_the_restored_a_draft(self):
        """A restored selection owns its draft even when its stored bytes still match the old held version."""
        page = self.cold("#doc=ms", "desktop")
        self.open_composer(page)
        page.locator("#note").fill("A note")
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        page.evaluate("discardSelection()")
        for key in ("hl", "ms"):
            page.evaluate("async key=>await switchDoc(key)", key)
        page.wait_for_function("COMPOSE.current&&!document.querySelector('#composer').hidden", timeout=8000)
        page.locator("#toasts .toast", has_text="선택 취소됨").locator("button[aria-label]").click()
        self.assertIn("A note", page.evaluate("sessionStorage.getItem(draftKey(META.label,'ms'))"))

    def test_repick_releases_waiting_selection_without_losing_note(self):
        """Repick takes over an unfinished drag, clearing its save queue and box while retaining the note draft."""
        page = self.cold("#doc=ms", "desktop")
        pid = page.evaluate("() => OPEN_ALL.find(p=>p.doc==='ms').id")
        page.evaluate(
            """() => {const realApi=api; api=(path,options) => {
              const result=realApi(path,options);
              if(path==='/api/pick')
                return result.then(value=>new Promise(resolve=>{window.releasePick=()=>resolve(value);}));
              return result;};}"""
        )
        page.evaluate("() => {const pg=$('#p1');finishRect(pg,newBox(pg),.1,.1,.4,.15);}")
        page.wait_for_function("typeof window.releasePick==='function'&&COMPOSE.picking&&!!COMPOSE.box", timeout=8000)
        page.locator("#note").fill("Keep this note")
        page.evaluate("savePin()")
        page.wait_for_function("COMPOSE.pendingSave", timeout=8000)
        page.evaluate("async id=>{openEdit(id);await startRepick();}", pid)
        page.wait_for_function("REPICK&&!COMPOSE.picking&&!COMPOSE.pendingSave&&!COMPOSE.box", timeout=8000)
        self.assertTrue(page.locator("#composer").evaluate("node=>node.hidden"))
        self.assertTrue(page.locator("#c-spin").evaluate("node=>node.hidden"))
        self.assertEqual(page.locator("#note").input_value(), "Keep this note")
        page.evaluate("cancelRepick();window.releasePick()")
        page.wait_for_function("!REPICK&&!COMPOSE.picking&&!COMPOSE.pendingSave", timeout=8000)
        page.wait_for_function("DRAFT.timer===0&&!!sessionStorage.getItem(draftKey(META.label,'ms'))", timeout=8000)
        self.assertFalse(page.evaluate("OPEN_ALL.some(p=>p.note==='Keep this note')"))

    def test_dirty_editor_survives_round_trip_then_saves_and_cancels(self):
        """A dirty editor stays on its pin across A→B→A, then save and cancel retain their controls."""
        page = self.cold("#doc=ms", "desktop")
        page.wait_for_function("LIGHT_TIMER&&DOC==='ms'", timeout=8000)
        pid = page.evaluate("() => OPEN_ALL.find(p=>p.doc==='ms').id")
        page.evaluate("id=>openEdit(id)", pid)
        page.locator(".e-note").fill("Edited after round trip")
        for key in ("hl", "ms"):
            page.evaluate("async key=>await switchDoc(key)", key)
            page.wait_for_function("key=>DOC===key&&EDITOR.current&&EDITOR.current.id", arg=key, timeout=8000)
        self.assertEqual(page.locator(".e-note").input_value(), "Edited after round trip")
        page.evaluate("saveEdit()")
        page.wait_for_function("EDITOR.current===null&&!EDITOR.saving", timeout=8000)
        self.assertEqual(find_record(ps.APP.snapshot_pins(), pid)["note"], "Edited after round trip")
        page.evaluate("id=>openEdit(id)", pid)
        page.wait_for_function("EDITOR.current&&EDITOR.current.id", timeout=8000)
        page.evaluate("cancelEdit()")
        self.assertIsNone(page.evaluate("EDITOR.current"))

    def test_inflight_edit_save_closes_same_card_after_document_switch(self):
        """A save started on A closes its still-owned card on B after the server response is released."""
        page = self.cold("#doc=ms", "desktop")
        page.wait_for_function("LIGHT_TIMER&&DOC==='ms'", timeout=8000)
        pid = page.evaluate("() => OPEN_ALL.find(p=>p.doc==='ms').id")
        page.evaluate("id=>openEdit(id)", pid)
        page.locator(".e-note").fill("Saved during switch")
        page.evaluate(
            """() => {const realApi=api; api=(path,options) => {
              const result=realApi(path,options);
              if(path.endsWith('/edit')&&options?.method==='POST')
                return result.then(value=>new Promise(resolve=>{window.releaseEdit=()=>resolve(value);}));
              return result;};}"""
        )
        page.evaluate("() => {saveEdit();}")
        page.wait_for_function("typeof window.releaseEdit==='function'", timeout=8000)
        page.evaluate("async()=>await switchDoc('hl')")
        page.evaluate("window.releaseEdit()")
        page.wait_for_function("DOC==='hl'&&EDITOR.current===null&&!EDITOR.saving", timeout=8000)
        self.assertEqual(find_record(ps.APP.snapshot_pins(), pid)["note"], "Saved during switch")

    def test_service_worker_carries_the_restore_action_into_a_new_window(self):
        self.assertIn("e.action==='restore'?'&act=restore':''", SW_JS)


class PreviewEqualsServer(BrowserBase):
    """The real input pipeline: text + autocomplete state -> the outcome line -> the request body -> the server decision."""

    WHO = ALICE
    LEE = {"login": "sl@example.com", "name": "Robin Lee"}
    PARK = {"login": "sp@example.com", "name": "Robin Park"}

    def setUp(self):
        """Seed several review pins and known mention targets to compare browser outcome previews with server results."""
        super().setUp()
        for p in (A, self.LEE, self.PARK):
            ps.APP.people_directory.record(p)
        self.pins = []
        for i in range(5):
            pid = add_pin(
                {"file": str(self.main), "lo": 4 + 2 * i, "hi": 5 + 2 * i, "page": 1, "note": "검토 %d" % i}, A
            ).record["id"]
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
                CloseRequest(reply="고침 %d" % i),
            )
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
        r = find_record(ps.APP.snapshot_pins(), pid)
        last = r["thread"][-1]
        return (
            preview,
            not r.get("done"),
            [ps.APP.people_directory.known()[lg]["name"] for lg in last.get("mentions") or []],
        )

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
    """Guard keyboard submission, offline reply recovery, and reply override controls."""

    WHO = ALICE

    def setUp(self):
        """Prepare an attributed review pin for reply keyboard handling and failed-submit recovery."""
        super().setUp()
        ps.APP.people_directory.record(A)
        self.rv = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "식"}, A).record["id"]
        ps.APP.pin_lifecycle.close_pin(
            self.rv,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", self.rv),
            CloseRequest(reply="고침"),
        )

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
        self.assertEqual(pin_state(find_record(ps.APP.snapshot_pins(), self.rv)), "review")

    def test_offline_failure_reopens_the_box_with_the_draft_and_an_error(self):
        page = self.open(0)
        page.route("**/api/pins/*/reply", lambda r: r.abort())
        card = self.box(page)
        page.fill(card + " textarea.r-text", "오프라인에서 쓴 글")
        page.click(card + " [data-act=reply-send]")
        page.locator("#toasts .toast").first.locator("button.btn-icon").click()
        page.wait_for_selector(card + " .reply-box .r-err:not([hidden])", timeout=5000)
        self.assertEqual(page.input_value(card + " textarea.r-text"), "오프라인에서 쓴 글")
        self.assertEqual(pin_state(find_record(ps.APP.snapshot_pins(), self.rv)), "review")

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
    """Ensure a consumed restore deep link does not repeat its mutation after reload."""

    WHO = ALICE

    def test_reload_does_not_restore_again(self):
        """A consumed restore fragment is removed so reloading cannot undo a later independent deletion."""
        ps.APP.people_directory.record(A)
        pid = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "지운 핀"}, A).record["id"]
        keep = add_pin({"file": str(self.main), "lo": 12, "hi": 13, "page": 1, "note": "남은 핀"}, A).record["id"]
        ps.APP.pin_trash.drop_pin(pid, post_authority(ps.APP.pin_trash.context().store, B, "drop", pid))
        context = self.browser.new_context(viewport={"width": 1400, "height": 850})
        self.addCleanup(context.close)
        watch_idle(context)
        page = context.new_page()
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=ko#pin=%d&act=restore" % pid)
        page.wait_for_function("typeof OPEN_ALL!=='undefined'&&OPEN_ALL.some(p=>p.id===%d)" % pid, timeout=20000)
        self.assertNotIn("act=restore", page.evaluate("location.href"))
        ps.APP.pin_trash.drop_pin(
            pid, post_authority(ps.APP.pin_trash.context().store, A, "drop", pid)
        )  # dropped again elsewhere
        page.reload()
        # boot() ends by acting on a pin link (openPinFromLink); a second restore it sent would be answered by settle()
        page.wait_for_function(booted(1) + "&&OPEN_ALL.some(p=>p.id===%d)" % keep, timeout=20000)
        settle(page)
        self.assertIsNone(find_record(ps.APP.snapshot_pins(), pid))


class TrashOfAnotherDocument(ColdDeepLink):
    """Ensure opening a foreign document trash item preserves the current list filter."""

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
    test_draft_and_build_baseline_survive_document_round_trip = None
    test_dirty_editor_survives_round_trip_then_saves_and_cancels = None
    test_inflight_edit_save_closes_same_card_after_document_switch = None


# ---------------------------------------------------------------- pin-scoped [View changes] and the viewer's Trash controls (v0.3, issue #9)


class ScopedViewer(BrowserBase):
    """The viewer's [View changes] for a pin on desktop, fold and phone in Korean and English."""

    WHO = ALICE

    def setUp(self):
        """Build real multi-pin Git revisions and a controlled compiler to exercise scoped comparison navigation."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        ps.APP.people_directory.record(A)
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
        ps.APP.pin_lifecycle.close_pin(
            self.p1,
            post_authority(ps.APP.pin_lifecycle.context().store, loc, "close", self.p1),
            CloseRequest(
                reply="alpha",
                ref=self.fix[:8],
                changes=(lifecycle_input.CloseChange(str(self.main.resolve()), 4, 5).record(),),
            ),
        )
        ps.APP.pin_lifecycle.close_pin(
            self.p2,
            post_authority(ps.APP.pin_lifecycle.context().store, loc, "close", self.p2),
            CloseRequest(reply="beta", ref=self.fix[:8]),
        )
        ps.APP.pin_lifecycle.close_pin(
            self.p3,
            post_authority(ps.APP.pin_lifecycle.context().store, loc, "close", self.p3),
            CloseRequest(reply="gamma", ref=self.fix[:8]),
        )
        self.p4 = add_pin({"file": str(self.main), "lo": 8, "hi": 8, "page": 1, "note": "filler"}, A).record["id"]
        self.write(NEW.replace("Filler two.", "Filler two, reworded."))
        self.solo = self.commit("fix the filler pin")
        ps.APP.pin_lifecycle.close_pin(
            self.p4,
            post_authority(ps.APP.pin_lifecycle.context().store, loc, "close", self.p4),
            CloseRequest(reply="filler", ref=self.solo[:8]),
        )
        self.builds = []
        self.fail_scoped = False
        patcher = mock.patch.object(revision_execution, "revision_compile", side_effect=self.fake_compile)
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
            "REV.sourceCommit&&document.querySelectorAll('#revision-diff .rd-line').length>0", timeout=15000
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
        page.wait_for_function("REV.sourceCommit===%s" % json.dumps(self.solo), timeout=15000)
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
            "REV.sourceCommit===%s&&!document.getElementById('revision-other-toggle').hidden" % json.dumps(self.fix),
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
        """Prepare live and deleted pins with owner and viewer roles for trash visibility and action checks."""
        super().setUp()
        ps.APP.people_directory.record(A)
        ps.APP.C.people_file.write_text(
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
        ps.APP.pin_trash.drop_pin(self.gone, post_authority(ps.APP.pin_trash.context().store, A, "drop", self.gone))

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
    """Guard keyboard saving from question nudges and kind controls in the browser."""

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
        rows = records(ps.APP.snapshot_pins())
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
    """Check viewer role controls and notice text while editors retain write controls."""

    WHO = CAROL
    STATE_CHANGING = ("edit", "drop", "close", "reply-open", "rv-reopen", "confirm", "reopen", "restore", "unclaim")

    def setUp(self):
        """Seed editor/viewer identities plus open and review threads to verify role-specific browser controls."""
        super().setUp()
        ps.APP.people_directory.record(actor(ALICE))
        ps.APP.C.people_file.write_text(
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
        ps.APP.pin_lifecycle.reply_pin(
            pid, "답글", post_authority(ps.APP.pin_lifecycle.context().store, actor(ALICE), "reply", pid)
        )
        rid = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "검토할 핀"}, actor(ALICE)).record[
            "id"
        ]
        ps.APP.pin_lifecycle.close_pin(
            rid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", rid),
            CloseRequest(reply="고침"),
        )

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
                n = len(ps.APP.snapshot_pins())
                page.keyboard.press("Control+Enter")
                page.evaluate("savePin()")
                settle(page)
                self.assertEqual(len(ps.APP.snapshot_pins()), n)

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


# ---------------------------------------------------------------- figure documents (P1c)


# The documents whose /api/pick goes to the real server in FigureDocuments (the figure, the view-only PDF).
REAL_PICK_DOCS = (helpers_figure.FIG, "rv")


class FigureDocuments(BrowserBase):
    """A figure document (limn-figure-map/1) beside the manuscript and a view-only PDF, in the real viewer: the tab,
    the element a drag picks, the pin saved from it and its mark across re-renders. Page 1 of the figure is 3:1, so
    every flow runs on a very wide page. /api/pick on the figure goes to the real server (its map answers without
    SyncTeX); the manuscript keeps BrowserBase's computed answer."""

    WHO = ALICE
    # First-visit coach marks off, so no hint sits over the page a test drags on.
    NO_COACH = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1}}))}catch(e){}"

    def setUp(self):
        """The three documents of helpers_figure.viewer_docs (P1b's figure_doc among them), each with a finished
        two-page build."""
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(ps.APP.set_docs, None)

    def route(self, route):
        """Send the figure's and the view-only PDF's picks to the real server; route everything else as BrowserBase
        does."""
        rq = route.request
        if urlparse(rq.url).path == "/api/pick" and json.loads(rq.post_data or "{}").get("doc") in REAL_PICK_DOCS:
            return self.forward(route)
        return super().route(route)

    def open_fig(self, lang="ko", **device):
        """The viewer switched to the figure document and settled (open() boots on the manuscript, the first one)."""
        page = self.open(0, lang=lang, init=self.NO_COACH, **device)
        page.evaluate("async()=>await switchDoc('fig')")
        page.wait_for_function("DOC==='fig'&&document.querySelectorAll('#doc .pg').length===2", timeout=8000)
        settle(page)
        return page

    @staticmethod
    def text(page, sel):
        """The textContent of the first element sel matches, or None when there is none (no wait)."""
        return page.evaluate("s=>{const e=document.querySelector(s);return e?e.textContent:null;}", sel)

    def test_a_figure_tab_and_a_view_only_tab_hide_rebuild_and_the_manuscript_keeps_it(self):
        """Rebuild follows the document kind: the manuscript shows [PDF 재빌드]; the figure and the view-only PDF, which
        redraw when their files change, hide it - there and back again."""
        page = self.open(0, init=self.NO_COACH)
        for key, shown in (("ms", True), ("fig", False), ("rv", False), ("ms", True)):
            with self.subTest(doc=key):
                page.evaluate("async k=>await switchDoc(k)", key)
                page.wait_for_function("k=>DOC===k", arg=key, timeout=8000)
                settle(page)
                self.assertEqual(page.locator("#btn-rebuild").is_visible(), shown)
                self.assertEqual(page.evaluate("document.body.classList.contains('no-rebuild')"), not shown)

    def test_the_phone_documents_sheet_marks_the_figure_and_the_view_only_pdf(self):
        """On a phone the documents sheet shows '그림' ('Figure' in English) on the figure and 'PDF' on the view-only
        document, and nothing on the manuscript."""
        for lang, word in (("ko", "그림"), ("en", "Figure")):
            with self.subTest(lang=lang):
                page = self.open(0, lang=lang, init=self.NO_COACH, **DEVICES["phone"])
                page.evaluate("openDocsMenu()")
                page.wait_for_selector("#docs-menu[open] .dm-item", timeout=8000)
                marks = page.eval_on_selector_all(
                    "#docs-menu-list .dm-item",
                    "els=>els.map(e=>[e.dataset.doc,(e.querySelector('.dfig')||{}).textContent||'',"
                    "(e.querySelector('.dvo')||{}).textContent||''])",
                )
                self.assertEqual(marks, [["ms", "", ""], ["fig", word, ""], ["rv", "", "PDF"]])

    # Where element sel sits on page n, as page fractions of that page's box (inside its border), plus the box's size.
    BOX = """([sel, n]) => {const b=document.querySelector(sel), pg=document.getElementById('p'+n);
      if(!b||b.parentNode!==pg)return null;
      const r=b.getBoundingClientRect(), p=pg.getBoundingClientRect(), L=p.left+pg.clientLeft, T=p.top+pg.clientTop;
      return [(r.left-L)/pg.clientWidth,(r.top-T)/pg.clientHeight,r.width/pg.clientWidth,r.height/pg.clientHeight,
        pg.clientWidth,pg.clientHeight];}"""

    def assert_box(self, page, sel, n, frac):
        """Element sel sits on page n at frac [x, y, w, h], to within one CSS pixel of that page's box."""
        got = page.evaluate(self.BOX, [sel, n])
        self.assertIsNotNone(got, "%s is not on page %d" % (sel, n))
        pw, ph = got[4], got[5]
        for i, (g, want, size) in enumerate(zip(got[:4], frac, (pw, ph, pw, ph), strict=True)):
            self.assertAlmostEqual(g, want, delta=1.0 / size, msg="%s[%d] on a %dx%d page" % (sel, i, pw, ph))

    def drag(self, page, frac, n=1, ready="COMPOSE.current&&!COMPOSE.picking"):
        """A mouse drag across frac [x, y, w, h] of page n through the real pointer path, then wait for ready."""
        page.locator("#p%d" % n).scroll_into_view_if_needed()
        b = page.locator("#p%d" % n).bounding_box()
        x0, y0 = b["x"] + b["width"] * frac[0], b["y"] + b["height"] * frac[1]
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x0 + b["width"] * frac[2], y0 + b["height"] * frac[3], steps=5)
        page.mouse.up()
        page.wait_for_function(ready, timeout=8000)
        settle(page)

    @staticmethod
    def touch(cdp, kind, pts):
        """One CDP touch event (touchStart/touchMove/touchEnd) at the given viewport points."""
        cdp.send(
            "Input.dispatchTouchEvent",
            {"type": kind, "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)]},
        )

    @staticmethod
    def on_page(page, fx, fy, n=1):
        """The viewport point at fractions (fx, fy) of page n's box."""
        b = page.locator("#p%d" % n).bounding_box()
        return b["x"] + b["width"] * fx, b["y"] + b["height"] * fy

    def test_a_drag_on_the_july_cell_snaps_the_box_to_it_and_names_its_path_and_lines(self):
        """The map chose the cell: '새 핀' sits on the cell's box, the location line reads its path and code lines, and
        the ladder offers cell, strip and figure by name with the cell pressed."""
        page = self.open_fig()
        self.drag(page, helpers_figure.CELL_DRAG)
        self.assert_box(page, "#doc .sel", 1, helpers_figure.JULY)
        self.assertEqual(self.text(page, "#c-path"), "B2 › 달력 › 7월 ·")
        self.assertEqual(self.text(page, "#c-loc"), "B2_calendar.py L88-L95")
        self.assertEqual(
            page.eval_on_selector_all(
                "#c-levels button",
                "bs=>bs.map(b=>[b.dataset.level,b.firstChild.textContent.trim(),b.getAttribute('aria-pressed')])",
            ),
            [["el", "7월", "true"], ["el2", "달력", "false"], ["fig", "B2", "false"]],
        )

    def test_a_rung_moves_the_box_path_and_lines_without_asking_the_server(self):
        """Pressing strip, figure, then cell moves '새 핀', the path and the lines each time, and no pick is requested."""
        page = self.open_fig()
        self.drag(page, helpers_figure.CELL_DRAG)
        page.evaluate(
            """()=>{window.pickCalls=0; const f=window.fetch; window.fetch=function(u,o){
              if(String(u).startsWith('/api/pick'))window.pickCalls++; return f.call(this,u,o);};}"""
        )
        for level, box, path, loc in (
            ("el2", helpers_figure.STRIP_FRAC, "B2 › 달력 ·", "B2_calendar.py L80-L97"),
            ("fig", (0, 0, 1, 1), "B2 ·", "B2_calendar.py L12-L140"),
            ("el", helpers_figure.JULY, "B2 › 달력 › 7월 ·", "B2_calendar.py L88-L95"),
        ):
            with self.subTest(level=level):
                page.click('#c-levels [data-level="%s"]' % level)
                settle(page)
                self.assert_box(page, "#doc .sel", 1, box)
                self.assertEqual(self.text(page, "#c-path"), path)
                self.assertEqual(self.text(page, "#c-loc"), loc)
        self.assertEqual(page.evaluate("window.pickCalls"), 0)

    def test_the_snapped_box_stays_on_the_cell_at_fit_and_300_percent_at_dpr_1_and_2(self):
        """The box is placed in page fractions, so it stays on the cell at fit width and at three times that, on a 1x and
        a 2x screen."""
        for dpr in (1, 2):
            with self.subTest(dpr=dpr):
                page = self.open_fig(viewport={"width": 1400, "height": 850}, device_scale_factor=dpr)
                self.drag(page, helpers_figure.CELL_DRAG)
                self.assert_box(page, "#doc .sel", 1, helpers_figure.JULY)
                page.evaluate("zoomTo(fitWidth()*3)")
                settle(page)
                self.assertGreater(page.evaluate("document.getElementById('p1').clientWidth"), 2000)
                self.assert_box(page, "#doc .sel", 1, helpers_figure.JULY)

    def test_switching_documents_while_a_figure_pick_is_in_flight_leaves_nothing_behind(self):
        """The figure pick answers after the switch to the manuscript: no box, path line or composer appears there and
        the late answer is dropped."""
        page = self.open_fig()
        page.evaluate(
            """()=>{const real=api; window.heldPicks=[];
              api=(path,options)=>path==='/api/pick'?new Promise((ok,no)=>window.heldPicks.push(()=>real(path,options).then(ok,no)))
                :real(path,options);}"""
        )
        page.evaluate("(()=>{const pg=document.getElementById('p1');finishRect(pg,newBox(pg),0.48,0.2,0.52,0.28);})()")
        page.wait_for_function("window.heldPicks.length===1", timeout=8000)
        page.evaluate("async()=>await switchDoc('ms')")
        page.wait_for_function("DOC==='ms'", timeout=8000)
        page.evaluate("window.heldPicks[0]()")
        settle(page)
        self.assertEqual(
            page.evaluate(
                "[COMPOSE.current,COMPOSE.box,COMPOSE.picking,document.querySelectorAll('#doc .sel').length,"
                "document.getElementById('composer').hidden,document.getElementById('c-path').hidden]"
            ),
            [None, None, False, 0, True, True],
        )

    def test_a_select_mode_finger_drag_on_a_phone_snaps_like_a_mouse_drag(self):
        """[선택] on, one finger drags across the cell on a phone: the map chooses the cell and the box snaps to it."""
        page = self.open_fig(**DEVICES["phone"])
        page.evaluate("setSelMode(true)")
        x, y, w, h = helpers_figure.CELL_DRAG
        x0, y0 = self.on_page(page, x, y)
        x1, y1 = self.on_page(page, x + w, y + h)
        cdp = page.context.new_cdp_session(page)
        self.touch(cdp, "touchStart", [(x0, y0)])
        for i in range(1, 7):
            self.touch(cdp, "touchMove", [(x0 + (x1 - x0) * i / 6, y0 + (y1 - y0) * i / 6)])
        self.touch(cdp, "touchEnd", [])
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking", timeout=8000)
        settle(page)
        self.assertEqual(page.evaluate("COMPOSE.current.elSel&&COMPOSE.current.elSel.id"), helpers_figure.CELL_ID)
        self.assert_box(page, "#doc .sel", 1, helpers_figure.JULY)

    def test_a_long_press_on_a_phone_picks_the_cell_under_the_finger(self):
        """A long-press on the cell of a very wide figure picks the cell, not the strip a text-line box would reach, and
        the box snaps to it."""
        page = self.open_fig(**DEVICES["phone"])
        x, y, w, h = helpers_figure.JULY
        px, py = self.on_page(page, x + w / 2, y + h / 2)
        cdp = page.context.new_cdp_session(page)
        self.touch(cdp, "touchStart", [(px, py)])
        page.wait_for_function("LP===null&&LP_PICKED!==null", timeout=8000)
        self.touch(cdp, "touchEnd", [])
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking", timeout=8000)
        settle(page)
        self.assertEqual(page.evaluate("COMPOSE.current.elSel&&COMPOSE.current.elSel.id"), helpers_figure.CELL_ID)
        self.assert_box(page, "#doc .sel", 1, helpers_figure.JULY)

    def assert_frac(self, got, want):
        """A stored frac equal to want within float noise."""
        self.assertEqual(len(got), 4, got)
        for g, w in zip(got, want, strict=True):
            self.assertAlmostEqual(g, w, places=6)

    def saved_cell_pin(self, page, note) -> int:
        """Pick the July cell, write note, press [핀 저장], and return the new pin's id once the list shows it."""
        return self.saved_pin_at(page, helpers_figure.CELL_DRAG, note)

    def saved_pin_at(self, page, frac, note) -> int:
        """Drag across frac on page 1, write note, press [핀 저장], and return the new pin's id once the list shows it."""
        self.drag(page, frac)
        page.locator("#note").fill(note)
        page.click("#btn-save")
        page.wait_for_function("n=>OPEN_ALL.some(p=>p.note===n)", arg=note, timeout=8000)
        settle(page)
        return page.evaluate("n=>OPEN_ALL.find(p=>p.note===n).id", note)

    def test_saving_a_pick_stores_the_chosen_element_its_box_and_kind(self):
        """[핀 저장] on the cell stores the cell with its box as el, the cell's box as frac too, el:MonthCell and its
        lines; after pressing the strip rung, the strip with its box, kind and lines."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        rec = find_record(ps.APP.snapshot_pins(), pid)
        self.assertEqual(
            (rec["doc"], rec["scope"], rec["kind"], rec["via"], rec["lo"], rec["hi"]),
            ("fig", "el", "el:MonthCell", "map", 88, 95),
        )
        self.assertEqual(
            {k: v for k, v in rec["el"].items() if k != "frac"},
            {
                "id": helpers_figure.CELL_ID,
                "path": [helpers_figure.ROOT_ID, helpers_figure.STRIP_ID, helpers_figure.CELL_ID],
                "label": "7월",
                "part": "MonthCell",
                "impl": {"file": "lib/components.py", "lo": 410, "hi": 470},
            },
        )
        self.assert_frac(rec["el"]["frac"], helpers_figure.JULY)
        self.assert_frac(rec["frac"], helpers_figure.JULY)
        self.drag(page, helpers_figure.CELL_DRAG)
        page.click('#c-levels [data-level="el2"]')
        settle(page)
        page.locator("#note").fill("달력 줄 간격")
        page.click("#btn-save")
        page.wait_for_function("OPEN_ALL.some(p=>p.note==='달력 줄 간격')", timeout=8000)
        settle(page)
        strip = find_record(ps.APP.snapshot_pins(), page.evaluate("OPEN_ALL.find(p=>p.note==='달력 줄 간격').id"))
        self.assertEqual(
            (strip["scope"], strip["kind"], strip["lo"], strip["hi"], strip["el"]["id"]),
            ("el2", "el:CalendarStrip", 80, 97, helpers_figure.STRIP_ID),
        )
        self.assert_frac(strip["el"]["frac"], helpers_figure.STRIP_FRAC)
        self.assert_frac(strip["frac"], helpers_figure.STRIP_FRAC)

    def test_re_placing_a_cell_pin_on_the_strip_moves_its_element_box_and_lines(self):
        """[위치 다시 잡기] on the strip: '새 위치' snaps to the strip before [이 위치로 바꾸기], and the pin then stores
        the strip - its element, box, kind and lines."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        page.evaluate("id=>openEdit(id)", pid)
        page.wait_for_selector(".edit .b-repick", timeout=8000)
        page.click(".edit .b-repick")
        page.wait_for_function("REPICK!==null", timeout=8000)
        self.drag(page, helpers_figure.STRIP_DRAG, ready="REPICK&&REPICK.cand")
        self.assert_box(page, "#doc .sel", 1, helpers_figure.STRIP_FRAC)
        page.click('#banner [data-act="rp-apply"]')
        page.wait_for_function("REPICK===null", timeout=8000)
        settle(page)
        rec = find_record(ps.APP.snapshot_pins(), pid)
        self.assertEqual(
            (rec["lo"], rec["hi"], rec["kind"], rec["el"]["id"]), (80, 97, "el:CalendarStrip", helpers_figure.STRIP_ID)
        )
        self.assert_frac(rec["frac"], helpers_figure.STRIP_FRAC)

    def test_the_edit_card_keeps_a_figure_pins_element_and_kind_unless_its_lines_change(self):
        """The edit card's ladder is the snippet route's raw rung only (P1b): pressing '지금 범위' and saving sends
        nothing; nudging a line saves the new lines with kind 'lines', and the pin keeps its el (a range edit is no
        loc). No tooltip reads 'undefined'."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        for step in ("press the current range", "nudge one line down"):
            with self.subTest(step=step):
                page.evaluate("id=>openEdit(id)", pid)
                page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0", timeout=8000)
                settle(page)
                tips = page.eval_on_selector_all(".edit .e-levels button", "bs=>bs.map(b=>b.dataset.tip)")
                self.assertTrue(tips and all("undefined" not in t for t in tips), tips)
                if step == "press the current range":
                    page.click('.edit .e-levels [data-level="raw"]')
                else:
                    page.click('.edit [data-dir="down-grow"]')
                settle(page)
                page.click(".edit .b-esave")
                page.wait_for_function("EDITOR.current===null", timeout=8000)
                settle(page)
                rec = find_record(ps.APP.snapshot_pins(), pid)
                want = (
                    ("el", "el:MonthCell", 88, 95) if step == "press the current range" else ("lines", "lines", 88, 96)
                )
                self.assertEqual((rec["scope"], rec["kind"], rec["lo"], rec["hi"]), want)
                self.assertEqual(rec["el"]["id"], helpers_figure.CELL_ID)

    def rerender_and_refresh(self, page, **july) -> None:
        """The figure is rendered again into build BUILD2 (helpers_figure.viewer_rerender with july/july_page) and the
        viewer takes it the way its poll does (refreshDoc: pages, then pins)."""
        helpers_figure.viewer_rerender(self.fig, **july)
        page.evaluate("async()=>await refreshDoc()")
        page.wait_for_function("b=>META.pages_build===b", arg=helpers_figure.BUILD2, timeout=8000)
        settle(page)

    def test_a_saved_pins_mark_follows_its_element_after_a_re_render(self):
        """The mark starts on the cell; after a re-render moves the cell it is drawn at the cell's new box, solid (a
        placed element is no estimate)."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        mark = '.mark[data-pin="%d"]' % pid
        self.assert_box(page, mark, 1, helpers_figure.JULY)
        moved = (0.30, 0.18, 0.07, 0.12)  # clear of the August cell
        self.rerender_and_refresh(page, july=moved)
        self.assert_box(page, mark, 1, moved)
        self.assertEqual(page.evaluate("s=>[...document.querySelector(s).classList]", mark), ["mark"])

    def test_a_mark_whose_element_moved_to_page_2_is_drawn_and_counted_there(self):
        """The cell moves to page 2: its mark is drawn there, the card's page link says 2쪽, and [보기] brings the mark
        on screen."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        there = (0.30, 0.40, 0.10, 0.05)
        self.rerender_and_refresh(page, july=there, july_page=2)
        mark, card = '.mark[data-pin="%d"]' % pid, '.pin[data-id="%d"]' % pid
        self.assert_box(page, mark, 2, there)
        self.assertEqual(self.text(page, card + " .pg-link"), "2쪽")
        page.click(card + " .pg-link")
        settle(page)
        self.assertTrue(
            page.evaluate(
                """s=>{const m=document.querySelector(s).getBoundingClientRect(),l=document.getElementById('left').getBoundingClientRect();
                return m.top>=l.top&&m.bottom<=l.bottom;}""",
                mark,
            )
        )

    def test_a_lost_element_shows_element_lost_like_a_lost_line(self):
        """The re-render drops the cell: the card gets '요소 잃음', the lost dot and the warning border, the mark stays
        where the pin was placed in the warning colour, and one toast says so."""
        page = self.open_fig()
        pid = self.saved_cell_pin(page, "7월 칸 글자 키우기")
        self.rerender_and_refresh(page, july=None)
        card, mark = '.pin[data-id="%d"]' % pid, '.mark[data-pin="%d"]' % pid
        self.assertIn("요소 잃음", self.text(page, card + " .tags"))
        self.assertEqual(
            page.evaluate("s=>[...document.querySelector(s).classList]", card + " .st-dot"), ["st-dot", "lost"]
        )
        self.assertTrue(page.evaluate("s=>document.querySelector(s).classList.contains('st')", card))
        self.assertTrue(page.evaluate("s=>document.querySelector(s).classList.contains('st')", mark))
        self.assert_box(page, mark, 1, helpers_figure.JULY)
        self.assertEqual(page.locator("#toasts .toast").filter(has_text="#%d 요소를 잃었습니다" % pid).count(), 1)

    def test_a_region_pins_card_and_edit_card_name_the_page_its_element_is_on_now(self):
        """The August cell is drawn without code, so it is pinned as a region with its element. After a re-render takes
        the cell to page 2, the card's copy text and the edit card's location name page 2, not page 1 where it was
        pinned."""
        page = self.open_fig()
        pid = self.saved_pin_at(page, helpers_figure.AUGUST_DRAG, "8월 칸이 비어 있음")
        rec = find_record(ps.APP.snapshot_pins(), pid)
        self.assertEqual((rec["kind"], rec["page"], rec["el"]["id"]), ("region", 1, helpers_figure.AUGUST_ID))
        self.rerender_and_refresh(page, august_page=2)
        card = '.pin[data-id="%d"]' % pid
        self.assertTrue(page.evaluate("s=>document.querySelector(s+' .loc').dataset.copy", card).endswith(" 쪽 2"))
        page.evaluate("id=>openEdit(id)", pid)
        page.wait_for_selector(".edit .e-range", timeout=8000)
        self.assertEqual(self.text(page, ".edit .e-range"), "쪽 2 · 영역")
        self.assertTrue(page.evaluate("document.querySelector('.edit .e-range').dataset.copy").endswith(" 쪽 2"))

    def test_re_placing_a_view_only_region_pin_sends_only_the_region_and_keeps_its_shape(self):
        """On the reviewer's PDF a drag pins a region. [위치 다시 잡기] then [이 위치로 바꾸기] sends a loc with the page,
        the box, the quote and the build and nothing else (no lines, no element), and the pin stays a region at the
        new box."""
        page = self.open(0, init=self.NO_COACH)
        page.evaluate("async()=>await switchDoc('rv')")
        page.wait_for_function("DOC==='rv'&&document.querySelectorAll('#doc .pg').length===2", timeout=8000)
        settle(page)
        pid = self.saved_pin_at(page, (0.2, 0.2, 0.3, 0.1), "이 문단 다시 쓰기")
        before = find_record(ps.APP.snapshot_pins(), pid)
        self.assertEqual((before["doc"], before["kind"], before["page"]), ("rv", "region", 1))
        page.evaluate("id=>openEdit(id)", pid)
        page.wait_for_selector(".edit .b-repick", timeout=8000)
        page.click(".edit .b-repick")
        page.wait_for_function("REPICK!==null", timeout=8000)
        new = (0.5, 0.5, 0.3, 0.1)
        self.drag(page, new, ready="REPICK&&REPICK.cand")
        with page.expect_request(lambda r: r.url.endswith("/edit")) as sent:
            page.click('#banner [data-act="rp-apply"]')
        loc = json.loads(sent.value.post_data)["loc"]
        self.assertEqual(sorted(loc), ["frac", "page", "pdf_build", "quote"])
        page.wait_for_function("REPICK===null", timeout=8000)
        settle(page)
        after = find_record(ps.APP.snapshot_pins(), pid)
        self.assertEqual((after["doc"], after["kind"], after["page"]), ("rv", "region", 1))
        self.assertNotIn("el", after)
        self.assertGreater(after["rev"], before["rev"])
        self.assert_frac(after["frac"], [round(v, 6) for v in loc["frac"]])
        self.assertGreater(after["frac"][0], before["frac"][0] + 0.2)
