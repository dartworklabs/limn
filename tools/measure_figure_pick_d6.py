"""The harness behind ADR-0015's figure-pick thresholds: modelled drags over a figure tool's real map, per threshold pair.

This is the original D6 measurement as a maintained tool. tools/measure_figure_pick.py is a different, reconstructed
sample (its docstring says so); the drag generator here consumes the random stream as the original did, so the same
map and PDF give the same drags - 59,492 on the 22 drawable pages that ADR-0015 measured - and the same tables.

Model of a person's drag in Limn's viewer (page fractions; jitter and margins in screen px at a viewer scale
s ~ U(1.42, 2.13) px/pt, i.e. fit-width 740 px for a 522 pt page at 100-150 % zoom):
  tight      the element's box, each edge moved by N(0, 1.5 px)
  loose-rel  each side widened by U(10, 40) % of the element's size on that axis, + jitter
  loose-px   each side widened by U(3, 12) px (a hand leaving visible air), + jitter
  partial    a sub-box holding U(30, 90) % of the element's area (along the long axis of a long
             element, a centred-ish square-ish piece otherwise), + jitter; leaves only
  span2      the element and its nearest sibling, union + U(2, 6) px per side; the intent is their
             nearest common ancestor (the root when the figure is flat there)
Every drag is at least 3 px on each axis and clipped to the page. Targets: per figure every scope element (group,
helper call) up to 40 and leaves up to 150 in all, seeded; 4 drags per target and kind. A target's size class is
big (at least 2 % of the page), small (under 14 pt on a side and under 400 pt^2) or medium.

Each drag is given to limn.builds.figure_map.pick_element for every (COVER_MIN, FILL_MIN) on the grid cover
0.30-0.90 x fill 0.20-0.80 (step 0.05), by setting the module's constants (the function reads them at call time),
so a results file holds all 169 outcomes of every drag. Outcomes, for a target T and the chosen element C:
  correct (ok)    C is T, or has T's box (indistinguishable on the page)
  finer (fi)      C is a descendant of T (the ladder climbs back to T)
  coarser (co)    C is a proper ancestor of T other than the root
  wrong (wr)      C is unrelated to T
  none (no)       C is the root (the whole figure)
span2 reads the same five columns differently: ok is C = the pair's nearest common ancestor (the root included
when that is it), fi is one of the pair or something inside one, co is above that ancestor, wr is unrelated, no is
the root when it is not that ancestor.

The map and the PDF are arguments: the tool reads the map with parse_map and refuses a rejected one, and reads each
page's /MediaBox from the PDF bytes (the page sizes that turn page fractions into points). Nothing else of the PDF
is read. A results file does not say which commit made it - name it for the commit it measured.

Run:
  uv run python tools/measure_figure_pick_d6.py measure MAP PDF -o results.json [--workers N] [--seed S]
  uv run python tools/measure_figure_pick_d6.py table results.json [--thresholds 0.6/0.5 0.4/0.5]
  uv run python tools/measure_figure_pick_d6.py compare before.json after.json [--threshold 0.4/0.5]
To measure another commit's picker, run measure from a checkout of it with a copy of this file.
"""

import argparse
import hashlib
import json
import os
import random
import re
import sys
from array import array
from collections.abc import Callable, Sequence
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Any, NamedTuple, TypedDict, cast

from limn.builds import figure_map
from limn.builds.figure_map import FigureMap, Frac, MapElement, MapPage, MapRejected

COVERS = [round(0.30 + 0.05 * i, 2) for i in range(13)]
FILLS = [round(0.20 + 0.05 * i, 2) for i in range(13)]
KINDS = ["tight", "loose-rel", "loose-px", "partial", "span2"]
SINGLE_KINDS = KINDS[:4]  # drags aimed at one element; span2 aims at a pair and is reported on its own
OUT = ["correct", "finer", "coarser", "wrong", "none"]
SIZES = ["small", "medium", "big"]
N_PER = 4
MAX_TARGETS, MAX_SCOPES = 150, 40
SEED = 20261006
ROW_KEYS = ("fig", "target", "kind", "size", "codes")  # what the reports read of a results row
CHUNK = 200  # drags per task of the worker pool; the results do not depend on it
DEFAULT_PAIRS = [(0.6, 0.5), (0.4, 0.5)]
DEFAULT_PAIR = (0.4, 0.5)


