"""Where pin files are, judged once per file for one computation (limn.pins.location.lookup.Locations).

A listing, a rendering of pins.md and a re-sync ask where the file of every pin is. Locations answers each path
once and remembers the answer for that one computation. These tests hold three things: the answer for every path is
the one locate_file gave pin by pin; nothing remembered outlives its computation or stands in for the checked read;
and the work a listing spends on judging paths, and the work one pin's answer spends on other pins, no longer grow
with the number of pins.

Run: uv run pytest -q src/limn/pins/tests/test_locations.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hypothesis import given, settings, strategies as st

from limn.pins.listing import projection
from limn.pins.location import lookup
from limn.pins.location.lookup import Locations, locate_file
from limn.pins.location.mapping import pin_rel_path
from limn.pins.model import parse_pin
from limn.platform import files
from limn.platform.files import PATH_MAX_CHARS
from limn.security.access import LOCAL_ACTOR

from helpers import Base, ps, records, write_records
from helpers_access import LOOPBACK_AGENT
from helpers_authority import post_authority


def reference_part(p, root, state):
    """The tree rule with all three paths resolved on every call - the rule before bounds existed, the oracle here."""
    try:
        base = root.resolve()
        real = p.resolve()
        rel = real.relative_to(base)
        held = state.resolve()
    except (ValueError, OSError, RuntimeError):
        return None
    if any(part.startswith(".") for part in rel.parts):
        return None
    if held.is_relative_to(base) and real.is_relative_to(held):
        return None
    return rel


def reference_location(file, file_rel, root, state, doc):
    """locate_file as it stood when every pin was judged on its own, as (rel, shown path, resolved path) or None: the
    oracle for Locations. It resolves the root and the state folder at every step and shares only the pure rule
    (pin_rel_path, which reads no files) with the code under test."""
    if not isinstance(file, str) or not file:
        return None
    try:
        under = Path(file).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError, RuntimeError):
        under = None
    scope = ""
    if under is None and doc is not None:
        try:
            scope = doc.src.resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError, RuntimeError):
            scope = ""
        scope = "" if scope == "." else scope
    rel = pin_rel_path(
        file,
        file_rel,
        under,
        lambda t: (root / t).is_file() and reference_part(root / t, root, state) is not None,
        scope,
    )
    if rel is None:
        return None
    named = str(root / rel)
    if "\x00" in named or len(named) > PATH_MAX_CHARS:
        return None
    part = reference_part(Path(named), root, state)
    if part is None:
        return None
    out = root / part
    try:
        resolved = out.resolve()
        if reference_part(resolved, root.resolve(), state.resolve()) is None or not resolved.is_file():
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return rel, out, resolved


def located(found):
    """A PinLocation in reference_location's form, so the two compare as values."""
    return None if found is None else (found.rel, found.path, found.source._resolved)


# What a stored `file` may be: where the manuscript is now, where it was on another machine, and places the rule
# refuses. {root} is the manuscript root of the tree under test.
FILES = (
    "{root}/main.tex",
    "{root}/sections/intro.tex",
    "{root}/figs/sections/intro.tex",
    "{root}/gone.tex",
    "{root}/.git/config",
    "{root}/limn-state/audit.jsonl",
    "{root}/to-secret",
    "{root}/to-outside/secret.tex",
    "{root}/to-git/config",
    "{root}/to-main",
    "/old/place/main.tex",
    "/old/place/paper/sections/intro.tex",
    "/old/place/intro.tex",
    "/old/place/.git/config",
    "/old/place/.git/main.tex",
    "/old/place/limn-state/audit.jsonl",
    "/old/place/to-secret",
    "/old/place/gone.tex",
    "/old/pl\x00ace/main.tex",
    "main.tex",
    "",
    None,
    7,
)
# What a stored `file_rel` may be, well-formed or left by a hand edit.
RELS = (
    None,
    "main.tex",
    "sections/intro.tex",
    "intro.tex",
    "paper/sections/intro.tex",
    ".git/config",
    "to-secret",
    "gone.tex",
    "../main.tex",
    "/main.tex",
    "",
    7,
    ["main.tex"],
    {"a": 1},
)
DOCS = (None, "", "figs", "sections", "nowhere", "to-outside")


