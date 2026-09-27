"""limn.web.parse on its own: each request parser returns the parsed value or the first refused field, in the order
the server has always checked them, with the exact 400 message and reason of the agent contract.

Every route's statuses and bodies are also pinned end to end through the handler (test_server.py, test_access.py and
the feature files). Here the parsers are called directly; the manuscript facts a location parser reads come from a
fake DocumentFacts, so each rule is seen without a server, a build or a real page image. EditAddParsing at the end
feeds them server.py's document facts instead, and checks the statuses the handler answers them with.

Run: uv run pytest -q tests/test_web_parse.py
"""

import json
import tempfile
import unittest
from pathlib import Path

from limn.access import LOCAL_ACTOR
from limn.features.builds import input as builds_input
from limn.features.pins.claims import input as claims_input
from limn.features.pins.editing import input as editing_input, location as editing_location
from limn.features.pins.lifecycle import input as lifecycle_input
from limn.features.pins.listing import input as listing_input
from limn.features.pins.location import input as location_input
from limn.features.pins.trash import input as trash_input
from limn.files import BadPath, NotAFile, OutsideTree, file_in_tree
from limn.pins.edit import LinePlace, PinEdited, RegionPlace, evolve_edit
from limn.pins.lifecycle import CloseRequest
from limn.pins.model import Agent, OpenPin
from limn.web import parse
from limn.web.errors import InputRejected

from helpers import Base, jreq, ps, split_resp

# A state folder outside every temporary tree here: the tree rule then takes nothing away for it.
NO_STATE = Path("/nonexistent-limn-state")


class Facts:
    """A DocumentFacts over a real temporary manuscript tree, with the pages and builds given in memory."""

    def __init__(self, root: Path, is_pdf: bool = False, pages: dict | None = None, current: str = "pages"):
        """root is the tree; pages maps a build name to its page sizes; current names the build on screen."""
        self.key, self.is_pdf, self.root, self.state = "rev" if is_pdf else "main", is_pdf, root, NO_STATE
        self.pdf = root / "review.pdf"
        self._pages = pages if pages is not None else {"pages": [(600.0, 800.0), (600.0, 800.0)]}
        self._current = current

    def lines(self, path: Path) -> list:
        """The file's lines, [] when it cannot be read as UTF-8."""
        try:
            return path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return []

    def page_count(self, build: str | None) -> int:
        """Pages of build (the one on screen for None or a gone build)."""
        return len(self._pages.get(build or self._current, self._pages[self._current]))

    def current_build(self) -> str:
        """The build on screen."""
        return self._current

    def pick_pages(self, build: str | None) -> tuple | None:
        """(directory, sizes) of build, or of the one on screen for None; None for a gone build."""
        name = self._current if build is None else build
        if name not in self._pages:
            return None
        return self.root / name, self._pages[name]


class Tree(unittest.TestCase):
    """A manuscript tree with a 5-line main.tex and an unreadable file."""

    def setUp(self):
        """Create the tree."""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "main.tex").write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
        (self.root / "bin.tex").write_bytes(b"\xff\xfe")
        self.facts = Facts(self.root)

    def tearDown(self):
        """Remove the tree."""
        self.tmp.cleanup()


