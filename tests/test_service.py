"""limn.service - the pin service shells, driven directly with a real PinStore over a temp folder and recording sinks.

The rules themselves are pinned in test_pins_lifecycle.py and test_pins_edit.py, and every HTTP flow in
test_server.py, test_v022.py and test_v031.py. This file pins what the shells add around the rules: they write only
when the rule accepts, notices are emitted only after the write and never for a refusal, the audit line is appended
outside the pin lock, an agent's confirm never touches the store, and the package's import boundary.

Run: uv run pytest -q tests/test_service.py
"""
import ast
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from limn import service
from limn.access import LOCAL_ACTOR
from limn.locate import PinLocation
from limn.mentions import NoteTags
from limn.pins.edit import AddRequest, EditRequest, LinePlace, StaleEdit
from limn.pins.lifecycle import (
    AgentCannotConfirm, AlreadyClosed, AlreadyLive, ClaimedByOther, NotClaimed, NotInTrash, ThreadFull,
)
from limn.pins.model import Agent, DonePin, OpenPin, Person, PinNotFound, ReviewPin, TrashedPin
from limn.service import add_edit, claim, trash, transitions
from limn.service.context import PinContext, is_agent, typed_actor
from limn.store import PinFiles, PinStore, find_pin

SERVICE_DIR = Path(service.__file__).parent
T = 1790000000.0
STAMP = "2026-09-26 10:00:00"
ALICE = {"login": "alice@example.com", "name": "Alice Kim"}
BOB = {"login": "bob@example.com", "name": "Bob Park"}
AGENT = dict(LOCAL_ACTOR)


class Refused(Exception):
    """The refusal a transaction step may raise (the server passes its HTTPError); no service raises it."""


def valid(r: object) -> bool:
    """The test's record check: a JSON object with an integer id."""
    return isinstance(r, dict) and isinstance(r.get("id"), int) and not isinstance(r.get("id"), bool)


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
        self.store = PinStore(PinFiles(self.state), self.lock, valid, lambda rows: False, lambda rows: "md\n", Refused)
        self.rec = Recorder(self.lock)
        self.people = {"alice@example.com": ALICE, "bob@example.com": BOB}
        self.checked = [0.0]
        self.ctx = self.context()
        self.doc = SimpleNamespace(key="main", dir=self.state)

    def tearDown(self):
        """Remove the temp folder."""
        self.tmp.cleanup()

    def context(self, **over):
        """A PinContext over this test's store and recorder; keyword arguments replace single collaborators."""
        fields = dict(
            store=self.store, now=lambda: STAMP, epoch=lambda: T, hm=lambda: "10:00",
            make_event=self.rec.make_event, emit_events=self.rec.emit, who=lambda a: {"login": a["login"]},
            audit=self.rec.audit, known_people=lambda rows: self.people,
            note_tags=lambda note, old, rows, hints, actor, pid: NoteTags((), []),
            role_of=lambda login: "editor", person_name=lambda login: self.people.get(login, {}).get("name", login),
            locate=self.locate, stamp=lambda r: None, thread_max=3, trash_days=30, trash_checked=self.checked)
        fields.update(over)
        return PinContext(**fields)

    def locate(self, r):
        """Where a record's file is: under the manuscript folder, else None (outside the tree)."""
        p = Path(str(r.get("file") or ""))
        return PinLocation(p.relative_to(self.ms).as_posix(), p) if p.is_relative_to(self.ms) else None

    def add(self, actor=ALICE, note="n", lo=1, hi=2):
        """A new open line pin by actor in main.tex -> its id."""
        place = LinePlace({"file": str(self.tex), "name": "main.tex", "lo": lo, "hi": hi, "page": 1},
                          frozenset({"file", "lo", "hi", "page"}))
        return add_edit.add_pin(self.ctx, self.doc, AddRequest(place, note), actor).record["id"]

    def pins_bytes(self):
        """pins.jsonl as stored now (b'' when missing)."""
        f = self.store.files.pins_jsonl
        return f.read_bytes() if f.exists() else b""

    def pin(self, pid):
        """The stored record of pin pid."""
        return find_pin(self.store.read_pins()[0], pid)


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
                self.assertFalse(names & {"C", "DOCS", "PIN_LOCK", "now_str", "pin_store", "transact", "THREAD_MAX",
                                          "TRASH_DAYS", "_TRASH_CHECKED", "make_docs", "cur_doc"})


