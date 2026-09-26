"""limn.web.parse on its own: each request parser returns the parsed value or the first refused field, in the order
the server has always checked them, with the exact 400 message and reason of the agent contract.

Every route's statuses and bodies are also pinned end to end through the handler (test_server.py, test_access.py and
the version suites). Here the parsers are called directly; the manuscript facts a location parser reads come from a
fake DocumentFacts, so each rule is seen without a server, a build or a real page image. EditAddParsing at the end
feeds them server.py's document facts instead, and checks the statuses the handler answers them with.

Run: uv run pytest -q tests/test_web_parse.py
"""
import json
import tempfile
import unittest
from pathlib import Path

from limn.access import LOCAL_ACTOR
from limn.files import BadPath, NotAFile, OutsideTree, file_in_tree
from limn.pins.edit import LinePlace, RegionPlace
from limn.web import parse
from limn.web.errors import InputRejected

from helpers import Base, jreq, ps, split_resp


class Facts:
    """A DocumentFacts over a real temporary manuscript tree, with the pages and builds given in memory."""

    def __init__(self, root: Path, is_pdf: bool = False, pages: dict | None = None, current: str = "pages"):
        """root is the tree; pages maps a build name to its page sizes; current names the build on screen."""
        self.key, self.is_pdf, self.root = "rev" if is_pdf else "main", is_pdf, root
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
        self.assertEqual(file_in_tree("main.tex", self.root), self.root / "main.tex")
        self.assertEqual(file_in_tree(str(self.root / "main.tex"), self.root), self.root / "main.tex")
        for bad in (None, 3, "", "a\x00b", "x" * 4097):
            self.assertEqual(file_in_tree(bad, self.root), BadPath(), bad)
        self.assertEqual(file_in_tree("/etc/passwd", self.root), OutsideTree())
        self.assertEqual(file_in_tree("../x", self.root), OutsideTree())
        self.assertEqual(file_in_tree("nope.tex", self.root), NotAFile())
        self.assertEqual(file_in_tree(".", self.root), NotAFile())

    def test_source_file_answers_each_refusal_with_its_message(self):
        """The 400 texts name the path as sent."""
        self.assertEqual(parse.source_file(3, self.root), InputRejected("file 이 올바르지 않습니다.", "bad_file"))
        self.assertEqual(parse.source_file("/etc/passwd", self.root),
                         InputRejected("원고 디렉토리 밖의 파일입니다: /etc/passwd", "file_outside_manuscript"))
        self.assertEqual(parse.source_file("nope.tex", self.root),
                         InputRejected("원고 안에 그런 파일이 없습니다: nope.tex", "file_not_found"))


