"""Manuscript copy, LaTeX compilation and PDF page rendering for one build."""

import contextlib
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from limn.builds import artifacts as build
from limn.builds.artifacts import (
    BUILD_EXCLUDE_DIRS,
    PAGES_DIR_RE,
    BuildAborted,
    BuildBusy,
    BuildConfig,
    BuildDoc,
    BuildFailed,
    BuildOk,
    BuildOkWithErrors,
    BuildStarted,
    CopyFailed,
    Doc,
    FinishedBuild,
    Json,
    ManuscriptCopyError,
    OutputFailureKind,
    PagesNotRendered,
)
from limn.platform.files import atomic_write
from limn.platform.git import run_git


def latex_errors(text: str) -> list[dict[str, Any]]:
    """Pulls out up to 5 '! ' lines and the first following 'l.<n>' line each (no file guessing)."""
    out: list[dict[str, Any]] = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if not ln.startswith("! "):
            continue
        line_no = None
        for nxt in lines[i + 1 : i + 40]:
            m = re.match(r"l\.(\d+)", nxt)
            if m:
                line_no = int(m.group(1))
                break
            if nxt.startswith("! "):
                break
        out.append({"line": line_no, "msg": ln[2:].strip()[:200]})
        if len(out) >= 5:
            break
    return out


def run_logged(cmd: list[str], cwd: Path, timeout: int) -> tuple[int | None, str, bool]:
    """Runs the whole process group, and kills the whole group on timeout (including pdflatex spawned by latexmk).

    Returns (returncode or None, combined output, timed out)."""
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
    except FileNotFoundError:
        return None, "%s 를 찾지 못했습니다." % cmd[0], False
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or "", False
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(p.pid, signal.SIGKILL)
        out, _ = p.communicate()
        return None, (out or "") + "\n[시간 초과 %d초 — 빌드를 중단했습니다]" % timeout, True


def _rsync_literal(name: str) -> str:
    """name as an rsync pattern that matches only itself: rsync reads a backslash as an escape only in a pattern that
    holds a wildcard (*, ?, [), so a name with one gets every wildcard and backslash escaped, and any other name is
    already literal."""
    if not any(c in name for c in "*?["):
        return name
    return re.sub(r"([*?\[\\])", r"\\\1", name)