class InputError(Exception):
    """An input the tool refuses: a rejected or unreadable map, a PDF that does not fit it, results that do not pair."""


class Drag(NamedTuple):
    """One modelled drag: the index of its page in the map, the target's id, the kind, the target's size class, the drag
    in page fractions, and for span2 the id of the nearest sibling whose union with the target was dragged (else None)."""

    page: int
    target: str
    kind: str
    size: str
    frac: Frac
    partner: str | None


class Row(TypedDict):
    """The outcome codes (index into OUT; see the module docstring for span2) of one drag at every grid cell, cover
    major: codes[i * len(fills) + j] is the outcome at covers[i], fills[j]."""

    fig: str
    target: str
    kind: str
    size: str
    span: bool
    codes: list[int]


class Results(TypedDict):
    """A results file: the threshold grid, the outcome names, one row per drag in generation order, and a meta record
    (seed and input hashes) that files from the original harness do not have."""

    covers: list[float]
    fills: list[float]
    outcomes: list[str]
    rows: list[Row]
    meta: dict[str, Any]


# ---------------------------------------------------------------- Inputs


def parse_figure_map(raw: bytes) -> FigureMap:
    """Parse a limn-figure-map/1 map; a map that parse_map rejects is refused with its reason."""
    parsed = figure_map.parse_map(raw)
    if isinstance(parsed, MapRejected):
        raise InputError(f"map rejected: {parsed.reason} ({parsed.detail})")
    return parsed


def page_sizes(pdf: bytes) -> list[tuple[float, float]]:
    """The (width, height) in points of every /MediaBox [a b c d] the PDF bytes hold, in file order."""
    boxes = re.findall(rb"/MediaBox \[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\]", pdf)
    return [(float(c) - float(a), float(d) - float(b)) for a, b, c, d in boxes]


def same_box(a: Frac, b: Frac, eps: float = 1e-4) -> bool:
    """Whether two page boxes agree in every component to within eps."""
    return all(abs(x - y) <= eps for x, y in zip(a, b, strict=True))


def size_class(fr: Frac, pw: float, ph: float) -> str:
    """The target's size class on a pw x ph pt page: big, small or medium."""
    w, h = fr[2] * pw, fr[3] * ph
    if fr[2] * fr[3] >= 0.02:
        return "big"
    if min(w, h) < 14 and w * h < 400:
        return "small"
    return "medium"


# ---------------------------------------------------------------- The drag generator


def _jitter(rng: random.Random, s: float) -> float:
    """One edge's hand jitter in points: N(0, 1.5 px) at s px per point."""
    return rng.gauss(0.0, 1.5) / s


def _sibling_gap(sib: MapElement, box: tuple[float, float, float, float], pw: float, ph: float) -> tuple[float, float]:
    """How far sib is from the target box (x, y, w, h in points): the squared gap between the boxes, then the
    centre distance (Manhattan) as the tie-break. The nearest sibling is the smallest."""
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    sx, sy, sw, sh = sib.frac[0] * pw, sib.frac[1] * ph, sib.frac[2] * pw, sib.frac[3] * ph
    gx = max(0.0, max(sx, x) - min(sx + sw, x + w))
    gy = max(0.0, max(sy, y) - min(sy + sh, y + h))
    return (gx * gx + gy * gy, abs(sx + sw / 2 - cx) + abs(sy + sh / 2 - cy))


