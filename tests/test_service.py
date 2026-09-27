"""limn.service - the pin service shells, driven directly with a real PinStore over a temp folder and recording sinks.

The rules themselves are pinned in test_pins_lifecycle.py and test_pins_edit.py, and the HTTP flows in
test_server.py and the feature files (test_reply.py, test_trash.py, test_notifications.py). The pin actions also run
through server.py's pin context at the end of this file: claims (Claim, ClaimEstimate), closing (CloseReplyRef,
CloseIdempotent, and CloseChanges - the optional `changes` of v0.3, issue #9), note_append, kinds and threads,
review and @-tags on edit. This file pins what the shells add around the rules: they write only when the rule
accepts, notices are emitted only after the write and never for a refusal, the audit line is appended
outside the pin lock, an agent's confirm never touches the store, and the package's import boundary.

Run: uv run pytest -q tests/test_service.py
"""

import ast
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from limn import mentions, service
from limn.access import LOCAL_ACTOR
from limn.locate import PinLocation
from limn.mentions import NoteTags
from limn.pins.edit import NOTE_MAX, AddRequest, EditRequest, LinePlace, NoteTooLong, StaleEdit
from limn.pins.lifecycle import (
    CLAIM_FIELDS,
    AgentCannotConfirm,
    AlreadyClosed,
    AlreadyLive,
    ClaimClosedPin,
    ClaimedByOther,
    CloseRequest,
    NotClaimed,
    NotInTrash,
    ThreadFull,
    pin_reopened_in_round,
)
from limn.pins.model import Agent, DonePin, OpenPin, Person, PinNotFound, ReviewPin, TrashedPin, parse_pin
from limn.pins.record import Broken
from limn.pins.view import pin_state
from limn.service import add_edit, claim, transitions, trash
from limn.service.context import LoadedPin, PinContext, is_agent, load_pin, typed_actor, who
from limn.store import PinFiles, PinStore, find_pin
from limn.web import parse
from limn.web.errors import InputRejected

from helpers import (
    Base,
    add_pin,
    edit_pin,
    find_record,
    fits,
    ps,
    record_of,
    records,
    req,
    split_resp,
    trash_records,
    write_records,
)
from helpers_access import ALICE_ACTOR, BOB_ACTOR, AccessBase

SERVICE_DIR = Path(service.__file__).parent
T = 1790000000.0
STAMP = "2026-09-26 10:00:00"
AGENT = dict(LOCAL_ACTOR)


def valid(r: object) -> bool:
    """The test's record check: a JSON object with an integer id."""
    return isinstance(r, dict) and isinstance(r.get("id"), int) and not isinstance(r.get("id"), bool)


def parse_rec(r: object):
    """The test's record parse: a record valid() lets through, parsed into its state; anything else Broken."""
    return parse_pin(r) if valid(r) else Broken()


def parse_trash(r: object):
    """The test's Trash parse: a record valid() lets through, parsed into its Trash copy; anything else Broken."""
    return TrashedPin.from_record(r) if valid(r) else Broken()


class Recorder:
    """Recording notice and audit sinks: what was made and emitted, and whether the pin lock was free at each audit."""

    def __init__(self, lock):
        """Remember the lock whose state the audit sink reports."""
        self.lock = lock
        self.emitted = []
        self.audits = []

    def make_event(self, typ, r, actor, to, msg=None, text=None):
        """A notice as (type, pin id, recipients without the actor), None when nobody is left - like events.make_event."""
        rcpt = [lg for lg in to or [] if lg and lg != actor.get("login") and lg != "local"]
        return {"type": typ, "pin": r.get("id"), "to": rcpt} if rcpt else None

    def emit(self, evs):
        """Record one emit call: the list as passed, Nones included."""
        self.emitted.append(list(evs))

    def audit(self, action, by, details):
        """Record the audit line and whether another thread could take the pin lock (it must be released)."""
        free = []
        t = threading.Thread(target=lambda: free.append(self.lock.acquire(blocking=False) and not self.lock.release()))
        t.start()
        t.join()
        self.audits.append((action, by["login"], details, free == [True]))
        return True


class ServiceBase(unittest.TestCase):
    """A context over a fresh temp state folder: a real PinStore, a frozen clock and recording sinks."""

    def setUp(self):
        """Make the store, the recorder, a manuscript file and the default context (thread_max 3, trash_days 30)."""
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ms = root / "ms"
        self.ms.mkdir()
        self.tex = self.ms / "main.tex"
        self.tex.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
        self.state = root / "state"
        self.state.mkdir()
        self.lock = threading.RLock()
        self.store = PinStore(
            PinFiles(self.state), self.lock, parse_rec, parse_trash, lambda pins: False, lambda pins: "md\n"
        )
        self.rec = Recorder(self.lock)
        self.people = {"alice@example.com": ALICE_ACTOR, "bob@example.com": BOB_ACTOR}
        self.checked = [0.0]
        self.ctx = self.context()
        self.doc = SimpleNamespace(key="main", dir=self.state)

    def tearDown(self):
        """Remove the temp folder."""
        self.tmp.cleanup()

    def context(self, **over):
        """A PinContext over this test's store and recorder; keyword arguments replace single collaborators."""
        fields = dict(
            store=self.store,
            now=lambda: STAMP,
            epoch=lambda: T,
            hm=lambda: "10:00",
            make_event=self.rec.make_event,
            emit_events=self.rec.emit,
            who=lambda a: {"login": a["login"]},
            audit=self.rec.audit,
            known_people=lambda rows: self.people,
            note_tags=lambda note, old, rows, hints, actor, pid: NoteTags((), []),
            role_of=lambda login: "editor",
            person_name=lambda login: self.people.get(login, {}).get("name", login),
            locate=self.locate,
            stamp=lambda r: None,
            thread_max=3,
            trash_days=30,
            trash_checked=self.checked,
        )
        fields.update(over)
        return PinContext(**fields)

    def locate(self, r):
        """Where a record's file is: under the manuscript folder, else None (outside the tree)."""
        p = Path(str(r.get("file") or ""))
        return PinLocation(p.relative_to(self.ms).as_posix(), p) if p.is_relative_to(self.ms) else None

    def add(self, actor=ALICE_ACTOR, note="n", lo=1, hi=2):
        """A new open line pin by actor in main.tex -> its id."""
        place = LinePlace(
            {"file": str(self.tex), "name": "main.tex", "lo": lo, "hi": hi, "page": 1},
            frozenset({"file", "lo", "hi", "page"}),
        )
        return add_edit.add_pin(self.ctx, self.doc, AddRequest(place, note), actor).record["id"]

    def pins_bytes(self):
        """pins.jsonl as stored now (b'' when missing)."""
        f = self.store.files.pins_jsonl
        return f.read_bytes() if f.exists() else b""

    def pin(self, pid):
        """The stored record of pin pid."""
        return find_record(self.store.read_pins()[0], pid)


