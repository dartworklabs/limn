"""The source a build was made from, kept with its pages (limn.builds.built_source, docs/handbook/build-sync.md §빌드가
읽은 원고 줄): which files a record keeps and how they are read from the build copy, what a damaged record answers, and
what a real LaTeX build publishes.

Run: uv run pytest -q src/limn/builds/tests/test_built_source.py
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hypothesis import given, settings, strategies as st

from limn.builds import artifacts as build, built_source
from limn.builds.artifacts import BuildOk
from limn.platform.files import ManuscriptFile, file_in_tree, tex_lines

from helpers import TEX, Base, needs_tex, ps


class Folder(unittest.TestCase):
    """A temporary folder standing for a build copy or a page folder."""

    def setUp(self):
        """root, resolved (macOS keeps its temporary folders under a link)."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "copy"
        self.root.mkdir()

    def put(self, rel, data=b"one\ntwo\n"):
        """Write data at rel below root, making its folders."""
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path


class Collect(Folder):
    """collect keeps the text sources a pick answers lines in, read through no link."""

    def test_text_sources_are_kept_by_suffix_and_everything_else_is_left_out(self):
        """.tex, .sty and .cls (any case) are kept as lines; a .bib, a picture and a file not named are not."""
        self.put("main.tex", b"a\nb\n")
        self.put("sec/intro.TEX", b"intro\n")
        self.put("style/own.sty", b"\\ProvidesPackage{own}\n")
        self.put("own.cls")
        self.put("refs.bib")
        self.put("fig/plot.pdf", b"%PDF")
        self.put("unnamed.tex")
        names = ["main.tex", "sec/intro.TEX", "style/own.sty", "own.cls", "refs.bib", "fig/plot.pdf", "main.tex"]
        got = built_source.collect(self.root, names)
        self.assertEqual(list(got), ["main.tex", "own.cls", "sec/intro.TEX", "style/own.sty"])
        self.assertEqual(got["main.tex"], ["a", "b"])
        self.assertEqual(got["sec/intro.TEX"], ["intro"])

    def test_a_file_that_is_not_utf_8_or_is_missing_is_left_out(self):
        """Bytes that are not UTF-8 have no lines a pick could read either; a name without a file is skipped."""
        self.put("main.tex")
        self.put("latin.tex", b"caf\xe9\n")
        got = built_source.collect(self.root, ["main.tex", "latin.tex", "gone.tex"])
        self.assertEqual(list(got), ["main.tex"])

    def test_a_link_is_never_followed_out_of_the_copy(self):
        """A file that is a link, a file under a folder that is a link, a path that climbs and a dot-named part are
        all left out - the secret they lead to is not copied into the page folder."""
        secret = self.root.parent / "secret.tex"
        secret.write_bytes(b"token\n")
        outside = self.root.parent / "outside"
        outside.mkdir()
        (outside / "x.tex").write_bytes(b"token\n")
        self.put("main.tex")
        self.put(".git/x.tex")
        os.symlink(secret, self.root / "linked.tex")
        os.symlink(outside, self.root / "linkdir")
        names = ["main.tex", "linked.tex", "linkdir/x.tex", "../secret.tex", ".git/x.tex", "/etc/hosts.tex", ""]
        self.assertEqual(list(built_source.collect(self.root, names)), ["main.tex"])
        for rel in names[1:]:
            self.assertIsNone(built_source.read_below(self.root, rel, 1 << 20), rel)

    def test_a_folder_or_a_fifo_named_like_a_source_is_not_read(self):
        """Only a regular file is read: a folder is refused, and a FIFO is refused without waiting for a writer."""
        self.put("main.tex")
        (self.root / "dir.tex").mkdir()
        os.mkfifo(self.root / "pipe.tex")
        self.assertEqual(list(built_source.collect(self.root, ["main.tex", "dir.tex", "pipe.tex"])), ["main.tex"])

    def test_a_file_over_the_limit_is_left_out_and_the_total_is_bounded(self):
        """A file larger than FILE_MAX_BYTES is not kept; once the record holds TOTAL_MAX_BYTES, later files are not."""
        self.put("a.tex", b"x" * 10)
        self.put("b.tex", b"y" * 40)
        self.put("c.tex", b"z" * 10)
        with mock.patch.object(built_source, "FILE_MAX_BYTES", 20):
            self.assertEqual(list(built_source.collect(self.root, ["a.tex", "b.tex", "c.tex"])), ["a.tex", "c.tex"])
        with mock.patch.object(built_source, "TOTAL_MAX_BYTES", 15):
            self.assertEqual(list(built_source.collect(self.root, ["a.tex", "b.tex", "c.tex"])), ["a.tex"])
        self.assertIsNone(built_source.read_below(self.root, "b.tex", 39))
        self.assertEqual(built_source.read_below(self.root, "b.tex", 40), b"y" * 40)


