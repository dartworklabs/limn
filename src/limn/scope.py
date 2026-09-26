"""Pin-scoped changes (docs/adr/0005-pin-scoped-changes.md): which hunks of a commit belong to one pin - pure.

[변경 보기] showed the whole commit linked to a pin. When one commit fixes several pins, a reviewer could not tell which
change belonged to which pin. The commit's -U0 hunks ("blocks") are attributed to the pin: the agent's recorded
`changes` (new-side line ranges) pick them, or - for a pin without it - the pin's own range mapped through the commit
does. The source diff then shows only those blocks, and the comparison PDF compiles old + only those blocks.

Everything here is pure (coding rule R1): bytes and records in, values out - no file, clock, git or HTTP. The git
edge that reads a commit into FileChange values, and the comparison build, are in limn/revisions.py. An expected
refusal is a returned value of the ScopeRefusal set; limn.web.errors.SCOPE_REJECTIONS is the one table that turns
each into a status, a Korean message and an API reason.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence, Set as AbstractSet
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple, TypeAlias, TypedDict

from limn.mapping import anchor_offset, find_line, norm

Record: TypeAlias = Mapping[str, Any]    # a pin record or a revision row, as read from JSON

SCOPE_CONTEXT = 3                     # context lines around a scoped hunk, git's default
REVISION_DIFF_MAX = 256 * 1024        # response/memory cap of a source diff. Review large changes in the repo instead.
_U0_HUNK_RE = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


@dataclass(frozen=True)
class PinNotInDoc:
    """The request names a pin that does not exist, or one that belongs to another document than the one asked about."""


@dataclass(frozen=True)
class ScopeUnreadable:
    """The commit could not be read again to build the pin's synthetic tree (a timeout, a size limit, a git failure)."""


@dataclass(frozen=True)
class ScopeMismatch:
    """A block of the pin's scope is not in the commit any more - the scope no longer describes this commit."""


@dataclass(frozen=True)
class UnsafePath:
    """A path of the synthetic tree could leave the snapshot (absolute, '..', '.git', a control character, a symlink)."""


@dataclass(frozen=True)
class ScopeUnwritable:
    """The synthetic tree could not be written (an OSError while writing or removing one of its files)."""


# Every expected refusal of pin scoping. limn.web.errors.SCOPE_REJECTIONS gives each its status, message and API reason
# - for an HTTP answer and for the status a failed comparison build records.
ScopeRefusal: TypeAlias = PinNotInDoc | ScopeUnreadable | ScopeMismatch | UnsafePath | ScopeUnwritable


class Block(NamedTuple):
    """One -U0 hunk of a file, 0-based. old_lo is where the old span starts; for a pure insertion (old_n == 0) it is the
    old index the new lines go before. new_lo is the same on the new side."""
    old_lo: int
    old_n: int
    new_lo: int
    new_n: int


class FileChange(NamedTuple):
    """One file of a commit. Paths are repo-relative POSIX; old_path is None for an added file, new_path for a deleted one.
    old/new are the file's lines as bytes, each keeping its newline (git_lines). A pure rename, a mode change, a
    symlink or submodule entry and a binary file have no blocks - they are shown as a header and never attributed to
    a pin. modes are git's (old, new) file modes ("" for a side that does not exist)."""
    old_path: str | None
    new_path: str | None
    old: tuple[bytes, ...]
    new: tuple[bytes, ...]
    blocks: tuple[Block, ...]
    binary: bool
    modes: tuple[str, str] = ("100644", "100644")


class RawEntry(NamedTuple):
    """One entry of `git diff --raw -z`: paths as in FileChange, both blob ids (all zeros for a missing side), the two
    modes, and text - False for a symlink (120000) or submodule (160000) side, which is never read as lines."""
    old_path: str | None
    new_path: str | None
    old_oid: str
    new_oid: str
    modes: tuple[str, str]
    text: bool


