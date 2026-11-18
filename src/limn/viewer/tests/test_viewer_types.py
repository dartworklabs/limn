"""The viewer's declared API shapes (src/limn/viewer/types/api.d.ts) match what the server answers.

The viewer is type-checked with tsc (docs/handbook/viewer.md §타입 검사), but tsc only trusts the declarations; nothing
in the browser checks them against the server. This test does. Every pin, thread entry and person in the recorded API
answers of tests/data/contract_snapshot*.json and verdict_snapshot.json (the agent contract, docs/handbook/verification.md §4) must have each of
its fields declared, with a TypeScript type that fits the JSON value, so a field the server adds or retypes fails here
until the declaration follows. A declared field those flows never show must be one the server's record tables
(limn.pins.model) define, so the declaration cannot drift into fields that do not exist.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_types.py
"""

import json
import re
import shutil
import unittest
from pathlib import Path
from unittest import mock

from limn.administration import serve_documents
from limn.builds import values as build_values
from limn.builds.artifacts import BuildOkWithErrors
from limn.documents import http as documents_http, source as document_source
from limn.pins import model
from limn.pins.location import mapping, range as ranges
from limn.platform import files
from limn.platform.git import run_git
from limn.revisions import core as revisions_core, execution as revision_execution
from limn.runtime.documents import Doc
from limn.sync import rules as sync_rules

import helpers_figure
from helpers import MINI_PDF, TEX, VIEWER, ps
from helpers_access import ALICE, BOB, AccessBase, join_revision_workers