class FileInTree(Tree):
    """limn.files.file_in_tree: the one rule for a named path inside the manuscript tree, shared by parse and pick."""

    def test_a_file_in_the_tree_or_why_not(self):
        """Absolute and relative names give root/<rel>; a bad value, a path outside and a missing file are refused apart."""
        self.assertEqual(file_in_tree("main.tex", self.root, NO_STATE), self.root / "main.tex")
        self.assertEqual(file_in_tree(str(self.root / "main.tex"), self.root, NO_STATE), self.root / "main.tex")
        for bad in (None, 3, "", "a\x00b", "x" * 4097):
            self.assertEqual(file_in_tree(bad, self.root, NO_STATE), BadPath(), bad)
        self.assertEqual(file_in_tree("/etc/passwd", self.root, NO_STATE), OutsideTree())
        self.assertEqual(file_in_tree("../x", self.root, NO_STATE), OutsideTree())
        self.assertEqual(file_in_tree("nope.tex", self.root, NO_STATE), NotAFile())
        self.assertEqual(file_in_tree(".", self.root, NO_STATE), NotAFile())

    def test_a_dot_named_part_is_outside_the_tree(self):
        """A path whose part below the root starts with '.' (.git, .env, .ssh, .latexmkrc, ...) is OutsideTree even
        though the file exists: such files are repository or machine secrets, never manuscript text a pin may quote.
        The rule is applied after symlinks are resolved, so a normal name that leads into .git is refused too, and a
        link leading out of the tree stays refused."""
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("[remote]\n", encoding="utf-8")
        (self.root / "sub" / ".git").mkdir(parents=True)
        (self.root / "sub" / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=x\n", encoding="utf-8")
        (self.root / "notes.tex").symlink_to(self.root / ".git" / "config")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / "secret.txt").write_text("s\n", encoding="utf-8")
        (self.root / "away.tex").symlink_to(Path(outside.name) / "secret.txt")
        for name in (".git/config", "sub/.git/config", ".env", "notes.tex", "away.tex", str(self.root / ".env")):
            self.assertEqual(file_in_tree(name, self.root, NO_STATE), OutsideTree(), name)
        self.assertEqual(
            parse.source_file(".git/config", self.root, NO_STATE),
            InputRejected("원고 디렉토리 밖의 파일입니다: .git/config", "file_outside_manuscript"),
        )

    def test_dots_elsewhere_in_a_name_or_above_the_root_are_allowed(self):
        """Only a part below the root is judged: a dotted file name (a.b.tex) and a root that itself lies under a
        dot folder (~/.local/paper) still name files in the tree."""
        (self.root / "a.b.tex").write_text("x\n", encoding="utf-8")
        self.assertEqual(file_in_tree("a.b.tex", self.root, NO_STATE), self.root / "a.b.tex")
        hidden_root = self.root / ".local" / "paper"
        hidden_root.mkdir(parents=True)
        (hidden_root / "main.tex").write_text("x\n", encoding="utf-8")
        self.assertEqual(file_in_tree("main.tex", hidden_root, NO_STATE), hidden_root / "main.tex")

    def test_the_state_folder_inside_the_tree_is_outside_it(self):
        """--state-dir inside the manuscript under a normal name: every path in that folder (by relative or absolute
        name, through '..', or through a normal-looking link) is OutsideTree - it holds people.json, tokens.json's
        hashes, audit.jsonl and events.jsonl. The folder's neighbours stay in the tree, a same-prefixed sibling
        (limn-state2) included, because the rule compares path parts, not strings."""
        state = self.root / "limn-state"
        (state / "docs" / "main").mkdir(parents=True)
        for name in ("people.json", "tokens.json", "audit.jsonl", "events.jsonl", "docs/main/builds.json"):
            (state / name).write_text("{}\n", encoding="utf-8")
        (self.root / "notes.tex").symlink_to(state / "people.json")
        (self.root / "limn-state2").mkdir()
        (self.root / "limn-state2" / "a.tex").write_text("x\n", encoding="utf-8")
        for name in (
            "limn-state/people.json",
            "limn-state/tokens.json",
            "limn-state/audit.jsonl",
            "limn-state/events.jsonl",
            "limn-state/docs/main/builds.json",
            "limn-state/../limn-state/people.json",
            str(state / "tokens.json"),
            "notes.tex",
            "limn-state",
        ):
            self.assertEqual(file_in_tree(name, self.root, state), OutsideTree(), name)
        self.assertEqual(file_in_tree("main.tex", self.root, state), self.root / "main.tex")
        self.assertEqual(file_in_tree("limn-state2/a.tex", self.root, state), self.root / "limn-state2" / "a.tex")
        self.assertEqual(
            parse.source_file("limn-state/people.json", self.root, state),
            InputRejected("원고 디렉토리 밖의 파일입니다: limn-state/people.json", "file_outside_manuscript"),
        )

    def test_a_state_folder_reached_through_a_link_is_judged_resolved(self):
        """A --state-dir given as a link that resolves inside the tree is the same folder: its files are refused by
        their real names too."""
        (self.root / "real-state").mkdir()
        (self.root / "real-state" / "people.json").write_text("{}\n", encoding="utf-8")
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        link = Path(elsewhere.name) / "state-link"
        link.symlink_to(self.root / "real-state")
        self.assertEqual(file_in_tree("real-state/people.json", self.root, link), OutsideTree())

    def test_a_state_folder_beside_or_above_the_root_takes_nothing_away(self):
        """Only a state folder inside the tree is cut out of it. One beside the manuscript changes nothing, and so
        does one that holds the manuscript (--state-dir ~/work, --manuscript ~/work/paper): the state files are
        then outside the tree already. A state folder that is the root itself leaves nothing in the tree."""
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        beside = Path(elsewhere.name)
        self.assertEqual(file_in_tree("main.tex", self.root, beside), self.root / "main.tex")
        self.assertEqual(file_in_tree("main.tex", self.root, self.root.parent), self.root / "main.tex")
        self.assertEqual(file_in_tree("main.tex", self.root, self.root), OutsideTree())

    def test_source_file_answers_each_refusal_with_its_message(self):
        """The 400 texts name the path as sent."""
        self.assertEqual(
            parse.source_file(3, self.root, NO_STATE), InputRejected("file 이 올바르지 않습니다.", "bad_file")
        )
        self.assertEqual(
            parse.source_file("/etc/passwd", self.root, NO_STATE),
            InputRejected("원고 디렉토리 밖의 파일입니다: /etc/passwd", "file_outside_manuscript"),
        )
        self.assertEqual(
            parse.source_file("nope.tex", self.root, NO_STATE),
            InputRejected("원고 안에 그런 파일이 없습니다: nope.tex", "file_not_found"),
        )


