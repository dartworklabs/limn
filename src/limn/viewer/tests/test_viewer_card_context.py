"""Native cards keep one readable assignee below the request across layouts and permissions."""

import json
import os

from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, find_record, ps
from helpers_access import ALICE, BOB, CAROL, actor
from helpers_authority import post_authority
from helpers_browser import BrowserBase, settle

PHONE = {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True}
TABLET = {"viewport": {"width": 842, "height": 758}, "is_mobile": True, "has_touch": True}
DESKTOP = {"viewport": {"width": 1400, "height": 850}}


class CardContextBrowser(BrowserBase):
    """Exercise native assembled cards against real pin storage and server permissions."""

    WHO = ALICE

    def setUp(self):
        """Give each test its own manuscript, participants, stored pins, and browser contexts."""
        super().setUp()
        self.next_line = 4
        for person in (ALICE, BOB, CAROL):
            ps.APP.people_directory.record(actor(person))

    def seed_pin(self, assignee="agent", kind="fix", author=ALICE):
        """Create a real pin with a distinct source range and return its assigned identifier."""
        line = self.next_line
        self.next_line += 3
        return add_pin(
            {
                "file": str(self.main),
                "lo": line,
                "hi": line + 1,
                "page": 1,
                "note": "First request line\nSecond request line",
                "kind_req": kind,
                "assignee": assignee,
            },
            actor(author),
        ).record["id"]

    def show_cards(self, n_open, device=DESKTOP, theme="light"):
        """Open the native list and its panel, waiting for requests, layout, and fonts to settle."""
        page = self.open(
            n_open,
            init="localStorage.setItem('pinPrefs', JSON.stringify({theme:%s}));" % json.dumps(theme),
            **device,
        )
        page.evaluate("setSide(true)")
        settle(page)
        return page

    def card(self, page, pid):
        """Select one rendered card by its persisted identifier, excluding overlay copies."""
        return page.locator('#right .pin[data-id="%d"]' % pid)

    def test_compact_card_keeps_one_assignee_after_preview_and_expanded_note(self):
        """Folding preserves readable kind, recipient, and state; unfolding keeps meaningful badges."""
        pid = self.seed_pin(BOB["Tailscale-User-Login"], "question")
        ps.APP.pin_lifecycle.reply_pin(
            pid, "One reply", post_authority(ps.APP.pin_lifecycle.context().store, actor(ALICE), "reply", pid)
        )
        for device in (PHONE, TABLET):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.show_cards(1, device)
                card = self.card(page, pid)
                self.assertEqual(card.locator(".card-meta").count(), 1)
                row = card.locator(".card-meta")
                self.assertTrue(row.is_visible())
                self.assertEqual(" ".join(row.inner_text().split()), "질문 · 담당 Bob Park · 열림")
                self.assertEqual(card.locator(".head .as-chip").count(), 0)
                self.assertEqual(card.locator(".as-chip").count(), 1)
                self.assertEqual(card.locator(".head .th-n").inner_text(), "1")
                self.assertEqual(card.locator(".head .au").count(), 1)
                self.assertFalse(card.locator(".badge-question").is_visible())
                self.assertGreaterEqual(row.bounding_box()["y"], card.locator(".sum").bounding_box()["y"])

                card.locator(".b-fold").click()
                settle(page)
                self.assertTrue(card.locator(".badge-question").is_visible())
                self.assertEqual(" ".join(row.inner_text().split()), "담당 Bob Park · 열림")
                self.assertEqual(card.locator(".as-chip").count(), 1)
                note = card.locator(".note").bounding_box()
                self.assertGreaterEqual(row.bounding_box()["y"], note["y"] + note["height"])

    def test_metadata_is_plain_regular_12px_with_a_shared_text_baseline(self):
        """Recipient and context share regular 12px ink without the old colored pill in either theme."""
        pid = self.seed_pin(BOB["Tailscale-User-Login"])
        for device, theme in ((DESKTOP, "light"), (DESKTOP, "dark"), (TABLET, "light"), (PHONE, "light")):
            with self.subTest(width=device["viewport"]["width"], theme=theme):
                page = self.show_cards(1, device, theme)
                card = self.card(page, pid)
                self.assertEqual(card.locator(".card-meta").count(), 1)
                ink = card.locator(".card-meta").evaluate(
                    """row => {
                      const texts=[], walker=document.createTreeWalker(row,NodeFilter.SHOW_TEXT);
                      let node;
                      while ((node=walker.nextNode())) {
                        if (!node.textContent.trim()) continue;
                        const range=document.createRange(); range.selectNodeContents(node);
                        const rect=range.getBoundingClientRect();
                        if (!rect.width || !rect.height) continue;
                        const style=getComputedStyle(node.parentElement);
                        texts.push({text:node.textContent.trim(), bottom:rect.bottom,
                          size:style.fontSize, weight:style.fontWeight});
                      }
                      const recipient=row.querySelector('.as-chip'), style=getComputedStyle(recipient);
                      return {texts, background:style.backgroundColor, border:style.borderTopWidth,
                        shadow:style.boxShadow};
                    }"""
                )
                self.assertGreaterEqual(len(ink["texts"]), 3, ink)
                self.assertEqual({item["size"] for item in ink["texts"]}, {"12px"})
                self.assertEqual({item["weight"] for item in ink["texts"]}, {"400"})
                bottoms = [item["bottom"] for item in ink["texts"]]
                self.assertLessEqual(max(bottoms) - min(bottoms), 1, ink)
                self.assertEqual(ink["background"], "rgba(0, 0, 0, 0)")
                self.assertEqual(ink["border"], "0px")
                self.assertEqual(ink["shadow"], "none")

    def test_own_human_assignee_opens_native_editor_and_saves_assignment(self):
        """Moving the human recipient preserves the author's native edit and persisted assignment flow."""
        pid = self.seed_pin(BOB["Tailscale-User-Login"])
        page = self.show_cards(1, PHONE)
        card = self.card(page, pid)
        self.assertEqual(card.locator(".card-meta").count(), 1)
        recipient = card.locator(".card-meta button.as-chip")
        self.assertTrue(recipient.is_visible())
        recipient.click()
        settle(page)
        self.assertEqual(card.locator(".e-note").input_value(), "First request line\nSecond request line")
        self.assertEqual(card.locator(".card-meta").count(), 1)
        self.assertTrue(card.locator(".card-meta").is_visible())
        self.assertEqual(card.locator(".head .as-chip").count(), 0)
        self.assertEqual(card.locator('.e-assign [data-v="bob@example.com"]').get_attribute("aria-checked"), "true")
        card.locator('.e-assign [data-v="agent"]').click()
        card.locator('[data-act="esave"]').click()
        settle(page)
        self.assertEqual(card.locator(".e-note").count(), 0)
        self.assertIn("담당 에이전트", card.locator(".card-meta").inner_text())
        self.assertEqual(find_record(ps.APP.snapshot_pins(), pid)["assignee"], "agent")

    def test_coarse_recipient_target_has_44px_hit_clear_of_note_and_actions(self):
        """The relocated recipient receives its 44px touch box without neighboring note or action targets taking it."""
        pid = self.seed_pin(BOB["Tailscale-User-Login"])
        for device in (PHONE, TABLET):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.show_cards(1, device)
                card = self.card(page, pid)
                for expanded in (False, True):
                    with self.subTest(expanded=expanded):
                        if expanded:
                            card.locator(".b-fold").click()
                        card.scroll_into_view_if_needed()
                        settle(page)
                        self.assertEqual(card.locator(".card-meta button.as-chip").count(), 1)
                        misses = card.locator(".card-meta button.as-chip").evaluate(
                            """button => {
                              const rect=button.getBoundingClientRect(), misses=[];
                              const x=rect.x+rect.width/2, y=rect.y+rect.height/2;
                              for (const dx of [-21,0,21]) for (const dy of [-21,0,21]) {
                                const hit=document.elementFromPoint(x+dx,y+dy);
                                if (!hit || !button.contains(hit)) misses.push({dx,dy,
                                  hit:hit && hit.outerHTML.slice(0,180)});
                              }
                              return misses;
                            }"""
                        )
                        self.assertEqual(misses, [])

    def test_other_author_review_and_agent_recipients_have_no_edit_button(self):
        """Read-only recipients stay visible while expanded question, claim, and review badges retain meaning."""
        other = self.seed_pin(BOB["Tailscale-User-Login"], author=BOB)
        review = self.seed_pin(BOB["Tailscale-User-Login"], "question")
        claimed = self.seed_pin("agent", "question")
        lost = self.seed_pin("agent")
        reopened = self.seed_pin("agent")
        ps.APP.pin_lifecycle.close_pin(
            review,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", review),
            CloseRequest(reply="Ready for review"),
        )
        ps.APP.pin_claims.claim_pin(
            claimed, post_authority(ps.APP.pin_claims.context().store, dict(LOCAL_ACTOR), "claim", claimed), 30
        )
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.close_pin(
            reopened, post_authority(store, dict(LOCAL_ACTOR), "close", reopened), CloseRequest(reply="Ready")
        )
        ps.APP.pin_lifecycle.reopen_pin(reopened, post_authority(store, actor(ALICE), "reopen", reopened))
        before = self.main.stat()
        lines = self.main.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[12:14] = ["Removed first anchor.\n", "Removed last anchor.\n"]
        self.main.write_text("".join(lines), encoding="utf-8")
        os.utime(self.main, (before.st_atime, before.st_mtime + 1))
        page = self.show_cards(4, PHONE)
        page.evaluate("toggleSec('review', true)")
        settle(page)
        for pid, state in (
            (other, "열림"),
            (review, "검토 대기"),
            (claimed, "처리 중"),
            (lost, "위치 잃음"),
            (reopened, "열림"),
        ):
            with self.subTest(pid=pid):
                card = self.card(page, pid)
                self.assertEqual(card.locator(".card-meta").count(), 1)
                row = card.locator(".card-meta")
                self.assertTrue(row.is_visible())
                self.assertIn(state, row.inner_text())
                self.assertEqual(row.locator("button,[role=button],[data-act=edit]").count(), 0)
                card.locator(".b-fold").click()
                settle(page)
                self.assertTrue(row.is_visible())
                if pid == review:
                    self.assertTrue(card.locator(".badge-review").is_visible())
                    self.assertTrue(card.locator(".badge-question").is_visible())
                    self.assertNotIn("검토 대기", row.inner_text())
                    self.assertNotIn("질문", row.inner_text())
                if pid == claimed:
                    self.assertTrue(card.locator(".badge-claimed").is_visible())
                    self.assertTrue(card.locator(".badge-question").is_visible())
                    self.assertNotIn("처리 중", row.inner_text())
                    self.assertNotIn("질문", row.inner_text())
                    self.assertIn("담당 에이전트", row.inner_text())
                if pid == lost:
                    self.assertTrue(card.locator(".badge-warning").filter(has_text="위치 잃음").is_visible())
                    self.assertNotIn("위치 잃음", row.inner_text())
                if pid == reopened:
                    self.assertTrue(card.locator(".badge-reopen").is_visible())
                    self.assertNotIn("열림", row.inner_text())

    def test_viewer_owns_pin_but_sees_plain_recipient_without_edit_authority(self):
        """A viewer can read their own recipient without a hidden edit button erasing the label."""
        pid = self.seed_pin(BOB["Tailscale-User-Login"])
        ps.APP.C.people_file.write_text(
            json.dumps({"version": 1, "people": [dict(actor(ALICE), role="viewer"), actor(BOB), actor(CAROL)]}),
            encoding="utf-8",
        )
        page = self.show_cards(1)
        card = self.card(page, pid)
        self.assertEqual(card.locator(".card-meta").count(), 1)
        row = card.locator(".card-meta")
        self.assertTrue(row.is_visible())
        self.assertIn("담당 Bob Park", " ".join(row.inner_text().split()))
        self.assertEqual(row.locator("button,[role=button],[data-act=edit]").count(), 0)

    def test_long_untrusted_name_stays_text_and_separate_from_author_and_reply_count(self):
        """Untrusted recipient names neither execute markup nor crowd the author's independent header."""
        name = '<img src=x onerror="window.nameAttack=true"> & ' + "LongRecipient" * 16
        ps.APP.C.people_file.write_text(
            json.dumps(
                {"version": 1, "people": [actor(ALICE), {"login": "bob@example.com", "name": name}, actor(CAROL)]}
            ),
            encoding="utf-8",
        )
        pid = self.seed_pin(BOB["Tailscale-User-Login"])
        ps.APP.pin_lifecycle.reply_pin(
            pid, "One reply", post_authority(ps.APP.pin_lifecycle.context().store, actor(ALICE), "reply", pid)
        )
        page = self.show_cards(1)
        card = self.card(page, pid)
        self.assertEqual(card.locator(".card-meta").count(), 1)
        recipient = card.locator(".card-meta .as-n")
        self.assertEqual(recipient.text_content(), name)
        self.assertEqual(recipient.get_attribute("translate"), "no")
        self.assertEqual(card.locator(".card-meta img, .card-meta script").count(), 0)
        self.assertFalse(page.evaluate("Boolean(window.nameAttack)"))
        self.assertIn("Alice Kim", card.locator(".head .au").inner_text())
        self.assertEqual(card.locator(".head .th-n").inner_text(), "1")
        bounds = card.bounding_box()
        recipient_bounds = recipient.bounding_box()
        self.assertLessEqual(recipient_bounds["x"] + recipient_bounds["width"], bounds["x"] + bounds["width"])
