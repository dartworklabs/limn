"""tools/measure_figure_pick_d6.py - the original D6 harness, checked on a small made-up map and PDF.

The tool's drags must stay the drags ADR-0015's measurement used, so these tests pin the random stream (seed string,
sampling order, draw order), the outcome classification on hand-checked cases, the table and compare arithmetic, and the
refusals. The map and the PDF are built here; no figure tool's output and no manuscript content is involved.

Run: uv run pytest -q tests/tools/test_measure_figure_pick_d6.py
"""

import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from limn.builds import figure_map
from limn.builds.figure_map import FigureMap, parse_map

TOOL = Path(__file__).resolve().parents[2] / "tools" / "measure_figure_pick_d6.py"
SPEC = importlib.util.spec_from_file_location("measure_figure_pick_d6", TOOL)
assert SPEC and SPEC.loader
d6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(d6)

SIZES = [(200.0, 100.0), (150.0, 150.0)]  # page 1 carries the figure below; page 2 is a root-only page
# The first page, boxes in page fractions (x, y, w, h). A page is 200 x 100 pt, so P is 100 x 60 pt.
#   F1  root
#   P   a panel holding G                 G  a group holding G1 and G2        G1 holds G1a, which has G1's box
#   G1  [0.10 0.10 0.15 0.50]  G2 [0.25 0.10 0.25 0.50]  so G1 is 37.5 % and G2 62.5 % of G
#   L   a large leaf of its own           T  a tiny leaf (4 x 5 pt)           M  a medium leaf (20 x 15 pt)
BOXES = {
    "F1/P": ("F1", (0.05, 0.05, 0.50, 0.60)),
    "F1/G": ("F1/P", (0.10, 0.10, 0.40, 0.50)),
    "F1/G1": ("F1/G", (0.10, 0.10, 0.15, 0.50)),
    "F1/G1a": ("F1/G1", (0.10, 0.10, 0.15, 0.50)),
    "F1/G2": ("F1/G", (0.25, 0.10, 0.25, 0.50)),
    "F1/L": ("F1", (0.70, 0.20, 0.20, 0.40)),
    "F1/T": ("F1", (0.60, 0.80, 0.02, 0.05)),
    "F1/M": ("F1", (0.30, 0.75, 0.10, 0.15)),
}
K = {(c, f): i * len(d6.FILLS) + j for i, c in enumerate(d6.COVERS) for j, f in enumerate(d6.FILLS)}  # grid column


def make_pdf(sizes) -> bytes:
    """A valid PDF with one empty page of each (width, height) in points."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    for w, h in sizes:
        kids.append(len(objs) + 1)
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] >>" % (w, h))
    objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


def make_map_bytes(pdf: bytes, **changes) -> bytes:
    """The limn-figure-map/1 bytes of the made-up figure for the PDF, with top-level keys replaced by changes."""
    elements = [{"id": "F1", "frac": [0, 0, 1, 1]}]
    elements += [{"id": i, "parent": p, "frac": list(box)} for i, (p, box) in BOXES.items()]
    doc = {
        "format": "limn-figure-map/1",
        "pdf": "synthetic.pdf",
        "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        "pages": [
            {"page": 1, "figure": "F1", "elements": elements},
            {"page": 2, "figure": "F2", "elements": [{"id": "F2", "frac": [0, 0, 1, 1]}]},
        ],
    }
    doc.update(changes)
    return json.dumps(doc).encode()


PDF = make_pdf(SIZES)
MAP_BYTES = make_map_bytes(PDF)


@pytest.fixture(scope="module")
def fmap() -> FigureMap:
    """The made-up map parsed by the real parser, so the tests judge picks on the structure the picker sees."""
    parsed = parse_map(MAP_BYTES)
    assert isinstance(parsed, FigureMap)
    return parsed


@pytest.fixture(scope="module")
def drags(fmap):
    """The model's drags for the made-up map and PDF at the default seed, shared by the tests that inspect them."""
    return d6.make_drags(fmap, d6.page_sizes(PDF))


# ---------------------------------------------------------------- The PDF and the size classes