API_TYPES = VIEWER / "types" / "api.d.ts"
SNAPSHOTS = [
    Path(__file__).resolve().parents[4] / "tests" / "data" / name
    for name in ("contract_snapshot.json", "contract_snapshot_figure.json", "verdict_snapshot.json")
]
JSON_TYPES = {str: "string", int: "number", float: "number", bool: "boolean"}
# Pin fields the recorded flows never show (no flow writes a suggested edit) that DeclaredSuggestionShapes takes from the real
# handler's answers instead, each with what it is.
PIN_FROM_HANDLER = {
    "suggest": "a LaTeX line pin's suggested edit {base, text} (docs/handbook/api.md §제안 수정 (`suggest`))",
    "suggest_state": "whether that suggestion still fits its lines, computed on every read",
}
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

    type_text is a primitive (string, number, boolean, null), a string literal ('pin'), an interface name, an inline
    object type, a `Record<string, T>`, any of those with `[]`, or a union of them (`A | null`); an interface's fields
    are checked against value's keys, recursively, and a record's values against T."""
    if " | " in type_text:
        tried = [mismatches(value, alt, shapes, where) for alt in type_text.split(" | ")]
        return [] if any(not t for t in tried) else ["%s: %r fits none of %s" % (where, value, type_text)]
    if type_text == "null":
        return [] if value is None else ["%s: %r is not null" % (where, value)]
    if type_text.startswith("'"):
        return [] if value == type_text[1:-1] else ["%s: %r is not %s" % (where, value, type_text)]
    if type_text.startswith("Record<string, "):
        if not isinstance(value, dict):
            return ["%s: %s is not an object" % (where, type(value).__name__)]
        inner = type_text[len("Record<string, ") : -1]
        return [m for k, v in value.items() for m in mismatches(v, inner, shapes, "%s.%s" % (where, k))]
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
                handler = set(PIN_FROM_HANDLER) if name == "Pin" else set()
                self.assertEqual(sorted(unseen - SERVER_FIELDS[name] - handler), [])

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

    def test_a_literal_and_a_record_are_checked_too(self):
        """A string literal type takes that string only, and a Record<string, T> takes an object whose every value is
        a T."""
        self.assertEqual(mismatches("pin", "'pin'", self.shapes, "m"), [])
        self.assertEqual(mismatches("commit", "'pin'", self.shapes, "m"), ["m: 'commit' is not 'pin'"])
        self.assertEqual(mismatches({"CR": 2}, "Record<string, number>", self.shapes, "e"), [])
        self.assertEqual(
            mismatches({"CR": "2"}, "Record<string, number>", self.shapes, "e"), ["e.CR: '2' is not number"]
        )
        self.assertEqual(mismatches([], "Record<string, number>", self.shapes, "e"), ["e: list is not an object"])


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


class DeclaredSuggestionShapes(AccessBase):
    """api.d.ts declares a suggested-edit pin as the real handler answers it: created with a suggestion, listed, read
    one by one, and after its lines changed (suggest_state "changed") - the fields PIN_FROM_HANDLER explains."""

    def answers(self) -> list[tuple[str, dict]]:
        """(where, pin) for every pin answer of the flow: POST /api/pin with the lines' exact text as base (GET
        /api/snippet?text=1), GET /api/pins, GET /api/pins/<id>, an edit's answer, and GET /api/pins/<id> once the file's
        lines changed."""
        code, snip = self.call("GET", "/api/snippet?file=main.tex&lo=4&hi=5&text=1")
        self.assertEqual(code, 200, snip)
        body = {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": ""}
        code, made = self.call("POST", "/api/pin", {**body, "suggest": {"base": snip["text"], "text": "Rewritten."}})
        self.assertEqual(code, 200, made)
        out = []
        code, pins = self.call("GET", "/api/pins")
        out += [("list", p) for p in pins]
        code, one = self.call("GET", "/api/pins/%d" % made["id"])
        out.append(("one", one["pin"]))
        code, edited = self.call(
            "POST", "/api/pins/%d/edit" % made["id"], {"note": "why", "base_rev": one["pin"]["rev"]}
        )
        self.assertEqual(code, 200, edited)
        out.append(("edit", edited["pin"]))
        self.main.write_text(self.main.read_text(encoding="utf-8").replace("line two.", "line 2."), encoding="utf-8")
        code, changed = self.call("GET", "/api/pins/%d" % made["id"])
        out.append(("changed", changed["pin"]))
        return out

    def test_every_answered_suggestion_field_is_declared_with_its_type(self):
        """No pin answer of the flow has an undeclared field or a value of another JSON type than declared."""
        shapes = interfaces(API_TYPES.read_text(encoding="utf-8"))
        found = [
            m for where, p in self.answers() for m in mismatches(p, "Pin", shapes, "%s: pin #%s" % (where, p["id"]))
        ]
        self.assertEqual(found, [])

    def test_the_handler_answers_each_field_it_explains(self):
        """Every field PIN_FROM_HANDLER explains is in the flow's answers, and its state reads changed once the lines did."""
        got = self.answers()
        self.assertTrue(set(PIN_FROM_HANDLER) <= {k for _, p in got for k in p}, got)
        self.assertEqual([p.get("suggest_state") for w, p in got if w in ("one", "changed")], ["ready", "changed"])


# The interfaces DeclaredViewShapes holds to the handler's answers in its three states.
VIEWS = ["Meta", "BuildStatus", "DocsAnswer", "PeopleAnswer", "RebuildAnswer", "SyncStatus", "PullRecord"]
VIEWS += ["Me", "PersonSeen", "PageImage", "LatexError", "BuildProgress", "LastBuild", "DocEntry"]
VIEWS += ["PickOverlap", "DocVerdicts", "VerdictChoice", "PinEvent"]


