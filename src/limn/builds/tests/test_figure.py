"""The import build of a figure document (limn.builds.figure) and, at the end, its wiring through server.py.

A figure repository writes a PDF, then its element map; Limn imports the pair only when the map's pdf_sha256 is the
PDF's SHA-256, renders exactly the bytes it checked, and keeps the map in the new page directory. Files that do not
agree yet are left alone - no build, no failure - until one of them changes again. The classes up to NoServerState
call the module on a real temporary tree with a fake pdftoppm on PATH (it copies a 200x100 PNG), so no Poppler is
needed; FigureDocumentThroughTheServer drives the same through server.py's build service and routes.

Run: uv run pytest -q src/limn/builds/tests/test_figure.py
"""

import ast
import contextlib
import io
import json
import os
import tempfile
import time
import typing
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from limn.administration import serve_documents as startup_documents
from limn.builds import artifacts as build, figure, figure_map as figmap
from limn.builds.answer import build_failure_log
from limn.builds.artifacts import BuildConfig, BuildFailed, BuildOk, BuildSkipped
from limn.builds.figure_map import FigureMap
from limn.runtime.documents import Doc, RunPaths

from helpers import MINI_PDF, Base, blank_png, figure_map, map_bytes, ps, req, split_resp

# pdftoppm stand-in (pdftoppm -r DPI -png PDF PREFIX): one page, the PNG named by LIMN_TEST_PAGE_PNG; exit 1 when
# LIMN_TEST_PDFTOPPM is "fail".
FAKE_PDFTOPPM = """#!/bin/sh
[ "$LIMN_TEST_PDFTOPPM" = fail ] && exit 1
cp "$LIMN_TEST_PAGE_PNG" "$5-1.png"
"""
OTHER_PDF = MINI_PDF.replace(b"Reviewer one", b"Reviewer two")  # the same size, other bytes


def fake_pdftoppm(case: unittest.TestCase, root: Path) -> None:
    """Put FAKE_PDFTOPPM first on PATH for the rest of case, with a 200x100 page image under root."""
    bin_dir = root / "bin"
    bin_dir.mkdir()
    (bin_dir / "pdftoppm").write_text(FAKE_PDFTOPPM, encoding="utf-8")
    (bin_dir / "pdftoppm").chmod(0o755)
    page = root / "page.png"
    page.write_bytes(blank_png(200, 100))
    env = mock.patch.dict(
        os.environ,
        {
            "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "LIMN_TEST_PAGE_PNG": str(page),
            "LIMN_TEST_PDFTOPPM": "ok",
        },
    )
    env.start()
    case.addCleanup(env.stop)


class Producer:
    """Writes a figure repository's files the way its render does, each write with a later mtime than the one before
    (so a same-size rewrite still changes the watch signature)."""

    def __init__(self, pdf: Path, map_file: Path) -> None:
        """Bind the PDF path and the map path the producer writes."""
        self.pdf, self.map = pdf, map_file
        self.clock = time.time_ns() + 10**9

    def write(self, path: Path, raw: bytes) -> None:
        """Write raw to path and stamp it one second after the last write."""
        path.write_bytes(raw)
        self.clock += 10**9
        os.utime(path, ns=(self.clock, self.clock))

    def render(self, pdf: bytes = MINI_PDF, described: bytes | None = None, **over: object) -> None:
        """A whole render: the PDF first, then the map describing `described` (default: that PDF), its top-level keys
        replaced by over."""
        self.write(self.pdf, pdf)
        m = figure_map(pdf if described is None else described)
        m.update(over)
        self.write(self.map, map_bytes(m))


