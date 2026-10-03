"""The viewer's declared API shapes (src/limn/viewer/types/api.d.ts) match what the server answers.

The viewer is type-checked with tsc (docs/handbook/viewer.md §타입 검사), but tsc only trusts the declarations; nothing
in the browser checks them against the server. This test does. Every pin, thread entry and person in the recorded API
answers of tests/data/contract_snapshot*.json (the agent contract, docs/handbook/verification.md §4) must have each of
its fields declared, with a TypeScript type that fits the JSON value, so a field the server adds or retypes fails here
until the declaration follows. A declared field those flows never show must be one the server's record tables
(limn.pins.model) define, so the declaration cannot drift into fields that do not exist.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_types.py
"""

import json
import re
import unittest
from pathlib import Path
from unittest import mock

from limn.administration import serve_documents
from limn.builds.artifacts import BuildOkWithErrors
from limn.pins import model
from limn.platform import files
from limn.sync import rules as sync_rules

from helpers import MINI_PDF, TEX, VIEWER, ps
from helpers_access import ALICE, BOB, AccessBase

API_TYPES = VIEWER / "types" / "api.d.ts"
SNAPSHOTS = [
    Path(__file__).resolve().parents[4] / "tests" / "data" / name
    for name in ("contract_snapshot.json", "contract_snapshot_figure.json")
]
JSON_TYPES = {str: "string", int: "number", float: "number", bool: "boolean"}
# The server tables a declared but unrecorded field may come from, per interface.
SERVER_FIELDS = {
    "Pin": set().union(
        model.CORE_SHAPES, model.CLAIM_SHAPES, model.CLOSE_SHAPES, model.CONFIRMATION_SHAPES, model.DROPPED_SHAPES
    ),
    "ThreadEntry": set(model.THREAD_ENTRY_SHAPES),
}


def interfaces(text: str) -> dict[str, dict[str, str]]:
    """Each `interface Name { field?: type; }` block of a declaration file, as name -> field -> type text."""
    out = {}
    for name, body in re.findall(r"^interface (\w+) \{\n(.*?)^\}", text, re.M | re.S):
        out[name] = dict(re.findall(r"^  (\w+)\??: (.+);$", body, re.M))
    return out


def mismatches(value: object, type_text: str, shapes: dict[str, dict[str, str]], where: str) -> list[str]:
    """Where a JSON value does not fit a declared type: a field the interface lacks, or a value of another JSON type.

    type_text is a primitive (string, number, boolean, null), an interface name, an inline object type, any of those
    with `[]`, or a union of them (`A | null`); an interface's fields are checked against value's keys, recursively."""
    if " | " in type_text:
        tried = [mismatches(value, alt, shapes, where) for alt in type_text.split(" | ")]
        return [] if any(not t for t in tried) else ["%s: %r fits none of %s" % (where, value, type_text)]
    if type_text == "null":
        return [] if value is None else ["%s: %r is not null" % (where, value)]
    if type_text.endswith("[]"):
        if not isinstance(value, list):
            return ["%s: %s is not an array" % (where, type(value).__name__)]
        return [
            m for i, item in enumerate(value) for m in mismatches(item, type_text[:-2], shapes, "%s[%d]" % (where, i))
        ]
    if type_text in shapes:
        if not isinstance(value, dict):
            return ["%s: %s is not an object" % (where, type(value).__name__)]
        fields = shapes[type_text]
        out = ["%s.%s: not declared in %s" % (where, k, type_text) for k in value if k not in fields]
        return out + [
            m for k, v in value.items() if k in fields for m in mismatches(v, fields[k], shapes, where + "." + k)
        ]
    if type_text.startswith("{"):
        return [] if isinstance(value, dict) else ["%s: %s is not an object" % (where, type(value).__name__)]
    if JSON_TYPES.get(type(value)) != type_text:
        return ["%s: %r is not %s" % (where, value, type_text)]
    return []


def recorded_pins() -> list[tuple[str, dict]]:
    """(step, pin) for every pin object in the recorded JSON answers: a list of pins, one pin, or a pin list inside an
    object (the Trash). A pin is an object with an id and a page."""
    out = []
    for path in SNAPSHOTS:
        for entry in json.loads(path.read_text(encoding="utf-8")):
            try:
                body = json.loads(entry["body"])
            except ValueError:
                continue  # pins.md and other text answers
            values = body if isinstance(body, list) else [body, *body.values()] if isinstance(body, dict) else []
            for v in values:
                for item in v if isinstance(v, list) else [v]:
                    if isinstance(item, dict) and "id" in item and "page" in item:
                        out.append((entry["step"], item))
    return out