class DeclaredViewShapes(AccessBase):
    """api.d.ts declares the document, build and people answers as the real handler gives them.

    Three states: one document with an open pin (and the overlaps a new range over it reports) and no build; three documents (a LaTeX file, one in a folder, a
    view-only PDF - the first with usable verdict words, the second with an unusable word file) with page images and two
    people who opened the viewer, then a figure document beside them whose map titles its pages and says one takes no
    verdict; one document after a build with LaTeX errors. The watch's states come from limn.sync.rules itself, since a test run has no remote to pull."""

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
        self.seen += [("PickOverlap", o) for o in ps.APP.overlaps_for_range(str(self.main), 4, 9)]
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
        kept = build_values.BuildUnchanged(0.3, None, 1.0, "h", "-", "pages-20260101000000", 1)
        with mock.patch.object(ps.APP.build_requests, "compile", return_value=kept):
            self.answer("RebuildAnswer", "POST", "/api/rebuild")
        self.answer("BuildStatus", "GET", "/api/build?log=1")

        (self.src / "rr").mkdir()
        (self.src / "rr" / "rr.tex").write_text(TEX, encoding="utf-8")
        (self.src / "review.pdf").write_bytes(MINI_PDF)
        # verdict words: the manuscript's usable (verdicts), the reply's unusable (verdicts_error), the PDF's none
        words = '{"format": "limn-verdicts/1", "page": true, "verdicts": [{"key": "채택"}, {"key": "삭제", "confirm": true}]}'
        (self.src / "main.limnverdicts.json").write_text(words, encoding="utf-8")
        (self.src / "rr" / "rr.limnverdicts.json").write_text("{", encoding="utf-8")
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
        self.answer("Meta", "GET", "/api/meta?doc=rr", headers=BOB)
        # a figure document whose map says page 2 takes no verdict and names page 1's figure body under its calendar
        # strip: meta's pages carry the map's page facts, the arrival's (figure_top, figure_above) among them
        fmap = helpers_figure.viewer_map()
        fmap["pages"][1]["verdict"] = False
        fmap["pages"][0]["elements"].append({"id": "B2/@figure", "parent": "B2", "frac": [0.06, 0.4, 0.88, 0.5]})
        fig = helpers_figure.figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([*docs, fig])
        helpers_figure.viewer_build(fig, helpers_figure.BUILD1, fmap)
        self.answer("Meta", "GET", "/api/meta?doc=fig", headers=BOB)
        self.answer("DocsAnswer", "GET", "/api/docs")
        ps.APP.people_directory.record(
            {"login": alice["Tailscale-User-Login"], "name": "Alice", "pic": alice["Tailscale-User-Profile-Pic"]}
        )
        self.answer("PeopleAnswer", "GET", "/api/people", headers=alice)
        statuses, pulls = sync_records()
        self.seen += [("SyncStatus", r) for r in statuses] + [("PullRecord", r) for r in pulls]
        self.event_states()

    def event_states(self):
        """The light poll with a cursor, after real writes addressed Alice and Bob: Bob's question pin tags Alice, Alice
        replies tagging Bob, closes it for review and reopens it; Bob deletes it. Each asks for its events after 0."""
        self.set_people(
            [
                {"login": ALICE["Tailscale-User-Login"], "name": "Alice Kim", "role": "owner"},
                {"login": BOB["Tailscale-User-Login"], "name": "Bob Park", "role": "editor"},
            ]
        )
        line = {
            "file": str(self.main),
            "lo": 4,
            "hi": 5,
            "page": 1,
            "note": "@Alice Kim 봐 주세요",
            "kind_req": "question",
        }
        code, made = self.call("POST", "/api/pin?doc=ms", line, BOB)
        self.assertEqual(code, 200, made)
        pid = made["id"]
        for path, body, who in [
            ("reply", {"text": "의견?"}, ALICE),
            ("close", {"review": True}, ALICE),
            ("reopen", {"reason": "다시 봐 주세요"}, ALICE),
            ("drop", {}, ALICE),
        ]:
            code, done = self.call("POST", "/api/pins/%d/%s?doc=ms" % (pid, path), body, who)
            self.assertEqual(code, 200, (path, done))
        for who in (ALICE, BOB):
            meta = self.answer("Meta", "GET", "/api/meta?doc=ms&light=1&ev=0", headers=who)
            self.assertTrue(meta["events"], meta)

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
        missing = sorted(
            "%s.%s" % (name, f) for name in VIEWS for f in self.shapes[name] if f not in seen.get(name, set())
        )
        self.assertEqual([m for m in missing if m not in UNSEEN], [])
        self.assertEqual(sorted(set(UNSEEN) - set(missing)), [])  # an explained field the states now show leaves UNSEEN
        self.assertTrue(seen["PageImage"] and seen["LatexError"] and seen["PersonSeen"], seen)


