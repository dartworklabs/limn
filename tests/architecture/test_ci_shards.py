"""The browser suite split across CI jobs (`--shard i/n`, tests/support/helpers_shards.py) runs every test once.

CI runs the browser suite once, on Python 3.12, as parts on separate runners (.github/workflows/browser.yml) and
reports them under the one check name branch protection requires (.github/workflows/ci.yml). A part that dropped a test,
or a test that ran in no part, would pass the gate without running; these tests hold that, for any number of parts:

1. Every selected test is in exactly one part, a scope (a class; a module's functions) whole in one part - for made-up
   collections with parameters and scopes the timing file does not know, and for the real browser suite.
2. The option runs that part: it splits what -m selected, runs subtests with their test, agrees across xdist workers,
   and starts the heaviest class first.
3. The workflows run every part, once, on Python 3.12 and fail the required name when a part did not pass.

Run: uv run pytest -q tests/architecture/test_ci_shards.py
"""

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

import helpers_shards as hs

pytest_plugins = ("pytester",)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
BROWSER_PYTHON = "3.12"


def collected(*args: str) -> list[str]:
    """The node ids `pytest --collect-only` lists for args in this repository, serially."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-n", "0", "-p", "no:cacheprovider", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if "::" in line]


def ci_parts() -> int:
    """How many parts browser.yml splits a version's suite in: its shard matrix, which must read 1..n."""
    text = (WORKFLOWS / "browser.yml").read_text(encoding="utf-8")
    (values,) = re.findall(r"^\s+shard: \[([\d, ]+)\]$", text, re.MULTILINE)
    numbers = [int(v) for v in values.split(",")]
    assert numbers == list(range(1, len(numbers) + 1)), numbers
    return len(numbers)


def jobs(text: str) -> dict[str, str]:
    """A workflow's jobs as {id: the job's lines}: each job starts at a two-space `id:` line under `jobs:`."""
    body = text.split("\njobs:\n", 1)[1]
    found = re.split(r"^  ([\w-]+):\n", body, flags=re.MULTILINE)
    return dict(zip(found[1::2], found[2::2], strict=True))


def check_parts(nodeids: list[str], parts: list[list[str]]) -> None:
    """Every node id in exactly one part, each scope whole in one part, and no empty part while there are scopes."""
    assert Counter(nodeid for part in parts for nodeid in part) == Counter(nodeids)
    homes: dict[str, set[int]] = {}
    for k, part in enumerate(parts):
        for nodeid in part:
            homes.setdefault(hs.scope_of(nodeid), set()).add(k)
    assert [scope for scope, ks in homes.items() if len(ks) != 1] == []
    assert sum(1 for part in parts if part) == min(len(parts), len(homes))


@st.composite
def selections(draw):
    """Made-up node ids - module functions and class methods, some parametrized, ids with '::' inside the brackets
    as pytest-xdist splits them - and a timing file that knows some of their scopes, and one that is gone."""
    ids = draw(
        st.lists(
            st.builds(
                lambda m, c, t, p: "m%d.py%s::t%d%s" % (m, "::" + c if c else "", t, p),
                st.integers(0, 3),
                st.sampled_from(["", "One", "Two"]),
                st.integers(0, 4),
                st.sampled_from(["", "[0]", "[a::b]", "[x-y]"]),
            ),
            min_size=1,
            max_size=40,
        )
    )
    scopes = sorted({hs.scope_of(nodeid) for nodeid in ids}) + ["gone.py::Removed"]
    seconds = draw(st.dictionaries(st.sampled_from(scopes), st.floats(0, 1000)))
    return ids, seconds


@given(selections(), st.integers(1, 12), st.randoms())
def test_every_test_is_in_exactly_one_part_whatever_the_order(selection, n, rnd):
    """For any n, each node id lands in one part with its whole scope, known or not; the parts do not depend on the
    order the tests were collected in, so each xdist worker and each CI job computes the same ones."""
    ids, seconds = selection
    parts = hs.shards(ids, seconds, n)
    check_parts(ids, parts)
    shuffled = list(ids)
    rnd.shuffle(shuffled)
    assert [Counter(part) for part in hs.shards(shuffled, seconds, n)] == [Counter(part) for part in parts]


def test_a_scope_without_a_measure_weighs_its_tests_at_the_measured_mean():
    """A new class weighs its tests at the measured seconds per test: four tests where two took 10s weigh 20s, and the
    unmeasured suite falls back to a second per test; a scope the suite no longer has changes nothing. The heaviest goes
    first, each to the lightest part."""
    counts = {"a.py::Old": 2, "b.py::New": 4, "c.py::Small": 1}
    seconds = {"a.py::Old": 10.0, "c.py::Small": 1.0, "gone.py::Removed": 500.0}
    assert hs.weights(counts, seconds) == {"a.py::Old": 10.0, "b.py::New": 11 / 3 * 4, "c.py::Small": 1.0}
    assert hs.weights({"b.py::New": 4}, {}) == {"b.py::New": 4 * hs.DEFAULT_PER_TEST}
    assert hs.partition(counts, seconds, 2) == [["b.py::New"], ["a.py::Old", "c.py::Small"]]
    zero = {"a.py::A": 1, "b.py::B": 1, "c.py::C": 1}  # measured at 0s, so the new one weighs 0s too: they still spread
    assert hs.partition(zero, {"a.py::A": 0, "b.py::B": 0}, 3) == [["a.py::A"], ["b.py::B"], ["c.py::C"]]


