"""The source a build was made from, kept with its pages (limn.builds.built_source, docs/handbook/build-sync.md §빌드가
읽은 원고 줄): which files a record keeps and how they are read from the build copy, which files a SyncTeX file names
as its inputs, what a damaged record answers, and what a real LaTeX build publishes.

Run: uv run pytest -q src/limn/builds/tests/test_built_source.py
"""

import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hypothesis import given, settings, strategies as st

from limn.builds import artifacts as build, built_source, engine
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

    def test_named_files_are_kept_whatever_their_suffix_except_a_bibliography(self):
        """What a build's own line numbers name is kept by content, not by suffix: a .tikz, a .pgf, a .txt, a file
        without a suffix and a script. A .bib and a .bbl (any case) are never kept - a pick on them is refused - and a
        file named both ways is kept once."""
        for rel in ("fig/plot.tikz", "fig/drawn.pgf", "tab/rows.txt", "LICENSE", "code/run.py", "main.tex"):
            self.put(rel, rel.encode("utf-8") + b"\n")
        self.put("refs.bib")
        self.put("main.BBL")
        named = ["fig/plot.tikz", "fig/drawn.pgf", "tab/rows.txt", "LICENSE", "code/run.py", "refs.bib", "main.BBL"]
        got = built_source.collect(self.root, ["main.tex"], [*named, "main.tex", "fig/plot.tikz"])
        self.assertEqual(
            list(got), ["main.tex", "LICENSE", "code/run.py", "fig/drawn.pgf", "fig/plot.tikz", "tab/rows.txt"]
        )
        self.assertEqual(got["fig/plot.tikz"], ["fig/plot.tikz"])
        self.assertEqual(list(built_source.collect(self.root, named)), [], "a source is still kept by suffix alone")

    def test_a_named_file_that_is_not_text_is_too_large_or_is_a_link_is_left_out(self):
        """The suffix does not vouch for a named file, so its bytes do: a picture named as an input (not UTF-8), a
        file over FILE_MAX_BYTES and a link out of the copy are left out, and a dot-named part is never opened."""
        self.put("fig/photo.tikz", b"\x89PNG\r\n\x1a\n\xff\xfe")
        self.put("fig/huge.pgf", b"p" * 64)
        self.put("fig/small.pgf", b"q\n")
        self.put(".cache/kept.txt")
        outside = self.root.parent / "outside.txt"
        outside.write_bytes(b"secret\n")
        os.symlink(outside, self.root / "linked.txt")
        named = ["fig/photo.tikz", "fig/huge.pgf", "fig/small.pgf", ".cache/kept.txt", "linked.txt", "missing.tikz"]
        with mock.patch.object(built_source, "FILE_MAX_BYTES", 32):
            self.assertEqual(list(built_source.collect(self.root, (), named)), ["fig/small.pgf"])

    def test_a_name_that_is_not_utf_8_is_left_out_so_the_record_can_be_written(self):
        """A file named in another encoding reaches Python with a lone surrogate in its name (Linux; the scan and
        SyncTeX's list both hand it over so). Such a name is not kept, whichever way it is named, and the record's
        text is UTF-8 - before, writing it raised and the build ended as crashed. The read is stood in for, since not
        every file system takes such a name."""
        odd = "caf\udce9"
        with mock.patch.object(built_source, "read_below", return_value=b"text\n"):
            got = built_source.collect(self.root, ["main.tex", odd + ".tex"], ["plot.tikz", odd + ".tikz"])
        self.assertEqual(list(got), ["main.tex", "plot.tikz"])
        self.assertEqual(json.loads(built_source.encode(got).encode("utf-8"))["files"], got)

    def test_the_sources_are_read_before_the_named_files_when_the_total_runs_out(self):
        """A bulky named file sorts before the manuscript's text by name and still cannot take its room: the sources
        are read first, and the named files share what is left."""
        self.put("a_drawing.pgf", b"d" * 30)
        self.put("b_note.txt", b"n" * 5)
        self.put("main.tex", b"m" * 10)
        with mock.patch.object(built_source, "TOTAL_MAX_BYTES", 16):
            got = built_source.collect(self.root, ["main.tex"], ["a_drawing.pgf", "b_note.txt"])
        self.assertEqual(list(got), ["main.tex", "b_note.txt"])