def test_page_sizes_are_the_media_boxes_in_file_order():
    """Page sizes come from each /MediaBox in file order, because they turn page fractions into points for every
    drag."""
    assert d6.page_sizes(make_pdf([(200, 100), (150, 150), (612, 792)])) == [(200, 100), (150, 150), (612, 792)]
    assert d6.page_sizes(b"%PDF-1.4 /MediaBox [ 10 20  110.5 70.25 ]") == [(100.5, 50.25)]


@pytest.mark.parametrize(
    ("w_pt", "h_pt", "expected"),
    [
        (13, 30, "small"),  # under 14 pt on a side and 390 pt^2
        (13, 31, "medium"),  # 403 pt^2 is not under 400
        (14, 20, "medium"),  # 14 pt on a side is not under 14
        (20, 15, "medium"),
        (4, 5, "small"),
        (100, 41, "big"),  # 4100 pt^2 is over 2 % of the 200,000 pt^2 page
        (100, 39, "medium"),  # 3900 pt^2 is under it
        (13, 400, "big"),  # big is decided first: 5200 pt^2, however thin
    ],
)
def test_size_class(w_pt, h_pt, expected):
    """big is 2 % of the page or more; small is under 14 pt on its short side and under 400 pt^2; the rest is medium."""
    pw, ph = 500.0, 400.0
    assert d6.size_class((0.1, 0.1, w_pt / pw, h_pt / ph), pw, ph) == expected


# ---------------------------------------------------------------- The drag generator


def test_the_stream_is_the_originals_seed_sampling_order_and_draw_order(fmap, drags):
    """A page's stream is Random("<seed>:<figure>"): scopes are sampled, then leaves, then each target's first drag
    draws the viewer scale and four jitters in turn. Replaying those draws by hand gives the first drag exactly."""
    assert d6.SEED == 20261006
    rng = random.Random("20261006:F1")
    scopes = rng.sample([fmap.find(i)[1] for i in ("F1/P", "F1/G", "F1/G1")], 3)
    leaves = rng.sample([fmap.find(i)[1] for i in ("F1/G1a", "F1/G2", "F1/L", "F1/T", "F1/M")], 5)
    targets = list(dict.fromkeys(d.target for d in drags))
    assert targets == [e.id for e in scopes + leaves]
    pw, ph = SIZES[0]
    x, y, w, h = (a * b for a, b in zip(scopes[0].frac, (pw, ph, pw, ph), strict=True))
    s = rng.uniform(1.42, 2.13)
    j = [rng.gauss(0.0, 1.5) / s for _ in range(4)]
    x0, y0, x1, y1 = x + j[0], y + j[1], x + w + j[2], y + h + j[3]
    first = drags[0]
    assert (first.page, first.target, first.kind, first.partner) == (0, scopes[0].id, "tight", None)
    assert first.frac == pytest.approx((x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph), abs=1e-12)


def test_drags_are_fixed_by_the_seed(fmap):
    """One seed gives one drag list and another seed gives another, so two pickers can be compared on the very same
    drags."""
    sizes = d6.page_sizes(PDF)
    assert d6.make_drags(fmap, sizes) == d6.make_drags(fmap, sizes)
    assert d6.make_drags(fmap, sizes, seed=7) == d6.make_drags(fmap, sizes, seed=7)
    assert d6.make_drags(fmap, sizes, seed=7) != d6.make_drags(fmap, sizes)


def test_the_drags_of_the_made_up_map_are_pinned(drags):
    """Every drag, rounded to 9 places, hashed: a change to any draw, its order or its arithmetic changes the digest."""
    text = repr([(d.page, d.target, d.kind, d.size, [round(v, 9) for v in d.frac], d.partner) for d in drags])
    assert (
        hashlib.sha256(text.encode()).hexdigest() == "6f8c48c99c0642e77bcba786126621be8231e1f99291aeae86f0f6a17637e4cd"
    )


