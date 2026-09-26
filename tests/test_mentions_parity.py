"""The viewer's @-tag reading (viewer/js) against the server's (limn.mentions), on one shared corpus.

The server is the source of truth (docs/handbook/api.md §@이름 풀기): resolve_mentions() decides whom a note, reply or
reopen reason tags. The viewer re-reads the same text before sending - mentionScan() drives the preview line under the
field ('@ 알림 Bob Park'), the reply outcome and the assignee choice - so a disagreement shows a tag that will not
notify anyone, or hides one that will (audit 2026-09-27: a name equal to its login's local part, a non-ASCII letter
before '@'). Every corpus case runs through both and the logins must be identical, in order.

The JS side is the served source pulled with extract_js_fn and run under node (skipped without node, a failure under
LIMN_TEST_REQUIRE_NODE=1).

Run: uv run pytest -q tests/test_mentions_parity.py
"""

import json
import os
import shutil
import unittest

from limn.mentions import resolve_mentions

from helpers import extract_js_fn, run_node

ALICE = {"login": "alice@example.com", "name": "Alice Kim"}
BOB_PARK = {"login": "bob@example.com", "name": "Bob Park"}
BOB_LEE = {"login": "bob.lee@example.com", "name": "Bob Lee"}
SEOJUN = {"login": "seojun@example.com", "name": "김서준"}
ROBIN = {"login": "rlee@example.com", "name": "Robin Lee"}
TEAM = [ALICE, BOB_PARK, BOB_LEE, SEOJUN, ROBIN]
# The audit's case (a): the display name is the login's local part, so two candidates lower-case to one token.
BOB_ALONE = [{"login": "bob@example.com", "name": "Bob"}]

# (label, people, text, hints). Hints are the logins the viewer carries in `mentions` (autocomplete picks).
CORPUS = [
    # the two divergences the audit found
    ("name equals the login's local part", BOB_ALONE, "@Bob 확인 부탁", []),
    ("name equals the local part, lower case", BOB_ALONE, "@bob.", []),
    ("non-ASCII letter before @", TEAM, "é@rlee 봐 주세요", []),
    # what each candidate is
    ("full name", TEAM, "@Alice Kim 확인", []),
    ("login", TEAM, "@alice@example.com 확인", []),
    ("login's local part", TEAM, "@rlee 봐 주세요", []),
    ("unique first word", TEAM, "@Alice 봐", []),
    ("case-insensitive", TEAM, "@ALICE KIM", []),
    ("Korean full name", TEAM, "@김서준 확인", []),
    ("Korean particle after the name", TEAM, "@김서준님 확인", []),
    ("part of a Korean name is no candidate", TEAM, "@서준 확인", []),
    ("longest candidate wins", TEAM, "@Alice Kimchi", []),
    # what may follow a name
    ("ASCII letter after an ASCII name", TEAM, "@Alicex", []),
    ("underscore after an ASCII name", TEAM, "@Alice_", []),
    ("digit after an ASCII name", TEAM, "@Alice1", []),
    ("punctuation after the name", TEAM, "@Alice, @Robin Lee.", []),
    ("closing bracket after the name", TEAM, "(@Alice)", []),
    # what may come before '@'
    ("start of text", TEAM, "@Alice", []),
    ("newline before @", TEAM, "메모\n@Alice", []),
    ("email address", TEAM, "mail a@alice", []),
    ("digit before @", TEAM, "1@alice", []),
    ("dot before @", TEAM, "x.@alice", []),
    ("underscore before @", TEAM, "x_@alice", []),
    ("hyphen before @", TEAM, "x-@alice", []),
    ("Korean letter before @", TEAM, "김@alice", []),
    ("Greek letter before @", TEAM, "Ω@alice", []),
    ("full-width digit before @", TEAM, "１@alice", []),
    ("astral letter before @ (two UTF-16 units)", TEAM, "𠀀@rlee", []),
    ("emoji before @ is not a letter", TEAM, "😀@alice", []),
    ("another @ before @", TEAM, "@@alice", []),
    ("slash before @", TEAM, "a/@alice", []),
    # people who share a candidate
    ("shared first word, no hint", TEAM, "@Bob 확인", []),
    ("shared first word, one hint", TEAM, "@Bob 확인", ["bob.lee@example.com"]),
    ("shared first word, both hinted", TEAM, "@Bob 확인", ["bob.lee@example.com", "bob@example.com"]),
    ("hint for someone not in the text", TEAM, "@Alice", ["bob@example.com"]),
    ("local part shared with first words", TEAM, "@bob 이거", ["bob@example.com"]),
    ("full names are never ambiguous", TEAM, "@Bob Park @Bob Lee", []),
    # order and duplicates
    ("first-seen order", TEAM, "@Robin Lee 그리고 @Alice Kim", []),
    ("duplicates once", TEAM, "@Alice @alice @Alice Kim @alice@example.com", []),
    ("unresolved words in between", TEAM, "@홍길동 @Alice @nobody", []),
    # names with unusual characters
    ("name with HTML characters", [{"login": "k@example.com", "name": "김<b>"}], "@김<b> 안녕", []),
    ("name spelling an HTML entity", [{"login": "lt@example.com", "name": "a&lt;b"}], "@a&lt;b 봐", []),
    ("name with regex characters", [{"login": "ab@example.com", "name": "A.B (x)"}], "@A.B (x) 봐", []),
    ("accented name", [{"login": "elodie@example.com", "name": "Élodie Martin"}], "@ÉLODIE 봐", []),
    ("one-character name is no candidate", [{"login": "x@example.com", "name": "X"}], "@X @x@example.com", []),
    ("one astral character is one character", [{"login": "c@example.com", "name": "𠀀"}], "@𠀀 봐", []),
    ("two astral characters are a name", [{"login": "cc@example.com", "name": "𠀀𠀁"}], "@𠀀𠀁 봐", []),
    ("double space in a name", [{"login": "bp@example.com", "name": "Bo  Park"}], "@Bo 와 @bo  park", []),
    # nothing to find
    ("empty text", TEAM, "", []),
    ("no @", TEAM, "그냥 메모", []),
    ("a lone @", TEAM, "@ 혼자", []),
    ("nobody known", [], "@Alice", []),
]

