"""Line pins on a text document (docs/adr/0029-text-documents.md D1, D3, D4): plain text or source code registered by its
--doc suffix, pinned by its lines with no page, and taking a suggested edit and a verdict as a Markdown document's lines do.

A text document is kind "text", with the capabilities of a Markdown one (renders_in_browser, takes_line_pins,
takes_suggestions): only the viewer tells the two apart. So every rule the Markdown pins follow is reached here through
the document a real --doc spec makes (serve_documents.make_docs), not through a Doc built by hand:

- the scope a text document's ladder adds, indent (pin kind indent), and its paragraph (para, kind paragraph) round-trip
  through a new pin, a re-placement and an edit of the note alone, in the record and in the answer;
- page, frac and pdf_build an agent sends out of habit are never stored, on a new pin or a re-placement;
- pins.md's page column is `—`, its range column `indent`, its section title `— 텍스트(쪽 없음)`;
- a suggested edit of its lines is accepted and reads ready;
- a verdict is about its lines: the newer verdict on the same lines supersedes the older, with the word file at the main
  file's stem (figs/plot.limnverdicts.json);
- a request that names only the file goes to the text document, though a LaTeX document's folder holds it.

Run: uv run pytest -q src/limn/pins/editing/tests/test_text_pins.py
"""

import json

from limn.administration import serve_documents
from limn.documents.verdicts import verdicts_path

from helpers import ps
from helpers_access import ALICE, BOB, AccessBase

