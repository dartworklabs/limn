"""Editing service and HTTP behavior over real pin storage and explicit collaborators."""

from limn.pins import mentions
from limn.pins.editing import service as add_edit
from limn.pins.editing.rules import AddRequest, EditRequest, LinePlace, NoteTooLong, StaleEdit
from limn.pins.editing.values import NOTE_MAX
from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.mentions import NoteTags
from limn.pins.model import OpenPin, PinNotFound, parse_pin
from limn.pins.thread import pin_reopened_in_round
from limn.security.access import LOCAL_ACTOR
from limn.web.errors import InputRejected

from helpers import (
    Base,
    add_pin,
    edit_pin,
    ps,
    record_of,
)
from helpers_access import ALICE_ACTOR, BOB_ACTOR
from helpers_authority import post_authority
from helpers_pin_service import STAMP, ServiceBase


class AddAndEdit(ServiceBase):
    """add_pin and edit_pin around the editing feature rules."""

    def test_add_writes_the_pin_then_emits_its_notices(self):
        """A new pin is stored with the next id, where its file is and the current build; mention and assigned
        notices are emitted after the write, in one call."""
        tags = NoteTags(("bob@example.com",), ["bob@example.com"])
        self.ctx = self.context(note_tags=lambda *a: tags)
        place = LinePlace(
            {"file": str(self.tex), "name": "main.tex", "lo": 2, "hi": 3, "page": 1},
            frozenset({"file", "lo", "hi", "page"}),
        )
        pin = add_edit.add_pin(
            self.ctx,
            self.doc,
            AddRequest(place, "hi @Bob", assignee="bob@example.com"),
            post_authority(self.ctx.store, ALICE_ACTOR, "add", self.doc),
        )
        self.assertIsInstance(pin, OpenPin)
        stored = self.pin(1)
        self.assertEqual(
            (stored["at"], stored["file_rel"], stored["pdf_build"], stored["doc"], stored["mentions"]),
            (STAMP, "main.tex", "pages", "main", ["bob@example.com"]),
        )
        self.assertEqual(
            self.rec.emitted,
            [
                [
                    {"type": "mention", "pin": 1, "to": ["bob@example.com"]},
                    {"type": "assigned", "pin": 1, "to": ["bob@example.com"]},
                ]
            ],
        )
        self.assertEqual(self.add(), 2)

    def python_script(self):
        """A drawing script figs/a.py in the manuscript folder whose lines 2 and 4 are # comments -> its LinePlace
        builder: place(lo, hi) is the place of lines lo..hi."""
        script = self.ms / "figs" / "a.py"
        script.parent.mkdir()
        script.write_text("x = 0\n# July cell\ncell = month(7)\n# TODO bigger\n", encoding="utf-8")

        def place(lo: int, hi: int) -> LinePlace:
            """The place of lines lo..hi of the script."""
            return LinePlace(
                {"file": str(script), "name": "a.py", "lo": lo, "hi": hi, "page": 1},
                frozenset({"file", "lo", "hi", "page"}),
            )

        return place

    def test_a_pin_on_a_python_script_is_anchored_past_its_hash_comments(self):
        """add_pin on lines 2-4 of a .py script, which open and close on # comments, anchors on the code between
        them, with the offsets recorded."""
        place = self.python_script()
        pin = add_edit.add_pin(
            self.ctx,
            self.doc,
            AddRequest(place(2, 4), "n"),
            post_authority(self.ctx.store, ALICE_ACTOR, "add", self.doc),
        )
        self.assertEqual(
            self.pin(pin.record["id"])["anchor"],
            {"head": "cell = month(7)", "tail": "cell = month(7)", "head_off": 1, "tail_off": 1},
        )

    def test_an_edit_that_moves_a_python_pin_re_anchors_past_its_hash_comments(self):
        """edit_pin moving a .py pin to lines 1-2 (code, then a # comment) anchors on the code line alone."""
        place = self.python_script()
        pid = add_edit.add_pin(
            self.ctx,
            self.doc,
            AddRequest(place(3, 3), "n"),
            post_authority(self.ctx.store, ALICE_ACTOR, "add", self.doc),
        ).record["id"]
        out = add_edit.edit_pin(
            self.ctx, pid, EditRequest(base_rev=0, lo=1, hi=2), post_authority(self.ctx.store, ALICE_ACTOR, "edit", pid)
        )
        self.assertIsInstance(out, OpenPin)
        self.assertEqual(self.pin(pid)["anchor"], {"head": "x = 0", "tail": "x = 0", "head_off": 0, "tail_off": 1})

    def test_an_edit_refusal_writes_nothing_and_notifies_nobody(self):
        """A stale base_rev comes back as StaleEdit; pins.jsonl keeps its bytes and the emit gets no notice."""
        pid = self.add()
        before = self.pins_bytes()
        self.rec.emitted.clear()
        out = add_edit.edit_pin(
            self.ctx, pid, EditRequest(base_rev=5, note="new"), post_authority(self.ctx.store, BOB_ACTOR, "edit", pid)
        )
        self.assertIsInstance(out, StaleEdit)
        self.assertEqual(self.pins_bytes(), before)
        self.assertEqual(self.rec.emitted, [[]])

    def test_an_accepted_edit_is_written_in_place(self):
        """A note edit with the current base_rev rewrites the record, bumps rev and records who edited."""
        pid = self.add()
        out = add_edit.edit_pin(
            self.ctx, pid, EditRequest(base_rev=0, note="new"), post_authority(self.ctx.store, BOB_ACTOR, "edit", pid)
        )
        self.assertIsInstance(out, OpenPin)
        self.assertEqual(
            (self.pin(pid)["note"], self.pin(pid)["rev"], self.pin(pid)["edited_by"]["login"]),
            ("new", 1, "bob@example.com"),
        )

    def test_edit_of_a_missing_pin_is_a_named_miss(self):
        """No pin with the id: PinNotFound, nothing written."""
        self.assertEqual(
            add_edit.edit_pin(
                self.ctx, 9, EditRequest(base_rev=0, note="x"), post_authority(self.ctx.store, BOB_ACTOR, "edit", 9)
            ),
            PinNotFound(9),
        )
        self.assertEqual(self.pins_bytes(), b"")