LATEX = [
    "\\section{A}",
    "Para one line.",
    "",
    "\\begin{figure}",
    "\\begin{center}",
    "x",
    "\\end{center}",
    "\\end{figure}",
    "after",
]


def recorded_rungs() -> list[dict]:
    """The ladder rungs the server builds: LaTeX ladders from limn.pins.location.mapping (a paragraph, a float
    environment, a merged raw rung, and a traced pick's rungs with their score, weighed and not), a figure script's raw
    ladder (range.raw_ladder), and the rungs of the recorded figure flow - the element rungs of its picks and the
    rungs of the snippet ladders it ends with, where the LaTeX document's carry the boxes their lines print in."""
    ladders = [
        mapping.compute_levels(LATEX, 6, 6, ["figure"]),
        mapping.compute_levels(LATEX, 2, 2, ["figure"]),
        ranges.raw_ladder(LATEX, 1, 3),
    ]
    rungs = [r for lad in ladders for r in lad["levels"]]
    for weights, synctex in (([("Para", 1.0)], (2, 2)), ([], (6, 6))):
        traced = mapping.trace_range(weights, LATEX, synctex, ["figure"])
        assert traced is not None
        rungs += traced.levels
    for entry in json.loads(SNAPSHOTS[1].read_text(encoding="utf-8")):
        answers_a_ladder = "picks" in entry["step"] or "/api/snippet" in entry["step"]
        if answers_a_ladder and "pins.md" not in entry["step"]:
            rungs += json.loads(entry["body"]).get("levels", [])
    return rungs


class DeclaredRungs(unittest.TestCase):
    """api.d.ts's Rung is what the server's ladders hold, LaTeX and figure alike, and each declared field occurs."""

    def test_every_rung_fits_and_every_field_occurs(self):
        """No rung has an undeclared field or a value of another type, and env, el and merged each appear somewhere."""
        shapes = interfaces(API_TYPES.read_text(encoding="utf-8"))
        rungs = recorded_rungs()
        found = [m for i, r in enumerate(rungs) for m in mismatches(r, "Rung", shapes, "rung %d" % i)]
        self.assertEqual(found, [])
        self.assertEqual(sorted(set(shapes["Rung"]) - {k for r in rungs for k in r}), [])


def recorded_picks() -> list[dict]:
    """The recorded POST /api/pick answers that placed a drag: a figure element (the traced-selection keys plus el), a
    figure region that fell back (the region keys plus el), and a drag traced to a LaTeX document's lines, whose
    default rung carries the boxes those lines print in (docs/adr/0049-pin-marks-follow-the-range.md)."""
    out = []
    for entry in json.loads(SNAPSHOTS[1].read_text(encoding="utf-8")):
        if "picks" in entry["step"] and "pins.md" not in entry["step"]:
            out.append(json.loads(entry["body"]))
    return out


class DeclaredPicks(unittest.TestCase):
    """api.d.ts's PickAnswer is the recorded pick answers' shape, and each declared field occurs in one of them."""

    def test_every_pick_fits_and_every_field_occurs(self):
        """No recorded pick has an undeclared field or another type; every PickAnswer field appears in some pick."""
        shapes = interfaces(API_TYPES.read_text(encoding="utf-8"))
        picks = recorded_picks()
        self.assertEqual(len(picks), 3)
        found = [m for i, p in enumerate(picks) for m in mismatches(p, "PickAnswer", shapes, "pick %d" % i)]
        self.assertEqual(found, [])
        self.assertEqual(sorted(set(shapes["PickAnswer"]) - {k for p in picks for k in p}), [])