class Fields(unittest.TestCase):
    """The field parsers that read the request alone."""

    def test_numbers(self):
        """An integral number (1.0 too) or a finite one; invalid and oversized numbers get a refusal."""
        self.assertEqual(parse.int_field(3.0, "lo"), 3)
        self.assertEqual(parse.int_field(True, "lo"), InputRejected("lo 는 정수여야 합니다.", "not_integer"))
        self.assertEqual(parse.int_field(1.5, "lo"), InputRejected("lo 는 정수여야 합니다.", "not_integer"))
        self.assertEqual(
            parse.num_field(float("inf"), "x0"), InputRejected("x0 는 유한한 숫자여야 합니다.", "not_number")
        )
        self.assertEqual(parse.num_field(2, "x0"), 2.0)
        self.assertEqual(parse.int_field(10**400, "lo"), InputRejected("lo 는 정수여야 합니다.", "not_integer"))
        self.assertEqual(parse.num_field(10**400, "x0"), InputRejected("x0 는 유한한 숫자여야 합니다.", "not_number"))
        self.assertEqual(claims_input.parse_claim_body({"ttl_min": 10**400}).reason, "not_integer")

    def test_closed_sets_come_back_narrowed_or_refused(self):
        """kind_req and scope: a member of the set comes back as is (typed as its Literal), None when absent, and
        anything else is the contract's 400 naming the whole set."""
        self.assertEqual(parse.parse_kind_req("question"), "question")
        self.assertIsNone(parse.parse_kind_req(None))
        self.assertEqual(
            parse.parse_kind_req("Question"), InputRejected("kind_req 는 fix|question 중 하나입니다.", "bad_kind_req")
        )
        self.assertEqual(parse.parse_scope("env2"), "env2")
        self.assertIsNone(parse.parse_scope(None))
        self.assertEqual(
            parse.parse_scope(["raw"]),
            InputRejected("scope 는 raw|para|env|env2|env3|lines 중 하나입니다.", "bad_scope"),
        )

    def test_thread_text_is_cleaned_then_checked(self):
        """Newlines are normalised and control characters dropped before the length and emptiness checks."""
        self.assertEqual(parse.parse_thread_text("a\r\nb\x00\x1b[1m\tc "), "a\nb[1m\tc")
        self.assertEqual(parse.parse_thread_text(None), InputRejected("text 가 필요합니다.", "text_required"))
        self.assertIsNone(parse.parse_thread_text(None, "reason", required=False))
        self.assertIsNone(parse.parse_thread_text(" \n", "reason", required=False))
        self.assertEqual(parse.parse_thread_text(" \n"), InputRejected("text 가 비어 있습니다.", "text_empty"))
        self.assertEqual(
            parse.parse_thread_text("x" * 1001, "reason"),
            InputRejected("reason 가 너무 깁니다(1000자 이하).", "text_too_long"),
        )
        self.assertEqual(lifecycle_input.parse_reply_text(3), InputRejected("text 는 문자열이어야 합니다.", "bad_text"))

    def test_flags_and_hints(self):
        """reopen/review are true, false or absent; hints are at most MENTION_MAX strings."""
        self.assertIsNone(lifecycle_input.parse_reopen_flag({}))
        self.assertEqual(
            lifecycle_input.parse_review_flag({"review": 1}),
            InputRejected("review 는 true/false 입니다.", "bad_review"),
        )
        self.assertEqual(parse.parse_mention_hints(["a"] * parse.MENTION_MAX), ["a"] * parse.MENTION_MAX)
        self.assertIsInstance(parse.parse_mention_hints(["a"] * (parse.MENTION_MAX + 1)), InputRejected)

    def test_close_body_blank_is_none(self):
        """reply/ref blank or absent are None; a CloseBody unpacks like the old (reply, ref) pair."""
        reply, ref = lifecycle_input.parse_close_body({"reply": " ", "ref": "PR #1"})
        self.assertEqual((reply, ref), (None, "PR #1"))

    def test_close_changes_resolve_inside_the_root(self):
        """Paths are resolved against the root and must stay in it; the first bad item is named."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            got = lifecycle_input.parse_close_changes([{"file": "a.tex", "lo": 1, "hi": 2}], root, NO_STATE)
            self.assertEqual(got, (lifecycle_input.CloseChange(str(root / "a.tex"), 1, 2),))
            self.assertEqual(got[0].record(), {"file": str(root / "a.tex"), "lo": 1, "hi": 2})
            self.assertIsNone(lifecycle_input.parse_close_changes([], root, NO_STATE))
            self.assertEqual(
                lifecycle_input.parse_close_changes(
                    [{"file": "a.tex", "lo": 1, "hi": 1}, {"file": "../b", "lo": 1, "hi": 1}], root, NO_STATE
                ),
                InputRejected(
                    "changes[1].file 은 원고 폴더(--manuscript) 안의 파일이어야 합니다.", "change_outside_manuscript"
                ),
            )

    def test_close_changes_refuse_a_dot_named_path(self):
        """A recorded change under a dot-named part (.git, .env) is refused like one outside the folder: the paths a
        close records feed the comparison diff every viewer may read, so they follow the tree rule of file_in_tree."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for name in (".env", "sub/.git/config", str(root / ".git" / "HEAD")):
                self.assertEqual(
                    lifecycle_input.parse_close_changes([{"file": name, "lo": 1, "hi": 1}], root, NO_STATE),
                    InputRejected(
                        "changes[0].file 은 원고 폴더(--manuscript) 안의 파일이어야 합니다.",
                        "change_outside_manuscript",
                    ),
                    name,
                )

    def test_close_request_checks_its_fields_in_order_and_ignores_the_rest(self):
        """parse_close refuses reply/ref, then changes, then review, then mentions - the first bad one is answered.
        Mentions are checked but not carried (a close tags nobody); a reopen's reason is not a close field and is
        ignored. Changes come back in their stored form."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            bad_changes = InputRejected('changes 는 [{"file", "lo", "hi"}] 목록이어야 합니다.', "bad_changes")
            bad_review = InputRejected("review 는 true/false 입니다.", "bad_review")
            bad_mentions = InputRejected("mentions 는 로그인 문자열 목록(10개 이하)입니다.", "bad_mentions")
            everything = {"reply": 1, "changes": 1, "review": 1, "mentions": 1}
            self.assertEqual(
                lifecycle_input.parse_close(everything, root, NO_STATE),
                InputRejected("reply 는 문자열이어야 합니다.", "bad_reply"),
            )
            self.assertEqual(lifecycle_input.parse_close(dict(everything, reply="x"), root, NO_STATE), bad_changes)
            self.assertEqual(
                lifecycle_input.parse_close({"changes": None, "review": 1, "mentions": 1}, root, NO_STATE), bad_review
            )
            self.assertEqual(lifecycle_input.parse_close({"review": True, "mentions": 1}, root, NO_STATE), bad_mentions)
            self.assertEqual(
                lifecycle_input.parse_close(
                    {
                        "reply": " fixed ",
                        "ref": " ",
                        "changes": [{"file": "a.tex", "lo": 2, "hi": 3}],
                        "review": False,
                        "mentions": ["bob@example.com"],
                        "reason": 5,
                    },
                    root,
                    NO_STATE,
                ),
                CloseRequest(" fixed ", None, ({"file": str(root / "a.tex"), "lo": 2, "hi": 3},), False),
            )
            self.assertEqual(lifecycle_input.parse_close({}, root, NO_STATE), CloseRequest())

    def test_reopen_body_checks_reason_then_mentions_and_ignores_the_rest(self):
        """parse_reopen refuses the reason before mentions; a blank reason is None; a close's reply, review or
        changes sent to reopen are ignored, however malformed."""
        self.assertEqual(
            lifecycle_input.parse_reopen({"reason": 3, "mentions": 1}),
            InputRejected("reason 는 문자열이어야 합니다.", "bad_text"),
        )
        self.assertEqual(
            lifecycle_input.parse_reopen({"reason": "again", "mentions": "bob"}),
            InputRejected("mentions 는 로그인 문자열 목록(10개 이하)입니다.", "bad_mentions"),
        )
        self.assertEqual(
            lifecycle_input.parse_reopen({"reason": " \n", "reply": 1, "review": "x", "changes": 7}),
            lifecycle_input.ReopenBody(None, []),
        )
        self.assertEqual(
            lifecycle_input.parse_reopen({"reason": "look @Bob", "mentions": ["bob@example.com"]}),
            ("look @Bob", ["bob@example.com"]),
        )

    def test_close_changes_refuse_a_path_in_the_state_folder(self):
        """A recorded change in a state folder inside the manuscript is refused like one outside the folder; a
        change beside it is recorded."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state = root / "limn-state"
            for name in ("limn-state/people.json", str(state / "audit.jsonl")):
                self.assertEqual(
                    lifecycle_input.parse_close_changes([{"file": name, "lo": 1, "hi": 1}], root, state),
                    InputRejected(
                        "changes[0].file 은 원고 폴더(--manuscript) 안의 파일이어야 합니다.",
                        "change_outside_manuscript",
                    ),
                    name,
                )
            self.assertEqual(
                lifecycle_input.parse_close_changes([{"file": "a.tex", "lo": 1, "hi": 1}], root, state),
                (lifecycle_input.CloseChange(str(root / "a.tex"), 1, 1),),
            )

    def test_claim_body_checks_eta_first_and_clamps(self):
        """eta_min is refused before ttl_min; values above the ceiling are clamped; ttl follows eta when absent."""
        self.assertEqual(
            claims_input.parse_claim_body({"eta_min": 0, "ttl_min": "x"}),
            InputRejected("eta_min 은 1 이상이어야 합니다(상한 240 를 넘으면 240 로 깎아 받습니다).", "too_small"),
        )
        self.assertEqual(claims_input.parse_claim_body({"eta_min": 10}), claims_input.ClaimBody(30, 10))
        self.assertEqual(claims_input.parse_claim_body({"ttl_min": 480, "eta_min": 241}), (120, 240))

    def test_revision_parameters(self):
        """The pin is parsed before the commit; POST names only commit, doc and pin, pin is a JSON integer, and the commit
        is a full lowercase SHA-1."""
        sha = "0123456789abcdef0123456789abcdef01234567"
        bad_commit = InputRejected("올바른 커밋 ID가 아닙니다.", "bad_commit")
        self.assertEqual(parse.parse_revision_query({"commit": [sha], "pin": ["12"]}), (sha, 12))
        self.assertEqual(parse.parse_revision_query({"commit": ["abc"], "pin": ["12"]}), bad_commit)
        self.assertEqual(parse.parse_revision_query({}), bad_commit)
        self.assertEqual(
            parse.parse_revision_query({"pin": ["0"]}),
            InputRejected("pin 은 핀 번호(양의 정수)여야 합니다.", "bad_pin"),
        )
        self.assertEqual(parse.parse_revision_build({"commit": sha.upper(), "pin": 3}), bad_commit)
        self.assertEqual(parse.parse_revision_build({"commit": 5}), bad_commit)
        self.assertEqual(parse.parse_revision_build({"commit": sha, "pin": 3}), (sha, 3))
        self.assertEqual(
            parse.parse_revision_build({"x": 1, "pin": "1"}),
            InputRejected("허용되지 않는 비교 PDF 요청 필드입니다.", "unknown_fields"),
        )
        self.assertEqual(
            parse.parse_revision_build({"pin": True}), InputRejected("pin 은 핀 번호(양의 정수)여야 합니다.", "bad_pin")
        )
        self.assertIsInstance(parse.parse_revision_build({"pin": 10**9}), InputRejected)

    def test_event_cursor_and_doc_key(self):
        """?ev= is int() of the text; ?doc= and the body's doc must agree, and the body's must be a string."""
        self.assertEqual(parse.parse_event_cursor(" 7 "), 7)
        self.assertIsNone(parse.parse_event_cursor(None))
        self.assertIsInstance(parse.parse_event_cursor("1.5"), InputRejected)
        self.assertEqual(parse.parse_doc_key({"doc": ["rev"]}, {"doc": "rev"}), "rev")
        self.assertEqual(parse.parse_doc_key({}, {"doc": ""}), "")
        self.assertIsNone(parse.parse_doc_key(None, None))
        self.assertEqual(parse.parse_doc_key({}, {"doc": 3}), InputRejected("doc 은 문자열이어야 합니다.", "bad_doc"))
        self.assertEqual(
            parse.parse_doc_key({"doc": ["a"]}, {"doc": "b"}),
            InputRejected("doc 이 주소(a)와 본문(b)에서 다릅니다.", "doc_mismatch"),
        )


