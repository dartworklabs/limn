"""A document's verdict word file (limn-verdicts/1): its parse, where it is, how a run reads it, and what /api/docs and
/api/meta report about it (docs/superpowers/specs/2026-10-26-verdict-pins.md §판정 낱말 파일, §HTTP API).

The parse is pure and total, so it is checked on its own: every rule of the format, the size checked before
decoding, repeated names refused, unknown names ignored - and, generated, that any bytes give words or a reason
code and that a well-formed file reads back as written. The reader is checked on real files in a temporary
manuscript tree: a missing file, an unusable one (a link out of the tree, a folder, an unreadable file, a broken
or too large one) and one warning per broken version. The HTTP answers are checked through the real handler.

Run: uv run pytest -q src/limn/documents/tests/test_verdicts.py
"""

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

from hypothesis import given, strategies as st

from limn.builds import artifacts as build_artifacts
from limn.documents import verdicts as verdicts_module
from limn.documents.verdicts import (
    VERDICTS_MAX_BYTES,
    NoVerdictFile,
    VerdictChoice,
    VerdictFiles,
    VerdictsUnusable,
    VerdictWords,
    parse_verdicts,
    verdict_fields,
    verdicts_path,
)
from limn.runtime.documents import Doc, RunPaths

from helpers import MINI_PDF, ps
from helpers_access import ALICE, AccessBase
from helpers_figure import figure_doc

EXAMPLE = {
    "format": "limn-verdicts/1",
    "page": True,
    "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}],
}


def raw(value: object) -> bytes:
    """value as the UTF-8 JSON bytes a project would commit."""
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def with_verdicts(*items: object, **top: object) -> bytes:
    """A file with these verdict entries and top-level names (format limn-verdicts/1 unless top replaces it)."""
    return raw({"format": "limn-verdicts/1", **top, "verdicts": list(items)})


