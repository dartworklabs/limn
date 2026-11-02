"""Split a test selection into n parts that run on separate machines (`--shard i/n`), a whole class at a time.

CI runs the browser suite as several jobs per Python version; each runs `pytest -m browser --shard i/n` and they
add up to the suite (docs/handbook/verification.md §검증 시간과 병렬 실행). The unit of the split is the scope that
pytest-xdist's `--dist loadscope` keeps on one worker (scope_of), so a class's browser and server stay together
in one shard as they stay on one worker inside it.

The assignment depends only on the selected node ids and the measured seconds per scope in SECONDS, never on the
machine, the run or hash seeds, so every xdist worker of a shard (each collects on its own) and every job of the
split computes the same parts. Each scope goes to exactly one part: the scopes are taken heaviest first and each
goes to the part with the least time so far (longest processing time first). A scope SECONDS does not know - a
new class, a renamed one - weighs as many tests as it has at the measured mean seconds per test, so it still lands
in one part and the parts stay near balanced until the file is refreshed.

Within a part the heaviest scopes come first, and the option turns off xdist's own reordering by test count, so the
part's slowest class starts at once instead of last on one worker while the others idle.

Refresh SECONDS from a whole run of the browser suite after classes are added, removed or made faster or slower:

    uv run pytest -q -m browser -n 4 --shard-record tests/data/shard_seconds.json

A class whose tests all skipped in that run (an engine the machine cannot launch) is left out of the file and weighs at
the mean. Stale or missing entries cost only balance, never a test.
"""

import argparse
import heapq
import json
import math
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TypeVar

import pytest

SECONDS = Path(__file__).resolve().parents[1] / "data" / "shard_seconds.json"
# Seconds per test for a scope when SECONDS knows none of the selected scopes (an empty or foreign file).
DEFAULT_PER_TEST = 1.0

T = TypeVar("T")


def scope_of(nodeid: str) -> str:
    """The unit `--dist loadscope` keeps on one worker: the node id up to its last '::' - a class for a method, a
    module for a function. This is pytest-xdist's own rule (LoadScopeScheduling._split_scope), parameters included."""
    return nodeid.rsplit("::", 1)[0]


def parse_shard(text: str) -> tuple[int, int]:
    """`i/n` as (i, n) with 1 <= i <= n."""
    index, sep, total = text.partition("/")
    if not (sep and index.isdigit() and total.isdigit() and 1 <= int(index) <= int(total)):
        raise argparse.ArgumentTypeError("expected i/n with 1 <= i <= n, got %r" % text)
    return int(index), int(total)


def load_seconds(path: Path) -> dict[str, float]:
    """The measured seconds per scope; a file that is not a JSON object of non-negative numbers is an error."""
    data = json.loads(path.read_text(encoding="utf-8"))
    ok = isinstance(data, dict) and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 for v in data.values()
    )
    if not ok:
        raise pytest.UsageError("%s: expected a JSON object of scope -> seconds" % path)
    return {str(k): float(v) for k, v in data.items()}


def weights(counts: dict[str, int], seconds: dict[str, float]) -> dict[str, float]:
    """Each scope's weight: its measured seconds, or for a scope without a measure its number of tests times the mean
    seconds per test of the measured scopes in counts (DEFAULT_PER_TEST if none is measured)."""
    known = sorted(scope for scope in counts if scope in seconds)
    tests = sum(counts[scope] for scope in known)
    per_test = math.fsum(seconds[scope] for scope in known) / tests if tests else DEFAULT_PER_TEST
    return {scope: seconds[scope] if scope in seconds else per_test * counts[scope] for scope in counts}


def partition(counts: dict[str, int], seconds: dict[str, float], n: int) -> list[list[str]]:
    """Split the scopes of counts (scope -> number of selected tests) into n parts of near-equal weight.

    Heaviest scope first (ties by name), each to the part with the least weight so far (ties: fewer scopes, then the
    lower index), so a scope of weight 0 still spreads out and no part is empty while there are at least n scopes.
    Each part lists its scopes heaviest first. The result depends on the mapping's contents, not its order."""
    weight = weights(counts, seconds)
    parts: list[list[str]] = [[] for _ in range(n)]
    heap = [(0.0, 0, k) for k in range(n)]
    for scope in sorted(counts, key=lambda s: (-weight[s], s)):
        load, size, k = heapq.heappop(heap)
        parts[k].append(scope)
        heapq.heappush(heap, (load + weight[scope], size + 1, k))
    return parts