class RouteRequests(unittest.TestCase):
    """The per-route request parsers the handler calls instead of reading a body field or a query parameter itself."""

    def test_a_flag_is_on_only_for_a_first_value_of_one(self):
        """parse_flag keeps the old `(q.get(x) or ["0"])[0] == "1"`: "1" first is on; absent, "0", "true", "" or a
        later "1" are off."""
        self.assertTrue(parse.parse_flag({"log": ["1", "0"]}, "log"))
        for q in ({}, {"log": ["0"]}, {"log": ["true"]}, {"log": [""]}, {"log": ["0", "1"]}, {"all": ["1"]}):
            with self.subTest(q=q):
                self.assertFalse(parse.parse_flag(q, "log"))

    def test_route_queries(self):
        """GET /api/pins, POST /api/rebuild, GET /pdf and GET /api/meta read their query only through these; none but
        the event cursor refuses anything."""
        self.assertEqual(
            listing_input.parse_pins_query({"all": ["1"], "doc": ["rev"]}), listing_input.PinsQuery(True, True)
        )
        self.assertEqual(listing_input.parse_pins_query({}), listing_input.PinsQuery(False, False))
        self.assertEqual(builds_input.parse_rebuild_query({"async": ["1"]}), builds_input.RebuildQuery(False, True))
        self.assertEqual(
            builds_input.parse_rebuild_query({"log": ["1"], "async": ["0"]}), builds_input.RebuildQuery(True, False)
        )
        self.assertEqual(builds_input.parse_build_name({"build": ["pages-x", "y"]}), "pages-x")
        self.assertEqual(builds_input.parse_build_name({}), "")
        self.assertEqual(parse.parse_events_query({"ev": ["4"]}), 4)
        self.assertIsNone(parse.parse_events_query({}))
        self.assertEqual(
            parse.parse_events_query({"ev": ["x"]}),
            InputRejected("ev 는 정수(마지막으로 본 이벤트 seq)입니다.", "bad_event_cursor"),
        )

    def test_reply_checks_text_then_mentions_then_reopen(self):
        """The first refused field of a reply is answered, in the order the server has always checked them."""
        self.assertEqual(
            lifecycle_input.parse_reply({"text": "  hi\r\n", "mentions": ["bob@example.com"], "reopen": False}),
            lifecycle_input.ReplyRequest("hi", ["bob@example.com"], False),
        )
        self.assertEqual(lifecycle_input.parse_reply({"text": "hi"}), lifecycle_input.ReplyRequest("hi", [], None))
        self.assertEqual(
            lifecycle_input.parse_reply({"mentions": 1, "reopen": 1}),
            InputRejected("text 가 필요합니다.", "text_required"),
        )
        self.assertEqual(lifecycle_input.parse_reply({"text": "x", "mentions": 1, "reopen": 1}).reason, "bad_mentions")
        self.assertEqual(lifecycle_input.parse_reply({"text": "x", "reopen": 1}).reason, "bad_reopen")

    def test_clear_needs_the_exact_phrase(self):
        """Only confirm == CLEAR_CONFIRM clears; anything else is the contract's 400 naming the phrase."""
        self.assertEqual(trash_input.parse_clear({"confirm": "clear all pins", "x": 1}), trash_input.ClearConfirmed())
        for body in ({}, {"confirm": "Clear all pins"}, {"confirm": ["clear all pins"]}):
            with self.subTest(body=body):
                self.assertEqual(
                    trash_input.parse_clear(body),
                    InputRejected(
                        '모든 핀을 지우려면 본문에 {"confirm": "clear all pins"} 를 보내세요'
                        "(보관본 pins_<시각>.jsonl.bak 이 남습니다).",
                        "confirm_required",
                    ),
                )

    def test_doc_choice_carries_a_new_pins_file_and_own_doc(self):
        """Every route gets the agreed key; only POST /api/pin also gets the body's file and its string doc."""
        self.assertEqual(parse.parse_doc_choice({"doc": ["rev"]}), parse.DocChoice("rev"))
        self.assertEqual(parse.parse_doc_choice({}, {"doc": "rev", "file": "a.tex"}), parse.DocChoice("rev"))
        self.assertEqual(
            parse.parse_doc_choice({"doc": ["main"]}, {"doc": "", "file": 3}, new_pin=True),
            parse.DocChoice("main", 3, ""),
        )
        self.assertEqual(parse.parse_doc_choice({}, {"file": "a.tex"}, new_pin=True), parse.DocChoice(None, "a.tex"))
        self.assertEqual(parse.parse_doc_choice({}, {"doc": 3}, new_pin=True).reason, "bad_doc")
        self.assertEqual(parse.parse_doc_choice({"doc": ["a"]}, {"doc": "b"}, new_pin=True).reason, "doc_mismatch")