class Fields(unittest.TestCase):
    """The field parsers that read the request alone."""

    def test_numbers(self):
        """An integral number (1.0 too) or a finite one; bools, strings, NaN and infinity are refused."""
        self.assertEqual(parse.int_field(3.0, "lo"), 3)
        self.assertEqual(parse.int_field(True, "lo"), InputRejected("lo 는 정수여야 합니다.", "not_integer"))
        self.assertEqual(parse.int_field(1.5, "lo"), InputRejected("lo 는 정수여야 합니다.", "not_integer"))
        self.assertEqual(parse.num_field(float("inf"), "x0"), InputRejected("x0 는 유한한 숫자여야 합니다.", "not_number"))
        self.assertEqual(parse.num_field(2, "x0"), 2.0)

    def test_thread_text_is_cleaned_then_checked(self):
        """Newlines are normalised and control characters dropped before the length and emptiness checks."""
        self.assertEqual(parse.parse_thread_text("a\r\nb\x00\x1b[1m\tc "), "a\nb[1m\tc")
        self.assertEqual(parse.parse_thread_text(None), InputRejected("text 가 필요합니다.", "text_required"))
        self.assertIsNone(parse.parse_thread_text(None, "reason", required=False))
        self.assertIsNone(parse.parse_thread_text(" \n", "reason", required=False))
        self.assertEqual(parse.parse_thread_text(" \n"), InputRejected("text 가 비어 있습니다.", "text_empty"))
        self.assertEqual(parse.parse_thread_text("x" * 1001, "reason"),
                         InputRejected("reason 가 너무 깁니다(1000자 이하).", "text_too_long"))
        self.assertEqual(parse.parse_reply_text(3), InputRejected("text 는 문자열이어야 합니다.", "bad_text"))

    def test_flags_and_hints(self):
        """reopen/review are true, false or absent; hints are at most MENTION_MAX strings."""
        self.assertIsNone(parse.parse_reopen_flag({}))
        self.assertEqual(parse.parse_review_flag({"review": 1}), InputRejected("review 는 true/false 입니다.", "bad_review"))
        self.assertEqual(parse.parse_mention_hints(["a"] * parse.MENTION_MAX), ["a"] * parse.MENTION_MAX)
        self.assertIsInstance(parse.parse_mention_hints(["a"] * (parse.MENTION_MAX + 1)), InputRejected)

    def test_close_body_blank_is_none(self):
        """reply/ref blank or absent are None; a CloseBody unpacks like the old (reply, ref) pair."""
        reply, ref = parse.parse_close_body({"reply": " ", "ref": "PR #1"})
        self.assertEqual((reply, ref), (None, "PR #1"))

    def test_close_changes_resolve_inside_the_root(self):
        """Paths are resolved against the root and must stay in it; the first bad item is named."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            got = parse.parse_close_changes([{"file": "a.tex", "lo": 1, "hi": 2}], root)
            self.assertEqual(got, (parse.CloseChange(str(root / "a.tex"), 1, 2),))
            self.assertEqual(got[0].record(), {"file": str(root / "a.tex"), "lo": 1, "hi": 2})
            self.assertIsNone(parse.parse_close_changes([], root))
            self.assertEqual(parse.parse_close_changes([{"file": "a.tex", "lo": 1, "hi": 1}, {"file": "../b", "lo": 1, "hi": 1}], root),
                             InputRejected("changes[1].file 은 원고 폴더(--manuscript) 안의 파일이어야 합니다.",
                                           "change_outside_manuscript"))

    def test_claim_body_checks_eta_first_and_clamps(self):
        """eta_min is refused before ttl_min; values above the ceiling are clamped; ttl follows eta when absent."""
        self.assertEqual(parse.parse_claim_body({"eta_min": 0, "ttl_min": "x"}),
                         InputRejected("eta_min 은 1 이상이어야 합니다(상한 240 를 넘으면 240 로 깎아 받습니다).", "too_small"))
        self.assertEqual(parse.parse_claim_body({"eta_min": 10}), parse.ClaimBody(30, 10))
        self.assertEqual(parse.parse_claim_body({"ttl_min": 480, "eta_min": 241}), (120, 240))

    def test_revision_parameters(self):
        """The pin is parsed before the commit; POST names only commit, doc and pin, pin is a JSON integer, and the commit
        is a full lowercase SHA-1."""
        sha = "0123456789abcdef0123456789abcdef01234567"
        bad_commit = InputRejected("올바른 커밋 ID가 아닙니다.", "bad_commit")
        self.assertEqual(parse.parse_revision_query({"commit": [sha], "pin": ["12"]}), (sha, 12))
        self.assertEqual(parse.parse_revision_query({"commit": ["abc"], "pin": ["12"]}), bad_commit)
        self.assertEqual(parse.parse_revision_query({}), bad_commit)
        self.assertEqual(parse.parse_revision_query({"pin": ["0"]}), InputRejected("pin 은 핀 번호(양의 정수)여야 합니다.", "bad_pin"))
        self.assertEqual(parse.parse_revision_build({"commit": sha.upper(), "pin": 3}), bad_commit)
        self.assertEqual(parse.parse_revision_build({"commit": 5}), bad_commit)
        self.assertEqual(parse.parse_revision_build({"commit": sha, "pin": 3}), (sha, 3))
        self.assertEqual(parse.parse_revision_build({"x": 1, "pin": "1"}),
                         InputRejected("허용되지 않는 비교 PDF 요청 필드입니다.", "unknown_fields"))
        self.assertEqual(parse.parse_revision_build({"pin": True}), InputRejected("pin 은 핀 번호(양의 정수)여야 합니다.", "bad_pin"))
        self.assertIsInstance(parse.parse_revision_build({"pin": 10 ** 9}), InputRejected)

    def test_event_cursor_and_doc_key(self):
        """?ev= is int() of the text; ?doc= and the body's doc must agree, and the body's must be a string."""
        self.assertEqual(parse.parse_event_cursor(" 7 "), 7)
        self.assertIsNone(parse.parse_event_cursor(None))
        self.assertIsInstance(parse.parse_event_cursor("1.5"), InputRejected)
        self.assertEqual(parse.parse_doc_key({"doc": ["rev"]}, {"doc": "rev"}), "rev")
        self.assertEqual(parse.parse_doc_key({}, {"doc": ""}), "")
        self.assertIsNone(parse.parse_doc_key(None, None))
        self.assertEqual(parse.parse_doc_key({}, {"doc": 3}), InputRejected("doc 은 문자열이어야 합니다.", "bad_doc"))
        self.assertEqual(parse.parse_doc_key({"doc": ["a"]}, {"doc": "b"}),
                         InputRejected("doc 이 주소(a)와 본문(b)에서 다릅니다.", "doc_mismatch"))


class Locations(Tree):
    """The parsers that check a request against the manuscript through DocumentFacts."""

    def test_add_checks_the_location_before_the_note(self):
        """A line pin's range is checked against the file's lines before any other field."""
        self.assertEqual(parse.parse_add({"file": "main.tex", "lo": 2, "hi": 9, "note": 3}, (), self.facts),
                         InputRejected("줄 범위가 파일(5줄) 밖입니다: L2-L9", "range_outside_file"))
        request = parse.parse_add({"file": "main.tex", "lo": 2, "hi": 3, "note": "n", "quote": "q" * 70}, (), self.facts)
        self.assertIsInstance(request.place, LinePlace)
        self.assertEqual((request.place.fields["lo"], request.place.fields["quote"][-1:], request.place.named),
                         (2, "…", frozenset({"file", "lo", "hi", "note", "quote"})))
        # an unreadable file counts as one line (L1 still fits), as the server has always done
        self.assertIsInstance(parse.parse_add({"file": "bin.tex", "lo": 1, "hi": 1}, (), self.facts).place, LinePlace)
        self.assertEqual(parse.parse_add({"file": "bin.tex", "lo": 1, "hi": 2}, (), self.facts),
                         InputRejected("줄 범위가 파일(0줄) 밖입니다: L1-L2", "range_outside_file"))

    def test_region_add_on_a_view_only_document(self):
        """file/lo/hi/scope are refused naming the document; page is checked against the named build's pages."""
        facts = Facts(self.root, is_pdf=True, pages={"pages": [(1, 1)] * 2, "pages-20260101000000": [(1, 1)] * 5})
        self.assertEqual(parse.parse_add({"lo": 1, "page": 1, "frac": [0, 0, 1, 1]}, (), facts),
                         InputRejected("보기 전용 문서(rev)의 핀에는 lo 가 없습니다 — 쪽(page)과 영역(frac)만 받습니다.", "no_source_lines"))
        self.assertEqual(parse.parse_add({"page": 3, "frac": [0, 0, 1, 1]}, (), facts),
                         InputRejected("page 는 1..2 이어야 합니다.", "page_out_of_range"))
        request = parse.parse_add({"page": 3, "frac": [0, 0, 1, 1], "pdf_build": "pages-20260101000000", "quote": " a  b "},
                                  (), facts)
        self.assertIsInstance(request.place, RegionPlace)
        self.assertEqual(request.place.fields, {"pdf": str(self.root / "review.pdf"), "name": "review.pdf", "kind": "region",
                                                "page": 3, "frac": [0.0, 0.0, 1.0, 1.0], "quote": "a b",
                                                "pdf_build": "pages-20260101000000"})

    def test_edit_place_refuses_lines_on_a_region_pin_and_defaults_the_build(self):
        """A region pin refuses lo/hi/scope/kind before its loc is read; a loc that re-places frac takes the build on
        screen unless it names one, and a loc without frac drops pdf_build."""
        body = parse.parse_edit({"lo": 1, "loc": {"page": 99}, "base_rev": 0}, ())
        self.assertEqual(parse.parse_edit_place(body, True, self.facts), InputRejected(parse.REGION_EDIT_REFUSAL, "no_source_lines"))
        body = parse.parse_edit({"loc": {"file": "main.tex", "lo": 1, "hi": 2, "frac": [0, 0, 1, 1]}, "base_rev": 0}, ())
        self.assertEqual(parse.parse_edit_place(body, False, self.facts).fields["pdf_build"], "pages")
        body = parse.parse_edit({"loc": {"file": "main.tex", "lo": 1, "hi": 2, "pdf_build": "pages"}, "base_rev": 0}, ())
        self.assertNotIn("pdf_build", parse.parse_edit_place(body, False, self.facts).fields)
        self.assertIsNone(parse.parse_edit_place(parse.parse_edit({"note": "x", "base_rev": 0}, ()), False, self.facts))

    def test_source_range_reads_the_file_before_the_numbers(self):
        """A snippet's file is checked, then lo/hi as int() of the text, then the range against the lines read."""
        rng = parse.parse_source_range({"file": ["main.tex"], "lo": ["2"], "hi": ["3"]}, self.facts)
        self.assertEqual((rng.file, rng.lines[:2], rng.lo, rng.hi), (self.root / "main.tex", ["a", "b"], 2, 3))
        self.assertEqual(parse.parse_source_range({"file": ["nope.tex"], "lo": ["x"]}, self.facts).reason, "file_not_found")
        self.assertEqual(parse.parse_source_range({"file": ["main.tex"], "lo": ["1.0"], "hi": ["2"]}, self.facts),
                         InputRejected("lo·hi 는 정수여야 합니다.", "not_integer"))
        self.assertEqual(parse.parse_snippet({"file": ["main.tex"]}, Facts(self.root, is_pdf=True)),
                         InputRejected("보기 전용 문서(rev)에는 원문 줄이 없습니다.", "no_source_lines"))

    def test_pick_checks_the_build_then_page_then_box(self):
        """A bad build name is refused, a gone one answered at once; the page is checked against that build's pages,
        then x0, x1, y0, y1 in order; the box is clamped to the page and sorted."""
        self.assertEqual(parse.parse_pick({"pdf_build": "../x"}, self.facts).reason, "bad_pdf_build")
        self.assertEqual(parse.parse_pick({"pdf_build": "pages-19990101000000", "page": "x"}, self.facts), parse.PickBuildGone())
        self.assertEqual(parse.parse_pick({"page": 3, "x0": "bad"}, self.facts),
                         InputRejected("page 는 1..2 이어야 합니다.", "page_out_of_range"))
        self.assertEqual(parse.parse_pick({"page": 1, "x0": 1, "x1": None, "y0": "c"}, self.facts),
                         InputRejected("x1 는 유한한 숫자여야 합니다.", "not_number"))
        got = parse.parse_pick({"page": 2, "x0": 900, "x1": 10, "y0": -5, "y1": 40, "frac": [0, 0, 1, 1]}, self.facts)
        self.assertEqual(got, parse.PickRequest(self.root / "pages", 2, (10.0, 0.0, 600.0, 40.0), (600.0, 800.0), [0, 0, 1, 1]))
        self.assertEqual(parse.parse_pick({"page": 1, "x0": 1, "x1": 2, "y0": 3, "y1": 4, "frac": [1, 2, 3, True]}, self.facts),
                         InputRejected("frac 은 숫자 4개 목록입니다.", "bad_frac"))


