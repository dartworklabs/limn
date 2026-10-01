"""Manuscript copy, LaTeX compilation and PDF page rendering for one build."""

import contextlib
import os
import re
import shutil
import signal
import stat
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from limn.builds import artifacts as build, png, warm
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
    BuildUnchanged,
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


def copy_manuscript(src: Path, dest: Path, state: Path, keep: tuple[str, ...] = ()) -> None:
    """Mirror the manuscript folder into the build folder, skipping BUILD_EXCLUDE_DIRS, *.synctex.gz and the state
    folder `state` when --state-dir puts it inside src (state_in_source).

    The state folder holds people.json, tokens.json (hashes), audit.jsonl and events.jsonl - not manuscript - and
    usually the build folder itself, which a copy would nest one level deeper on every build.
    keep are paths below dest (POSIX, limn.builds.warm.kept_paths) that the copy neither deletes nor overwrites: the
    last build's LaTeX byproducts and PDF, so latexmk runs warm, and a committed PDF of the same name never lands on the
    build's. Uses rsync -a --checksum --delete when it is installed (keep as anchored excludes; --checksum because a
    same-size edit within the second of the last copy passes rsync's size-and-mtime check, and the copy - now kept
    between builds - would keep the old text), otherwise rebuilds dest as a fresh tree copy around the kept files. Raises ManuscriptCopyError when the copy cannot be trusted: rsync exits non-zero
    (a partial transfer exits 23 and skips --delete, leaving removed files behind), times out, or the copy hits
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
            for rel in keep:  # anchored too: an excluded file is neither sent nor deleted
                excl += ["--exclude", "/" + "/".join(_rsync_literal(part) for part in rel.split("/"))]
            r = subprocess.run(
                [rs, "-a", "--checksum", "--delete"]
                + excl
                + ["--exclude", "*.synctex.gz", str(src) + "/", str(dest) + "/"],
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
            if dest.is_dir():
                _clear_except(dest, (), frozenset(keep))
            shutil.copytree(src, dest, ignore=_copy_ignore(src, held, frozenset(keep)), dirs_exist_ok=True)
    except (subprocess.TimeoutExpired, OSError) as e:
        raise ManuscriptCopyError(str(e)) from e


def _clear_except(folder: Path, rel: tuple[str, ...], keep: frozenset[str]) -> None:
    """Remove everything in folder (rel: its parts below the build copy) but the kept files (keep, POSIX paths below
    the build copy) and the folders that lead to them - the copy without rsync, before the fresh tree copy."""
    for entry in os.scandir(folder):
        parts = rel + (entry.name,)
        path = "/".join(parts)
        if entry.is_dir(follow_symlinks=False):
            if any(k.startswith(path + "/") for k in keep):
                _clear_except(Path(entry.path), parts, keep)
            else:
                shutil.rmtree(entry.path)
        elif path not in keep or not entry.is_file(follow_symlinks=False):
            os.unlink(entry.path)


def _copy_ignore(
    src: Path, held: tuple[str, ...] | None, keep: frozenset[str] = frozenset()
) -> Callable[[str, list[str]], set[str]]:
    """shutil.copytree's ignore for copy_manuscript without rsync: BUILD_EXCLUDE_DIRS and *.synctex.gz by name, the
    state folder `held` (its parts below src, state_in_source) at that one place, and the kept paths (keep, POSIX
    below src) at theirs, so a source file of a kept name is never copied over the build's. Folders are compared with
    symlinks resolved, as held is: copytree follows a linked folder, so a link into the state folder copies nothing of
    it."""
    by_name = shutil.ignore_patterns(*BUILD_EXCLUDE_DIRS, "*.synctex.gz")
    base = os.path.realpath(src)

    def ignore(folder: str, names: list[str]) -> set[str]:
        """The names of folder to skip."""
        out = set(by_name(folder, names))
        rel = Path(os.path.relpath(os.path.realpath(folder), base)).parts
        here = () if rel == (".",) else rel
        if held is not None:
            if here[: len(held)] == held:
                return set(names)
            if here == held[:-1] and held[-1] in names:
                out.add(held[-1])
        out.update(n for n in names if "/".join(here + (n,)) in keep)
        return out

    return ignore


LATEXMK_ARGS = ("-pdf", "-synctex=1", "-interaction=nonstopmode")  # latexmk's switches; part of every build's recipe


def compile_tex(D: BuildDoc, cfg: BuildConfig, pull: Callable[[], Json] | None, force: bool = False) -> FinishedBuild:
    """Builds D with -synctex=1 from a copy, leaving the original untouched, then renders pages into a new directory and only swaps the pointer.

    pull is the --git-pull step (None when the flag is off); its record is the outcome's pull. Outcomes: CopyFailed
    (the copy could not be trusted, nothing compiled), BuildFailed (no new PDF, a timeout, no SyncTeX, or the pages
    could not be rendered - the screen keeps the old PDF), BuildOkWithErrors (a new PDF with LaTeX errors, '! '
    lines), BuildOk (no errors) and BuildUnchanged (the copy is the manuscript of the ok build on screen: nothing ran).
    Each carries what the build got as far as: the pull, the manuscript mtime it compiled, the copy's fingerprint,
    latexmk's last lines, and for a success the new page directory.

    The copy keeps the main file's LaTeX byproducts from the last build (limn.builds.warm), so latexmk runs only what
    changed. force (POST /api/rebuild?force=1) clears them first and never skips. Every outcome but BuildOk and
    BuildUnchanged clears them afterwards, so the next build is cold (docs/handbook/build-sync.md §따뜻한 LaTeX와 변경
    없는 재빌드).

    The files another document owns (D.apart) are left out of the manuscript mtime and the fingerprint unless the build
    read them. Which it read is only known once latexmk has run, from the .fls this run wrote in the copy (or, when a
    warm latexmk found everything up to date, the one it vouched for): the copy is scanned once before latexmk (digest
    and mtime of every file), and afterwards the fingerprint is chosen from that scan and the baseline mtime takes in
    the newest file the build read - the mtime as that scan saw it, and only for a file that was in it, so neither a
    file latexmk made nor one it touched can move the baseline past an edit made during the run. The .fls is published
    with the pages (next to the .synctex.gz and .aux), where the later queries find it. The scan hashes the copy but
    takes each mtime from the same file of D.src (when it is the file that was copied), because a copy tool may keep
    only whole seconds and the baseline must not fall below the source's mtime."""
    if force:
        clear_byproducts(D)
    res = _compile(D, cfg, pull, force)
    if not isinstance(res, BuildOk | BuildUnchanged):
        clear_byproducts(D)
    return res


