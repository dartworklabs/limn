"""Real temporary pin storage, frozen time and observable notice/audit sinks for feature tests."""

import tempfile
import threading
import unittest
from pathlib import Path

from limn.builds import pin_build_queries
from limn.pins.context import PinContext
from limn.pins.editing import service as add_edit
from limn.pins.editing.rules import AddRequest, LinePlace
from limn.pins.location.lookup import PinLocation
from limn.pins.mentions import NoteTags
from limn.pins.model import TrashedPin, parse_pin
from limn.pins.record import Broken
from limn.pins.store import PinFiles, PinStore
from limn.platform.files import ManuscriptFile, file_in_tree
from limn.runtime.documents import Doc, RunPaths
from limn.security.access import LOCAL_ACTOR

from helpers import (
    find_record,
)
from helpers_access import ALICE_ACTOR, BOB_ACTOR
from helpers_authority import post_authority

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
        self.doc = Doc("main", "Main", paths=RunPaths(self.ms, self.tex, self.state), legacy=True)

    def tearDown(self):
        """Remove the temp folder."""
        self.tmp.cleanup()

    def context(self, **over):
        """A PinContext over this test's store and recorder, with build queries (and their map cache) made for this
        call alone; keyword arguments replace single collaborators."""
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
            builds=pin_build_queries(),
        )
        fields.update(over)
        return PinContext(**fields)

    def locate(self, r):
        """Where a record's file is: under the manuscript folder, else None (outside the tree)."""
        p = Path(str(r.get("file") or ""))
        source = file_in_tree(str(p), self.ms, self.state)
        return PinLocation(p.relative_to(self.ms).as_posix(), source) if isinstance(source, ManuscriptFile) else None

    def add(self, actor=ALICE_ACTOR, note="n", lo=1, hi=2):
        """A new open line pin by actor in main.tex -> its id."""
        place = LinePlace(
            {"file": str(self.tex), "name": "main.tex", "lo": lo, "hi": hi, "page": 1},
            frozenset({"file", "lo", "hi", "page"}),
        )
        return add_edit.add_pin(
            self.ctx, self.doc, AddRequest(place, note), post_authority(self.ctx.store, actor, "add", self.doc)
        ).record["id"]

    def pins_bytes(self):
        """pins.jsonl as stored now (b'' when missing)."""
        f = self.store.files.pins_jsonl
        return f.read_bytes() if f.exists() else b""

    def pin(self, pid):
        """The stored record of pin pid."""
        return find_record(self.store.read_pins()[0], pid)