class ModuleBoundary(unittest.TestCase):
    """limn/service sits below the composition root: no server import, no run settings, no clock of its own."""

    def modules(self):
        """(file name, set of imported module names, set of Name ids) for every module of the package."""
        out = []
        for f in sorted(SERVICE_DIR.glob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            mods |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            out.append((f.name, mods, names))
        return out

    def test_imports_no_server_http_or_clock(self):
        """No module imports server.py, the HTTP layer, subprocess or a clock (time, datetime): those come in the context."""
        for name, mods, _ in self.modules():
            with self.subTest(name):
                self.assertFalse({m for m in mods if m.startswith(("limn.server", "limn.web", "server"))}, mods)
                self.assertFalse({"time", "datetime", "subprocess", "http", "http.server", "urllib"} & mods, mods)

    def test_reads_no_server_global(self):
        """No run-argument object, server lock or server helper is named in the package."""
        for name, _, names in self.modules():
            with self.subTest(name):
                self.assertFalse(
                    names
                    & {
                        "C",
                        "DOCS",
                        "PIN_LOCK",
                        "now_str",
                        "pin_store",
                        "transact",
                        "THREAD_MAX",
                        "TRASH_DAYS",
                        "_TRASH_CHECKED",
                        "make_docs",
                        "cur_doc",
                    }
                )


class Actors(unittest.TestCase):
    """is_agent and typed_actor: who a request's actor dict is to the rules."""

    def test_headerless_and_token_actors_are_agents(self):
        """login 'local' (also the default) and 'agent:<name>' are agents; a person's login is not."""
        self.assertTrue(is_agent(AGENT))
        self.assertTrue(is_agent({}))
        self.assertTrue(is_agent(None))
        self.assertTrue(is_agent({"login": "agent:ci", "name": "ci"}))
        self.assertFalse(is_agent(ALICE_ACTOR))

    def test_typed_actor_keeps_a_picture_only_when_it_is_text(self):
        """An agent becomes Agent; a person Person with pic only for a non-empty string."""
        self.assertEqual(typed_actor({"login": "agent:ci", "name": "ci"}), Agent("agent:ci", "ci"))
        self.assertEqual(
            typed_actor(dict(ALICE_ACTOR, pic="https://example.com/a.png")),
            Person("alice@example.com", "Alice Kim", "https://example.com/a.png"),
        )
        self.assertEqual(typed_actor(dict(ALICE_ACTOR, pic="")), Person("alice@example.com", "Alice Kim", None))


class LoadPin(unittest.TestCase):
    """load_pin: the one lookup by id every pin action's transact() step starts with."""

    def test_a_found_pin_comes_back_with_its_position(self):
        """The first pin with the id comes back by identity with its position (where a step puts its next state)."""
        pins = [parse_pin({"id": 1, "done": False}), parse_pin({"id": 2, "done": True, "review": True})]
        pins.append(parse_pin({"id": 2}))
        found = load_pin(pins, 2)
        self.assertIsInstance(found, LoadedPin)
        self.assertEqual(found.pos, 1)
        self.assertIs(found.pin, pins[1])
        self.assertIsInstance(found.pin, ReviewPin)
        pos, pin = found
        self.assertEqual((pos, pin), (1, pins[1]))

    def test_a_missing_id_is_a_named_miss(self):
        """No pin with the id is PinNotFound carrying that id, never None."""
        self.assertEqual(load_pin([parse_pin({"id": 1})], 3), PinNotFound(3))
        self.assertEqual(load_pin([], 1), PinNotFound(1))


class AddAndEdit(ServiceBase):
    """add_pin and edit_pin around limn.pins.edit."""

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
            self.ctx, self.doc, AddRequest(place, "hi @Bob", assignee="bob@example.com"), ALICE_ACTOR
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

    def test_an_edit_refusal_writes_nothing_and_notifies_nobody(self):
        """A stale base_rev comes back as StaleEdit; pins.jsonl keeps its bytes and the emit gets no notice."""
        pid = self.add()
        before = self.pins_bytes()
        self.rec.emitted.clear()
        out = add_edit.edit_pin(self.ctx, pid, EditRequest(base_rev=5, note="new"), BOB_ACTOR)
        self.assertIsInstance(out, StaleEdit)
        self.assertEqual(self.pins_bytes(), before)
        self.assertEqual(self.rec.emitted, [[]])

    def test_an_accepted_edit_is_written_in_place(self):
        """A note edit with the current base_rev rewrites the record, bumps rev and records who edited."""
        pid = self.add()
        out = add_edit.edit_pin(self.ctx, pid, EditRequest(base_rev=0, note="new"), BOB_ACTOR)
        self.assertIsInstance(out, OpenPin)
        self.assertEqual(
            (self.pin(pid)["note"], self.pin(pid)["rev"], self.pin(pid)["edited_by"]["login"]),
            ("new", 1, "bob@example.com"),
        )

    def test_edit_of_a_missing_pin_is_a_named_miss(self):
        """No pin with the id: PinNotFound, nothing written."""
        self.assertEqual(add_edit.edit_pin(self.ctx, 9, EditRequest(base_rev=0, note="x"), BOB_ACTOR), PinNotFound(9))
        self.assertEqual(self.pins_bytes(), b"")


class Transitions(ServiceBase):
    """reply_pin, close_pin, reopen_pin and confirm_pin around limn.pins.lifecycle."""

    def test_agent_close_awaits_review_and_tells_the_author(self):
        """An agent's close is a ReviewPin with a review_requested notice to the author; a second close is
        AlreadyClosed and leaves the file as it was."""
        pid = self.add()
        out = transitions.close_pin(self.ctx, pid, AGENT, CloseRequest(reply="fixed"))
        self.assertIsInstance(out, ReviewPin)
        self.assertEqual(self.rec.emitted[-1], [{"type": "review_requested", "pin": pid, "to": ["alice@example.com"]}])
        before = self.pins_bytes()
        self.assertIsInstance(transitions.close_pin(self.ctx, pid, BOB_ACTOR, CloseRequest()), AlreadyClosed)
        self.assertEqual(self.pins_bytes(), before)

    def test_a_person_reply_on_a_closed_pin_reopens_it(self):
        """A person's untagged reply on a done pin is a reopen: the pin is open again and the author hears reopened."""
        pid = self.add()
        transitions.close_pin(self.ctx, pid, ALICE_ACTOR, CloseRequest())
        out = transitions.reply_pin(self.ctx, pid, "redo please", BOB_ACTOR)
        self.assertIsInstance(out, OpenPin)
        self.assertEqual(self.pin(pid)["thread"][-1]["ev"], "reopen")
        self.assertIn({"type": "reopened", "pin": pid, "to": ["alice@example.com"]}, self.rec.emitted[-1])

    def test_a_full_thread_refuses_the_reply_without_writing(self):
        """With thread_max replies already there the next is ThreadFull and pins.jsonl is unchanged."""
        pid = self.add()
        self.ctx = self.context(thread_max=1)
        self.assertIsInstance(transitions.reply_pin(self.ctx, pid, "one", BOB_ACTOR), OpenPin)
        before = self.pins_bytes()
        self.assertIsInstance(transitions.reply_pin(self.ctx, pid, "two", BOB_ACTOR), ThreadFull)
        self.assertEqual(self.pins_bytes(), before)

    def test_close_or_reopen_of_a_missing_pin_is_a_named_miss(self):
        """close_pin and reopen_pin on no pin are PinNotFound, and nothing is written."""
        pid = self.add()
        before = self.pins_bytes()
        self.assertEqual(
            transitions.close_pin(self.ctx, pid + 6, ALICE_ACTOR, CloseRequest(reply="x")), PinNotFound(pid + 6)
        )
        self.assertEqual(transitions.reopen_pin(self.ctx, pid + 6, ALICE_ACTOR, "why", None), PinNotFound(pid + 6))
        self.assertEqual(self.pins_bytes(), before)

    def test_an_agent_confirm_never_loads_the_store(self):
        """AgentCannotConfirm comes back before the store is read: a store whose re-sync would fail is never asked."""

        def boom(pins):
            """A re-sync that must not run."""
            raise AssertionError("store touched")

        ctx = self.context(
            store=PinStore(PinFiles(self.state), self.lock, parse_rec, parse_trash, boom, lambda pins: "")
        )
        self.assertEqual(transitions.confirm_pin(ctx, 1, AGENT), AgentCannotConfirm())

    def test_a_person_confirms_a_pin_awaiting_review(self):
        """Review -> done by a person; confirming again is refused and writes nothing."""
        pid = self.add()
        transitions.close_pin(self.ctx, pid, AGENT, CloseRequest())
        self.assertIsInstance(transitions.confirm_pin(self.ctx, pid, ALICE_ACTOR), DonePin)
        before = self.pins_bytes()
        self.assertNotIsInstance(transitions.confirm_pin(self.ctx, pid, ALICE_ACTOR), DonePin)
        self.assertEqual(self.pins_bytes(), before)


class Claims(ServiceBase):
    """claim_pin and unclaim_pin around limn.pins.lifecycle.claim/unclaim."""

    def test_another_identitys_live_claim_is_refused_without_writing(self):
        """The agent claims; Bob's claim is ClaimedByOther and the file keeps the agent's claim."""
        pid = self.add()
        self.assertIsInstance(claim.claim_pin(self.ctx, pid, AGENT, 30), OpenPin)
        before = self.pins_bytes()
        self.assertIsInstance(claim.claim_pin(self.ctx, pid, BOB_ACTOR, 30), ClaimedByOther)
        self.assertEqual(self.pins_bytes(), before)
        self.assertEqual(self.pin(pid)["claim_until"], T + 30 * 60)

    def test_unclaim_writes_only_when_there_was_a_claim(self):
        """unclaim clears the marker; a second unclaim is NotClaimed with the file unchanged."""
        pid = self.add()
        claim.claim_pin(self.ctx, pid, AGENT, 30)
        self.assertIsInstance(claim.unclaim_pin(self.ctx, pid, BOB_ACTOR), OpenPin)
        self.assertNotIn("claimed_by", self.pin(pid))
        before = self.pins_bytes()
        self.assertIsInstance(claim.unclaim_pin(self.ctx, pid, BOB_ACTOR), NotClaimed)
        self.assertEqual(self.pins_bytes(), before)


class Trash(ServiceBase):
    """drop, restore, the expiry rule, purge and clear."""

    def old_entry(self, pid, days_ago):
        """A Trash entry of pin pid dropped days_ago days before T (local time)."""
        import time as clock

        return {
            "id": pid,
            "file": str(self.tex),
            "lo": 1,
            "hi": 1,
            "dropped_at": clock.strftime("%Y-%m-%d %H:%M:%S", clock.localtime(T - days_ago * 86400)),
        }

    def test_expiry_is_counted_from_dropped_at(self):
        """An entry expires trash_days after dropped_at; one without a readable dropped_at never expires."""
        fresh, old, unknown = (
            TrashedPin.from_record(r) for r in (self.old_entry(1, 29), self.old_entry(2, 31), {"id": 3})
        )
        self.assertEqual(trash.unexpired([fresh, old, unknown], 30, T), [fresh, unknown])
        self.assertIsNone(trash.expires_ts(unknown, 30))
        self.assertFalse(trash.expired(unknown, 30, T + 10**9))

    def test_drop_moves_the_pin_to_the_trash_and_restore_brings_it_back(self):
        """drop takes the pin out of pins.jsonl into the Trash and tells its author; restore puts it back, removes it
        from the Trash, and refuses a second restore (NotInTrash) without touching the Trash file."""
        pid = self.add()
        self.assertIsInstance(trash.drop_pin(self.ctx, pid, BOB_ACTOR), TrashedPin)
        self.assertIsNone(self.pin(pid))
        self.assertEqual([e.pin.core.id for e in self.store.read_dropped()[0]], [pid])
        self.assertEqual(self.rec.emitted[-1], [{"type": "dropped", "pin": pid, "to": ["alice@example.com"]}])
        self.assertIsInstance(trash.restore_pin(self.ctx, pid, ALICE_ACTOR), OpenPin)
        self.assertEqual(self.store.read_dropped()[0], [])
        trash_before = self.store.files.dropped.read_bytes()
        self.assertEqual(trash.restore_pin(self.ctx, pid, ALICE_ACTOR), NotInTrash(pid))
        self.assertEqual(self.store.files.dropped.read_bytes(), trash_before)

    def test_restore_of_a_pin_that_is_live_again_is_refused(self):
        """A Trash copy whose id is live is AlreadyLive; both files keep their bytes."""
        pid = self.add()
        self.store.write_dropped([TrashedPin.from_record(dict(self.pin(pid), dropped_at=STAMP))])
        pins, dropped = self.pins_bytes(), self.store.files.dropped.read_bytes()
        self.assertEqual(trash.restore_pin(self.ctx, pid, ALICE_ACTOR), AlreadyLive(pid))
        self.assertEqual((self.pins_bytes(), self.store.files.dropped.read_bytes()), (pins, dropped))

    def test_purge_trash_drops_expired_entries_and_restarts_the_hourly_clock(self):
        """purge_trash rewrites the Trash without expired entries and returns how many went; maybe_purge_trash waits
        TRASH_CHECK_EVERY_S after any check."""
        self.store.write_dropped(
            [TrashedPin.from_record(self.old_entry(1, 31)), TrashedPin.from_record(self.old_entry(2, 1))]
        )
        self.assertEqual(trash.purge_trash(self.ctx), 1)
        self.assertEqual([e.pin.core.id for e in self.store.read_dropped()[0]], [2])
        self.assertEqual(self.checked, [T])
        self.assertEqual(trash.maybe_purge_trash(self.ctx), 0)
        later = self.context(epoch=lambda: T + trash.TRASH_CHECK_EVERY_S + 2 * 86400 * 30)
        self.assertEqual(trash.maybe_purge_trash(later), 1)

    def test_purge_pin_is_audited_outside_the_pin_lock(self):
        """A permanent delete removes the entry, emits `purged` and appends the audit line after releasing the lock;
        a pin not in the Trash is NotInTrash with no audit."""
        pid = self.add()
        trash.drop_pin(self.ctx, pid, ALICE_ACTOR)
        self.assertIsInstance(trash.purge_pin(self.ctx, pid, ALICE_ACTOR), TrashedPin)
        self.assertEqual(self.store.read_dropped()[0], [])
        self.assertEqual(
            self.rec.emitted[-1], [{"type": "purged", "to": [], "pin": pid, "by": {"login": "alice@example.com"}}]
        )
        self.assertEqual(self.rec.audits, [("purged", "alice@example.com", {"pin": pid}, True)])
        self.assertEqual(trash.purge_pin(self.ctx, pid, ALICE_ACTOR), NotInTrash(pid))
        self.assertEqual(len(self.rec.audits), 1)

    def test_clear_archives_and_is_audited_as_the_agent_without_an_actor(self):
        """clear_pins archives pins.jsonl, emits `cleared` and audits it outside the lock - by the headerless agent
        when no actor is given."""
        self.add()
        out = trash.clear_pins(self.ctx)
        self.assertEqual(out["cleared"], 1)
        self.assertTrue((self.state / out["archive"]).exists())
        self.assertFalse(self.store.files.pins_jsonl.exists())
        self.assertEqual(self.rec.audits, [("cleared", "local", {"n": 1, "archive": out["archive"]}, True)])


# ---------------------------------------------------------------- through server.py's wiring
#
# Claims and closing with a reply, over the server's pin context. These classes load server.py (helpers.ps) and drive
# the module through its bindings; the tests above call the module on its own.

# ---------------------------------------------------------------- close reason · re-close no-op (docs/handbook/api.md §닫을 때 사유 남기기, §휴지통)


class CloseReplyRef(Base):
    """§C: /close accepts optional {"reply","ref"} and stores them as close_reply/close_ref."""

    def test_close_with_reply_and_ref_is_stored(self):
        pid = self.add()
        p = record_of(
            ps.close_pin(
                pid,
                dict(LOCAL_ACTOR),
                parse.parse_close({"reply": "제목을 고침", "ref": "PR #227"}, ps.C.src, ps.C.state),
            )
        )
        self.assertEqual(p["close_reply"], "제목을 고침")
        self.assertEqual(p["close_ref"], "PR #227")
        self.assertTrue(p["done"])

    def test_close_without_body_behaves_as_before(self):
        pid = self.add()
        p = record_of(ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest()))
        self.assertNotIn("close_reply", p)
        self.assertNotIn("close_ref", p)

    def test_clean_close_body_empty_or_whitespace_is_none(self):
        self.assertEqual(parse.parse_close_body({}), (None, None))
        self.assertEqual(parse.parse_close_body({"reply": "", "ref": "  "}), (None, None))
        self.assertEqual(parse.parse_close_body({"reply": None, "ref": None}), (None, None))

    def test_clean_close_body_rejects_wrong_type(self):
        self.assertIsInstance(parse.parse_close_body({"reply": 123}), InputRejected)
        self.assertIsInstance(parse.parse_close_body({"ref": ["PR #227"]}), InputRejected)

    def test_clean_close_body_enforces_length_caps(self):
        self.assertIsInstance(parse.parse_close_body({"reply": "x" * (parse.CLOSE_REPLY_MAX + 1)}), InputRejected)
        self.assertIsInstance(parse.parse_close_body({"ref": "x" * (parse.CLOSE_REF_MAX + 1)}), InputRejected)
        # the cap itself is allowed through.
        reply, ref = parse.parse_close_body({"reply": "x" * parse.CLOSE_REPLY_MAX, "ref": "x" * parse.CLOSE_REF_MAX})
        self.assertEqual(len(reply), parse.CLOSE_REPLY_MAX)
        self.assertEqual(len(ref), parse.CLOSE_REF_MAX)

    def test_close_endpoint_http_stores_reply_and_escapes_in_card(self):
        pid = self.add()
        body = json.dumps({"reply": "제목을 <b>고침</b>", "ref": "PR #227"}).encode()
        out = self.talk(req("POST", "/api/pins/%d/close" % pid, body, {"Content-Type": "application/json"}))
        self.assertIn(b" 200 ", out)
        p = self.pin(pid)
        self.assertEqual(p["close_reply"], "제목을 <b>고침</b>")
        self.assertEqual(p["close_ref"], "PR #227")

    def test_close_endpoint_http_rejects_oversized_reply(self):
        pid = self.add()
        body = json.dumps({"reply": "x" * (parse.CLOSE_REPLY_MAX + 1)}).encode()
        out = self.talk(req("POST", "/api/pins/%d/close" % pid, body, {"Content-Type": "application/json"}))
        self.assertIn(b" 400 ", out)
        self.assertFalse(self.pin(pid).get("done"))


