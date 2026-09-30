"""A figure document for the tests: a figure folder with its drawing script and shared components, the element map of
the spec's example, and build folders with that map's copy on screen - no producer or pdftoppm (the map pick reads
the map copy and the script only). tests/support/helpers.py's figure_map() (P1a) is the same example without the August
cell; b2_map() here adds that cell (drawn without code) and a July box that a re-render can move.

figure_doc() makes figs/ under a manuscript and returns the document (key fig, folder figs/, map
figs/out/figures.limnmap.json); write_build() puts a build of it on screen, and import_build() imports one through the
tracked build (only pdftoppm stood in for), as the watch and startup do. Every page is PAGE_PT points (a
1500 x 1000 px image at the tests' 150 dpi), and the *_BOX drags are in those points. Test modules import fixtures
only from helpers modules, never from one another (tests/support/helpers.py).

The viewer tests (P1c) add viewer_docs(): the manuscript, figure_doc()'s figure and a reviewer's view-only PDF served
together, each with a two-page build of real page images (the figure's page 1 is 3:1); viewer_map() and
viewer_rerender() move the July cell, take it to page 2 or drop it, as a re-render does.
"""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, TypeAlias
from unittest import mock

from limn.administration import serve_documents as startup_documents
from limn.builds import engine
from limn.builds.artifacts import FIGMAP_NAME, BuildBusy, FinishedBuild, PagesNotRendered
from limn.pins.location import source as pick_source
from limn.platform import files
from limn.runtime.documents import Doc, RunPaths
from limn.web.errors import InputRejected

from helpers import add_pin, blank_png, minimal_pdf, pick

BUILD1 = "pages-20260926100000"
BUILD2 = "pages-20260926110000"
PAGE_PT = (720.0, 480.0)
JULY = (0.47, 0.18, 0.07, 0.12)  # the July cell: x 338.4-388.8, y 86.4-144 points
AUGUST = (0.55, 0.18, 0.07, 0.12)  # the August cell, drawn without code (D7): x 396-446.4
JULY_BOX = (345.0, 95.0, 380.0, 130.0)  # a drag inside the July cell
AUGUST_BOX = (400.0, 95.0, 440.0, 130.0)  # a drag inside the August cell
STRIP_BOX = (100.0, 95.0, 140.0, 130.0)  # a drag inside the calendar strip (x 43.2-676.8, y 86.4-144), over no cell
EMPTY_BOX = (100.0, 300.0, 200.0, 400.0)  # a drag below the calendar strip, over no element but the figure
SCRIPT = "figs/src/B2_calendar.py"  # the drawing script, relative to the manuscript


def png_header(w: int, h: int) -> bytes:
    """The first bytes of a w x h PNG - all limn.builds.artifacts.page_list reads of a page image."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + w.to_bytes(4, "big")
        + h.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )


def script_lines(n: int = 140) -> list[str]:
    """The first n lines of the drawing script: a distinct statement per line, where L12 opens the figure, L88 is the
    comment above the July cell's call (L89-L95) and L140 closes the figure."""
    lines = ["step_%03d = draw(%d)" % (i, i) for i in range(1, n + 1)]
    for no, text in ((12, "def draw_b2():"), (88, "    # July cell"), (140, "    return fig")):
        if no <= n:
            lines[no - 1] = text
    return lines


def b2_map(july: tuple[float, float, float, float] = JULY, august: bool = True) -> dict:
    """The element map of the spec's example: figure B2 (lines 12-140), its calendar strip (80-97), the July cell
    (88-95, shared component lib/components.py 410-470) at box `july`, and - unless august is False - the August cell
    drawn without code (no src, D7). Paths are relative to the figure folder."""
    elements = [
        {"id": "B2", "frac": [0, 0, 1, 1], "src": {"file": "src/B2_calendar.py", "lo": 12, "hi": 140}},
        {
            "id": "B2/calendar",
            "parent": "B2",
            "part": "CalendarStrip",
            "label": "달력",
            "frac": [0.06, 0.18, 0.88, 0.12],
            "src": {"file": "src/B2_calendar.py", "lo": 80, "hi": 97},
        },
        {
            "id": "B2/calendar/m07",
            "parent": "B2/calendar",
            "part": "MonthCell",
            "label": "7월",
            "frac": list(july),
            "src": {"file": "src/B2_calendar.py", "lo": 88, "hi": 95},
            "impl": {"file": "lib/components.py", "lo": 410, "hi": 470},
        },
    ]
    if august:
        elements.append(
            {
                "id": "B2/calendar/m08",
                "parent": "B2/calendar",
                "part": "MonthCell",
                "label": "8월",
                "frac": list(AUGUST),
            }
        )
    return {
        "format": "limn-figure-map/1",
        "pdf": "figures.pdf",
        "pdf_sha256": "0" * 64,
        "pages": [{"page": 1, "figure": "B2", "title": "Deployment calendar", "elements": elements}],
    }


