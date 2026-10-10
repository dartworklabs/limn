"""Save, edit, and append preserve later input and concurrent notes in the real viewer."""

from helpers import add_pin, find_record, ps
from helpers_access import ALICE, BOB, CAROL, actor
from helpers_browser import BrowserBase, settle


class SaveIntegrity(BrowserBase):
    """Hold completed real API responses to expose changes made while a form is saving."""

    WHO = ALICE

    def setUp(self):
        """Give each flow its own pin, manuscript, server state, and browser context."""
        super().setUp()
        self.pid = add_pin(
            {"file": str(self.main), "lo": 5, "hi": 5, "page": 1, "note": "Original note"}, actor(ALICE)
        ).record["id"]

    def hold_response(self, page, path):
        """Delay the viewer-owned API adapter's first POST result after the real server handles it."""
        page.evaluate(
            """path => {const realApi=api;let held=false;api=(url,options)=>{
              const result=realApi(url,options);
              if(!held&&url===path&&options?.method==='POST'){
                held=true;return result.then(value=>new Promise(resolve=>{
                  window.releaseSavedResponse=()=>resolve(value);
                }));
              }
              return result;
            };}""",
            path,
        )

    def wait_response(self, page):
        """Wait for an actual server result before changing the still-editable form."""
        page.wait_for_function("typeof window.releaseSavedResponse==='function'", timeout=8000)

    def release_response(self, page):
        """Let the submission finish and observe its complete UI and persisted effects."""
        page.evaluate("window.releaseSavedResponse()")
        page.wait_for_function("!COMPOSE.saving&&!EDITOR.saving", timeout=8000)
        settle(page)

    def stored_note(self):
        """Return the real persisted note, independently of the viewer's cached pin list."""
        return find_record(ps.APP.snapshot_pins(), self.pid)["note"]

    def test_create_keeps_note_typed_while_the_submission_is_pending(self):
        """A successful create saves its submitted note and retains later text as a reloadable draft."""
        page = self.open(1)
        self.open_composer(page)
        page.locator("#note").fill("Submitted note")
        self.hold_response(page, "/api/pin")
        page.evaluate("()=>{savePin();}")
        self.wait_response(page)
        page.locator("#note").fill("Submitted note with a later thought")
        self.release_response(page)
        self.assertEqual(page.locator("#note").input_value(), "Submitted note with a later thought")
        self.assertFalse(page.locator("#composer").evaluate("node=>node.hidden"))
        self.assertEqual(
            [p.record["note"] for p in ps.APP.snapshot_pins() if p.core.id != self.pid], ["Submitted note"]
        )
        page.reload()
        page.wait_for_function("DRAFT.ready&&LIGHT_TIMER", timeout=20000)
        self.assertEqual(page.locator("#note").input_value(), "Submitted note with a later thought")

    def test_create_keeps_a_kind_changed_while_the_submission_is_pending(self):
        """Changing the request kind while create is pending leaves that unsaved choice on screen."""
        page = self.open(1)
        self.open_composer(page)
        page.locator("#note").fill("Submitted note")
        self.hold_response(page, "/api/pin")
        page.evaluate("()=>{savePin();}")
        self.wait_response(page)
        page.locator('#c-kind [data-kind="question"]').click()
        self.release_response(page)
        self.assertFalse(page.locator("#composer").evaluate("node=>node.hidden"))
        self.assertEqual(page.evaluate("KIND_NEW"), "question")
        self.assertEqual(page.locator("#note").input_value(), "Submitted note")

    def test_create_without_later_edits_clears_the_saved_draft(self):
        """Unchanged submitted fields still close normally and cannot reappear on reload."""
        page = self.open(1)
        self.open_composer(page)
        page.locator("#note").fill("Only submitted note")
        self.hold_response(page, "/api/pin")
        page.evaluate("()=>{savePin();}")
        self.wait_response(page)
        self.release_response(page)
        self.assertTrue(page.locator("#composer").evaluate("node=>node.hidden"))
        self.assertEqual(page.locator("#note").input_value(), "")
        self.assertIsNone(page.evaluate("sessionStorage.getItem(draftKey(META.label,DOC))"))

    def test_edit_keeps_later_text_and_can_save_it_again(self):
        """A late edit response retains newer text and advances its baseline for the next save."""
        page = self.open(1)
        page.evaluate("id=>openEdit(id)", self.pid)
        page.locator(".e-note").fill("Submitted edit")
        self.hold_response(page, "/api/pins/%d/edit" % self.pid)
        page.evaluate("()=>{saveEdit();}")
        self.wait_response(page)
        page.locator(".e-note").fill("Submitted edit with a later thought")
        self.release_response(page)
        self.assertEqual(page.locator(".e-note").count(), 1)
        self.assertEqual(page.locator(".e-note").input_value(), "Submitted edit with a later thought")
        self.assertEqual(self.stored_note(), "Submitted edit")
        page.locator('[data-act="esave"]').click()
        page.wait_for_function("EDITOR.current===null&&!EDITOR.saving", timeout=8000)
        self.assertEqual(self.stored_note(), "Submitted edit with a later thought")

    def test_edit_keeps_a_kind_changed_while_the_submission_is_pending(self):
        """An in-flight note save cannot discard a later request-kind change on the same edit card."""
        page = self.open(1)
        page.evaluate("id=>openEdit(id)", self.pid)
        page.locator(".e-note").fill("Submitted edit")
        self.hold_response(page, "/api/pins/%d/edit" % self.pid)
        page.evaluate("()=>{saveEdit();}")
        self.wait_response(page)
        page.locator('.e-kind [data-kind="question"]').click()
        self.release_response(page)
        self.assertEqual(page.locator(".e-note").count(), 1)
        self.assertEqual(page.evaluate("EDITOR.current.kind_req"), "question")
        page.locator('[data-act="esave"]').click()
        page.wait_for_function("EDITOR.current===null&&!EDITOR.saving", timeout=8000)
        self.assertEqual(find_record(ps.APP.snapshot_pins(), self.pid)["kind_req"], "question")

    def test_closed_pin_refusal_keeps_later_note_for_an_explicit_note_only_retry(self):
        """A rival close refuses a range edit while retaining later text for a safe note-only save."""
        page = self.open(1)
        page.evaluate("clearInterval(LIGHT_TIMER)")
        page.evaluate("id=>openEdit(id)", self.pid)
        page.locator(".e-note").fill("Submitted range and note")
        page.evaluate("()=>{EDITOR.current.lo=4;EDITOR.current.scope=null;renderEdit();}")
        page.evaluate(
            "async id=>await api('/api/pins/'+id+'/close',{method:'POST',body:{reply:'Remote completion'}})",
            self.pid,
        )
        self.hold_response(page, "/api/pins/%d/edit" % self.pid)
        page.evaluate("()=>{saveEdit();}")
        self.wait_response(page)
        page.locator(".e-note").fill("Submitted range and note with a later thought")
        self.release_response(page)
        self.assertEqual(page.locator(".e-note").count(), 1)
        self.assertTrue(page.locator(".e-note").is_visible())
        self.assertEqual(page.locator(".e-note").input_value(), "Submitted range and note with a later thought")
        self.assertEqual(self.stored_note(), "Original note")
        page.locator('[data-act="esave"]').click()
        page.wait_for_function("EDITOR.current===null&&!EDITOR.saving", timeout=8000)
        pin = find_record(ps.APP.snapshot_pins(), self.pid)
        self.assertEqual(pin["note"], "Submitted range and note with a later thought")
        self.assertTrue(pin["done"])
        self.assertEqual((pin["lo"], pin["hi"]), (5, 5))

    def test_edit_resaves_later_mention_choice_when_the_note_text_is_unchanged(self):
        """An ambiguous autocomplete choice made during save remains dirty even when its visible text is identical. The
        second choice replaced the text that held the first tag, so its hint went with it (docs/handbook/viewer.md §담당:
        a hint belongs to its one '@name'): the saved hints are the second choice's alone."""
        for person in (BOB, CAROL):
            ps.APP.people_directory.record(actor({**person, "Tailscale-User-Name": "Shared Reviewer"}))
        page = self.open(1)
        page.evaluate("id=>openEdit(id)", self.pid)
        page.locator(".e-note").fill("@Shared")
        page.locator('#mention-pop [data-act="mention-pick"]').filter(has_text="bob@example.com").click()
        submitted = page.locator(".e-note").input_value()
        self.hold_response(page, "/api/pins/%d/edit" % self.pid)
        page.evaluate("()=>{saveEdit();}")
        self.wait_response(page)
        page.locator(".e-note").fill("@Shared")
        page.locator('#mention-pop [data-act="mention-pick"]').filter(has_text="carol@example.com").click()
        self.assertEqual(page.locator(".e-note").input_value(), submitted)
        self.release_response(page)
        self.assertEqual(page.locator(".e-note").count(), 1)
        self.assertEqual(find_record(ps.APP.snapshot_pins(), self.pid)["mentions"], ["bob@example.com"])
        page.locator('[data-act="esave"]').click()
        page.wait_for_function("EDITOR.current===null&&!EDITOR.saving", timeout=8000)
        pin = find_record(ps.APP.snapshot_pins(), self.pid)
        self.assertEqual(pin["note"], submitted)
        self.assertEqual(pin["mentions"], ["carol@example.com"])

    def test_opening_an_unchanged_alias_mention_does_not_write_a_new_revision(self):
        """Persisted recipients from a typed alias do not invent an unsaved autocomplete hint on opening."""
        ps.APP.people_directory.record(actor(BOB))
        page = self.open(1)
        page.evaluate(
            """async id=>{const pin=PINS.find(p=>p.id===id);
              await api('/api/pins/'+id+'/edit',{method:'POST',body:{base_rev:pin.rev,note:'Please check @bob'}});
              await loadPins();}""",
            self.pid,
        )
        before = find_record(ps.APP.snapshot_pins(), self.pid)
        self.assertEqual(before["mentions"], ["bob@example.com"])
        page.evaluate("id=>openEdit(id)", self.pid)
        page.locator('[data-act="esave"]').click()
        page.wait_for_function("EDITOR.current===null&&!EDITOR.saving", timeout=8000)
        self.assertEqual(find_record(ps.APP.snapshot_pins(), self.pid)["rev"], before["rev"])

    def test_stale_append_preserves_remote_work_and_allows_a_safe_retry_and_undo(self):
        """An append based on an old displayed revision rejects without writing or clearing the draft."""
        page = self.open(1)
        self.open_composer(page)
        page.locator("#note").fill("My appended note")
        page.evaluate("clearInterval(LIGHT_TIMER)")
        page.evaluate(
            "async id=>await api('/api/pins/'+id+'/edit',{method:'POST',body:{note_append:'Remote work'}})",
            self.pid,
        )
        remote_note = self.stored_note()
        page.evaluate("async id=>await appendToPin(id,'My appended note')", self.pid)
        settle(page)
        self.assertEqual(self.stored_note(), remote_note)
        self.assertEqual(page.locator("#note").input_value(), "My appended note")
        self.assertFalse(page.locator("#composer").evaluate("node=>node.hidden"))
        page.evaluate("async id=>await appendToPin(id,'My appended note')", self.pid)
        self.assertIn("My appended note", self.stored_note())
        page.locator('[data-act="notice-act"]').filter(has_text="되돌리기").click()
        settle(page)
        self.assertEqual(self.stored_note(), remote_note)

    def test_append_keeps_note_typed_while_the_submission_is_pending(self):
        """A successful append retains later composer text without appending it implicitly."""
        page = self.open(1)
        self.open_composer(page)
        page.locator("#note").fill("Submitted append")
        self.hold_response(page, "/api/pins/%d/edit" % self.pid)
        page.evaluate("id=>{appendToPin(id,'Submitted append');}", self.pid)
        self.wait_response(page)
        page.locator("#note").fill("Submitted append with a later thought")
        self.release_response(page)
        self.assertEqual(page.locator("#note").input_value(), "Submitted append with a later thought")
        self.assertFalse(page.locator("#composer").evaluate("node=>node.hidden"))
        self.assertTrue(self.stored_note().endswith("Submitted append"))

    def test_repeated_append_and_create_submit_only_one_append(self):
        """Rapid append clicks and a create shortcut share one submission and cannot duplicate content."""
        page = self.open(1)
        self.open_composer(page)
        page.locator("#note").fill("Append once")
        self.hold_response(page, "/api/pins/%d/edit" % self.pid)
        page.locator('[data-act="overlap-append"]').click()
        self.wait_response(page)
        page.locator('[data-act="overlap-append"]').evaluate("node=>node.click()")
        page.evaluate("()=>{savePin();}")
        self.release_response(page)
        self.assertEqual(self.stored_note().count("Append once"), 1)
        self.assertEqual(len(ps.APP.snapshot_pins()), 1)
