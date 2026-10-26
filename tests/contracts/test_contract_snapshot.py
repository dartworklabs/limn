"""The agent contract as one recorded snapshot: pins.md and the main API answers of a fixed pin flow, byte for byte.

A fixed sequence of requests - new pins by people and the agent, a question, a claim, replies, a close with a reply,
ref and changes, a confirm, a reopen, an edit, the Trash and back, and the refusals an agent meets (confirm by the
agent, a stale edit, a claim on a closed pin, a missing pin) - runs through the real handler with the clock, the time
zone and the paths pinned. Every answer (status and body), pins.md after every write, and at the end GET /pins.md,
GET /api/pins, GET /api/pins/<id> and GET /api/pins/dropped are compared with tests/data/contract_snapshot.json
(docs/handbook/verification.md §4), so a refactor that changes any of these bytes fails here. The figure flow and the
verdict flow are recorded apart, in tests/data/contract_snapshot_figure.json and tests/data/verdict_snapshot.json.

Paths are written as <ROOT> (the temporary folder), the clock is 2026-09-26 10:00:00 +09:00 whatever the machine's
zone. A deliberate contract change (docs/handbook/api.md, approved first) re-records the snapshot:
LIMN_RECORD_SNAPSHOT=1 uv run pytest -q tests/contracts/test_contract_snapshot.py - and the diff of the JSON is the change.

Run: uv run pytest -q tests/contracts/test_contract_snapshot.py
"""

import json
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from limn.builds import engine as build_engine
from limn.documents.verdicts import verdicts_path
from limn.pins.listing import markdown as listing_markdown
from limn.pins.location import source as pick_source
from limn.runtime.documents import Doc
from limn.security import people as limn_people

from helpers import ps
from helpers_access import ALICE, BOB, AccessBase
from helpers_figure import (
    AUGUST_BOX,
    BUILD1,
    BUILD2,
    JULY_BOX,
    SCRIPT,
    b2_map,
    figure_doc,
    viewer_docs,
    write_build,
)

SNAPSHOT = Path(__file__).resolve().parents[2] / "tests" / "data" / "contract_snapshot.json"
T0 = 1790384400.0  # 2026-09-26 10:00:00 +09:00
ZONE = timezone(timedelta(hours=9))
_STRFTIME = time.strftime


class FrozenDateTime(datetime):
    """datetime whose now() is T0 in +09:00 and whose astimezone() keeps that zone, so no reading depends on the
    machine's clock or zone (pins.md's updated line, the appended-note time, a build's finished_at, people.json)."""

    @classmethod
    def now(cls, tz=None):
        """T0 in +09:00 (or in tz when given)."""
        return cls.fromtimestamp(T0, tz or ZONE)

    @classmethod
    def fromtimestamp(cls, t, tz=None):
        """t in +09:00 (or in tz when given) - never the machine's zone."""
        return super().fromtimestamp(t, tz or ZONE)

    def astimezone(self, tz=None):
        """This time in tz; with none, unchanged (+09:00) rather than the machine's zone."""
        return self if tz is None else super().astimezone(tz)


def frozen_strftime(fmt, t=None):
    """time.strftime of T0 in +09:00 when no time is given (the store's backup and archive names)."""
    return _STRFTIME(fmt, time.gmtime(T0 + 9 * 3600) if t is None else t)


