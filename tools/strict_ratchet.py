"""Hold the viewer's not-yet-met checks to per-file counts that only go down (docs/adr/0042-viewer-es-modules.md D7,
docs/handbook/viewer.md §타입 검사).

Two checks run over the viewer's ES modules (TypeScript, src/limn/viewer/js/**/*.ts), and the existing code does not
meet all of them yet (tsc, with the full TypeScript `strict` set, is not among them: tsconfig.json turns it on and npm
run typecheck must report no error):

- eslint: every rule eslint.config.mjs turns on (no any, no type assertion, no write to another module's state, no
  confusing global, an exhaustive switch over a closed union, a declared name of whole words, a comment with no
  history - limn/plain-names and limn/no-history-comment, tools/viewer-names.json), per rule.
- boundaries: tools/check_viewer_boundaries.mjs - import cycles, the one boundary rule the code does not meet yet. Its
  other rules (feature dependencies ALLOWED does not list, platform importing a feature, role rules) are invariants:
  the check fails outright on any violation of one, so this run fails with it and nothing of them is counted.

This script runs both and compares each file's count, per check and rule, with tools/strict-baseline.json. The
eslint part of the baseline holds only the viewer's trust points - the lines that take a value from outside as its
declared type with nothing to check it against, each commented with what it trusts and what holds that true - and the
one assertion on META's first value; docs/handbook/viewer.md §타입 검사 and docs/adr/0046-viewer-endpoint-answers.md D8
list them. Every other eslint message is to be fixed, not counted. A count above its baseline fails: new code must
meet the rule. A count below fails too, until the baseline is lowered with --update, so it cannot creep back. A file
or rule the baseline does not name has a baseline of 0. A check that fails without giving counts (a broken config, a
parse error, a mistake in the boundary tables, a broken boundary invariant) fails this run.

Run: npm ci --ignore-scripts && uv run python tools/strict_ratchet.py [--update]
"""

import json
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tools" / "strict-baseline.json"
NODE_MODULES = ROOT / "node_modules"
ESLINT = NODE_MODULES / "eslint" / "bin" / "eslint.js"
BOUNDARIES = ROOT / "tools" / "check_viewer_boundaries.mjs"
VIEWER_JS = "src/limn/viewer/js"

Counts = dict[str, int]  # file -> count
RuleCounts = dict[str, Counts]  # rule -> file -> count
CHECKS = ("eslint", "boundaries")  # the checks the baseline holds, in its order


def eslint_counts(report: list[dict], root: Path = ROOT) -> RuleCounts:
    """Messages per rule and file in ESLint's JSON report, files relative to root. Raises SystemExit for a message
    with no rule (a file ESLint could not parse) - a count cannot stand for it."""
    out: dict[str, Counter[str]] = {}
    for result in report:
        name = Path(result["filePath"]).resolve().relative_to(root).as_posix()
        for message in result["messages"]:
            if not message.get("ruleId"):
                raise SystemExit("eslint could not check %s: %s" % (name, message.get("message")))
            out.setdefault(message["ruleId"], Counter())[name] += 1
    return {rule: dict(sorted(c.items())) for rule, c in sorted(out.items())}


def compare(counts: Mapping[str, int], baseline: Mapping[str, int], what: str) -> list[str]:
    """Each file whose count differs from its baseline (0 when unlisted), as a line saying which way; empty when every
    count equals its baseline. what names the rule in the line."""
    out = []
    for name in sorted(set(counts) | set(baseline)):
        now, base = counts.get(name, 0), baseline.get(name, 0)
        if now > base:
            out.append("%s: %d errors, baseline %d - the new code must meet %s" % (name, now, base, what))
        elif now < base:
            out.append("%s: %d errors, baseline %d - lower the baseline (--update)" % (name, now, base))
    return out


def compare_all(found: Mapping[str, object], baseline: Mapping[str, object]) -> list[str]:
    """compare() over every check and rule: found and baseline hold 'eslint' and 'boundaries' as rule counts. A rule
    only one side names is compared with nothing (0) on the other."""
    out = []
    for check in CHECKS:
        now, base = found.get(check, {}), baseline.get(check, {})
        assert isinstance(now, Mapping) and isinstance(base, Mapping)
        for rule in sorted(set(now) | set(base)):
            out += ["%s %s: %s" % (check, rule, line) for line in compare(now.get(rule, {}), base.get(rule, {}), rule)]
    return out


def _require(path: Path) -> None:
    """Raise SystemExit when a tool npm ci installs is missing."""
    if not path.exists():
        raise SystemExit("%s is not installed: run `npm ci --ignore-scripts` first" % path.relative_to(ROOT))


def run_eslint() -> list[dict]:
    """ESLint's JSON report on the viewer's modules. Raises SystemExit when ESLint is not installed or stops without a
    report (exit 2: a broken config)."""
    _require(ESLINT)
    proc = subprocess.run(
        ["node", str(ESLINT), "--format", "json", VIEWER_JS], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if proc.returncode not in (0, 1):
        raise SystemExit("eslint failed (exit %d):\n%s%s" % (proc.returncode, proc.stdout, proc.stderr))
    return json.loads(proc.stdout)


def run_boundaries() -> RuleCounts:
    """The boundary check's counts (cycle). Raises SystemExit when it refuses its own tables or an invariant rule is
    broken (exit 2), or it fails."""
    _require(NODE_MODULES / "rollup")
    proc = subprocess.run(["node", str(BOUNDARIES), "--json"], cwd=ROOT, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit("the boundary check failed (exit %d):\n%s%s" % (proc.returncode, proc.stdout, proc.stderr))
    counts = json.loads(proc.stdout)
    return {rule: c for rule, c in counts.items() if c}


def measure() -> dict[str, object]:
    """Every check's counts now: {'eslint': rule counts, 'boundaries': rule counts}."""
    return {
        "eslint": eslint_counts(run_eslint()),
        "boundaries": run_boundaries(),
    }


def total(found: Mapping[str, object], check: str) -> int:
    """The sum of one check's counts."""
    value = found.get(check, {})
    assert isinstance(value, Mapping)
    return sum(n for c in value.values() for n in c.values())


def main(argv: list[str]) -> int:
    """Compare the counts with the baseline (exit 1 on any difference), or with --update write them as the baseline."""
    found = measure()
    summary = ", ".join("%s %d" % (check, total(found, check)) for check in CHECKS)
    if "--update" in argv:
        BASELINE.write_text(json.dumps(found, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("wrote %s: %s" % (BASELINE.name, summary))
        return 0
    problems = compare_all(found, json.loads(BASELINE.read_text(encoding="utf-8")))
    for line in problems:
        print(line)
    if not problems:
        print("strict ratchet: %s, as the baseline says" % summary)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