class NoteAppend(Base):
    """An edit with note_append adds to the note in place (one line, undoable), needs no base_rev, and is refused
    without a change when it is empty or would take the note over NOTE_MAX."""

    def test_note_append_then_undo(self):
        pid = self.add(note="원본")
        p0 = self.pin(pid)
        p1 = record_of(edit_pin(pid, {"note_append": "추가 텍스트"}, dict(LOCAL_ACTOR)))
        self.assertIn("추가 텍스트", p1["note"])
        self.assertIn("(추가 ", p1["note"])
        self.assertEqual(len(ps.APP.C.pins_jsonl.read_text().splitlines()), 1)  # line count unchanged
        undone = record_of(edit_pin(pid, {"note": p0["note"], "base_rev": p1["rev"]}, dict(LOCAL_ACTOR)))
        self.assertEqual(undone["note"], p0["note"])

    def test_note_append_does_not_need_base_rev(self):
        pid = self.add()
        p = record_of(edit_pin(pid, {"note_append": "x"}, dict(LOCAL_ACTOR)))
        self.assertIn("x", p["note"])

    def test_note_append_empty_string_rejected(self):
        """An empty note_append is refused (note_append_empty) and changes nothing."""
        pid = self.add(note="원본")
        empty = InputRejected("덧붙일 메모가 비어 있습니다.", "note_append_empty")
        self.assertEqual(edit_pin(pid, {"note_append": ""}, dict(LOCAL_ACTOR)), empty)
        self.assertEqual(edit_pin(pid, {"note_append": "   "}, dict(LOCAL_ACTOR)), empty)  # whitespace only too
        self.assertEqual(self.pin(pid)["note"], "원본")  # unchanged since it was rejected

    def test_note_append_over_note_max_combined_is_rejected(self):
        pid = self.add(note="x" * (NOTE_MAX - 20))  # only 20 chars of headroom
        # under the per-field cap (2000), over it once combined
        refused = edit_pin(pid, {"note_append": "y" * 100}, dict(LOCAL_ACTOR))
        self.assertIsInstance(refused, NoteTooLong)
        self.assertEqual(refused.limit, NOTE_MAX)
        self.assertEqual(len(self.pin(pid)["note"]), NOTE_MAX - 20)  # unchanged length since it was rejected
        self.assertEqual(self.pin(pid)["rev"], 0)


