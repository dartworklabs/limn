"""Comparison snapshot, sandbox, and PDF execution for one revision spec."""

import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from itertools import chain
from pathlib import Path

from limn.platform.files import atomic_write
from limn.revisions import core
from limn.revisions.core import (
    REVISION_FILE_MAX,
    REVISION_FILES_MAX,
    REVISION_PDF_MAX,
    REVISION_TREE_MAX,
    BuildFailure,
    ComparisonBuilt,
    RevisionSpec,
    StepFailed,
)
from limn.revisions.macros import PREAMBLE_MAX, text_macros
from limn.revisions.scope import ScopeRefusal, ScopeUnwritable, UnsafePath, plan_scope_writes

TEXT_COMMANDS_FILE = "textcmd.txt"  # in a job's work folder, beside the old/ and new/ snapshots
# What a TeX build reads only when something names it: finished PDFs and pictures. A build root past the limits has those no
# other file names stand as blank files (revision_snapshot) - a manuscript folder that keeps its past comparison PDFs holds
# 350 MB of them beside 6 MB it builds from.
REVISION_NAMED_FILES = frozenset(
    (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps", ".mps", ".svg", ".gif", ".tif", ".tiff", ".webp")
)
# A word of a source file that can be a file's name: \includegraphics[width=2cm]{images/fig1.pdf} has images and fig1.pdf.
NAME_EDGES = rb"\s{}\[\]()<>,;:=%\"'`|\\/"
NAME_WORD = re.compile(rb"[^" + NAME_EDGES + rb"]+")
NAME_EDGE = re.compile(rb"[" + NAME_EDGES + rb"]")
COMPARISON_NOTE = "수식 내부와 같은 파일명의 그림 내용 변경은 강조되지 않을 수 있습니다. 그림·서지·스타일 변경은 소스 변경사항도 확인하세요."
# Issue #162: the run with the document's text commands did not build, so the comparison shown is plain latexdiff's.
TEXT_COMMANDS_FALLBACK_NOTE = (
    "원고가 정의한 명령 안까지 강조한 비교가 만들어지지 않아, 그 명령 안의 변경은 강조하지 않고 비교했습니다."
)
TEXT_COMMANDS_FALLBACK_LOG = (
    "limn: the run with the document's text commands (--append-textcmd) did not build; this is plain latexdiff's.\n"
)


@dataclass(frozen=True)
class TreeFile:
    """One regular file of a commit's build root as `git ls-tree -r -l -z` lists it: its path relative to the build
    root (relative, no ".", ".." or ".git" part, no backslash or control character), its blob id and its size in
    bytes."""

    path: Path
    oid: str
    size: int


@dataclass(frozen=True)
class UnsafeTreeRow:
    """An ls-tree row a snapshot never writes: not a regular file (a symlink, a submodule), outside the build root, a
    name that could leave or confuse the snapshot folder, or a row that does not parse. The snapshot is refused
    (StepFailed("unsafe_snapshot"))."""


@dataclass(frozen=True)
class DotNamedRow:
    """An ls-tree row under a dot-named part of the build root (.private/notes.tex, a/.old/refs.bib, .draft.tex): never
    the manuscript (limn.platform.files.tree_part, the history's pathspec, limn.revisions.core.dot_excludes), so a
    snapshot neither reads its blob nor writes it, whatever it is."""


def parse_ls_tree_row(row: bytes, prefix: str) -> TreeFile | UnsafeTreeRow | DotNamedRow:
    """One row of `git ls-tree -r -l -z` (the text between two NULs: "<mode> <type> <oid> <size>\\t<name>") read as a
    file under the build root prefix ("" for the repository root, else "<folder>/"), DotNamedRow for one with a
    dot-named part below the build root (a name that could leave or confuse the snapshot folder is still UnsafeTreeRow),
    or UnsafeTreeRow. Pure: it only looks at the bytes; the name is UTF-8 and the object id ASCII, as git writes them."""
    meta, tab, rawname = row.partition(b"\t")
    fields = meta.split()
    if not tab or len(fields) != 4:
        return UnsafeTreeRow()
    mode, kind, oid, size = fields
    try:
        name = rawname.decode("utf-8")
        oid_text = oid.decode("ascii")
    except UnicodeError:
        return UnsafeTreeRow()
    if not name.startswith(prefix):
        return UnsafeTreeRow()
    name = name[len(prefix) :]
    path = Path(name)
    if (
        path.is_absolute()
        or not name
        or any(p in (".", "..", ".git") for p in name.split("/"))
        or "\\" in name
        or any(ord(c) < 32 for c in name)
    ):
        return UnsafeTreeRow()
    if core.dot_named(name):
        return DotNamedRow()
    if mode not in (b"100644", b"100755") or kind != b"blob":
        return UnsafeTreeRow()
    try:
        return TreeFile(path, oid_text, int(size))
    except ValueError:
        return UnsafeTreeRow()


def snapshot_over_limits(entries: list[TreeFile]) -> bool:
    """Whether a snapshot of these files is past a file's size or the whole's."""
    return sum(e.size for e in entries) > REVISION_TREE_MAX or any(e.size > REVISION_FILE_MAX for e in entries)


def names_found(data: bytes, wanted: set[bytes], deadline: float) -> set[bytes] | StepFailed:
    """Which of the wanted names are words of a source file, none for a binary file. Holds no more than those: a source
    is the repository's, and its words could be any number."""
    found: set[bytes] = set()
    if b"\0" in data:
        return found
    for i, word in enumerate(NAME_WORD.finditer(data)):
        if not i & 0xFFFF and time.monotonic() >= deadline:
            return StepFailed("snapshot_timeout")
        if word.group() in wanted:
            found.add(word.group())
    return found


def side_sources(dest: Path) -> Iterator[bytes]:
    """The files of a written snapshot that are read for names."""
    for path in dest.rglob("*"):
        if path.is_file() and path.suffix.lower() not in REVISION_NAMED_FILES:
            yield path.read_bytes()


def scope_sources(spec: RevisionSpec) -> list[bytes]:
    """The text a pin's blocks write over the old side (revision_apply_scope), which may name what the old text does not."""
    writes = plan_scope_writes(
        core.revision_changes(spec.repo, spec.base, spec.head, spec.paths), spec.scope, spec.source
    )
    return [w.data for w in writes if w.data is not None] if isinstance(writes, list) else []


def write_tree_file(spec: RevisionSpec, entry: TreeFile, dest: Path, deadline: float) -> bytes | StepFailed:
    """Writes one file of a snapshot under dest from git objects, within deadline: its bytes, or the step failure."""
    if time.monotonic() >= deadline:
        return StepFailed("snapshot_timeout")
    ran = core.git_exec(
        ["cat-file", "blob", entry.oid],
        spec.repo,
        min(15, max(0.01, deadline - time.monotonic())),
        entry.size + 4096,
    )
    if isinstance(ran, StepFailed):
        return ran
    rc, data, _ = ran
    if rc != 0 or len(data) != entry.size:
        return StepFailed("snapshot_blob")
    target = dest / entry.path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


def revision_snapshot(spec: RevisionSpec, commit: str, dest: Path, also: Iterable[bytes] = ()) -> None | StepFailed:
    """Write the build root of commit (spec.source) into the new folder dest from git objects - regular files only,
    within the file-count and size limits - and check that spec.main is there. The step failure otherwise. A file under
    a dot-named part of the build root (DotNamedRow) is left out before any blob is read: it is no document's history,
    so neither side of a comparison - nor the latexdiff and latexmk runs over them - ever holds its text.

    A build root past the size limits has the REVISION_NAMED_FILES that nothing names stand as blank files, and is refused
    if it is still past them. What names one is the other files of the build root and the sources in also (the other side
    of the comparison, a pin's blocks). A build root within the limits is written whole, as a name found here is a guess:
    a blank file is sparse, the real one's size in zeros on no disk, so \\IfFileExists and \\pdffilesize answer as for the
    real one, and reading it fails the build (no reader of pictures takes zeros, and TeX refuses a NUL), so a picture named
    by a macro (fig\\thepage) ends in compile_failed, not in a wrong PDF."""
    prefix = "" if spec.source == "." else spec.source + "/"
    cmd = ["ls-tree", "-r", "-l", "-z", commit]
    if prefix:
        cmd += ["--", ":(literal)" + spec.source]
    ran = core.git_exec(cmd, spec.repo, 30, 2 * 1024 * 1024)
    if isinstance(ran, StepFailed):
        return ran
    rc, tree, _ = ran
    if rc != 0:
        return StepFailed("snapshot_read")
    entries: list[TreeFile] = []
    for row in tree.split(b"\0"):
        if not row:
            continue
        entry = parse_ls_tree_row(row, prefix)
        if isinstance(entry, DotNamedRow):
            continue
        if isinstance(entry, UnsafeTreeRow):
            return StepFailed("unsafe_snapshot")
        entries.append(entry)
    if len(entries) > REVISION_FILES_MAX:
        return StepFailed("snapshot_size")
    held: list[TreeFile] = []
    if snapshot_over_limits(entries):
        held = [e for e in entries if e.path.suffix.lower() in REVISION_NAMED_FILES]
        entries = [e for e in entries if e.path.suffix.lower() not in REVISION_NAMED_FILES]
        if snapshot_over_limits(entries):
            return StepFailed("snapshot_size")
    wanted = {n for e in held for n in (e.path.name.encode(), e.path.stem.encode())}
    found: set[bytes] = set()
    dest.mkdir(parents=True)
    deadline = time.monotonic() + 60
    for entry in entries:
        data = write_tree_file(spec, entry, dest, deadline)
        if isinstance(data, StepFailed):
            return data
        names = names_found(data, wanted, deadline) if held else found
        if isinstance(names, StepFailed):
            return names
        found |= names
    for data in also if held else ():
        names = names_found(data, wanted, deadline)
        if isinstance(names, StepFailed):
            return names
        found |= names
    needed = [
        e
        for e in held
        if NAME_EDGE.search(e.path.name.encode()) or e.path.name.encode() in found or e.path.stem.encode() in found
    ]
    if snapshot_over_limits(entries + needed):
        return StepFailed("snapshot_size")
    for entry in needed:
        data = write_tree_file(spec, entry, dest, deadline)
        if isinstance(data, StepFailed):
            return data
    for entry in held:
        target = dest / entry.path
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as blank:
                blank.truncate(entry.size)
    if not (dest / spec.main).is_file():
        return StepFailed("missing_main")
    return None


def revision_apply_scope(spec: RevisionSpec, dest: Path) -> None | ScopeRefusal:
    """Turns dest (a fresh snapshot of the old side) into old + only spec.scope's blocks: re-reads the commit from git
    (deterministic for two SHA-1s), lets revisions.scope.plan_scope_writes() decide, and writes or removes those files under
    dest. Refused as ScopeUnreadable, ScopeMismatch, UnsafePath (also for a symlink or a parent outside dest) or
    ScopeUnwritable (an OSError while writing); the build worker records it like any other failure, and a pin's
    scope_failed is answered from the cache next time."""
    writes = plan_scope_writes(
        core.revision_changes(spec.repo, spec.base, spec.head, spec.paths), spec.scope, spec.source
    )
    if not isinstance(writes, list):
        return writes
    for w in writes:
        target = dest / w.rel
        if target.is_symlink() or not target.parent.resolve().is_relative_to(dest.resolve()):
            return UnsafePath()
        try:
            if w.data is None:
                if target.is_file():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(w.data)
        except OSError:
            return ScopeUnwritable()
    return None


def revision_text_commands(
    work: Path, main: Path, text_commands_of: Callable[[str], tuple[str, ...]] = text_macros
) -> list[str]:
    """The latexdiff arguments that mark changes inside the commands the new side's main file defines as text
    (text_commands_of, by default limn.revisions.macros.text_macros): ["--append-textcmd=/work/textcmd.txt"] after writing their names, one per
    line, to work/textcmd.txt - outside both snapshots, so neither the diff nor the build sees it - or [] when there
    are none or the main file cannot be read. latexdiff takes the new side's preamble, so the old side's definitions
    do not count. Reads at most PREAMBLE_MAX bytes of work/new/main; a name list is never passed inline, because
    latexdiff reads an existing file of that name instead."""
    try:
        with (work / "new" / main).open("rb") as f:
            head = f.read(PREAMBLE_MAX)
    except OSError:
        return []
    names = text_commands_of(head.decode("utf-8", errors="replace"))
    if not names:
        return []
    (work / TEXT_COMMANDS_FILE).write_text("".join(name + "\n" for name in names), encoding="ascii")
    return ["--append-textcmd=/work/" + TEXT_COMMANDS_FILE]


def revision_sandbox(work: Path, main_parent: Path, tool: str, args: list[str]) -> list[str] | StepFailed:
    """The bwrap command that runs tool (latexdiff or latexmk) on work: only the TeX installation and throwaway
    snapshots are visible; no host home or network. A missing sandbox or tool, or one outside /usr, is a step failure;
    any other tool is a programming error (ValueError)."""
    if tool not in ("latexdiff", "latexmk"):
        raise ValueError("unsupported revision tool")
    bwrap, found = shutil.which("bwrap"), shutil.which(tool)
    if not bwrap or not found:
        return StepFailed("sandbox_tools")
    exe = Path(found).resolve()
    if not exe.is_relative_to(Path("/usr")):
        return StepFailed("sandbox_system")
    cmd = [bwrap, "--unshare-all", "--die-with-parent", "--clearenv"]
    for path in (
        "/usr",
        "/bin",
        "/lib",
        "/lib64",
        "/etc/alternatives",  # Debian's /usr/bin/bibtex and others are links through it, dangling without it
        "/etc/fonts",
        "/etc/texmf",
        "/var/lib/texmf",
        "/var/cache/fontconfig",
    ):
        if Path(path).exists():
            cmd += ["--ro-bind", path, path]
    cmd += [
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--bind",
        str(work),
        "/work",
        "--chdir",
        "/work/new/" + main_parent.as_posix(),
    ]
    # latexmk invokes the engine by name; use the installation's public binary directory,
    # not a symlink-resolved Perl script directory.
    texbin = str(Path(shutil.which("latexmk") or "/usr/bin/latexmk").parent)
    for key, value in {
        "PATH": texbin + ":/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "TEXMFVAR": "/tmp/texmf-var",
        "TEXMFCONFIG": "/tmp/texmf-config",
        "openin_any": "p",
        "openout_any": "p",
    }.items():
        cmd += ["--setenv", key, value]
    return cmd + ["--", str(exe)] + args


def revision_compile(
    spec: RevisionSpec, jobdir: Path, timeout: int, text_commands_of: Callable[[str], tuple[str, ...]] = text_macros
) -> ComparisonBuilt | BuildFailure:
    """Builds the comparison PDF of spec into jobdir/revision.pdf (and jobdir/build.log) inside the bwrap sandbox:
    snapshots of both sides - for a pin scope, old + only its blocks (revision_apply_scope) - then latexdiff, told the
    commands text_commands_of finds in the new side's main file (revision_text_commands; the parameter is the seam
    tests use to force a list), then latexmk with timeout seconds (_diff_and_build). When a run with a list ends in
    diff_failed or compile_failed, it is built once more with plain latexdiff, and a success says so in its warnings
    (TEXT_COMMANDS_FALLBACK_NOTE) and build log (TEXT_COMMANDS_FALLBACK_LOG). Returns ComparisonBuilt with the warnings
    to show, or the first step that failed (a StepFailed as before 0.3 - after a fallback, the plain run's - or a
    ScopeRefusal from the scope step); the worker records either."""
    with tempfile.TemporaryDirectory(prefix="work-", dir=jobdir) as tmp:
        work = Path(tmp)
        failed: BuildFailure | None = revision_snapshot(spec, spec.base, work / "old")
        if failed is None:
            old = side_sources(work / "old")  # latexdiff can carry its words into the new side, the pictures they name
            if spec.scope:  # v0.3: the new side is old + only the pin's blocks
                failed = revision_snapshot(
                    spec, spec.base, work / "new", chain(old, scope_sources(spec))
                ) or revision_apply_scope(spec, work / "new")
            else:
                failed = revision_snapshot(spec, spec.head, work / "new", old)
        if failed is not None:
            return failed
        text_commands = revision_text_commands(work, spec.main, text_commands_of)
        built = _diff_and_build(spec, work, jobdir, timeout, text_commands, "")
        if text_commands and isinstance(built, StepFailed) and built.kind in ("diff_failed", "compile_failed"):
            # A comparison that built before issue #162 must not stop building because of the list: a macro judged
            # text whose argument is not costs only the markup inside macros. Once, and only after a run with a list
            # (without one the run was already plain). The answer is cached like any other: a ready one is served
            # from the cache, so later requests never repeat the failing run. Only when the plain run fails too is a
            # failure stored, and a whole commit's failure is built again on the next POST by design (it may be
            # transient); that repeats one extra run for a comparison that does not build either way.
            built = _diff_and_build(spec, work, jobdir, timeout, [], TEXT_COMMANDS_FALLBACK_LOG)
            if not isinstance(built, StepFailed):
                built.insert(0, TEXT_COMMANDS_FALLBACK_NOTE)
    return built if isinstance(built, StepFailed) else ComparisonBuilt([COMPARISON_NOTE] + built)


def _diff_and_build(
    spec: RevisionSpec, work: Path, jobdir: Path, timeout: int, text_commands: list[str], log_note: str
) -> list[str] | StepFailed:
    """One latexdiff + latexmk run over the snapshots in work, with the extra latexdiff arguments text_commands. On
    success the PDF is moved to jobdir/revision.pdf and the notes to show after COMPARISON_NOTE are returned (no
    marked difference, then up to 12 warning lines of the final engine log); otherwise the step that failed. Either
    way a run that got to latexdiff leaves its log tail, after log_note, in jobdir/build.log. Removes the previous
    run's pin_revision.* files first, so a second run starts clean."""
    main = spec.main.as_posix()
    head_label = spec.head[:8] + ("+scoped" if spec.scope else "")
    args = [
        "--encoding=utf8",
        "--flatten",
        "--math-markup=off",
        "--add-to-config",
        "ARRENV=tabularx;tabular;tabular[*]",
        *text_commands,
        "--label",
        spec.base[:8],
        "--label",
        head_label,
        "/work/old/" + main,
        "/work/new/" + main,
    ]
    cmd = revision_sandbox(work, spec.main.parent, "latexdiff", args)
    if isinstance(cmd, StepFailed):
        return cmd
    ran = core.revision_exec(cmd, work, 60)
    if isinstance(ran, StepFailed):
        return ran
    rc, diff, err = ran
    log = err.decode("utf-8", errors="replace")
    keep = 8000 - len(log_note)
    if rc != 0 or b"\\begin{document}" not in diff or "Could not find" in log:
        atomic_write(jobdir / "build.log", log_note + log[-keep:])
        return StepFailed("diff_failed")
    notes = []
    if not re.search(rb"\\DIF(?:add|del)(?:begin|\{)", diff.split(b"\\begin{document}", 1)[1]):
        notes.append("본문에 강조할 문장 차이가 없습니다. 서지·스타일 또는 주석만 바뀌었을 수 있습니다.")
    out = work / "new" / spec.main.parent
    # Tracked artifacts (and a previous run's) must never satisfy the fresh-PDF check or influence latexmk.
    for stale in out.glob("pin_revision.*"):
        if stale.is_file():
            stale.unlink()
    (out / "pin_revision.tex").write_bytes(diff)
    args = ["-norc", "-pdf", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "pin_revision.tex"]
    cmd = revision_sandbox(work, spec.main.parent, "latexmk", args)
    if isinstance(cmd, StepFailed):
        return cmd
    ran = core.revision_exec(cmd, work, timeout)
    if isinstance(ran, StepFailed):
        return ran
    rc, stdout, stderr = ran
    log += (stdout + stderr).decode("utf-8", errors="replace")
    atomic_write(jobdir / "build.log", log_note + log[-keep:])
    pdf = out / "pin_revision.pdf"
    if rc != 0 or not pdf.is_file() or pdf.stat().st_size > REVISION_PDF_MAX:
        return StepFailed("compile_failed")
    if not pdf.read_bytes().startswith(b"%PDF-"):
        return StepFailed("invalid_pdf")
    # Earlier latexmk passes normally contain unresolved citations. Report the final
    # engine log only, otherwise a successful BibTeX pass looks like a broken PDF.
    final_log = out / "pin_revision.log"
    final_text = (
        final_log.read_text(encoding="utf-8", errors="replace")
        if final_log.is_file() and final_log.stat().st_size <= 8 * 1024 * 1024
        else log
    )
    warning_lines = [
        line.strip()
        for line in final_text.splitlines()
        if "Warning:" in line or "undefined" in line or "Missing character:" in line
    ]
    os.replace(pdf, jobdir / "revision.pdf")
    return notes + list(dict.fromkeys(warning_lines))[:12]