class DeclaredPinShapes(unittest.TestCase):
    """api.d.ts declares every field the recorded answers carry, with a type that fits, and nothing the server lacks."""

    def setUp(self):
        self.shapes = interfaces(API_TYPES.read_text(encoding="utf-8"))
        self.pins = recorded_pins()

    def test_the_recorded_flows_hold_pins(self):
        """The check reads a real sample: both flows' pins, with threads, claims, closes and figure elements."""
        self.assertGreater(len(self.pins), 20)
        seen = {k for _, p in self.pins for k in p}
        self.assertTrue({"thread", "claimed_by", "close_reply", "el", "dropped_at"} <= seen, seen)

    def test_every_recorded_field_is_declared_with_its_type(self):
        """No recorded pin has a field api.d.ts lacks or a value of another JSON type than declared."""
        found = [m for step, p in self.pins for m in mismatches(p, "Pin", self.shapes, "%s: pin #%s" % (step, p["id"]))]
        self.assertEqual(found, [])

    def test_declared_fields_are_recorded_or_server_fields(self):
        """A Pin or ThreadEntry field the flows never show is one of the server's record fields for it."""
        seen_pin = {k for _, p in self.pins for k in p}
        seen_entry = {k for _, p in self.pins for e in p.get("thread", []) for k in e}
        for name, seen in (("Pin", seen_pin), ("ThreadEntry", seen_entry)):
            with self.subTest(interface=name):
                unseen = set(self.shapes[name]) - seen
                self.assertEqual(sorted(unseen - SERVER_FIELDS[name]), [])

    def test_the_check_catches_each_kind_of_drift(self):
        """A field the declaration lacks, a value of another type, and a nested object's unknown field all fail."""
        pin = dict(self.pins[0][1])
        self.assertEqual(mismatches(pin, "Pin", self.shapes, "p"), [])
        self.assertEqual(
            mismatches({**pin, "colour": "red"}, "Pin", self.shapes, "p"), ["p.colour: not declared in Pin"]
        )
        self.assertEqual(mismatches({**pin, "page": "1"}, "Pin", self.shapes, "p"), ["p.page: '1' is not number"])
        author = {"login": "a", "name": "A", "email": "alice@example.com"}
        self.assertEqual(
            mismatches({**pin, "author": author}, "Pin", self.shapes, "p"), ["p.author.email: not declared in Person"]
        )


PAGE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (417).to_bytes(4, "big") * 2 + b"\x08\x02\x00\x00\x00"
# Declared fields the set-up states below never answer, each with where the server adds it.
UNSEEN = {
    "RebuildAnswer.pull": "only a run with --git-pull pulls before a rebuild (limn.builds.answer)",
}


def sync_records() -> list[dict]:
    """Every sync status and pull record shape the server's producers return, one per outcome and watch state."""
    outcomes = [
        sync_rules.Pulled("a1", "b2"),
        sync_rules.UpToDate("a1"),
        sync_rules.PullSkipped("dirty", "a1"),
        sync_rules.PullFailed("fetch", None),
    ]
    return [
        sync_rules.initial_status(),
        sync_rules.disabled(),
        sync_rules.deferred("2026-09-26 10:00:00"),
        sync_rules.unexpected("2026-09-26 10:00:00"),
        *[sync_rules.after_pull(o, "2026-09-26 10:00:00") for o in outcomes],
    ], [sync_rules.pull_record(o) for o in outcomes]