class Parse(unittest.TestCase):
    """parse_verdicts on the format's rules: what a usable file gives, and the reason code of each broken rule."""

    def test_the_example_gives_its_words_in_file_order(self):
        """The spec's example: page true, three choices in order, labels defaulting to the key, one confirm."""
        self.assertEqual(
            parse_verdicts(raw(EXAMPLE)),
            VerdictWords(
                True,
                (
                    VerdictChoice("채택", "채택", False),
                    VerdictChoice("보류", "보류", False),
                    VerdictChoice("삭제", "삭제", True),
                ),
            ),
        )

    def test_a_key_longer_than_a_label_is_its_own_button_name(self):
        """Without a label the button shows the key, which may hold up to 16 characters - more than a label may."""
        self.assertEqual(
            parse_verdicts(with_verdicts({"key": "x" * 16})),
            VerdictWords(False, (VerdictChoice("x" * 16, "x" * 16, False),)),
        )
        self.assertEqual(
            parse_verdicts(with_verdicts({"key": "x" * 16, "label": "x" * 13})), VerdictsUnusable("invalid")
        )

    def test_page_defaults_to_false_and_a_label_replaces_the_key_on_the_button(self):
        """Without page the file asks for no page verdicts; a label is the button's name, the key what is stored."""
        got = parse_verdicts(with_verdicts({"key": "accept", "label": "Accept it"}))
        self.assertEqual(got, VerdictWords(False, (VerdictChoice("accept", "Accept it", False),)))

    def test_unknown_names_are_ignored_at_the_top_and_in_an_entry(self):
        """Names the format does not know are room for a later version, not an error."""
        got = parse_verdicts(with_verdicts({"key": "ok", "color": "red"}, note="later", page=False))
        self.assertEqual(got, VerdictWords(False, (VerdictChoice("ok", "ok", False),)))

    def test_one_to_five_verdicts(self):
        """One and five entries are usable; none and six are invalid."""
        keys = ["a", "b", "c", "d", "e", "f"]
        self.assertIsInstance(parse_verdicts(with_verdicts({"key": "a"})), VerdictWords)
        self.assertIsInstance(parse_verdicts(with_verdicts(*({"key": k} for k in keys[:5]))), VerdictWords)
        self.assertEqual(parse_verdicts(with_verdicts()), VerdictsUnusable("invalid"))
        self.assertEqual(parse_verdicts(with_verdicts(*({"key": k} for k in keys))), VerdictsUnusable("invalid"))

    def test_a_key_is_one_to_sixteen_word_characters_or_dashes(self):
        """Letters of any script, digits, '-' and '_' up to 16; anything else - a space, '|', a line break, a dot, an
        empty or 17-character key, a non-string - is invalid."""
        for key in ("채택", "a", "x" * 16, "accept-now", "keep_2", "第一"):
            with self.subTest(key=key):
                self.assertEqual(parse_verdicts(with_verdicts({"key": key})).keys, (key,))
        for key in ("", "x" * 17, "a b", "a|b", "a\nb", "a.b", "<b>", 1, None, ["a"]):
            with self.subTest(key=key):
                self.assertEqual(parse_verdicts(with_verdicts({"key": key})), VerdictsUnusable("invalid"))
        self.assertEqual(parse_verdicts(with_verdicts({"label": "no key"})), VerdictsUnusable("invalid"))

    def test_a_key_appears_once(self):
        """Two entries with one key are invalid: a pin could not say which one it meant."""
        self.assertEqual(parse_verdicts(with_verdicts({"key": "a"}, {"key": "a"})), VerdictsUnusable("invalid"))

    def test_a_repeated_name_in_any_object_is_invalid(self):
        """json would keep the last value of a repeated name silently; the file is refused instead."""
        top = b'{"format": "limn-verdicts/1", "page": false, "page": true, "verdicts": [{"key": "a"}]}'
        entry = b'{"format": "limn-verdicts/1", "verdicts": [{"key": "a", "key": "b"}]}'
        nested = b'{"format": "limn-verdicts/1", "x": {"y": 1, "y": 2}, "verdicts": [{"key": "a"}]}'
        for text in (top, entry, nested):
            with self.subTest(text=text):
                self.assertEqual(parse_verdicts(text), VerdictsUnusable("invalid"))

    def test_a_label_is_one_to_twelve_characters_without_control_characters(self):
        """A label of 1-12 characters is shown as written, markup included; an empty, 13-character or non-string label,
        or one with a control, format (a bidirectional override) or line-separator character, is invalid."""
        for label in ("x" * 12, "<script>", "확정 삭제"):
            with self.subTest(label=label):
                self.assertEqual(parse_verdicts(with_verdicts({"key": "a", "label": label})).choices[0].label, label)
        for label in ("", "x" * 13, "a\tb", "a\x00", "\u202eab", "a\u2028b", 3, None):
            with self.subTest(label=label):
                self.assertEqual(
                    parse_verdicts(with_verdicts({"key": "a", "label": label})), VerdictsUnusable("invalid")
                )

    def test_page_and_confirm_are_booleans(self):
        """page and confirm, when present, are true or false - null, a number or a string is invalid."""
        for value in (None, 1, "true"):
            with self.subTest(value=value):
                self.assertEqual(parse_verdicts(with_verdicts({"key": "a"}, page=value)), VerdictsUnusable("invalid"))
                self.assertEqual(
                    parse_verdicts(with_verdicts({"key": "a", "confirm": value})), VerdictsUnusable("invalid")
                )

    def test_the_format_and_the_shape_are_exact(self):
        """A missing or other format, a top level that is not an object, verdicts that are not a list of objects."""
        for text in (
            raw({"verdicts": [{"key": "a"}]}),
            raw({"format": "limn-verdicts/2", "verdicts": [{"key": "a"}]}),
            raw([EXAMPLE]),
            raw({"format": "limn-verdicts/1", "verdicts": {"key": "a"}}),
            raw({"format": "limn-verdicts/1", "verdicts": ["a"]}),
            raw({"format": "limn-verdicts/1"}),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_verdicts(text), VerdictsUnusable("invalid"))

    def test_bytes_that_are_not_utf8_json_are_invalid(self):
        """Another encoding, a byte-order mark, NaN, a truncated file and a nesting deeper than the decoder's stack."""
        deep = b'{"format": "limn-verdicts/1", "verdicts": [{"key": "a"}], "x": ' + b"[" * 3000 + b"]" * 3000 + b"}"
        for text in (
            raw(EXAMPLE).decode("utf-8").encode("utf-16"),
            b"\xef\xbb\xbf" + raw(EXAMPLE),
            b'{"format": "limn-verdicts/1", "verdicts": [{"key": "a"}], "x": NaN}',
            raw(EXAMPLE)[:-3],
            b"",
        ):
            with self.subTest(text=text[:20]):
                self.assertEqual(parse_verdicts(text), VerdictsUnusable("invalid"))
        self.assertIn(parse_verdicts(deep), (VerdictsUnusable("invalid"), VerdictsUnusable("too_large")))
        self.assertEqual(parse_verdicts(deep[:VERDICTS_MAX_BYTES]), VerdictsUnusable("invalid"))

    def test_the_size_is_checked_before_anything_else(self):
        """VERDICTS_MAX_BYTES bytes still parse; one more is too_large even for a well-formed file."""
        body = raw(EXAMPLE)
        exact = body[:-1] + b" " * (VERDICTS_MAX_BYTES - len(body)) + b"}"
        self.assertEqual(len(exact), VERDICTS_MAX_BYTES)
        self.assertIsInstance(parse_verdicts(exact), VerdictWords)
        self.assertEqual(parse_verdicts(exact[:-1] + b" }"), VerdictsUnusable("too_large"))
        self.assertEqual(parse_verdicts(b"\xff" * (VERDICTS_MAX_BYTES + 1)), VerdictsUnusable("too_large"))