class CloseIdempotent(Base):
    """§D: re-closing an already-closed pin changes nothing (rev stays the same too)."""

    def test_second_close_does_not_overwrite_closed_by_or_rev(self):
        pid = self.add()
        first = record_of(ps.close_pin(pid, {"login": "alice", "name": "Wendy"}, CloseRequest()))
        self.assertEqual(first["rev"], 1)
        second = record_of(ps.close_pin(pid, {"login": "bob", "name": "Bob"}, CloseRequest()))
        self.assertEqual(second["closed_by"]["login"], "alice")
        self.assertEqual(second["rev"], first["rev"])
        self.assertEqual(second["done_at"], first["done_at"])

    def test_second_close_with_reply_does_not_apply(self):
        pid = self.add()
        ps.close_pin(pid, dict(LOCAL_ACTOR), parse.parse_close({"reply": "first"}, ps.C.src, ps.C.state))
        again = record_of(
            ps.close_pin(pid, dict(LOCAL_ACTOR), parse.parse_close({"reply": "second"}, ps.C.src, ps.C.state))
        )
        self.assertEqual(again["close_reply"], "first")

    def test_reopen_then_close_allows_new_reply(self):
        pid = self.add()
        ps.close_pin(
            pid, dict(LOCAL_ACTOR), parse.parse_close({"reply": "first", "ref": "PR #1"}, ps.C.src, ps.C.state)
        )
        ps.reopen_pin(pid, dict(LOCAL_ACTOR))
        reopened = self.pin(pid)
        self.assertNotIn("close_reply", reopened)
        self.assertNotIn("close_ref", reopened)
        closed_again = record_of(
            ps.close_pin(pid, dict(LOCAL_ACTOR), parse.parse_close({"reply": "second"}, ps.C.src, ps.C.state))
        )
        self.assertEqual(closed_again["close_reply"], "second")
        self.assertNotIn("close_ref", closed_again)

    def test_close_http_endpoint_second_call_returns_ok_unchanged(self):
        pid = self.add()
        out1 = self.talk(req("POST", "/api/pins/%d/close" % pid))
        self.assertIn(b" 200 ", out1)
        rev_after_first = self.pin(pid)["rev"]
        out2 = self.talk(req("POST", "/api/pins/%d/close" % pid))
        self.assertIn(b" 200 ", out2)
        self.assertTrue(json.loads(out2.split(b"\r\n\r\n", 1)[1])["ok"])
        self.assertEqual(self.pin(pid)["rev"], rev_after_first)