def clear_byproducts(D: BuildDoc) -> None:
    """Remove the main file's LaTeX byproducts and outputs from the folder latexmk runs in (warm.byproduct_names), so
    the next latexmk starts cold. What cannot be removed is left; the next copy or latexmk run decides then."""
    for name in warm.byproduct_names(D.main.stem):
        with contextlib.suppress(OSError):
            (D.out / name).unlink()


def _kept(D: BuildDoc) -> tuple[str, ...]:
    """The build-copy paths of D's byproducts that its copy keeps (warm.kept_paths), against the files the manuscript
    holds where the main file is; none (a cold build) when that folder cannot be listed or lies outside the copy."""
    try:
        out_rel = D.out.relative_to(D.build)
        names = os.listdir(D.src / out_rel)
    except (ValueError, OSError):
        return ()
    return warm.kept_paths(PurePosixPath(out_rel.as_posix()), D.main.stem, names)


def _published_head(D: BuildDoc) -> str:
    """The short commit D's manuscript has checked out now, or '-' outside git."""
    try:
        head = run_git(["-C", str(D.src), "rev-parse", "--short", "HEAD"], D.src, 10)
        return head.stdout.strip() or "-"
    except (OSError, subprocess.SubprocessError):
        return "-"


def _signature(f: Path) -> tuple[int, int, int] | None:
    """(mtime_ns, size, inode) of f when it is a plain file (not a symlink), else None."""
    try:
        st = os.lstat(f)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino) if stat.S_ISREG(st.st_mode) else None