def figure_doc(src: Path, paths: RunPaths) -> Doc:
    """Figure document fig (그림) over manuscript src: figs/ holds src/B2_calendar.py (script_lines()),
    lib/components.py (480 lines) and out/figures.limnmap.json (b2_map()) beside out/figures.pdf."""
    fig = src / "figs"
    for sub in ("src", "lib", "out"):
        (fig / sub).mkdir(parents=True, exist_ok=True)
    (fig / "src" / "B2_calendar.py").write_text("\n".join(script_lines()) + "\n", encoding="utf-8")
    (fig / "lib" / "components.py").write_text(
        "".join("part_%03d = shape(%d)\n" % (i, i) for i in range(1, 481)), encoding="utf-8"
    )
    (fig / "out" / "figures.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (fig / "out" / "figures.limnmap.json").write_text(json.dumps(b2_map(), ensure_ascii=False), encoding="utf-8")
    return Doc("fig", "그림", "figure", fig, fig / "out" / "figures.limnmap.json", paths=paths)


def write_build(D: Doc, name: str, fmap: dict | None, pages: int = 1) -> Path:
    """Put build `name` of figure document D on screen as an import leaves it: `pages` page images of PAGE_PT, the PDF
    copy (D.pdf_name) and, unless fmap is None, the map copy (FIGMAP_NAME). Returns the build folder."""
    d = D.dir / name
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, pages + 1):
        (d / ("page-%d.png" % i)).write_bytes(png_header(1500, 1000))
    (d / D.pdf_name).write_bytes(b"%PDF-1.4\n%%EOF\n")
    if fmap is not None:
        (d / FIGMAP_NAME).write_text(json.dumps(fmap, ensure_ascii=False), encoding="utf-8")
    files.atomic_write(D.dir / "pages.cur", name)
    return d