# ---------------------------------------------------------------- in-progress indicator (docs/handbook/api.md §처리 중 표시 (claim))


class Claim(Base):
    def test_claim_sets_fields_and_bumps_rev(self):
        pid = self.add()
        p = record_of(ps.claim_pin(pid, {"login": "alice@example.com", "name": "Wendy"}, 120))
        self.assertEqual(p["claimed_by"], {"login": "alice@example.com", "name": "Wendy"})
        self.assertEqual(p["rev"], 1)
        self.assertTrue(ps.claim_active(self.pin(pid)))

    def test_default_ttl_used_when_body_omits_it(self):
        pid = self.add()
        before = time.time()
        p = record_of(ps.claim_pin(pid, dict(LOCAL_ACTOR), parse.parse_claim_body({}).ttl))
        self.assertAlmostEqual(p["claim_until"], before + parse.CLAIM_TTL_DEFAULT * 60, delta=5)

    def test_claim_conflict_from_other_identity_is_409(self):
        pid = self.add()
        ps.claim_pin(pid, {"login": "alice@example.com", "name": "Wendy"}, 120)
        refused = ps.claim_pin(pid, {"login": "bob@example.com", "name": "Bob"}, 120)  # answered 409 "claimed"
        self.assertIsInstance(refused, ClaimedByOther)
        self.assertEqual(refused.claimed_by["login"], "alice@example.com")
        self.assertIsNotNone(refused.claim_until)

    def test_claim_same_identity_extends(self):
        pid = self.add()
        first = record_of(ps.claim_pin(pid, {"login": "alice@example.com", "name": "Wendy"}, 5))
        second = record_of(ps.claim_pin(pid, {"login": "alice@example.com", "name": "Wendy"}, 200))
        self.assertGreater(second["claim_until"], first["claim_until"])
        self.assertEqual(second["rev"], first["rev"] + 1)

    def test_claim_on_closed_pin_is_409_done(self):
        pid = self.add()
        ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest())
        # 409 "done"
        self.assertIsInstance(ps.claim_pin(pid, {"login": "alice@example.com", "name": "Wendy"}, 120), ClaimClosedPin)

    def test_claim_missing_pin_id_returns_none(self):
        self.assertEqual(ps.claim_pin(999, dict(LOCAL_ACTOR), 120), PinNotFound(999))

    def test_ttl_out_of_range_or_wrong_type_rejected(self):
        for bad in (0, -1, "120", 12.5, True, None):  # 400 for a wrong type or a value below 1
            self.assertIsInstance(parse.parse_claim_body({"ttl_min": bad}), InputRejected)
        self.assertEqual(parse.parse_claim_body({}).ttl, parse.CLAIM_TTL_DEFAULT)
        self.assertEqual(parse.parse_claim_body({"ttl_min": 1}).ttl, 1)
        self.assertEqual(parse.parse_claim_body({"ttl_min": 120}).ttl, 120)
        self.assertEqual(parse.CLAIM_TTL_MAX, 120)
        for over in (121, 480, 10_000):  # above the cap (120, formerly 480) it gets clamped down (backward compat)
            self.assertEqual(parse.parse_claim_body({"ttl_min": over}).ttl, 120)

    def test_expired_claim_is_inactive_and_can_be_reclaimed_by_another_identity(self):
        pid = self.add()
        ps.claim_pin(pid, {"login": "alice@example.com", "name": "Wendy"}, 120)
        rows = records(ps.snapshot_pins())
        for r in rows:
            if r["id"] == pid:
                r["claim_until"] = time.time() - 10
        write_records(rows)
        self.assertFalse(ps.claim_active(self.pin(pid)))
        p = record_of(ps.claim_pin(pid, {"login": "bob@example.com", "name": "Bob"}, 120))
        self.assertEqual(p["claimed_by"]["login"], "bob@example.com")

    def test_unclaim_clears_fields_regardless_of_requester(self):
        pid = self.add()
        ps.claim_pin(pid, {"login": "alice@example.com", "name": "Wendy"}, 120)
        p = record_of(ps.unclaim_pin(pid, {"login": "bob@example.com", "name": "Bob"}))
        self.assertNotIn("claimed_by", p)
        self.assertNotIn("claimed_at", p)
        self.assertNotIn("claim_until", p)

    def test_unclaim_missing_pin_returns_none(self):
        self.assertEqual(ps.unclaim_pin(999, dict(LOCAL_ACTOR)), PinNotFound(999))

    def test_close_clears_claim(self):
        pid = self.add()
        ps.claim_pin(pid, dict(LOCAL_ACTOR), 120)
        p = record_of(ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest()))
        self.assertNotIn("claimed_by", p)

    def test_drop_clears_claim_even_in_dropped_record(self):
        pid = self.add()
        ps.claim_pin(pid, dict(LOCAL_ACTOR), 120)
        ps.drop_pin(pid, dict(LOCAL_ACTOR))
        dropped = ps.dropped_payload()
        self.assertEqual(len(dropped), 1)
        self.assertNotIn("claimed_by", dropped[0])

    def test_pins_md_shows_hourglass_with_claimer_name_and_legend(self):
        pid = self.add()
        ps.claim_pin(pid, {"login": "kim@example.com", "name": "Coauthor Kim"}, 120)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("처리 중(Coauthor Kim)", md)  # just the name when there's no ETA
        self.assertNotIn("⏳", md)
        self.assertIn("'처리 중(이름, 약 N분)' = 다른 에이전트가 잡음, 건너뛴다", md)

    def test_pins_md_hourglass_uses_local_label_for_curl_claims(self):
        pid = self.add()
        ps.claim_pin(pid, dict(LOCAL_ACTOR), 120)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("처리 중(로컬/에이전트)", md)

    def test_claim_fields_survive_jsonl_roundtrip(self):
        pid = self.add()
        ps.claim_pin(pid, {"login": "alice@example.com", "name": "Wendy"}, 120)
        pins, bad = ps.read_pins()
        self.assertEqual(bad, [])
        self.assertIn("claimed_by", find_record(pins, pid))

    def test_http_claim_then_conflict_then_unclaim(self):
        pid = self.add()
        h1 = {"Host": "127.0.0.1:18999", "Tailscale-User-Login": "alice@example.com", "Tailscale-User-Name": "Wendy"}
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, headers=h1))
        self.assertIn(b" 200 ", out)
        h2 = {"Host": "127.0.0.1:18999", "Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob"}
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, headers=h2))
        self.assertIn(b" 409 ", out)
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(body["claimed_by"]["login"], "alice@example.com")
        out = self.talk(req("POST", "/api/pins/%d/unclaim" % pid))
        self.assertIn(b" 200 ", out)
        self.assertFalse(ps.claim_active(self.pin(pid)))

    def test_http_claim_bad_ttl_type_is_400(self):
        pid = self.add()
        body = json.dumps({"ttl_min": "soon"}).encode()
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, body, {"Content-Type": "application/json"}))
        self.assertIn(b" 400 ", out)

    def test_http_claim_missing_pin_returns_ok_false(self):
        out = self.talk(req("POST", "/api/pins/999/claim"))
        self.assertIn(b" 200 ", out)
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertFalse(body["ok"])