def copy_manuscript(src: Path, dest: Path, state: Path) -> None:
    """Mirror the manuscript folder into the build folder, skipping BUILD_EXCLUDE_DIRS, *.synctex.gz and the state
    folder `state` when --state-dir puts it inside src (state_in_source).

    The state folder holds people.json, tokens.json (hashes), audit.jsonl and events.jsonl - not manuscript - and
    usually the build folder itself, which a copy would nest one level deeper on every build.
    Uses rsync -a --delete when it is installed, otherwise replaces dest with a fresh tree copy.
    Raises ManuscriptCopyError when the copy cannot be trusted: rsync exits non-zero (a partial
    transfer exits 23 and skips --delete, leaving removed files behind), times out, or the copy hits
    an OS error. The caller must not compile dest after that.
    """
    rs = shutil.which("rsync")
    held = build.state_in_source(src, state)
    try:
        if rs:
            excl = []
            for d in BUILD_EXCLUDE_DIRS:
                excl += ["--exclude", d + "/"]
            if held is not None:  # anchored at the transfer root: only that folder, never a same-named one elsewhere
                excl += ["--exclude", "/" + "/".join(_rsync_literal(part) for part in held) + "/"]
            r = subprocess.run(
                [rs, "-a", "--delete"] + excl + ["--exclude", "*.synctex.gz", str(src) + "/", str(dest) + "/"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=300,
                check=False,
            )
            if r.returncode != 0:
                last = (r.stderr.strip().splitlines() or ["(no message)"])[-1]
                raise ManuscriptCopyError("rsync exit %d: %s" % (r.returncode, last))
        else:  # must still work without rsync
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(src, dest, ignore=_copy_ignore(src, held))
    except (subprocess.TimeoutExpired, OSError) as e:
        raise ManuscriptCopyError(str(e)) from e


def _copy_ignore(src: Path, held: tuple[str, ...] | None) -> Callable[[str, list[str]], set[str]]:
    """shutil.copytree's ignore for copy_manuscript without rsync: BUILD_EXCLUDE_DIRS and *.synctex.gz by name, and the
    state folder `held` (its parts below src, state_in_source) at that one place. Folders are compared with symlinks
    resolved, as held is: copytree follows a linked folder, so a link into the state folder copies nothing of it."""
    by_name = shutil.ignore_patterns(*BUILD_EXCLUDE_DIRS, "*.synctex.gz")
    base = os.path.realpath(src)

    def ignore(folder: str, names: list[str]) -> set[str]:
        """The names of folder to skip."""
        out = set(by_name(folder, names))
        if held is not None:
            rel = Path(os.path.relpath(os.path.realpath(folder), base)).parts
            here = () if rel == (".",) else rel
            if here[: len(held)] == held:
                return set(names)
            if here == held[:-1] and held[-1] in names:
                out.add(held[-1])
        return out

    return ignore


def compile_tex(D: BuildDoc, cfg: BuildConfig, pull: Callable[[], Json] | None) -> FinishedBuild:
    """Builds D with -synctex=1 from a copy, leaving the original untouched, then renders pages into a new directory and only swaps the pointer.

    pull is the --git-pull step (None when the flag is off); its record is the outcome's pull. Outcomes: CopyFailed
    (the copy could not be trusted, nothing compiled), BuildFailed (no new PDF, a timeout, no SyncTeX, or the pages
    could not be rendered - the screen keeps the old PDF), BuildOkWithErrors (a new PDF with LaTeX errors, '! '
    lines) and BuildOk (no errors). Each carries what the build got as far as: the pull, the manuscript mtime it
    compiled, the copy's fingerprint, latexmk's last lines, and for a success the new page directory.

    The files another document owns (D.apart) are left out of the manuscript mtime and the fingerprint unless the build
    read them. Which it read is only known once latexmk has run, from the .fls it records in the copy: the fingerprint
    hashes the whole copy before latexmk and chooses afterwards, and the mtime takes in the newest file the build read.
    The .fls is published with the pages (next to the .synctex.gz and .aux), where the later queries find it."""
    t0 = time.time()
    D.build.mkdir(parents=True, exist_ok=True)
    pulled: Json | None = None

    # --git-pull fast-forwards to remote main before the copy step (docs/handbook/build-sync.md §pull 단계).
    if pull is not None:
        build.state_update(D, phase="pull")
        pulled = pull()
        build.state_update(D, phase="copy")
    # mtime of the manuscript this build will actually compile - after the pull if there was one (a
    # fast-forward can bump the .tex mtime), otherwise measured now (right before the copy). run_tracked()
    # commits this value to built_src_mtime/history - using the build start time (before the pull) instead
    # caused the new mtime from the pull to be misread as "not built yet", leaving the "manuscript modified"
    # badge on even right after a success.
    compiled_at = build.src_mtime(D, cfg.state, force=True)

    try:
        copy_manuscript(D.src, D.build, cfg.state)
    except ManuscriptCopyError as e:
        return CopyFailed(str(e), round(time.time() - t0, 1), pulled, compiled_at)
    # The hashes are taken from the copy - these are exactly the files this build actually compiles (the original can still
    # change meanwhile). The files another document owns are hashed too, because which of them the build reads is only
    # known after latexmk; the fingerprint is chosen from them below.
    digests: dict[str, bytes] | None
    try:
        digests = build.source_digests(D, D.build, cfg.state, keep_apart=True)
    except OSError:
        digests = None

    build.state_update(D, phase="latex")
    # A single document runs in the build root as before; a --doc document runs in the folder holding its main .tex (Doc.out).
    _rc, out, timed_out = run_logged(
        ["latexmk", "-pdf", "-synctex=1", "-interaction=nonstopmode", D.main.name], D.out, cfg.timeout
    )
    with contextlib.suppress(OSError):
        atomic_write(D.dir / "build.log", out)
    tail = "\n".join(out.splitlines()[-40:])[-4000:]

    pdf = D.out / (D.main.stem + ".pdf")
    syn = D.out / (D.main.stem + ".synctex.gz")
    texlog = D.out / (D.main.stem + ".log")
    try:
        logtxt = (
            texlog.read_text(encoding="utf-8", errors="replace")
            if texlog.exists() and texlog.stat().st_mtime >= t0 - 1
            else out
        )
    except OSError:
        logtxt = out
    errors = latex_errors(logtxt)

    # What this run read: the figure-set files of another document that the manuscript uses count as part of it.
    recorder = D.out / (D.main.stem + ".fls")
    reads = build.recorded_inputs(D, recorder) if not D.apart.empty else frozenset()
    compiled_at = max(compiled_at, build.newest_read_apart(D, D.build, reads))
    src_hash = None if digests is None else build.fingerprint_of(build.without_apart(D, digests, reads))

    def failed(kind: OutputFailureKind, detail: str = "") -> BuildFailed:
        """This build's failure of `kind`, with latexmk's last lines and what it compiled."""
        return BuildFailed(kind, detail, tail, errors, round(time.time() - t0, 1), pulled, compiled_at, src_hash)

    fresh = (not timed_out) and pdf.exists() and pdf.stat().st_mtime >= t0 - 1
    if not fresh:
        return failed("timeout" if timed_out else "no_pdf")
    if not syn.exists() or syn.stat().st_mtime < t0 - 1:
        return failed("no_synctex")

    extra = [syn]
    aux = D.out / (D.main.stem + ".aux")
    if aux.is_file() and aux.stat().st_mtime >= t0 - 1:
        extra.append(aux)
    if recorder.is_file() and not recorder.is_symlink() and recorder.stat().st_mtime >= t0 - 1:
        extra.append(recorder)  # what this build read, kept with its pages (build.build_inputs reads it back)
    newdir = render_pages(D, pdf, extra, cfg.dpi)
    if isinstance(newdir, PagesNotRendered):
        return failed(newdir.kind, newdir.detail)
    head_short = commit_pages(D, newdir)
    pages = len(list(newdir.glob("page-*.png")))
    elapsed_s = round(time.time() - t0, 1)
    if errors:
        return BuildOkWithErrors(errors, tail, elapsed_s, pulled, compiled_at, src_hash, head_short, newdir.name, pages)
    return BuildOk(tail, elapsed_s, pulled, compiled_at, src_hash, head_short, newdir.name, pages)


def render_pages(D: BuildDoc, pdf: Path, extra: list[Path], dpi: int) -> Path | PagesNotRendered:
    """Renders pages into a new directory and drops in a copy of the PDF (and extra - synctex). The screen keeps
    showing the old directory until this finishes. Returns the new directory, or why there is none (the half-made
    directory is removed)."""
    D.dir.mkdir(parents=True, exist_ok=True)
    bid = time.strftime("%Y%m%d%H%M%S")
    name = "pages-" + bid
    k = 1
    while (D.dir / name).exists():
        name = "pages-%s-%d" % (bid, k)
        k += 1
    newdir = D.dir / name
    newdir.mkdir(parents=True)
    build.state_update(D, phase="render")
    try:
        r = subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(newdir / "page")],
            capture_output=True,
            timeout=600,
            check=False,
        )
        ok_render = r.returncode == 0 and any(newdir.glob("page-*.png"))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        ok_render = False
    if not ok_render:
        shutil.rmtree(newdir, ignore_errors=True)
        return PagesNotRendered("render", "")
    try:
        shutil.copy2(pdf, newdir / D.pdf_name)
        for f in extra:
            shutil.copy2(f, newdir / f.name)
    except OSError as e:
        shutil.rmtree(newdir, ignore_errors=True)
        return PagesNotRendered("pdf_copy", str(e))
    return newdir