class FigureTree(unittest.TestCase):
    """figs/out/figures.pdf and figs/out/figures.limnmap.json under a manuscript, served as figure document fig with
    folder figs/, a fake pdftoppm, and no server."""

    def setUp(self):
        """A temporary root holding the tree (use_tree), build settings at 72 dpi and the fake pdftoppm."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.use_tree(self.root)
        self.cfg = BuildConfig(state=self.root / "state", dpi=72, timeout=5)
        fake_pdftoppm(self, self.root)

    def use_tree(self, base: Path) -> None:
        """Make base/ms/figs/out and bind to it: the paths, document fig (state folder under base/state, made), a
        fresh map memo and a producer. A test calls it again with a new base to start over on a tree of its own."""
        self.ms = base / "ms"
        self.figs = self.ms / "figs"
        (self.figs / "out").mkdir(parents=True)
        self.pdf = self.figs / "out" / "figures.pdf"
        self.map = self.figs / "out" / "figures.limnmap.json"
        paths = RunPaths(self.ms, self.ms / "main.tex", base / "state")
        self.doc = Doc("fig", "그림", "figure", self.figs, self.map, paths=paths)
        self.doc.dir.mkdir(parents=True)
        self.looks = figure.MapLooks()
        self.producer = Producer(self.pdf, self.map)

    def pending(self, first: bool = False) -> figure.FigureImport | None:
        """figure.pending_import for the document, its stderr line swallowed."""
        with contextlib.redirect_stderr(io.StringIO()):
            return figure.pending_import(self.doc, self.looks, 72, first=first)

    def imported(self) -> BuildOk | BuildFailed:
        """Import the files as they are now (startup rules), expecting them to agree."""
        ready = self.pending(first=True)
        self.assertIsInstance(ready, figure.FigureImport)
        return figure.render_figure_doc(self.doc, self.cfg, ready)


class Signatures(FigureTree):
    """watch_signature: what one 3-second tick looks at without reading an unchanged map."""

    def test_the_signature_names_the_map_and_the_pdf_it_points_to(self):
        """mtime_ns:size of the map, a bar, then mtime_ns:size of the PDF the map names."""
        self.producer.render()
        m, p = self.map.stat(), self.pdf.stat()
        self.assertEqual(
            figure.watch_signature(self.doc, self.looks),
            "%d:%d|%d:%d" % (m.st_mtime_ns, m.st_size, p.st_mtime_ns, p.st_size),
        )

    def test_no_signature_without_a_map(self):
        """A figure document whose map is missing has nothing to look at."""
        self.producer.write(self.pdf, MINI_PDF)
        self.assertIsNone(figure.watch_signature(self.doc, self.looks))

    def test_a_rejected_map_or_a_missing_pdf_leaves_the_pdf_half_empty(self):
        """The PDF half is NO_FILE when the map is rejected or the PDF it names does not exist."""
        self.producer.render(format="limn-figure-map/2")
        self.assertTrue(figure.watch_signature(self.doc, self.looks).endswith("|" + figure.NO_FILE))
        self.producer.render()
        self.pdf.unlink()
        self.assertTrue(figure.watch_signature(self.doc, self.looks).endswith("|" + figure.NO_FILE))

    def test_a_changed_map_is_read_again_and_its_new_pdf_followed(self):
        """An unchanged map is not re-read (its memo holds), but once the map changes to name another PDF, the
        signature follows that PDF."""
        self.producer.render()
        first = figure.watch_signature(self.doc, self.looks)
        with mock.patch.object(figure, "parse_map", side_effect=AssertionError("an unchanged map is not re-read")):
            self.assertEqual(figure.watch_signature(self.doc, self.looks), first)
        other = self.figs / "out" / "other.pdf"
        self.producer.write(other, OTHER_PDF)
        self.producer.write(self.map, map_bytes(figure_map(OTHER_PDF, "other.pdf")))
        o = other.stat()
        now = figure.watch_signature(self.doc, self.looks)
        self.assertNotEqual(now, first)
        self.assertTrue(now.endswith("|%d:%d" % (o.st_mtime_ns, o.st_size)))

    def test_two_documents_registering_one_map_share_its_parse(self):
        """The parse is the map's bytes alone, so the memo is keyed by the map's path: fig2, whose folder is the map's
        own, finds the parse fig made and reads the map no more than once."""
        self.producer.render()
        fig2 = Doc("fig2", "그림 2", "figure", self.figs / "out", self.map, paths=self.doc.paths)
        fig2.dir.mkdir(parents=True)
        first = figure.watch_signature(self.doc, self.looks)
        with mock.patch.object(figure, "parse_map", side_effect=AssertionError("the parse is shared, not made again")):
            self.assertEqual(figure.watch_signature(fig2, self.looks), first)


class ImportDue(unittest.TestCase):
    """import_due: the pure rule for when the files are read and checked."""

    def test_files_are_read_only_when_their_signature_moved_or_startup_lacks_pages(self):
        """No map: never. A new signature: always. The settled one: only at startup without page images."""
        for now, settled, missing, want in (
            (None, None, True, False),
            ("a|b", None, False, True),
            ("a|b", "a|c", False, True),
            ("a|b", "a|b", False, False),
            ("a|b", "a|b", True, True),
        ):
            with self.subTest(now=now, settled=settled, missing=missing):
                self.assertIs(figure.import_due(now, settled, missing), want)


class Deferral(FigureTree):
    """Files that do not agree are left alone: no build, no failure, one log line, and a look again on change."""

    def test_a_pdf_newer_than_its_map_is_not_imported_and_records_no_build(self):
        """The producer has written the new PDF but not yet its map: nothing renders, no page directory, no
        builds.json, build_seq stays 0, one stderr line names pdf_mismatch, and the next tick reads nothing. When the
        map lands, the new pair is ready."""
        self.producer.render()
        self.producer.write(self.pdf, OTHER_PDF)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=True))
            self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=False))
        self.assertEqual(err.getvalue().count("pdf_mismatch"), 1)
        self.assertEqual(list(self.doc.dir.glob("pages-*")), [])
        self.assertFalse((self.doc.dir / "builds.json").exists())
        self.assertEqual(build.state_snapshot(self.doc)["seq"], 0)
        self.producer.write(self.map, map_bytes(figure_map(OTHER_PDF)))
        ready = self.pending()
        self.assertIsInstance(ready, figure.FigureImport)
        self.assertEqual(ready.pdf_raw, OTHER_PDF)

    def test_a_map_written_before_its_pdf_waits_for_the_pdf(self):
        """The other order: the new map lands first and describes a PDF not yet written. The pair waits and is ready
        once the PDF matches."""
        self.producer.render()
        self.producer.write(self.map, map_bytes(figure_map(OTHER_PDF)))
        self.assertIsNone(self.pending())
        self.producer.write(self.pdf, OTHER_PDF)
        self.assertIsInstance(self.pending(), figure.FigureImport)

    def test_a_rejected_map_waits_for_its_next_change(self):
        """A map breaking a rule (a box of zero width) is logged once as map_rejected with the parser's reason, is
        not read again while unchanged, and the fixed map is imported."""
        self.producer.write(self.pdf, MINI_PDF)
        broken = figure_map(MINI_PDF)
        broken["pages"][0]["elements"][1]["frac"] = [0.1, 0.1, 0, 0.1]
        self.producer.write(self.map, map_bytes(broken))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=False))
            self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=False))
        self.assertEqual(err.getvalue().count("map_rejected: bad_frac"), 1)
        self.producer.write(self.map, map_bytes(figure_map(MINI_PDF)))
        self.assertIsInstance(self.pending(), figure.FigureImport)

    def test_a_pdf_outside_the_figure_folder_is_never_read(self):
        """A map naming a PDF outside figs/ - by ../ or through a symlink - is pdf_outside even though that file
        exists and matches the hash; nothing is rendered (docs/handbook/code-style-roadmap.md §R10)."""
        outside = self.ms / "elsewhere.pdf"
        outside.write_bytes(MINI_PDF)
        (self.figs / "out" / "link.pdf").symlink_to(outside)
        for name in ("../../elsewhere.pdf", "link.pdf"):
            with self.subTest(pdf=name):
                self.producer.write(self.map, map_bytes(figure_map(MINI_PDF, name)))
                got = figure.read_figure_import(self.doc)
                self.assertIsInstance(got, figure.ImportDeferred)
                self.assertEqual(got.reason, "pdf_outside")
                self.assertIsNone(self.pending(first=True))
        self.assertEqual(list(self.doc.dir.glob("pages-*")), [])

    def test_a_map_naming_a_path_that_is_not_canonical_is_rejected(self):
        """A src.file that climbs out of figs/ by '..' is not a canonical relative path: the whole map is rejected
        (path_outside), so the pair is not imported. Unchanged by where scripts are judged: it is the map's shape."""
        m = figure_map(MINI_PDF)
        m["pages"][0]["elements"][1]["src"]["file"] = "../../main.tex"
        self.producer.write(self.pdf, MINI_PDF)
        self.producer.write(self.map, map_bytes(m))
        got = figure.read_figure_import(self.doc)
        self.assertEqual((got.reason, got.detail.split(":")[0]), ("map_rejected", "path_outside"))

    def test_a_map_whose_script_leads_out_of_the_folder_is_imported(self):
        """figs/src is a symlink out of the folder, so the script src/B2_calendar.py the map names cannot be read
        inside figs/. The map still describes its PDF: the pair is imported, nothing is deferred and nothing is logged.
        Whether a script may be read is decided when a pick reads it (limn.pins.location.figure.read_source), so
        one script that links out costs its own elements, not the whole figure."""
        elsewhere = self.ms / "elsewhere"
        elsewhere.mkdir()
        (self.figs / "src").symlink_to(elsewhere)
        self.producer.render()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ready = figure.pending_import(self.doc, self.looks, 72, first=True)
        self.assertIsInstance(ready, figure.FigureImport)
        self.assertEqual(err.getvalue(), "")
        self.assertIsInstance(figure.render_figure_doc(self.doc, self.cfg, ready), BuildOk)

    def test_a_script_that_becomes_a_link_out_after_an_import_does_not_hold_back_the_next_one(self):
        """The map was imported, then lib/ became a symlink out of the folder and the producer wrote the PDF again with
        the same map bytes: the new pair is imported. (Before, the same folder judgement was made again on the
        unchanged map and deferred it map_rejected.)"""
        self.producer.render()
        self.imported()
        elsewhere = self.ms / "elsewhere"
        elsewhere.mkdir()
        (self.figs / "lib").symlink_to(elsewhere)
        self.producer.write(self.pdf, MINI_PDF)
        self.assertIsInstance(self.pending(), figure.FigureImport)

    def test_a_missing_map_imports_nothing_and_records_nothing(self):
        """No map: no signature, no read, nothing settled - the last pages stay."""
        self.producer.write(self.pdf, MINI_PDF)
        self.assertIsNone(self.pending(first=True))
        self.assertIsNone(figure.settled_signature(self.doc))

    def test_a_symlinked_pdf_repointed_to_a_new_target_is_seen_without_a_map_change(self):
        """The map names current.pdf, a symlink first pointing at v1.pdf (whose bytes do not match the map's declared
        hash - deferred pdf_mismatch). Repointing the same symlink to v2.pdf, whose bytes do match, is picked up on
        the next tick even though the map's own bytes never change: the resolved target must be recomputed on every
        tick, not cached from the first look - a cached target would report pdf_mismatch, or nothing, forever."""
        v1, v2 = self.figs / "out" / "v1.pdf", self.figs / "out" / "v2.pdf"
        self.producer.write(v1, MINI_PDF)
        self.producer.write(v2, OTHER_PDF)
        link = self.figs / "out" / "current.pdf"
        link.symlink_to(v1)
        self.producer.write(self.map, map_bytes(figure_map(OTHER_PDF, "current.pdf")))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=True))
        self.assertIn("pdf_mismatch", err.getvalue())
        link.unlink()
        link.symlink_to(v2)
        self.assertIsInstance(self.pending(), figure.FigureImport)

    def test_a_pdf_that_becomes_a_symlink_after_the_map_named_it_is_still_found(self):
        """The map names current.pdf before that path exists at all (deferred pdf_missing - there is nothing yet for
        figure_pdf's resolve to follow, so it reports the literal, nonexistent path). Once current.pdf appears as a
        symlink to a real PDF matching the map's hash, the pair is ready on the next tick: the target must be
        resolved again then, not reused from the earlier look, which could not have resolved through a symlink that
        did not exist yet."""
        v1 = self.figs / "out" / "v1.pdf"
        self.producer.write(v1, MINI_PDF)
        self.producer.write(self.map, map_bytes(figure_map(MINI_PDF, "current.pdf")))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=True))
        self.assertIn("pdf_missing", err.getvalue())
        (self.figs / "out" / "current.pdf").symlink_to(v1)
        self.assertIsInstance(self.pending(), figure.FigureImport)

    def test_the_pdf_a_map_names_reaches_the_log_quoted_and_cut(self):
        """The map's pdf text appears in the log line of pdf_outside, pdf_missing and pdf_mismatch only as a quoted
        literal of at most DETAIL_TEXT_MAX characters: a newline in it cannot start a forged second line, and a long
        name cannot flood the log."""
        tail = "x" * 200 + "\nforged"
        (self.figs / "out" / ("fig" + tail + ".pdf")).write_bytes(OTHER_PDF)
        for reason, name in (
            ("pdf_outside", "../../" + tail + ".pdf"),
            ("pdf_missing", "absent" + tail + ".pdf"),
            ("pdf_mismatch", "fig" + tail + ".pdf"),
        ):
            with self.subTest(reason=reason):
                self.producer.write(self.map, map_bytes(figure_map(MINI_PDF, name)))
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=False))
                line = err.getvalue()
                self.assertEqual(line.count("\n"), 1, line)
                self.assertIn("(%s: %r)" % (reason, name[: figmap.DETAIL_TEXT_MAX]), line)

    def test_a_pdf_over_the_size_cap_is_deferred_before_it_is_hashed(self):
        """A PDF bigger than PDF_MAX_BYTES is deferred pdf_too_large: logged once, settled from its real size so an
        unchanged oversized file is not re-checked on the next tick, no page directory, no builds.json - all without
        ever holding the file whole in memory (the cap is patched small here so the test does not write real
        megabytes)."""
        with mock.patch.object(figure, "PDF_MAX_BYTES", 16):
            self.producer.write(self.pdf, MINI_PDF)
            self.producer.write(self.map, map_bytes(figure_map(MINI_PDF)))
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=True))
                self.assertIsNone(figure.pending_import(self.doc, self.looks, 72, first=False))
            self.assertEqual(err.getvalue().count("pdf_too_large"), 1)
            self.assertEqual(list(self.doc.dir.glob("pages-*")), [])
            self.assertFalse((self.doc.dir / "builds.json").exists())


