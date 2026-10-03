"""tools/strict_ratchet.py: the viewer's not-yet-strict type errors per file only go down.

The script's run of tsc needs node_modules (npm ci), which the CI lint job installs and runs it there; these tests
check its counting and comparison on tsc's own output format without node.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("strict_ratchet", ROOT / "tools" / "strict_ratchet.py")
assert SPEC is not None and SPEC.loader is not None
ratchet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ratchet)

OUTPUT = """src/limn/viewer/js/a.js(2,7): error TS18047: 'data' is possibly 'null'.
src/limn/viewer/js/a.js(9,1): error TS2322: Type 'number' is not assignable to type 'null'.
  Type 'number' is not assignable to type 'null'.
src/limn/viewer/js/b.js(1,1): error TS2339: Property 'x' does not exist on type 'never'.
"""


def test_counts_errors_per_file_and_skips_continuation_lines():
    """Each `path(line,col): error` line counts once for its file; an indented detail line counts for nothing."""
    assert ratchet.error_counts(OUTPUT) == {"src/limn/viewer/js/a.js": 2, "src/limn/viewer/js/b.js": 1}
    assert ratchet.error_counts("") == {}


def test_more_errors_than_the_baseline_fail():
    """A file over its baseline, and a file the baseline does not list (baseline 0), each fail."""
    out = ratchet.compare({"a.js": 3, "c.js": 1}, {"a.js": 2})
    assert out == [
        "a.js: 3 errors, baseline 2 - the new code must meet tsconfig.strict.json",
        "c.js: 1 errors, baseline 0 - the new code must meet tsconfig.strict.json",
    ]


def test_fewer_errors_than_the_baseline_fail_until_it_is_lowered():
    """A file under its baseline, or gone from the errors while listed, asks for --update, so the count cannot rise back."""
    assert ratchet.compare({"a.js": 1}, {"a.js": 2, "b.js": 4}) == [
        "a.js: 1 errors, baseline 2 - lower the baseline (--update)",
        "b.js: 0 errors, baseline 4 - lower the baseline (--update)",
    ]


def test_equal_counts_pass():
    """Counts equal to the baseline are no problem, and a file at 0 need not be listed."""
    assert ratchet.compare({"a.js": 2}, {"a.js": 2, "b.js": 0}) == []


def test_the_baseline_lists_only_viewer_parts_with_errors():
    """The committed baseline names viewer JS parts only, each with a positive count."""
    baseline = json.loads((ROOT / "tools" / "strict-baseline.json").read_text(encoding="utf-8"))
    assert baseline
    assert all(k.startswith("src/limn/viewer/js/") and k.endswith(".js") and v > 0 for k, v in baseline.items())