class SynctexInputs(Folder):
    """synctex_inputs reads the names a SyncTeX file lists as its inputs, and nothing from a file that is not one."""

    HEAD = b"SyncTeX Version:1\n"
    TAIL = b"Output:pdf\nContent:\n{1\n[1,10:0,0:0,0,0\n]\n}1\n"

    def synctex(self, body, name="main.synctex.gz"):
        """A SyncTeX file holding body, gzipped at name below root; its path."""
        path = self.root / name
        path.write_bytes(gzip.compress(body))
        return path

    def test_every_input_line_is_a_name_whatever_its_suffix_each_once_in_order(self):
        """The inputs listed before the content and those TeX opened later, between the boxes; a name listed twice (an
        .aux read at the start and the end) is one name; lines that only look alike are not names."""
        body = (
            self.HEAD
            + b"Input:1:/copy/./main.tex\nInput:2:/copy/./fig/plot.tikz\nInput:3:/copy/./main.aux\n"
            + self.TAIL
            + b"Input:40:/copy/./tab/rows.txt\n(2,7:10,20:0,0,0\nInput:41:/copy/./main.aux\n"
            + b"xInput:9:/not/a/name\nInput:nine:/not/a/name\nInput:42:rel/\xed\x95\x9c.ltx\n"
        )
        self.assertEqual(
            built_source.synctex_inputs(self.synctex(body)),
            ("/copy/./main.tex", "/copy/./fig/plot.tikz", "/copy/./main.aux", "/copy/./tab/rows.txt", "rel/한.ltx"),
        )

    def test_a_name_is_read_across_a_block_boundary_and_from_a_last_line_without_a_newline(self):
        """The file is read in 1 MiB blocks: an input line cut by a boundary is still one name, and so is a last line
        that ends the file without a newline."""
        filler = b"h1,2:3,4:5,6,7\n"
        before = filler * ((1024 * 1024 - 10) // len(filler))
        pad = b"x" * (1024 * 1024 - 10 - len(before) - 1) + b"\n"
        body = before + pad + b"Input:7:/copy/./fig/over_the_boundary.pgf\n" + filler * 3 + b"Input:8:/copy/last.txt"
        self.assertEqual(len(before + pad), 1024 * 1024 - 10)
        self.assertEqual(
            built_source.synctex_inputs(self.synctex(body)), ("/copy/./fig/over_the_boundary.pgf", "/copy/last.txt")
        )

    def test_a_file_that_is_not_a_synctex_file_names_nothing(self):
        """Not gzip, gzip cut short, missing, a folder, a link to a real one, more bytes than SYNCTEX_MAX_BYTES and a
        line longer than SYNCTEX_LINE_MAX_BYTES: each is None, never a partial list."""
        body = self.HEAD + b"Input:1:/copy/./main.tex\n" + self.TAIL
        good = self.synctex(body)
        self.assertEqual(built_source.synctex_inputs(good), ("/copy/./main.tex",))
        plain = self.put("plain.synctex.gz", body)
        cut = self.put("cut.synctex.gz", good.read_bytes()[:-12])
        (self.root / "dir.synctex.gz").mkdir()
        os.symlink(good, self.root / "link.synctex.gz")
        for path in (plain, cut, self.root / "none.synctex.gz", self.root / "dir.synctex.gz"):
            self.assertIsNone(built_source.synctex_inputs(path), path.name)
        self.assertIsNone(built_source.synctex_inputs(self.root / "link.synctex.gz"))
        with mock.patch.object(built_source, "SYNCTEX_MAX_BYTES", len(body) - 1):
            self.assertIsNone(built_source.synctex_inputs(good))
        with mock.patch.object(built_source, "SYNCTEX_MAX_BYTES", len(body)):
            self.assertEqual(built_source.synctex_inputs(good), ("/copy/./main.tex",))
        with mock.patch.object(built_source, "SYNCTEX_LINE_MAX_BYTES", 8):
            self.assertIsNone(built_source.synctex_inputs(self.synctex(body + b"a line with no end")))

    @given(
        st.lists(
            st.text(alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\n\x00"), min_size=1)
        )
    )
    @settings(max_examples=50, deadline=None)
    def test_any_names_listed_are_read_back_each_once_in_order(self, listed):
        """Whatever names a SyncTeX file lists (any characters but a newline), they come back as written, the first
        time each is listed."""
        body = b"SyncTeX Version:1\n" + b"".join(
            b"Input:%d:%s\n" % (n, name.encode("utf-8")) for n, name in enumerate(listed)
        )
        self.assertEqual(built_source.synctex_inputs(self.synctex(body)), tuple(dict.fromkeys(listed)))

    @given(st.binary(max_size=400), st.booleans())
    @settings(max_examples=80, deadline=None)
    def test_any_bytes_are_answered_with_names_or_none_and_never_raise(self, raw, packed):
        """Bytes that are no SyncTeX file, gzipped or not: a tuple of names or None, never an exception."""
        path = self.root / "any.synctex.gz"
        path.write_bytes(gzip.compress(raw) if packed else raw)
        got = built_source.synctex_inputs(path)
        self.assertTrue(got is None or all(isinstance(name, str) for name in got))


class NamedByTheBuild(Folder):
    """Which of the names in a build's SyncTeX file the engine hands to the record (engine._synctex_named): files of
    the manuscript inside the build copy, by where they lie there."""

    def setUp(self):
        """A manuscript ms/ and its build copy copy/ holding the same files, latexmk run in copy/paper/."""
        super().setUp()
        self.ms = self.root.parent / "ms"
        for base in (self.ms, self.root):
            for rel in ("paper/main.tex", "paper/fig/plot.tikz", "shared/rows.txt"):
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_text("text\n", encoding="utf-8")
        self.doc = SimpleNamespace(src=self.ms, build=self.root, out=self.root / "paper")

    def named(self, *names):
        """engine._synctex_named for a SyncTeX file listing names as its inputs."""
        body = b"SyncTeX Version:1\n" + b"".join(b"Input:%d:%s\n" % (n, os.fsencode(x)) for n, x in enumerate(names, 1))
        syn = self.root / "paper" / "main.synctex.gz"
        syn.write_bytes(gzip.compress(body))
        return engine._synctex_named(self.doc, syn)

    def test_a_name_inside_the_copy_is_named_by_its_path_there(self):
        """An absolute name with TeX's /./, a name relative to the folder latexmk ran in and one that climbs out of
        that folder but stays in the copy; each once."""
        paper = str(self.root / "paper")
        got = self.named(paper + "/./main.tex", "fig/plot.tikz", "../shared/rows.txt", paper + "/./fig/plot.tikz")
        self.assertEqual(got, ["paper/main.tex", "paper/fig/plot.tikz", "shared/rows.txt"])

    def test_a_file_through_a_linked_folder_is_named_by_where_it_lies(self):
        """paper/tables links to shared/ in the copy: the input paper/tables/rows.txt is shared/rows.txt."""
        os.symlink(self.root / "shared", self.root / "paper" / "tables")
        self.assertEqual(self.named("tables/rows.txt"), ["shared/rows.txt"])

    def test_a_name_outside_the_copy_or_not_in_the_manuscript_is_not_named(self):
        """A class file of the TeX installation, a path that climbs out of the copy, the copy's root, a byproduct
        latexmk made in the copy that the manuscript does not have, and a manuscript path that is a link there."""
        (self.root / "paper" / "main.aux").write_text("\\relax\n", encoding="utf-8")
        (self.root / "paper" / "alias.tex").write_text("text\n", encoding="utf-8")
        os.symlink(self.ms / "paper" / "main.tex", self.ms / "paper" / "alias.tex")
        got = self.named(
            "/usr/share/texmf/tex/latex/base/article.cls", "../../ms/paper/main.tex", "..", "main.aux", "alias.tex"
        )
        self.assertEqual(got, [])

    def test_a_synctex_file_that_cannot_be_read_names_nothing(self):
        """A file that is not gzip: no names, so the record keeps the scan's files alone."""
        syn = self.root / "paper" / "main.synctex.gz"
        syn.write_bytes(b"Input:1:main.tex\n")
        self.assertEqual(engine._synctex_named(self.doc, syn), [])


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

    @needs_tex("latexmk", "pdftoppm")
    def test_a_build_keeps_what_its_synctex_names_whatever_the_suffix(self):
        """main.tex inputs fig/plot.tikz, tab/rows.txt and sec/old.ltx: SyncTeX names each as an input, so the record
        holds their lines next to main.tex. A .tikz the build never read, a data file it read without making it an
        input (\\openin) and the .aux latexmk made in the copy are not in it."""
        for rel, text in (
            ("fig/plot.tikz", "Words drawn in a tikz file.\n"),
            ("tab/rows.txt", "Rows kept as plain text.\n"),
            ("sec/old.ltx", "An old section file.\n"),
            ("fig/unread.tikz", "Never input.\n"),
            ("tab/data.csv", "a,b\n"),
        ):
            (self.src / rel).parent.mkdir(exist_ok=True)
            (self.src / rel).write_text(text, encoding="utf-8")
        reads = (
            "\\input{fig/plot.tikz}\n\\input{tab/rows.txt}\n\\input{sec/old.ltx}\n"
            "\\newread\\data \\openin\\data=tab/data.csv \\read\\data to \\row \\closein\\data\n"
        )
        self.main.write_text(TEX.replace("\\section{Intro}\n", "\\section{Intro}\n" + reads), encoding="utf-8")
        D = ps.APP.docs[0]
        self.assertIsInstance(ps.APP.build_requests.build_all(D), BuildOk)
        pages = build.cur_pages(D)
        record = json.loads((pages / built_source.SOURCE_NAME).read_text(encoding="utf-8"))
        self.assertEqual(sorted(record["files"]), ["fig/plot.tikz", "main.tex", "sec/old.ltx", "tab/rows.txt"])
        self.assertEqual(built_source.built_lines(pages, "fig/plot.tikz"), ("Words drawn in a tikz file.",))
        self.assertEqual(list(record["files"])[0], "main.tex", "the manuscript's sources come first")
