"""Reply draft round trips preserve chosen recipients without changing server lifecycle rules."""

from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.listing.projection import pin_state
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, find_record, ps
from helpers_access import ALICE, actor
from helpers_authority import post_authority
from helpers_browser import BrowserBase, settle


class ReplyDraftRecipients(BrowserBase):
    """The real browser, handler, pin file and notice file agree after a reply draft is reopened."""

    RECIPIENT = "robin.one@example.com"
    OTHER = "robin.two@example.com"

    def setUp(self):
        """Prepare two review pins and duplicate display names whose login choice must survive."""
        super().setUp()
        self.author = actor(ALICE)
        for login in (self.RECIPIENT, self.OTHER):
            ps.APP.people_directory.record({"login": login, "name": "Robin Lee"})
        self.pins = []
        for offset in (5, 9):
            pid = add_pin(
                {"file": str(self.main), "lo": offset, "hi": offset, "page": 1, "note": "Review request"},
                self.author,
            ).record["id"]
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
                CloseRequest(reply="Completed"),
            )
            self.pins.append(pid)

    def reply_box(self, page, pid):
        """Open a pin's visible reply control and return its card selector."""
        card = '#review-pins .pin[data-id="%d"]' % pid
        page.evaluate("id=>{OPEN_CARDS.add(id);drawPins();}", pid)
        page.locator(card + ' .acts [data-act="reply-open"]').click()
        return card

    def choose_recipient(self, page, card, login=None, text="@Robin Lee Please check"):
        """Choose one duplicate-name autocomplete entry and keep its displayed tag in the draft."""
        textarea = page.locator(card + " textarea.r-text")
        textarea.fill("@Rob")
        page.locator('#mention-pop [data-act="mention-pick"]').filter(has_text=login or self.RECIPIENT).click()
        textarea.fill(text)

    def send_and_assert(self, page, card, pid, text="@Robin Lee Please check", tagged=True, recipient=None):
        """Commit the deferred reply and check its stored recipients, state and exact notification target."""
        preview = page.locator(card + " .r-out-t").inner_text()
        cursor = ps.APP.notices.since(self.author, None)["ev_seq"]
        page.locator(card + ' [data-act="reply-send"]').click()
        page.locator(card + ' .nt-note [data-act="notice-x"]').click()
        settle(page)
        pin = find_record(ps.APP.snapshot_pins(), pid)
        self.assertEqual(pin["thread"][-1]["text"], text)
        expected = [recipient or self.RECIPIENT] if tagged else []
        self.assertEqual(pin["thread"][-1].get("mentions", []), expected)
        self.assertEqual(pin_state(pin), "review" if tagged else "open")
        notices = [event for event in ps.APP.notices.read()[0] if event["seq"] > cursor]
        if tagged:
            self.assertEqual([event["to"] for event in notices], [expected])
        else:
            self.assertEqual(notices, [])
        self.assertEqual(
            preview,
            "보내면 Robin Lee에게 알림이 가고 상태는 그대로입니다"
            if tagged
            else "보내면 이 핀이 다시 열려 에이전트에게 갑니다",
        )

    def hold_failed_reply(self, page, pid):
        """Hold the viewer API adapter's first aborted transport error until a newer draft can be entered."""
        path = "/api/pins/%d/reply" % pid
        page.route("**" + path, lambda route: route.abort(), times=1)
        page.evaluate(
            """path=>{const realApi=api;let held=false;api=(url,options)=>{
              const result=realApi(url,options);
              if(!held&&url===path&&options?.method==='POST'){
                held=true;return result.catch(error=>new Promise((_,reject)=>{
                  window.releaseReplyFailure=()=>reject(error);
                }));
              }
              return result;
            };}""",
            path,
        )

    def overlap_case(self, recovery, cached):
        """A stale recovery must leave the newer live or cached draft, focus and recipient intact before real sending."""
        page = self.open(0)
        pid, other_pid = self.pins
        card = self.reply_box(page, pid)
        self.choose_recipient(page, card, text="@Robin Lee OLD")
        page.locator(card + ' [data-act="reply-flip"]').click()
        before = find_record(ps.APP.snapshot_pins(), pid)
        if recovery == "failure":
            self.hold_failed_reply(page, pid)
        page.locator(card + ' [data-act="reply-send"]').click()
        if recovery == "failure":
            page.locator(card + ' .nt-note [data-act="notice-x"]').click()
            page.wait_for_function("typeof window.releaseReplyFailure==='function'")
        card = self.reply_box(page, pid)
        self.choose_recipient(page, card, login=self.OTHER, text="@Robin Lee NEW")
        if cached:
            page.locator(card + ' [data-act="reply-cancel"]').click()
            other_card = self.reply_box(page, other_pid)
            page.locator(other_card + " textarea.r-text").fill("Other pin remains active")
            focus_selector = other_card + " textarea.r-text"
        else:
            focus_selector = card + " textarea.r-text"
        page.locator(focus_selector).evaluate("node=>{node.focus();node.setSelectionRange(3,7);}")
        focus_before = page.locator(focus_selector).evaluate(
            "node=>({focused:document.activeElement===node,start:node.selectionStart,end:node.selectionEnd})"
        )
        if recovery == "failure":
            page.evaluate("window.releaseReplyFailure()")
        else:
            page.locator(card + ' .nt-note [data-act="notice-act"]').evaluate("node=>node.click()")
        settle(page)
        self.assertEqual(find_record(ps.APP.snapshot_pins(), pid), before)
        focus_after = page.evaluate(
            """selector=>{const node=document.querySelector(selector);return {
              focused:!!node&&document.activeElement===node,start:node?.selectionStart??null,end:node?.selectionEnd??null
            };}""",
            focus_selector,
        )
        if recovery == "failure":
            self.assertIn("보내지 못했습니다", page.locator("#status .st-tx").inner_text())
            self.assertIn("#%d" % pid, page.locator("#status .st-tx").inner_text())
            self.assertEqual(
                page.locator(focus_selector).locator("xpath=..").locator(".r-err:not([hidden])").count(), 0
            )
        if cached:
            page.evaluate("id=>openReply(id)", pid)
        flip_after = page.locator(card + ' [data-act="reply-flip"]').get_attribute("aria-checked")
        self.send_and_assert(page, card, pid, text="@Robin Lee NEW", recipient=self.OTHER)
        self.assertEqual(flip_after, "false")
        self.assertEqual(focus_after, focus_before)

    def test_old_undo_keeps_newer_live_recipient_override_and_cursor(self):
        """An old undo cannot overwrite or focus a newer same-pin reply addressed to a different duplicate-name login."""
        self.overlap_case("undo", cached=False)

    def test_old_failure_keeps_newer_live_recipient_override_and_cursor(self):
        """A late old-send failure leaves the newer reply coherent and sends it to its selected colleague."""
        self.overlap_case("failure", cached=False)

    def test_old_undo_keeps_newer_cached_reply_and_other_pin_focus(self):
        """An old undo cannot replace a retained newer same-pin draft or steal focus from another pin's draft."""
        self.overlap_case("undo", cached=True)

    def test_old_failure_keeps_newer_cached_reply_and_other_pin_focus(self):
        """A late old failure cannot replace a cached newer reply or change another active reply's cursor."""
        self.overlap_case("failure", cached=True)

    def test_cancel_reopen_keeps_duplicate_name_recipient_and_closed_state(self):
        """Cancelling retains the chosen duplicate-name login, which is still notified after reopening."""
        page = self.open(0)
        pid = self.pins[0]
        card = self.reply_box(page, pid)
        self.choose_recipient(page, card)
        page.locator(card + ' [data-act="reply-cancel"]').click()
        card = self.reply_box(page, pid)
        self.assertEqual(page.locator(card + " textarea.r-text").input_value(), "@Robin Lee Please check")
        self.send_and_assert(page, card, pid)

    def test_switching_pins_keeps_each_draft_and_duplicate_name_recipient(self):
        """Opening another reply retains the selected recipient and the other pin's ordinary draft separately."""
        page = self.open(0)
        first, second = self.pins
        card = self.reply_box(page, first)
        self.choose_recipient(page, card)
        other_card = self.reply_box(page, second)
        page.locator(other_card + " textarea.r-text").fill("Ordinary reply")
        card = self.reply_box(page, first)
        self.send_and_assert(page, card, first)
        other_card = self.reply_box(page, second)
        self.assertEqual(page.locator(other_card + " textarea.r-text").input_value(), "Ordinary reply")
        self.send_and_assert(page, other_card, second, "Ordinary reply", tagged=False)

    def test_undo_then_cancel_reopen_keeps_selected_recipient(self):
        """Undo restores an unsent recipient choice and a subsequent cancellation preserves it again."""
        page = self.open(0)
        pid = self.pins[0]
        card = self.reply_box(page, pid)
        self.choose_recipient(page, card)
        before = find_record(ps.APP.snapshot_pins(), pid)
        page.locator(card + ' [data-act="reply-flip"]').click()
        page.locator(card + ' [data-act="reply-send"]').click()
        page.locator(card + ' .nt-note [data-act="notice-act"]').click()
        settle(page)
        self.assertEqual(find_record(ps.APP.snapshot_pins(), pid), before)
        self.assertEqual(page.locator(card + ' [data-act="reply-flip"]').get_attribute("aria-checked"), "true")
        page.locator(card + ' [data-act="reply-cancel"]').click()
        card = self.reply_box(page, pid)
        self.assertEqual(page.locator(card + ' [data-act="reply-flip"]').get_attribute("aria-checked"), "false")
        self.send_and_assert(page, card, pid)

    def test_failed_send_then_cancel_reopen_keeps_selected_recipient(self):
        """An aborted HTTP send restores the draft without writing and cancellation still preserves its recipient."""
        page = self.open(0)
        pid = self.pins[0]
        card = self.reply_box(page, pid)
        self.choose_recipient(page, card)
        before = find_record(ps.APP.snapshot_pins(), pid)
        page.locator(card + ' [data-act="reply-flip"]').click()
        page.route("**/api/pins/*/reply", lambda route: route.abort())
        page.locator(card + ' [data-act="reply-send"]').click()
        page.locator(card + ' .nt-note [data-act="notice-x"]').click()
        page.wait_for_selector(card + " .r-err:not([hidden])")
        self.assertEqual(find_record(ps.APP.snapshot_pins(), pid), before)
        self.assertEqual(page.locator(card + ' [data-act="reply-flip"]').get_attribute("aria-checked"), "true")
        page.unroute("**/api/pins/*/reply")
        page.locator(card + ' [data-act="reply-cancel"]').click()
        card = self.reply_box(page, pid)
        self.send_and_assert(page, card, pid)

    def test_removing_tag_before_cancel_discards_its_recipient_hint(self):
        """A removed full-name tag cannot silently regain its old recipient when the ambiguous tag is typed again."""
        page = self.open(0)
        pid = self.pins[0]
        card = self.reply_box(page, pid)
        self.choose_recipient(page, card)
        page.locator(card + " textarea.r-text").fill("Ordinary reply")
        page.locator(card + ' [data-act="reply-cancel"]').click()
        card = self.reply_box(page, pid)
        page.locator(card + " textarea.r-text").fill("@Robin Lee Please check")
        self.send_and_assert(page, card, pid, tagged=False)
