"""limn.builds.artifacts.PageFolderCache: what a run keeps of a published page folder.

The light poll (GET /api/meta?light=1, every few seconds per open viewer) reports the pages of the build on screen:
how many there are and each one's size. Reading them is one folder listing and one opened image per page, and every
one of those calls gives the interpreter up to whichever thread is computing. A stamped page folder
(pages-<14 digits>[-<n>]) is written whole under a hidden name and renamed into place, and its name is never given to
another build, so what it holds is read once per run and kept under the document's state folder and the build's name.

These tests count file-system calls instead of timing them (docs/handbook/verification.md §불안정한 테스트).

Run: uv run pytest -q src/limn/builds/tests/test_page_folders.py
"""

import os
import tempfile
import unittest
from pathlib import Path

from limn.builds import artifacts
from limn.builds.artifacts import FolderPages, PageFolderCache, count_folder_pages, page_list, read_folder_pages
from limn.runtime.documents import Doc, RunPaths

from helpers import fs_calls
from helpers_figure import png_header

B1, B2, B3 = "pages-20260101000000", "pages-20260101000001", "pages-20260101000001-1"


def write_pages(folder: Path, sizes) -> None:
    """Write page-<n>.png of the given pixel sizes into folder, zero-padded as a render names them."""
    width = len(str(len(sizes)))
    for number, (w, h) in enumerate(sizes, 1):
        (folder / ("page-%0*d.png" % (width, number))).write_bytes(png_header(w, h))


def publish(doc: Doc, name: str, sizes) -> Path:
    """Publish build `name` of doc as a render does - made whole under a hidden name, renamed into place - and put it
    on screen (pages.cur). Returns the page folder."""
    doc.dir.mkdir(parents=True, exist_ok=True)
    part = doc.dir / ("." + name + ".part")
    part.mkdir()
    write_pages(part, sizes)
    os.rename(part, doc.dir / name)
    (doc.dir / "pages.cur").write_text(name, encoding="utf-8")
    return doc.dir / name


def disk_reads(counts) -> int:
    """How many calls of counts opened a file or listed a folder."""
    return counts["open"] + counts["scandir"] + counts["listdir"]


class Fixture(unittest.TestCase):
    """Two LaTeX documents of one instance, each with its own state folder."""

    def setUp(self):
        """A temporary manuscript and state folder; no build is published yet."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        src = root / "ms"
        (src / "rr").mkdir(parents=True)
        (src / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        (src / "rr" / "rr.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        (root / "state").mkdir()
        paths = RunPaths(src, src / "main.tex", root / "state")
        self.ms = Doc("ms", "Body", "tex", src, src / "main.tex", paths=paths)
        self.rr = Doc("rr", "Reply", "tex", src / "rr", src / "rr" / "rr.tex", paths=paths)


class ReadingAFolder(Fixture):
    """read_folder_pages and count_folder_pages: what one look at a page folder gives."""

    def test_the_names_are_counted_and_the_readable_images_sized_in_name_order(self):
        """Ten pages come back in the order their zero-padded names sort, each with its pixel size."""
        folder = publish(self.ms, B1, [(100 + n, 50) for n in range(10)])
        got = read_folder_pages(folder)
        self.assertEqual(got.count, 10)
        self.assertEqual(got.sized[0], ("page-01.png", 100, 50))
        self.assertEqual(got.sized[-1], ("page-10.png", 109, 50))

    def test_a_missing_folder_has_no_pages(self):
        """A folder that is not there is no pages, not an error."""
        self.assertEqual(read_folder_pages(self.ms.dir / B1), FolderPages(0, ()))
        self.assertEqual(count_folder_pages(self.ms.dir / B1), 0)

    def test_an_unreadable_image_is_counted_and_not_sized(self):
        """A page image shorter than a PNG header is one of the folder's names and has no size."""
        folder = publish(self.ms, B1, [(300, 150)] * 3)
        (folder / "page-2.png").write_bytes(b"\x89PNG\r\n")
        got = read_folder_pages(folder)
        self.assertEqual((got.count, [row[0] for row in got.sized]), (3, ["page-1.png", "page-3.png"]))

    def test_counting_opens_no_image(self):
        """The count is a listing: no page image is opened for it."""
        folder = publish(self.ms, B1, [(300, 150)] * 4)
        counts, got = fs_calls(lambda: count_folder_pages(folder))
        self.assertEqual((got, counts["open"]), (4, 0))

    def test_rows_are_sized_in_points_at_the_dpi_asked(self):
        """A 300 x 150 pixel page is 144 x 72 pt at 150 dpi and half that at 300."""
        pages = read_folder_pages(publish(self.ms, B1, [(300, 150)]))
        self.assertEqual(pages.rows(150), [{"name": "page-1.png", "pt_w": 144.0, "pt_h": 72.0}])
        self.assertEqual(pages.rows(300), [{"name": "page-1.png", "pt_w": 72.0, "pt_h": 36.0}])

    def test_rows_are_new_each_call(self):
        """A caller that writes into the rows it was given (BuildQueries.page_facts does) changes no later answer."""
        pages = read_folder_pages(publish(self.ms, B1, [(300, 150)]))
        first = pages.rows(150)
        first[0]["figure"] = "f1"
        first.append({"name": "extra"})
        self.assertEqual(pages.rows(150), [{"name": "page-1.png", "pt_w": 144.0, "pt_h": 72.0}])

    def test_rows_equal_page_list(self):
        """The rows are what page_list answers for the folder, an unreadable image left out of both."""
        folder = publish(self.ms, B1, [(300, 150), (200, 100), (1241, 1754)])
        (folder / "page-2.png").write_bytes(b"short")
        for dpi in (72, 150, 151):
            with self.subTest(dpi=dpi):
                self.assertEqual(read_folder_pages(folder).rows(dpi), page_list(folder, dpi))