class Locations(Tree):
    """The parsers that check a request against the manuscript through DocumentFacts."""

    def test_line_location_is_typed_and_stored_in_the_old_key_order(self):
        """parse_loc gives a LineLoc; its record has file, name, lo, hi, page, then the sent optional fields in the
        order records have always had, whatever order the request sent them in, and nothing for a null."""
        loc = editing_location.parse_loc(
            {
                "pdf_build": "pages",
                "quote": "q",
                "scope": "para",
                "frac": [0, 0, 1, 1],
                "score": 1,
                "via": "text",
                "kind": "para",
                "raw_hi": 3,
                "raw_lo": None,
                "hi": 3,
                "lo": 2,
                "file": "main.tex",
            },
            self.facts,
        )
        self.assertIsInstance(loc, editing_location.LineLoc)
        self.assertEqual((loc.frac, loc.raw_lo, loc.page), ((0.0, 0.0, 1.0, 1.0), None, 1))
        record = loc.to_record()
        self.assertEqual(
            list(record),
            [
                "file",
                "name",
                "lo",
                "hi",
                "page",
                "raw_hi",
                "kind",
                "via",
                "score",
                "frac",
                "scope",
                "quote",
                "pdf_build",
            ],
        )
        self.assertEqual((record["frac"], record["score"]), ([0.0, 0.0, 1.0, 1.0], 1.0))
        self.assertEqual(
            editing_location.parse_loc({"file": "main.tex", "lo": 1, "hi": 1, "frac": [0, 0, 1, "x"]}, self.facts),
            InputRejected("frac 는 유한한 숫자여야 합니다.", "not_number"),
        )
        self.assertEqual(
            editing_location.parse_loc({"file": "main.tex", "lo": 1, "hi": 1, "frac": [0, 0, 1]}, self.facts),
            InputRejected("frac 은 숫자 4개 목록입니다.", "bad_frac"),
        )

    def test_region_location_is_typed_and_stored_in_the_old_key_order(self):
        """parse_region gives a RegionLoc; its record is pdf, name, kind region, page, frac, then quote and pdf_build
        only when present."""
        facts = Facts(self.root, is_pdf=True)
        loc = editing_location.parse_region({"frac": [0.1, 0.1, 0.2, 0.2], "page": 2}, facts)
        self.assertIsInstance(loc, editing_location.RegionLoc)
        self.assertEqual(list(loc.to_record()), ["pdf", "name", "kind", "page", "frac"])
        self.assertEqual(loc.to_record()["frac"], [0.1, 0.1, 0.2, 0.2])
        self.assertEqual(
            editing_location.parse_frac([0.5, 0, 0.6, 1]),
            InputRejected("frac 이 쪽 밖입니다(0..1, 넓이 > 0).", "frac_outside_page"),
        )

    def test_add_checks_the_location_before_the_note(self):
        """A line pin's range is checked against the file's lines before any other field."""
        self.assertEqual(
            editing_input.parse_add({"file": "main.tex", "lo": 2, "hi": 9, "note": 3}, (), self.facts),
            InputRejected("줄 범위가 파일(5줄) 밖입니다: L2-L9", "range_outside_file"),
        )
        request = editing_input.parse_add(
            {"file": "main.tex", "lo": 2, "hi": 3, "note": "n", "quote": "q" * 70}, (), self.facts
        )
        self.assertIsInstance(request.place, LinePlace)
        self.assertEqual(
            (request.place.fields["lo"], request.place.fields["quote"][-1:], request.place.named),
            (2, "…", frozenset({"file", "lo", "hi", "note", "quote"})),
        )
        # an unreadable file counts as one line (L1 still fits), as the server has always done
        self.assertIsInstance(
            editing_input.parse_add({"file": "bin.tex", "lo": 1, "hi": 1}, (), self.facts).place, LinePlace
        )
        self.assertEqual(
            editing_input.parse_add({"file": "bin.tex", "lo": 1, "hi": 2}, (), self.facts),
            InputRejected("줄 범위가 파일(0줄) 밖입니다: L1-L2", "range_outside_file"),
        )

    def test_region_add_on_a_view_only_document(self):
        """file/lo/hi/scope are refused naming the document; page is checked against the named build's pages."""
        facts = Facts(self.root, is_pdf=True, pages={"pages": [(1, 1)] * 2, "pages-20260101000000": [(1, 1)] * 5})
        self.assertEqual(
            editing_input.parse_add({"lo": 1, "page": 1, "frac": [0, 0, 1, 1]}, (), facts),
            InputRejected(
                "보기 전용 문서(rev)의 핀에는 lo 가 없습니다 — 쪽(page)과 영역(frac)만 받습니다.", "no_source_lines"
            ),
        )
        self.assertEqual(
            editing_input.parse_add({"page": 3, "frac": [0, 0, 1, 1]}, (), facts),
            InputRejected("page 는 1..2 이어야 합니다.", "page_out_of_range"),
        )
        request = editing_input.parse_add(
            {"page": 3, "frac": [0, 0, 1, 1], "pdf_build": "pages-20260101000000", "quote": " a  b "}, (), facts
        )
        self.assertIsInstance(request.place, RegionPlace)
        self.assertEqual(
            request.place.fields,
            {
                "pdf": str(self.root / "review.pdf"),
                "name": "review.pdf",
                "kind": "region",
                "page": 3,
                "frac": [0.0, 0.0, 1.0, 1.0],
                "quote": "a b",
                "pdf_build": "pages-20260101000000",
            },
        )

    def test_edit_place_refuses_lines_on_a_region_pin_and_defaults_the_build(self):
        """A region pin refuses lo/hi/scope/kind before its loc is read; a loc that re-places frac takes the build on
        screen unless it names one, and a loc without frac drops pdf_build."""
        body = editing_input.parse_edit({"lo": 1, "loc": {"page": 99}, "base_rev": 0}, ())
        self.assertEqual(
            editing_input.parse_edit_place(body, True, self.facts),
            InputRejected(editing_input.REGION_EDIT_REFUSAL, "no_source_lines"),
        )
        body = editing_input.parse_edit(
            {"loc": {"file": "main.tex", "lo": 1, "hi": 2, "frac": [0, 0, 1, 1]}, "base_rev": 0}, ()
        )
        self.assertEqual(editing_input.parse_edit_place(body, False, self.facts).fields["pdf_build"], "pages")
        body = editing_input.parse_edit(
            {"loc": {"file": "main.tex", "lo": 1, "hi": 2, "pdf_build": "pages"}, "base_rev": 0}, ()
        )
        self.assertNotIn("pdf_build", editing_input.parse_edit_place(body, False, self.facts).fields)
        self.assertIsNone(
            editing_input.parse_edit_place(
                editing_input.parse_edit({"note": "x", "base_rev": 0}, ()), False, self.facts
            )
        )

    def test_null_fraction_does_not_re_place_a_line_pin_fraction(self):
        """A null frac is absent, so an edit keeps the stored coordinates and their build identity."""
        body = editing_input.parse_edit(
            {"loc": {"file": "main.tex", "lo": 1, "hi": 2, "frac": None}, "base_rev": 0}, ()
        )
        place = editing_input.parse_edit_place(body, False, self.facts)
        self.assertIsInstance(place, LinePlace)
        self.assertNotIn("frac", place.fields)
        self.assertNotIn("frac", place.named)
        self.assertNotIn("pdf_build", place.fields)

        record = {
            "file": str(self.root / "main.tex"),
            "name": "main.tex",
            "lo": 1,
            "hi": 2,
            "page": 1,
            "frac": [0.1, 0.2, 0.3, 0.4],
            "frac_build": "pages-20260101000000",
            "id": 7,
        }

        def after(loc: dict) -> dict:
            """Apply a parsed re-placement to the same pin, retaining record field order for comparison."""
            edit = editing_input.parse_edit({"loc": loc, "base_rev": 0}, ())
            replacement = editing_input.parse_edit_place(edit, False, self.facts)
            event = PinEdited(Agent("local", "Local"), "now", None, replacement, None, True, None, None, None, None)
            return evolve_edit(OpenPin.from_record(record), event, None, None, None, None).record

        without = after({"file": "main.tex", "lo": 1, "hi": 2})
        with_null = after({"file": "main.tex", "lo": 1, "hi": 2, "frac": None})
        self.assertEqual(list(with_null.items()), list(without.items()))
        self.assertEqual((with_null["frac"], with_null["frac_build"]), (record["frac"], record["frac_build"]))

    def test_source_range_reads_the_file_before_the_numbers(self):
        """A snippet's file is checked, then lo/hi as int() of the text, then the range against the lines read."""
        rng = location_input.parse_source_range({"file": ["main.tex"], "lo": ["2"], "hi": ["3"]}, self.facts)
        self.assertEqual((rng.file, rng.lines[:2], rng.lo, rng.hi), (self.root / "main.tex", ["a", "b"], 2, 3))
        self.assertEqual(
            location_input.parse_source_range({"file": ["nope.tex"], "lo": ["x"]}, self.facts).reason, "file_not_found"
        )
        self.assertEqual(
            location_input.parse_source_range({"file": ["main.tex"], "lo": ["1.0"], "hi": ["2"]}, self.facts),
            InputRejected("lo·hi 는 정수여야 합니다.", "not_integer"),
        )
        self.assertEqual(
            location_input.parse_snippet({"file": ["main.tex"]}, Facts(self.root, is_pdf=True)),
            InputRejected("보기 전용 문서(rev)에는 원문 줄이 없습니다.", "no_source_lines"),
        )

    def test_pick_checks_the_build_then_page_then_box(self):
        """A bad build name is refused, a gone one answered at once; the page is checked against that build's pages,
        then x0, x1, y0, y1 in order; the box is clamped to the page and sorted."""
        self.assertEqual(location_input.parse_pick({"pdf_build": "../x"}, self.facts).reason, "bad_pdf_build")
        self.assertEqual(
            location_input.parse_pick({"pdf_build": "pages-19990101000000", "page": "x"}, self.facts),
            location_input.PickBuildGone(),
        )
        self.assertEqual(
            location_input.parse_pick({"page": 3, "x0": "bad"}, self.facts),
            InputRejected("page 는 1..2 이어야 합니다.", "page_out_of_range"),
        )
        self.assertEqual(
            location_input.parse_pick({"page": 1, "x0": 1, "x1": None, "y0": "c"}, self.facts),
            InputRejected("x1 는 유한한 숫자여야 합니다.", "not_number"),
        )
        got = location_input.parse_pick(
            {"page": 2, "x0": 900, "x1": 10, "y0": -5, "y1": 40, "frac": [0, 0, 1, 1]}, self.facts
        )
        self.assertEqual(
            got,
            location_input.PickRequest(self.root / "pages", 2, (10.0, 0.0, 600.0, 40.0), (600.0, 800.0), [0, 0, 1, 1]),
        )
        self.assertEqual(
            location_input.parse_pick(
                {"page": 1, "x0": 1, "x1": 2, "y0": 3, "y1": 4, "frac": [1, 2, 3, True]}, self.facts
            ),
            InputRejected("frac 은 숫자 4개 목록입니다.", "bad_frac"),
        )