def make_drags(m: FigureMap, sizes: Sequence[tuple[float, float]], seed: int = SEED) -> list[Drag]:
    """Every sampled drag of the model, in generation order. The order of the rng calls is the original harness's: a
    page's stream is random.Random(f"{seed}:{figure}"), consumed by the two target samples, then per target and kind
    by the viewer scale and the geometry draws and the four edge jitters of each drag. Changing it changes the drags."""
    if len(sizes) != len(m.pages):
        raise InputError(f"the map has {len(m.pages)} pages but the PDF has {len(sizes)} /MediaBox entries")
    drags: list[Drag] = []
    for pi, (pg, (pw, ph)) in enumerate(zip(m.pages, sizes, strict=True)):
        rng = random.Random(f"{seed}:{pg.figure}")
        root = pg.root()
        els = [e for e in pg.elements if e.id != root.id]
        if not els:
            continue
        children: dict[str | None, list[MapElement]] = {}
        for e in els:
            children.setdefault(e.parent, []).append(e)
        scopes = [e for e in els if e.id in children]
        leaves = [e for e in els if e.id not in children]
        scopes = rng.sample(scopes, min(len(scopes), MAX_SCOPES))
        leaves = rng.sample(leaves, min(len(leaves), MAX_TARGETS - len(scopes)))
        for t in scopes + leaves:
            is_leaf = t.id not in children
            x, y, w, h = t.frac[0] * pw, t.frac[1] * ph, t.frac[2] * pw, t.frac[3] * ph
            sc = size_class(t.frac, pw, ph)
            for kind in KINDS:
                if kind == "partial" and not is_leaf:
                    continue
                partner = None
                if kind == "span2":
                    sibs = [s for s in children.get(t.parent, []) if s.id != t.id and not same_box(s.frac, t.frac)]
                    if not sibs:
                        continue
                    partner = min(sibs, key=partial(_sibling_gap, box=(x, y, w, h), pw=pw, ph=ph))
                for _ in range(N_PER):
                    s = rng.uniform(1.42, 2.13)  # px per pt
                    if kind == "tight":
                        x0, y0, x1, y1 = x, y, x + w, y + h
                    elif kind == "loose-rel":
                        x0, x1 = x - rng.uniform(0.1, 0.4) * w, x + w + rng.uniform(0.1, 0.4) * w
                        y0, y1 = y - rng.uniform(0.1, 0.4) * h, y + h + rng.uniform(0.1, 0.4) * h
                    elif kind == "loose-px":
                        x0, x1 = x - rng.uniform(3, 12) / s, x + w + rng.uniform(3, 12) / s
                        y0, y1 = y - rng.uniform(3, 12) / s, y + h + rng.uniform(3, 12) / s
                    elif kind == "partial":
                        p = rng.uniform(0.3, 0.9)
                        if w >= 2.5 * h:  # along the long axis: part of a label or a bar
                            a, b = p, 1.0
                        elif h >= 2.5 * w:
                            a, b = 1.0, p
                        else:
                            r = rng.uniform(0.3, 0.7)
                            a, b = p**r, p ** (1 - r)
                        x0 = x + rng.uniform(0, 1 - a) * w
                        y0 = y + rng.uniform(0, 1 - b) * h
                        x1, y1 = x0 + a * w, y0 + b * h
                    else:  # span2
                        assert partner is not None
                        q = partner.frac
                        qx, qy, qw, qh = q[0] * pw, q[1] * ph, q[2] * pw, q[3] * ph
                        x0, y0 = min(x, qx), min(y, qy)
                        x1, y1 = max(x + w, qx + qw), max(y + h, qy + qh)
                        x0, y0 = x0 - rng.uniform(2, 6) / s, y0 - rng.uniform(2, 6) / s
                        x1, y1 = x1 + rng.uniform(2, 6) / s, y1 + rng.uniform(2, 6) / s
                    x0, y0, x1, y1 = (
                        x0 + _jitter(rng, s),
                        y0 + _jitter(rng, s),
                        x1 + _jitter(rng, s),
                        y1 + _jitter(rng, s),
                    )
                    mn = 3 / s
                    if x1 - x0 < mn:
                        c = (x0 + x1) / 2
                        x0, x1 = c - mn / 2, c + mn / 2
                    if y1 - y0 < mn:
                        c = (y0 + y1) / 2
                        y0, y1 = c - mn / 2, c + mn / 2
                    x0, y0 = max(0.0, x0), max(0.0, y0)
                    x1, y1 = min(pw, x1), min(ph, y1)
                    fr = (x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph)
                    drags.append(Drag(pi, t.id, kind, sc, fr, partner.id if partner else None))
    return drags


# ---------------------------------------------------------------- Judging a pick