class DeclaredViewShapes(AccessBase):
    """api.d.ts declares the document, build and people answers as the real handler gives them.

    Three states: one document with an open pin and no build; three documents (a LaTeX file, one in a folder, a
    view-only PDF) with page images and two people who opened the viewer; one document after a build with LaTeX
    errors. The watch's states come from limn.sync.rules itself, since a test run has no remote to pull."""

    def setUp(self):
        super().setUp()
        self.shapes = interfaces(API_TYPES.read_text(encoding="utf-8"))
        self.seen: list[tuple[str, object]] = []

    def answer(self, interface, method, path, headers=None):
        """Call path and keep its body as an instance of interface."""
        code, body = self.call(method, path, headers=headers)
        self.assertEqual(code, 200, (path, body))
        self.seen.append((interface, body))
        return body

    def run_states(self):
        """Answer every view the viewer reads in each of the three states (see the class docstring)."""
        self.pin_id()
        self.answer("Meta", "GET", "/api/meta")
        self.answer("Meta", "GET", "/api/meta?light=1")
        self.answer("BuildStatus", "GET", "/api/build?log=1")
        self.answer("DocsAnswer", "GET", "/api/docs")
        self.answer("PeopleAnswer", "GET", "/api/people")

        def built(D=None, force=False):
            """A finished build with two LaTeX errors, one without a line."""
            errors = [{"line": 3, "msg": "Undefined control sequence"}, {"line": None, "msg": "x"}]
            return BuildOkWithErrors(errors, "log a\nlog b", 0.5, None, 1.0, None, "-", "", 1)

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=built):
            self.answer("RebuildAnswer", "POST", "/api/rebuild")
        self.answer("BuildStatus", "GET", "/api/build?log=1")
        self.answer("Meta", "GET", "/api/meta")

        (self.src / "rr").mkdir()
        (self.src / "rr" / "rr.tex").write_text(TEX, encoding="utf-8")
        (self.src / "review.pdf").write_bytes(MINI_PDF)
        docs = serve_documents.make_docs(
            ["ms=본문:main.tex", "rr=답변서:rr/rr.tex", "rv=리뷰어:review.pdf"], self.src, ps.APP.C
        )
        ps.APP.set_docs(docs)
        self.addCleanup(ps.APP.set_docs, None)
        for D in docs:
            pages = D.dir / "pages-20260101000000"
            pages.mkdir(parents=True, exist_ok=True)
            for i in (1, 2):
                (pages / ("page-%d.png" % i)).write_bytes(PAGE_PNG)
            (pages / D.pdf_name).write_bytes(MINI_PDF)
            files.atomic_write(D.dir / "pages.cur", pages.name)
        alice = {**ALICE, "Tailscale-User-Profile-Pic": "https://example.com/alice.png"}  # a tailnet photo
        self.answer("Meta", "GET", "/api/meta?doc=ms", headers=alice)
        self.answer("Meta", "GET", "/api/meta?doc=rv&light=1", headers=BOB)
        self.answer("DocsAnswer", "GET", "/api/docs")
        self.answer("PeopleAnswer", "GET", "/api/people", headers=alice)
        statuses, pulls = sync_records()
        self.seen += [("SyncStatus", r) for r in statuses] + [("PullRecord", r) for r in pulls]

    def test_every_answered_field_is_declared_with_its_type(self):
        """No answer in the three states, and no record the sync producers return, has an undeclared field or a value
        of another JSON type than declared."""
        self.run_states()
        found = [
            m
            for i, (name, body) in enumerate(self.seen)
            for m in mismatches(body, name, self.shapes, "%d %s" % (i, name))
        ]
        self.assertEqual(found, [])

    def test_declared_fields_are_answered_or_explained(self):
        """Each field these interfaces declare is a key of some answer of its interface, or is in UNSEEN with the reason
        the set-up states cannot show it; the states show pages, several documents, people and LaTeX errors."""
        self.run_states()
        seen: dict[str, set[str]] = {}

        def collect(value, type_text):
            """Record the keys value shows for each declared interface it is (or holds) an instance of."""
            for alt in type_text.split(" | "):
                alt = alt[:-2] if alt.endswith("[]") else alt
                if alt in self.shapes:
                    for item in value if isinstance(value, list) else [value]:
                        if isinstance(item, dict):
                            seen.setdefault(alt, set()).update(item)
                            for k, v in item.items():
                                if k in self.shapes[alt]:
                                    collect(v, self.shapes[alt][k])

        for name, body in self.seen:
            collect(body, name)
        views = ["Meta", "BuildStatus", "DocsAnswer", "PeopleAnswer", "RebuildAnswer", "SyncStatus", "PullRecord"]
        views += ["Me", "PersonSeen", "PageImage", "LatexError", "BuildProgress", "LastBuild", "DocEntry"]
        missing = sorted(
            "%s.%s" % (name, f) for name in views for f in self.shapes[name] if f not in seen.get(name, set())
        )
        self.assertEqual([m for m in missing if m not in UNSEEN], [])
        self.assertEqual(sorted(set(UNSEEN) - set(missing)), [])  # an explained field the states now show leaves UNSEEN
        self.assertTrue(seen["PageImage"] and seen["LatexError"] and seen["PersonSeen"], seen)
