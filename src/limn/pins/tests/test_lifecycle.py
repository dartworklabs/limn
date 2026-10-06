"""Shared pin predicates and purity boundaries remain independent of mutation features."""

import ast
import subprocess
import sys
import unittest
from pathlib import Path

import limn.pins
from limn.pins.lifecycle.rules import Replied, evolve_reply
from limn.pins.mentions import thread_round
from limn.pins.model import Claim as ClaimValue, DonePin, OpenPin, ReviewPin, parse_pin
from limn.pins.thread import claim_holds, pin_reopened_in_round, round_marks, thread_message

from helpers_pin_rules import ALICE_PERSON, AT, NOW

PINS_DIR = Path(limn.pins.__file__).parent


PURE_IMPORTS = {
    "__future__",
    "collections.abc",
    "collections",
    "dataclasses",
    "datetime",
    "math",
    "re",
    "typing",
    "limn.pins.needs",  # the slice's own Protocols for the injected build facts; itself checked below
    "limn.pins.element",  # a figure pin's el shape; pure (src/limn/pins/tests/test_element.py)
    "limn.pins.model",
    "limn.pins.thread",
    "limn.pins.location.position",
    "limn.pins.editing.values",
    "limn.platform.values",
    "limn.platform.text",
    "limn.security.values",
    "limn.pins.mentions",  # the @-tag rules view.py reads; pure (src/limn/collaboration/tests/test_mentions.py checks it)
    "limn.pins.revision",  # the stored `changes` shape record.py checks; pure (src/limn/pins/tests/test_scope.py)
    "posixpath",  # record.py's isabs: string work only (os.path is posixpath on POSIX)
    "types",  # MappingProxyType freezes a validated close command's changes without I/O.
    "limn.security.guidance",
    "limn.pins.location.mapping",
}  # the last two: pure text modules render.py uses (checked below)


PURE_TEXT_IMPORTS = {
    "__future__",
    "collections.abc",
    "dataclasses",
    "typing",
    "re",
    "shlex",
    "pathlib",
    "limn.platform.values",
    "limn.platform.text",
    "limn.security.values",
}

# What limn.pins.needs may import - declarations only: no feature, no effect.
NEEDS_IMPORTS = {
    "__future__",
    "collections.abc",
    "pathlib",
    "typing",
    "limn.pins.element",  # the element box shape; pure (src/limn/pins/tests/test_element.py)
    "limn.runtime.documents",  # Doc, the argument of every build question
    "limn.web.parse",  # DocumentFacts, the boundary type one question answers; under TYPE_CHECKING only (checked below)
}