class ClaimBody(unittest.TestCase):
    """parse_claim_body(): eta_min 1..240 derives the claim's ttl (min(120, max(30, eta_min*2))), a given ttl_min wins,
    a malformed value is refused, and an over-limit value is clamped so old agents' ttl_min 480 keeps working."""

    def test_body_validation_and_derived_ttl(self):
        self.assertEqual(claims_input.parse_claim_body({}), (claims_input.CLAIM_TTL_DEFAULT, None))
        for eta, ttl in ((1, 30), (5, 30), (15, 30), (20, 40), (45, 90), (60, 120), (90, 120), (240, 120)):
            self.assertEqual(claims_input.parse_claim_body({"eta_min": eta}), (ttl, eta), eta)
        # supplying ttl passes it through unchanged
        self.assertEqual(claims_input.parse_claim_body({"eta_min": 15, "ttl_min": 10}), (10, 15))
        for bad in (0, "15", 1.5, True, None, -5):  # refused: answered 400 by the handler
            self.assertIsInstance(claims_input.parse_claim_body({"eta_min": bad}), InputRejected, bad)
        self.assertIsInstance(claims_input.parse_claim_body({"eta_min": 15, "ttl_min": 0}), InputRejected)
        # exceeding the cap clamps instead of 400ing — so an agent that claimed via the old procedure (ttl_min 480) doesn't break when extending
        self.assertEqual(claims_input.parse_claim_body({"eta_min": 241}), (120, 240))
        self.assertEqual(claims_input.parse_claim_body({"eta_min": 15, "ttl_min": 480}), (120, 15))
        self.assertEqual(claims_input.parse_claim_body({"ttl_min": 480}), (120, None))