ScopeMode = Literal["pin", "commit"]
ScopeSource = Literal["changes", "inferred", "none"]


class Anchor(NamedTuple):
    """A pin's anchor (anchor_of): the normalised first and last non-comment lines and their distance from lo/hi."""
    head: str
    tail: str
    head_off: int
    tail_off: int


class PinFacts(NamedTuple):
    """What scope attribution reads from a pin record (pin_facts): its id, its file relative to the repository (None
    for a view-only PDF pin or a file outside the repository), its range (None when the record has no int lo/hi),
    whether sync lost it, and its anchor if it has a usable one."""
    id: int
    rel: str | None
    lo: int | None
    hi: int | None
    stale: bool
    anchor: Anchor | None


BlockId = tuple[int, int]                         # (index into the files, index into that file's blocks)
ScopeItem = tuple[str, str, int, int, int, int]   # (old path or "", new path or "", *Block) - see scope_key()


class Placement(NamedTuple):
    """Where a pin's range may sit on one side of a commit: side "new" or "old", 1-based lines in git's numbering."""
    side: str
    lo: int
    hi: int


class RepoRange(NamedTuple):
    """A recorded change as attribution sees it: the repo-relative POSIX path (None when the recorded path could not be
    placed in the repository - pin_scope's caller drops those) and its new-side lines, 1 ≤ lo ≤ hi."""
    path: str | None
    lo: int
    hi: int


class ChangeRecord(TypedDict):
    """One item of a pin record's stored `changes` (api.md §핀 레코드 스키마): an absolute path and 1 ≤ lo ≤ hi."""
    file: str
    lo: int
    hi: int


class ScopeMeta(TypedDict):
    """The additive fields of a revision-build status for a pin request (api.md §핀 단위 변경 보기). Never stored in
    status.json: several pins and pin-less requests share the whole-commit comparison."""
    scope: ScopeMode
    pin: int
    source: ScopeSource
    hunks: int
    other: int


class _ScopeCounts(TypedDict):
    """The fields of ScopePayload that are always present (a TypedDict base, since 3.10 has no NotRequired)."""
    pin: int
    mode: ScopeMode
    source: ScopeSource
    hunks: int
    other: int


class ScopePayload(_ScopeCounts, total=False):
    """The additive `scope` object of GET /api/revision-diff?pin=; the patches and their truncation flags only in mode
    "pin"."""
    diff: str
    other_diff: str
    truncated: bool
    other_truncated: bool


class ScopeWrite(NamedTuple):
    """One file of the synthetic "old + this pin's blocks" tree: path relative to the build root, and the bytes to write
    there, or None to remove the file (the pin's block deletes it)."""
    rel: str
    data: bytes | None


class PinScope(NamedTuple):
    """How one pin sees one commit. mode "pin" means the pin owns some but not all of the commit; "commit" means the
    whole commit is shown (it is all the pin's, none of it is, or scoping was not possible). source says what picked
    the blocks: "changes" (recorded at close), "inferred" (the pin's range) or "none"."""
    pin: int
    mode: ScopeMode
    source: ScopeSource
    hunks: int
    other: int
    blocks: tuple[ScopeItem, ...] = ()   # scope_key() of the pin's blocks, in mode "pin" only
    diff: bytes = b""                    # the two patches (UTF-8, cut at REVISION_DIFF_MAX + 1 bytes), in mode "pin" only
    other_diff: bytes = b""


