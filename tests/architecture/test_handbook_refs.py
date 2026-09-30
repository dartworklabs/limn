"""The Handbook's cross-references stay true, and its topics state the present.

1. A section reference - `docs/handbook/X.md §Heading` in src/, tests/ and docs/, or `[X.md](X.md) §Heading` between
   Handbook files - names a heading of X.md. The text after the § runs on into the sentence, so a reference holds
   when it is the start of a heading, or a whole heading followed by other words or a Korean particle (§위치 추정에).
   `§N` names the numbered heading "N. ...". References chained with a comma (§A, §B) are checked too.
2. Every backticked `src/...` or `tests/...` path in a Handbook topic exists.
3. Topics carry no ISO dates (YYYY-MM-DD) outside code fences: history lives in git, CHANGELOG.md and the ADRs
   (docs/handbook/workflow.md §문서 동기화). The index's ADR table is the one place a date may stand.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDBOOK = ROOT / "docs" / "handbook"
FILE_REF = re.compile(r"(?:docs/handbook/|\]\(\.\./handbook/)([a-z0-9-]+\.md)\)? §")
LINK_REF = re.compile(r"\]\(([a-z0-9-]+\.md)\) §")  # a link from one Handbook topic to another
CUT = re.compile(r"[:;,|\"']| - | — |\*/|-->|\. |\.$| and | or ")
PARTICLE = re.compile(r"(에서|에|으로|로|을|를|이|가|은|는|과|와|의|도)")
PATH = re.compile(r"`((?:src|tests)/[^`*<\s]+)`")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# Topics not yet brought to the present-tense rule; the documentation pass that cleans one removes it from this set.
DATES_PENDING: set[str] = set()


def prose_lines(path: Path) -> list[tuple[int, str]]:
    """The numbered lines of a Markdown file that lie outside ``` code fences."""
    out, fenced = [], False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced:
            out.append((n, line))
    return out


def headings(name: str) -> list[str]:
    """The heading texts of one Handbook topic, without the leading #s and backticks."""
    return [t.lstrip("#").strip().replace("`", "") for _, t in prose_lines(HANDBOOK / name) if re.match(r"#{1,6} ", t)]


def names_heading(text: str, heading: str) -> bool:
    """Whether the words after a § name this heading (see the module docstring for the forms that count)."""
    if heading.startswith(text) or text.startswith(heading):
        return True
    number = re.match(r"\d+(?!\d)", text)
    if number and heading.startswith(number.group() + "."):
        return True
    # Neither is a prefix of the other, so they differ somewhere: a heading word may end there and a particle begin.
    k = next(i for i, (a, b) in enumerate(zip(text, heading, strict=False)) if a != b)
    return k > 0 and heading[k] == " " and bool(PARTICLE.match(text[k:]))


def references(line: str, pattern: re.Pattern[str] = FILE_REF) -> list[tuple[str, str]]:
    """(topic, words after §) for every section reference on a line, including the §B of `X.md §A, §B`."""
    found = []
    for m in pattern.finditer(line):
        rest = line[m.end() - 1 :]
        following = pattern.search(rest, 1)
        pieces = (rest[: following.start()] if following else rest).split("§")[1:]
        for i, piece in enumerate(pieces):
            if i and not re.search(r"(,|·| and) ?$", pieces[i - 1]):
                break
            found.append((m.group(1), CUT.split(piece.replace("`", ""), maxsplit=1)[0].strip().rstrip(").")))
    return found


def tracked(*roots: str) -> list[Path]:
    """The text files git tracks under the given roots (the bundled vendor tree is not ours to check)."""
    listed = subprocess.run(["git", "ls-files", *roots], cwd=ROOT, capture_output=True, text=True, check=True)
    paths = [ROOT / p for p in listed.stdout.splitlines()]
    return [p for p in paths if p.is_file() and "vendor" not in p.parts and p.suffix not in {".png", ".pdf", ".otf"}]


def test_section_references_name_real_headings():
    """A reference whose heading was renamed or never existed fails with its file and line."""
    broken = []
    for path in tracked("src", "tests", "docs"):
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            refs = references(line) + (references(line, LINK_REF) if path.parent == HANDBOOK else [])
            for name, text in refs:
                where = f"{path.relative_to(ROOT)}:{n}"
                if not (HANDBOOK / name).is_file():
                    broken.append(f"{where}: no topic {name}")
                elif not any(names_heading(text, h) for h in headings(name) if text and h):
                    broken.append(f"{where}: {name} §{text}")
    assert broken == []


def test_backticked_repository_paths_exist():
    """A Handbook topic that names `src/...` or `tests/...` points at a file or folder that is there."""
    missing = [
        f"{topic.name}:{n}: {p}"
        for topic in sorted(HANDBOOK.glob("*.md"))
        for n, line in prose_lines(topic)
        for p in PATH.findall(line)
        if not (ROOT / p.rstrip("/")).exists()
    ]
    assert missing == []


def test_topics_carry_no_dates():
    """Dates belong to git, the CHANGELOG and the ADRs; a topic states the current rule without them."""
    dated = []
    for topic in sorted(HANDBOOK.glob("*.md")):
        if topic.name in DATES_PENDING:
            continue
        section = ""
        for n, line in prose_lines(topic):
            if line.startswith("## "):
                section = line
            if DATE.search(line) and not (topic.name == "index.md" and section == "## 결정 기록"):
                dated.append(f"{topic.name}:{n}: {line.strip()[:80]}")
    assert dated == []


def test_pending_topics_still_need_the_pass():
    """A pending topic with no date left leaves DATES_PENDING, so the rule guards it from then on."""
    clean = [t for t in sorted(DATES_PENDING) if not any(DATE.search(s) for _, s in prose_lines(HANDBOOK / t))]
    assert clean == []