class Actors(unittest.TestCase):
    """is_agent and typed_actor: who a request's actor dict is to the rules."""

    def test_headerless_and_token_actors_are_agents(self):
        """login 'local' (also the default) and 'agent:<name>' are agents; a person's login is not."""
        self.assertTrue(is_agent(AGENT))
        self.assertTrue(is_agent({}))
        self.assertTrue(is_agent(None))
        self.assertTrue(is_agent({"login": "agent:ci", "name": "ci"}))
        self.assertFalse(is_agent(ALICE))

    def test_typed_actor_keeps_a_picture_only_when_it_is_text(self):
        """An agent becomes Agent; a person Person with pic only for a non-empty string."""
        self.assertEqual(typed_actor({"login": "agent:ci", "name": "ci"}), Agent("agent:ci", "ci"))
        self.assertEqual(typed_actor(dict(ALICE, pic="https://example.com/a.png")),
                         Person("alice@example.com", "Alice Kim", "https://example.com/a.png"))
        self.assertEqual(typed_actor(dict(ALICE, pic="")), Person("alice@example.com", "Alice Kim", None))


class AddAndEdit(ServiceBase):
    """add_pin and edit_pin around limn.pins.edit."""

    def test_add_writes_the_pin_then_emits_its_notices(self):
        """A new pin is stored with the next id, where its file is and the current build; mention and assigned
        notices are emitted after the write, in one call."""
        tags = NoteTags(("bob@example.com",), ["bob@example.com"])
        self.ctx = self.context(note_tags=lambda *a: tags)
        place = LinePlace({"file": str(self.tex), "name": "main.tex", "lo": 2, "hi": 3, "page": 1},
                          frozenset({"file", "lo", "hi", "page"}))
        pin = add_edit.add_pin(self.ctx, self.doc, AddRequest(place, "hi @Bob", assignee="bob@example.com"), ALICE)
        self.assertIsInstance(pin, OpenPin)
        stored = self.pin(1)
        self.assertEqual((stored["at"], stored["file_rel"], stored["pdf_build"], stored["doc"], stored["mentions"]),
                         (STAMP, "main.tex", "pages", "main", ["bob@example.com"]))
        self.assertEqual(self.rec.emitted, [[{"type": "mention", "pin": 1, "to": ["bob@example.com"]},
                                             {"type": "assigned", "pin": 1, "to": ["bob@example.com"]}]])
        self.assertEqual(self.add(), 2)

    def test_an_edit_refusal_writes_nothing_and_notifies_nobody(self):
        """A stale base_rev comes back as StaleEdit; pins.jsonl keeps its bytes and the emit gets no notice."""
        pid = self.add()
        before = self.pins_bytes()
        self.rec.emitted.clear()
        out = add_edit.edit_pin(self.ctx, pid, EditRequest(base_rev=5, note="new"), BOB)
        self.assertIsInstance(out, StaleEdit)
        self.assertEqual(self.pins_bytes(), before)
        self.assertEqual(self.rec.emitted, [[]])

    def test_an_accepted_edit_is_written_in_place(self):
        """A note edit with the current base_rev rewrites the record, bumps rev and records who edited."""
        pid = self.add()
        out = add_edit.edit_pin(self.ctx, pid, EditRequest(base_rev=0, note="new"), BOB)
        self.assertIsInstance(out, OpenPin)
        self.assertEqual((self.pin(pid)["note"], self.pin(pid)["rev"], self.pin(pid)["edited_by"]["login"]),
                         ("new", 1, "bob@example.com"))

    def test_edit_of_a_missing_pin_is_a_named_miss(self):
        """No pin with the id: PinNotFound, nothing written."""
        self.assertEqual(add_edit.edit_pin(self.ctx, 9, EditRequest(base_rev=0, note="x"), BOB), PinNotFound(9))
        self.assertEqual(self.pins_bytes(), b"")