class ThreadText(unittest.TestCase):
    """parse_thread_text() strips control characters but keeps newlines and tabs."""

    def test_control_characters_are_stripped_but_newlines_kept(self):
        self.assertEqual(parse.parse_thread_text("a\x00b\x1b[31m\tc\nd"), "ab[31m\tc\nd")


class MentionHints(unittest.TestCase):
    """parse_mention_hints(): a list of at most MENTION_MAX logins, absent means none."""

    def test_mention_hints_validated(self):
        self.assertIsInstance(parse.parse_mention_hints("x"), InputRejected)
        self.assertIsInstance(parse.parse_mention_hints(["a"] * (parse.MENTION_MAX + 1)), InputRejected)
        self.assertEqual(parse.parse_mention_hints(None), [])


# ---------------------------------------------------------------- through server.py's wiring
#
# The edit/add parsers fed the server's document facts, and the answers the handler gives them. These classes load
# server.py (helpers.ps) and drive the module through its bindings; the tests above call the module on its own.


class EditAddParsing(Base):
    """The HTTP-boundary parsers of pin edit/add return the checked request or the refusal, in the contract's order."""

    def test_parse_edit_returns_the_request_or_the_first_refusal(self):
        """A valid body becomes an EditRequest (place still unset); the first bad field wins, before base_rev and emptiness."""
        body = editing_input.parse_edit({"note": "n", "lo": 3.0, "scope": "para", "base_rev": 2, "mentions": ["a"]}, ())
        self.assertIsNone(body.loc)
        self.assertEqual(
            (
                body.request.note,
                body.request.lo,
                body.request.scope,
                body.request.base_rev,
                body.request.hints,
                body.request.place,
            ),
            ("n", 3, "para", 2, ("a",), None),
        )
        self.assertEqual(
            editing_input.parse_edit({"note": 3}, ()), InputRejected("note 는 문자열이어야 합니다.", "bad_note")
        )
        self.assertEqual(
            editing_input.parse_edit({"note": "n"}, ()),
            InputRejected("base_rev 가 필요합니다(카드를 열 때 받은 rev).", "base_rev_required"),
        )
        self.assertEqual(
            editing_input.parse_edit({"base_rev": 0}, ()),
            InputRejected(
                "바꿀 필드가 없습니다(note, lo, hi, scope, loc, note_append, kind_req, assignee).", "nothing_to_change"
            ),
        )
        # the assignee refusal comes before base_rev's
        unknown = editing_input.parse_edit({"assignee": "carol@example.com"}, ())
        self.assertTrue(unknown.message.startswith("담당(assignee) 'carol@example.com'"))
        # note_append alone needs no base_rev
        self.assertIsNone(editing_input.parse_edit({"note_append": "x"}, ()).request.base_rev)

    def test_parse_assignee_checks_known_people_only_for_a_person(self):
        """ "agent" needs no lookup; a person must be among the known logins; local is never an assignee."""
        self.assertEqual(parse.parse_assignee("agent", ()), "agent")
        self.assertEqual(parse.parse_assignee("bob@example.com", {"bob@example.com"}), "bob@example.com")
        self.assertIsInstance(parse.parse_assignee("bob@example.com", ()), InputRejected)
        self.assertEqual(
            parse.parse_assignee("local", {"local"}),
            InputRejected("assignee 는 'agent' 또는 사람의 로그인(문자열)입니다.", "bad_assignee"),
        )
        self.assertIsNone(parse.parse_assignee(None, ()))

    def test_parse_add_checks_the_location_first(self):
        """A bad location is reported before a bad note; a valid body carries the place and the fields it named."""
        self.assertEqual(
            editing_input.parse_add(
                {"file": str(self.main), "lo": 4, "hi": 99, "note": 3}, (), ps.APP.document_facts(ps.APP.docs[0])
            ),
            InputRejected("줄 범위가 파일(20줄) 밖입니다: L4-L99", "range_outside_file"),
        )
        request = editing_input.parse_add(
            {"file": "main.tex", "lo": 4, "hi": 5, "note": "n", "extra": 1}, (), ps.APP.document_facts(ps.APP.docs[0])
        )
        self.assertEqual(
            (request.place.fields["file"], request.place.fields["page"], request.note, request.hints),
            (str(self.main), 1, "n", ()),
        )
        self.assertEqual(request.place.named, frozenset({"file", "lo", "hi", "note"}))

    def test_edit_and_add_answers_keep_the_contract_statuses(self):
        """Over HTTP the refusals keep their statuses and bodies: 404 for no pin, 409 conflict/done, 400 for a bad field."""
        pid = self.add()
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pins/%d/edit" % pid, {"note": "x", "base_rev": 5})))
        self.assertEqual((code, json.loads(body)["error"], json.loads(body)["pin"]["id"]), (409, "conflict", pid))
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pins/999/edit", {"note": "x", "base_rev": 0})))
        self.assertEqual((code, json.loads(body)), (404, {"error": "핀 #999 이 없습니다.", "reason": "pin_not_found"}))
        ps.APP.pin_lifecycle.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest())
        code, _, body = split_resp(
            self.talk(jreq("POST", "/api/pins/%d/edit" % pid, {"lo": 4, "hi": 6, "base_rev": 1}))
        )
        d = json.loads(body)
        self.assertEqual(
            (code, d["error"], d["detail"], d["pin"]["id"]), (409, "done", "닫힌 핀은 메모만 고칠 수 있습니다.", pid)
        )
        code, _, body = split_resp(
            self.talk(jreq("POST", "/api/pin", {"file": "main.tex", "lo": 4, "hi": 5, "kind_req": "x"}))
        )
        self.assertEqual(
            (code, json.loads(body)),
            (400, {"error": "kind_req 는 fix|question 중 하나입니다.", "reason": "bad_kind_req"}),
        )


if __name__ == "__main__":
    unittest.main()