def endpoint_map(text: str, name: str) -> dict[str, str]:
    """The `interface NAME { 'METHOD /path': Type; }` map of a declaration file (ApiAnswers, ApiRefusals), as endpoint
    -> type text."""
    found = re.search(r"^interface %s \{\n(.*?)^\}" % name, text, re.M | re.S)
    assert found, name
    return dict(re.findall(r"^  '([A-Z]+ /[^']+)': (.+);$", found.group(1), re.M))


def type_names(type_text: str) -> set[str]:
    """The declared interface names a type text mentions (`A | B`, `C[]`, `{ 409: D }`)."""
    return set(re.findall(r"\b([A-Z]\w+)\b", type_text)) - {"Record"}


def fake_compile(spec, jobdir, timeout):
    """A comparison build that writes a PDF naming its two sides, instead of latexdiff and latexmk."""
    (jobdir / "revision.pdf").write_bytes(b"%PDF-1.4\n" + spec.base.encode() + b".." + spec.head.encode())
    return revisions_core.ComparisonBuilt(["fake build"])


SECTION_AUX = "\\@writefile{toc}{\\contentsline {section}{\\numberline {1}Intro}{1}{section.1}}\n"
PLAN = "# Plan\n\nIntro.\x0cAfter a form feed.\n\nAlpha line.\nBeta line.\n"
# Declared fields of the endpoint answers that DeclaredEndpointAnswers' flows never answer, each with where the server
# adds it.
ENDPOINT_UNSEEN = {
    "RevisionsAnswer.reason": "a document with more history files than HISTORY_PATHS_MAX (limn.revisions.core)",
    "RevisionsAnswer.limit": "the same: too_many_files names HISTORY_PATHS_MAX",
    "RevisionsAnswer.overlay": "a figure document's history, whose two builds the viewer lays one over the other",
    "RevisionDiff.merge_base": "a range whose base is on another line than its commit (range_ends)",
    "RevisionSources.merge_base": "the same, for both sides of a browser-drawn document",
    "RevisionBuildStatus.merge_base": "the same, for a range's comparison PDF",
    "RangeFile.old_path": "a range that renames a manuscript file (git diff --numstat -M)",
}