def test_targets_kinds_and_partners(drags):
    """8 targets of page 1 (3 scopes, 5 leaves), 4 drags per target and kind; the root-only page 2 yields none. partial
    needs a leaf; span2 needs a sibling with another box (G and G1a have none), and carries it."""
    assert {d.page for d in drags} == {0}
    assert len(drags) == 140
    counts = {k: sum(d.kind == k for d in drags) for k in d6.KINDS}
    assert counts == {"tight": 32, "loose-rel": 32, "loose-px": 32, "partial": 20, "span2": 24}
    assert {d.target for d in drags if d.kind == "partial"} == {"F1/G1a", "F1/G2", "F1/L", "F1/T", "F1/M"}
    span = {d.target: d.partner for d in drags if d.kind == "span2"}
    assert span == {  # the nearest sibling by the squared gap between boxes (pt^2), P = [10 110] x [5 65] pt
        "F1/P": "F1/M",  # M 10 pt below P (100); T is 325 away, L 900
        "F1/G1": "F1/G2",
        "F1/G2": "F1/G1",
        "F1/L": "F1/T",  # T 16 pt left and 20 pt below L (656); P is 900 away, M 3825
        "F1/T": "F1/P",  # P 10 pt left and 15 pt above T (325); L is 656 away, M 1600
        "F1/M": "F1/P",  # P 10 pt above M (100); T is 1600 away, L 3825
    }
    assert all((d.partner is not None) == (d.kind == "span2") for d in drags)
    assert {d.target: d.size for d in drags} == {
        "F1/P": "big",
        "F1/G": "big",
        "F1/G1": "big",
        "F1/G1a": "big",
        "F1/G2": "big",
        "F1/L": "big",
        "F1/T": "small",
        "F1/M": "medium",
    }


def test_every_drag_is_on_the_page_and_at_least_three_pixels(drags):
    """At most 2.13 px per point, so 3 px is at least 1.4 pt; the page edge clips a drag, never an element's drag here."""
    pw, ph = SIZES[0]
    for d in drags:
        x, y, w, h = d.frac
        assert x >= 0 and y >= 0 and x + w <= 1 + 1e-12 and y + h <= 1 + 1e-12
        assert w * pw >= 3 / 2.13 - 1e-9 and h * ph >= 3 / 2.13 - 1e-9


def test_drags_refuse_a_pdf_with_another_page_count(fmap):
    """A PDF whose page count differs from the map's is refused, not paired short, which would silently drop pages from
    the measurement."""
    with pytest.raises(d6.InputError, match="2 pages but the PDF has 1 /MediaBox"):
        d6.make_drags(fmap, d6.page_sizes(make_pdf([(200, 100)])))


# ---------------------------------------------------------------- Judging a pick


def el(fmap, el_id):
    """The map element with this id, to hand the classifier a picked answer built by hand."""
    return fmap.find(el_id)[1]


@pytest.mark.parametrize(
    ("target", "chosen", "outcome"),
    [
        ("F1/G2", "F1/G2", "correct"),  # the target itself
        ("F1/G1", "F1/G1a", "correct"),  # a child with the target's box cannot be told apart on the page
        ("F1/G", "F1/G2", "finer"),  # a descendant
        ("F1/G", "F1/G1a", "finer"),
        ("F1/G2", "F1/G", "coarser"),  # a proper ancestor other than the root
        ("F1/G2", "F1/P", "coarser"),
        ("F1/G2", "F1/L", "wrong"),  # an unrelated element
        ("F1/G2", "F1/G1", "wrong"),  # a sibling is unrelated too
        ("F1/G2", "F1", "none"),  # the root
        ("F1/P", "F1", "none"),
    ],
)
def test_single_target_outcomes(fmap, target, chosen, outcome):
    """Each relation between a pick and its target (itself or same box, descendant, ancestor, unrelated, root) gets its
    own outcome name, which is how every table column is counted."""
    assert d6.OUT[d6.classify(fmap.pages[0], target, el(fmap, chosen), None)] == outcome