class SnapshotBase(AccessBase):
    """The pinned clocks and zone and the recording of one flow's answers (every snapshot test's setup)."""

    def setUp(self):
        """AccessBase's fresh server, with every clock the flow reads pinned to T0 in +09:00 (Asia/Seoul)."""
        super().setUp()
        # The store reads a stored wall time (dropped_at) in the machine's zone (the Trash's expires_ts), so the zone
        # itself is pinned too.
        zone = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Seoul"
        time.tzset()
        self.addCleanup(self.restore_zone, zone)
        for patcher in (
            mock.patch.object(ps.APP, "now_str", return_value="2026-09-26 10:00:00"),
            mock.patch("time.time", return_value=T0),
            mock.patch("time.strftime", frozen_strftime),
            mock.patch.object(ps, "datetime", FrozenDateTime),
            mock.patch.object(listing_markdown, "datetime", FrozenDateTime),
            mock.patch.object(build_engine, "datetime", FrozenDateTime),
            mock.patch.object(limn_people, "datetime", FrozenDateTime),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.utime(self.main, (T0, T0))  # a synced pin records its file's mtime (synced_at)
        self.roots = sorted({str(Path(self.tmp.name)), str(Path(self.tmp.name).resolve())}, key=len, reverse=True)
        self.seen = []

    @staticmethod
    def restore_zone(zone):
        """Put the process's time zone back as it was before the test."""
        if zone is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = zone
        time.tzset()

    def text(self, raw):
        """raw (bytes or str) as text with the temporary folder written as <ROOT>."""
        out = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        for root in self.roots:
            out = out.replace(root, "<ROOT>")
        return out

    def step(self, name, method, path, body=None, headers=None):
        """One request: its status and body are recorded, and pins.md after it when it wrote."""
        code, data = self.call(method, path, body, headers)
        rendered = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, sort_keys=False)
        self.seen.append({"step": name, "status": code, "body": self.text(rendered)})
        if method == "POST" and ps.APP.C.pins_md.exists():
            self.seen.append({"step": name + " -> pins.md", "body": self.text(ps.APP.C.pins_md.read_bytes())})
        return data

    def assert_recorded(self, path: Path) -> None:
        """The answers seen equal the snapshot at path, step by step; LIMN_RECORD_SNAPSHOT=1 writes it first."""
        if os.environ.get("LIMN_RECORD_SNAPSHOT") == "1":
            path.write_text(json.dumps(self.seen, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        recorded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([s["step"] for s in self.seen], [s["step"] for s in recorded])
        for got, want in zip(self.seen, recorded, strict=True):
            self.assertEqual(got, want, got["step"])


class ContractSnapshot(SnapshotBase):
    """The recorded pin flow; see the module docstring."""

    def test_the_pin_flow_answers_as_recorded(self):
        """Every answer and pins.md along the flow equal the recorded snapshot."""
        main = str(self.main)
        a = self.step(
            "person adds a fix pin",
            "POST",
            "/api/pin",
            {"file": main, "lo": 4, "hi": 5, "page": 1, "note": "tighten this sentence"},
            ALICE,
        )["id"]
        b = self.step(
            "person asks a question",
            "POST",
            "/api/pin",
            {
                "file": main,
                "lo": 8,
                "hi": 8,
                "page": 1,
                "note": "why this word?",
                "kind_req": "question",
                "quote": "betaunique",
            },
            BOB,
        )["id"]
        c = self.step(
            "agent adds a pin",
            "POST",
            "/api/pin",
            {"file": main, "lo": 12, "hi": 16, "page": 1, "note": "table caption"},
        )["id"]
        self.step("agent claims", "POST", "/api/pins/%d/claim" % a, {"ttl_min": 30, "eta_min": 10})
        self.step("agent answers the question", "POST", "/api/pins/%d/reply" % b, {"text": "it is the defined term"})
        self.step(
            "agent closes with reply, ref and changes",
            "POST",
            "/api/pins/%d/close" % a,
            {"reply": "shortened", "ref": "PR #1 (abc1234)", "changes": [{"file": main, "lo": 4, "hi": 5}]},
        )
        self.step("agent may not confirm", "POST", "/api/pins/%d/confirm" % a, {})
        self.step("claim on a closed pin", "POST", "/api/pins/%d/claim" % a, {"ttl_min": 30})
        self.step("person confirms", "POST", "/api/pins/%d/confirm" % a, {}, ALICE)
        self.step("agent closes the third pin", "POST", "/api/pins/%d/close" % c, {"reply": "done"})
        self.step("person reopens it", "POST", "/api/pins/%d/reopen" % c, {"reason": "caption still long"}, BOB)
        self.step(
            "person edits the question",
            "POST",
            "/api/pins/%d/edit" % b,
            {"note": "why this word here?", "base_rev": self.pin(b)["rev"]},
            BOB,
        )
        self.step("stale edit", "POST", "/api/pins/%d/edit" % b, {"note": "x", "base_rev": 1}, BOB)
        self.step("person drops the third pin", "POST", "/api/pins/%d/drop" % c, {}, ALICE)
        self.step("the Trash", "GET", "/api/pins/dropped")
        self.step("person restores it", "POST", "/api/pins/%d/restore" % c, {}, ALICE)
        self.step("missing pin", "POST", "/api/pins/999/close", {})
        self.step("GET /pins.md", "GET", "/pins.md")
        self.step("GET /api/pins", "GET", "/api/pins")
        self.step("GET /api/pins?all=1", "GET", "/api/pins?all=1")
        self.step("GET /api/pins/<a>", "GET", "/api/pins/%d" % a)
        self.assert_recorded(SNAPSHOT)


FIGURE_SNAPSHOT = Path(__file__).resolve().parents[2] / "tests" / "data" / "contract_snapshot_figure.json"


class FigureContractSnapshot(SnapshotBase):
    """The figure flow, recorded in tests/data/contract_snapshot_figure.json: a map pick and its pin, an agent's pin
    without el, a pick on an element drawn without code and its region pin, pins.md and the pin list, then a re-render
    that moves one element and removes the other (read-time mark and el_sync, 요소 잃음). pdftotext answers no text,
    so the fallback's quote does not depend on the machine."""

    def setUp(self):
        """The pinned clocks; a LaTeX document ms and figure document fig with BUILD1 on screen; the scripts' mtime
        T0."""
        super().setUp()
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), self.fig])
        self.addCleanup(ps.APP.set_docs, None)
        write_build(self.fig, BUILD1, b2_map())
        for path in (self.fig.src / "src" / "B2_calendar.py", self.fig.src / "lib" / "components.py"):
            os.utime(path, (T0, T0))
        patcher = mock.patch.object(pick_source, "region_text", return_value="")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_figure_pin_flow_answers_as_recorded(self):
        """Every answer and pins.md along the figure flow equal the recorded snapshot."""
        x0, y0, x1, y1 = JULY_BOX
        july = self.step(
            "figure: person picks the July cell",
            "POST",
            "/api/pick",
            {
                "doc": "fig",
                "page": 1,
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "frac": [0.479, 0.198, 0.049, 0.073],
                "pdf_build": BUILD1,
            },
            ALICE,
        )
        body = {
            k: july[k]
            for k in (
                "file",
                "name",
                "page",
                "lo",
                "hi",
                "raw_lo",
                "raw_hi",
                "kind",
                "via",
                "score",
                "frac",
                "quote",
                "pdf_build",
                "el",
            )
        }
        body.update(doc="fig", scope=july["default_level"], note="글자를 키워 줘")
        self.step("figure: person pins the element", "POST", "/api/pin", body, ALICE)
        self.step(
            "figure: agent pins lines without el",
            "POST",
            "/api/pin",
            {"file": SCRIPT, "lo": 20, "hi": 22, "note": "선 굵기"},
        )
        x0, y0, x1, y1 = AUGUST_BOX
        august = self.step(
            "figure: person picks the August cell drawn without code",
            "POST",
            "/api/pick",
            {"doc": "fig", "page": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "pdf_build": BUILD1},
            BOB,
        )
        self.step(
            "figure: person pins the August cell as a region",
            "POST",
            "/api/pin",
            {
                "doc": "fig",
                "page": 1,
                "frac": august["frac"],
                "el": august["el"],
                "pdf_build": BUILD1,
                "note": "색을 바꿔 줘",
            },
            BOB,
        )
        self.step("figure: GET /pins.md", "GET", "/pins.md")
        self.step("figure: GET /api/pins", "GET", "/api/pins")
        write_build(self.fig, BUILD2, b2_map(july=(0.4, 0.18, 0.07, 0.12), august=False))
        self.step("figure: re-rendered, GET /api/pins", "GET", "/api/pins")
        self.step("figure: re-rendered, GET /pins.md", "GET", "/pins.md")
        self.assert_recorded(FIGURE_SNAPSHOT)


