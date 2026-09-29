"""The import build of a figure document (limn.features.builds.figure) and, at the end, its wiring through server.py.

A figure repository writes a PDF, then its element map; Limn imports the pair only when the map's pdf_sha256 is the
PDF's SHA-256, renders exactly the bytes it checked, and keeps the map in the new page directory. Files that do not
agree yet are left alone - no build, no failure - until one of them changes again. The classes up to NoServerState
call the module on a real temporary tree with a fake pdftoppm on PATH (it copies a 200x100 PNG), so no Poppler is
needed; FigureDocumentThroughTheServer drives the same through server.py's build service and routes.

Run: uv run pytest -q src/limn/features/builds/test_figure.py
"""

import ast
import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from limn import build
from limn.build import BuildConfig, BuildFailed, BuildOk
from limn.documents import Doc, RunPaths
from limn.features.builds import figure
from limn.figmap import FigureMap
from limn.web.errors import build_failure_log

from helpers import MINI_PDF, blank_png, figure_map, map_bytes

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
        """The tree, the document (its state folder made), build settings at 72 dpi, a fresh map memo."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.ms = root / "ms"
        self.figs = self.ms / "figs"
        (self.figs / "out").mkdir(parents=True)
        self.pdf = self.figs / "out" / "figures.pdf"
        self.map = self.figs / "out" / "figures.limnmap.json"
        paths = RunPaths(self.ms, self.ms / "main.tex", root / "state")
        self.doc = Doc("fig", "그림", "figure", self.figs, self.map, paths=paths)
        self.doc.dir.mkdir(parents=True)
        self.cfg = BuildConfig(state=root / "state", dpi=72, timeout=5)
        self.looks = figure.MapLooks()
        self.producer = Producer(self.pdf, self.map)
        fake_pdftoppm(self, root)

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

    def test_a_map_naming_a_source_outside_its_folder_is_rejected(self):
        """A src.file that escapes figs/ rejects the whole map (path_outside), so the pair is not imported."""
        m = figure_map(MINI_PDF)
        m["pages"][0]["elements"][1]["src"]["file"] = "../../main.tex"
        self.producer.write(self.pdf, MINI_PDF)
        self.producer.write(self.map, map_bytes(m))
        got = figure.read_figure_import(self.doc)
        self.assertEqual((got.reason, got.detail.split(":")[0]), ("map_rejected", "path_outside"))

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