class Who(unittest.TestCase):
    """who: an actor as notices and audit.jsonl record it."""

    def test_login_and_name_only_with_the_local_defaults(self):
        """A person keeps login and name (never pic or role); an empty actor is the headerless loopback agent."""
        self.assertEqual(
            who({"login": "alice@example.com", "name": "Alice", "pic": "https://x", "role": "owner"}),
            {"login": "alice@example.com", "name": "Alice"},
        )
        self.assertEqual(who({}), {"login": "local", "name": ""})
        actor = {"login": "agent:ci", "name": "ci"}
        self.assertIsNot(who(actor), actor)


class NoteAppend(Base):
    """An edit with note_append adds to the note in place (one line, undoable), needs no base_rev, and is refused
    without a change when it is empty or would take the note over NOTE_MAX."""

    def test_note_append_then_undo(self):
        pid = self.add(note="원본")
        p0 = self.pin(pid)
        p1 = record_of(edit_pin(pid, {"note_append": "추가 텍스트"}, dict(LOCAL_ACTOR)))
        self.assertIn("추가 텍스트", p1["note"])
        self.assertIn("(추가 ", p1["note"])
        self.assertEqual(len(ps.C.pins_jsonl.read_text().splitlines()), 1)  # line count unchanged
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
        self.assertEqual(self.pin(pid)["rev"], 0)  # rev doesn't bump either