def classify(pg: MapPage, target_id: str, chosen: MapElement, partner_id: str | None) -> int:
    """The outcome code (index into OUT) of the picker's choice for a drag aimed at target_id, or for span2 (a partner
    id) at the pair's nearest common ancestor."""
    root = pg.root()
    t = pg.by_id(target_id)
    assert t is not None
    if partner_id is not None:  # span2: 0 the pair's nearest common ancestor, 1 one of the pair (or inside
        p = pg.by_id(partner_id)  # it), 2 above that ancestor, 3 unrelated, 4 the root when it is not that ancestor
        assert p is not None
        nca = figure_map._common_ancestor(pg, [t, p])
        if chosen.id == nca.id:
            return 0
        if chosen.id == root.id:
            return 4
        if chosen.id in (t.id, p.id) or any(a.id in (t.id, p.id) for a in pg.ancestors(chosen)):
            return 1
        if any(a.id == chosen.id for a in pg.ancestors(nca)):
            return 2
        return 3
    if chosen.id == t.id or same_box(chosen.frac, t.frac):
        return 0
    if chosen.id == root.id:
        return 4
    if any(a.id == t.id for a in pg.ancestors(chosen)):
        return 1
    if any(a.id == chosen.id for a in pg.ancestors(t)):
        return 2
    return 3


# ---------------------------------------------------------------- Measuring


_MAP: FigureMap | None = None


def _load(raw: bytes) -> None:
    """Worker initializer: parse the map once per process."""
    global _MAP
    _MAP = parse_figure_map(raw)


def _work(chunk: list[Drag]) -> list[bytes]:
    """The outcome codes of every drag in the chunk over the whole grid, one bytes object of len(COVERS) * len(FILLS)
    codes per drag. The picker's thresholds are module constants; they are set for each cell and put back after."""
    assert _MAP is not None
    saved = figure_map.COVER_MIN, figure_map.FILL_MIN
    out: list[bytes] = []
    try:
        for pi, tid, _kind, _sc, fr, partner in chunk:
            pg = _MAP.pages[pi]
            codes = array("b")
            for c in COVERS:
                figure_map.COVER_MIN = c
                for f in FILLS:
                    figure_map.FILL_MIN = f
                    codes.append(classify(pg, tid, figure_map.pick_element(pg, fr).chosen, partner))
            out.append(codes.tobytes())
    finally:
        figure_map.COVER_MIN, figure_map.FILL_MIN = saved
    return out


def measure(map_raw: bytes, pdf_raw: bytes, *, workers: int = 1, seed: int = SEED) -> Results:
    """Generate the drags for a map and its PDF and judge each at every grid cell; workers > 1 uses a process pool."""
    m = parse_figure_map(map_raw)
    drags = make_drags(m, page_sizes(pdf_raw), seed)
    print(f"{len(drags)} drags on {len({d.page for d in drags})} figures", file=sys.stderr)
    chunks = [drags[i : i + CHUNK] for i in range(0, len(drags), CHUNK)]
    if workers > 1:
        with Pool(workers, initializer=_load, initargs=(map_raw,)) as pool:
            parts = pool.map(_work, chunks)
    else:
        _load(map_raw)
        parts = [_work(c) for c in chunks]
    rows: list[Row] = [
        {
            "fig": m.pages[d.page].figure,
            "target": d.target,
            "kind": d.kind,
            "size": d.size,
            "span": d.partner is not None,
            "codes": list(codes),
        }
        for d, codes in zip(drags, (b for part in parts for b in part), strict=True)
    ]
    meta = {
        "seed": seed,
        "map_sha256": hashlib.sha256(map_raw).hexdigest(),
        "pdf_sha256": hashlib.sha256(pdf_raw).hexdigest(),
    }
    return {"covers": COVERS, "fills": FILLS, "outcomes": OUT, "rows": rows, "meta": meta}


def load_results(path: Path) -> Results:
    """Read a results file, from this tool or from the original harness (which wrote no meta record)."""
    try:
        data = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise InputError(f"cannot read results {path.name}: {exc}") from exc
    if not (
        isinstance(data, dict)
        and all(isinstance(data.get(key), list) for key in ("covers", "fills", "outcomes", "rows"))
        and all(isinstance(r, dict) and all(k in r for k in ROW_KEYS) for r in data["rows"])
    ):
        raise InputError(f"{path.name} is not a results file of this tool")
    cells = len(data["covers"]) * len(data["fills"])
    if any(len(r["codes"]) != cells for r in data["rows"]):
        raise InputError(f"{path.name} has rows whose codes do not match its {cells}-cell grid")
    data.setdefault("meta", {})
    return cast(Results, data)


# ---------------------------------------------------------------- Reports


