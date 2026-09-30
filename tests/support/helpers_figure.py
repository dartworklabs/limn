"""A figure document for the tests: a figure folder with its drawing script and shared components, the element map of
the spec's example, and build folders with that map's copy on screen - no producer or pdftoppm (the map pick reads
the map copy and the script only). tests/support/helpers.py's figure_map() (P1a) is the same example without the August cell;
b2_map() here adds that cell (drawn without code) and a July box that a re-render can move.

figure_doc() makes figs/ under a manuscript and returns the document (key fig, folder figs/, map
figs/out/figures.limnmap.json); write_build() puts a build of it on screen. Every page is PAGE_PT points (a
1500 x 1000 px image at the tests' 150 dpi), and the *_BOX drags are in those points. Test modules import fixtures
only from helpers modules, never from one another (tests/support/helpers.py).
"""

import json
from pathlib import Path
from unittest import mock

from limn.builds.artifacts import FIGMAP_NAME
from limn.pins.location import source as pick_source
from limn.platform import files
from limn.runtime.documents import Doc, RunPaths
from limn.web.errors import InputRejected

from helpers import add_pin, pick

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
    """The element map of the spec's example: figure B2 (lines 12-140), its calendar strip (80-97), the July cell (88-95,
    shared component lib/components.py 410-470) at box `july`, and - unless august is False - the August cell drawn
    without code (no src, D7). Paths are relative to the figure folder."""
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