KEYS = st.from_regex(r"[\w-]{1,16}", fullmatch=True)
LABELS = st.text(st.characters(categories=("L", "N", "P", "Zs")), min_size=1, max_size=12)
CHOICES = st.lists(st.tuples(KEYS, st.none() | LABELS, st.none() | st.booleans()), min_size=1, max_size=5).filter(
    lambda items: len({key for key, _, _ in items}) == len(items)
)


class ParseProperties(unittest.TestCase):
    """Generated inputs: the parse is total, and a well-formed file reads back as it was written."""

    @given(st.binary(max_size=VERDICTS_MAX_BYTES + 64))
    def test_any_bytes_give_words_or_a_reason_code(self, data):
        """Whatever a repository commits, the parse answers words or invalid/too_large - never an exception."""
        got = parse_verdicts(data)
        self.assertTrue(
            isinstance(got, VerdictWords) or got in (VerdictsUnusable("invalid"), VerdictsUnusable("too_large"))
        )

    @given(CHOICES, st.none() | st.booleans())
    def test_a_well_formed_file_reads_back_as_written(self, items, page):
        """Generated keys, labels, confirms and page flags, written as a file, give exactly those words."""
        entries = []
        for key, label, confirm in items:
            entry: dict[str, object] = {"key": key}
            if label is not None:
                entry["label"] = label
            if confirm is not None:
                entry["confirm"] = confirm
            entries.append(entry)
        top = {} if page is None else {"page": page}
        data = with_verdicts(*entries, **top)
        if len(data) > VERDICTS_MAX_BYTES:
            return
        want = tuple(VerdictChoice(key, label or key, bool(confirm)) for key, label, confirm in items)
        self.assertEqual(parse_verdicts(data), VerdictWords(bool(page), want))


class ReadsOnlyThroughTheCheckedFile(unittest.TestCase):
    """The word-file module opens nothing itself: every byte it reads comes through ManuscriptFile.read_bounded."""

    RAW_READS = {"open", "read_text", "read_bytes", "read", "fdopen", "readlines"}

    def test_the_module_calls_no_raw_read(self):
        """No call to open(), os.open/os.read/os.fdopen or Path.read_text/read_bytes appears in documents/verdicts.py;
        the only read is the checked handle's read_bounded."""
        source = Path(verdicts_module.__file__).read_text(encoding="utf-8")
        calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
        names = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in calls
            if isinstance(node.func, (ast.Name, ast.Attribute))
        }
        self.assertEqual(sorted(names & self.RAW_READS), [])
        self.assertIn("read_bounded", names)