def _compile(D: BuildDoc, cfg: BuildConfig, pull: Callable[[], Json] | None, force: bool) -> FinishedBuild:
    """compile_tex's build itself: pull, copy, the no-change skip, latexmk and the render (compile_tex)."""
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

    keep = _kept(D)
    try:
        copy_manuscript(D.src, D.build, cfg.state, keep)
    except ManuscriptCopyError as e:
        return CopyFailed(str(e), round(time.time() - t0, 1), pulled, compiled_at)
    # The scan is taken from the copy - these are exactly the files this build actually compiles (the original can still
    # change meanwhile). The files another document owns are scanned too, because which of them the build reads is only
    # known after latexmk; the fingerprint and the baseline are chosen from this scan below.
    scan: dict[str, build.ScannedSource] | None
    try:
        scan = build.scan_sources(D, D.build, cfg.state, keep_apart=True, mtimes_from=D.src)
    except OSError:
        scan = None
    build_recipe = warm.recipe(cfg.dpi, PurePosixPath(D.main_rel.as_posix()), LATEXMK_ARGS)

    # The no-change skip: the copy read as the build on screen read its manuscript (that build's .fls) has that build's
    # fingerprint, and the recipe and an ok last build agree - its pages are what this build would make.
    cur = build.cur_pages(D)
    if not force and scan is not None:
        cur_reads = build.read_in_scan(scan, build.build_inputs(D, cur.name))
        seen = build.fingerprint_of(build.without_apart(D, scan, cur_reads))
        pages = len(list(cur.glob("page-*.png"))) if cur.is_dir() else 0
        if pages and warm.keeps_pages(build.load_builds(D), cur.name, seen, build_recipe):
            compiled_at = max(compiled_at, build.newest_read_apart(D, scan, cur_reads))
            head = _published_head(D)
            atomic_write(D.dir / "head.txt", head)
            return BuildUnchanged(round(time.time() - t0, 1), pulled, compiled_at, seen, head, cur.name, pages)

    pdf = D.out / (D.main.stem + ".pdf")
    syn = D.out / (D.main.stem + ".synctex.gz")
    texlog = D.out / (D.main.stem + ".log")
    aux = D.out / (D.main.stem + ".aux")
    fls = D.out / (D.main.stem + ".fls")
    # What the outputs were before latexmk: the copy can hold the last build's (warm), so "written by this run" is a
    # changed file, not a recent mtime - a build that fails a second after the last one must not pass its PDF off.
    before = {f: _signature(f) for f in (pdf, syn, texlog, aux, fls)}

    build.state_update(D, phase="latex")
    # A single document runs in the build root as before; a --doc document runs in the folder holding its main .tex (Doc.out).
    rc, out, timed_out = run_logged(["latexmk", *LATEXMK_ARGS, D.main.name], D.out, cfg.timeout)
    with contextlib.suppress(OSError):
        atomic_write(D.dir / "build.log", out)
    tail = "\n".join(out.splitlines()[-40:])[-4000:]

    def written(f: Path) -> bool:
        """f is a plain file this latexmk run wrote (it is new or changed since before the run)."""
        now = _signature(f)
        return now is not None and now != before[f]

    try:
        logtxt = texlog.read_text(encoding="utf-8", errors="replace") if written(texlog) else out
    except OSError:
        logtxt = out
    errors = latex_errors(logtxt)

    # A warm copy that latexmk found up to date wrote nothing new: its PDF, SyncTeX, .aux and .fls are the last run's,
    # which matched the manuscript then and still do. Only a warm copy is trusted so: a cold one has no fdb of its own.
    settled = bool(keep) and rc == 0 and not timed_out and warm.up_to_date(out)

    def current(f: Path) -> bool:
        """f is a plain file this run wrote, or one that latexmk vouched for (settled)."""
        return written(f) or (settled and _signature(f) is not None)

    # What this run read: the figure-set files of another document that the manuscript uses count as part of it. Only a
    # recorder file this run wrote (or a warm latexmk vouched for) says so - a main.fls shipped with the manuscript is the
    # copy's, not latexmk's - and only the files the scan before latexmk had. A damaged recorder file must not fail a
    # build that made its pages.
    recorder: Path | None = fls if current(fls) else None
    reads: frozenset[str] = frozenset()
    if scan is not None and recorder is not None and not D.apart.empty:
        try:
            reads = build.read_in_scan(scan, build.recorded_inputs(D, recorder))
        except (OSError, ValueError):
            reads = frozenset()
    src_hash = None
    if scan is not None:
        compiled_at = max(compiled_at, build.newest_read_apart(D, scan, reads))
        src_hash = build.fingerprint_of(build.without_apart(D, scan, reads))

    def failed(kind: OutputFailureKind, detail: str = "") -> BuildFailed:
        """This build's failure of `kind`, with latexmk's last lines and what it compiled."""
        return BuildFailed(kind, detail, tail, errors, round(time.time() - t0, 1), pulled, compiled_at, src_hash)

    if timed_out or not current(pdf):
        return failed("timeout" if timed_out else "no_pdf")
    if not current(syn):
        return failed("no_synctex")

    extra = [syn]
    if current(aux):
        extra.append(aux)
    if recorder is not None:
        extra.append(recorder)  # what this build read, kept with its pages (build.build_inputs reads it back)
    newdir = render_pages(D, pdf, extra, cfg.dpi)
    if isinstance(newdir, PagesNotRendered):
        return failed(newdir.kind, newdir.detail)
    # the manuscript is measured against this build's recorder file from the moment the pointer names its pages
    head_short = commit_pages(D, newdir, lambda: build.expire_src_mtime(D))
    pages = len(list(newdir.glob("page-*.png")))
    elapsed_s = round(time.time() - t0, 1)
    if errors:
        return BuildOkWithErrors(
            errors, tail, elapsed_s, pulled, compiled_at, src_hash, head_short, newdir.name, pages, build_recipe
        )
    return BuildOk(tail, elapsed_s, pulled, compiled_at, src_hash, head_short, newdir.name, pages, build_recipe)