def split(things: Sequence[T], nodeid: Callable[[T], str], seconds: dict[str, float], total: int) -> list[list[T]]:
    """The things (tests, or their node ids) in total parts: whole scopes, each part's heaviest scope first, each
    scope's things in their given order."""
    by_scope: dict[str, list[T]] = {}
    for thing in things:
        by_scope.setdefault(scope_of(nodeid(thing)), []).append(thing)
    parts = partition({scope: len(group) for scope, group in by_scope.items()}, seconds, total)
    return [[thing for scope in part for thing in by_scope[scope]] for part in parts]


def shards(nodeids: Sequence[str], seconds: dict[str, float], total: int) -> list[list[str]]:
    """The node ids each `--shard i/total` keeps of nodeids (part i at index i - 1), in the order it runs them."""
    return split(nodeids, str, seconds, total)


def scope_seconds(reports: Iterable[pytest.TestReport]) -> dict[str, float]:
    """Seconds per scope from a run's reports: the setup, call and teardown of each test (a class's setUpClass is in
    its first test's setup). A subtest's report is part of its test's call and is not counted again. A scope none of
    whose tests got to its call - all skipped, as a browser engine the measuring machine cannot launch skips its
    classes - is left out: its few seconds say nothing of its cost, and left out it weighs at the measured mean."""
    total: dict[str, float] = {}
    ran: set[str] = set()
    for report in reports:
        if not isinstance(report, pytest.SubtestReport):
            scope = scope_of(report.nodeid)
            total[scope] = total.get(scope, 0.0) + report.duration
            if report.when == "call":
                ran.add(scope)
    return {scope: round(value, 1) for scope, value in sorted(total.items()) if scope in ran}


class Recorder:
    """--shard-record: keep every report this process sees and write scope_seconds at the end. Registered on the
    controller only, which receives the reports of all xdist workers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.reports: list[pytest.TestReport] = []

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Keep the report."""
        self.reports.append(report)

    def pytest_sessionfinish(self) -> None:
        """Write the seconds, one scope per line, sorted."""
        self.path.write_text(json.dumps(scope_seconds(self.reports), indent=1) + "\n", encoding="utf-8")


def pytest_addoption(parser: pytest.Parser) -> None:
    """--shard, --shard-seconds and --shard-record."""
    group = parser.getgroup("shard", "split the selected tests across machines (tests/support/helpers_shards.py)")
    group.addoption(
        "--shard",
        type=parse_shard,
        default=None,
        metavar="i/n",
        help="run only part i of n of the selected tests: whole loadscope scopes, balanced by measured seconds, "
        "heaviest first (turns off xdist's --loadscope-reorder)",
    )
    group.addoption(
        "--shard-seconds",
        type=Path,
        default=SECONDS,
        metavar="PATH",
        help="JSON object of scope -> measured seconds that --shard balances by (default: tests/data/shard_seconds.json)",
    )
    group.addoption(
        "--shard-record",
        type=Path,
        default=None,
        metavar="PATH",
        help="write the seconds each scope of this run took to PATH, in the form --shard-seconds reads",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Keep the part's own order under xdist; start a recording on the controller."""
    if config.getoption("shard") is not None and hasattr(config.option, "loadscopereorder"):
        config.option.loadscopereorder = False
    path = config.getoption("shard_record")
    if path is not None and not hasattr(config, "workerinput"):
        config.pluginmanager.register(Recorder(path), "shard-record")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """After -m, -k and --deselect have made the selection, keep this shard's part of it."""
    spec = config.getoption("shard")
    if spec is None:
        return
    index, total = spec
    seconds = load_seconds(config.getoption("shard_seconds"))
    keep = split(items, lambda item: item.nodeid, seconds, total)[index - 1]
    kept = {id(item) for item in keep}
    deselected = [item for item in items if id(item) not in kept]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = keep