def commit_pages(D: BuildDoc, newdir: Path) -> str:
    """Swaps the pointer to the new page directory in one shot (atomically), keeps only current+previous, and writes built_at/head. head is the short hash."""
    prev = build.cur_pages(D).name
    atomic_write(D.dir / "pages.cur", newdir.name)  # a single atomic swap
    for d in D.dir.iterdir():  # keep only current and previous
        if d.is_dir() and PAGES_DIR_RE.fullmatch(d.name) and d.name not in (newdir.name, prev):
            shutil.rmtree(d, ignore_errors=True)
    atomic_write(D.dir / "built_at.txt", datetime.now().astimezone().isoformat(timespec="seconds"))
    try:
        head = run_git(["-C", str(D.src), "rev-parse", "--short", "HEAD"], D.src, 10)
        head_short = head.stdout.strip() or "-"
    except (OSError, subprocess.SubprocessError):
        head_short = "-"
    atomic_write(D.dir / "head.txt", head_short)
    return head_short


# ---------------------------------------------------------------- View-only PDF documents
#
# A PDF with no LaTeX source (reviewer comments, etc.) has no rebuild. Instead, when that PDF file changes
# (mtime/size), the page images are re-rendered - since it goes through the same tracked build (run_tracked ->
# history/build_seq), the viewer updates the screen exactly as it would for a LaTeX rebuild.