class ClaimEstimate(Base):
    """A claim with an estimate (eta_min) stores eta_ts and the start next to claim_until; the same identity extends it
    keeping the start, another identity is refused with the holder's estimate, and every way of ending the claim
    (close, drop, unclaim) clears all claim fields."""

    A = {"login": "alice@example.com", "name": "Wendy"}

    B = {"login": "bob@example.com", "name": "Bob"}

    def test_claim_stores_eta_and_start(self):
        pid = self.add()
        t0 = time.time()
        p = record_of(ps.claim_pin(pid, self.A, *parse.parse_claim_body({"eta_min": 15})))
        self.assertAlmostEqual(p["eta_ts"], t0 + 15 * 60, delta=5)
        self.assertAlmostEqual(p["claim_ts"], t0, delta=5)
        self.assertAlmostEqual(p["claim_until"], t0 + 30 * 60, delta=5)
        self.assertIsInstance(p["claimed_at"], str)
        rows = records(ps.read_pins()[0])  # it's a stored value (not a computed field)
        self.assertIn("eta_ts", find_pin(rows, pid))

    def test_same_identity_reclaim_extends_and_updates_estimate(self):
        pid = self.add()
        first = record_of(ps.claim_pin(pid, self.A, *parse.parse_claim_body({"eta_min": 5})))
        with ps.PIN_LOCK:  # move it back to having been claimed 10 minutes ago
            rows = records(ps.read_pins()[0])
            r = find_pin(rows, pid)
            for k in ("claim_ts", "eta_ts", "claim_until"):
                r[k] -= 600
            write_records(rows)
        second = record_of(ps.claim_pin(pid, self.A, *parse.parse_claim_body({"eta_min": 20})))
        self.assertAlmostEqual(second["claim_ts"], first["claim_ts"] - 600, delta=1)  # the start time stays put
        self.assertEqual(second["claimed_at"], first["claimed_at"])
        self.assertAlmostEqual(second["eta_ts"], time.time() + 20 * 60, delta=5)  # the new estimate starts from now
        self.assertAlmostEqual(second["claim_until"], time.time() + 40 * 60, delta=5)
        # extending with no new estimate keeps the previous one
        third = record_of(ps.claim_pin(pid, self.A, *parse.parse_claim_body({})))
        self.assertEqual(third["eta_ts"], second["eta_ts"])
        self.assertEqual(third["rev"], second["rev"] + 1)

    def test_other_identity_conflict_reports_eta_and_new_claim_drops_old_eta(self):
        pid = self.add()
        ps.claim_pin(pid, self.A, *parse.parse_claim_body({"eta_min": 15}))
        refused = ps.claim_pin(pid, self.B, *parse.parse_claim_body({"eta_min": 5}))  # answered 409 "claimed"
        self.assertIsInstance(refused, ClaimedByOther)
        self.assertIsNotNone(refused.eta_ts)
        with ps.PIN_LOCK:  # A's claim has expired
            rows = records(ps.read_pins()[0])
            find_pin(rows, pid)["claim_until"] = time.time() - 1
            write_records(rows)
        p = record_of(ps.claim_pin(pid, self.B, *parse.parse_claim_body({})))
        self.assertEqual(p["claimed_by"]["login"], "bob@example.com")
        self.assertNotIn("eta_ts", p)  # doesn't inherit someone else's old estimate

    def test_close_drop_unclaim_clear_all_claim_fields(self):
        for how in ("close", "drop", "unclaim"):
            pid = self.add()
            ps.claim_pin(pid, self.A, *parse.parse_claim_body({"eta_min": 10}))
            if how == "close":
                rec = record_of(ps.close_pin(pid, self.A, CloseRequest()))
            elif how == "unclaim":
                rec = record_of(ps.unclaim_pin(pid, self.A))
            else:
                ps.drop_pin(pid, self.A)
                rec = trash_records()[-1]
            for k in CLAIM_FIELDS:
                self.assertNotIn(k, rec, (how, k))