RENDER_WORKERS_MAX = 8  # pdftoppm processes one render runs at once, at most
RENDER_TIMEOUT_S = 600  # one render's whole budget; each page gets what is left of it
PART_DIR_RE = re.compile(r"\.pages-.*\.part")  # a page folder being drawn: no client may ask for it (valid_build_name)


def render_workers() -> int:
    """How many pages one render draws at once: min(RENDER_WORKERS_MAX, os.cpu_count()), and one when the count is
    unknown."""
    return min(RENDER_WORKERS_MAX, os.cpu_count() or 1)


def _last_line(err: bytes) -> str:
    """A tool's last non-empty stderr line, for a failure's detail ("" when it said nothing)."""
    lines = err.decode("utf-8", "replace").strip().splitlines()
    return lines[-1].strip()[:200] if lines else ""


def page_count(pdf: Path, timeout: float) -> int | str:
    """The number of pages pdfinfo reads in pdf, or why there is none (a detail for PagesNotRendered render)."""
    try:
        r = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return "pdfinfo not found"
    except subprocess.TimeoutExpired:
        return "pdfinfo timed out"
    if r.returncode != 0:
        return "pdfinfo exit %d: %s" % (r.returncode, _last_line(r.stderr))
    m = re.search(rb"^Pages:\s+(\d+)\s*$", r.stdout, re.MULTILINE)
    if m is None:
        return "pdfinfo gave no page count"
    return int(m.group(1)) or "the PDF has no pages"


def draw_page(pdf: Path, page: int, dpi: int, dest: Path, deadline: float) -> str | None:
    """Draw page `page` of pdf at dpi with its own pdftoppm (a PPM on stdout) and write it to dest as a PNG
    (limn.builds.png). None when the page is written; otherwise why not (the page, and pdftoppm's last message)."""
    left = deadline - time.monotonic()
    if left <= 0:
        return "page %d: no time left" % page
    try:
        r = subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page), "-singlefile", str(pdf)],
            capture_output=True,
            timeout=left,
            check=False,
        )
    except FileNotFoundError:
        return "pdftoppm not found"
    except subprocess.TimeoutExpired:
        return "page %d: pdftoppm timed out" % page
    if r.returncode != 0:
        return "page %d: pdftoppm exit %d: %s" % (page, r.returncode, _last_line(r.stderr))
    img = png.parse_ppm(r.stdout)
    if img is None:
        return "page %d: pdftoppm wrote no PPM image" % page
    try:
        dest.write_bytes(png.png_from_ppm(img, dpi))
    except OSError as e:
        return "page %d: %s" % (page, e)
    return None


