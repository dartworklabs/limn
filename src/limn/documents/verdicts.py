"""A document's verdict words: the producer file `<name>.limnverdicts.json` (format `limn-verdicts/1`) next to it.

A project may declare, next to a registered document, the words a person can pick as a pin's verdict with one press
(docs/superpowers/specs/2026-10-26-verdict-pins.md §판정 낱말 파일). The file is written by the repository that owns the
document, so it is untrusted input: parse_verdicts recognizes it completely or names why it cannot be used, and
nothing here repairs a malformed file. The file has no path or URL field, so it never leads to another file.

- verdicts_path: where a document's word file is - its main file with the kind suffix (.tex, .pdf or the map's
  .limnmap.json) replaced by .limnverdicts.json. A '::' document's main file is the path after '::' already.
- parse_verdicts (pure): the bytes -> VerdictWords, or VerdictsUnusable with the reason code docs and meta report.
- VerdictFiles: one run's reader. It opens the file only through the checked ManuscriptFile (limn.platform.files:
  inside the manuscript tree, under no dot-named part, no symlink swapped in), reads at most VERDICTS_MAX_BYTES + 1
  bytes, parses a file again only when its signature (mtime_ns, size, inode) changed, and warns on the server log once
  per unusable version of a file.
- verdict_fields: what GET /api/docs' entries and the full GET /api/meta add for a document - `verdicts`, or
  `verdicts_error`, or nothing when the document has no word file.

The word file is not a LaTeX source: it is not part of a build's fingerprint or src_mtime (limn.builds owns those and
never names it).
"""

import json
import os
import re
import sys
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeAlias

from limn.platform.files import (
    BoundedBytes,
    FileSignature,
    ManuscriptFile,
    OverLimit,
    ReadRefused,
    file_in_tree,
)
from limn.runtime.documents import MAP_SUFFIX, Doc

VERDICTS_FORMAT = "limn-verdicts/1"
VERDICTS_SUFFIX = ".limnverdicts.json"
VERDICTS_MAX_BYTES = 4096
VERDICTS_MAX = 5
LABEL_MAX = 12
# A key: 1-16 Unicode letters, digits, '-' or '_' (Python's [\w-]). The key is stored on the pin as written and shown
# in pins.md's number cell, so it never holds '|', a space or a line break. limn.pins.verdict reads a stored verdict
# by the same rule; tests/contracts/test_verdict_keys.py holds the two in agreement.
KEY_RE = re.compile(r"[\w-]{1,16}")
# Unicode categories a button label may not hold: control, format (bidirectional overrides included) and surrogate
# characters, and the line and paragraph separators.
LABEL_REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})

# Why a word file that exists cannot be used, as /api/docs and /api/meta report it (`verdicts_error`).
UnusableReason: TypeAlias = Literal["unreadable", "too_large", "invalid"]


@dataclass(frozen=True)
class VerdictChoice:
    """One verdict word: its key (what a pin stores), the label its button shows (the key when the file names none)
    and whether it is saved only on a second press (confirm)."""

    key: str
    label: str
    confirm: bool

    def __post_init__(self) -> None:
        """Reject a choice the file rules would not let through (a defect of whoever built it): the label is the
        file's own (1-12 characters, _usable_label) or the key itself, which may be up to 16."""
        if not (isinstance(self.key, str) and KEY_RE.fullmatch(self.key)):
            raise ValueError("a verdict key is 1-16 letters, digits, '-' or '_'")
        if not (self.label == self.key or _usable_label(self.label)):
            raise ValueError("a verdict label is the key or 1-12 characters without control characters")
        if not isinstance(self.confirm, bool):
            raise ValueError("confirm is a boolean")


@dataclass(frozen=True)
class VerdictWords:
    """A usable word file: whether it asks for page verdicts (`page`, before the document's kind is applied) and its
    choices in file order - one to VERDICTS_MAX of them, no key twice."""

    page: bool
    choices: tuple[VerdictChoice, ...]

    def __post_init__(self) -> None:
        """Reject an empty, too long or repeating choice list (a defect of whoever built it)."""
        keys = [choice.key for choice in self.choices]
        if not 1 <= len(keys) <= VERDICTS_MAX or len(set(keys)) != len(keys):
            raise ValueError("a word file declares 1-5 verdicts with distinct keys")

    @property
    def keys(self) -> tuple[str, ...]:
        """The verdict keys in file order."""
        return tuple(choice.key for choice in self.choices)


@dataclass(frozen=True)
class VerdictsUnusable:
    """The document has a word file that cannot be used, so it has no verdicts: it cannot be read (unreadable: a
    link out of the manuscript tree, no permission, not a regular file), it is over VERDICTS_MAX_BYTES (too_large), or
    it breaks a rule of the format (invalid). Every reason is answered the same way - no verdicts, the code reported
    and logged - so one type carries it."""

    reason: UnusableReason


