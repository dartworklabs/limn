"""The agent contract as one recorded snapshot: pins.md and the main API answers of a fixed pin flow, byte for byte.

A fixed sequence of requests - new pins by people and the agent, a question, a claim, replies, a close with a reply,
ref and changes, a confirm, a reopen, an edit, the Trash and back, and the refusals an agent meets (confirm by the
agent, a stale edit, a claim on a closed pin, a missing pin) - runs through the real handler with the clock, the time
zone and the paths pinned. Every answer (status and body), pins.md after every write, and at the end GET /pins.md,
GET /api/pins, GET /api/pins/<id> and GET /api/pins/dropped are compared with tests/data/contract_snapshot.json. The
snapshot was recorded from the server before stage 6 finished (docs/handbook/code-style-roadmap.md, stage 4 evidence),
so a refactor that changes any of these bytes fails here.

Paths are written as <ROOT> (the temporary folder), the clock is 2026-09-26 10:00:00 +09:00 whatever the machine's
zone. A deliberate contract change (docs/handbook/api.md, approved first) re-records the snapshot:
LIMN_RECORD_SNAPSHOT=1 uv run pytest -q tests/test_contract_snapshot.py - and the diff of the JSON is the change.

Run: uv run pytest -q tests/test_contract_snapshot.py
"""
import json
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from limn import build as limn_build, people as limn_people

from helpers import ps
from test_access import ALICE, BOB, AccessBase

SNAPSHOT = Path(__file__).parent / "data" / "contract_snapshot.json"
T0 = 1790384400.0                                   # 2026-09-26 10:00:00 +09:00
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


class ContractSnapshot(AccessBase):
    """The recorded pin flow; see the module docstring."""

    def setUp(self):
        """AccessBase's fresh server, with every clock the flow reads pinned to T0 in +09:00 (Asia/Seoul)."""
        super().setUp()
        # The store reads a stored wall time (dropped_at) in the machine's zone (the Trash's expires_ts), so the zone
        # itself is pinned too.
        zone = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Seoul"
        time.tzset()
        self.addCleanup(self.restore_zone, zone)
        for patcher in (mock.patch.object(ps, "now_str", return_value="2026-09-26 10:00:00"),
                        mock.patch("time.time", return_value=T0), mock.patch("time.strftime", frozen_strftime),
                        mock.patch.object(ps, "datetime", FrozenDateTime),
                        mock.patch.object(limn_build, "datetime", FrozenDateTime),
                        mock.patch.object(limn_people, "datetime", FrozenDateTime)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.utime(self.main, (T0, T0))                # a synced pin records its file's mtime (synced_at)
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
        if method == "POST" and ps.C.pins_md.exists():
            self.seen.append({"step": name + " -> pins.md", "body": self.text(ps.C.pins_md.read_bytes())})
        return data

    def test_the_pin_flow_answers_as_recorded(self):
        """Every answer and pins.md along the flow equal the recorded snapshot."""
        main = str(self.main)
        a = self.step("person adds a fix pin", "POST", "/api/pin",
                      {"file": main, "lo": 4, "hi": 5, "page": 1, "note": "tighten this sentence"}, ALICE)["id"]
        b = self.step("person asks a question", "POST", "/api/pin",
                      {"file": main, "lo": 8, "hi": 8, "page": 1, "note": "why this word?", "kind_req": "question",
                       "quote": "betaunique"}, BOB)["id"]
        c = self.step("agent adds a pin", "POST", "/api/pin",
                      {"file": main, "lo": 12, "hi": 16, "page": 1, "note": "table caption"})["id"]
        self.step("agent claims", "POST", "/api/pins/%d/claim" % a, {"ttl_min": 30, "eta_min": 10})
        self.step("agent answers the question", "POST", "/api/pins/%d/reply" % b, {"text": "it is the defined term"})
        self.step("agent closes with reply, ref and changes", "POST", "/api/pins/%d/close" % a,
                  {"reply": "shortened", "ref": "PR #1 (abc1234)", "changes": [{"file": main, "lo": 4, "hi": 5}]})
        self.step("agent may not confirm", "POST", "/api/pins/%d/confirm" % a, {})
        self.step("claim on a closed pin", "POST", "/api/pins/%d/claim" % a, {"ttl_min": 30})
        self.step("person confirms", "POST", "/api/pins/%d/confirm" % a, {}, ALICE)
        self.step("agent closes the third pin", "POST", "/api/pins/%d/close" % c, {"reply": "done"})
        self.step("person reopens it", "POST", "/api/pins/%d/reopen" % c, {"reason": "caption still long"}, BOB)
        self.step("person edits the question", "POST", "/api/pins/%d/edit" % b,
                  {"note": "why this word here?", "base_rev": self.pin(b)["rev"]}, BOB)
        self.step("stale edit", "POST", "/api/pins/%d/edit" % b, {"note": "x", "base_rev": 1}, BOB)
        self.step("person drops the third pin", "POST", "/api/pins/%d/drop" % c, {}, ALICE)
        self.step("the Trash", "GET", "/api/pins/dropped")
        self.step("person restores it", "POST", "/api/pins/%d/restore" % c, {}, ALICE)
        self.step("missing pin", "POST", "/api/pins/999/close", {})
        self.step("GET /pins.md", "GET", "/pins.md")
        self.step("GET /api/pins", "GET", "/api/pins")
        self.step("GET /api/pins?all=1", "GET", "/api/pins?all=1")
        self.step("GET /api/pins/<a>", "GET", "/api/pins/%d" % a)
        if os.environ.get("LIMN_RECORD_SNAPSHOT") == "1":
            SNAPSHOT.write_text(json.dumps(self.seen, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        recorded = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual([s["step"] for s in self.seen], [s["step"] for s in recorded])
        for got, want in zip(self.seen, recorded, strict=True):
            self.assertEqual(got, want, got["step"])


if __name__ == "__main__":
    unittest.main()