@pytest.mark.parametrize(
    ("target", "partner", "chosen", "code"),
    [
        ("F1/G1", "F1/G2", "F1/G", 0),  # their nearest common ancestor
        ("F1/G1", "F1/G2", "F1/G1", 1),  # one of the pair
        ("F1/G1", "F1/G2", "F1/G2", 1),
        ("F1/G1", "F1/G2", "F1/G1a", 1),  # inside one of the pair
        ("F1/G1", "F1/G2", "F1/P", 2),  # above their common ancestor
        ("F1/G1", "F1/G2", "F1/L", 3),
        ("F1/G1", "F1/G2", "F1", 4),  # the root when it is not their common ancestor
        ("F1/L", "F1/T", "F1", 0),  # the root when it is
        ("F1/L", "F1/T", "F1/L", 1),
        ("F1/L", "F1/T", "F1/M", 3),
    ],
)
def test_span2_outcomes(fmap, target, partner, chosen, code):
    """A drag over a pair is judged against the pair's nearest common ancestor, so the span2 columns tell reaching it
    from stopping at a part, overshooting or missing."""
    assert d6.classify(fmap.pages[0], target, el(fmap, chosen), partner) == code


def codes_of(fmap, target, frac, partner=None):
    """The 169 outcome codes of one hand-made drag, by the tool's own worker."""
    d6._load(MAP_BYTES)
    drag = d6.Drag(0, target, "tight", "big", frac, partner)
    (raw,) = d6._work([drag])
    assert len(raw) == len(d6.COVERS) * len(d6.FILLS)
    return list(raw)


def by_cover(codes):
    """Per cover (the grid's major axis) the code, after checking that no fill changes it."""
    out = []
    for i in range(len(d6.COVERS)):
        row = codes[i * len(d6.FILLS) : (i + 1) * len(d6.FILLS)]
        assert len(set(row)) == 1
        out.append(row[0])
    return out


def test_a_drag_on_the_group_picks_a_part_until_the_cover_floor_passes_the_parts(fmap):
    """The drag is exactly G's box. G1a (and its parent G1, 37.5 % of the drag) is the smallest unpruned candidate for
    a cover floor up to 0.35, G2 (62.5 %) up to 0.6, then only G and the panel P are candidates and G is the child.
    Against the target G the parts are finer; G itself is correct."""
    drag = (0.10, 0.10, 0.40, 0.50)
    expected = [1 if c <= 0.6 else 0 for c in d6.COVERS]
    assert by_cover(codes_of(fmap, "F1/G", drag)) == expected
    # the same drag read as an aim at the pair G1, G2: a part is one of the pair, G is their common ancestor
    assert by_cover(codes_of(fmap, "F1/G1", drag, "F1/G2")) == expected


def test_hand_made_drags_land_in_each_outcome_at_every_threshold(fmap):
    """Drags with the same answer at all 169 cells land in the expected outcome through the whole worker path, so
    classification and grid agree end to end."""
    grid = len(d6.COVERS)
    assert by_cover(codes_of(fmap, "F1/L", (0.70, 0.20, 0.20, 0.40))) == [0] * grid  # exactly L
    assert by_cover(codes_of(fmap, "F1/L", (0.30, 0.75, 0.10, 0.15))) == [3] * grid  # exactly M: unrelated to L
    assert by_cover(codes_of(fmap, "F1/G2", (0.06, 0.20, 0.03, 0.20))) == [2] * grid  # P's margin, beside G: P
    assert by_cover(codes_of(fmap, "F1/G2", (0.02, 0.85, 0.10, 0.10))) == [4] * grid  # empty page: the root


def test_the_cells_run_cover_major_and_the_thresholds_are_put_back(fmap, monkeypatch):
    """The grid runs cover-major, which the reports index by, and the picker's constants are restored, so an in-process
    caller keeps the shipped thresholds."""
    monkeypatch.setattr(figure_map, "COVER_MIN", 0.42)
    monkeypatch.setattr(figure_map, "FILL_MIN", 0.57)
    codes = codes_of(fmap, "F1/G", (0.10, 0.10, 0.40, 0.50))
    assert (figure_map.COVER_MIN, figure_map.FILL_MIN) == (0.42, 0.57)
    assert codes[K[(0.6, 0.5)]] == 1 and codes[K[(0.65, 0.5)]] == 0
    assert codes[: len(d6.FILLS)] == [1] * len(d6.FILLS)  # the first cover, every fill