@dataclass(frozen=True)
class NoVerdictFile:
    """The document has no word file: it has no verdicts and nothing is reported."""


VerdictAnswer: TypeAlias = VerdictWords | VerdictsUnusable | NoVerdictFile


class _Invalid(Exception):
    """A rule of the format is broken; caught inside parse_verdicts and answered as VerdictsUnusable("invalid")."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """json.loads' object hook: the object, or _Invalid when a name repeats - json would keep the last value
    silently, so a file could show one key to a reviewer and mean another."""
    out: dict[str, Any] = {}
    for name, value in pairs:
        if name in out:
            raise _Invalid("repeated name %r" % name)
        out[name] = value
    return out


def _no_constant(name: str) -> Any:
    """json.loads' constant hook: NaN, Infinity and -Infinity are not JSON, so a file holding one is invalid."""
    raise _Invalid("not JSON: %s" % name)


def _usable_label(label: object) -> bool:
    """Is label a button name the file may give: a string of 1 to LABEL_MAX characters, none of them in
    LABEL_REFUSED_CATEGORIES?"""
    return (
        isinstance(label, str)
        and 1 <= len(label) <= LABEL_MAX
        and not any(unicodedata.category(ch) in LABEL_REFUSED_CATEGORIES for ch in label)
    )


def _choice(item: object) -> VerdictChoice:
    """One entry of `verdicts` as a choice, or _Invalid: an object with a key that fits KEY_RE, an optional label
    (_usable_label; without one the button shows the key, which may be longer than a label) and an optional boolean
    confirm. Other names in it are ignored."""
    if not isinstance(item, dict):
        raise _Invalid("a verdict is an object")
    key = item.get("key")
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        raise _Invalid("bad key")
    label = item.get("label", key)
    if "label" in item and not _usable_label(label):
        raise _Invalid("bad label")
    confirm = item.get("confirm", False)
    if not isinstance(confirm, bool):
        raise _Invalid("confirm is not a boolean")
    return VerdictChoice(key, label, confirm)


def parse_verdicts(raw: bytes) -> VerdictWords | VerdictsUnusable:
    """The word file raw holds, or why it cannot be used - checked in this order: more than VERDICTS_MAX_BYTES bytes
    (too_large, before decoding); then invalid for anything that is not UTF-8 JSON without a repeated name in any
    object and without NaN or Infinity; a top-level object whose format is exactly VERDICTS_FORMAT; page, when
    present, a boolean; verdicts a list of 1 to VERDICTS_MAX entries (_choice) whose keys are distinct. Names the
    format does not know are ignored, at the top level and in an entry. Pure and total: any bytes give one of the two
    answers, never an exception."""
    if len(raw) > VERDICTS_MAX_BYTES:
        return VerdictsUnusable("too_large")
    try:
        top = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_no_constant)
        if not isinstance(top, dict) or top.get("format") != VERDICTS_FORMAT:
            raise _Invalid("not a limn-verdicts/1 object")
        page = top.get("page", False)
        if not isinstance(page, bool):
            raise _Invalid("page is not a boolean")
        items = top.get("verdicts")
        if not isinstance(items, list) or not 1 <= len(items) <= VERDICTS_MAX:
            raise _Invalid("verdicts is a list of 1-5 entries")
        choices = tuple(_choice(item) for item in items)
        if len({choice.key for choice in choices}) != len(choices):
            raise _Invalid("a key repeats")
        return VerdictWords(page, choices)
    except (_Invalid, UnicodeDecodeError, ValueError, RecursionError):
        return VerdictsUnusable("invalid")


def verdicts_path(doc: Doc) -> Path:
    """Where document doc's word file is: next to its main file, named after it with the kind's suffix replaced by
    VERDICTS_SUFFIX - figures.limnmap.json -> figures.limnverdicts.json, main.tex -> main.limnverdicts.json,
    review.pdf -> review.limnverdicts.json. Names a path only; nothing is opened."""
    main = doc.main
    stem = main.name.removesuffix(MAP_SUFFIX) if doc.has_element_map else main.stem
    return main.with_name(stem + VERDICTS_SUFFIX)


def page_verdicts(doc: Doc, words: VerdictWords) -> bool:
    """Whether doc shows page verdicts: the file asks for them and the document's page identifies its target - a
    figure document (the page's figure) or a view-only PDF (the page itself). A LaTeX document never does: a page of
    it is not one item (the spec's D6)."""
    return words.page and (doc.has_element_map or doc.view_only)