class WordFilePlace(unittest.TestCase):
    """verdicts_path: next to the registered file, the kind's suffix replaced - '::' documents included."""

    def test_each_kind_names_its_sibling_file(self):
        """main.tex, a '::' main file, a figure map and a view-only PDF each give <name>.limnverdicts.json beside them."""
        paths = RunPaths(Path("/m"), Path("/m/main.tex"), Path("/s"))
        cases = [
            (Doc("main", "본문", legacy=True, paths=paths), Path("/m/main.limnverdicts.json")),
            (
                Doc("ms", "본문", "tex", Path("/m/paper"), Path("/m/paper/sub/main.tex"), paths=paths),
                Path("/m/paper/sub/main.limnverdicts.json"),
            ),
            (
                Doc(
                    "fig",
                    "그림",
                    "figure",
                    Path("/m/figures"),
                    Path("/m/figures/out/figures.limnmap.json"),
                    paths=paths,
                ),
                Path("/m/figures/out/figures.limnverdicts.json"),
            ),
            (
                Doc("rv", "답변", "pdf", Path("/m/submission"), Path("/m/submission/manuscript.pdf"), paths=paths),
                Path("/m/submission/manuscript.limnverdicts.json"),
            ),
        ]
        for doc, want in cases:
            with self.subTest(doc=doc.key):
                self.assertEqual(verdicts_path(doc), want)