def test_the_nearest_sibling_is_the_smallest_gap_then_the_nearest_centre():
    """The key is the squared gap between the boxes (0 when they overlap), then the Manhattan distance of the centres."""
    target = (10.0, 10.0, 20.0, 20.0)  # points on a 100 x 100 pt page
    apart = SimpleNamespace(frac=(0.5, 0.1, 0.1, 0.2))  # 20 pt to the right, level with the target
    overlapping = SimpleNamespace(frac=(0.2, 0.2, 0.2, 0.2))
    assert d6._sibling_gap(apart, target, 100.0, 100.0) == pytest.approx((400.0, 35.0))
    assert d6._sibling_gap(overlapping, target, 100.0, 100.0) == pytest.approx((0.0, 20.0))
    same_gap_nearer = SimpleNamespace(frac=(0.5, 0.1, 0.1, 0.2))
    same_gap_farther = SimpleNamespace(frac=(0.5, 0.1, 0.5, 0.2))
    assert d6._sibling_gap(same_gap_nearer, target, 100.0, 100.0) < d6._sibling_gap(
        same_gap_farther, target, 100.0, 100.0
    )


# ---------------------------------------------------------------- Measuring


@pytest.fixture(scope="module")
def measured():
    """The made-up map measured once in-process, shared by the result and command-line tests."""
    return d6.measure(MAP_BYTES, PDF, workers=1)


def test_measure_holds_every_drag_over_the_whole_grid(measured, drags):
    """A results file holds one row per drag with all 169 codes and a meta record of seed and input hashes, which is
    what makes two files comparable."""
    assert measured["covers"] == d6.COVERS and measured["fills"] == d6.FILLS and measured["outcomes"] == d6.OUT
    assert len(measured["rows"]) == len(drags)
    first = measured["rows"][0]
    assert (first["fig"], first["target"], first["kind"], first["span"]) == ("F1", drags[0].target, "tight", False)
    assert all(len(r["codes"]) == 169 and set(r["codes"]) <= set(range(5)) for r in measured["rows"])
    assert [r["span"] for r in measured["rows"]] == [d.partner is not None for d in drags]
    assert measured["meta"] == {
        "seed": 20261006,
        "map_sha256": hashlib.sha256(MAP_BYTES).hexdigest(),
        "pdf_sha256": hashlib.sha256(PDF).hexdigest(),
    }


def test_an_isolated_large_leaf_is_picked_by_tight_and_air_drags_at_the_recommended_floor(measured):
    """L is 40 x 40 pt with nothing near it. A tight drag holds all of L, and a drag with 3-12 px of air still holds at
    least (40 / 57)^2 = 49 % of itself in L, so cover 0.4 / fill 0.5 picks L every time."""
    k = K[(0.4, 0.5)]
    rows = [r for r in measured["rows"] if r["target"] == "F1/L" and r["kind"] in ("tight", "loose-px")]
    assert len(rows) == 8
    assert [r["codes"][k] for r in rows] == [0] * 8


def run_tool(*args):
    """Run the tool as a script in a child process, as uv run python tools/... does, and return the finished process."""
    return subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True, check=False)


def test_the_command_line_with_a_worker_pool_gives_the_same_rows(tmp_path, measured):
    """The pool runs the tool as a script, as `uv run python tools/...` does; its rows equal the in-process ones."""
    (tmp_path / "m.json").write_bytes(MAP_BYTES)
    (tmp_path / "f.pdf").write_bytes(PDF)
    done = run_tool("measure", tmp_path / "m.json", tmp_path / "f.pdf", "-o", tmp_path / "r.json", "--workers", 2)
    assert done.returncode == 0, done.stderr
    assert "140 drags on 1 figures" in done.stderr
    written = json.loads((tmp_path / "r.json").read_text())
    assert written == json.loads(json.dumps(measured))
    shown = run_tool("table", tmp_path / "r.json")
    assert shown.returncode == 0, shown.stderr
    assert shown.stdout.splitlines()[0] == "140 drags / 1 figures / 8 targets"
    assert shown.stdout.splitlines()[1] == "group  n  | 0.6/0.5 ok fi co wr no | 0.4/0.5 ok fi co wr no"