class KeepingAFolder(Fixture):
    """PageFolderCache.pages: a stamped folder on screen is read once; anything that could still change is not kept."""

    def test_a_stamped_folder_is_read_once(self):
        """The second answer for a published folder equals the first and touches no file."""
        folder = publish(self.ms, B1, [(300, 150)] * 3)
        cache = PageFolderCache()
        first = cache.pages(self.ms, folder)
        counts, again = fs_calls(lambda: cache.pages(self.ms, folder))
        self.assertEqual(again, first)
        self.assertEqual((first.count, len(first.sized)), (3, 3))
        self.assertEqual(disk_reads(counts), 0)
        self.assertEqual(cache.held(), 3)

    def test_the_second_read_costs_the_same_for_three_pages_as_for_thirty(self):
        """What a kept folder costs does not grow with its pages."""
        cache = PageFolderCache()
        small = publish(self.ms, B1, [(300, 150)] * 3)
        large = publish(self.rr, B1, [(300, 150)] * 30)
        cache.pages(self.ms, small)
        cache.pages(self.rr, large)
        few, _ = fs_calls(lambda: cache.pages(self.ms, small))
        many, _ = fs_calls(lambda: cache.pages(self.rr, large))
        self.assertEqual(sum(few.values()), sum(many.values()))
        self.assertEqual(disk_reads(many), 0)

    def test_the_legacy_folder_is_never_kept(self):
        """<state>/pages is not a build name no other build gets: it is read at every call."""
        legacy = self.ms.dir / "pages"
        legacy.mkdir(parents=True)
        write_pages(legacy, [(300, 150)])
        (self.ms.dir / "pages.cur").write_text("pages", encoding="utf-8")
        cache = PageFolderCache()
        self.assertEqual(cache.pages(self.ms, legacy).count, 1)
        (legacy / "page-2.png").write_bytes(png_header(10, 10))
        self.assertEqual(cache.pages(self.ms, legacy).count, 2)
        self.assertEqual(cache.held(), 0)

    def test_an_empty_folder_is_not_kept(self):
        """A stamped folder without a page is answered and read again next time."""
        folder = publish(self.ms, B1, [])
        cache = PageFolderCache()
        self.assertEqual(cache.pages(self.ms, folder), FolderPages(0, ()))
        (folder / "page-1.png").write_bytes(png_header(10, 10))
        self.assertEqual(cache.pages(self.ms, folder).count, 1)

    def test_a_folder_with_an_unreadable_image_is_not_kept(self):
        """One image that could not be read may be one failed read: the folder is read again, and answers the image
        once it can be read."""
        folder = publish(self.ms, B1, [(300, 150)] * 3)
        whole = (folder / "page-2.png").read_bytes()
        (folder / "page-2.png").write_bytes(whole[:10])
        cache = PageFolderCache()
        first = cache.pages(self.ms, folder)
        self.assertEqual((first.count, len(first.sized), cache.held()), (3, 2, 0))
        (folder / "page-2.png").write_bytes(whole)
        self.assertEqual(len(cache.pages(self.ms, folder).sized), 3)

    def test_a_read_the_pointer_moved_away_from_is_answered_and_not_kept(self):
        """A page swap during the read may be deleting the folder being read: its answer is given and not kept."""
        folder = publish(self.ms, B1, [(300, 150)] * 3)

        def reads_then_swaps(pdir: Path) -> FolderPages:
            """Read the folder, then let a build put another one on screen before the answer is back."""
            got = read_folder_pages(pdir)
            publish(self.ms, B2, [(10, 10)])
            return got

        cache = PageFolderCache(read=reads_then_swaps)
        self.assertEqual(cache.pages(self.ms, folder).count, 3)
        self.assertEqual(cache.held(), 0)

    def test_two_documents_with_one_build_name_keep_their_own_pages(self):
        """Two documents published in the same second have the same build name and different pages."""
        cache = PageFolderCache()
        body = publish(self.ms, B1, [(300, 150)] * 2)
        reply = publish(self.rr, B1, [(600, 800)] * 5)
        self.assertEqual((cache.pages(self.ms, body).count, cache.pages(self.rr, reply).count), (2, 5))
        self.assertEqual((cache.pages(self.ms, body).count, cache.pages(self.rr, reply).count), (2, 5))
        self.assertEqual(cache.pages(self.rr, reply).sized[0], ("page-1.png", 600, 800))

    def test_two_builds_of_one_document_keep_their_own_pages(self):
        """A rebuild is another name, and so another answer."""
        cache = PageFolderCache()
        self.assertEqual(cache.pages(self.ms, publish(self.ms, B1, [(300, 150)] * 2)).count, 2)
        self.assertEqual(cache.pages(self.ms, publish(self.ms, B3, [(300, 150)] * 4)).count, 4)
        self.assertEqual(cache.pages(self.ms, self.ms.dir / B3).count, 4)

    def test_the_rows_kept_stay_within_the_limit_oldest_first(self):
        """Past the limit the folder kept first is dropped, and is read again when asked for."""
        cache = PageFolderCache(max_rows=5)
        old = publish(self.ms, B1, [(300, 150)] * 3)
        cache.pages(self.ms, old)
        cache.pages(self.ms, publish(self.ms, B2, [(300, 150)] * 3))
        self.assertEqual(cache.held(), 3)
        counts, _ = fs_calls(lambda: cache.pages(self.ms, self.ms.dir / B2))
        self.assertEqual(disk_reads(counts), 0)
        (self.ms.dir / "pages.cur").write_text(B1, encoding="utf-8")
        counts, _ = fs_calls(lambda: cache.pages(self.ms, old))
        self.assertGreater(counts["open"], 3)

    def test_a_folder_larger_than_the_limit_is_not_kept(self):
        """A folder that would not fit is answered from the disk every time and evicts nothing."""
        cache = PageFolderCache(max_rows=5)
        small = publish(self.rr, B1, [(300, 150)] * 2)
        cache.pages(self.rr, small)
        self.assertEqual(cache.pages(self.ms, publish(self.ms, B1, [(300, 150)] * 6)).count, 6)
        self.assertEqual(cache.held(), 2)

    def test_the_default_limit_is_the_module_constant(self):
        """A run's cache holds at most PAGE_ROWS_MAX rows."""
        self.assertEqual(PageFolderCache().max_rows, artifacts.PAGE_ROWS_MAX)
        self.assertEqual(artifacts.PAGE_ROWS_MAX, 4096)

    def test_two_caches_share_nothing(self):
        """What one run keeps another run does not have."""
        folder = publish(self.ms, B1, [(300, 150)] * 3)
        one, two = PageFolderCache(), PageFolderCache()
        one.pages(self.ms, folder)
        self.assertEqual((one.held(), two.held()), (3, 0))