class Reader(unittest.TestCase):
    """VerdictFiles on real files under a temporary manuscript tree, with its warnings collected."""

    def setUp(self):
        """A manuscript tree with main.tex, a state folder beside it, the single document over them and a reader
        whose warnings land in self.warnings."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.src = root / "ms"
        self.src.mkdir()
        (self.src / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        (root / "state").mkdir()
        paths = RunPaths(self.src, self.src / "main.tex", root / "state")
        self.doc = Doc("main", "본문", legacy=True, paths=paths)
        self.file = self.src / "main.limnverdicts.json"
        self.warnings: list[str] = []
        self.reader = VerdictFiles(self.warnings.append)

    def test_no_file_means_no_verdicts_and_no_warning(self):
        """A document without a word file has no verdicts, reports nothing and logs nothing."""
        self.assertEqual(self.reader.read(self.doc), NoVerdictFile())
        self.assertEqual(verdict_fields(self.doc, self.reader.read(self.doc)), {})
        self.assertEqual(self.warnings, [])

    def test_a_usable_file_gives_its_words(self):
        """The example file next to main.tex reads as its three words."""
        self.file.write_bytes(raw(EXAMPLE))
        self.assertEqual(self.reader.read(self.doc).keys, ("채택", "보류", "삭제"))
        self.assertEqual(self.warnings, [])

    def test_a_file_is_parsed_again_only_when_its_signature_changes(self):
        """Same bytes count, same inode and the old mtime_ns kept: the reader answers the version it holds. A write
        that changes the signature is read again."""
        self.file.write_bytes(with_verdicts({"key": "aa"}))
        before = self.file.stat()
        self.assertEqual(self.reader.read(self.doc).keys, ("aa",))
        with open(self.file, "r+b") as fh:  # same inode, same size
            fh.write(with_verdicts({"key": "bb"}))
        os.utime(self.file, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self.reader.read(self.doc).keys, ("aa",))
        self.file.write_bytes(with_verdicts({"key": "ccc"}))
        self.assertEqual(self.reader.read(self.doc).keys, ("ccc",))

    def test_a_broken_version_is_reported_once(self):
        """A broken file warns on its first read only; a fix reads quietly; a new breakage warns again."""
        self.file.write_bytes(b"{")
        for _ in range(3):
            self.assertEqual(self.reader.read(self.doc), VerdictsUnusable("invalid"))
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("main.limnverdicts.json", self.warnings[0])
        self.assertIn("invalid", self.warnings[0])
        self.assertNotIn(str(self.src), self.warnings[0])
        self.file.write_bytes(raw(EXAMPLE))
        self.assertIsInstance(self.reader.read(self.doc), VerdictWords)
        self.file.write_bytes(raw({"format": "x"}))
        self.assertEqual(self.reader.read(self.doc), VerdictsUnusable("invalid"))
        self.assertEqual(len(self.warnings), 2)

    def test_a_large_file_is_too_large(self):
        """A file over VERDICTS_MAX_BYTES is too_large, whatever it holds."""
        self.file.write_bytes(raw(EXAMPLE) + b" " * VERDICTS_MAX_BYTES)
        self.assertEqual(self.reader.read(self.doc), VerdictsUnusable("too_large"))
        self.assertEqual(verdict_fields(self.doc, self.reader.read(self.doc)), {"verdicts_error": "too_large"})
        self.assertEqual(len(self.warnings), 1)

    def test_a_link_out_of_the_manuscript_is_unreadable_and_never_read(self):
        """A word file that links to a usable file outside the manuscript tree is unreadable, not its words."""
        outside = Path(self.tmp.name) / "outside.json"
        outside.write_bytes(raw(EXAMPLE))
        self.file.symlink_to(outside)
        self.assertEqual(self.reader.read(self.doc), VerdictsUnusable("unreadable"))
        self.assertEqual(len(self.warnings), 1)

    def test_a_link_into_a_dot_folder_is_unreadable(self):
        """A word file that links into .git (a part of the tree that is never manuscript) is unreadable."""
        hidden = self.src / ".git"
        hidden.mkdir()
        (hidden / "words.json").write_bytes(raw(EXAMPLE))
        self.file.symlink_to(hidden / "words.json")
        self.assertEqual(self.reader.read(self.doc), VerdictsUnusable("unreadable"))

    def test_a_folder_or_a_dangling_link_is_unreadable(self):
        """Something that is there but is no regular file counts as an unreadable word file."""
        self.file.mkdir()
        self.assertEqual(self.reader.read(self.doc), VerdictsUnusable("unreadable"))
        self.file.rmdir()
        self.file.symlink_to(self.src / "gone.json")
        self.assertEqual(self.reader.read(self.doc), VerdictsUnusable("unreadable"))
        self.file.unlink()
        self.assertEqual(self.reader.read(self.doc), NoVerdictFile())

    def test_the_word_file_is_no_source_of_the_build(self):
        """Writing a word file next to main.tex changes neither the manuscript fingerprint nor src_mtime: it is not a
        LaTeX source (limn.builds.artifacts.SRC_TEX_EXTS), so a new verdict word never marks the PDF stale."""
        state = self.doc.paths.state
        os.utime(self.src / "main.tex", (1_000_000, 1_000_000))
        fingerprint = build_artifacts.source_fingerprint(self.doc, self.src, state)
        newest = build_artifacts.src_mtime(self.doc, state, force=True)
        self.file.write_bytes(raw(EXAMPLE))
        os.utime(self.file, (2_000_000, 2_000_000))
        self.assertEqual(build_artifacts.source_fingerprint(self.doc, self.src, state), fingerprint)
        self.assertEqual(build_artifacts.src_mtime(self.doc, state, force=True), newest)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads a file without read permission")
    def test_a_file_without_read_permission_is_unreadable(self):
        """A word file the server may not read is unreadable, reported once."""
        self.file.write_bytes(raw(EXAMPLE))
        self.file.chmod(0)
        self.addCleanup(self.file.chmod, 0o644)
        self.assertEqual(self.reader.read(self.doc), VerdictsUnusable("unreadable"))
        self.assertEqual(self.reader.read(self.doc), VerdictsUnusable("unreadable"))
        self.assertEqual(len(self.warnings), 1)


class DocsAndMeta(AccessBase):
    """GET /api/docs and GET /api/meta through the real handler: verdicts, verdicts_error, and where they are absent."""

    def setUp(self):
        """AccessBase's one LaTeX document (main) plus figure document fig and view-only PDF rv, each with a word file
        that asks for page verdicts."""
        super().setUp()
        (self.src / "rv").mkdir()
        (self.src / "rv" / "review.pdf").write_bytes(MINI_PDF)
        self.fig = figure_doc(self.src, ps.APP.C.paths)
        self.rv = Doc("rv", "답변", "pdf", self.src / "rv", self.src / "rv" / "review.pdf", paths=ps.APP.C.paths)
        self.ms = Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths)
        ps.APP.set_docs([self.ms, self.fig, self.rv])
        self.addCleanup(ps.APP.set_docs, None)
        for doc in (self.ms, self.fig, self.rv):
            verdicts_path(doc).write_bytes(raw(EXAMPLE))

    def choices(self):
        """The example's choices as the API answers them."""
        return [
            {"key": "채택", "label": "채택", "confirm": False},
            {"key": "보류", "label": "보류", "confirm": False},
            {"key": "삭제", "label": "삭제", "confirm": True},
        ]

    def test_docs_entries_end_with_their_verdicts_and_page_follows_the_kind(self):
        """Each /api/docs entry ends with verdicts after n_open; page is false for the LaTeX document (D6) and true for
        the figure document and the view-only PDF, whose files ask for it."""
        code, d = self.call("GET", "/api/docs", headers=ALICE)
        self.assertEqual(code, 200, d)
        by_key = {e["key"]: e for e in d["docs"]}
        for key, page in (("ms", False), ("fig", True), ("rv", True)):
            with self.subTest(doc=key):
                entry = by_key[key]
                self.assertEqual(list(entry)[-2:], ["n_open", "verdicts"])
                self.assertEqual(entry["verdicts"], {"page": page, "choices": self.choices()})

    def test_full_meta_ends_with_the_documents_verdicts_and_the_light_poll_has_none(self):
        """The full meta carries the asked document's verdicts after its pin counts (the event cursor still comes last);
        the light poll and every docs copy carry none."""
        code, full = self.call("GET", "/api/meta?doc=fig", headers=ALICE)
        self.assertEqual(code, 200, full)
        self.assertEqual(list(full)[-3:], ["n_review", "verdicts", "ev_seq"])
        self.assertEqual(full["verdicts"], {"page": True, "choices": self.choices()})
        self.assertTrue(all("verdicts" not in e and "verdicts_error" not in e for e in full["docs"]))
        code, light = self.call("GET", "/api/meta?doc=fig&light=1", headers=ALICE)
        self.assertEqual(code, 200, light)
        self.assertNotIn("verdicts", light)
        self.assertTrue(all("verdicts" not in e and "verdicts_error" not in e for e in light["docs"]))

    def test_an_unusable_file_is_reported_by_its_reason_and_a_missing_one_not_at_all(self):
        """A broken file gives verdicts_error instead of verdicts; a document without one gives neither."""
        verdicts_path(self.fig).write_bytes(b"[]")
        verdicts_path(self.rv).unlink()
        _, d = self.call("GET", "/api/docs", headers=ALICE)
        by_key = {e["key"]: e for e in d["docs"]}
        self.assertEqual(by_key["fig"]["verdicts_error"], "invalid")
        self.assertNotIn("verdicts", by_key["fig"])
        self.assertNotIn("verdicts", by_key["rv"])
        self.assertNotIn("verdicts_error", by_key["rv"])
        _, meta = self.call("GET", "/api/meta?doc=fig", headers=ALICE)
        self.assertEqual(meta["verdicts_error"], "invalid")
        _, meta = self.call("GET", "/api/meta?doc=rv", headers=ALICE)
        self.assertNotIn("verdicts", meta)
        self.assertNotIn("verdicts_error", meta)

    def test_a_label_is_answered_as_the_text_the_file_holds(self):
        """A label holding markup reaches the API as plain text, character for character; the viewer shows it as
        text (its textContent), never as markup."""
        words = {"format": "limn-verdicts/1", "verdicts": [{"key": "a", "label": "<script>"}]}
        verdicts_path(self.ms).write_text(json.dumps(words), encoding="utf-8")
        _, d = self.call("GET", "/api/docs", headers=ALICE)
        entry = next(e for e in d["docs"] if e["key"] == "ms")
        self.assertEqual(entry["verdicts"]["choices"], [{"key": "a", "label": "<script>", "confirm": False}])

    def test_a_document_without_a_word_file_answers_as_before(self):
        """With no word file anywhere, /api/docs entries and the full meta end with the keys they ended with before."""
        for doc in (self.ms, self.fig, self.rv):
            verdicts_path(doc).unlink()
        _, d = self.call("GET", "/api/docs", headers=ALICE)
        self.assertTrue(all(list(e)[-1] == "n_open" for e in d["docs"]))
        _, meta = self.call("GET", "/api/meta?doc=ms", headers=ALICE)
        self.assertEqual(list(meta)[-4:], ["n_open", "n_done", "n_review", "ev_seq"])
