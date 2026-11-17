"""tools/strict_ratchet.py: the viewer's not-yet-met checks (ESLint, the module boundaries) per file only go down.

The script's runs need node_modules (npm ci), which the CI lint job installs and runs it there; these tests check its
counting and comparison on the tools' own output formats without node.
"""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("strict_ratchet", ROOT / "tools" / "strict_ratchet.py")
assert SPEC is not None and SPEC.loader is not None
ratchet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ratchet)


def test_more_errors_than_the_baseline_fail():
    """A file over its baseline, and a file the baseline does not list (baseline 0), each fail."""
    out = ratchet.compare({"a.js": 3, "c.js": 1}, {"a.js": 2}, "r1")
    assert out == [
        "a.js: 3 errors, baseline 2 - the new code must meet r1",
        "c.js: 1 errors, baseline 0 - the new code must meet r1",
    ]


def test_fewer_errors_than_the_baseline_fail_until_it_is_lowered():
    """A file under its baseline, or gone from the errors while listed, asks for --update, so the count cannot rise back."""
    assert ratchet.compare({"a.js": 1}, {"a.js": 2, "b.js": 4}, "r1") == [
        "a.js: 1 errors, baseline 2 - lower the baseline (--update)",
        "b.js: 0 errors, baseline 4 - lower the baseline (--update)",
    ]


def test_equal_counts_pass():
    """Counts equal to the baseline are no problem, and a file at 0 need not be listed."""
    assert ratchet.compare({"a.js": 2}, {"a.js": 2, "b.js": 0}, "r1") == []


def test_eslint_counts_per_rule_and_file_and_refuses_a_file_it_could_not_check():
    """ESLint's JSON report counts each message once for its rule and file (relative to the checkout); a message with
    no rule is a file ESLint could not parse, which no count can stand for."""
    report = [
        {
            "filePath": str(ROOT / "src/limn/viewer/js/a.js"),
            "messages": [{"ruleId": "r1"}, {"ruleId": "r1"}, {"ruleId": "r2"}],
        },
        {"filePath": str(ROOT / "src/limn/viewer/js/b.js"), "messages": [{"ruleId": "r1"}]},
        {"filePath": str(ROOT / "src/limn/viewer/js/c.js"), "messages": []},
    ]
    assert ratchet.eslint_counts(report) == {
        "r1": {"src/limn/viewer/js/a.js": 2, "src/limn/viewer/js/b.js": 1},
        "r2": {"src/limn/viewer/js/a.js": 1},
    }
    broken = [
        {"filePath": str(ROOT / "src/limn/viewer/js/a.js"), "messages": [{"ruleId": None, "message": "Parsing error"}]}
    ]
    try:
        ratchet.eslint_counts(broken)
    except SystemExit as stop:
        assert "could not check src/limn/viewer/js/a.js" in str(stop)
    else:
        raise AssertionError("a parse error must stop the ratchet")


def test_every_check_and_rule_is_compared_and_a_new_rule_starts_at_zero():
    """compare_all names the check and rule of each difference; a rule the baseline does not name has a baseline of 0,
    and a rule that is met everywhere may leave the baseline."""
    found = {"eslint": {"r1": {"a.js": 2}, "new": {"b.js": 1}}, "boundaries": {}}
    baseline = {"eslint": {"r1": {"a.js": 2}}, "boundaries": {"cycle": {"c.js": 3}}}
    assert ratchet.compare_all(found, baseline) == [
        "eslint new: b.js: 1 errors, baseline 0 - the new code must meet new",
        "boundaries cycle: c.js: 0 errors, baseline 3 - lower the baseline (--update)",
    ]
    assert ratchet.compare_all(found, found) == []


def test_the_naming_rules_are_held_per_file_and_only_go_down():
    """limn/plain-names and limn/no-history-comment are counted per file like every other ESLint rule: a new
    abbreviation or history comment (a count above the file's baseline, or in a file the baseline does not name) fails
    and names the rule, and a burned-down count fails until the baseline is lowered."""
    report = [
        {
            "filePath": str(ROOT / "src/limn/viewer/js/a.ts"),
            "messages": [
                {"ruleId": "limn/plain-names"},
                {"ruleId": "limn/plain-names"},
                {"ruleId": "limn/no-history-comment"},
            ],
        },
        {"filePath": str(ROOT / "src/limn/viewer/js/b.ts"), "messages": [{"ruleId": "limn/plain-names"}]},
    ]
    found = {"eslint": ratchet.eslint_counts(report), "boundaries": {}}
    held = {
        "eslint": {
            "limn/plain-names": {"src/limn/viewer/js/a.ts": 2, "src/limn/viewer/js/b.ts": 1},
            "limn/no-history-comment": {"src/limn/viewer/js/a.ts": 1},
        }
    }
    assert ratchet.compare_all(found, held) == []
    grown = {
        "eslint": {**held["eslint"], "limn/plain-names": {"src/limn/viewer/js/a.ts": 1, "src/limn/viewer/js/b.ts": 1}}
    }
    assert ratchet.compare_all(found, grown) == [
        "eslint limn/plain-names: src/limn/viewer/js/a.ts: 2 errors, baseline 1 - the new code must meet limn/plain-names"
    ]
    burned = {"eslint": {"limn/plain-names": {"src/limn/viewer/js/a.ts": 3, "src/limn/viewer/js/b.ts": 1}}}
    assert ratchet.compare_all(found, burned) == [
        "eslint limn/no-history-comment: src/limn/viewer/js/a.ts: 1 errors, baseline 0 - the new code must meet limn/no-history-comment",
        "eslint limn/plain-names: src/limn/viewer/js/a.ts: 2 errors, baseline 3 - lower the baseline (--update)",
    ]


def test_the_baseline_lists_only_viewer_modules_with_violations():
    """The committed baseline holds the two checks, each naming viewer modules (.ts) only with positive counts (a rule
    leaves it once it is met)."""
    baseline = json.loads((ROOT / "tools" / "strict-baseline.json").read_text(encoding="utf-8"))
    assert sorted(baseline) == ["boundaries", "eslint"]
    tables = [*baseline["eslint"].values(), *baseline["boundaries"].values()]
    for counts in tables:
        assert counts
        assert all(k.startswith("src/limn/viewer/js/") and k.endswith(".ts") and v > 0 for k, v in counts.items())


def test_the_boundary_baseline_holds_only_cycle():
    """feature-dependency, platform-isolation and role are invariants the boundary check fails on outright, so the
    baseline counts only cycle."""
    baseline = json.loads((ROOT / "tools" / "strict-baseline.json").read_text(encoding="utf-8"))
    assert sorted(baseline["boundaries"]) == ["cycle"]


def test_a_broken_boundary_invariant_fails_the_run(monkeypatch):
    """The boundary check's exit 2 (a table mistake or a broken invariant) is no count: the run stops with what it said."""
    said = "feature-dependency: js/pdf/view.ts (pdf) imports js/pins/view.ts (pins): ALLOWED has no pdf -> pins"
    monkeypatch.setattr(ratchet, "_require", lambda path: None)
    monkeypatch.setattr(
        ratchet.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 2, stdout="", stderr=said + "\n")
    )
    with pytest.raises(SystemExit, match="feature-dependency: js/pdf/view.ts"):
        ratchet.run_boundaries()
