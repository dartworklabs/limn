"""Verdict pins in the store (docs/superpowers/specs/2026-10-26-verdict-pins.md §핀 레코드): a verdict survives every
write of pins.jsonl in its place, byte for byte, and a stored value that is no verdict is kept as stored - read, served
and rewritten like any unknown field, never a broken line.

Run: uv run pytest -q src/limn/pins/tests/test_verdict_store.py
"""

import json

from limn.documents.verdicts import verdicts_path

from helpers import ps, records, write_records
from helpers_access import BOB, AccessBase

WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}]}


class VerdictInTheStore(AccessBase):
    """The real store and handler over a temporary state folder."""

    def setUp(self):
        """The word file next to main.tex."""
        super().setUp()
        verdicts_path(ps.APP.docs[0]).write_text(json.dumps(WORDS, ensure_ascii=False), encoding="utf-8")

    def stored_line(self, pid):
        """Pin pid's line in pins.jsonl, as bytes on disk."""
        return next(
            line for line in ps.APP.C.pins_jsonl.read_text(encoding="utf-8").splitlines() if '"id": %d,' % pid in line
        )

    def test_a_verdict_keeps_its_place_through_later_writes(self):
        """After an edit, a claim, a close and a reopen of the pin - each a transact() write - the verdict is still
        the record's field after file_rel, with its value."""
        code, d = self.call(
            "POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "verdict": "보류"}, headers=BOB
        )
        self.assertEqual(code, 200, d)
        pid = d["id"]
        steps = (
            ("edit", {"note": "다음 판에", "base_rev": 0}, BOB),
            ("claim", {"eta_min": 5}, None),
            ("close", {"reply": "대상: fig-1"}, None),
            ("reopen", {"reason": "다시"}, BOB),
        )
        for action, body, who in steps:
            with self.subTest(action=action):
                code, d = self.call("POST", "/api/pins/%d/%s" % (pid, action), body, headers=who)
                self.assertEqual(code, 200, d)
                record = json.loads(self.stored_line(pid))
                self.assertEqual(record["verdict"], "보류")
                keys = list(record)
                self.assertEqual(keys[keys.index("file_rel") + 1], "verdict")

    def test_a_stored_value_that_is_no_verdict_is_kept_and_served_as_stored(self):
        """Hand-edited verdicts 7 and "채택|보류" are no broken lines: the pins are read, GET /api/pins answers the values
        as stored, pins.md shows no verdict for them, and a rewrite (the re-sync that anchors them) keeps the values."""
        base = {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "n", "doc": "main", "rev": 0}
        write_records([dict(base, id=1, verdict=7), dict(base, id=2, verdict="채택|보류")])
        pins, bad = ps.APP.read_pins()
        self.assertEqual(bad, [])
        self.assertEqual([r["verdict"] for r in records(pins)], [7, "채택|보류"])
        code, listed = self.call("GET", "/api/pins", headers=BOB)
        self.assertEqual(code, 200, listed)
        self.assertEqual([p["verdict"] for p in listed], [7, "채택|보류"])
        self.assertNotIn("판정", ps.APP.C.pins_md.read_text(encoding="utf-8"))
        ps.APP.snapshot_pins()
        stored = [json.loads(line) for line in ps.APP.C.pins_jsonl.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["verdict"] for r in stored], [7, "채택|보류"])