# ---------------------------------------------------------------- Table and compare arithmetic


def synthetic(rows, meta=None):
    """Results of the given (kind, size, code at 0.6/0.5, code at 0.4/0.5) drags; every other cell is 0."""
    out = []
    for n, (kind, size, a, b) in enumerate(rows):
        codes = [0] * (len(d6.COVERS) * len(d6.FILLS))
        codes[K[(0.6, 0.5)]], codes[K[(0.4, 0.5)]] = a, b
        out.append(
            {"fig": f"F{n % 2}", "target": f"t{n}", "kind": kind, "size": size, "span": kind == "span2", "codes": codes}
        )
    return {"covers": d6.COVERS, "fills": d6.FILLS, "outcomes": d6.OUT, "rows": out, "meta": meta or {}}


BEFORE = synthetic(
    [
        ("tight", "small", 0, 0),
        ("tight", "big", 3, 3),
        ("loose-rel", "small", 2, 0),
        ("loose-rel", "small", 2, 2),
        ("loose-px", "medium", 0, 0),
        ("partial", "big", 3, 1),
        ("span2", "small", 0, 1),
        ("span2", "small", 3, 3),
    ]
)
AFTER = synthetic(
    [
        ("tight", "small", 0, 0),
        ("tight", "big", 0, 0),
        ("loose-rel", "small", 0, 0),
        ("loose-rel", "small", 3, 0),
        ("loose-px", "medium", 0, 3),
        ("partial", "big", 3, 3),
        ("span2", "small", 0, 0),
        ("span2", "small", 3, 0),
    ]
)


def test_the_table_is_the_share_of_each_outcome():
    """Shares are percentages of a group's drags (codes: 0 correct, 1 finer, 2 coarser, 3 wrong, 4 none). mean4 averages
    the four single-target kinds' shares, so it differs from the share over their six drags; the size rows leave span2
    out; span2 has its own row."""
    assert d6.format_table(BEFORE, [(0.6, 0.5), (0.4, 0.5)]).splitlines() == [
        "8 drags / 2 figures / 8 targets",
        "group  n  | 0.6/0.5 ok fi co wr no | 0.4/0.5 ok fi co wr no",
        "tight 2 | 50.0 0.0 0.0 50.0 0.0 | 50.0 0.0 0.0 50.0 0.0",  # 0.6: 0 3   0.4: 0 3
        "loose-rel 2 | 0.0 0.0 100.0 0.0 0.0 | 50.0 0.0 50.0 0.0 0.0",  # 0.6: 2 2   0.4: 0 2
        "loose-px 1 | 100.0 0.0 0.0 0.0 0.0 | 100.0 0.0 0.0 0.0 0.0",  # 0 | 0
        "partial 1 | 0.0 0.0 0.0 100.0 0.0 | 0.0 100.0 0.0 0.0 0.0",  # 3 | 1
        # at 0.6 ok (50 + 0 + 100 + 0) / 4, co (0 + 100 + 0 + 0) / 4, wr (50 + 0 + 0 + 100) / 4; at 0.4 ok
        # (50 + 50 + 100 + 0) / 4, fi (0 + 0 + 0 + 100) / 4, co (0 + 50 + 0 + 0) / 4, wr (50 + 0 + 0 + 0) / 4
        "mean4 6 | 37.5 0.0 25.0 37.5 0.0 | 50.0 25.0 12.5 12.5 0.0",
        "span2 2 | 50.0 0.0 0.0 50.0 0.0 | 0.0 50.0 0.0 50.0 0.0",  # 0.6: 0 3   0.4: 1 3
        "small 3 | 33.3 0.0 66.7 0.0 0.0 | 66.7 0.0 33.3 0.0 0.0",  # tight, loose-rel, loose-rel: 0 2 2 | 0 0 2
        "medium 1 | 100.0 0.0 0.0 0.0 0.0 | 100.0 0.0 0.0 0.0 0.0",
        "big 2 | 0.0 0.0 0.0 100.0 0.0 | 0.0 50.0 0.0 50.0 0.0",  # tight, partial: 3 3 | 3 1
    ]