@pytest.mark.parametrize("text", ["0/3", "4/3", "1/0", "a/b", "3", "-1/2", " 1/2", "1/2/3", ""])
def test_a_part_is_named_i_of_n(text):
    """Only i/n with 1 <= i <= n names a part."""
    with pytest.raises(Exception, match="expected i/n"):
        hs.parse_shard(text)


def test_the_timing_file_is_scope_seconds():
    """The committed file holds only non-negative seconds per scope; it may lag the suite, which costs balance only."""
    seconds = hs.load_seconds(hs.SECONDS)
    assert seconds and all("::" in scope or scope.endswith(".py") for scope in seconds), sorted(seconds)[:5]


def test_the_browser_suite_splits_into_whole_parts_for_any_n_and_the_ci_parts_are_what_the_option_runs():
    """The real browser suite, with the committed timing file: for every n up to one more than it has scopes, every
    test is in exactly one part. For the n CI uses, no part is empty and `--shard i/n` collects exactly part i, heaviest
    scope first."""
    ids = collected("-m", "browser")
    seconds = hs.load_seconds(hs.SECONDS)
    n_scopes = len({hs.scope_of(nodeid) for nodeid in ids})
    assert n_scopes > 100, n_scopes
    for n in range(1, n_scopes + 2):
        check_parts(ids, hs.shards(ids, seconds, n))
    n = ci_parts()
    expected = hs.shards(ids, seconds, n)
    assert all(expected), [len(part) for part in expected]
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-n", "0", "-p", "no:cacheprovider", "-m"]
    runs = [
        subprocess.Popen(
            [*command, "browser", "--shard", "%d/%d" % (i, n)], cwd=ROOT, stdout=subprocess.PIPE, text=True
        )
        for i in range(1, n + 1)
    ]
    got = [[line for line in run.communicate()[0].splitlines() if "::" in line] for run in runs]
    assert [run.returncode for run in runs] == [0] * n
    assert got == expected


SUITE = {
    "conftest.py": 'pytest_plugins = ["helpers_shards"]\n',
    "test_a.py": """
import unittest
import pytest

pytestmark = pytest.mark.browser

class TestParams:
    @pytest.mark.parametrize("x", ["1", "a::b", "c-d"])
    def test_p(self, x): pass
    def test_q(self): pass

@pytest.mark.parametrize("y", range(3))
def test_free(y): pass

def test_pytest_subtests(subtests):
    for i in range(2):
        with subtests.test(i=i): pass

class UnitSubtests(unittest.TestCase):
    def test_sub(self):
        for i in range(3):
            with self.subTest(i=i): pass
    def test_plain(self): pass
""",
    "test_b.py": """
import pytest

@pytest.mark.browser
class TestKnown:
    def test_1(self): pass
    def test_2(self): pass

@pytest.mark.browser
class TestOther:
    def test_1(self): pass

def test_not_selected(): pass
""",
}
SECONDS = {"test_b.py::TestKnown": 100.0, "test_a.py": 1.0}


@pytest.fixture
def suite(pytester):
    """A small suite that loads the plugin as this repository does, with a timing file that knows two scopes."""
    pytester.makeini(
        "[pytest]\npythonpath = %s\nmarkers =\n    browser: launches a browser\n" % (ROOT / "tests/support")
    )
    for name, text in SUITE.items():
        pytester.path.joinpath(name).write_text(text, encoding="utf-8")
    (pytester.path / "seconds.json").write_text(json.dumps(SECONDS), encoding="utf-8")
    return pytester


def ran(reprec) -> tuple[list[str], Counter]:
    """(the node ids that passed their call in run order, the passed subtests per node id) of an inline run."""
    calls, subtests = [], Counter()
    for report in reprec.getreports("pytest_runtest_logreport"):
        if report.when == "call" and report.passed:
            if isinstance(report, pytest.SubtestReport):
                subtests[report.nodeid] += 1
            else:
                calls.append(report.nodeid)
    return calls, subtests


