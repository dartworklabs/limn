"""Project finished builds into history and viewer values without reading runtime state."""

from dataclasses import dataclass
from typing import Any

from limn.builds.values import (
    BuildAborted,
    BuildFailed,
    BuildOk,
    BuildOkWithErrors,
    BuildUnchanged,
    CopyFailed,
    FinishedBuild,
    FinishedState,
    Json,
    LatexError,
)


@dataclass(frozen=True)
class BuildCompletion:
    """History and live display facts, awaiting the persisted sequence and built-at timestamp.

    The history log is bounded; log retains the entire rendered text for the live error panel.
    Payload dictionaries preserve the existing serialized insertion order.
    """

    last: Json
    entry: Json | None
    pages: int
    log: str

    def publication(self, seq: int, built_at: str | None) -> Json:
        """Add shell-provided persistence facts to the final atomic state update payload."""
        last = self.last
        return {
            "state": last["state"],
            "phase": None,
            "start_ts": None,
            "seq": seq,
            "finished_at": last["finished_at"],
            "elapsed_s": last["elapsed_s"],
            "last_s": last["elapsed_s"],
            "pages": self.pages,
            "errors": last["errors"],
            "head": last["head"],
            "pull": last["pull"],
            "log_tail": self.log,
            "built_at": built_at,
            "last": {
                "state": last["state"],
                "errors": last["errors"],
                "finished_at": last["finished_at"],
                "seq": seq,
                "head": last["head"],
                "pull": last["pull"],
            },
        }


def project_completion(
    res: FinishedBuild,
    finished_at: str,
    started_at: Any,
    src_mtime_for_build: float | None,
    log: str,
) -> BuildCompletion:
    """Compute completion payloads from a finished outcome and already-read runtime facts.

    log is the outcome's success log or the shell-rendered failure text. started_at keeps
    the existing state's value unchanged, including absent or legacy values. Only successful
    outcomes naming a page directory receive a history entry; every outcome receives last.
    """
    new_pages = res if isinstance(res, BuildOk | BuildOkWithErrors) else None
    last = {
        "state": finished_state(res),
        "errors": list(build_errors(res))[:5],
        "finished_at": finished_at,
        "elapsed_s": build_elapsed(res),
        "log_tail": log[-4000:],
        "head": None if new_pages is None else new_pages.head,
        "pull": build_pull(res),
        "started_at": started_at,
    }
    entry = None
    if new_pages is not None and new_pages.build:
        entry = {
            "build": new_pages.build,
            "src_mtime": src_mtime_for_build,
            "src_hash": new_pages.src_hash,
            "finished_at": finished_at,
        }
        if new_pages.recipe is not None:
            entry["recipe"] = new_pages.recipe
    return BuildCompletion(last, entry, 0 if new_pages is None else new_pages.pages, log)


def kept_publication(res: BuildUnchanged, finished_at: str, built_at: str | None) -> Json:
    """The build state an unchanged rebuild leaves (limn.builds.values.BuildUnchanged): finished ok, with unchanged
    true, its elapsed time, pull, head and the kept build's page count. seq, last_s and last stay as the last counted
    build left them - nothing was built, so the viewer swaps nothing and the next build's estimate keeps its basis."""
    return {
        "state": "ok",
        "phase": None,
        "start_ts": None,
        "finished_at": finished_at,
        "elapsed_s": res.elapsed_s,
        "pages": res.pages,
        "errors": [],
        "head": res.head,
        "pull": res.pull,
        "log_tail": "",
        "built_at": built_at,
        "unchanged": True,
    }


def compiled_mtime(res: FinishedBuild) -> float | None:
    """The mtime of the manuscript the build compiled (measured after the pull, before the copy), or None when the
    build never measured it (a view-only render, or a build that stopped first)."""
    match res:
        case (
            BuildOk(src_mtime=m)
            | BuildOkWithErrors(src_mtime=m)
            | BuildUnchanged(src_mtime=m)
            | CopyFailed(src_mtime=m)
            | BuildFailed(src_mtime=m)
        ):
            return m
        case BuildAborted():
            return None


def finished_state(res: FinishedBuild) -> FinishedState:
    """The build state name of a finished build: ok (an unchanged rebuild too), ok_errors (new pages, LaTeX errors) or
    fail."""
    match res:
        case BuildOk() | BuildUnchanged():
            return "ok"
        case BuildOkWithErrors():
            return "ok_errors"
        case CopyFailed() | BuildFailed() | BuildAborted():
            return "fail"


def build_errors(res: FinishedBuild) -> list[LatexError]:
    """The LaTeX errors a finished build reports ([] when it has none or never ran latexmk)."""
    match res:
        case BuildOkWithErrors(errors=errors) | BuildFailed(errors=errors):
            return errors
        case BuildOk() | BuildUnchanged() | CopyFailed() | BuildAborted():
            return []


def build_elapsed(res: FinishedBuild) -> float:
    """How long the build took in seconds (rounded to 0.1); 0.0 for a build that stopped before measuring."""
    match res:
        case (
            BuildOk(elapsed_s=s)
            | BuildOkWithErrors(elapsed_s=s)
            | BuildUnchanged(elapsed_s=s)
            | CopyFailed(elapsed_s=s)
            | BuildFailed(elapsed_s=s)
        ):
            return s
        case BuildAborted():
            return 0.0


def build_pull(res: FinishedBuild) -> Json | None:
    """The --git-pull record of the build, or None when no pull ran."""
    match res:
        case (
            BuildOk(pull=p)
            | BuildOkWithErrors(pull=p)
            | BuildUnchanged(pull=p)
            | CopyFailed(pull=p)
            | BuildFailed(pull=p)
        ):
            return p
        case BuildAborted():
            return None
