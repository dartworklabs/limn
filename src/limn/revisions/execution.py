"""Comparison snapshot, sandbox, and PDF execution for one revision spec."""

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from limn.pins import ScopeRefusal, ScopeUnwritable, UnsafePath, plan_scope_writes
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


def parse_ls_tree_row(row: bytes, prefix: str) -> TreeFile | UnsafeTreeRow:
    """One row of `git ls-tree -r -l -z` (the text between two NULs: "<mode> <type> <oid> <size>\\t<name>") read as a
    file under the build root prefix ("" for the repository root, else "<folder>/"), or UnsafeTreeRow. Pure: it only
    looks at the bytes; the name is UTF-8 and the object id ASCII, as git writes them."""
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
        mode not in (b"100644", b"100755")
        or kind != b"blob"
        or path.is_absolute()
        or not name
        or any(p in (".", "..", ".git") for p in name.split("/"))
        or "\\" in name
        or any(ord(c) < 32 for c in name)
    ):
        return UnsafeTreeRow()
    try:
        return TreeFile(path, oid_text, int(size))
    except ValueError:
        return UnsafeTreeRow()


def revision_snapshot(spec: RevisionSpec, commit: str, dest: Path) -> None | StepFailed:
    """Write the build root of commit (spec.source) into the new folder dest from git objects - regular files only,
    within the file-count and size limits - and check that spec.main is there. The step failure otherwise."""
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
    total = 0
    for row in tree.split(b"\0"):
        if not row:
            continue
        entry = parse_ls_tree_row(row, prefix)
        if isinstance(entry, UnsafeTreeRow):
            return StepFailed("unsafe_snapshot")
        total += entry.size
        entries.append(entry)
        if entry.size > REVISION_FILE_MAX or total > REVISION_TREE_MAX or len(entries) > REVISION_FILES_MAX:
            return StepFailed("snapshot_size")
    dest.mkdir(parents=True)
    deadline = time.monotonic() + 60
    for entry in entries:
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
    if not (dest / spec.main).is_file():
        return StepFailed("missing_main")
    return None


def revision_apply_scope(spec: RevisionSpec, dest: Path) -> None | ScopeRefusal:
    """Turns dest (a fresh snapshot of the old side) into old + only spec.scope's blocks: re-reads the commit from git
    (deterministic for two SHA-1s), lets limn.pins.changes.plan_scope_writes() decide, and writes or removes those files under
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


def revision_compile(spec: RevisionSpec, jobdir: Path, timeout: int) -> ComparisonBuilt | BuildFailure:
    """Builds the comparison PDF of spec into jobdir/revision.pdf (and jobdir/build.log) inside the bwrap sandbox:
    snapshots of both sides - for a pin scope, old + only its blocks (revision_apply_scope) - then latexdiff, then
    latexmk with timeout seconds. Returns ComparisonBuilt with the warnings to show, or the first step that failed (a
    StepFailed as before 0.3, or a ScopeRefusal from the scope step); the worker records either."""
    warnings = [
        "수식 내부와 같은 파일명의 그림 내용 변경은 강조되지 않을 수 있습니다. 그림·서지·스타일 변경은 소스 변경사항도 확인하세요."
    ]
    with tempfile.TemporaryDirectory(prefix="work-", dir=jobdir) as tmp:
        work = Path(tmp)
        failed: BuildFailure | None = revision_snapshot(spec, spec.base, work / "old")
        if failed is None:
            if spec.scope:  # v0.3: the new side is old + only the pin's blocks
                failed = revision_snapshot(spec, spec.base, work / "new") or revision_apply_scope(spec, work / "new")
            else:
                failed = revision_snapshot(spec, spec.head, work / "new")
        if failed is not None:
            return failed
        main = spec.main.as_posix()
        head_label = spec.head[:8] + ("+scoped" if spec.scope else "")
        args = [
            "--encoding=utf8",
            "--flatten",
            "--math-markup=off",
            "--add-to-config",
            "ARRENV=tabularx;tabular;tabular[*]",
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
        if rc != 0 or b"\\begin{document}" not in diff or "Could not find" in log:
            atomic_write(jobdir / "build.log", log[-8000:])
            return StepFailed("diff_failed")
        if not re.search(rb"\\DIF(?:add|del)(?:begin|\{)", diff.split(b"\\begin{document}", 1)[1]):
            warnings.append("본문에 강조할 문장 차이가 없습니다. 서지·스타일 또는 주석만 바뀌었을 수 있습니다.")
        out = work / "new" / spec.main.parent
        # Tracked artifacts must never satisfy the fresh-PDF check or influence latexmk.
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
        atomic_write(jobdir / "build.log", log[-8000:])
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
        warnings += list(dict.fromkeys(warning_lines))[:12]
        os.replace(pdf, jobdir / "revision.pdf")
    return ComparisonBuilt(warnings)