VERDICT_SNAPSHOT = Path(__file__).resolve().parents[2] / "tests" / "data" / "verdict_snapshot.json"
# The word files of the verdict flow: the LaTeX document's (page is ignored there), the figure document's with labels.
MS_WORDS = {
    "format": "limn-verdicts/1",
    "page": True,
    "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}],
}
FIG_WORDS = {
    "format": "limn-verdicts/1",
    "page": True,
    "verdicts": [{"key": "채택", "label": "본문으로"}, {"key": "보류", "label": "후보로"}],
}


class VerdictContractSnapshot(SnapshotBase):
    """The verdict flow, recorded in tests/data/verdict_snapshot.json (docs/superpowers/specs/2026-10-26-verdict-pins.md):
    three documents - LaTeX ms, figure fig (two pages on BUILD1) and view-only PDF rv - of which ms and fig declare
    verdict words; the document list with them; verdict pins by people on each kind (rv once it has words), whole
    figure and whole page included; every creation refusal in turn; a claim; the edit rule; an agent's close; then
    pins.md, the pin lists and one pin. Every file's mtime is T0, so the document list does not depend on when the
    test ran. The two older flows never meet a word file, and their snapshots stay byte for byte as they were."""

    def setUp(self):
        """The pinned clocks; the three documents with BUILD1 on screen; word files for ms and fig; every manuscript
        file's mtime T0."""
        super().setUp()
        self.ms, self.fig, self.rv = viewer_docs(ps.APP, self.src)
        self.addCleanup(ps.APP.set_docs, None)
        for doc, words in ((self.ms, MS_WORDS), (self.fig, FIG_WORDS)):
            verdicts_path(doc).write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
        for path in self.src.rglob("*"):
            os.utime(path, (T0, T0), follow_symlinks=False)

    def test_the_verdict_flow_answers_as_recorded(self):
        """Every answer and pins.md along the verdict flow equal the recorded snapshot."""
        main = str(self.main)
        root = {"id": "B2", "path": ["B2"]}
        figure = {"doc": "fig", "file": SCRIPT, "lo": 12, "hi": 140, "page": 1, "scope": "fig", "pdf_build": BUILD1}
        self.step("verdicts: GET /api/docs", "GET", "/api/docs", headers=ALICE)
        a = self.step(
            "verdicts: person picks 채택 for lines, no memo",
            "POST",
            "/api/pin",
            {"doc": "ms", "file": main, "lo": 4, "hi": 5, "page": 1, "verdict": "채택"},
            ALICE,
        )["id"]
        b = self.step(
            "verdicts: person picks 보류 for the whole figure",
            "POST",
            "/api/pin",
            dict(figure, el=root, verdict="보류", note="다음 판에서 다시 본다"),
            BOB,
        )["id"]
        self.step(
            "verdicts: the view-only PDF has no words",
            "POST",
            "/api/pin",
            {"doc": "rv", "page": 2, "frac": [0, 0, 1, 1], "pdf_build": BUILD1, "verdict": "삭제"},
            ALICE,
        )
        verdicts_path(self.rv).write_text(json.dumps(MS_WORDS, ensure_ascii=False), encoding="utf-8")
        c = self.step(
            "verdicts: person picks 삭제 for the whole PDF page",
            "POST",
            "/api/pin",
            {"doc": "rv", "page": 2, "frac": [0, 0, 1, 1], "pdf_build": BUILD1, "verdict": "삭제"},
            ALICE,
        )["id"]
        self.step(
            "verdicts: agent may not make one",
            "POST",
            "/api/pin",
            {"doc": "ms", "file": main, "lo": 8, "hi": 8, "page": 1, "verdict": "채택"},
        )
        self.step(
            "verdicts: a word the document does not declare",
            "POST",
            "/api/pin",
            {"doc": "fig", "file": SCRIPT, "lo": 12, "hi": 140, "page": 1, "el": root, "verdict": "삭제"},
            BOB,
        )
        self.step(
            "verdicts: a question with a verdict",
            "POST",
            "/api/pin",
            {"doc": "ms", "file": main, "lo": 8, "hi": 8, "page": 1, "verdict": "보류", "kind_req": "question"},
            BOB,
        )
        self.step(
            "verdicts: a figure that is not the page's root",
            "POST",
            "/api/pin",
            dict(figure, el={"id": "B3", "path": ["B3"]}, verdict="채택"),
            BOB,
        )
        self.step("verdicts: agent claims the figure verdict", "POST", "/api/pins/%d/claim" % b, {"eta_min": 10})
        self.step(
            "verdicts: agent may not move a verdict pin",
            "POST",
            "/api/pins/%d/edit" % b,
            {"lo": 80, "hi": 97, "base_rev": 0},
        )
        self.step(
            "verdicts: agent rewrites its memo",
            "POST",
            "/api/pins/%d/edit" % b,
            {"note": "후보 절의 3번째", "base_rev": self.pin(b)["rev"]},
        )
        d = self.step(
            "verdicts: person adds an ordinary pin",
            "POST",
            "/api/pin",
            {"doc": "ms", "file": main, "lo": 12, "hi": 16, "page": 1, "note": "표 제목"},
            ALICE,
        )["id"]
        self.step(
            "verdicts: an edit may not give a pin a verdict",
            "POST",
            "/api/pins/%d/edit" % d,
            {"verdict": "채택", "base_rev": 0},
            ALICE,
        )
        self.step(
            "verdicts: agent closes the lines verdict",
            "POST",
            "/api/pins/%d/close" % a,
            {"reply": "대상: intro-1\n본문에 넣었습니다", "ref": "PR #3 (abc1234)"},
        )
        self.step("verdicts: GET /pins.md", "GET", "/pins.md")
        self.step("verdicts: GET /api/pins", "GET", "/api/pins")
        self.step("verdicts: GET /api/pins?all=1", "GET", "/api/pins?all=1")
        self.step("verdicts: GET /api/pins/<c>", "GET", "/api/pins/%d" % c)
        self.assert_recorded(VERDICT_SNAPSHOT)


if __name__ == "__main__":
    unittest.main()
