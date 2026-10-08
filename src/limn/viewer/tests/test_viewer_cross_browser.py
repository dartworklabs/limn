"""Critical pin writes through rendered controls in bundled desktop Firefox and WebKit.

These focused flows use the real server and pin store with BrowserBase's resolved-pick fixture. They verify note
persistence and concurrent append/undo behavior; desktop WebKit does not stand for testing a physical iOS device.
"""

import re

from helpers import add_pin, find_record, ps, records
from helpers_access import ALICE, actor
from helpers_browser import BrowserBase, settle


class PinSaveSmoke:
    """Share the same user-visible save contracts between Firefox and WebKit."""

    def seeded_pin(self):
        """Create one real open pin overlapping the fixture's resolved page selection."""
        return add_pin(
            {"file": str(self.main), "lo": 5, "hi": 5, "page": 1, "note": "Original note"}, actor(ALICE)
        ).record["id"]

    def stored_note(self, pid):
        """Read the persisted note independently of the browser's displayed pin list."""
        return find_record(ps.APP.snapshot_pins(), pid)["note"]

    def append_as_another_writer(self, page, pid, text):
        """Write through the real API without refreshing the tested form's displayed revision."""
        result = page.evaluate(
            """async ({id,text})=>await api('/api/pins/'+id+'/edit',{
              method:'POST',body:{note_append:text}})""",
            {"id": pid, "text": text},
        )
        self.assertEqual(result["status"], 200)

    def test_create_then_edit_persists_the_text_entered_in_the_controls(self):
        """A new note and its subsequent edit survive saving and render as literal text."""
        page = self.open(0, lang="en")
        self.open_composer(page)
        page.locator("#note").fill("Created <note> & review")
        page.locator("#btn-save").click()
        page.wait_for_selector("#composer", state="hidden", timeout=8000)
        settle(page)
        stored = records(ps.APP.snapshot_pins())
        self.assertEqual([p["note"] for p in stored], ["Created <note> & review"])
        pid = stored[0]["id"]
        card = page.locator('.pin[data-id="%d"]' % pid)
        self.assertEqual(card.locator(".note").inner_text(), "Created <note> & review")
        card.locator("button[data-act=edit]").click()
        card.locator(".e-note").fill("Edited <note> & review")
        card.locator("[data-act=esave]").click()
        page.wait_for_selector(".e-note", state="detached", timeout=8000)
        settle(page)
        self.assertEqual(self.stored_note(pid), "Edited <note> & review")
        self.assertEqual(card.locator(".note").inner_text(), "Edited <note> & review")

    def test_stale_append_can_retry_and_undo_without_losing_the_other_writers_note(self):
        """A stale append keeps the draft; retrying and undoing restore the latest verified note."""
        pid = self.seeded_pin()
        page = self.open(1)
        page.evaluate("clearInterval(LIGHT_TIMER)")
        self.open_composer(page)
        page.locator("#note").fill("My appended note")
        self.append_as_another_writer(page, pid, "Remote work")
        remote_note = self.stored_note(pid)
        page.locator("[data-act=overlap-append]").click()
        page.wait_for_function("!COMPOSE.saving", timeout=8000)
        settle(page)
        self.assertEqual(self.stored_note(pid), remote_note)
        self.assertEqual(page.locator("#note").input_value(), "My appended note")
        self.assertTrue(page.locator("#composer").is_visible())
        page.locator("[data-act=overlap-append]").click()
        page.wait_for_selector("#composer", state="hidden", timeout=8000)
        self.assertRegex(self.stored_note(pid), re.escape(remote_note) + r"\n\(추가 \d{2}:\d{2}\) My appended note\Z")
        page.locator("[data-act=notice-act]").filter(has_text="되돌리기").click()
        settle(page)
        self.assertEqual(self.stored_note(pid), remote_note)

    def test_undo_append_rejects_a_later_concurrent_note(self):
        """An undo cannot overwrite another writer's note added after the accepted append."""
        pid = self.seeded_pin()
        page = self.open(1)
        page.evaluate("clearInterval(LIGHT_TIMER)")
        self.open_composer(page)
        page.locator("#note").fill("My appended note")
        page.locator("[data-act=overlap-append]").click()
        page.wait_for_selector("#composer", state="hidden", timeout=8000)
        self.append_as_another_writer(page, pid, "Later remote work")
        latest_note = self.stored_note(pid)
        page.locator("[data-act=notice-act]").filter(has_text="되돌리기").click()
        settle(page)
        self.assertEqual(self.stored_note(pid), latest_note)
        self.assertIn("My appended note", latest_note)
        self.assertIn("Later remote work", latest_note)


class FirefoxPinSave(PinSaveSmoke, BrowserBase):
    """Run critical persisted pin-write flows in Playwright's bundled desktop Firefox."""

    BROWSER_ENGINE = "firefox"


class WebKitPinSave(PinSaveSmoke, BrowserBase):
    """Run the same contracts in desktop WebKit, without claiming physical iOS coverage."""

    BROWSER_ENGINE = "webkit"