def git_lines(data: bytes) -> tuple[bytes, ...]:
    """Split the way git counts lines - on "\\n" only, keeping it; a last line without one stays as it is."""
    parts = data.split(b"\n")
    return tuple([p + b"\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else []))


def parse_u0_blocks(patch: bytes) -> list[Block]:
    """The blocks of one file's `git diff -U0` output. Only the @@ headers are read: the lines themselves come from
    the two blobs, so a missing final newline or odd bytes never have to be reconstructed from the patch."""
    out = []
    for m in _U0_HUNK_RE.finditer(patch):
        a, c = int(m[1]), int(m[3])
        b = 1 if m[2] is None else int(m[2])
        d = 1 if m[4] is None else int(m[4])
        out.append(Block(a if b == 0 else a - 1, b, c if d == 0 else c - 1, d))
    return out


def touch_range(lo0: int, n: int) -> tuple[int, int]:
    """The 1-based lines a block touches on one side. An empty side (pure insertion or deletion) touches the lines on
    both sides of the point, so a range naming the line before or after a deletion still names the deletion."""
    return (lo0 + 1, lo0 + n) if n > 0 else (max(1, lo0), lo0 + 1)


def _hits(rng: tuple[int, int], lo: int, hi: int) -> bool:
    """Whether the inclusive line ranges rng and lo..hi share at least one line (overlap only - no nearby lines,
    ADR-0005 §3: attributing a neighbour's change is worse than showing the whole commit)."""
    return rng[0] <= hi and rng[1] >= lo


def pin_range_candidates(f: FileChange, pin: PinFacts) -> list[Placement]:
    """Where the pin's range may sit in this commit, best first; the pin must have a range (lo/hi not None).

    A closed pin keeps the lines of its last sync, and nothing records which version that was: the commit's new side
    when the anchor survived the fix, the old side when the fix rewrote the anchored text (sync lost it and kept the
    pre-edit lines) or when the pin was closed before the server's checkout reached the commit. So the anchor is
    looked up on both sides near the recorded range, with the same rule as sync_all(), and the side where it sits
    closer to the recorded line comes first (the recorded number is in that side's coordinates; ties prefer the new
    side). A generic anchor such as \\begin{equation} is found on both sides - the distance is what tells them apart.
    The raw range comes last: old side if the pin went stale, else new."""
    assert pin.lo is not None and pin.hi is not None       # the caller's precondition (attribute_blocks checks it)
    lo, hi, anc = pin.lo, pin.hi, pin.anchor
    found: list[tuple[int, int, Placement]] = []
    sides = {"new": _pin_lines(f.new), "old": _pin_lines(f.old)}
    if anc is not None:
        ho, to = anc.head_off, anc.tail_off
        for rank, side in enumerate(("new", "old")):
            texts, to_git = sides[side]
            if not texts:
                continue
            nl = [norm(t) for t in texts]
            head = find_line(nl, anc.head, lo + ho)
            if head is None:
                continue
            a = max(1, head - ho)
            tail = find_line(nl, anc.tail, hi - to + (a - lo))
            b = max(a, min(len(texts), tail + to if tail is not None and tail >= head else a + (hi - lo)))
            found.append((abs(a - lo), rank, Placement(side, to_git(a), to_git(b))))
    raw = "old" if pin.stale else "new"
    return [c for _, _, c in sorted(found)] + [Placement(raw, sides[raw][1](lo), sides[raw][1](hi))]


def _pin_lines(lines: tuple[bytes, ...]) -> tuple[list[str], Callable[[int], int]]:
    """(texts, to_git) for one side. A pin's lines are numbered by str.splitlines() (tex_lines), git's by "\\n" only; they
    differ after a form feed, a lone CR, U+2028 and the like. texts are the splitlines lines (what anchors match) and
    to_git maps a 1-based splitlines line number to git's line number (identity when the two agree)."""
    text = b"".join(lines).decode("utf-8", "replace")
    texts = text.splitlines()
    if len(texts) == len(lines):
        return texts, lambda n: n
    starts, line = [], 1
    for piece in text.splitlines(keepends=True):
        starts.append(line)
        line += piece.count("\n")
    return texts, lambda n: starts[min(max(n, 1), len(starts)) - 1] if starts else n


def attribute_blocks(files: Sequence[FileChange], pin: PinFacts,
                     changes: Sequence[RepoRange]) -> tuple[ScopeSource, set[BlockId]]:
    """(source, block ids) - the blocks of this commit that belong to the pin.

    changes are the pin's recorded new-side ranges for this commit (recorded_changes). If none of them hits a block
    (a wrong path, lines the commit did not touch) the pin's own range decides (pin_range_candidates; pin.rel is its
    repo-relative file), and if that hits nothing either the answer is ("none", set()) and the caller shows the whole
    commit as before."""
    chosen = set()
    for fi, f in enumerate(files):
        if f.new_path is None:
            continue
        for rel, lo, hi in changes:
            if rel == f.new_path:
                chosen |= {(fi, bi) for bi, b in enumerate(f.blocks) if _hits(touch_range(b.new_lo, b.new_n), lo, hi)}
    if chosen:
        return "changes", chosen
    if pin.rel and pin.lo is not None and pin.hi is not None:
        for fi, f in enumerate(files):
            if pin.rel not in (f.old_path, f.new_path):
                continue
            for side, lo, hi in pin_range_candidates(f, pin):     # the first placement that meets a change wins
                hit = {(fi, bi) for bi, b in enumerate(f.blocks)
                       if _hits(touch_range(b.new_lo, b.new_n) if side == "new" else touch_range(b.old_lo, b.old_n), lo, hi)}
                if hit:
                    chosen |= hit
                    break
    return ("inferred" if chosen else "none"), chosen


def _patch_line(prefix: str, line: bytes) -> list[str]:
    """One diff body line for a file line (prefix " ", "-" or "+"), without its newline or a trailing CR; a line that
    has no newline (the file's last) is followed by git's "\\ No newline at end of file" marker. Undecodable bytes
    become U+FFFD - the patch is for display."""
    text = line.decode("utf-8", "replace")
    if text.endswith("\n"):
        return [prefix + text[:-1].rstrip("\r")]
    return [prefix + text.rstrip("\r"), "\\ No newline at end of file"]


def _file_header(f: FileChange) -> list[str]:
    """git-style header lines for one file of a scoped patch: diff --git, new/deleted/rename lines, and either the
    ---/+++ pair (when hunks follow) or the "Binary files ... differ" line. The viewer's revisionFiles() splits files
    on "diff --git" and names them after " b/"."""
    a, b = f.old_path or f.new_path or "", f.new_path or f.old_path or ""
    out = ["diff --git a/%s b/%s" % (a, b)]
    if f.old_path is None:
        out.append("new file mode " + (f.modes[1] or "100644"))
    elif f.new_path is None:
        out.append("deleted file mode " + (f.modes[0] or "100644"))
    else:
        if f.modes[0] != f.modes[1]:
            out += ["old mode " + f.modes[0], "new mode " + f.modes[1]]
        if a != b:
            out += ["rename from " + a, "rename to " + b]
    old_name = "/dev/null" if f.old_path is None else "a/" + a
    new_name = "/dev/null" if f.new_path is None else "b/" + b
    if f.binary:
        out.append("Binary files %s and %s differ" % (old_name, new_name))
    elif f.blocks:
        out += ["--- " + old_name, "+++ " + new_name]
    return out


def _hunk(f: FileChange, i: int, j: int) -> list[str]:
    """One unified hunk for blocks i..j of f (adjacent in f.blocks). Context stops at any neighbouring block, so a
    change that is not in this hunk never shows up as context; the new-side numbers count every block before i -
    they are the commit's real line numbers, the same ones the whole-commit diff and the pin's range use."""
    bl = f.blocks
    start = max(bl[i - 1].old_lo + bl[i - 1].old_n if i else 0, bl[i].old_lo - SCOPE_CONTEXT)
    end = min(bl[j + 1].old_lo if j + 1 < len(bl) else len(f.old), bl[j].old_lo + bl[j].old_n + SCOPE_CONTEXT, len(f.old))
    shift = sum(b.new_n - b.old_n for b in bl[:i])
    body, oc, nc, pos = [], 0, 0, start
    for b in bl[i:j + 1]:
        for ln in f.old[pos:b.old_lo]:
            body += _patch_line(" ", ln)
        oc += b.old_lo - pos
        nc += b.old_lo - pos
        for ln in f.old[b.old_lo:b.old_lo + b.old_n]:
            body += _patch_line("-", ln)
        for ln in f.new[b.new_lo:b.new_lo + b.new_n]:
            body += _patch_line("+", ln)
        oc += b.old_n
        nc += b.new_n
        pos = b.old_lo + b.old_n
    for ln in f.old[pos:end]:
        body += _patch_line(" ", ln)
    oc += max(0, end - pos)
    nc += max(0, end - pos)
    return ["@@ -%d,%d +%d,%d @@" % (start + 1 if oc else start, oc, start + shift + 1 if nc else start + shift, nc)] + body


def scoped_patch(files: Sequence[FileChange], chosen: AbstractSet[BlockId], want: bool) -> tuple[str, int]:
    """(unified patch text, number of places) for the blocks whose membership in chosen equals want. A place is one
    changed spot (a block); blocks of the same side within 2 x context of each other with nothing between them share
    one hunk, like git. Files without blocks (pure rename, mode change, binary) are one place on the "other" side."""
    out, places = [], 0
    for fi, f in enumerate(files):
        if not f.blocks:
            if not want:
                out += _file_header(f)
                places += 1
            continue
        pick = [bi for bi in range(len(f.blocks)) if ((fi, bi) in chosen) == want]
        if not pick:
            continue
        out += _file_header(f)
        groups: list[list[int]] = []
        for bi in pick:
            prev = f.blocks[bi - 1]                        # only read when bi - 1 was picked too, so bi > 0
            if groups and groups[-1][-1] == bi - 1 and f.blocks[bi].old_lo - (prev.old_lo + prev.old_n) <= 2 * SCOPE_CONTEXT:
                groups[-1].append(bi)
            else:
                groups.append([bi])
        for g in groups:
            out += _hunk(f, g[0], g[-1])
        places += len(pick)
    return "".join(line + "\n" for line in out), places


def apply_blocks(f: FileChange, chosen: AbstractSet[int]) -> bytes:
    """The file's old bytes with only the chosen blocks (indices into f.blocks) replaced by their new lines - the
    synthetic "old + this pin's changes" version the pin-scoped comparison PDF compiles."""
    out: list[bytes] = []
    pos = 0
    for bi, b in enumerate(f.blocks):
        if bi in chosen:
            out += f.old[pos:b.old_lo]
            out += f.new[b.new_lo:b.new_lo + b.new_n]
            pos = b.old_lo + b.old_n
    out += f.old[pos:]
    return b"".join(out)


def _item(f: FileChange, b: Block) -> ScopeItem:
    """One block of file f as a plain value: (old path or "", new path or "", *block)."""
    return (f.old_path or "", f.new_path or "", b.old_lo, b.old_n, b.new_lo, b.new_n)


def scope_key(files: Sequence[FileChange], chosen: AbstractSet[BlockId]) -> tuple[ScopeItem, ...]:
    """The chosen blocks as plain values (path pair + block), sorted - the part of a comparison's identity that says
    which hunks it applies. It does not depend on file order or indices, so it is stable across requests."""
    return tuple(sorted(_item(files[fi], files[fi].blocks[bi]) for fi, bi in chosen))


def pin_scope(files: Sequence[FileChange] | None, pin: PinFacts, changes: Sequence[RepoRange]) -> PinScope:
    """The decision for one pin and one commit's files (None = the commit could not be read for scoping, which
    shows the whole commit). Mode "pin" only when the pin owns some but not all places of the commit. The patches
    are kept cut at REVISION_DIFF_MAX + 1 bytes - one byte more than a response sends, so truncation still shows."""
    if files is None:
        return PinScope(pin.id, "commit", "none", 0, 0)
    source, chosen = attribute_blocks(files, pin, changes)
    mine_text, mine = scoped_patch(files, chosen, True)
    other_text, other = scoped_patch(files, chosen, False)
    if not (chosen and other):
        return PinScope(pin.id, "commit", source, mine, other)
    cut = REVISION_DIFF_MAX + 1
    return PinScope(pin.id, "pin", source, mine, other, scope_key(files, chosen),
                    mine_text.encode("utf-8", "replace")[:cut], other_text.encode("utf-8", "replace")[:cut])


def pin_facts(r: Record, rel: str | None) -> PinFacts:
    """Parses a pin record (already accepted by valid_rec) into what attribution reads. rel is its file relative to
    the repository, resolved by the caller; an anchor without a non-empty head counts as none."""
    stored = r.get("anchor")
    anc: Record = stored if isinstance(stored, dict) else {}
    head = anc.get("head")
    tail = anc.get("tail")
    anchor = (Anchor(head, tail if isinstance(tail, str) else "", anchor_offset(anc.get("head_off")),
                     anchor_offset(anc.get("tail_off"))) if isinstance(head, str) and head else None)
    lo, hi = r.get("lo"), r.get("hi")
    return PinFacts(r["id"], rel, lo if _is_int(lo) else None, hi if _is_int(hi) else None, bool(r.get("stale")), anchor)


_REF_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.ASCII)
_REF_PR_RE = re.compile(r"#(\d+)", re.ASCII)


def ref_commit(ref: object, revisions: Sequence[Record]) -> str | None:
    """The commit a close reference names among revisions ([{id, subject}], newest first) - the viewer's
    matchRevision() rule, kept identical (a test runs both): the first 7-40 hex token that prefixes a commit id,
    else the first #N found in a subject as "(#N)", "pull request #N" or "#N" (the squash or merge commit)."""
    ref = ref if isinstance(ref, str) else ""
    for tok in _REF_SHA_RE.findall(ref):
        for r in revisions:
            if str(r["id"]).startswith(tok):
                return str(r["id"])
    for n in _REF_PR_RE.findall(ref):
        rx = re.compile(r"\(#%s\)|pull request #%s\b|#%s\b" % (n, n, n), re.ASCII)
        for r in revisions:
            if rx.search(r.get("subject") or ""):
                return str(r["id"])
    return None


def recorded_changes(pin: Record, head: str, revisions: Sequence[Record]) -> tuple[ChangeRecord, ...]:
    """The pin's stored `changes` that apply to commit head: none unless changes_at equals done_at (a 0.2.2 server,
    after a rollback, neither clears nor writes them, so an older close's set may still be on the record) and head is
    the commit its close_ref names (ref_commit) - the lines were recorded for that commit, and on any other commit
    they would select another pin's fix (review M1). Items of the wrong shape are skipped."""
    if pin.get("changes_at") != pin.get("done_at") or ref_commit(pin.get("close_ref"), revisions) != head:
        return ()
    return tuple(c for c in (pin.get("changes") or []) if valid_changes([c]))


def scope_meta(sc: PinScope) -> ScopeMeta:
    """The per-request status fields of a pin's comparison PDF (added to every build status answer, never stored)."""
    return {"scope": sc.mode, "pin": sc.pin, "source": sc.source, "hunks": sc.hunks, "other": sc.other}


def scope_payload(sc: PinScope) -> ScopePayload:
    """The additive `scope` object of GET /api/revision-diff?pin=. The two patches are only sent in mode "pin", each cut
    at REVISION_DIFF_MAX bytes like the whole-commit diff, with truncated / other_truncated saying so."""
    out: ScopePayload = {"pin": sc.pin, "mode": sc.mode, "source": sc.source, "hunks": sc.hunks, "other": sc.other}
    if sc.mode == "pin":
        out["diff"] = sc.diff[:REVISION_DIFF_MAX].decode("utf-8", "ignore")
        out["other_diff"] = sc.other_diff[:REVISION_DIFF_MAX].decode("utf-8", "ignore")
        out["truncated"] = len(sc.diff) > REVISION_DIFF_MAX
        out["other_truncated"] = len(sc.other_diff) > REVISION_DIFF_MAX
    return out


def plan_scope_writes(files: Sequence[FileChange] | None, scope: Sequence[ScopeItem],
                      source: str) -> list[ScopeWrite] | ScopeUnreadable | UnsafePath | ScopeMismatch:
    """The files to write into an old-side snapshot so it becomes old + only the scope's blocks.

    source is the build root relative to the repo ("." for the root); files outside it are not part of the compiled
    document and are skipped. Files keep their old names - a rename that belongs to the pin is applied as an edit in
    place, so the old main still finds what it \\inputs; an added file is written, a deleted one removed.
    Refused: ScopeUnreadable (files is None), UnsafePath (a path that could leave the snapshot), ScopeMismatch (a
    block of the scope is not in the commit any more)."""
    if files is None:
        return ScopeUnreadable()
    want: set[ScopeItem] = set(scope)
    found: set[ScopeItem] = set()
    out: list[ScopeWrite] = []
    prefix = "" if source == "." else source + "/"
    for f in files:
        idx = {bi for bi, b in enumerate(f.blocks) if _item(f, b) in want}
        if not idx:
            continue
        found |= {_item(f, f.blocks[bi]) for bi in idx}
        name = f.old_path if f.old_path is not None else f.new_path or ""
        if not name.startswith(prefix):
            continue
        rel = name[len(prefix):]
        if (not rel or rel.startswith("/") or "\\" in rel or any(ord(c) < 32 for c in rel)
                or any(part in ("", ".", "..", ".git") for part in rel.split("/"))):
            return UnsafePath()
        out.append(ScopeWrite(rel, None if f.new_path is None else apply_blocks(f, idx)))
    if found != want:
        return ScopeMismatch()
    return out


_TEXT_MODES = ("100644", "100755")


def parse_raw_entries(raw: bytes) -> list[RawEntry]:
    """The entries of `git diff --raw -z --abbrev=40` output. A side whose mode is not a regular file (symlink
    120000, submodule 160000) makes the entry non-text. Raises ValueError or UnicodeError on output it cannot read
    (a non-UTF-8 path included); revision_changes() then shows the whole commit."""
    tokens, out, i = raw.split(b"\0"), [], 0
    while i < len(tokens):
        meta = tokens[i]
        if not meta.startswith(b":"):
            i += 1
            continue
        old_mode, new_mode, old_oid, new_oid, status = meta[1:].decode("ascii").split()
        n = 2 if status[:1] in ("R", "C") else 1
        names = [t.decode("utf-8") for t in tokens[i + 1:i + 1 + n]]
        if len(names) != n:
            raise ValueError("truncated raw entry")
        i += 1 + n
        old_path = None if status[:1] == "A" else names[0]
        new_path = None if status[:1] == "D" else names[-1]
        modes = ("" if old_path is None else old_mode, "" if new_path is None else new_mode)
        text = all(m in _TEXT_MODES for m in modes if m)
        out.append(RawEntry(old_path, new_path, old_oid, new_oid, modes, text))
    return out


def valid_changes(v: object) -> bool:
    """Whether v has the stored shape of `changes` - a list of {file: str, lo: int, hi: int}. server.valid_rec() treats
    a record failing this as a broken line; recorded_changes() skips such items."""
    return isinstance(v, list) and all(isinstance(c, dict) and isinstance(c.get("file"), str) and _is_int(c.get("lo"))
                                       and _is_int(c.get("hi")) for c in v)


def _is_int(v: object) -> bool:
    """An int that is not a bool - how a JSON integer arrives from json.loads."""
    return isinstance(v, int) and not isinstance(v, bool)