# ---------------------------------------------------------------- through server.py's wiring
#
# The edit/add parsers fed the server's document facts, and the answers the handler gives them. These classes load
# server.py (helpers.ps) and drive the module through its bindings; the tests above call the module on its own.

class EditAddParsing(Base):
    """The HTTP-boundary parsers of pin edit/add return the checked request or the refusal, in the contract's order."""

    def test_parse_edit_returns_the_request_or_the_first_refusal(self):
        """A valid body becomes an EditRequest (place still unset); the first bad field wins, before base_rev and emptiness."""
        body = parse.parse_edit({"note": "n", "lo": 3.0, "scope": "para", "base_rev": 2, "mentions": ["a"]}, ())
        self.assertIsNone(body.loc)
        self.assertEqual((body.request.note, body.request.lo, body.request.scope, body.request.base_rev,
                          body.request.hints, body.request.place), ("n", 3, "para", 2, ("a",), None))
        self.assertEqual(parse.parse_edit({"note": 3}, ()), InputRejected("note 는 문자열이어야 합니다.", "bad_note"))
        self.assertEqual(parse.parse_edit({"note": "n"}, ()), InputRejected("base_rev 가 필요합니다(카드를 열 때 받은 rev).", "base_rev_required"))
        self.assertEqual(parse.parse_edit({"base_rev": 0}, ()),
                         InputRejected("바꿀 필드가 없습니다(note, lo, hi, scope, loc, note_append, kind_req, assignee).",
                                          "nothing_to_change"))
        unknown = parse.parse_edit({"assignee": "carol@example.com"}, ())      # the assignee refusal comes before base_rev's
        self.assertTrue(unknown.message.startswith("담당(assignee) 'carol@example.com'"))
        self.assertIsNone(parse.parse_edit({"note_append": "x"}, ()).request.base_rev)   # note_append alone needs no base_rev

    def test_parse_assignee_checks_known_people_only_for_a_person(self):
        """"agent" needs no lookup; a person must be among the known logins; local is never an assignee."""
        self.assertEqual(parse.parse_assignee("agent", ()), "agent")
        self.assertEqual(parse.parse_assignee("bob@example.com", {"bob@example.com"}), "bob@example.com")
        self.assertIsInstance(parse.parse_assignee("bob@example.com", ()), InputRejected)
        self.assertEqual(parse.parse_assignee("local", {"local"}),
                         InputRejected("assignee 는 'agent' 또는 사람의 로그인(문자열)입니다.", "bad_assignee"))
        self.assertIsNone(parse.parse_assignee(None, ()))

    def test_parse_add_checks_the_location_first(self):
        """A bad location is reported before a bad note; a valid body carries the place and the fields it named."""
        self.assertEqual(parse.parse_add({"file": str(self.main), "lo": 4, "hi": 99, "note": 3}, (), ps.document_facts(ps.DOCS[0])),
                         InputRejected("줄 범위가 파일(20줄) 밖입니다: L4-L99", "range_outside_file"))
        request = parse.parse_add({"file": "main.tex", "lo": 4, "hi": 5, "note": "n", "extra": 1}, (), ps.document_facts(ps.DOCS[0]))
        self.assertEqual((request.place.fields["file"], request.place.fields["page"], request.note, request.hints),
                         (str(self.main), 1, "n", ()))
        self.assertEqual(request.place.named, frozenset({"file", "lo", "hi", "note"}))

    def test_edit_and_add_answers_keep_the_contract_statuses(self):
        """Over HTTP the refusals keep their statuses and bodies: 404 for no pin, 409 conflict/done, 400 for a bad field."""
        pid = self.add()
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pins/%d/edit" % pid, {"note": "x", "base_rev": 5})))
        self.assertEqual((code, json.loads(body)["error"], json.loads(body)["pin"]["id"]), (409, "conflict", pid))
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pins/999/edit", {"note": "x", "base_rev": 0})))
        self.assertEqual((code, json.loads(body)), (404, {"error": "핀 #999 이 없습니다.", "reason": "pin_not_found"}))
        ps.set_done(pid, True, dict(LOCAL_ACTOR))
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pins/%d/edit" % pid, {"lo": 4, "hi": 6, "base_rev": 1})))
        d = json.loads(body)
        self.assertEqual((code, d["error"], d["detail"], d["pin"]["id"]), (409, "done", "닫힌 핀은 메모만 고칠 수 있습니다.", pid))
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pin", {"file": "main.tex", "lo": 4, "hi": 5, "kind_req": "x"})))
        self.assertEqual((code, json.loads(body)), (400, {"error": "kind_req 는 fix|question 중 하나입니다.", "reason": "bad_kind_req"}))



if __name__ == "__main__":
    unittest.main()
