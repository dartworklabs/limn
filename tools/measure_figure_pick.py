"""Compare the current figure picker with its former depth-first rule on reproducible modelled drags.

Accept any limn-figure-map/1 map; never execute the producer's code or inspect its source files. The regenerated
sample pool is separate from ADR-0015's unavailable original harness. Padding is in page fractions, independent
of PDF dimensions or viewer zoom, so these measurements compare algorithms rather than predict user accuracy.

Run: uv run python tools/measure_figure_pick.py MAP --seed 2090015 --per-page 150
"""

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from collections.abc import Iterator
from typing import TypeAlias

from limn.builds.figure_map import FigureMap, Frac, MapElement, MapPage, MapRejected, parse_map, pick_element

Sample: TypeAlias = tuple[MapPage, MapElement, Frac, tuple[str, ...]]


def area(box: Frac) -> float:
    """Return the area of a modelled page box."""
    return box[2] * box[3]


def overlap(a: Frac, b: Frac) -> float:
    """Return the actual area shared by two page boxes, zero for disjoint or touching boxes."""
    w = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return w * h


def cover(box: Frac, drag: Frac) -> float:
    """Return actual drag coverage; a zero-area drag is its centre point."""
    if area(drag) <= 0:
        x, y = drag[0] + drag[2] / 2, drag[1] + drag[3] / 2
        return float(box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3])
    return min(1.0, overlap(box, drag) / area(drag))


def fill(box: Frac, drag: Frac) -> float:
    """Return the fraction of a parsed positive-area box covered by the drag."""
    return min(1.0, overlap(box, drag) / area(box))


def bounded(x: float, y: float, w: float, h: float) -> Frac:
    """Clip a modelled drag to the page, including tolerated map origins slightly beyond its far edges."""
    right, bottom = max(0.0, min(1.0, x + w)), max(0.0, min(1.0, y + h))
    x, y = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
    return (x, y, max(0.0, right - x), max(0.0, bottom - y))


def baseline_pick(pg: MapPage, drag: Frac, *, chain_only: bool = False) -> MapElement:
    """Choose by the frozen pre-fix rule; chain_only isolates the ancestor-pruning change without hit expansion.

    Baseline thresholds stay at 0.4/0.5 even if production thresholds later change. Parsed maps guarantee a root
    and acyclic parent chains, so every drag yields a page element.
    """
    others = pg.elements[1:]
    covering = [e for e in others if cover(e.frac, drag) >= 0.4]
    order = {e.id: i for i, e in enumerate(pg.elements)}
    if covering:
        if chain_only:
            parents = {a.id for e in covering for a in pg.ancestors(e)}
            return min((e for e in covering if e.id not in parents), key=lambda e: (area(e.frac), order[e.id]))
        return min(covering, key=lambda e: (-len(pg.ancestors(e)), area(e.frac), order[e.id]))
    filled = [e for e in others if fill(e.frac, drag) >= 0.5]
    if not filled:
        return pg.root()
    chains = [(e, *pg.ancestors(e)) for e in filled]
    shared = set.intersection(*({e.id for e in chain} for chain in chains))
    return next(e for e in chains[0] if e.id in shared)


def modelled_drag(box: Frac, kind: str, rng: random.Random) -> Frac:
    """Make a tight, proportional-padded, absolute-padded, partial, or point drag around an intended element."""
    x, y, w, h = box
    if kind == "tight":
        return bounded(x + w * 0.05, y + h * 0.05, w * 0.9, h * 0.9)
    if kind == "ratio":
        return bounded(x - w * 0.25, y - h * 0.25, w * 1.5, h * 1.5)
    if kind == "padding":
        px, py = rng.uniform(0.002, 0.008), rng.uniform(0.002, 0.008)
        return bounded(x - px, y - py, w + px * 2, h + py * 2)
    if kind == "partial":
        sx, sy = rng.uniform(0.1, 0.45), rng.uniform(0.1, 0.45)
        return bounded(x + w * sx, y + h * sy, w * 0.5, h * 0.5)
    return bounded(x + w / 2, y + h / 2, 0.0, 0.0)