def grid_index(res: Results, pair: tuple[float, float]) -> int:
    """The column of a (cover, fill) pair in every row's codes; a pair that is not a grid cell is refused."""
    cover, fill = pair
    ci = [i for i, c in enumerate(res["covers"]) if abs(c - cover) < 1e-9]
    fi = [j for j, f in enumerate(res["fills"]) if abs(f - fill) < 1e-9]
    if not ci or not fi:
        raise InputError(
            f"{cover}/{fill} is not a measured threshold pair: cover is one of {res['covers']}, fill one of {res['fills']}"
        )
    return ci[0] * len(res["fills"]) + fi[0]


def shares(rows: Sequence[Row], k: int) -> list[float]:
    """The percentage of rows with each outcome at grid column k, in OUT order."""
    return [100 * sum(r["codes"][k] == o for r in rows) / len(rows) for o in range(len(OUT))]


def mean_shares(rows: Sequence[Row], k: int) -> list[float]:
    """The unweighted mean over the single-target kinds present in rows of each kind's outcome percentages."""
    per_kind = [shares(sel, k) for kind in SINGLE_KINDS if (sel := [r for r in rows if r["kind"] == kind])]
    return [sum(col) / len(per_kind) for col in zip(*per_kind, strict=True)]


def _cells(values: Sequence[float]) -> str:
    """Percentages to one decimal, space separated."""
    return " ".join(f"{v:.1f}" for v in values)


def format_table(res: Results, pairs: Sequence[tuple[float, float]]) -> str:
    """The per-kind and per-size table at each threshold pair: the share of drags with each outcome. The size rows
    leave span2 out. mean4 is the unweighted mean of the four single-target kinds, with their drag count as n."""
    cols = [grid_index(res, p) for p in pairs]
    rows = res["rows"]
    head = " | ".join(f"{c}/{f} ok fi co wr no" for c, f in pairs)
    lines = [
        f"{len(rows):,} drags / {len({r['fig'] for r in rows})} figures / "
        f"{len({(r['fig'], r['target']) for r in rows}):,} targets",
        f"group  n  | {head}",
    ]

    def line(name: str, sel: Sequence[Row], measure_of: Callable[[Sequence[Row], int], list[float]] = shares) -> None:
        if sel:
            lines.append(f"{name} {len(sel)} | " + " | ".join(_cells(measure_of(sel, k)) for k in cols))

    for kind in SINGLE_KINDS:
        line(kind, [r for r in rows if r["kind"] == kind])
    line("mean4", [r for r in rows if r["kind"] != "span2"], mean_shares)
    line("span2", [r for r in rows if r["kind"] == "span2"])
    for size in SIZES:
        line(size, [r for r in rows if r["size"] == size and r["kind"] != "span2"])
    return "\n".join(lines)


def paired(before: Results, after: Results) -> list[tuple[Row, Row]]:
    """The two files' rows paired by drag. Files from different grids, maps, seeds or drag lists are refused: a pairing
    is only a comparison of pickers when both measured the very same drags."""
    if before["covers"] != after["covers"] or before["fills"] != after["fills"]:
        raise InputError("the two results files measured different threshold grids")
    for key in ("seed", "map_sha256"):
        a, b = before["meta"].get(key), after["meta"].get(key)
        if a is not None and b is not None and a != b:
            raise InputError(f"the two results files differ in {key}: {a} and {b}")
    x_rows, y_rows = before["rows"], after["rows"]
    if len(x_rows) != len(y_rows):
        raise InputError(f"the two results files hold {len(x_rows)} and {len(y_rows)} drags")
    pairs = list(zip(x_rows, y_rows, strict=True))
    for i, (x, y) in enumerate(pairs):
        if (x["fig"], x["target"], x["kind"], x["size"]) != (y["fig"], y["target"], y["kind"], y["size"]):
            raise InputError(f"drag {i} is not the same drag in the two results files")
    return pairs


