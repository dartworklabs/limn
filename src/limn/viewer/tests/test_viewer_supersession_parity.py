"""The server's `superseded_by` (limn.pins.verdict.superseded_by, ADR-0023) against the viewer's verdict order (verdict.js).

The viewer counts which verdict pin is a target's current verdict itself (verdictOrder: the page line, the card's '이전 판정 ·
#N로 대체됨', the [보기] jump), and since 0.4.34 the server tells agents the same thing in GET /api/pins and pins.md. They are
two implementations of one rule, so a disagreement shows a card that says a verdict is current while an agent is told to
skip it. One flow of verdicts runs through the real handler in all three kinds of document - a figure's root and panel, a
LaTeX file's lines (an open one and a closed one), a view-only PDF's pages, a region and a verdict taken back to the Trash and
restored - and every verdict pin's `superseded_by` must equal the number the viewer names as its superseding verdict.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_supersession_parity.py
"""

import json

import helpers_figure
from helpers import ps, split_resp
from helpers_access import ALICE, BOB, talk_to
from helpers_browser import BrowserBase, settle

WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}]}
ROOT = {"id": "B2", "path": ["B2"]}
PANEL = {"id": "B2/calendar", "path": ["B2", "B2/calendar"]}
# Every verdict pin the viewer knows as [id, the id of the verdict it says supersedes it, or null] - the viewer's own count,
# for the pins of every document under [모든 문서].
VIEWER_ORDER = """()=>{SHOW_ALL=true; drawPins();
  const all=OPEN_ALL.concat(REVIEW_ALL,DONE_ALL).filter(p=>verdictOf(p));
  return all.map(p=>{const c=verdictSuperseder(p); return [p.id, c?c.id:null];}).sort((a,b)=>a[0]-b[0]);}"""


class SupersessionParity(BrowserBase):
    """Verdicts made over HTTP in the three documents, then the viewer's order read from the page."""

    def setUp(self):
        """The three documents of helpers_figure.viewer_docs, each with a word file."""
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        words = {
            "ms": ps.APP.C.src / "main.limnverdicts.json",
            "fig": self.fig.main.parent / "figures.limnverdicts.json",
            "rv": ps.APP.C.src / "reviewer.limnverdicts.json",
        }
        for path in words.values():
            path.write_text(json.dumps(WORDS, ensure_ascii=False), encoding="utf-8")

    def call(self, method, path, body=None, who=ALICE):
        """One request to the handler as who -> (status, JSON)."""
        data = json.dumps(body).encode() if body is not None else b""
        h = {"Host": "127.0.0.1:18999", **who}
        if data:
            h.update({"Content-Type": "application/json", "Content-Length": str(len(data))})
        if method == "POST":
            h["Origin"] = "http://127.0.0.1:18999"
        raw = ("%s %s HTTP/1.1\r\n" % (method, path) + "".join("%s: %s\r\n" % kv for kv in h.items()) + "\r\n").encode()
        code, _, out = split_resp(talk_to(ps, raw + data))
        return code, json.loads(out or b"null")

    def make(self, body, who=BOB):
        """Make a pin as person who; its id."""
        code, d = self.call("POST", "/api/pin", body, who)
        self.assertEqual(code, 200, d)
        return d["id"]

    def server_order(self):
        """[id, superseded_by or None] of every verdict pin as GET /api/pins?all=1 answers, by id."""
        pins = self.call("GET", "/api/pins?all=1")[1]
        return sorted([p["id"], p.get("superseded_by")] for p in pins if p.get("verdict"))

    def open_viewer(self, n_open):
        """The viewer on the LaTeX document, settled, with at least n_open open pins listed."""
        page = self.open(n_open)
        settle(page)
        return page

    def test_the_viewers_order_and_the_servers_field_name_the_same_verdicts(self):
        """The flow, checked after each step that changes the order: the viewer's count equals the server's field."""
        fig = {
            "doc": "fig",
            "file": helpers_figure.SCRIPT,
            "lo": 12,
            "hi": 140,
            "page": 1,
            "pdf_build": helpers_figure.BUILD1,
        }
        ms = {"doc": "ms", "file": str(self.main), "page": 1, "lo": 4, "hi": 5}
        rv = {"doc": "rv", "pdf_build": helpers_figure.BUILD1}
        made = [
            self.make({**fig, "el": ROOT, "verdict": "보류"}, ALICE),  # a figure verdict on the figure,
            self.make({**fig, "el": PANEL, "verdict": "채택"}),  # then one on a panel of it (ADR-0022 D1),
            self.make({**ms, "verdict": "채택"}),  # LaTeX lines: an open pin,
            self.make({**ms, "verdict": "보류"}, ALICE),  # a newer one on the same lines,
            self.make({**ms, "lo": 8, "hi": 9, "verdict": "채택"}),  # other lines,
            self.make({**rv, "page": 2, "frac": [0, 0, 1, 1], "verdict": "채택"}),  # a PDF page,
            self.make({**rv, "page": 2, "frac": [0, 0, 1, 1], "verdict": "보류"}, ALICE),  # a newer one on it,
            self.make({**rv, "page": 1, "frac": [0, 0, 1, 1], "verdict": "채택"}),  # another page,
            self.make({**rv, "page": 2, "frac": [0, 0, 1, 0.5], "verdict": "삭제"}),  # and a region: no target.
        ]
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % made[2], {})[0], 200)  # a closed older verdict
        newest = self.make({**fig, "el": ROOT, "verdict": "채택"})  # and the figure's newest
        want = {made[0]: newest, made[1]: newest, made[2]: made[3], made[5]: made[6]}
        steps = [("every verdict made", want)]
        server = dict(self.server_order())
        self.assertEqual({i: c for i, c in server.items() if c is not None}, want)
        page = self.open_viewer(len(made))
        self.assertEqual(page.evaluate(VIEWER_ORDER), self.server_order(), steps[0][0])

        # The newest figure verdict goes to the Trash: the older two are current again, in the server and in the viewer.
        self.assertEqual(self.call("POST", "/api/pins/%d/drop" % newest, {}, ALICE)[0], 200)
        page = self.open_viewer(len(made) - 1)
        self.assertEqual(page.evaluate(VIEWER_ORDER), self.server_order(), "the newest figure verdict deleted")
        self.assertEqual(dict(self.server_order())[made[0]], made[1])

        # Restored, it supersedes them again.
        self.assertEqual(self.call("POST", "/api/pins/%d/restore" % newest, {}, ALICE)[0], 200)
        page = self.open_viewer(len(made))
        self.assertEqual(page.evaluate(VIEWER_ORDER), self.server_order(), "the verdict restored")
        self.assertEqual(dict(self.server_order())[made[0]], newest)