class OneLookPerChange(FigureTree):
    """A deferral settles the very signature the next tick's watch_signature computes, whatever its reason, so files
    that do not agree are read and logged once per change and never on every tick. Each scenario below sets up one
    way to defer on a tree of its own and returns what must stay active while the ticks run."""

    def rule_broken(self) -> contextlib.AbstractContextManager[object]:
        """map_rejected: the map breaks a rule of its own (a box of zero width)."""
        broken = figure_map(MINI_PDF)
        broken["pages"][0]["elements"][1]["frac"] = [0.1, 0.1, 0, 0.1]
        self.producer.write(self.pdf, MINI_PDF)
        self.producer.write(self.map, map_bytes(broken))
        return contextlib.nullcontext()

    def pdf_flipped_out(self) -> contextlib.AbstractContextManager[object]:
        """pdf_outside: the map names current.pdf, a symlink inside the folder that the watch has resolved and imported;
        then the link is pointed at a matching PDF outside the folder and the PDF is written again - the map's
        bytes never changed, so the watch still remembers it as accepted and must resolve the PDF afresh."""
        inside = self.figs / "out" / "inside.pdf"
        (self.figs / "out" / "current.pdf").symlink_to(inside)
        self.producer.write(inside, MINI_PDF)
        self.producer.write(self.map, map_bytes(figure_map(MINI_PDF, "current.pdf")))
        self.imported()
        outside = self.ms / "elsewhere.pdf"
        outside.write_bytes(MINI_PDF)
        (self.figs / "out" / "current.pdf").unlink()
        (self.figs / "out" / "current.pdf").symlink_to(outside)
        return contextlib.nullcontext()

    def pdf_up_and_out(self) -> contextlib.AbstractContextManager[object]:
        """pdf_outside: the map names ../../elsewhere.pdf, a file that exists and matches the hash."""
        (self.ms / "elsewhere.pdf").write_bytes(MINI_PDF)
        self.producer.write(self.map, map_bytes(figure_map(MINI_PDF, "../../elsewhere.pdf")))
        return contextlib.nullcontext()

    def pdf_linked_out(self) -> contextlib.AbstractContextManager[object]:
        """pdf_outside: the map names link.pdf, a symlink to a matching PDF outside the folder."""
        (self.ms / "elsewhere.pdf").write_bytes(MINI_PDF)
        (self.figs / "out" / "link.pdf").symlink_to(self.ms / "elsewhere.pdf")
        self.producer.write(self.map, map_bytes(figure_map(MINI_PDF, "link.pdf")))
        return contextlib.nullcontext()

    def pdf_absent(self) -> contextlib.AbstractContextManager[object]:
        """pdf_missing: the map names a PDF that does not exist."""
        self.producer.write(self.map, map_bytes(figure_map(MINI_PDF, "absent.pdf")))
        return contextlib.nullcontext()

    def pdf_a_folder(self) -> contextlib.AbstractContextManager[object]:
        """pdf_missing: the map names dir.pdf, which is a folder."""
        (self.figs / "out" / "dir.pdf").mkdir()
        self.producer.write(self.map, map_bytes(figure_map(MINI_PDF, "dir.pdf")))
        return contextlib.nullcontext()

    def pdf_unreadable(self) -> contextlib.AbstractContextManager[object]:
        """pdf_missing: the PDF is there and can be stat'ed, but not opened (mode 000)."""
        self.producer.render()
        self.pdf.chmod(0)
        self.addCleanup(self.pdf.chmod, 0o644)
        return contextlib.nullcontext()

    def pdf_over_cap(self) -> contextlib.AbstractContextManager[object]:
        """pdf_too_large: the matching PDF is bigger than PDF_MAX_BYTES (patched small while the ticks run)."""
        self.producer.render()
        return mock.patch.object(figure, "PDF_MAX_BYTES", 16)

    def pdf_newer(self) -> contextlib.AbstractContextManager[object]:
        """pdf_mismatch: a new PDF has been written and its map not yet."""
        self.producer.render()
        self.producer.write(self.pdf, OTHER_PDF)
        return contextlib.nullcontext()

    def map_newer(self) -> contextlib.AbstractContextManager[object]:
        """pdf_mismatch: a new map has been written and its PDF not yet."""
        self.producer.render()
        self.producer.write(self.map, map_bytes(figure_map(OTHER_PDF)))
        return contextlib.nullcontext()

    def scenarios(
        self,
    ) -> list[tuple[figure.DeferReason, Callable[[], contextlib.AbstractContextManager[object]]]]:
        """Every scenario with the reason it defers for. pdf_unreadable is left out when running as root, who opens a
        file whatever its mode."""
        out: list[tuple[figure.DeferReason, Callable[[], contextlib.AbstractContextManager[object]]]] = [
            ("map_rejected", self.rule_broken),
            ("pdf_outside", self.pdf_flipped_out),
            ("pdf_outside", self.pdf_up_and_out),
            ("pdf_outside", self.pdf_linked_out),
            ("pdf_missing", self.pdf_absent),
            ("pdf_missing", self.pdf_a_folder),
            ("pdf_too_large", self.pdf_over_cap),
            ("pdf_mismatch", self.pdf_newer),
            ("pdf_mismatch", self.map_newer),
        ]
        if os.geteuid() != 0:
            out.append(("pdf_missing", self.pdf_unreadable))
        return out

    def tick(self) -> tuple[figure.FigureImport | None, str, int]:
        """One watch tick of the document: what pending_import returned, what it wrote to stderr, and how many files
        it opened (figure._read_file)."""
        err = io.StringIO()
        with mock.patch.object(figure, "_read_file", wraps=figure._read_file) as reads, contextlib.redirect_stderr(err):
            got = figure.pending_import(self.doc, self.looks, 72, first=False)
        return got, err.getvalue(), reads.call_count

    def test_every_deferral_settles_the_signature_the_next_tick_computes(self):
        """For every reason a deferral can have (map_missing settles nothing), and for the cases where the files
        and what the watch sees can drift apart - a PDF that can be stat'ed but not read, a PDF judged again after
        its link was pointed out of the folder with the map's bytes unchanged: right after the deferring tick,
        watch_signature equals the settled signature, and the next tick opens no file and logs nothing."""
        scenarios = self.scenarios()
        reasons = set(typing.get_args(figure.DeferReason)) - {"map_missing"}
        self.assertEqual({reason for reason, _ in scenarios}, reasons)
        for reason, setup in scenarios:
            with self.subTest(reason=reason, scenario=setup.__name__):
                self.use_tree(self.root / setup.__name__)
                with setup():
                    got, log, _ = self.tick()
                    self.assertIsNone(got)
                    self.assertEqual(log.count("(%s: " % reason), 1, log)
                    self.assertEqual(figure.watch_signature(self.doc, self.looks), figure.settled_signature(self.doc))
                    self.assertEqual(self.tick(), (None, "", 0))

    @unittest.skipIf(os.geteuid() == 0, "root opens a file whatever its mode")
    def test_an_unreadable_pdf_is_logged_once_and_imported_once_it_is_written_again(self):
        """A PDF the server may stat but not open is pdf_missing: one log line, then ticks that open nothing - not a
        line and a map read every 3 seconds. Its mode changing alone moves neither mtime nor size, so the pair waits
        for the next write, which is imported."""
        self.producer.render()
        self.pdf.chmod(0)
        self.addCleanup(self.pdf.chmod, 0o644)
        ticks = [self.tick() for _ in range(3)]
        self.assertEqual(ticks[0][1].count("(pdf_missing: "), 1)
        self.assertEqual(ticks[1:], [(None, "", 0)] * 2)
        self.pdf.chmod(0o644)
        self.producer.render()
        self.assertIsInstance(self.pending(), figure.FigureImport)

    def test_one_map_under_two_folders_is_judged_per_document_and_imported_once(self):
        """The same map registered twice: fig with folder figs/, fig2 with the map's own folder figs/out/. The map
        names ../figures.pdf, a PDF inside figs/ but outside figs/out/, so fig imports it and fig2 defers it pdf_outside.
        The parse is the map's bytes alone and is shared through one memo, while the PDF is judged per document
        (build.figure_pdf): over three rounds of ticks, fig imports once and fig2 logs once - a judgement is never
        borrowed from the other document."""
        self.producer.write(self.figs / "figures.pdf", MINI_PDF)
        self.producer.write(self.map, map_bytes(figure_map(MINI_PDF, "../figures.pdf")))
        fig2 = Doc("fig2", "그림 2", "figure", self.figs / "out", self.map, paths=self.doc.paths)
        fig2.dir.mkdir(parents=True)
        imports = {"fig": 0, "fig2": 0}
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for _ in range(3):
                for doc in (fig2, self.doc):
                    ready = figure.pending_import(doc, self.looks, 72, first=False)
                    if ready is not None:
                        imports[doc.key] += 1
                        self.assertIsInstance(figure.render_figure_doc(doc, self.cfg, ready), BuildOk)
        self.assertEqual(imports, {"fig": 1, "fig2": 0})
        self.assertEqual(err.getvalue().count("pdf_outside"), 1, err.getvalue())
        self.assertEqual(len(list(self.doc.dir.glob("pages-*"))), 1)

    def test_a_script_that_leads_out_of_one_documents_folder_is_imported_by_both_documents(self):
        """The same map registered with folders figs/ and figs/out/, whose script src/B2_calendar.py lies inside figs/
        but through a symlink that leads out of figs/out/: both documents import it. Before, fig2 rejected the map
        (path_outside) for that script; now the script's folder is judged only when a pick reads it."""
        (self.figs / "src").mkdir()
        (self.figs / "out" / "src").symlink_to(self.figs / "src")
        self.producer.render()
        fig2 = Doc("fig2", "그림 2", "figure", self.figs / "out", self.map, paths=self.doc.paths)
        fig2.dir.mkdir(parents=True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            got = [figure.pending_import(doc, self.looks, 72, first=False) for doc in (fig2, self.doc)]
        self.assertTrue(all(isinstance(ready, figure.FigureImport) for ready in got), got)
        self.assertEqual(err.getvalue(), "")


class Render(FigureTree):
    """render_figure_doc and import_now: the pages, the PDF copy and the map copy land together."""

    def test_an_import_publishes_the_pages_the_pdf_and_the_map_together(self):
        """One page directory holds the page image, the PDF bytes that were checked (named after the map) and the
        map bytes; pages.cur points at it; the staging folder is gone; the settled signature is the files' own."""
        self.producer.render()
        res = self.imported()
        self.assertIsInstance(res, BuildOk)
        pdir = build.cur_pages(self.doc)
        self.assertEqual((res.build, res.pages, res.log, res.src_mtime), (pdir.name, 1, "", None))
        self.assertEqual(sorted(p.name for p in pdir.iterdir()), ["figmap.json", "figures.pdf", "page-1.png"])
        self.assertEqual((pdir / "figures.pdf").read_bytes(), self.pdf.read_bytes())
        self.assertEqual((pdir / build.FIGMAP_NAME).read_bytes(), self.map.read_bytes())
        self.assertEqual(res.src_hash, figure.figure_src_hash(self.pdf.read_bytes(), self.map.read_bytes()))
        self.assertEqual(figure.settled_signature(self.doc), figure.watch_signature(self.doc, self.looks))
        self.assertFalse((self.doc.dir / figure.STAGE_DIR).exists())
        self.assertIsInstance(build.load_build_map(self.doc, pdir.name), FigureMap)

    def test_an_unchanged_pair_is_imported_again_only_at_startup_without_pages(self):
        """After an import the watch finds nothing to do, and so does startup - until the page images are gone."""
        self.producer.render()
        self.imported()
        self.assertIsNone(self.pending())
        self.assertIsNone(self.pending(first=True))
        for page in build.cur_pages(self.doc).glob("page-*.png"):
            page.unlink()
        self.assertIsNone(self.pending())
        self.assertIsInstance(self.pending(first=True), figure.FigureImport)

    def test_a_failed_render_is_settled_and_not_retried_until_a_file_changes(self):
        """pdftoppm failing is BuildFailed render with no latexmk output; no page directory is kept, the same files
        are not tried again, and the next render of the files is."""
        self.producer.render()
        ready = self.pending(first=True)
        with mock.patch.dict(os.environ, {"LIMN_TEST_PDFTOPPM": "fail"}):
            res = figure.render_figure_doc(self.doc, self.cfg, ready)
        self.assertIsInstance(res, BuildFailed)
        self.assertEqual((res.kind, res.output), ("render", None))
        self.assertEqual(list(self.doc.dir.glob("pages-*")), [])
        self.assertIsNone(self.pending())
        self.producer.render()
        self.assertIsInstance(self.pending(), figure.FigureImport)

    def test_a_map_with_more_pages_than_the_pdf_still_imports(self):
        """The PDF has one page and the map describes two: the one page is imported with the whole map; the map's
        page 2 has no page image to be picked on."""
        m = figure_map(MINI_PDF)
        m["pages"].append({"page": 2, "figure": "C1", "elements": [{"id": "C1", "frac": [0, 0, 1, 1]}]})
        self.producer.write(self.pdf, MINI_PDF)
        self.producer.write(self.map, map_bytes(m))
        res = self.imported()
        self.assertEqual(res.pages, 1)
        self.assertEqual([p.page for p in build.load_build_map(self.doc, res.build).pages], [1, 2])

    def test_the_fingerprint_follows_either_file_and_their_boundary(self):
        """32 hex digits that change with the PDF bytes, the map bytes, and a byte moved from one to the other."""
        a = figure.figure_src_hash(b"pdf", b"map")
        self.assertEqual(len(a), 32)
        for other in (("pdf2", "map"), ("pdf", "map2"), ("pdfm", "ap")):
            self.assertNotEqual(a, figure.figure_src_hash(other[0].encode(), other[1].encode()), other)

    def test_the_fingerprint_is_the_digest_of_the_pdf_digest_then_the_map_digest(self):
        """A golden value for fixed bytes: SHA-256 over the raw SHA-256 digest of the PDF bytes followed by that of the
        map bytes, cut to 32 hex digits. Swapping the two digests, or hashing their hex text instead, gives another
        value, so either slip fails here."""
        self.assertEqual(figure.figure_src_hash(b"pdf bytes", b"map bytes"), "55f525c2f7fdff784c31e00fe04c29dc")

    def test_a_tracked_step_without_a_verified_pair_checks_the_files_itself(self):
        """import_now with no pair reads and checks the files: a pair that does not agree is BuildAborted
        figure_unready naming the reason, logged with its Korean text, and nothing is settled; a pair that agrees is
        imported."""
        self.producer.render(described=b"a pdf not written yet")
        res = figure.import_now(self.doc, self.cfg, None)
        self.assertEqual(res.kind, "figure_unready")
        self.assertTrue(res.detail.startswith("pdf_mismatch: "), res.detail)
        self.assertTrue(build_failure_log(res).startswith("그림 PDF 와 지도를 가져오지 못했습니다: pdf_mismatch"))
        self.assertIsNone(figure.settled_signature(self.doc))
        self.producer.render()
        self.assertIsInstance(figure.import_now(self.doc, self.cfg, None), BuildOk)


class NoServerState(unittest.TestCase):
    """The import reads no server global and imports neither the server nor the web layer (coding rule R5)."""

    def test_the_import_module_names_no_server_state(self):
        """No C., cur_doc() or document list, and no import of server.py or limn.web."""
        source = Path(figure.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertEqual(names & {"C", "cur_doc", "DOCS", "LEGACY_DOC", "BUILD_STATE", "BUILD_LOCK"}, set())
        self.assertNotIn("C.", source)
        modules = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertFalse({m for m in modules if "server" in m or m.startswith("limn.web")})


class FigureDocumentThroughTheServer(Base):
    """A figure document served beside a LaTeX body, driven through server.py's build service and routes: startup
    import, the watch tick, and the answers a figure document shares with a view-only PDF."""

    def setUp(self):
        """figs/out/figures.pdf with its map under the fixture manuscript, documents ms and fig (folder figs/), and the
        fake pdftoppm on PATH."""
        super().setUp()
        self.figs = self.src / "figs"
        (self.figs / "out").mkdir(parents=True)
        self.pdf = self.figs / "out" / "figures.pdf"
        self.map = self.figs / "out" / "figures.limnmap.json"
        self.producer = Producer(self.pdf, self.map)
        self.producer.render()
        docs = startup_documents.make_docs(
            ["ms=본문:main.tex", "fig=그림:figs::out/figures.limnmap.json"], self.src, ps.APP.C.paths
        )
        ps.APP.set_docs(docs)
        self.fig = docs[1]
        self.bin = tempfile.TemporaryDirectory()
        self.addCleanup(self.bin.cleanup)
        fake_pdftoppm(self, Path(self.bin.name))

    def tearDown(self):
        """Back to the single document before the fixture removes the manuscript."""
        ps.APP.set_docs(None)
        super().tearDown()

    def test_startup_imports_a_figure_document_whose_files_agree(self):
        """init_doc imports the pair even under --no-build; /pdf serves the checked PDF bytes, and /api/docs and
        /api/meta report kind figure, view_only true, never stale, the map as main."""
        self.assertIsInstance(ps.APP.build_requests.init_doc(self.fig, no_build=True, wait=True), BuildOk)
        code, hdrs, body = split_resp(self.talk(req("GET", "/pdf?doc=fig")))
        self.assertEqual((code, hdrs["content-type"], body), (200, "application/pdf", MINI_PDF))
        code, _, body = split_resp(self.talk(req("GET", "/api/docs")))
        brief = json.loads(body)["docs"][1]
        self.assertEqual(
            (brief["key"], brief["kind"], brief["view_only"], brief["stale_build"], brief["n_pages"]),
            ("fig", "figure", True, False, 1),
        )
        code, _, body = split_resp(self.talk(req("GET", "/api/meta?doc=fig")))
        m = json.loads(body)
        self.assertEqual(
            (m["kind"], m["view_only"], m["stale_build"], m["main"], m["build_seq"]),
            ("figure", True, False, "figures.limnmap.json", 1),
        )

    def test_startup_leaves_a_figure_whose_files_disagree_unbuilt(self):
        """A map describing a PDF not yet written: startup skips the document - no build state, no history."""
        self.producer.write(self.map, map_bytes(figure_map(b"a pdf not written yet")))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ps.APP.build_requests.init_doc(self.fig, no_build=False, wait=True), BuildSkipped())
        self.assertEqual(build.state_snapshot(self.fig)["state"], "idle")
        self.assertEqual(build.load_builds(self.fig)["seq"], 0)

    def test_the_watch_imports_a_figure_once_its_map_catches_up(self):
        """A new PDF alone starts nothing and leaves build_seq; once its map lands, the tick starts a background
        import that publishes the new PDF as the next build."""
        ps.APP.build_requests.init_doc(self.fig, no_build=False, wait=True)
        self.producer.write(self.pdf, OTHER_PDF)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(ps.APP.build_requests.refresh_watched(self.fig))
        self.assertEqual(build.state_snapshot(self.fig)["seq"], 1)
        self.producer.write(self.map, map_bytes(figure_map(OTHER_PDF)))
        self.assertTrue(ps.APP.build_requests.refresh_watched(self.fig))
        self.assertTrue(self.fig.lock.acquire(timeout=10))  # the background import holds the lock until it is done
        self.fig.lock.release()
        self.assertEqual(build.state_snapshot(self.fig)["seq"], 2)
        self.assertEqual((build.cur_pages(self.fig) / "figures.pdf").read_bytes(), OTHER_PDF)

    def test_a_tick_while_the_figure_is_building_reads_nothing_and_starts_nothing(self):
        """While fig's build lock is held (an import is running), a tick with a new agreeing pair on disk opens no
        file, starts nothing, and moves neither build_seq nor the settled signature. Once the lock is free, the next
        tick starts the import of the new pair."""
        ps.APP.build_requests.init_doc(self.fig, no_build=False, wait=True)
        settled = figure.settled_signature(self.fig)
        self.producer.render(OTHER_PDF)
        with self.fig.lock:
            with mock.patch.object(figure, "_read_file", wraps=figure._read_file) as reads:
                self.assertFalse(ps.APP.build_requests.refresh_watched(self.fig))
            self.assertEqual(reads.call_count, 0)
            self.assertEqual((build.state_snapshot(self.fig)["seq"], figure.settled_signature(self.fig)), (1, settled))
        self.assertTrue(ps.APP.build_requests.refresh_watched(self.fig))
        self.assertTrue(self.fig.lock.acquire(timeout=10))  # the background import holds the lock until it is done
        self.fig.lock.release()
        self.assertEqual(build.state_snapshot(self.fig)["seq"], 2)
        self.assertEqual((build.cur_pages(self.fig) / "figures.pdf").read_bytes(), OTHER_PDF)

    def test_a_latex_document_is_not_refreshed_by_the_watch(self):
        """refresh_watched answers False for a document built from source and starts nothing."""
        self.assertFalse(ps.APP.build_requests.refresh_watched(ps.APP.docs[0]))
        self.assertEqual(build.state_snapshot(ps.APP.docs[0])["state"], "idle")

    def test_rebuild_snippet_and_revisions_refuse_a_figure_document(self):
        """POST /api/rebuild is 400 view_only_no_rebuild, a snippet is 400 no_source_lines, and the changes view is
        unavailable - as for a view-only PDF."""
        code, _, body = split_resp(self.talk(req("POST", "/api/rebuild?doc=fig")))
        self.assertEqual((code, json.loads(body)["reason"]), (400, "view_only_no_rebuild"))
        code, _, body = split_resp(self.talk(req("GET", "/api/snippet?doc=fig&file=main.tex&lo=1&hi=2")))
        self.assertEqual((code, json.loads(body)["reason"]), (400, "no_source_lines"))
        code, _, body = split_resp(self.talk(req("GET", "/api/revisions?doc=fig")))
        self.assertEqual((code, json.loads(body)["available"]), (200, False))