# The page fields a text pin never keeps (limn.pins.pages.PAGE_FIELDS).
PAGE_FIELDS = ("page", "frac", "pdf_build", "frac_build")
HABIT = {"page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "pdf_build": "pages"}
PLOT = (
    "import numpy as np\n"  # 1
    "\n"  # 2
    "def plot(ax, data):\n"  # 3
    '    """Draw the power."""\n'  # 4
    "    for row in data:\n"  # 5
    "        ax.plot(row)\n"  # 6
    "    return ax\n"  # 7
    "\n"  # 8
    "def save(fig):\n"  # 9
    '    fig.savefig("p.pdf")\n'  # 10
)
WORDS = {"format": "limn-verdicts/1", "page": True, "verdicts": [{"key": "채택"}, {"key": "보류"}]}


class TextDocument(AccessBase):
    """A LaTeX document ms (main.tex) and a text document py (figs/plot.py, PLOT) from real --doc specs, in that order."""

    def setUp(self):
        """ms and py as startup makes them from `--doc ms=본문:main.tex --doc py=그림 코드:figs/plot.py`."""
        super().setUp()
        (self.src / "figs").mkdir()
        self.py = self.src / "figs" / "plot.py"
        self.py.write_text(PLOT, encoding="utf-8")
        docs = serve_documents.make_docs(["ms=본문:main.tex", "py=그림 코드:figs/plot.py"], self.src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        self.ms, self.tx = docs
        ps.APP.set_docs(docs)
        self.addCleanup(ps.APP.set_docs, None)

    def make(self, headers=None, **body):
        """A new pin on figs/plot.py made over HTTP (as the loopback agent unless headers name a person); its id."""
        code, d = self.call("POST", "/api/pin", {"doc": "py", "file": str(self.py), "note": "n", **body}, headers)
        self.assertEqual(code, 200, d)
        return d["id"]

    def edit(self, pid, body, headers=None):
        """POST /api/pins/{pid}/edit with body; the answer, which must be a 200."""
        code, d = self.call("POST", "/api/pins/%d/edit" % pid, body, headers)
        self.assertEqual(code, 200, d)
        return d

    def stored(self, pid):
        """Pin pid's record as pins.jsonl holds it."""
        for line in ps.APP.C.pins_jsonl.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("id") == pid:
                return rec
        self.fail("pin %d is not in pins.jsonl" % pid)

    def shown(self, pid):
        """GET /api/pins/{pid}'s pin."""
        code, d = self.call("GET", "/api/pins/%d" % pid)
        self.assertEqual(code, 200, d)
        return d["pin"]

    def assert_pageless(self, pid):
        """Pin pid's record and its answer hold none of the page fields."""
        record, shown = self.stored(pid), self.shown(pid)
        for key in PAGE_FIELDS:
            self.assertNotIn(key, record)
            self.assertNotIn(key, shown)


class Registration(TextDocument):
    """What the --doc suffix makes, as the API names it."""

    def test_the_api_names_the_document_text_with_no_pages(self):
        """GET /api/docs lists py as kind text after ms; GET /api/meta?doc=py answers kind text and no page."""
        code, docs = self.call("GET", "/api/docs")
        self.assertEqual(code, 200, docs)
        self.assertEqual([(d["key"], d["kind"]) for d in docs["docs"]], [("ms", "tex"), ("py", "text")])
        code, meta = self.call("GET", "/api/meta?doc=py")
        self.assertEqual(code, 200, meta)
        self.assertEqual((meta["kind"], meta["pages"]), ("text", []))

    def test_a_request_naming_only_the_file_goes_to_the_text_document(self):
        """A pin that names figs/plot.py and no doc is the text document's, though the LaTeX document's folder holds the
        file: a document the browser draws owns its own file first."""
        code, d = self.call("POST", "/api/pin", {"file": str(self.py), "lo": 3, "hi": 3, "note": "n"})
        self.assertEqual(code, 200, d)
        self.assertEqual(self.stored(d["id"])["doc"], "py")
        self.assert_pageless(d["id"])


class Scopes(TextDocument):
    """The text ladder's scopes through every write that sets or keeps them."""

    def test_an_indented_block_keeps_its_scope_and_kind_and_takes_no_page(self):
        """A pin on the function plot() (lines 3-7) at scope indent, kind indent, sent with page fields: stored and answered
        with scope and kind indent and no page field; pins.md shows `—` for its page, `indent` for its range, and the
        document's section title names the form."""
        pid = self.make(lo=3, hi=7, scope="indent", kind="indent", quote="def plot(ax, data):", **HABIT)
        for got in (self.stored(pid), self.shown(pid)):
            self.assertEqual((got["lo"], got["hi"], got["scope"], got["kind"]), (3, 7, "indent", "indent"))
        self.assert_pageless(pid)
        code, text = self.call("GET", "/pins.md")
        self.assertEqual(code, 200, text)
        self.assertIn("\n## 그림 코드 · `py` · `figs/plot.py` — 텍스트(쪽 없음)\n", text)
        self.assertIn("\n| %d | — | `figs/plot.py L3-L7` | indent | n |\n" % pid, text)

    def test_a_re_placement_and_a_note_edit_keep_the_scope_and_take_no_page(self):
        """A paragraph pin (para, kind paragraph) re-placed onto the block of save() at indent with page fields again: it
        moves, keeps no page field and takes the new scope and kind; an edit of its note alone then keeps them."""
        pid = self.make(lo=1, hi=1, scope="para", kind="paragraph", **HABIT)
        self.assertEqual((self.stored(pid)["scope"], self.stored(pid)["kind"]), ("para", "paragraph"))
        loc = {"file": str(self.py), "lo": 9, "hi": 10, "scope": "indent", "kind": "indent", **dict(HABIT, page=2)}
        self.edit(pid, {"base_rev": 0, "loc": loc}, ALICE)
        got = self.stored(pid)
        self.assertEqual((got["lo"], got["hi"], got["scope"], got["kind"]), (9, 10, "indent", "indent"))
        self.assert_pageless(pid)
        self.edit(pid, {"base_rev": got.get("rev", 0), "note": "저장 이름을 바꿔 줘"}, ALICE)
        got = self.stored(pid)
        self.assertEqual(
            (got["note"], got["scope"], got["kind"], got["lo"], got["hi"]),
            ("저장 이름을 바꿔 줘", "indent", "indent", 9, 10),
        )
        self.assert_pageless(pid)

    def test_an_edit_that_sets_the_indent_scope_alone_is_kept(self):
        """An edit naming lo, hi and scope indent (the edit card's ladder) stores that scope."""
        pid = self.make(lo=5, hi=5)
        self.edit(pid, {"base_rev": 0, "lo": 5, "hi": 6, "scope": "indent", "kind": "indent"}, ALICE)
        got = self.stored(pid)
        self.assertEqual((got["lo"], got["hi"], got["scope"], got["kind"]), (5, 6, "indent", "indent"))


class SuggestionsAndVerdicts(TextDocument):
    """A text document's lines take a suggested edit and a verdict (ADR-0029 D4)."""

    def test_a_suggestion_on_its_lines_is_accepted_and_ready(self):
        """A suggestion whose base is line 10 is stored with the pin and reads ready; pins.md's `## 제안 문안` block has
        the text in a fence."""
        pid = self.make(
            lo=10, hi=10, suggest={"base": '    fig.savefig("p.pdf")', "text": '    fig.savefig("power.pdf")'}
        )
        self.assertEqual(
            self.stored(pid)["suggest"], {"base": '    fig.savefig("p.pdf")', "text": '    fig.savefig("power.pdf")'}
        )
        self.assertEqual(self.shown(pid)["suggest_state"], "ready")
        code, text = self.call("GET", "/pins.md")
        self.assertIn(
            '\n### #%d · `py` · figs/plot.py L10-L10 · 바꿀 준비됨\n```\n    fig.savefig("power.pdf")\n```\n' % pid,
            text,
        )

    def test_an_edit_sets_a_suggestion_on_a_text_pin(self):
        """An edit setting a suggestion on a text pin by a person is accepted and answered with its state."""
        pid = self.make(lo=7, hi=7)
        d = self.edit(pid, {"base_rev": 0, "suggest": {"base": "    return ax", "text": "    return ax.figure"}}, ALICE)
        self.assertEqual(d["pin"]["suggest_state"], "ready")

    def test_the_newer_verdict_on_the_same_lines_supersedes_the_older(self):
        """Two verdicts by editor Bob on lines 3-7, with the word file figs/plot.limnverdicts.json: the older gets
        superseded_by the newer; a verdict on line 9 is its own target."""
        self.set_people([{"login": "bob@example.com", "name": "Bob", "role": "editor"}])
        # resolved: on macOS the temporary folder /var/... is /private/var/... once a path is resolved
        self.assertEqual(verdicts_path(self.tx).resolve(), (self.src / "figs" / "plot.limnverdicts.json").resolve())
        verdicts_path(self.tx).write_text(json.dumps(WORDS, ensure_ascii=False), encoding="utf-8")
        first = self.make(BOB, lo=3, hi=7, verdict="채택")
        other = self.make(BOB, lo=9, hi=9, verdict="채택")
        second = self.make(BOB, lo=3, hi=7, verdict="보류")
        code, pins = self.call("GET", "/api/pins?all=1", headers=BOB)
        self.assertEqual(code, 200, pins)
        self.assertEqual({p["id"]: p["superseded_by"] for p in pins if "superseded_by" in p}, {first: second})
        self.assertNotIn(other, [p["id"] for p in pins if "superseded_by" in p])
        for pid in (first, other, second):
            self.assert_pageless(pid)