def test_the_compare_pairs_drags_and_counts_gains_and_losses():
    """At 0.4/0.5 the six single-target drags go from [0 3 0 2 0 1] to [0 0 0 0 3 3] (0 correct, 3 wrong). Gained
    correct: the tight big (3 to 0) and the second loose-rel (2 to 0); lost: the loose-px (0 to 3)."""
    assert d6.format_compare(BEFORE, AFTER, (0.4, 0.5)).splitlines() == [
        "correct  4-kind avg  before  50.0  after  50.0",
        "finer    4-kind avg  before  25.0  after   0.0",
        "coarser  4-kind avg  before  12.5  after   0.0",
        "wrong    4-kind avg  before  12.5  after  50.0",
        "none     4-kind avg  before   0.0  after   0.0",
        "single-target drags 6: gained correct 2, lost correct 1, net 1",
        "wrong picks 1 -> 2 of 6",
        "small  tight     n=    1 correct     1->    1 (100.0->100.0%)  wrong     0->    0",
        "small  loose-rel n=    2 correct     1->    2 (50.0->100.0%)  wrong     0->    0",
        "medium loose-px  n=    1 correct     1->    0 (100.0-> 0.0%)  wrong     0->    1",
        "big    tight     n=    1 correct     0->    1 ( 0.0->100.0%)  wrong     1->    0",
        "big    partial   n=    1 correct     0->    0 ( 0.0-> 0.0%)  wrong     0->    1",
    ]


def test_compare_accepts_the_same_file_twice():
    """Comparing a file with itself gains and loses nothing, the baseline that shows the pairing adds no differences of
    its own."""
    report = d6.format_compare(BEFORE, BEFORE, (0.4, 0.5))
    assert "gained correct 0, lost correct 0, net 0" in report


# ---------------------------------------------------------------- Refusals


def test_compare_refuses_results_that_are_not_the_same_drags():
    """Files of another length, drag order, grid, map or seed are refused, because a pairing of different drags would
    pass for a picker difference."""
    shorter = dict(AFTER, rows=AFTER["rows"][:-1])
    with pytest.raises(d6.InputError, match="8 and 7 drags"):
        d6.format_compare(BEFORE, shorter, (0.4, 0.5))
    swapped = dict(AFTER, rows=[AFTER["rows"][1], AFTER["rows"][0], *AFTER["rows"][2:]])
    with pytest.raises(d6.InputError, match="drag 0 is not the same drag"):
        d6.format_compare(BEFORE, swapped, (0.4, 0.5))
    with pytest.raises(d6.InputError, match="different threshold grids"):
        d6.format_compare(BEFORE, dict(AFTER, covers=d6.COVERS[:-1]), (0.4, 0.5))
    other_map = dict(AFTER, meta={"map_sha256": "b" * 64})
    with pytest.raises(d6.InputError, match="differ in map_sha256"):
        d6.format_compare(dict(BEFORE, meta={"map_sha256": "a" * 64}), other_map, (0.4, 0.5))
    with pytest.raises(d6.InputError, match="differ in seed"):
        d6.format_compare(dict(BEFORE, meta={"seed": 1}), dict(AFTER, meta={"seed": 2}), (0.4, 0.5))


def test_a_pair_off_the_grid_is_refused():
    """A threshold pair that is not a measured grid cell is refused, not read from the nearest cell, which would report
    numbers for a pair nobody measured."""
    with pytest.raises(d6.InputError, match="0.42/0.5 is not a measured threshold pair"):
        d6.format_table(BEFORE, [(0.6, 0.5), (0.42, 0.5)])
    with pytest.raises(d6.InputError, match="0.95/0.5 is not a measured threshold pair"):
        d6.format_compare(BEFORE, AFTER, (0.95, 0.5))