class Transitions(ServiceBase):
    """reply_pin, set_done (close/reopen) and confirm_pin around limn.pins.lifecycle."""

    def test_agent_close_awaits_review_and_tells_the_author(self):
        """An agent's close is a ReviewPin with a review_requested notice to the author; a second close is
        AlreadyClosed and leaves the file as it was."""
        pid = self.add()
        out = transitions.set_done(self.ctx, pid, True, AGENT, reply="fixed")
        self.assertIsInstance(out, ReviewPin)
        self.assertEqual(self.rec.emitted[-1], [{"type": "review_requested", "pin": pid, "to": ["alice@example.com"]}])
        before = self.pins_bytes()
        self.assertIsInstance(transitions.set_done(self.ctx, pid, True, BOB), AlreadyClosed)
        self.assertEqual(self.pins_bytes(), before)

    def test_a_person_reply_on_a_closed_pin_reopens_it(self):
        """A person's untagged reply on a done pin is a reopen: the pin is open again and the author hears reopened."""
        pid = self.add()
        transitions.set_done(self.ctx, pid, True, ALICE)
        out = transitions.reply_pin(self.ctx, pid, "redo please", BOB)
        self.assertIsInstance(out, OpenPin)
        self.assertEqual(self.pin(pid)["thread"][-1]["ev"], "reopen")
        self.assertIn({"type": "reopened", "pin": pid, "to": ["alice@example.com"]}, self.rec.emitted[-1])

    def test_a_full_thread_refuses_the_reply_without_writing(self):
        """With thread_max replies already there the next is ThreadFull and pins.jsonl is unchanged."""
        pid = self.add()
        self.ctx = self.context(thread_max=1)
        self.assertIsInstance(transitions.reply_pin(self.ctx, pid, "one", BOB), OpenPin)
        before = self.pins_bytes()
        self.assertIsInstance(transitions.reply_pin(self.ctx, pid, "two", BOB), ThreadFull)
        self.assertEqual(self.pins_bytes(), before)

    def test_reopen_of_a_missing_pin_is_a_named_miss(self):
        """set_done(done=False) on no pin is PinNotFound."""
        self.assertEqual(transitions.set_done(self.ctx, 7, False, ALICE, reason="why"), PinNotFound(7))

    def test_an_agent_confirm_never_loads_the_store(self):
        """AgentCannotConfirm comes back before the store is read: a store whose re-sync would fail is never asked."""
        def boom(rows):
            """A re-sync that must not run."""
            raise AssertionError("store touched")
        ctx = self.context(store=PinStore(PinFiles(self.state), self.lock, valid, boom, lambda rows: "", Refused))
        self.assertEqual(transitions.confirm_pin(ctx, 1, AGENT), AgentCannotConfirm())

    def test_a_person_confirms_a_pin_awaiting_review(self):
        """Review -> done by a person; confirming again is refused and writes nothing."""
        pid = self.add()
        transitions.set_done(self.ctx, pid, True, AGENT)
        self.assertIsInstance(transitions.confirm_pin(self.ctx, pid, ALICE), DonePin)
        before = self.pins_bytes()
        self.assertNotIsInstance(transitions.confirm_pin(self.ctx, pid, ALICE), DonePin)
        self.assertEqual(self.pins_bytes(), before)


class Claims(ServiceBase):
    """claim_pin and unclaim_pin around limn.pins.lifecycle.claim/unclaim."""

    def test_another_identitys_live_claim_is_refused_without_writing(self):
        """The agent claims; Bob's claim is ClaimedByOther and the file keeps the agent's claim."""
        pid = self.add()
        self.assertIsInstance(claim.claim_pin(self.ctx, pid, AGENT, 30), OpenPin)
        before = self.pins_bytes()
        self.assertIsInstance(claim.claim_pin(self.ctx, pid, BOB, 30), ClaimedByOther)
        self.assertEqual(self.pins_bytes(), before)
        self.assertEqual(self.pin(pid)["claim_until"], T + 30 * 60)

    def test_unclaim_writes_only_when_there_was_a_claim(self):
        """unclaim clears the marker; a second unclaim is NotClaimed with the file unchanged."""
        pid = self.add()
        claim.claim_pin(self.ctx, pid, AGENT, 30)
        self.assertIsInstance(claim.unclaim_pin(self.ctx, pid, BOB), OpenPin)
        self.assertNotIn("claimed_by", self.pin(pid))
        before = self.pins_bytes()
        self.assertIsInstance(claim.unclaim_pin(self.ctx, pid, BOB), NotClaimed)
        self.assertEqual(self.pins_bytes(), before)


