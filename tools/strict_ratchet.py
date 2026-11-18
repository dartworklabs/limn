"""Check viewer module boundaries and hold ESLint trust points to the committed per-file baseline.

Every boundary violation fails both normal and --update runs. The baseline holds ESLint messages
per rule and file. The trust points are documented in docs/handbook/viewer.md and ADR-0046 D8.
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
    """Compare ESLint counts by rule, treating any missing rule as zero."""
    now, base = found.get("eslint", {}), baseline.get("eslint", {})
    assert isinstance(now, Mapping) and isinstance(base, Mapping)
    out = []
    for rule in sorted(set(now) | set(base)):
        out += ["eslint %s: %s" % (rule, line) for line in compare(now.get(rule, {}), base.get(rule, {}), rule)]
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


def run_boundaries() -> None:
    """Reject every broken module boundary, including when updating the ESLint baseline."""
    _require(NODE_MODULES / "rollup")
    proc = subprocess.run(["node", str(BOUNDARIES)], cwd=ROOT, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit("the boundary check failed (exit %d):\n%s%s" % (proc.returncode, proc.stdout, proc.stderr))


def total(found: Mapping[str, object], check: str) -> int:
    """The sum of one check's counts."""
    value = found.get(check, {})
    assert isinstance(value, Mapping)
    return sum(n for c in value.values() for n in c.values())


def main(argv: list[str]) -> int:
    """Compare the counts with the baseline (exit 1 on any difference), or with --update write them as the baseline."""
    run_boundaries()
    found = {"eslint": eslint_counts(run_eslint())}
    summary = "eslint %d" % total(found, "eslint")
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