class Tree(unittest.TestCase):
    """One manuscript with a document folder holding a same-named file, the places the tree rule refuses, and a
    folder beside it that is outside."""

    @classmethod
    def setUpClass(cls):
        """Build the tree once: main.tex, sections/intro.tex, figs/sections/intro.tex, .git, a state folder inside
        the root, and links to a dot folder, to the folder outside and to a file inside."""
        cls.tmp = tempfile.TemporaryDirectory()
        top = Path(cls.tmp.name).resolve()
        cls.root, cls.outside, cls.state = top / "ms", top / "outside", top / "ms" / "limn-state"
        for folder in (
            cls.root / "sections",
            cls.root / "figs" / "sections",
            cls.root / ".git",
            cls.state,
            cls.outside,
        ):
            folder.mkdir(parents=True)
        for file in (
            cls.root / "main.tex",
            cls.root / "sections" / "intro.tex",
            cls.root / "figs" / "sections" / "intro.tex",
            cls.root / ".git" / "config",
            cls.root / ".git" / "main.tex",
            cls.state / "audit.jsonl",
            cls.outside / "secret.tex",
        ):
            file.write_text("x\n", encoding="utf-8")
        os.symlink(cls.root / ".git", cls.root / "to-git")
        os.symlink(cls.outside, cls.root / "to-outside")
        os.symlink(cls.outside / "secret.tex", cls.root / "to-secret")
        os.symlink(cls.root / "main.tex", cls.root / "to-main")

    @classmethod
    def tearDownClass(cls):
        """Remove the tree."""
        cls.tmp.cleanup()

    def stored(self, file):
        """A FILES entry as a stored value: its {root} filled in, anything that is not a string as it is."""
        return file.format(root=self.root) if isinstance(file, str) else file

    def doc(self, folder):
        """A document whose build root is root / folder, or None for a pin whose document is not configured."""
        return None if folder is None else SimpleNamespace(src=self.root / folder)