class Trash(ServiceBase):
    """drop, restore, the expiry rule, purge and clear."""

    def old_entry(self, pid, days_ago):
        """A Trash entry of pin pid dropped days_ago days before T (local time)."""
        import time as clock
        return {"id": pid, "file": str(self.tex), "lo": 1, "hi": 1,
                "dropped_at": clock.strftime("%Y-%m-%d %H:%M:%S", clock.localtime(T - days_ago * 86400))}

    def test_expiry_is_counted_from_dropped_at(self):
        """An entry expires trash_days after dropped_at; one without a readable dropped_at never expires."""
        fresh, old, unknown = self.old_entry(1, 29), self.old_entry(2, 31), {"id": 3}
        self.assertEqual(trash.unexpired([fresh, old, unknown], 30, T), [fresh, unknown])
        self.assertIsNone(trash.expires_ts(unknown, 30))
        self.assertFalse(trash.expired(unknown, 30, T + 10 ** 9))

    def test_drop_moves_the_pin_to_the_trash_and_restore_brings_it_back(self):
        """drop takes the pin out of pins.jsonl into the Trash and tells its author; restore puts it back, removes it
        from the Trash, and refuses a second restore (NotInTrash) without touching the Trash file."""
        pid = self.add()
        self.assertIsInstance(trash.drop_pin(self.ctx, pid, BOB), TrashedPin)
        self.assertIsNone(self.pin(pid))
        self.assertEqual([r["id"] for r in self.store.read_dropped()[0]], [pid])
        self.assertEqual(self.rec.emitted[-1], [{"type": "dropped", "pin": pid, "to": ["alice@example.com"]}])
        self.assertIsInstance(trash.restore_pin(self.ctx, pid, ALICE), OpenPin)
        self.assertEqual(self.store.read_dropped()[0], [])
        trash_before = self.store.files.dropped.read_bytes()
        self.assertEqual(trash.restore_pin(self.ctx, pid, ALICE), NotInTrash(pid))
        self.assertEqual(self.store.files.dropped.read_bytes(), trash_before)

    def test_restore_of_a_pin_that_is_live_again_is_refused(self):
        """A Trash copy whose id is live is AlreadyLive; both files keep their bytes."""
        pid = self.add()
        self.store.write_dropped([dict(self.pin(pid), dropped_at=STAMP)])
        pins, dropped = self.pins_bytes(), self.store.files.dropped.read_bytes()
        self.assertEqual(trash.restore_pin(self.ctx, pid, ALICE), AlreadyLive(pid))
        self.assertEqual((self.pins_bytes(), self.store.files.dropped.read_bytes()), (pins, dropped))

    def test_purge_trash_drops_expired_entries_and_restarts_the_hourly_clock(self):
        """purge_trash rewrites the Trash without expired entries and returns how many went; maybe_purge_trash waits
        TRASH_CHECK_EVERY_S after any check."""
        self.store.write_dropped([self.old_entry(1, 31), self.old_entry(2, 1)])
        self.assertEqual(trash.purge_trash(self.ctx), 1)
        self.assertEqual([r["id"] for r in self.store.read_dropped()[0]], [2])
        self.assertEqual(self.checked, [T])
        self.assertEqual(trash.maybe_purge_trash(self.ctx), 0)
        later = self.context(epoch=lambda: T + trash.TRASH_CHECK_EVERY_S + 2 * 86400 * 30)
        self.assertEqual(trash.maybe_purge_trash(later), 1)

    def test_purge_pin_is_audited_outside_the_pin_lock(self):
        """A permanent delete removes the entry, emits `purged` and appends the audit line after releasing the lock;
        a pin not in the Trash is NotInTrash with no audit."""
        pid = self.add()
        trash.drop_pin(self.ctx, pid, ALICE)
        self.assertIsInstance(trash.purge_pin(self.ctx, pid, ALICE), TrashedPin)
        self.assertEqual(self.store.read_dropped()[0], [])
        self.assertEqual(self.rec.emitted[-1], [{"type": "purged", "to": [], "pin": pid, "by": {"login": "alice@example.com"}}])
        self.assertEqual(self.rec.audits, [("purged", "alice@example.com", {"pin": pid}, True)])
        self.assertEqual(trash.purge_pin(self.ctx, pid, ALICE), NotInTrash(pid))
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


if __name__ == "__main__":
    unittest.main()