class Lines(Folder):
    """The record's lines are the lines a pick reads from the file itself."""

    CASES = (b"", b"a", b"a\n", b"a\r\nb\rc\n", b"a\x0cb\n\n", b"\xef\xbb\xbfbom\n", "한글 \u2028 줄\n".encode())

    def same_as_the_manuscript_reader(self, raw):
        """text_lines(raw) equals what tex_lines reads from a manuscript file holding raw."""
        path = self.put("ms/main.tex", raw)
        found = file_in_tree(str(path), self.root / "ms", self.root / "state")
        self.assertIsInstance(found, ManuscriptFile)
        self.assertEqual(built_source.text_lines(raw), tex_lines(found), raw)

    def test_the_two_readers_split_the_same_bytes_into_the_same_lines(self):
        """Newline forms, a form feed, a byte order mark and a Unicode line separator: line for line the same."""
        for raw in self.CASES:
            self.same_as_the_manuscript_reader(raw)

    @settings(max_examples=60, deadline=None)
    @given(st.text(alphabet=st.sampled_from("ab \n\r\x0b\x0c\x1c\x85\u2028\\%가"), max_size=40))
    def test_any_text_is_split_the_same_by_both_readers(self, text):
        """Whatever mix of line boundaries a file holds."""
        self.same_as_the_manuscript_reader(text.encode("utf-8"))

    def test_bytes_that_are_not_utf_8_have_no_lines(self):
        """The manuscript reader answers no lines for them; the record keeps none."""
        self.assertIsNone(built_source.text_lines(b"\xff\xfe"))