class EveryPathIsJudgedAsBefore(Tree):
    """Asked once or after any other paths, a stored path is placed where the pin-by-pin rule placed it."""

    @settings(max_examples=250, deadline=None)
    @given(
        asks=st.lists(
            st.tuples(st.sampled_from(FILES), st.sampled_from(RELS), st.sampled_from(DOCS)), min_size=1, max_size=12
        )
    )
    def test_one_value_answers_a_run_of_asks_like_the_rule(self, asks):
        """Whatever paths one Locations value was asked about before, and in whatever order, each answer is the
        reference's for that path alone - and asking again gives the same answer. locate_file, one judgment made
        now, agrees too."""
        one = Locations(self.root, self.state)
        for file, file_rel, folder in asks + asks[::-1]:
            stored, doc = self.stored(file), self.doc(folder)
            want = reference_location(stored, file_rel, self.root, self.state, doc)
            self.assertEqual(located(one.file(stored, file_rel, doc)), want)
            self.assertEqual(located(locate_file(stored, file_rel, self.root, self.state, doc)), want)

    def test_every_listed_combination_once(self):
        """The whole table of stored files, file_rels and document folders, each asked of one shared value: no
        combination is left to the generator's luck, and the table is not one that places nothing."""
        one = Locations(self.root, self.state)
        placed = set()
        for file in FILES:
            for file_rel in RELS:
                for folder in DOCS:
                    stored, doc = self.stored(file), self.doc(folder)
                    want = reference_location(stored, file_rel, self.root, self.state, doc)
                    self.assertEqual(located(one.file(stored, file_rel, doc)), want, (file, file_rel, folder))
                    if want is not None:
                        placed.add(want[0])
        self.assertEqual(placed, {"main.tex", "sections/intro.tex", "figs/sections/intro.tex"})

    def test_a_refused_tail_is_skipped_for_the_next_one(self):
        """A moved record whose longest existing tail lies under a dot folder is not given up on: that tail is
        skipped and the next one that is in the tree places the pin."""
        one = Locations(self.root, self.state)
        self.assertTrue((self.root / ".git" / "main.tex").is_file())
        self.assertEqual(one.file("/old/place/.git/main.tex", None, None).rel, "main.tex")
        self.assertEqual(one.file("/old/place/to-git/main.tex", None, None).rel, "main.tex")

    def test_a_record_and_a_pin_are_asked_with_their_own_file_rel(self):
        """The two ways production asks - by a record's fields and by a stored pin - pass the stored file_rel on: a
        record whose file_rel names a file that is gone is placed there by rule 2, where the tail guess alone would
        place it on another file of the same name."""
        stored = "/old/place/paper/sections/intro.tex"
        for file_rel, rel in ((None, "sections/intro.tex"), ("paper/sections/intro.tex", None)):
            with self.subTest(file_rel=file_rel):
                want = reference_location(stored, file_rel, self.root, self.state, None)
                self.assertEqual(None if want is None else want[0], rel)
                record = {"id": 1, "file": stored, "lo": 1, "hi": 1, "page": 1, "note": "n"}
                if file_rel is not None:
                    record["file_rel"] = file_rel
                one = Locations(self.root, self.state)
                self.assertEqual(located(one.record(record, None)), want)
                self.assertEqual(located(one.pin(parse_pin(record), None)), want)
        region = parse_pin({"id": 2, "pdf": "/x/a.pdf", "page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "n"})
        self.assertIsNone(Locations(self.root, self.state).pin(region, None))

    def test_a_documents_folder_is_found_under_any_root_that_resolves(self):
        """doc_scope answers '' for a root that cannot be resolved, whatever the reason - also a name with a NUL."""
        doc = self.doc("figs")
        self.assertEqual(lookup.doc_scope(doc, self.root), "figs")
        self.assertEqual(lookup.doc_scope(doc, Path("/limn-test\x00unresolvable")), "")
        self.assertEqual(lookup.doc_scope(None, self.root), "")

    def test_a_moved_record_is_searched_in_its_own_documents_folder(self):
        """Two documents share one value: the same stored path of a moved checkout is placed in each pin's own
        document folder, so remembering one document's answer never answers for the other."""
        one = Locations(self.root, self.state)
        old = "/old/place/sections/intro.tex"
        self.assertEqual(one.file(old, None, self.doc("figs")).rel, "figs/sections/intro.tex")
        self.assertEqual(one.file(old, None, self.doc("")).rel, "sections/intro.tex")
        self.assertEqual(one.file(old, None, None).rel, "sections/intro.tex")
        self.assertEqual(one.file(old, None, self.doc("figs")).rel, "figs/sections/intro.tex")

    def test_the_places_the_tree_refuses_are_never_located(self):
        """A stored path into a dot folder, the state folder or out of the tree through a link is not located, by
        its own path or by a moved record's tail - the negative cases by name."""
        one = Locations(self.root, self.state)
        for file, file_rel in (
            (str(self.root / ".git" / "config"), None),
            (str(self.root / "to-git" / "config"), None),
            (str(self.state / "audit.jsonl"), None),
            (str(self.root / "to-secret"), None),
            (str(self.root / "to-outside" / "secret.tex"), None),
            (str(self.outside / "secret.tex"), None),
            ("/old/place/.git/config", ".git/config"),
            ("/old/place/.git/config", None),
            ("/old/place/limn-state/audit.jsonl", "limn-state/audit.jsonl"),
            ("/old/place/to-secret", "to-secret"),
            ("/old/place/to-secret", None),
        ):
            with self.subTest(file=file, file_rel=file_rel):
                self.assertIsNone(one.file(file, file_rel, None))

    def test_a_tree_that_cannot_be_resolved_locates_nothing(self):
        """A state folder or a root that cannot be resolved places no path, as the rule refused every path then."""
        unresolvable = Path("/limn-test\x00unresolvable")
        for root, state in ((self.root, unresolvable), (unresolvable, self.state)):
            with self.subTest(root=root.name):
                self.assertIsNone(reference_location(str(self.root / "main.tex"), None, root, state, None))
                self.assertIsNone(Locations(root, state).file(str(self.root / "main.tex"), None, None))
                self.assertIsNone(Locations(root, state).file("/old/place/main.tex", "main.tex", None))


class WhatIsRememberedIsNotPermission(unittest.TestCase):
    """A remembered location lasts one computation and never reads a file the tree does not hold."""

    def setUp(self):
        """A manuscript with one file and a folder beside it holding a file that is not the manuscript's."""
        self.tmp = tempfile.TemporaryDirectory()
        top = Path(self.tmp.name).resolve()
        self.root, self.outside, self.state = top / "ms", top / "outside", top / "state"
        for folder in (self.root, self.outside, self.state):
            folder.mkdir()
        self.main = self.root / "main.tex"
        self.main.write_text("manuscript line\n", encoding="utf-8")
        (self.outside / "secret.tex").write_text("secret line\n", encoding="utf-8")

    def tearDown(self):
        """Remove the folders."""
        self.tmp.cleanup()

    def swap_for_a_link_out(self):
        """Replace the manuscript file with a link to the file outside the tree."""
        self.main.unlink()
        os.symlink(self.outside / "secret.tex", self.main)

    def test_a_fresh_value_sees_a_file_replaced_by_a_link(self):
        """The next computation judges the tree as it is then: a file replaced by a link out of the tree after one
        value located it is not located by a new value."""
        self.assertIsNotNone(Locations(self.root, self.state).file(str(self.main), None, None))
        self.swap_for_a_link_out()
        self.assertIsNone(Locations(self.root, self.state).file(str(self.main), None, None))

    def test_a_remembered_location_reads_nothing_through_a_link_put_in_its_place(self):
        """Within one computation the place is remembered, but the read is checked at the read: after the file is
        replaced by a link out of the tree, the remembered location's handle gives no line of the outside file."""
        one = Locations(self.root, self.state)
        before = one.file(str(self.main), None, None)
        self.assertEqual(before.source.snapshot()[0], ["manuscript line"])
        self.swap_for_a_link_out()
        again = one.file(str(self.main), None, None)
        self.assertIs(again, before)
        self.assertEqual(again.source.snapshot()[0], [])
        with self.assertRaises(files.ManuscriptReadError):
            again.source.snapshot_checked()


def lines_run(module, call):
    """How many lines of `module` run while call() does: a count of work that a busy machine does not change, where
    a clock would (docs/handbook/verification.md §불안정한 테스트). Returns (count, call's result)."""
    wanted = module.__file__
    count = 0

    def tracer(frame, event, _arg):
        nonlocal count
        if frame.f_code.co_filename != wanted:
            return None
        count += event == "line"
        return tracer

    sys.settrace(tracer)
    try:
        result = call()
    finally:
        sys.settrace(None)
    return count, result


class WorkDoesNotGrowWithThePins(Base):
    """Through the run's composition: judging paths costs per file, and one pin's answer costs one pin."""

    def fill(self, count):
        """Leave `count` open line pins on main.tex, on ranges that repeat (so pins overlap) and with a note each."""
        rows = records(ps.APP.snapshot_pins())
        base = dict(rows[0]) if rows else None
        if base is None:
            self.add(4, 5)
            base = dict(records(ps.APP.snapshot_pins())[0])
        made = []
        for pid in range(1, count + 1):
            lo = 4 + pid % 3
            row = {**base, "id": pid, "lo": lo, "hi": lo + 1, "note": "request %d" % pid}
            made.append({**row, "file": str(self.main), "file_rel": "main.tex"})
        write_records(made)

    def judging_lines(self, call):
        """The lines of the tree rule (limn.platform.files) that run during call(), and its result."""
        return lines_run(files, call)

    def test_a_listing_judges_one_file_once_however_many_pins_name_it(self):
        """GET /api/pins?all=1 over pins that all name one file runs the tree rule the same number of lines for 40
        pins as for 80: where the file is is judged once, not once per pin and per computed field."""
        self.fill(40)
        small, first = self.judging_lines(lambda: ps.APP.pin_listing.list_payload(True))
        self.fill(80)
        large, second = self.judging_lines(lambda: ps.APP.pin_listing.list_payload(True))
        self.assertEqual((len(first), len(second)), (40, 80))
        self.assertGreater(small, 0)
        self.assertEqual(large, small)

    def test_rendering_pins_md_judges_one_file_once(self):
        """GET /pins.md, and the rendering every write does, runs the tree rule the same number of lines for 40 pins
        as for 80."""
        self.fill(40)
        small, first = self.judging_lines(
            lambda: ps.APP.pin_markdown.current_text("http://127.0.0.1:1", LOOPBACK_AGENT)
        )
        self.fill(80)
        large, second = self.judging_lines(
            lambda: ps.APP.pin_markdown.current_text("http://127.0.0.1:1", LOOPBACK_AGENT)
        )
        self.assertIn("request 40", first)
        self.assertIn("request 80", second)
        self.assertGreater(small, 0)
        self.assertEqual(large, small)

    def test_a_resync_judges_one_file_once(self):
        """The re-sync before every write runs the path rule of the location module in proportion to the files, not
        the pins: twice the pins on one file run the tree rule the same number of lines."""
        self.fill(40)
        small, _ = self.judging_lines(lambda: ps.APP.sync_all(ps.APP.snapshot_pins()))
        self.fill(80)
        large, _ = self.judging_lines(lambda: ps.APP.sync_all(ps.APP.snapshot_pins()))
        self.assertGreater(small, 0)
        self.assertEqual(large, small)

    def test_two_files_cost_two_judgments_not_one_per_pin(self):
        """The count follows the files: the same pins spread over two files run the tree rule more than on one file,
        and still the same for twice the pins. The second file costs less than the first, since the root and the
        state folder are resolved once for the listing and not once per file."""
        other = self.src / "other.tex"
        other.write_text(self.main.read_text(encoding="utf-8"), encoding="utf-8")

        def spread(count):
            self.fill(count)
            rows = [dict(r) for r in records(ps.APP.snapshot_pins())]
            for r in rows[::2]:
                r["file"], r["file_rel"] = str(other), "other.tex"
            write_records(rows)
            return self.judging_lines(lambda: ps.APP.pin_listing.list_payload(True))[0]

        self.fill(40)
        one_file = self.judging_lines(lambda: ps.APP.pin_listing.list_payload(True))[0]
        two_small, two_large = spread(40), spread(80)
        self.assertGreater(two_small, one_file)
        self.assertLess(two_small, 2 * one_file)
        self.assertEqual(two_large, two_small)

    def test_one_pins_answer_computes_one_pins_view(self):
        """GET /api/pins/<id> runs the record projection (limn.pins.listing.projection) the same number of lines
        whether 40 or 80 pins are stored: the other pins' shown records, estimates and marks are not computed."""
        self.fill(40)
        small, first = lines_run(projection, lambda: ps.APP.pin_listing.pin_payload(7))
        self.fill(80)
        large, second = lines_run(projection, lambda: ps.APP.pin_listing.pin_payload(7))
        self.assertEqual((first["id"], second["id"]), (7, 7))
        self.assertGreater(small, 0)
        self.assertEqual(large, small)

    def test_one_documents_list_computes_that_documents_views(self):
        """GET /api/pins?doc=<key> runs the record projection for the listed document's pins alone: pins of another
        document, however many, add no line."""
        self.fill(40)
        key = ps.APP.docs[0].key
        small, first = lines_run(projection, lambda: ps.APP.pin_listing.list_payload(True, key))
        rows = [dict(r) for r in records(ps.APP.snapshot_pins())]
        write_records(rows + [{**rows[0], "id": 1000 + i, "doc": "elsewhere"} for i in range(40)])
        large, second = lines_run(projection, lambda: ps.APP.pin_listing.list_payload(True, key))
        self.assertEqual(len(ps.APP.pin_listing.list_payload(True)), 80)
        self.assertEqual((len(first), len(second)), (40, 40))
        self.assertEqual(large, small)


class TheAnswersAreTheListsAnswers(Base):
    """One pin's answer and one document's list are the full list's records, byte for byte."""

    def setUp(self):
        """Pins of every kind the list computes something for: overlapping open pins, a closed one, a pin with a
        thread, one whose file is gone, one of another document and one stored under a moved checkout's path."""
        super().setUp()
        self.add(4, 9, note="outer")
        self.add(4, 5, note="inner")
        self.add(8, 9, note="tail")
        rows = [dict(r) for r in records(ps.APP.snapshot_pins())]
        rows[2]["done"] = True
        rows[2]["done_at"] = "2026-01-01 00:00"
        rows.append({**rows[0], "id": 11, "file": str(self.src / "gone.tex"), "file_rel": "gone.tex"})
        rows.append({**rows[0], "id": 12, "doc": "elsewhere"})
        rows.append({**rows[1], "id": 13, "file": "/old/place/ms/main.tex", "file_rel": "main.tex"})
        rows.append({**rows[1], "id": 14, "file": "/old/place/ms/main.tex"})
        rows[-1].pop("file_rel", None)
        write_records(rows)

    def as_bytes(self, value):
        """A JSON answer as the bytes the route sends, so key order counts."""
        return json.dumps(value, ensure_ascii=False).encode()

    def test_each_pin_alone_is_its_record_of_the_full_list(self):
        """For every stored pin, GET /api/pins/<id> is the record of that id in the list of all pins, key for key
        and in the same order; an id no pin has is the named miss."""
        full = ps.APP.pin_listing.list_payload(True)
        self.assertEqual(len(full), 7)
        for want in full:
            with self.subTest(pin=want["id"]):
                self.assertEqual(self.as_bytes(ps.APP.pin_listing.pin_payload(want["id"])), self.as_bytes(want))
        self.assertEqual(type(ps.APP.pin_listing.pin_payload(999)).__name__, "PinNotFound")

    def test_one_documents_list_is_the_full_list_filtered(self):
        """For every document key, with and without closed pins, the scoped list is the full list's records of
        that document in order."""
        for allp in (True, False):
            full = ps.APP.pin_listing.list_payload(allp)
            for key in sorted({r["doc"] for r in ps.APP.pin_listing.list_payload(True)} | {"none"}):
                with self.subTest(allp=allp, doc=key):
                    scoped = ps.APP.pin_listing.list_payload(allp, key)
                    self.assertEqual(self.as_bytes(scoped), self.as_bytes([r for r in full if r["doc"] == key]))

    def test_a_pin_keeps_its_overlaps_with_pins_that_are_not_listed(self):
        """The relations are still those over every live pin: one pin's answer names the pins it overlaps."""
        one = ps.APP.pin_listing.pin_payload(1)
        self.assertEqual(
            {rel["id"] for rel in one["rel"]}, {r["id"] for r in ps.APP.pin_listing.list_payload(True)[0]["rel"]}
        )
        self.assertIn(2, {rel["id"] for rel in one["rel"]})


class TheNextRequestJudgesAgain(Base):
    """Nothing about a file's place is kept from one request to the next."""

    def test_a_listing_after_the_file_became_a_link_out_does_not_place_it(self):
        """A pin's file replaced by a link out of the manuscript between two listings is placed by the first and
        not by the second: its answer carries no rel_path, and pins.md omits the stored quote."""
        quote = "First paragraph"
        lines = self.main.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[3] = quote + " " + "x" * 650 + "\n"
        self.main.write_text("".join(lines), encoding="utf-8")
        pid = self.add(4, 4, note="quoted")
        rows = [dict(r) for r in records(ps.APP.snapshot_pins())]
        rows[0]["quote"] = quote
        write_records(rows)
        base = "http://127.0.0.1:1"
        self.assertEqual(ps.APP.pin_listing.pin_payload(pid)["rel_path"], "main.tex")
        self.assertIn(f"«{quote}» quoted", ps.APP.pin_markdown.current_text(base, LOOPBACK_AGENT))
        outside = Path(self.tmp.name).resolve() / "outside.tex"
        outside.write_text("x\n" * 3 + "S" * 650 + "\n", encoding="utf-8")
        self.main.unlink()
        os.symlink(outside, self.main)
        self.assertNotIn("rel_path", ps.APP.pin_listing.pin_payload(pid))
        self.assertNotIn("rel_path", ps.APP.pin_listing.list_payload(True)[0])
        rendered = ps.APP.pin_markdown.current_text(base, LOOPBACK_AGENT)
        self.assertNotIn(f"«{quote}»", rendered)
        self.assertIn("| quoted |", rendered)


class EveryCallSiteJudgesAgain(Base):
    """Each place that takes a view of the pins' files takes a fresh one: nothing is kept on the run."""

    def link_out(self):
        """Replace the manuscript file with a link to a file outside the manuscript."""
        outside = Path(self.tmp.name).resolve() / "outside.tex"
        outside.write_text("x\n", encoding="utf-8")
        self.main.unlink()
        os.symlink(outside, self.main)

    def test_a_change_responses_pin_is_judged_when_it_is_shown(self):
        """The record a write answers with (public) is placed by the tree as it is at that answer, not as an
        earlier answer saw it."""
        self.add(4, 5)
        record = records(ps.APP.snapshot_pins())[0]
        self.assertEqual(ps.APP.public(record)["rel_path"], "main.tex")
        self.link_out()
        self.assertNotIn("rel_path", ps.APP.public(record))

    def test_the_trash_list_is_judged_at_each_listing(self):
        """GET /api/pins/dropped places each entry's file at that listing."""
        pid = self.add(4, 5)
        ps.APP.pin_trash.drop_pin(pid, post_authority(ps.APP.pin_trash.context().store, dict(LOCAL_ACTOR), "drop", pid))
        self.assertEqual(ps.APP.pin_listing.dropped_payload()[0]["rel_path"], "main.tex")
        self.link_out()
        self.assertNotIn("rel_path", ps.APP.pin_listing.dropped_payload()[0])

    def test_a_maintenance_pass_watches_the_files_as_they_are_at_that_pass(self):
        """The files a pass watches are found at that pass: a pin's file moved to another name between two passes is
        watched under its new place by the second."""
        self.add(4, 5)
        self.assertIn(self.main, ps.APP.maintenance_files())
        moved = self.src / "moved"
        moved.mkdir()
        self.main.rename(moved / "main.tex")
        rows = [dict(r) for r in records(ps.APP.snapshot_pins())]
        rows[0]["file"] = "/old/place/moved/main.tex"
        rows[0].pop("file_rel", None)
        write_records(rows)
        self.assertIn(moved / "main.tex", ps.APP.maintenance_files())
        (moved / "main.tex").rename(self.main)
        self.assertNotIn(moved / "main.tex", ps.APP.maintenance_files())
        self.assertIn(self.main, ps.APP.maintenance_files())


class OddRecordsInTheScopedAnswers(Base):
    """Records a hand edit or an old version left behind get the full list's answers too."""

    def test_a_record_without_a_doc_field_is_listed_under_the_first_document(self):
        """A legacy record has no doc and belongs to the first document: the scoped list of that document holds it,
        as the full list says its doc is that key."""
        self.add(4, 5)
        rows = [dict(r) for r in records(ps.APP.snapshot_pins())]
        legacy = {**rows[0], "id": 7}
        legacy.pop("doc", None)
        write_records(rows + [legacy])
        key = ps.APP.docs[0].key
        full = ps.APP.pin_listing.list_payload(True)
        self.assertEqual([r["doc"] for r in full], [key, key])
        self.assertNotIn("doc", records(ps.APP.snapshot_pins())[1])
        self.assertEqual(ps.APP.pin_listing.list_payload(True, key), full)
        self.assertEqual(ps.APP.pin_listing.list_payload(True, "other"), [])

    def test_an_id_the_wire_cannot_carry_is_no_pins_answer(self):
        """A stored id too large for the wire is shown as null in the list, so asking for that number finds no pin -
        as picking it out of the full list never did."""
        self.add(4, 5)
        rows = [dict(r) for r in records(ps.APP.snapshot_pins())]
        huge = 10**400
        write_records(rows + [{**rows[0], "id": huge}])
        stored = [r["id"] for r in records(ps.APP.snapshot_pins())]
        if huge not in stored:
            self.skipTest("the store does not keep an id this large")
        self.assertIsNone(ps.APP.pin_listing.list_payload(True)[1]["id"])
        self.assertEqual(type(ps.APP.pin_listing.pin_payload(huge)).__name__, "PinNotFound")
        self.assertEqual(ps.APP.pin_listing.pin_payload(rows[0]["id"])["id"], rows[0]["id"])


class Keys(unittest.TestCase):
    """What a judgment is remembered by."""

    def test_a_file_rel_that_is_no_string_shares_the_key_of_none(self):
        """A hand-edited file_rel that is a list or an object cannot be a dictionary key and reads as no file_rel."""
        for odd in (["main.tex"], {"a": 1}, 7, None):
            with self.subTest(file_rel=repr(odd)):
                self.assertIsNone(lookup._rel_key(odd))
        self.assertEqual(lookup._rel_key("main.tex"), "main.tex")


if __name__ == "__main__":
    unittest.main()