class DeclaredEndpointAnswers(AccessBase):
    """api.d.ts declares every endpoint answer of ApiAnswers and every expected refusal of ApiRefusals as the real handler
    gives it: the pin writes and their 409s, the source and snippet reads, the build hold, rebuild and outline labels,
    the version, and the history, diff, sides and comparison builds of a small Git repository.

    Two documents over one manuscript folder that is a Git repository: ms (main.tex, with a published build, its page
    images and its .aux) and nt (plan.md, which the browser draws). Two commits: the second edits a pin's line and
    another line of main.tex and plan.md, and the pin is closed with that commit, so its scope is a part of it."""

    def setUp(self):
        """The two documents, the build of ms, and the repository with its two commits."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.shapes = interfaces(API_TYPES.read_text(encoding="utf-8"))
        self.seen: list[tuple[str, object]] = []
        self.md = self.src / "plan.md"
        self.md.write_text(PLAN, encoding="utf-8")
        ms = Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths)
        ps.APP.set_docs([ms, Doc("nt", "계획", "markdown", self.src, self.md, paths=ps.APP.C.paths)])
        self.addCleanup(ps.APP.set_docs, None)
        pages = ms.dir / "pages-20260101000000"
        pages.mkdir(parents=True, exist_ok=True)
        (pages / "page-1.png").write_bytes(PAGE_PNG)
        (pages / ms.pdf_name).write_bytes(MINI_PDF)
        (pages / "main.aux").write_text(SECTION_AUX, encoding="utf-8")
        files.atomic_write(ms.dir / "pages.cur", pages.name)
        self.build = pages.name
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "user.email", "alice@example.com")
        self.git("config", "user.name", "Alice")
        self.git("config", "commit.gpgsign", "false")
        self.first = self.commit("first")
        self.pin = self.pin_id(lo=4, hi=4)
        text = self.main.read_text(encoding="utf-8")
        self.main.write_text(text.replace("rarewordalpha", "rarewordomega").replace("zetaunique", "etaunique"), "utf-8")
        self.md.write_text(PLAN.replace("Beta line.", "Beta line, reworded."), encoding="utf-8")
        self.second = self.commit("second")
        code, closed = self.call(
            "POST",
            "/api/pins/%d/close" % self.pin,
            {"ref": self.second[:8], "changes": [{"file": "main.tex", "lo": 4, "hi": 4}]},
        )
        self.assertEqual(code, 200, closed)

    def git(self, *args):
        """Run a fixture git command in the manuscript folder; its stdout, stripped."""
        done = run_git(list(args), self.src, 10)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def commit(self, subject):
        """Commit the whole folder with subject; the new commit's full id."""
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", subject)
        return self.git("rev-parse", "HEAD")

    def answer(self, interface, method, path, body=None, status=200, headers=None):
        """Call path (as headers' identity, else the loopback agent) and keep its body as an instance of interface; the
        call must answer status."""
        code, data = self.call(method, path, body, headers)
        self.assertEqual(code, status, (method, path, data))
        self.seen.append((interface, data))
        return data

    def pin_flows(self):
        """Every pin answer api.d.ts declares an endpoint for, and the 409s the viewer expects of them."""
        line = {"file": str(self.main), "lo": 8, "hi": 8, "page": 1, "note": "n"}
        made = self.answer("PinSaved", "POST", "/api/pin", {**line, "idem": "k" * 24})
        self.answer("PinSaved", "POST", "/api/pin", {**line, "idem": "k" * 24})  # replay
        pid = made["id"]
        self.answer("SaveConflict", "POST", "/api/pin", {"idem": "u" * 24, "replay_only": True}, 409)
        self.answer("SaveConflict", "POST", "/api/pin", {**line, "suggest": {"base": "x", "text": "y"}}, 409)
        one = self.answer("PinAnswer", "GET", "/api/pins/%d" % pid)
        edit = "/api/pins/%d/edit" % pid
        self.answer("PinChanged", "POST", edit, {"note": "m", "base_rev": one["pin"]["rev"]})
        self.answer("PinConflict", "POST", edit, {"note": "x", "base_rev": 0}, 409)
        rev = self.answer("PinAnswer", "GET", "/api/pins/%d" % pid)["pin"]["rev"]
        self.answer("PinConflict", "POST", edit, {"suggest": {"base": "x", "text": "y"}, "base_rev": rev}, 409)
        self.answer("PinReplyAnswer", "POST", "/api/pins/%d/reply" % pid, {"text": "a reply"})
        self.answer("PinUnclaimed", "POST", "/api/pins/%d/unclaim" % pid, {})
        self.answer("PinConflict", "POST", "/api/pins/%d/confirm" % pid, {}, 409, ALICE)  # open
        self.answer("PinStateAnswer", "POST", "/api/pins/%d/close" % pid, {})
        done = self.answer("PinAnswer", "GET", "/api/pins/%d" % pid)["pin"]
        self.answer("PinConflict", "POST", edit, {"lo": 9, "hi": 9, "base_rev": done["rev"]}, 409)  # done
        self.answer("PinStateAnswer", "POST", "/api/pins/%d/reopen" % pid, {})
        self.answer("PinStateAnswer", "POST", "/api/pins/%d/close" % pid, {})
        self.answer("PinStateAnswer", "POST", "/api/pins/%d/confirm" % pid, {}, headers=ALICE)
        self.answer("PinStateAnswer", "POST", "/api/pins/99999/close", {})  # no such pin
        self.answer("PinReplyAnswer", "POST", "/api/pins/99999/reply", {"text": "a reply"})
        self.answer("PinUnclaimed", "POST", "/api/pins/99999/unclaim", {})
        self.answer("PinDropped", "POST", "/api/pins/%d/drop" % pid, {})
        self.answer("DroppedAnswer", "GET", "/api/pins/dropped")
        self.answer("PinChanged", "POST", "/api/pins/%d/restore" % pid, {})
        self.answer("PinDropped", "POST", "/api/pins/%d/drop" % pid, {})
        self.set_people([{"login": ALICE["Tailscale-User-Login"], "name": "Alice Kim", "role": "owner"}])
        self.answer("PinPurged", "POST", "/api/pins/%d/purge" % pid, {}, headers=ALICE)
        self.answer("PinDropped", "POST", "/api/pins/99999/drop", {})

    def document_flows(self):
        """The source, snippet, outline, hold, rebuild, version and pick answers, with the refusals expected of them."""
        self.answer("SourceAnswer", "GET", "/api/source?doc=nt")
        with mock.patch.object(documents_http, "read_source", lambda file: document_source.read_source(file, 8)):
            self.answer("SourceTooLarge", "GET", "/api/source?doc=nt", status=413)
        lines = "/api/snippet?doc=ms&file=%s&lo=4&hi=5" % self.main
        self.answer("SnippetAnswer", "GET", lines)
        self.answer("SnippetAnswer", "GET", lines + "&levels=1&text=1")
        # the marks request, the only one told which build they were measured against (boxes_build)
        self.answer("SnippetAnswer", "GET", lines + "&levels=1&boxes=1")
        self.answer("ErrorBody", "GET", "/api/snippet?doc=ms&file=%s&lo=900&hi=901" % self.main, status=400)
        self.answer("OutlineLabelsAnswer", "GET", "/api/outline-labels?doc=ms")
        self.answer("HoldAnswer", "POST", "/api/hold?doc=ms", {"build": self.build, "days": 1})
        self.answer("HoldAnswer", "POST", "/api/hold?doc=ms", {"build": self.build, "days": 0})
        self.answer("VersionAnswer", "GET", "/api/version")
        requests = ps.APP.build_requests
        with mock.patch.object(requests, "rebuild_async", return_value=build_values.BuildStarted()):
            self.answer("RebuildStarted", "POST", "/api/rebuild?doc=ms&async=1", status=202)
        with mock.patch.object(requests, "rebuild_async", return_value=build_values.BuildBusy()):
            self.answer("RebuildBusy", "POST", "/api/rebuild?doc=ms&async=1", status=409)
        with mock.patch.object(requests, "rebuild", return_value=build_values.BuildBusy()):
            self.answer("RebuildBusy", "POST", "/api/rebuild?doc=ms", status=409)
        gone = {"page": 1, "x0": 0, "y0": 0, "x1": 10, "y1": 10, "pdf_build": "pages-20000101000000", "doc": "ms"}
        self.answer("PickRefusal", "POST", "/api/pick?doc=ms", gone)

    def revision_flows(self):
        """The history, the diffs (one commit, a pin's part of it, the pin on a commit it is not in, a range), both
        sides of the Markdown file (one cut by the size limit), and a comparison build's status idle and started."""
        commit, first = "commit=" + self.second, "commit=" + self.first
        self.answer("RevisionsAnswer", "GET", "/api/revisions?doc=ms")
        self.answer("RevisionsAnswer", "GET", "/api/revisions?doc=ms&limit=1")
        self.answer("RevisionDiff", "GET", "/api/revision-diff?doc=ms&" + commit)
        self.answer("RevisionDiff", "GET", "/api/revision-diff?doc=ms&%s&pin=%d" % (commit, self.pin))
        self.answer("RevisionDiff", "GET", "/api/revision-diff?doc=ms&%s&pin=%d" % (first, self.pin))
        self.answer("RevisionDiff", "GET", "/api/revision-diff?doc=ms&%s&base=%s" % (commit, self.first))
        self.answer("RevisionSources", "GET", "/api/revision-source?doc=nt&" + commit)
        self.answer("RevisionSources", "GET", "/api/revision-source?doc=nt&%s&base=%s" % (commit, self.first))
        with mock.patch.object(revisions_core, "REVISION_SOURCE_MAX", 8):
            self.answer("RevisionSources", "GET", "/api/revision-source?doc=nt&" + commit)
        self.answer("RevisionBuildStatus", "GET", "/api/revision-build?doc=ms&" + commit)
        with mock.patch.object(revision_execution, "revision_compile", side_effect=fake_compile):
            body = {"commit": self.second, "pin": self.pin}
            self.answer("RevisionBuildStatus", "POST", "/api/revision-build?doc=ms", body, status=202)
            join_revision_workers(self)
            self.answer("RevisionBuildStatus", "GET", "/api/revision-build?doc=ms&%s&pin=%d" % (commit, self.pin))

    def run_flows(self):
        """Every flow above, in order."""
        self.pin_flows()
        self.document_flows()
        self.revision_flows()

    def test_every_answered_field_is_declared_with_its_type(self):
        """No answer of the flows has an undeclared field or a value of another JSON type than declared."""
        self.run_flows()
        found = [
            m
            for i, (name, body) in enumerate(self.seen)
            for m in mismatches(body, name, self.shapes, "%d %s" % (i, name))
        ]
        self.assertEqual(found, [])

    def test_declared_fields_are_answered_or_explained(self):
        """Each field of the endpoint answers' interfaces is a key of some answer of its interface, or is in
        ENDPOINT_UNSEEN with the reason the flows cannot show it; an explained field the flows show leaves it."""
        self.run_flows()
        seen: dict[str, set[str]] = {}

        def collect(value, type_text):
            """Record the keys value shows for each declared interface it is (or holds) an instance of."""
            for alt in type_text.split(" | "):
                alt = alt[:-2] if alt.endswith("[]") else alt
                if alt in self.shapes:
                    for item in value if isinstance(value, list) else [value]:
                        if isinstance(item, dict) and not mismatches(item, alt, self.shapes, ""):
                            seen.setdefault(alt, set()).update(item)
                            for k, v in item.items():
                                if k in self.shapes[alt]:
                                    collect(v, self.shapes[alt][k])

        for name, body in self.seen:
            collect(body, name)
        names = {name for name, _ in self.seen} | {"OutlineLabelRow", "RevisionPinScope", "RevisionCommitScope"}
        names |= {"RangeFile", "RevisionSide"}
        missing = sorted("%s.%s" % (n, f) for n in names for f in self.shapes[n] if f not in seen.get(n, set()))
        self.assertEqual([m for m in missing if m not in ENDPOINT_UNSEEN], [])
        self.assertEqual(sorted(set(ENDPOINT_UNSEEN) - set(missing)), [])

    def test_every_endpoint_answer_is_held_to_a_handler(self):
        """Each type ApiAnswers and ApiRefusals name is one this module checks against what the server answers: the pins
        through the recorded flows (DeclaredPinShapes, DeclaredPicks), the views through DeclaredViewShapes, the rest
        through these flows."""
        text = API_TYPES.read_text(encoding="utf-8")
        named = set().union(
            *(type_names(t) for m in ("ApiAnswers", "ApiRefusals") for t in endpoint_map(text, m).values())
        )
        self.run_flows()
        held = {name for name, _ in self.seen} | {"Pin", "PickAnswer"} | set(VIEWS)
        self.assertEqual(sorted(named - held), [])
        self.assertGreater(len(endpoint_map(text, "ApiAnswers")), 25)