def test_the_option_runs_each_selected_test_and_its_subtests_in_one_part(suite):
    """-m picks the tests first; each part runs its share with the subtests of its tests, and the parts' runs add up to
    the unsplit run for any n - more parts than scopes included, where the extra parts deselect everything."""
    whole, whole_subtests = ran(suite.inline_run("-m", "browser", "-p", "no:xdist"))
    assert len(whole) == 13 and sum(whole_subtests.values()) == 5, (whole, whole_subtests)
    for n in (1, 2, 3, 6):
        calls, subtests = [], Counter()
        for i in range(1, n + 1):
            part = ran(
                suite.inline_run(
                    "-m", "browser", "-p", "no:xdist", "--shard", "%d/%d" % (i, n), "--shard-seconds", "seconds.json"
                )
            )
            calls += part[0]
            subtests += part[1]
        assert Counter(calls) == Counter(whole), n
        assert subtests == whole_subtests, n


def test_xdist_workers_agree_on_the_part_and_run_its_heaviest_class_first(suite):
    """Under xdist each worker collects and splits on its own; they agree, and the part's heaviest class runs first."""
    args = ["-m", "browser", "--shard", "1/2", "--shard-seconds", "seconds.json"]
    alone = [r.nodeid for r in suite.inline_run(*args, "-p", "no:xdist").getreports("pytest_runtest_logreport")]
    alone = list(dict.fromkeys(alone))
    assert alone[:2] == ["test_b.py::TestKnown::test_1", "test_b.py::TestKnown::test_2"], alone
    result = suite.runpytest_subprocess(*args, "-n", "2", "-rA")
    result.assert_outcomes(passed=len(alone))
    assert sorted(re.findall(r"^PASSED (\S+)$", result.stdout.str(), re.MULTILINE)) == sorted(alone)


def test_a_recording_is_the_seconds_of_each_scope_without_counting_subtests_again(suite):
    """--shard-record writes {scope: seconds} for the scopes that ran, in the form --shard-seconds reads; a subtest's
    report is inside its test's call and adds nothing, and a scope whose tests were all skipped is left out."""
    suite.inline_run("-m", "browser", "-p", "no:xdist", "--shard-record", "out.json")
    recorded = hs.load_seconds(suite.path / "out.json")
    # test_p[a::b] is a scope of its own, as pytest-xdist splits it
    assert sorted(recorded) == [
        "test_a.py",
        "test_a.py::TestParams",
        "test_a.py::TestParams::test_p[a",
        "test_a.py::UnitSubtests",
        "test_b.py::TestKnown",
        "test_b.py::TestOther",
    ]

    def report(cls, nodeid, when, duration):
        return cls(nodeid, (nodeid, 0, nodeid), {}, "passed", None, when, duration=duration)

    reports = [
        report(pytest.TestReport, "m.py::C::t", "setup", 1.0),
        report(pytest.TestReport, "m.py::C::t", "call", 2.0),
        report(pytest.SubtestReport, "m.py::C::t", "call", 1.5),
        report(pytest.TestReport, "m.py::C::t", "teardown", 0.5),
        report(pytest.TestReport, "m.py::f", "call", 0.3),
        report(pytest.TestReport, "m.py::Skipped::t", "setup", 0.2),
        report(pytest.TestReport, "m.py::Skipped::t", "teardown", 0.1),
    ]
    assert hs.scope_seconds(reports) == {"m.py": 0.3, "m.py::C": 3.5}


def test_ci_runs_every_part_once_on_3_12_and_fails_the_required_name_unless_all_passed():
    """browser.yml runs `-m browser --shard i/n` for i in 1..n on the caller's Python; ci.yml calls it once, on 3.12,
    and reports `test (3.12, browser, browser, 2)` - the one browser result it has - from those parts, failing on
    anything but success (a failed, cancelled or skipped part) and running even then (`if: always()`)."""
    browser = jobs((WORKFLOWS / "browser.yml").read_text(encoding="utf-8"))
    (part,) = browser.values()
    assert "python-version: ${{ inputs.python }}" in part
    assert re.search(r"pytest .*-m browser --shard \$\{\{ matrix\.shard \}\}/\$\{\{ strategy\.job-total \}\}", part)
    matrix = re.search(r"\n      matrix:\n((?:        .*\n)+)", part).group(1)
    keys = [line.split(":")[0].strip() for line in matrix.splitlines() if not line.strip().startswith("#")]
    assert keys == ["shard"], matrix  # so strategy.job-total is the number of parts
    ci = jobs((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    (caller,) = [name for name, job in ci.items() if "uses: ./.github/workflows/browser.yml" in job]
    assert re.findall(r'^      python: "([\d.]+)"$', ci[caller], re.MULTILINE) == [BROWSER_PYTHON], ci[caller]
    (gate,) = [
        job for job in ci.values() if re.search(r"^    name: test \([\d.]+, browser, browser, 2\)$", job, re.MULTILINE)
    ]
    assert "    name: test (%s, browser, browser, 2)\n" % BROWSER_PYTHON in gate, gate
    assert "needs: %s\n" % caller in gate and "if: always()\n" in gate, gate
    assert "RESULT: ${{ needs.%s.result }}" % caller in gate and '[ "$RESULT" = success ]' in gate, gate
    assert ci_parts() > 1
