"""Hold the viewer's not-yet-strict type errors to a per-file count that only goes down (docs/handbook/viewer.md §타입 검사).

The viewer's JS parts share one global scope, so a stricter tsc option cannot be turned on one file at a time. Instead
tsconfig.strict.json turns the next options on, and this script runs it and compares each part's error count with
tools/strict-baseline.json: a part with more errors than its baseline fails (new code must meet the stricter rule), and
a part with fewer fails too until the baseline is lowered with --update, so the count never creeps back. A part not in
the baseline has a baseline of 0.

Run: npm ci --ignore-scripts && uv run python tools/strict_ratchet.py [--update]
"""

import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tools" / "strict-baseline.json"
TSC = ROOT / "node_modules" / ".bin" / "tsc"
ERROR = re.compile(r"^(?P<file>[^\s(]+)\(\d+,\d+\): error TS\d+:", re.M)


def error_counts(output: str) -> dict[str, int]:
    """Errors per file in tsc's plain (--pretty false) output, by the path tsc prints."""
    return dict(Counter(m["file"] for m in ERROR.finditer(output)))


def compare(counts: Mapping[str, int], baseline: Mapping[str, int]) -> list[str]:
    """Each file whose error count differs from its baseline (0 when unlisted), as a line saying which way; empty when
    every count equals its baseline."""
    out = []
    for name in sorted(set(counts) | set(baseline)):
        now, base = counts.get(name, 0), baseline.get(name, 0)
        if now > base:
            out.append("%s: %d errors, baseline %d - the new code must meet tsconfig.strict.json" % (name, now, base))
        elif now < base:
            out.append("%s: %d errors, baseline %d - lower the baseline (--update)" % (name, now, base))
    return out


def run_tsc() -> str:
    """tsc -p tsconfig.strict.json's output, type errors included. Raises SystemExit when tsc is not installed (npm ci)
    or fails without listing type errors (a broken config)."""
    if not TSC.exists():
        raise SystemExit("tsc is not installed: run `npm ci --ignore-scripts` first")
    proc = subprocess.run(
        [str(TSC), "-p", "tsconfig.strict.json", "--pretty", "false"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 and not ERROR.search(proc.stdout):  # a nonzero exit with errors listed is the answer
        raise SystemExit("tsc failed (exit %d):\n%s%s" % (proc.returncode, proc.stdout, proc.stderr))
    return proc.stdout


def main(argv: list[str]) -> int:
    """Compare the counts with the baseline (exit 1 on any difference), or with --update write them as the baseline."""
    counts = error_counts(run_tsc())
    if "--update" in argv:
        BASELINE.write_text(json.dumps(dict(sorted(counts.items())), indent=2) + "\n", encoding="utf-8")
        print("wrote %s: %d errors in %d files" % (BASELINE.name, sum(counts.values()), len(counts)))
        return 0
    problems = compare(counts, json.loads(BASELINE.read_text(encoding="utf-8")))
    for line in problems:
        print(line)
    if not problems:
        print("strict ratchet: %d errors in %d files, as the baseline says" % (sum(counts.values()), len(counts)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