class PinKindAndThread(Base):
    """kind_req (fix request or question) is stored only when given and can be switched on a closed pin; the thread is
    capped except for status records, and a close reply enters it once."""

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
        pid = self.add()
        p = record_of(edit_pin(pid, {"kind_req": "question", "base_rev": 0}, dict(self.S)))
        self.assertEqual(p["kind_req"], "question")
        ps.close_pin(pid, dict(self.S), CloseRequest())
        p = record_of(edit_pin(pid, {"kind_req": "fix", "base_rev": self.pin(pid)["rev"]}, dict(self.S)))
        self.assertEqual(p["kind_req"], "fix")

    def test_thread_is_capped(self):
        pid = self.add()
        with mock.patch.object(ps, "THREAD_MAX", 2):
            ps.reply_pin(pid, "1", dict(self.S))
            ps.reply_pin(pid, "2", dict(self.S))
            self.assertEqual(ps.reply_pin(pid, "3", dict(self.S)), ThreadFull(2))  # answered 409 "full" over HTTP
            # a status-transition record is exempt from the cap
            ps.close_pin(pid, dict(self.S), CloseRequest(reply="닫음"))
        self.assertEqual([m.get("ev") for m in self.pin(pid)["thread"]], [None, None, "close"])

    def test_close_reply_is_appended_to_thread_once(self):
        pid = self.add()
        ps.reply_pin(pid, "질문이 있어요", dict(self.S))
        ps.close_pin(pid, dict(self.S), CloseRequest(reply="제목을 고침", ref="PR #227"))
        ps.close_pin(pid, dict(self.S), CloseRequest(reply="두 번째 닫기"))  # already closed — nothing gets appended
        th = self.pin(pid)["thread"]
        self.assertEqual(
            [(m["id"], m.get("ev"), m["text"], m.get("ref")) for m in th],
            [(1, None, "질문이 있어요", None), (2, "close", "제목을 고침", "PR #227")],
        )
        # the old field is left in place too (compat with old viewers/agents)
        self.assertEqual(self.pin(pid)["close_reply"], "제목을 고침")


class ReviewTransitions(Base):
    """A pin awaiting review is not open work for agents (not listed, not claimable, counted apart), and reopening a
    confirmed pin drops the confirmation."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    def test_review_pins_are_not_open_for_agents(self):
        pid = self.add()
        ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest(reply="고침"))
        _, _, raw = split_resp(self.talk(req("GET", "/api/pins")))
        self.assertEqual(json.loads(raw), [])  # not in the open-pin list (legacy contract)
        self.assertIsInstance(ps.claim_pin(pid, dict(LOCAL_ACTOR), 30), ClaimClosedPin)  # 409 "done"
        m = ps.meta(ps.DOCS[0], dict(LOCAL_ACTOR))
        self.assertEqual((m["n_open"], m["n_review"], m["n_done"]), (0, 1, 0))

    def test_reopen_after_confirm_drops_confirmation(self):
        pid = self.add()
        ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest())
        ps.confirm_pin(pid, dict(self.S))
        ps.reopen_pin(pid, dict(self.S), reason="다시")
        p = self.pin(pid)
        self.assertNotIn("confirmed_by", p)
        self.assertEqual(pin_state(p), "open")


class MentionsOnEdit(Base):
    """An edit notifies only newly tagged people, a self-tag is never stored or addressed, and a reopen after a confirm
    still marks the pin reopened."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    W = {"login": "wendy@example.com", "name": "Wendy Kim"}

    def setUp(self):
        super().setUp()
        ps._PEOPLE_SEEN.clear()
        ps._EVENTS_CACHE.clear()

    def events(self):
        return ps._read_events()[0]

    def test_edit_adds_mention_event_only_for_new_names(self):
        ps.record_person(dict(self.W))
        ps.record_person(dict(self.S))
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
        # observed bug: reopening after a confirm made the round start with [confirm, reopen, ...], so the
        # "reopened" marker was missing (the old check only looked at "is the round's first message a
        # reopen?"). pin_reopened_in_round() now skips over confirm.
        pid = self.add()
        ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest(reply="고침"))
        ps.confirm_pin(pid, dict(self.S))
        ps.reopen_pin(pid, dict(self.S), reason="다시 봐 주세요")
        self.assertTrue(pin_reopened_in_round(parse_pin(self.pin(pid)).core.thread))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % pid))
        self.assertIn("다시 열림", row)

    def test_self_mention_never_becomes_addressed(self):
        ps.record_person(dict(self.W))
        ps.record_person(dict(self.S))
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "note": "@Wendy Kim 셀프 태그", "kind_req": "question"},
            dict(self.W),
        ).record["id"]
        p = self.pin(pid)
        self.assertNotIn("mentions", p)  # a self-@mention isn't stored
        self.assertEqual(mentions.addressed_to(parse_pin(p)), [])
        msg = ps.reply_pin(pid, "@Bob Park 님 확인 부탁드립니다 @Wendy Kim", dict(self.W)).record["thread"][-1]
        self.assertEqual(msg["mentions"], [self.S["login"]])  # the reply's own author (W) is excluded


# ---------------------------------------------------------------- the close contract's optional `changes` (v0.3, issue #9)