class MentionsOnEdit(Base):
    """An edit notifies only newly tagged people, a self-tag is never stored or addressed, and a reopen after a confirm
    still marks the pin reopened."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    W = {"login": "wendy@example.com", "name": "Wendy Kim"}

    def setUp(self):
        super().setUp()

    def events(self):
        return ps.APP.notices.read()[0]

    def test_edit_adds_mention_event_only_for_new_names(self):
        ps.APP.people_directory.record(dict(self.W))
        ps.APP.people_directory.record(dict(self.S))
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "note": "@Wendy Kim 봐 주세요"}, dict(LOCAL_ACTOR)
        ).record["id"]
        edit_pin(pid, {"note": "@Wendy Kim @Bob Park 봐 주세요", "base_rev": 0}, dict(LOCAL_ACTOR))
        self.assertEqual(
            [(e["type"], e["to"]) for e in self.events()],
            [("mention", [self.W["login"]]), ("mention", [self.S["login"]])],
        )
        edit_pin(pid, {"note": "그냥 메모", "base_rev": 1}, dict(LOCAL_ACTOR))
        self.assertNotIn("mentions", self.pin(pid))

    def test_reopen_after_confirm_marks_reopened_symbol_not_just_first_round_msg(self):
        """A confirmation before reopening must not hide the reopened marker in the current thread round."""
        # observed bug: reopening after a confirm made the round start with [confirm, reopen, ...], so the
        # "reopened" marker was missing (the old check only looked at "is the round's first message a
        # reopen?"). pin_reopened_in_round() now skips over confirm.
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
            CloseRequest(reply="고침"),
        )
        ps.APP.pin_lifecycle.confirm_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "confirm", pid)
        )
        ps.APP.pin_lifecycle.reopen_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "reopen", pid),
            reason="다시 봐 주세요",
        )
        self.assertTrue(pin_reopened_in_round(parse_pin(self.pin(pid)).core.thread))
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % pid))
        self.assertIn("다시 열림", row)

    def test_self_mention_never_becomes_addressed(self):
        """Self-tags create no addressed recipient, while a reply still records tags of other people."""
        ps.APP.people_directory.record(dict(self.W))
        ps.APP.people_directory.record(dict(self.S))
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "note": "@Wendy Kim 셀프 태그", "kind_req": "question"},
            dict(self.W),
        ).record["id"]
        p = self.pin(pid)
        self.assertNotIn("mentions", p)  # a self-@mention isn't stored
        self.assertEqual(mentions.addressed_to(parse_pin(p)), [])
        msg = ps.APP.pin_lifecycle.reply_pin(
            pid,
            "@Bob Park 님 확인 부탁드립니다 @Wendy Kim",
            post_authority(ps.APP.pin_lifecycle.context().store, dict(self.W), "reply", pid),
        ).record["thread"][-1]
        self.assertEqual(msg["mentions"], [self.S["login"]])


class PinKindAndThread(Base):
    """Kind requests are validated, stored only when given, and remain editable on closed pins."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    def test_kind_req_stored_only_when_given_and_validated(self):
        """kind_req is stored only when given, and an unknown value is refused (bad_kind_req)."""
        q = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "구간의 정의는?", "kind_req": "question"},
            dict(self.S),
        ).record["id"]
        f = self.add()
        self.assertEqual(self.pin(q)["kind_req"], "question")
        self.assertNotIn("kind_req", self.pin(f))  # an old-style call (agent curl) has no field = fix request
        self.assertEqual(
            add_pin({"file": str(self.main), "lo": 4, "hi": 5, "kind_req": "ask"}, dict(self.S)),
            InputRejected("kind_req 는 fix|question 중 하나입니다.", "bad_kind_req"),
        )

    def test_edit_switches_kind_even_on_closed_pin(self):
        """Changing request kind remains valid after closing and preserves the requested fix/question value."""
        pid = self.add()
        p = record_of(edit_pin(pid, {"kind_req": "question", "base_rev": 0}, dict(self.S)))
        self.assertEqual(p["kind_req"], "question")
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "close", pid), CloseRequest()
        )
        p = record_of(edit_pin(pid, {"kind_req": "fix", "base_rev": self.pin(pid)["rev"]}, dict(self.S)))
        self.assertEqual(p["kind_req"], "fix")