def single_samples(m: FigureMap, seed: int, per_page: int) -> Iterator[Sample]:
    """Sample up to per_page non-root targets per page and five drags each, with independent geometry cohorts."""
    rng = random.Random(seed)
    for pg in m.pages:
        targets = rng.sample(list(pg.elements[1:]), min(per_page, len(pg.elements) - 1))
        for e in targets:
            for kind in ("tight", "ratio", "padding", "partial", "point"):
                cohorts = ["single", kind]
                if area(e.frac) >= 0.005:
                    cohorts.append("large-" + kind)
                if min(e.frac[2:]) < 0.004:
                    cohorts.append("thin-" + kind)
                if max(e.frac[2:]) < 0.012:
                    cohorts.append("tiny-" + kind)
                if e.part in ("Text", "ctext", "rt"):
                    cohorts.append("text-" + kind)
                yield pg, e, modelled_drag(e.frac, kind, rng), tuple(cohorts)


def sibling_samples(m: FigureMap, seed: int, per_parent: int) -> Iterator[Sample]:
    """Drag around nearby siblings, targeting their parent; descendants are reported as potential ladder recovery."""
    rng = random.Random(seed)
    for pg in m.pages:
        groups: dict[str, list[MapElement]] = defaultdict(list)
        for e in pg.elements[1:]:
            if e.parent is not None:
                groups[e.parent].append(e)
        for parent_id, siblings in groups.items():
            if len(siblings) < 2:
                continue
            target = pg.by_id(parent_id)
            assert target is not None
            for first in rng.sample(siblings, min(per_parent, len(siblings))):
                near = min(
                    (e for e in siblings if e.id != first.id),
                    key=lambda e: (
                        (e.frac[0] + e.frac[2] / 2 - first.frac[0] - first.frac[2] / 2) ** 2
                        + (e.frac[1] + e.frac[3] / 2 - first.frac[1] - first.frac[3] / 2) ** 2
                    ),
                )
                a, b = first.frac, near.frac
                x, y = min(a[0], b[0]), min(a[1], b[1])
                w = max(a[0] + a[2], b[0] + b[2]) - x
                h = max(a[1] + a[3], b[1] + b[3]) - y
                yield pg, target, bounded(x - 0.002, y - 0.002, w + 0.004, h + 0.004), ("siblings",)


def measure(samples: Iterator[Sample]) -> dict[str, dict[str, dict[str, int | float]]]:
    """Count exact, ancestor, descendant, and unrelated choices for each rule and cohort, without source identities."""
    counters: dict[str, dict[str, Counter[str]]] = {
        name: defaultdict(Counter) for name in ("legacy", "chain", "current")
    }
    for pg, target, drag, cohorts in samples:
        choices = {
            "legacy": baseline_pick(pg, drag),
            "chain": baseline_pick(pg, drag, chain_only=True),
            "current": pick_element(pg, drag).chosen,
        }
        target_ancestors = {e.id for e in pg.ancestors(target)}
        for name, chosen in choices.items():
            if chosen.id == target.id:
                outcome = "exact"
            elif chosen.id in target_ancestors:
                outcome = "ancestor"
            elif target in pg.ancestors(chosen):
                outcome = "descendant"
            else:
                outcome = "wrong"
            for cohort in cohorts:
                counters[name][cohort][outcome] += 1
    return {
        name: {
            cohort: {
                "samples": c.total(),
                **{key: c[key] for key in ("exact", "ancestor", "descendant", "wrong")},
                "exact_percent": round(100 * c["exact"] / c.total(), 2),
                "wrong_percent": round(100 * c["wrong"] / c.total(), 2),
            }
            for cohort, c in groups.items()
        }
        for name, groups in counters.items()
    }


def main() -> int:
    """Read a map supplied by the caller and print reproducible cohort statistics; reject unreadable or invalid maps."""
    from itertools import chain
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map", type=Path)
    parser.add_argument("--seed", type=int, default=2090015)
    parser.add_argument("--per-page", type=int, default=150)
    parser.add_argument("--per-parent", type=int, default=20)
    args = parser.parse_args()
    if args.per_page < 1 or args.per_parent < 1:
        parser.error("sample counts must be positive")
    try:
        raw = args.map.read_bytes()
    except OSError:
        parser.error("cannot read the supplied map")
    parsed = parse_map(raw)
    if isinstance(parsed, MapRejected):
        parser.error("map rejected: " + parsed.reason)
    report = {
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "seed": args.seed,
        "per_page": args.per_page,
        "per_parent": args.per_parent,
        "pages": len(parsed.pages),
        "non_root_elements": sum(len(pg.elements) - 1 for pg in parsed.pages),
        "metrics": measure(
            chain(single_samples(parsed, args.seed, args.per_page), sibling_samples(parsed, args.seed, args.per_parent))
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
