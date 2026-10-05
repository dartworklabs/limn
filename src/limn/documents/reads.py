"""What the viewer polls about a document: GET /api/meta, GET /api/docs and GET /api/outline-labels.

These responses are the viewer's view of a document's builds and pins (docs/handbook/viewer.md, api.md): the pages
on screen and their sizes, whether the manuscript is newer than the PDF, the build in progress and the last finished
one, and the instance settings the viewer shows. They only read - the page directories, the build state, the
pins file's size and mtime, a build's .aux - so the light poll every few seconds never writes anything.

Every function takes the document, the other documents and the run settings it reads as arguments (coding rule R5):
nothing here reads the server's run arguments or imports it. What only the composition root knows is passed in as a
value - the --git-pull sync status, the pins as read, which document a pin belongs to. What the builds own - the
pages on screen, staleness, build state, the published .aux - is asked of builds (limn.documents.needs.BuildFacts),
which every caller passes: there is no default, so this module imports no other capability. The keys and their order
are the agent contract; a change here must keep every body byte-identical.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from limn.documents.needs import BuildFacts
from limn.documents.outline import toc_labels
from limn.runtime.documents import Doc


@dataclass(frozen=True)
class MetaSettings:
    """The run settings GET /api/meta reads or reports: the state folder (also where the manuscript scan stops), the
    pin files, the instance label/accent/repository the viewer shows, and the dpi the page images were rendered at.
    The composition root makes one per request from its run arguments."""

    state: Path
    pins_md: Path
    label: str
    accent: str
    repo: str | None
    dpi: int


def doc_brief(D: Doc, state_dir: Path, builds: BuildFacts) -> dict[str, Any]:
    """A summary of document D - an entry of /api/docs and (with several documents) of /api/meta's docs: kind, whether
    its pins are regions only (view_only), path, staleness against its manuscript (only for a document built from
    source), build in progress and last result, the page directory on screen and its page count. Never writes (called
    from polling)."""
    return builds.summary(D, state_dir, 150).brief


def docs_payload(
    docs: Sequence[Doc],
    open_counts: Mapping[str, int],
    other_open: int,
    state_dir: Path,
    builds: BuildFacts,
) -> dict[str, Any]:
    """GET /api/docs: every document of docs (the first is the default) with its open-pin count, from the pin records
    rows as read (doc_of says which document a record belongs to). Open pins of a key no document serves any more are
    counted in other_open."""
    return {
        "docs": [dict(doc_brief(d, state_dir, builds), n_open=open_counts.get(d.key, 0)) for d in docs],
        "default": docs[0].key,
        "multi": len(docs) > 1,
        "other_open": other_open,
    }


def meta(
    D: Doc,
    actor: Mapping[str, Any],
    settings: MetaSettings,
    docs: Sequence[Doc],
    sync: Mapping[str, Any],
    now: float,
    builds: BuildFacts,
    pin_revision: str = "0",
) -> dict[str, Any]:
    """GET /api/meta for document D without the pin counts - exactly the light poll's body: its pages (sized at
    settings.dpi), build markers, staleness (only for a document built from source), the build in progress and the
    last finished one, the instance settings, who is asking (actor) and the --git-pull status (sync). With several
    documents, each one's summary (docs) and a signature of their manuscript mtimes (src_sig). now is the clock the
    manuscript age is measured against."""

    facts = builds.summary(D, settings.state, settings.dpi).meta
    sm = facts["src_mtime"]
    multi = len(docs) > 1
    out = {
        "pages": facts["pages"],
        "built_at": facts["built_at"],
        "head": facts["head"],
        "main": D.main.name,
        "pins_md": str(settings.pins_md),
        "state_dir": str(settings.state),
        "me": actor,
        "label": settings.label,
        "accent": settings.accent,
        "repo": settings.repo,
        "building": facts["building"],
        "sync": sync,
        "doc": D.key,
        "doc_name": D.name,
        "kind": D.kind,
        "view_only": D.view_only,
        "multi": multi,
        # Is the manuscript newer than the PDF on screen - the server judges this numerically (independent of browser clock/timezone).
        "stale_build": facts["stale_build"],
        "src_age_s": round(max(0.0, now - sm), 1) if sm else None,
        "src_mtime": sm,
        "build_src_mtime": facts["build_src_mtime"],
        "pages_build": facts["pages_build"],
        "pins_rev": pin_revision,
        # build_seq = number of finished builds, last_build = the most recently finished build (kept regardless of any build in progress).
        "build_seq": facts["build_seq"],
        "last_build": facts["last_build"],
        "build": facts["build"],
    }
    if multi:  # staleness/build of other documents - the viewer shows a dot/progress marker on their tabs
        briefs = [doc_brief(d, settings.state, builds) for d in docs]
        out["docs"] = briefs
        out["src_sig"] = ",".join("%s=%.3f" % (d["key"], d["src_mtime"]) for d in briefs)
    return out


def pin_counts(states: Sequence[str]) -> dict[str, int]:
    """The full /api/meta's pin counts from every pin's state (pin_state): n_open, n_done (done only - awaiting review
    is n_review) and n_review, in that order."""
    return {"n_open": states.count("open"), "n_done": states.count("done"), "n_review": states.count("review")}


def outline_labels(D: Doc, builds: BuildFacts) -> dict[str, Any]:
    """GET /api/outline-labels for document D: {build, labels} - the name of the page directory on screen and the
    outline rows (limn.documents.outline.toc_labels) of the .aux that same build published next to its PDF. Never the .aux in
    the mutable build copy, which a later failed build may have overwritten. No labels for a document not built from
    source (it publishes no .aux), a build without an .aux, an .aux that is a symlink or larger than AUX_MAX_BYTES, or
    one that cannot be read."""
    published = builds.outline(D)
    return {"build": published.build, "labels": toc_labels(published.text)}