def test_results_from_the_original_harness_load_without_a_meta_record(tmp_path):
    """Files written by the recovered scripts, which have no meta record, still load while malformed and truncated files
    are refused, so old measurements stay usable."""
    original = {k: v for k, v in BEFORE.items() if k != "meta"}
    (tmp_path / "r.json").write_text(json.dumps(original))
    assert d6.load_results(tmp_path / "r.json")["meta"] == {}
    (tmp_path / "bad.json").write_text(json.dumps({"rows": []}))
    with pytest.raises(d6.InputError, match="bad.json is not a results file"):
        d6.load_results(tmp_path / "bad.json")
    (tmp_path / "short.json").write_text(json.dumps(dict(original, rows=[dict(original["rows"][0], codes=[0])])))
    with pytest.raises(d6.InputError, match="do not match its 169-cell grid"):
        d6.load_results(tmp_path / "short.json")
    (tmp_path / "text.json").write_text("not json")
    with pytest.raises(d6.InputError, match="cannot read results text.json"):
        d6.load_results(tmp_path / "text.json")


def write_inputs(tmp_path, map_bytes, pdf=PDF):
    """Write the made-up map and a PDF into tmp_path and return the measure arguments for them with one worker."""
    (tmp_path / "m.json").write_bytes(map_bytes)
    (tmp_path / "f.pdf").write_bytes(pdf)
    return [
        "measure",
        str(tmp_path / "m.json"),
        str(tmp_path / "f.pdf"),
        "-o",
        str(tmp_path / "r.json"),
        "--workers",
        "1",
    ]


def test_a_rejected_map_is_refused_with_its_reason(tmp_path, capsys):
    """A map the parser rejects ends the run with status 2, the reason in the message and no results file, so a bad map
    is never measured."""
    argv = write_inputs(tmp_path, make_map_bytes(PDF, format="limn-figure-map/9"))
    with pytest.raises(SystemExit) as stop:
        d6.main(argv)
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert "map rejected: bad_format" in err
    assert not (tmp_path / "r.json").exists()


def test_a_map_that_is_not_json_is_refused(tmp_path, capsys):
    """Bytes that are not JSON are refused with the parser's reason, like any other rejected map."""
    with pytest.raises(SystemExit) as stop:
        d6.main(write_inputs(tmp_path, b"{"))
    assert stop.value.code == 2
    assert "map rejected: not_json" in capsys.readouterr().err


def test_a_pdf_with_another_page_count_is_refused(tmp_path, capsys):
    """The command refuses a PDF with another page count and names both counts, so the mismatch can be fixed from the
    message."""
    with pytest.raises(SystemExit) as stop:
        d6.main(write_inputs(tmp_path, MAP_BYTES, make_pdf([(200, 100)])))
    assert stop.value.code == 2
    assert "the map has 2 pages but the PDF has 1 /MediaBox entries" in capsys.readouterr().err


def test_a_missing_input_and_a_bad_worker_count_are_refused(tmp_path, capsys):
    """An unreadable input and a worker count below 1 end the command with a message and status 2, not a traceback or a
    hung pool."""
    argv = write_inputs(tmp_path, MAP_BYTES)
    (tmp_path / "f.pdf").unlink()
    with pytest.raises(SystemExit) as stop:
        d6.main(argv)
    assert stop.value.code == 2
    assert "cannot read an input" in capsys.readouterr().err
    with pytest.raises(SystemExit) as stop:
        d6.main([*write_inputs(tmp_path, MAP_BYTES)[:-1], "0"])
    assert stop.value.code == 2
    assert "--workers must be at least 1" in capsys.readouterr().err


def test_the_default_worker_count_is_the_cpu_count():
    """--workers defaults to the machine's CPU count and --seed to the seed ADR-0015's drags were drawn with, so a bare
    run reproduces them."""
    args = d6.build_parser().parse_args(["measure", "m", "p", "-o", "r"])
    assert args.workers == (os.cpu_count() or 1)
    assert args.seed == 20261006