def draw_pages(pdf: Path, folder: Path, dpi: int, workers: int) -> str | None:
    """Draw every page of pdf into folder as page-<n>.png, n zero-padded to the page count's digits as
    `pdftoppm -png` names them, with at most `workers` pdftoppm processes at once, page 1 first. None when every page
    is written; otherwise the first failure's detail - the pages not yet started are not drawn."""
    deadline = time.monotonic() + RENDER_TIMEOUT_S
    n = page_count(pdf, RENDER_TIMEOUT_S)
    if isinstance(n, str):
        return n
    width = len(str(n))
    stop = threading.Event()

    def one(page: int) -> str | None:
        """Draw one page unless another page already failed."""
        if stop.is_set():
            return None
        why = draw_page(pdf, page, dpi, folder / ("page-%0*d.png" % (width, page)), deadline)
        if why is not None:
            stop.set()
        return why

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(one, page) for page in range(1, n + 1)]
        failures = [why for why in (f.result() for f in futures) if why is not None]
    return failures[0] if failures else None


def _new_build_name(D: BuildDoc) -> str:
    """A page folder name for a new build: pages-<YYYYmmddHHMMSS>, with the first free -<n> suffix when that folder
    exists or the build history still names it - a name is never given to two builds, so a URL that names a build
    always means the same images."""
    used = set(build.load_builds(D)["by"])
    bid = time.strftime("%Y%m%d%H%M%S")
    name = "pages-" + bid
    k = 1
    while (D.dir / name).exists() or name in used:
        name = "pages-%s-%d" % (bid, k)
        k += 1
    return name


def render_pages(
    D: BuildDoc, pdf: Path, extra: list[Path], dpi: int, workers: int | None = None
) -> Path | PagesNotRendered:
    """Renders pages into a new directory and drops in a copy of the PDF (and extra - synctex, .aux, a figure map).
    Pages are drawn in parallel (draw_pages, at most `workers` at once, render_workers() by default) into a hidden
    folder (.<name>.part) that no client can name; only when every page and companion is in place does it get its
    pages-<build> name, in one rename. The screen keeps showing the old directory until commit_pages. Returns the new
    directory, or why there is none: render (a page could not be drawn; detail names it) or pdf_copy (a companion
    could not be stored) - the half-made folder is removed. A half-made folder a killed process left is cleared first."""
    D.dir.mkdir(parents=True, exist_ok=True)
    for d in D.dir.iterdir():
        if d.is_dir() and PART_DIR_RE.fullmatch(d.name):
            shutil.rmtree(d, ignore_errors=True)
    name = _new_build_name(D)
    part = D.dir / ("." + name + ".part")
    part.mkdir(parents=True)
    build.state_update(D, phase="render")
    why = draw_pages(pdf, part, dpi, render_workers() if workers is None else workers)
    if why is not None:
        shutil.rmtree(part, ignore_errors=True)
        return PagesNotRendered("render", why)
    try:
        shutil.copy2(pdf, part / D.pdf_name)
        for f in extra:
            shutil.copy2(f, part / f.name)
    except OSError as e:
        shutil.rmtree(part, ignore_errors=True)
        return PagesNotRendered("pdf_copy", str(e))
    newdir = D.dir / name
    try:
        os.rename(part, newdir)
    except OSError as e:
        shutil.rmtree(part, ignore_errors=True)
        return PagesNotRendered("render", "page folder not published: %s" % e)
    return newdir


def commit_pages(D: BuildDoc, newdir: Path, on_swap: Callable[[], None] | None = None) -> str:
    """Swaps the pointer to the new page directory in one shot (atomically), keeps only current+previous, and writes built_at/head. head is the short hash.

    on_swap, when given, is called once, right after the pointer names the new directory and before anything else is
    done (the removal of old directories and the call to git can take seconds): the caller's caches that depend on the
    page on screen are dropped there."""
    prev = build.cur_pages(D).name
    atomic_write(D.dir / "pages.cur", newdir.name)  # a single atomic swap
    if on_swap is not None:
        on_swap()
    for d in D.dir.iterdir():  # keep only current and previous
        if d.is_dir() and PAGES_DIR_RE.fullmatch(d.name) and d.name not in (newdir.name, prev):
            shutil.rmtree(d, ignore_errors=True)
    atomic_write(D.dir / "built_at.txt", datetime.now().astimezone().isoformat(timespec="seconds"))
    head_short = _published_head(D)
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