def import_build(app: Any, D: Doc, name: str, fmap: dict, *, renders: bool = True) -> FinishedBuild | BuildBusy:
    """Import build `name` of figure document D through its tracked build, as the watch and startup do: fmap - stamped
    with the SHA-256 of D's PDF, so the pair agrees - is written as the map beside the PDF, and
    app.build_requests.build_all(D) reads and checks the pair, renders it and moves pages.cur to the new page directory.
    Only pdftoppm is stood in for: a render (renders True) makes directory `name` with one PAGE_PT page image, the PDF
    copy and the map copy, as engine.render_pages leaves it; with renders False it fails (PagesNotRendered) and nothing
    is committed. Returns the tracked build's outcome."""
    pdf = D.main.parent / fmap["pdf"]
    stamped = {**fmap, "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()}
    D.main.write_text(json.dumps(stamped, ensure_ascii=False), encoding="utf-8")

    def render_pages(doc: Doc, pdf_path: Path, extra: list[Path], dpi: int) -> Path | PagesNotRendered:
        """engine.render_pages without pdftoppm: the page directory `name`, or why there is none."""
        if not renders:
            return PagesNotRendered("render", "")
        newdir = doc.dir / name
        newdir.mkdir(parents=True)
        (newdir / "page-1.png").write_bytes(png_header(1500, 1000))
        shutil.copy2(pdf_path, newdir / doc.pdf_name)
        for f in extra:
            shutil.copy2(f, newdir / f.name)
        return newdir

    with mock.patch.object(engine, "render_pages", render_pages):
        return app.build_requests.build_all(D)


SAVE_LINE = (
    "file",
    "name",
    "page",
    "lo",
    "hi",
    "raw_lo",
    "raw_hi",
    "kind",
    "via",
    "score",
    "frac",
    "quote",
    "pdf_build",
    "el",
)


def pin_from_pick(fig: Doc, box: tuple[float, float, float, float], actor: dict, note: str = "n") -> int:
    """Pick box (points) on build BUILD1 of figure document fig and save the answer as the viewer does - a line pin with
    its el at the default level, or, when the pick fell back, a region pin with the el - as actor; the new pin's id.
    pdftotext answers no text."""
    x0, y0, x1, y1 = box
    with mock.patch.object(pick_source, "region_text", return_value=""):
        d = pick({"doc": fig.key, "page": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "pdf_build": BUILD1}, doc=fig)
    if d.get("kind") == "region":
        body = {k: d[k] for k in ("page", "frac", "quote", "pdf_build", "el") if d.get(k) not in (None, "")}
    else:
        body = {k: d[k] for k in SAVE_LINE if d.get(k) is not None}
        body["scope"] = d["default_level"]
    body.update(doc=fig.key, note=note)
    pin = add_pin(body, dict(actor))
    assert not isinstance(pin, InputRejected), pin
    return pin.core.pid


# ---------------------------------------------------------------- the viewer tests' documents (P1c)

Box: TypeAlias = tuple[float, float, float, float]  # x, y, w, h in page fractions
FIG = "fig"  # figure_doc()'s key
ROOT_ID, STRIP_ID, CELL_ID = "B2", "B2/calendar", "B2/calendar/m07"
STRIP_FRAC: Box = (0.06, 0.18, 0.88, 0.12)  # the calendar strip's box in b2_map()
CELL_DRAG: Box = (0.48, 0.20, 0.04, 0.08)  # a drag inside the July cell (JULY), as page fractions
STRIP_DRAG: Box = (0.20, 0.20, 0.04, 0.08)  # a drag inside the strip, clear of the July and August cells
WIDE_PX, TALL_PX = (2400, 800), (1275, 1650)  # page images at 150 dpi: the figure's page 1 is 3:1, the rest portrait


def viewer_map(july: Box | None = JULY, july_page: int = 1) -> dict[str, Any]:
    """b2_map() with a second page (figure B3, lines 1-10) and the July cell where a re-render left it: at box july on
    page july_page (2: under figure B3), or gone (july None) - its id renamed or dropped."""
    fmap = b2_map(JULY if july is None else july)
    one = fmap["pages"][0]["elements"]
    cell = next(e for e in one if e["id"] == CELL_ID)
    two = [{"id": "B3", "frac": [0, 0, 1, 1], "src": {"file": "src/B2_calendar.py", "lo": 1, "hi": 10}}]
    if july is None or july_page != 1:
        one.remove(cell)
    if july is not None and july_page == 2:
        two.append(dict(cell, parent="B3"))
    fmap["pages"].append({"page": 2, "figure": "B3", "title": "Review flow", "elements": two})
    return fmap


def viewer_build(D: Doc, name: str, fmap: dict[str, Any] | None = None) -> Path:
    """Put the two-page build `name` of document D on screen for the browser: write_build()'s folder (with fmap's copy
    for a figure) whose page images are real PNGs - page 1 WIDE_PX on a figure, TALL_PX otherwise, page 2 TALL_PX - a
    view-only document's own PDF as its copy, and the built_at/head files the meta route reads."""
    d = write_build(D, name, fmap, pages=2)
    for i, (w, h) in enumerate((WIDE_PX if D.has_element_map else TALL_PX, TALL_PX), 1):
        (d / ("page-%d.png" % i)).write_bytes(blank_png(w, h))
    if D.view_only:
        (d / D.pdf_name).write_bytes(D.main.read_bytes())
    (D.dir / "built_at.txt").write_text("2026-09-25 10:00:00")
    (D.dir / "head.txt").write_text("abc1234")
    return d


def viewer_docs(app: Any, src: Path) -> list[Doc]:
    """Serve the LaTeX manuscript src/main.tex (ms), figure_doc()'s figure (fig) and a reviewer's view-only PDF (rv) from
    app, each with build BUILD1 on screen (viewer_map() for the figure); returns the three documents in that order."""
    (src / "reviewer.pdf").write_bytes(minimal_pdf("reviewer"))
    docs = startup_documents.make_docs(["ms=본문:main.tex", "rv=리뷰어:reviewer.pdf"], src, app.C.paths)
    assert isinstance(docs, list), docs
    ms, rv = docs
    fig = figure_doc(src, app.C.paths)
    app.set_docs([ms, fig, rv])
    for D in (ms, fig, rv):
        viewer_build(D, BUILD1, viewer_map() if D.has_element_map else None)
    return [ms, fig, rv]


def viewer_rerender(D: Doc, july: Box | None = JULY, july_page: int = 1) -> None:
    """The figure repository rendered again and the import took it: build BUILD2 on screen, with the July cell at july on
    july_page, or gone (july None)."""
    viewer_build(D, BUILD2, viewer_map(july, july_page))