def verdict_fields(doc: Doc, answer: VerdictAnswer) -> dict[str, Any]:
    """What a document's /api/docs entry and the full /api/meta add for its word file: {"verdicts": {"page", "choices":
    [{"key", "label", "confirm"}, ...]}} for a usable file (page after page_verdicts), {"verdicts_error": <reason>}
    for an unusable one, {} without one."""
    match answer:
        case VerdictWords(choices=choices):
            return {
                "verdicts": {
                    "page": page_verdicts(doc, answer),
                    "choices": [{"key": c.key, "label": c.label, "confirm": c.confirm} for c in choices],
                }
            }
        case VerdictsUnusable(reason=reason):
            return {"verdicts_error": reason}
        case NoVerdictFile():
            return {}


def verdict_keys(answer: VerdictAnswer) -> tuple[str, ...]:
    """The keys a pin of the document may carry as its verdict now, in file order; () without a usable word file."""
    return answer.keys if isinstance(answer, VerdictWords) else ()


# A version of a word file as the reader tells versions apart: the signature of a descriptor it read, or a word for a
# file it could not open - "absent" (nothing there) or "unopened" (something there it may not or cannot read).
Version: TypeAlias = FileSignature | Literal["absent", "unopened"]


def _stderr(message: str) -> None:
    """The server log: one line on stderr."""
    print(message, file=sys.stderr)


@dataclass
class VerdictFiles:
    """One run's reader of its documents' word files, kept per word-file path.

    read(doc) checks where the file is (file_in_tree against the document's manuscript root and state folder; never a
    raw open), stats the checked descriptor, and parses again only when that version differs from the one it holds:
    a read and a parse happen when a file appears, changes or goes away, not on every poll. Each new unusable version
    is reported once through warn (the server log by default) - a file that stays broken is not reported again,
    and one broken again after a fix is. The parse is pure (parse_verdicts), so a warm reader answers what a cold
    one does. Request threads share it: the version check, the read and parse of a new version and its entry happen
    under one lock, so of two threads that ask for the same new version at once one reads it and the other is
    answered from its entry, and a broken version is reported once. The lock is held for a stat and a read of at most
    VERDICTS_MAX_BYTES + 1 bytes of a checked file, never for the warning."""

    warn: Callable[[str], None] = _stderr
    _entries: dict[str, tuple[Version, VerdictAnswer]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def read(self, doc: Doc) -> VerdictAnswer:
        """Document doc's word file now: VerdictWords, VerdictsUnusable or NoVerdictFile. Reads at most
        VERDICTS_MAX_BYTES + 1 bytes of it, through the checked handle only, and only for a version not seen before;
        the thread that reads an unusable version is the one that warns."""
        path = verdicts_path(doc)
        checked = file_in_tree(str(path), doc.paths.src, doc.paths.state)
        with self._lock:
            version = self._version(path, checked)
            held = self._entries.get(str(path))
            if held is not None and held[0] == version:
                return held[1]
            version, answer = self._load(path, checked, version)
            self._entries[str(path)] = (version, answer)
        if isinstance(answer, VerdictsUnusable):  # a version not seen before: a held one returned above
            self.warn(
                "warning: verdict words of document %s are not used (%s): %s"
                % (doc.key, answer.reason, _shown(doc, path))
            )
        return answer

    @staticmethod
    def _version(path: Path, checked: object) -> Version:
        """The version of the file at path now: its descriptor's signature when the checked handle opens it, else
        "absent" when nothing is at path (not even a dangling link) or "unopened" when something is."""
        if isinstance(checked, ManuscriptFile):
            found = checked.metadata()
            if found is not None:
                return FileSignature.of(found)
        return "unopened" if os.path.lexists(path) else "absent"

    @staticmethod
    def _load(path: Path, checked: object, version: Version) -> tuple[Version, VerdictAnswer]:
        """Read and parse one version: (the version the answer belongs to, the answer). A bounded read names the
        signature of the descriptor it read, which may be newer than the one stat'ed a moment before; the entry is
        kept under that one, so the next read misses only if the file changed again."""
        if version == "absent":
            return version, NoVerdictFile()
        if not isinstance(checked, ManuscriptFile) or version == "unopened":
            return version, VerdictsUnusable("unreadable")
        got = checked.read_bounded(VERDICTS_MAX_BYTES)
        match got:
            case BoundedBytes(data=data, signature=signature):
                return signature, parse_verdicts(data)
            case OverLimit(signature=signature):
                return signature, VerdictsUnusable("too_large")
            case ReadRefused():
                if os.path.lexists(path):  # replaced or made unreadable between the stat and the read
                    return "unopened", VerdictsUnusable("unreadable")
                return "absent", NoVerdictFile()


def _shown(doc: Doc, path: Path) -> str:
    """The word file's path as the log line names it: relative to the manuscript root when it lies under it, else its
    file name - never a home folder or another absolute path."""
    try:
        return str(path.relative_to(doc.paths.src))
    except ValueError:
        return path.name
