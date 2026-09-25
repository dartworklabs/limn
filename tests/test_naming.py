"""Repository hygiene: one name for the app, and no personal data.

1. The app is called Limn everywhere. Its former names may appear only in the README "History"
   sections, in `limn migrate` (src/limn/migrate.py) and its tests, and in a CHANGELOG.
2. No personal data: real e-mail domains, home paths, tailnet/machine names, avatar URLs, or the
   names of the papers the app was first used on. The patterns are assembled from pieces so this
   file does not contain them literally.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()


def j(*parts):
    return "".join(parts)


OLD_NAMES = re.compile("|".join([
    j("pin", "-viewer"), j("pin", "_viewer"), j("pin", "_server"), j("pin", "-picker"), j("pin", "_picker"),
    j("manuscript-", "pin"), j("핀 ", "뷰어"),
]), re.I)

PERSONAL = re.compile("|".join([
    r"[A-Za-z0-9._%+-]+@(?:" + j("gm", "ail") + "|" + j("nav", "er") + "|" + j("da", "um") + "|" + j("hanm", "ail")
    + "|" + j("jn", r"u\.ac") + r")\.",
    j("tail", "8937"), j("ml", "-main"), j("ml", "-a6000"), j("168", r"\.131\."),
    j("/home/", "won"), j("/Users/", "won"), j("google", "usercontent"),
    j("won", "jun"), j("sang", "won"), j("상", "원"), j("원", "준"),
    j("cp", "ptl"), r"(?<![A-Za-z])" + j("pp", "tl") + r"(?![A-Za-z])", j("bet", "lab"),
    j("iTrans", "former"), j("lesth", "esia"),
]), re.I)

ALLOWED_OLD_NAME_FILES = {"src/limn/migrate.py", "tests/test_migrate.py", "CHANGELOG.md"}
HISTORY_READMES = {"README.md", "README.ko.md"}
HISTORY_HEADING = re.compile(r"^## (History|출처|이력)", re.M)


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split("\n")
    for rel in out:
        if not rel:
            continue
        p = ROOT / rel
        if p.resolve() == SELF or not p.is_file():
            continue
        if rel.startswith("src/limn/vendor/") and rel.endswith(".mjs"):
            continue                                  # minified third-party code
        try:
            yield rel, p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def outside_history(text):
    """README text with the History section (up to the next level-2 heading) removed."""
    m = HISTORY_HEADING.search(text)
    if not m:
        return text
    nxt = re.search(r"^## ", text[m.end():], re.M)
    return text[:m.start()] + (text[m.end() + nxt.start():] if nxt else "")


def hits(pattern, text):
    return sorted({m.group(0) for m in pattern.finditer(text)})


def test_former_names_only_in_allowed_places():
    bad = {}
    for rel, text in tracked_files():
        if rel in ALLOWED_OLD_NAME_FILES:
            continue
        if rel in HISTORY_READMES:
            text = outside_history(text)
        found = hits(OLD_NAMES, text) + hits(OLD_NAMES, rel)
        if found:
            bad[rel] = found
    assert not bad, "former names outside the allowed places: %s" % bad


def test_no_personal_data():
    bad = {}
    for rel, text in tracked_files():
        found = hits(PERSONAL, text)
        if found:
            bad[rel] = found
    assert not bad, "personal data: %s" % bad


def test_readmes_have_a_history_section_and_link_each_other():
    en = (ROOT / "README.md").read_text(encoding="utf-8")
    ko = (ROOT / "README.ko.md").read_text(encoding="utf-8")
    assert HISTORY_HEADING.search(en) and HISTORY_HEADING.search(ko)
    assert "README.ko.md" in en.split("\n## ")[0]
    assert "README.md" in ko.split("\n## ")[0]