class CloseChanges(AccessBase):
    """The optional `changes` on POST /api/pins/{id}/close: validation, storage, reopen, pins.md."""

    def setUp(self):
        super().setUp()
        (self.src / "sec").mkdir()
        (self.src / "sec" / "a.tex").write_text("x\n" * 30)
        self.pid = self.add()

    def close(self, body):
        return self.call("POST", "/api/pins/%d/close" % self.pid, body)

    def test_valid_changes_are_stored_as_absolute_paths_and_exposed(self):
        """A valid changes list is stored resolved and absolute on the first close and appears in the pins API."""
        code, d = self.close(
            {
                "reply": "fixed",
                "ref": "abc1234",
                "changes": [
                    {"file": "main.tex", "lo": 4, "hi": 5},
                    {"file": str(self.src / "sec" / "a.tex"), "lo": 7, "hi": 7},
                ],
            }
        )
        self.assertEqual(code, 200, d)
        want = [
            {"file": str(self.main.resolve()), "lo": 4, "hi": 5},
            {"file": str((self.src / "sec" / "a.tex").resolve()), "lo": 7, "hi": 7},
        ]
        self.assertEqual(d["pin"]["changes"], want)
        code, d = self.call("GET", "/api/pins/%d" % self.pid)
        self.assertEqual(d["pin"]["changes"], want)
        code, d = self.call("GET", "/api/pins?all=1")
        self.assertEqual([p.get("changes") for p in d if p["id"] == self.pid], [want])
        self.assertTrue(fits(self.pin(self.pid)))

    def test_invalid_changes_are_rejected_with_400_and_change_nothing(self):
        """Each malformed changes item or list is a 400 and leaves the pin open (boundary validation)."""
        bad = [
            {"file": "main.tex", "lo": 5, "hi": 4},
            {"file": "main.tex", "lo": 0, "hi": 1},
            {"file": "main.tex", "lo": 1.5, "hi": 2},
            {"file": "main.tex", "lo": True, "hi": 2},
            {"file": "main.tex", "lo": "1", "hi": 2},
            {"file": "main.tex", "lo": 1},
            {"file": "", "lo": 1, "hi": 1},
            {"file": 3, "lo": 1, "hi": 1},
            {"file": "../outside.tex", "lo": 1, "hi": 1},
            {"file": "/etc/passwd", "lo": 1, "hi": 1},
            {"file": "main.tex", "lo": 1, "hi": 1, "extra": 1},
            {"file": "main.tex", "lo": 1, "hi": 10**7},
            {"file": "a\x00b", "lo": 1, "hi": 1},
            "main.tex:1-2",
        ]
        for item in bad:
            with self.subTest(item=item):
                code, d = self.close({"changes": [item]})
                self.assertEqual(code, 400, d)
                self.assertFalse(self.pin(self.pid).get("done"))
        for whole in (
            {"file": "main.tex", "lo": 1, "hi": 1},
            "x",
            [{"file": "main.tex", "lo": 1, "hi": 1}] * (parse.CLOSE_CHANGES_MAX + 1),
        ):
            with self.subTest(whole=str(whole)[:40]):
                code, d = self.close({"changes": whole})
                self.assertEqual(code, 400, d)
        self.assertFalse(self.pin(self.pid).get("done"))

    def test_absent_or_empty_changes_close_like_0_2_2(self):
        """Old agents: a close without changes (or with []) stores nothing new."""
        code, d = self.close({"changes": []})
        self.assertEqual(code, 200)
        self.assertNotIn("changes", d["pin"])
        other = self.add(lo=8, hi=9)
        code, d = self.call("POST", "/api/pins/%d/close" % other)
        self.assertEqual((code, "changes" in d["pin"]), (200, False))

    def test_reclose_keeps_and_reopen_clears_changes(self):
        """Changes follow close_reply/close_ref: the first close wins, a reopen clears them."""
        self.close({"changes": [{"file": "main.tex", "lo": 4, "hi": 5}]})
        self.close({"changes": [{"file": "main.tex", "lo": 9, "hi": 9}]})
        self.assertEqual(self.pin(self.pid)["changes"][0]["lo"], 4)
        self.call("POST", "/api/pins/%d/reopen" % self.pid, {})
        self.assertNotIn("changes", self.pin(self.pid))

    def test_a_malformed_stored_changes_field_marks_the_line_broken(self):
        """The record parse (parse_record) refuses a record whose stored changes have the wrong shape."""
        r = dict(self.pin(self.pid), changes=[{"file": 3, "lo": 1, "hi": 2}])
        self.assertFalse(fits(r))
        self.assertTrue(fits(dict(r, changes=[{"file": "/a.tex", "lo": 1, "hi": 2}])))

    def test_pins_md_close_instruction_line_asks_for_changes_and_the_merged_commit(self):
        """Owner decision (review of #13): the close line asks for changes and ref = PR #N (hash); the rest of the line is 0.2.2's."""
        # decided after review (ADR-0005, accepted): paper repos squash-merge and agents close after the merge, so the
        # line asks for `changes` in the numbering of the commit `ref` names, and ref = "PR #N (<hash>)"; per-pin commits
        # help but are optional
        text = ps.pins_md_text(ps.snapshot_pins())
        line = next(ln for ln in text.splitlines() if ln.startswith("처리한 핀은 닫는다"))
        self.assertTrue(
            line.startswith(
                "처리한 핀은 닫는다 — 닫을 때 `changes` 에 이 핀 때문에 바꾼 줄 범위를, `ref` 에 `PR #번호 (커밋 해시)` 를 적는다: `curl"
            ),
            line,
        )
        self.assertIn(
            '"ref":"PR #12 (커밋 해시)","changes":[{"file":"main.tex","lo":12,"hi":14}]}'
            + "' http://127.0.0.1:18999/api/pins/N/close`",
            line,
        )
        self.assertIn(
            "(본문 생략 가능, 그러면 옛 방식처럼 사유 없이 닫힘. `changes` 의 줄 번호는 `ref` 의 커밋이 만든 판 기준 — 스쿼시 머지 뒤 닫으면 머지된 main 기준, 경로는 위치 칸 기준. 핀마다 커밋을 나누면 더 좋지만 필수는 아니다)"
            + " · 줄 번호는 갱신 시각 기준이니 원문을 다시 읽고 고친다 · '질문' 핀은 원고를 고치지 말고",
            line,
        )
        self.assertNotIn("스쿼시하지", line)
        self.assertTrue(
            line.endswith(
                "에이전트는 확인(confirm)하지 않는다 — `/api/pins/N/confirm` 은 사람 신원(테일넷 헤더)이 없으면 403"
            )
        )


if __name__ == "__main__":
    unittest.main()
