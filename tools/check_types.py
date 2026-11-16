"""Type-check the production code as on Linux and as on macOS, holding the recorded errors to a baseline that only shrinks.

basedpyright reads its settings from [tool.basedpyright] in pyproject.toml and the errors recorded when the gate came
in from .basedpyright/baseline.json. An error the baseline does not hold fails the run. When an error is gone,
basedpyright rewrites the baseline without it and still exits 0, so this script compares the file before and after:
a rewrite fails too, until the lowered baseline is committed, so a count never creeps back. The baseline cannot hold
an error of one platform only: the other platform's run would drop it.

Run: uv run python tools/check_types.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / ".basedpyright" / "baseline.json"
# Contributors type-check on macOS too, where the standard library declares fewer names (os.sched_getaffinity).
PLATFORMS = ("Linux", "Darwin")


def baseline_changed(before: bytes | None, after: bytes | None) -> bool:
    """Whether a run rewrote the baseline: its bytes differ, or it appeared or vanished."""
    return before != after


def read(path: Path) -> bytes | None:
    """A file's bytes, or None when it does not exist."""
    return path.read_bytes() if path.is_file() else None


def main() -> int:
    """Run basedpyright for each platform; exit 1 when a run fails or lowers the baseline."""
    command = shutil.which("basedpyright")
    if command is None:
        print("basedpyright is not installed: run `uv sync --group dev` first", file=sys.stderr)
        return 1
    before = read(BASELINE)
    failed = []
    for platform in PLATFORMS:
        print(f"basedpyright --pythonplatform {platform}", flush=True)
        if subprocess.run([command, "--pythonplatform", platform], cwd=ROOT, check=False).returncode != 0:
            failed.append(platform)
    if failed:
        print(f"type errors not in the baseline ({', '.join(failed)})", file=sys.stderr)
        return 1
    if baseline_changed(before, read(BASELINE)):
        print(
            f"{BASELINE.relative_to(ROOT)} was lowered: errors it held are gone. Commit the new baseline.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