# The viewer functions mentionScan() reaches, pulled from the served page.
SCAN_FNS = ("mentionTokens", "mentionAfterWord", "mentionScan")


def server_logins(people, text, hints):
    """What the server records as the tags of text: resolve_mentions() over people keyed by login, with the hints."""
    return resolve_mentions(text, {p["login"]: p for p in people}, hints)


def viewer_scans(cases):
    """mentionScan(text, hints) for every (people, text, hints) case, run in one node process with PEOPLE set per case."""
    js = "\n".join(
        [
            "let PEOPLE=[];",
            *(extract_js_fn(n) for n in SCAN_FNS),
            "const CASES=%s;" % json.dumps(cases, ensure_ascii=False),
            "console.log(JSON.stringify(CASES.map(([people,text,hints])=>{PEOPLE=people;"
            " return mentionScan(text,new Set(hints));})));",
        ]
    )
    return json.loads(run_node(js))


class MentionParity(unittest.TestCase):
    """The viewer's mentionScan() finds exactly the logins the server's resolve_mentions() records, case by case."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 (CI), where a missing node is a failure."""
        if shutil.which("node"):
            return
        if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
            self.fail("node is required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
        self.skipTest("node is not installed")

    def test_the_viewer_and_the_server_resolve_the_corpus_alike(self):
        """Every case yields the same logins in the same order on both sides - the server's list is the oracle."""
        scans = viewer_scans([[people, text, hints] for _, people, text, hints in CORPUS])
        self.assertEqual(len(scans), len(CORPUS))
        for (label, people, text, hints), scan in zip(CORPUS, scans, strict=True):
            with self.subTest(label, text=text, hints=hints):
                self.assertEqual(scan["hit"], server_logins(people, text, hints))

    def test_the_audit_cases_are_what_the_server_says(self):
        """Pins the oracle for the two audited cases, so the parity above cannot pass by both sides drifting together:
        '@Bob' finds the person named Bob whose login is bob@..., and 'é@rlee' is part of a word, not a tag."""
        self.assertEqual(server_logins(BOB_ALONE, "@Bob 확인 부탁", []), ["bob@example.com"])
        self.assertEqual(server_logins(TEAM, "é@rlee 봐 주세요", []), [])

    def test_the_corpus_covers_both_answers(self):
        """The corpus is not trivially agreeing: it has cases that tag nobody, one person, several, and hint-picked."""
        found = [server_logins(people, text, hints) for _, people, text, hints in CORPUS]
        self.assertTrue(any(not f for f in found))
        self.assertTrue(any(len(f) == 1 for f in found))
        self.assertTrue(any(len(f) > 1 for f in found))
        self.assertIn(["bob.lee@example.com"], found)


if __name__ == "__main__":
    unittest.main()