class CountingAFolder(Fixture):
    """PageFolderCache.count: the page count a brief reports."""

    def test_count_of_the_legacy_folder_opens_no_image(self):
        """The legacy folder is known by its name before it is read, so a count there is a listing only."""
        legacy = self.ms.dir / "pages"
        legacy.mkdir(parents=True)
        write_pages(legacy, [(300, 150)] * 3)
        (self.ms.dir / "pages.cur").write_text("pages", encoding="utf-8")
        cache = PageFolderCache()
        counts, got = fs_calls(lambda: cache.count(self.ms, legacy))
        self.assertEqual((got, counts["open"], cache.held()), (3, 0, 0))

    def test_count_of_a_stamped_folder_fills_what_is_kept(self):
        """A brief of a published folder reads it whole once, so the next read of either kind touches no file."""
        folder = publish(self.ms, B1, [(300, 150)] * 3)
        cache = PageFolderCache()
        self.assertEqual(cache.count(self.ms, folder), 3)
        self.assertEqual(cache.held(), 3)
        counts, pages = fs_calls(lambda: cache.pages(self.ms, folder))
        self.assertEqual((len(pages.sized), disk_reads(counts)), (3, 0))
        counts, got = fs_calls(lambda: cache.count(self.ms, folder))
        self.assertEqual((got, disk_reads(counts)), (3, 0))

    def test_count_includes_an_image_that_cannot_be_read(self):
        """n_pages counts names, as it always has, whether or not each image can be sized."""
        folder = publish(self.ms, B1, [(300, 150)] * 3)
        (folder / "page-3.png").write_bytes(b"")
        self.assertEqual(PageFolderCache().count(self.ms, folder), 3)