class Purity(unittest.TestCase):
    """The shared pin domain and feature mutation rules stay free of I/O, clocks and the server."""

    def test_modules_import_only_pure_modules(self):
        """A file, subprocess, time or HTTP import would put an effect inside the domain (architecture.md stop signal)."""
        for path in (
            *(
                PINS_DIR / name
                for name in (
                    "model.py",
                    "record.py",
                    "thread.py",
                    "revision.py",
                    "retention.py",
                    "mentions.py",
                    "location/position.py",
                    "listing/render.py",
                    "listing/projection.py",
                    "editing/values.py",
                )
            ),
            PINS_DIR.parent / "pins/claims/rules.py",
            PINS_DIR.parent / "pins/trash/rules.py",
            PINS_DIR.parent / "pins/lifecycle/rules.py",
            PINS_DIR.parent / "pins/editing/rules.py",
        ):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported.add(node.module or "")
            self.assertLessEqual(imported, PURE_IMPORTS, path.name)

    def test_text_modules_the_package_imports_are_pure_too(self):
        """limn.security.guidance and limn.pins.location.mapping (imported by render.py) do string work only; from pathlib only PurePath."""
        for path in (PINS_DIR.parent / "security/guidance.py", PINS_DIR.parent / "pins/location/mapping.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported, from_pathlib = set(), set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported.add(node.module or "")
                    if node.module == "pathlib":
                        from_pathlib |= {a.name for a in node.names}
            self.assertLessEqual(imported, PURE_TEXT_IMPORTS, path.name)
            self.assertLessEqual(from_pathlib, {"PurePath"}, path.name)
            self.assertNotIn("pathlib", {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names})


class NeedsPurity(unittest.TestCase):
    """The pure pin modules name the build facts they are handed through the slice's own declarations
    (limn.pins.needs), never through another feature's surface: the purity above holds as long as that module only
    declares."""

    def test_the_needs_module_imports_no_feature_and_no_effect(self):
        """needs.py imports typing helpers, the pure element shape and the two boundary types its questions name - no
        feature package and no module that does I/O."""
        tree = ast.parse((PINS_DIR / "needs.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertLessEqual(imported, NEEDS_IMPORTS)

    def test_loading_the_needs_module_loads_no_http_or_file_module(self):
        """Importing needs.py in a fresh interpreter loads neither the HTTP layer nor the file module: the boundary
        type it names (limn.web.parse.DocumentFacts) is imported for type checking only, so the pure pin modules
        that name a build fact do not pull those in at run time."""
        code = "import sys, limn.pins.needs; print(*sorted(m for m in sys.modules if m.startswith('limn.')))"
        loaded = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split()
        self.assertIn("limn.pins.needs", loaded)
        self.assertEqual([m for m in loaded if m.startswith("limn.web") or m == "limn.platform.files"], [])


class States(unittest.TestCase):
    """parse_pin() follows pin_state(): the state is computed from done/review, never stored."""

    def test_open_when_not_done(self):
        """A record without done, or with done false, is open."""
        self.assertIsInstance(parse_pin({"id": 1}), OpenPin)
        self.assertIsInstance(parse_pin({"id": 1, "done": False, "review": True}), OpenPin)

    def test_review_only_when_done_and_review_is_true(self):
        """review must be the boolean true; a truthy string does not make a pin await review."""
        self.assertIsInstance(parse_pin({"done": True, "review": True}), ReviewPin)
        self.assertIsInstance(parse_pin({"done": True, "review": "yes"}), DonePin)

    def test_legacy_done_without_review_is_done(self):
        """A done record from before review existed stays done - reading it never migrates it."""
        self.assertIsInstance(parse_pin({"done": True}), DonePin)


class ClaimTransitions(unittest.TestCase):
    """Shared claim display and lifted claim expiry agree for valid open-pin claims."""

    def test_claim_holds_only_until_claim_until(self):
        """A claim holds while claim_until is a number in the future."""
        self.assertTrue(claim_holds({"claim_until": NOW + 1}, NOW))
        self.assertFalse(claim_holds({"claim_until": NOW}, NOW))
        self.assertFalse(claim_holds({"claim_until": True}, NOW))

    def test_the_record_and_the_lifted_claim_share_one_expiry_rule(self):
        """claim_holds on a record and Claim.holds on its claim agree for every claim_until an open pin can lift."""
        for until in (NOW + 1, int(NOW) + 1, NOW, NOW - 1, None):
            record = {"claimed_by": {"login": "a"}, "claim_until": until}
            lifted = OpenPin.from_record(record).claim
            self.assertIsInstance(lifted, ClaimValue)
            self.assertEqual(claim_holds(record, NOW), lifted.holds(NOW), until)


class ThreadMessage(unittest.TestCase):
    """Thread entry ids are one past the largest integer id and never reused."""

    def test_id_skips_non_integer_ids(self):
        """Booleans and strings are not ids (the entry keeps them unlifted); the next id follows the largest real one."""
        thread = parse_pin({"id": 1, "thread": [{"id": 3}, {"id": True}, {"id": "9"}, {}]}).core.thread
        self.assertEqual(thread_message(thread, {"login": "a", "name": "A"}, AT)["id"], 4)
        self.assertEqual(thread_message(None, {"login": "a", "name": "A"}, AT)["id"], 1)

    def test_a_transition_keeps_every_earlier_entry_as_stored(self):
        """A reply appends its entry after the earlier ones, written back byte for byte - unknown fields, unlifted
        parts and field order included - and a thread that could not be lifted counts as none."""
        earlier = [{"text": "t", "id": 2, "x": [1], "at": "t", "by": {"login": "b"}}, {"id": "7", "ev": "vote"}]
        pin = parse_pin({"id": 1, "thread": earlier, "rev": 1})
        replied = evolve_reply(pin, Replied(ALICE_PERSON, AT, "hi", ()))
        self.assertEqual(replied.record["thread"][:2], earlier)
        self.assertEqual(
            [list(entry) for entry in replied.record["thread"]],
            [["text", "id", "x", "at", "by"], ["id", "ev"], ["id", "by", "at", "text"]],
        )
        self.assertEqual(replied.record["thread"][2]["id"], 3)
        junk = parse_pin({"id": 1, "thread": [{"id": 5}, "junk"]})
        self.assertEqual(evolve_reply(junk, Replied(ALICE_PERSON, AT, "hi", ())).record["thread"][0]["id"], 1)

    def test_optional_fields_only_when_given(self):
        """ref and mentions appear only when passed; an empty text is stored as ''."""
        msg = thread_message(None, {"login": "a", "name": "A"}, AT, text="", ref="PR #1 (abc)", mentions=["b"])
        self.assertEqual(
            msg,
            {"id": 1, "by": {"login": "a", "name": "A"}, "at": AT, "text": "", "ref": "PR #1 (abc)", "mentions": ["b"]},
        )


class ReopenedInRound(unittest.TestCase):
    """pin_reopened_in_round: pins.md's "reopened" marker - a reopen after the last close, whatever else follows."""

    def entry(self, i, ev=None):
        """Thread entry i as stored, a state-transition mark when ev is given."""
        return thread_message([], {"login": "a", "name": "A"}, AT, "t%d" % i, ev=ev) | {"id": i}

    def thread(self, th):
        """The typed thread (PinCore.thread) a stored thread value parses to; None when it is not a list of objects."""
        return parse_pin({"thread": th}).core.thread

    def test_a_reopen_after_the_last_close_counts_even_past_a_confirm(self):
        """close, confirm, reopen and a reply: reopened. The old rule (the round's first post is a reopen) missed it."""
        th = [self.entry(1, "close"), self.entry(2, "confirm"), self.entry(3, "reopen"), self.entry(4)]
        self.assertTrue(pin_reopened_in_round(self.thread(th)))

    def test_closed_again_after_the_reopen_or_never_reopened_does_not(self):
        """reopen then close, a close alone, only replies, no thread and a malformed one (which parses to none): not
        reopened."""
        for th in (
            [self.entry(1, "close"), self.entry(2, "reopen"), self.entry(3, "close")],
            [self.entry(1, "close")],
            [self.entry(1), self.entry(2)],
            None,
            "x",
            ["x", 3],
        ):
            self.assertFalse(pin_reopened_in_round(self.thread(th)), th)
        self.assertFalse(pin_reopened_in_round(None))

    def test_a_reopen_without_any_close_counts(self):
        """A legacy thread that lost its close still shows the reopen."""
        self.assertTrue(pin_reopened_in_round(self.thread([self.entry(1, "reopen")])))

    def test_round_marks_are_the_latest_close_and_reopen(self):
        """(last close, last reopen) by position in the thread, -1 for none; no thread has neither."""
        th = [self.entry(0), self.entry(1, "close"), self.entry(2, "reopen"), self.entry(3, "close"), self.entry(4)]
        self.assertEqual(round_marks(self.thread(th)), (3, 2))
        self.assertEqual(round_marks(self.thread([self.entry(1)])), (-1, -1))
        self.assertEqual(round_marks(None), (-1, -1))

    def test_the_marker_and_the_current_round_agree(self):
        """Whenever the marker says reopened, the current round (limn.pins.mentions.thread_round) starts at that reopen."""
        e = self.entry
        for th in (
            [e(1, "close"), e(2, "confirm"), e(3, "reopen"), e(4)],
            [e(1, "close"), e(2), e(3, "reopen")],
            [e(1, "reopen"), e(2, "close"), e(3)],
            [e(1), e(2)],
        ):
            thread = self.thread(th)
            starts_at_reopen = bool(thread_round(thread)) and thread_round(thread)[0].ev == "reopen"
            self.assertEqual(pin_reopened_in_round(thread), starts_at_reopen, th)


if __name__ == "__main__":
    unittest.main()
