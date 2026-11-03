"""Install instructions name the release that `__version__` names.

README.md, README.ko.md and the agent skill (skill/SKILL.md, skill/SKILL.ko.md) tell people and agents to run
`uv tool install git+https://github.com/dartworklabs/limn@vX.Y.Z`. A release raises `__version__`
(docs/handbook/workflow.md §릴리스); a tag the release leaves behind keeps installing the older release for everyone
who follows the instructions, and nothing else notices.

1. Every `dartworklabs/limn@v<version>` in a tracked Markdown file names `__version__`. CHANGELOG.md and the decision
   and review records (docs/adr/, docs/superpowers/) describe earlier releases and are not read.
2. Each of the four install documents names it at least once, so deleting the line does not pass by naming nothing.

The rule is a pure function over a document's text, so the tests feed it stale text as well as the real files.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL_DOCS = ("README.md", "README.ko.md", "skill/SKILL.md", "skill/SKILL.ko.md")
HISTORY = ("CHANGELOG.md", "docs/adr/", "docs/superpowers/")
TAG = re.compile(r"dartworklabs/limn@v([0-9]+\.[0-9]+\.[0-9]+)")


def version() -> str:
    """`__version__` as src/limn/__init__.py writes it (the source tree, not whichever limn is installed)."""
    text = (ROOT / "src" / "limn" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    assert m, "src/limn/__init__.py sets no __version__"
    return m.group(1)


def stale_tags(text: str, current: str) -> list[str]:
    """Return `line N: v<tag>` for each install tag in a document's text that is not `current`."""
    return [
        "line %d: v%s" % (n, m.group(1))
        for n, line in enumerate(text.splitlines(), 1)
        for m in TAG.finditer(line)
        if m.group(1) != current
    ]


def markdown_files(root: Path = ROOT) -> list[str]:
    """Tracked and untracked-but-not-ignored Markdown files under `root`, history excluded.

    `-z` keeps a non-ASCII name as it is: without it Git quotes and escapes the name, which then names no file.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "-co", "--exclude-standard", "--", "*.md"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return [p for p in out.stdout.split("\0") if p and not p.startswith(HISTORY) and (root / p).is_file()]


def test_the_file_list_keeps_non_ascii_names_and_leaves_out_history_and_ignored_files(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    # Git's default, set here so a contributor's own `core.quotePath false` cannot hide the case.
    subprocess.run(["git", "config", "core.quotePath", "true"], cwd=tmp_path, check=True)
    for name in (
        "docs/설치.md",
        "설명.md",
        "README.md",
        "CHANGELOG.md",
        "docs/adr/0001-기록.md",
        "ignored.md",
        "a.txt",
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("dartworklabs/limn@v0.0.1\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored.md\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/설치.md", "README.md", "CHANGELOG.md", "docs/adr"], cwd=tmp_path, check=True)
    assert sorted(markdown_files(tmp_path)) == ["README.md", "docs/설치.md", "설명.md"]


def test_the_rule_finds_every_tag_but_the_current_one() -> None:
    text = (
        "uv tool install git+https://github.com/dartworklabs/limn@v0.4.22\n"
        "or `git+ssh://git@github.com/dartworklabs/limn@v0.4.45`, not limn@v0.4.21 of another owner\n"
        "both git+https://github.com/dartworklabs/limn@v0.4.45 and dartworklabs/limn@v0.4.4\n"
    )
    assert stale_tags(text, "0.4.45") == ["line 1: v0.4.22", "line 3: v0.4.4"]
    assert stale_tags(text.replace("0.4.22", "0.4.45").replace("v0.4.4\n", "v0.4.45\n"), "0.4.45") == []


def test_every_install_tag_in_the_documents_is_the_current_release() -> None:
    current = version()
    found: dict[str, list[str]] = {}
    for path in markdown_files():
        stale = stale_tags((ROOT / path).read_text(encoding="utf-8"), current)
        if stale:
            found[path] = stale
    assert not found, "install tags other than v%s (raise them with __version__): %s" % (current, found)


@pytest.mark.parametrize("path", INSTALL_DOCS)
def test_each_install_document_names_the_current_release(path: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    assert "dartworklabs/limn@v%s" % version() in text, "%s gives no install command for v%s" % (path, version())