def pdf_signature(D: BuildDoc) -> str | None:
    """ "<mtime_ns>:<size>" of view-only document D's PDF, or None when it cannot be read (missing)."""
    try:
        st = D.main.stat()
        return "%d:%d" % (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def render_pdf_doc(D: BuildDoc, cfg: BuildConfig) -> BuildOk | BuildFailed | BuildAborted:
    """The 'build' of view-only document D - renders its PDF into page images at cfg.dpi. No LaTeX, SyncTeX, or pull.
    The PDF's signature is recorded (pdf_sig.txt) after a render, successful or not, so a PDF that fails to render is
    retried only when the file changes, never on every poll. A missing PDF is BuildAborted pdf_missing naming it."""
    t0 = time.time()
    sig = pdf_signature(D)
    if sig is None:
        return BuildAborted("pdf_missing", str(D.main))
    src_hash: str | None
    try:
        src_hash = build.doc_fingerprint(D, cfg.state)
    except OSError:
        src_hash = None
    newdir = render_pages(D, D.main, [], cfg.dpi)
    if isinstance(newdir, PagesNotRendered):
        failed = BuildFailed(newdir.kind, newdir.detail, None, [], round(time.time() - t0, 1), None, None, src_hash)
        # never retries the same file every 3 seconds - re-renders only when the file changes
        with contextlib.suppress(OSError):
            atomic_write(D.dir / "pdf_sig.txt", sig)
        return failed
    head = commit_pages(D, newdir)
    with contextlib.suppress(OSError):
        atomic_write(D.dir / "pdf_sig.txt", sig)
    return BuildOk(
        "", round(time.time() - t0, 1), None, None, src_hash, head, newdir.name, len(list(newdir.glob("page-*.png")))
    )


def pdf_changed(D: BuildDoc) -> bool:
    """Has view-only document D's PDF changed since its page images were last rendered (or have they never been
    rendered)? False when the PDF is missing - there is nothing to render."""
    sig = pdf_signature(D)
    if sig is None:
        return False
    try:
        done = (D.dir / "pdf_sig.txt").read_text().strip()
    except OSError:
        done = ""
    return sig != done


def refresh_pdf_doc(D: Doc, start: Callable[[Doc], BuildStarted | BuildBusy]) -> bool:
    """If watched document D's PDF changed (pdf_changed), start its tracked re-render with `start` (the composition
    root's background build). True when a render started; False for a document the watch does not follow (not
    D.watches_files), an unchanged or missing PDF, or a render already running (start answered BuildBusy)."""
    if not D.watches_files or not pdf_changed(D):
        return False
    return isinstance(start(D), BuildStarted)
