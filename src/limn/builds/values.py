"""Shared build outcome values without artifact, clock, or persistence dependencies."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, get_args

# The build state's "state" (GET /api/build, builds.json `last.state`): no build yet, a build running, or how the last
# one finished. The viewer's chip and error panel read the same names.
BuildState: TypeAlias = Literal["idle", "running", "ok", "ok_errors", "fail"]
BUILD_STATES: tuple[BuildState, ...] = get_args(BuildState)
FinishedState: TypeAlias = Literal["ok", "ok_errors", "fail"]
# One LaTeX error of the error panel: {"line": <int or None>, "msg": <text>} (latex_errors).
LatexError: TypeAlias = dict[str, Any]
Json: TypeAlias = dict[str, Any]

# ---------------------------------------------------------------- Build outcomes
#
# A build ends in one of these values; nothing here writes their JSON or their failure texts. The HTTP answer of POST
# /api/rebuild is written once, at the build feature edge (limn.builds.answer.rebuild_answer), and a failure's log text comes from
# the web layer's table (limn.web.errors.BUILD_FAILURES) through the `describe` function the composition root passes
# to the calls that record a finished build. Where a field is "None: no key", the answer leaves that key out - the
# answer has always carried only what the build got as far as.

# Why a build failed; each kind has one text in limn.web.errors.BUILD_FAILURES. The narrower kinds are what each
# failure type can carry (tests pin that together they are every kind but "copy", which is CopyFailed's own).
BuildFailureKind: TypeAlias = Literal[
    "copy",
    "timeout",
    "no_pdf",
    "no_synctex",
    "render",
    "pdf_copy",
    "pdf_missing",
    "figure_unready",
    "crashed",
    "worker_crashed",
]
RenderFailureKind: TypeAlias = Literal["render", "pdf_copy"]
OutputFailureKind: TypeAlias = Literal["timeout", "no_pdf", "no_synctex", "render", "pdf_copy"]
AbortKind: TypeAlias = Literal["pdf_missing", "figure_unready", "crashed", "worker_crashed"]


@dataclass(frozen=True)
class BuildOk:
    """A build that made new page images with no LaTeX error.

    log is latexmk's last lines ("" for a view-only render); pull is the --git-pull record (None: no pull ran, no key);
    src_mtime the manuscript mtime it compiled (None for a view-only document, no key); src_hash the fingerprint of
    what it compiled (None when it could not be read); head the short commit, build the new page directory's name,
    pages how many page images it holds."""

    log: str
    elapsed_s: float
    pull: Json | None
    src_mtime: float | None
    src_hash: str | None
    head: str
    build: str
    pages: int


@dataclass(frozen=True)
class BuildOkWithErrors:
    """A LaTeX build that made new page images although the log has errors ('! ' lines, at most five in errors).
    The other fields are BuildOk's."""

    errors: list[LatexError]
    log: str
    elapsed_s: float
    pull: Json | None
    src_mtime: float
    src_hash: str | None
    head: str
    build: str
    pages: int


@dataclass(frozen=True)
class CopyFailed:
    """The manuscript copy could not be trusted (limn.builds.artifacts.ManuscriptCopyError, its text in error), so nothing was
    compiled. pull and src_mtime as in BuildOk; no fingerprint was taken."""

    error: str
    elapsed_s: float
    pull: Json | None
    src_mtime: float


@dataclass(frozen=True)
class BuildFailed:
    """The build ran but left no new page images: latexmk timed out, made no fresh PDF or no SyncTeX file, or the
    pages could not be rendered or stored. detail fills the kind's text (the OSError of pdf_copy, else "");
    output is latexmk's last lines, appended after the text (None for a view-only render, which runs no latexmk).
    errors, pull, src_mtime and src_hash as in BuildOk and BuildOkWithErrors."""

    kind: OutputFailureKind
    detail: str
    output: str | None
    errors: list[LatexError]
    elapsed_s: float
    pull: Json | None
    src_mtime: float | None
    src_hash: str | None


@dataclass(frozen=True)
class BuildAborted:
    """The build stopped before it measured anything: a view-only document's PDF is missing (detail: its path), a
    figure document's map and PDF do not agree when a tracked build is asked to import them (figure_unready; detail:
    the reason and its detail - the watch never gets here, it waits instead), or the build died of an unexpected
    exception (detail: its repr) - in the tracked build (crashed) or in the background worker around it
    (worker_crashed). Reported with elapsed_s 0.0."""

    kind: AbortKind
    detail: str


FailedBuild: TypeAlias = CopyFailed | BuildFailed | BuildAborted
FinishedBuild: TypeAlias = BuildOk | BuildOkWithErrors | FailedBuild
# The text of a failed build's log (limn.web.errors.build_failure_log), passed in by the composition root.
Describe: TypeAlias = Callable[[FailedBuild], str]


@dataclass(frozen=True)
class BuildBusy:
    """The document is already building (its build lock is held); nothing was started."""


@dataclass(frozen=True)
class BuildStarted:
    """A background build of the document was started; its state is running."""


@dataclass(frozen=True)
class ViewOnlyNoRebuild:
    """A rebuild asked of a view-only PDF document (request_rebuild): there is nothing to compile - its pages are
    redrawn by themselves when the PDF file changes. key names the document for the refusal."""

    key: str


@dataclass(frozen=True)
class BuildSkipped:
    """Startup found the document's page images current, so it did not build."""


@dataclass(frozen=True)
class PagesNotRendered:
    """render_pages made no page directory: pdftoppm failed (render), or the PDF and its companions could not be
    copied next to the pages (pdf_copy; detail is the OSError)."""

    kind: RenderFailureKind
    detail: str