class Record(Folder):
    """built_lines reads one file's lines back from a page folder's record, or answers that there is none."""

    def write(self, text):
        """The page folder's record holds text."""
        (self.root / built_source.SOURCE_NAME).write_text(text, encoding="utf-8")

    def test_the_lines_written_are_the_lines_read_back(self):
        """Backslashes, quotes, tabs and non-ASCII text survive the record; a file it does not hold is None."""
        lines = ['\\section{가} % "quoted"', "", "\tindented \\\\"]
        self.write(built_source.encode({"sec/a.tex": lines, "main.tex": []}))
        self.assertEqual(built_source.built_lines(self.root, "sec/a.tex"), tuple(lines))
        self.assertEqual(built_source.built_lines(self.root, "main.tex"), ())
        self.assertIsNone(built_source.built_lines(self.root, "other.tex"))
        self.assertIsNone(built_source.built_lines(self.root, "../copy/sec/a.tex"))

    def test_a_folder_without_a_record_has_none(self):
        """A build made before builds kept their source."""
        self.assertIsNone(built_source.built_lines(self.root, "main.tex"))

    def test_a_damaged_record_is_no_record(self):
        """Cut-off JSON, another JSON shape, another format number and lines that are not strings: each is None."""
        good = {"format": built_source.SOURCE_FORMAT, "files": {"main.tex": ["a"]}}
        for text in (
            '{"format": 1, "files": {"main.tex": ["a"',
            "[]",
            '"main.tex"',
            json.dumps({**good, "format": 2}),
            json.dumps({**good, "files": ["main.tex"]}),
            json.dumps({**good, "files": {"main.tex": "a"}}),
            json.dumps({**good, "files": {"main.tex": ["a", 1]}}),
            "[" * 100000,
        ):
            self.write(text)
            self.assertIsNone(built_source.built_lines(self.root, "main.tex"), text[:40])
        self.write(json.dumps(good))
        self.assertEqual(built_source.built_lines(self.root, "main.tex"), ("a",))

    def test_a_record_that_is_a_link_or_too_large_is_not_read(self):
        """A link in the record's place is not followed, and a record over RECORD_MAX_BYTES is not parsed."""
        text = built_source.encode({"main.tex": ["a"]})
        elsewhere = self.root / "elsewhere.json"
        elsewhere.write_text(text, encoding="utf-8")
        os.symlink(elsewhere, self.root / built_source.SOURCE_NAME)
        self.assertIsNone(built_source.built_lines(self.root, "main.tex"))
        (self.root / built_source.SOURCE_NAME).unlink()
        self.write(text)
        with mock.patch.object(built_source, "RECORD_MAX_BYTES", len(text.encode()) - 1):
            self.assertIsNone(built_source.built_lines(self.root, "main.tex"))
        self.assertEqual(built_source.built_lines(self.root, "main.tex"), ("a",))


class Key(Folder):
    """source_key names a manuscript file the way the build's scan of its copy names it."""

    def test_a_file_below_the_build_root_is_named_by_its_path_there(self):
        """Through a linked folder the name is where the file really lies; a file outside the root has no name."""
        self.put("sec/a.tex")
        os.symlink(self.root / "sec", self.root / "chapters")
        self.assertEqual(built_source.source_key(self.root, self.root / "sec" / "a.tex"), "sec/a.tex")
        self.assertEqual(built_source.source_key(self.root, self.root / "chapters" / "a.tex"), "sec/a.tex")
        self.assertIsNone(built_source.source_key(self.root, self.root.parent / "elsewhere.tex"))
        self.assertIsNone(built_source.source_key(self.root, self.root))


class PublishedWithTheBuild(Base):
    """What a real LaTeX build leaves in its page folder."""

    @needs_tex("latexmk", "pdftoppm")
    def test_a_build_keeps_the_lines_of_the_files_it_read_and_of_no_other(self):
        """main.tex inputs sec/intro.tex; notes.tex lies in the tree unread. The record holds the two files the build
        read, as the build copy held them, and an edit of the manuscript afterwards does not change it."""
        (self.src / "sec").mkdir()
        intro = "Intro words from another file.\n"
        (self.src / "sec" / "intro.tex").write_text(intro, encoding="utf-8")
        (self.src / "notes.tex").write_text("Never input.\n", encoding="utf-8")
        text = TEX.replace("\\section{Intro}\n", "\\section{Intro}\n\\input{sec/intro}\n")
        self.main.write_text(text, encoding="utf-8")
        D = ps.APP.docs[0]
        self.assertIsInstance(ps.APP.build_requests.build_all(D), BuildOk)
        pages = build.cur_pages(D)
        record = json.loads((pages / built_source.SOURCE_NAME).read_text(encoding="utf-8"))
        self.assertEqual(sorted(record["files"]), ["main.tex", "sec/intro.tex"])
        self.main.write_text(text.replace("Tail paragraph", "Edited tail"), encoding="utf-8")
        self.assertEqual(built_source.built_lines(pages, "main.tex"), tuple(text.splitlines()))
        self.assertEqual(built_source.built_lines(pages, "sec/intro.tex"), ("Intro words from another file.",))
        key = built_source.source_key(D.src, self.src / "sec" / "intro.tex")
        self.assertEqual(key, "sec/intro.tex")