def format_compare(before: Results, after: Results, pair: tuple[float, float]) -> str:
    """The single-target drags of two results files compared drag by drag at one threshold pair: each outcome's
    four-kind mean, the drags that gained or lost a correct pick, the wrong picks, and per size and kind the correct
    and wrong counts before and after."""
    k = grid_index(before, pair)
    single = [(x, y) for x, y in paired(before, after) if x["kind"] != "span2"]
    if not single:
        raise InputError("the results files hold no single-target drags to compare")
    xs, ys = [x for x, _ in single], [y for _, y in single]
    lines = []
    for o, name in enumerate(OUT):
        lines.append(f"{name:8s} 4-kind avg  before {mean_shares(xs, k)[o]:5.1f}  after {mean_shares(ys, k)[o]:5.1f}")
    n = len(single)
    won = sum(x["codes"][k] != 0 and y["codes"][k] == 0 for x, y in single)
    lost = sum(x["codes"][k] == 0 and y["codes"][k] != 0 for x, y in single)
    lines.append(f"single-target drags {n}: gained correct {won}, lost correct {lost}, net {won - lost}")
    wr_a, wr_b = sum(x["codes"][k] == 3 for x in xs), sum(y["codes"][k] == 3 for y in ys)
    lines.append(f"wrong picks {wr_a} -> {wr_b} of {n}")
    for size in SIZES:
        for kind in SINGLE_KINDS:
            s = [(x, y) for x, y in single if x["size"] == size and x["kind"] == kind]
            if not s:
                continue
            oa, ob = sum(x["codes"][k] == 0 for x, _ in s), sum(y["codes"][k] == 0 for _, y in s)
            wa, wb = sum(x["codes"][k] == 3 for x, _ in s), sum(y["codes"][k] == 3 for _, y in s)
            lines.append(
                f"{size:6s} {kind:9s} n={len(s):5d} correct {oa:5d}->{ob:5d} ({100 * oa / len(s):4.1f}->{100 * ob / len(s):4.1f}%)"
                f"  wrong {wa:5d}->{wb:5d}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------- Command line


def threshold_pair(text: str) -> tuple[float, float]:
    """Parse COVER/FILL, for example 0.4/0.5."""
    try:
        cover, fill = text.split("/")
        return float(cover), float(fill)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not COVER/FILL, for example 0.4/0.5") from None


def build_parser() -> argparse.ArgumentParser:
    """The three sub-commands: measure, table, compare."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    measure_cmd = sub.add_parser("measure", help="generate the drags, judge them over the grid, write a results file")
    measure_cmd.add_argument("map", type=Path, help="a limn-figure-map/1 map")
    measure_cmd.add_argument("pdf", type=Path, help="the PDF the map describes; only its page sizes are read")
    measure_cmd.add_argument("-o", "--output", type=Path, required=True, help="the results file to write")
    measure_cmd.add_argument(
        "--workers", type=int, default=os.cpu_count() or 1, help="worker processes (default: CPUs)"
    )
    measure_cmd.add_argument("--seed", type=int, default=SEED, help="seed of the drag generator (default: %(default)s)")
    table_cmd = sub.add_parser("table", help="print the per-kind and per-size table at two threshold pairs")
    table_cmd.add_argument("results", type=Path)
    table_cmd.add_argument(
        "--thresholds",
        nargs=2,
        type=threshold_pair,
        default=DEFAULT_PAIRS,
        metavar="COVER/FILL",
        help="the two pairs to print, on the measured grid (default: 0.6/0.5 0.4/0.5)",
    )
    compare_cmd = sub.add_parser("compare", help="pair two results files by drag: gained and lost, per size and kind")
    compare_cmd.add_argument("before", type=Path)
    compare_cmd.add_argument("after", type=Path)
    compare_cmd.add_argument(
        "--threshold", type=threshold_pair, default=DEFAULT_PAIR, metavar="COVER/FILL", help="default: 0.4/0.5"
    )
    return parser


def run(args: argparse.Namespace) -> str | None:
    """Carry out the parsed command; the report to print, or None after writing a results file."""
    if args.command == "measure":
        if args.workers < 1:
            raise InputError("--workers must be at least 1")
        try:
            map_raw, pdf_raw = args.map.read_bytes(), args.pdf.read_bytes()
        except OSError as exc:
            raise InputError(f"cannot read an input: {exc}") from exc
        res = measure(map_raw, pdf_raw, workers=args.workers, seed=args.seed)
        try:
            args.output.write_text(json.dumps(res))
        except OSError as exc:
            raise InputError(f"cannot write the results: {exc}") from exc
        print(f"wrote {args.output.name}", file=sys.stderr)
        return None
    if args.command == "table":
        return format_table(load_results(args.results), args.thresholds)
    return format_compare(load_results(args.before), load_results(args.after), args.threshold)


def main(argv: Sequence[str] | None = None) -> int:
    """Run a sub-command; a refused input ends with a message and exit status 2, as a bad argument does."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = run(args)
    except InputError as exc:
        parser.error(str(exc))
    if report is not None:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
