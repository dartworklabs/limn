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

from limn.pins import model

from helpers import VIEWER

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

    type_text is a primitive (string, number, boolean), an interface name, an inline object type, or any of those
    with `[]`; an interface's fields are checked against value's keys, recursively."""
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
