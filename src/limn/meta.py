"""What the viewer polls about a document: GET /api/meta, GET /api/docs and GET /api/outline-labels.

These responses are the viewer's view of a document's builds and pins (docs/handbook/viewer.md, api.md): the pages
on screen and their sizes, whether the manuscript is newer than the PDF, the build in progress and the last finished
one, and the instance settings the viewer shows. They only read - the page directories, the build state, the
pins file's size and mtime, a build's .aux - so the light poll every few seconds never writes anything.

Every function takes the document, the other documents and the run settings it reads as arguments (coding rule R5):
nothing here reads the server's run arguments or imports it. What only the composition root knows is passed in as a
value - the --git-pull sync status, the pins as read, which document a pin belongs to. The keys and their order are
the agent contract; a change here must keep every body byte-identical.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from limn import build
from limn.documents import Doc
from limn.outline import toc_labels

AUX_MAX_BYTES = 4 * 1024 * 1024    # a larger .aux is not read for outline labels


@dataclass(frozen=True)
class MetaSettings:
    """The run settings GET /api/meta reads or reports: the state folder (also where the manuscript scan stops), the
    pin files, the instance label/accent/repository the viewer shows, and the dpi the page images were rendered at.
    The composition root makes one per request from its run arguments."""
    state: Path
    pins_md: Path
    pins_jsonl: Path
    label: str
    accent: str
    repo: str | None
    dpi: int


def pins_rev(pins_jsonl: Path) -> str:
    """"<mtime_ns>:<size>" of the live pins file, or "0" when there is none: the viewer refetches the pins only when
    this changes, so it must change with every write (a write always replaces the file) and not otherwise."""
    try:
        st = pins_jsonl.stat()
        return "%d:%d" % (st.st_mtime_ns, st.st_size)
    except OSError:
        return "0"


def doc_brief(D: Doc, state_dir: Path) -> dict[str, Any]:
    """A summary of document D - an entry of /api/docs and (with several documents) of /api/meta's docs: kind, path,
    staleness against its manuscript, build in progress and last result, the page directory on screen and its page
    count. Never writes (called from polling)."""
    b = build.state_snapshot(D)
    stale = (not D.is_pdf) and build.source_newer(D, state_dir) > 2
    pdir = build.cur_pages(D)
    n_pages = sum(1 for _ in pdir.glob("page-*.png")) if pdir.is_dir() else 0
    return {"key": D.key, "name": D.name, "kind": D.kind, "view_only": D.is_pdf, "path": D.rel_path(),
            "main": D.main.name, "stale_build": stale, "src_mtime": build.src_mtime(D, state_dir),
            "building": D.lock.locked(), "build": {"state": b["state"], "phase": b["phase"]},
            "build_seq": b.get("seq", 0), "last_state": (b.get("last") or {}).get("state"),
            "pages_build": pdir.name, "n_pages": n_pages}


def docs_payload(docs: Sequence[Doc], rows: Iterable[Mapping[str, Any]], doc_of: Callable[[Mapping[str, Any]], str],
                 state_dir: Path) -> dict[str, Any]:
    """GET /api/docs: every document of docs (the first is the default) with its open-pin count, from the pin records
    rows as read (doc_of says which document a record belongs to). Open pins of a key no document serves any more are
    counted in other_open."""
    counts: dict[str, int] = {}
    for r in rows:
        if not r.get("done"):
            k = doc_of(r)
            counts[k] = counts.get(k, 0) + 1
    known = {d.key for d in docs}
    return {"docs": [dict(doc_brief(d, state_dir), n_open=counts.get(d.key, 0)) for d in docs],
            "default": docs[0].key, "multi": len(docs) > 1,
            "other_open": sum(v for k, v in counts.items() if k not in known)}


def meta(D: Doc, actor: Mapping[str, Any], settings: MetaSettings, docs: Sequence[Doc], sync: Mapping[str, Any],
         now: float) -> dict[str, Any]:
    """GET /api/meta for document D without the pin counts - exactly the light poll's body: its pages (sized at
    settings.dpi), build markers, staleness, the build in progress and the last finished one, the instance settings,
    who is asking (actor) and the --git-pull status (sync). With several documents, each one's summary (docs) and a
    signature of their manuscript mtimes (src_sig). now is the clock the manuscript age is measured against."""

    def read(f: str) -> str:
        """A build marker file of D (built_at.txt, head.txt), or "?" when it cannot be read."""
        try:
            return (D.dir / f).read_text().strip()
        except OSError:
            return "?"
    bstate = build.state_snapshot(D)
    sm = build.src_mtime(D, settings.state)
    # view-only: the server re-renders on its own when the PDF changes
    newer = 0.0 if D.is_pdf else build.source_newer(D, settings.state)
    multi = len(docs) > 1
    out = {"pages": build.page_list(build.cur_pages(D), settings.dpi), "built_at": read("built_at.txt"),
           "head": read("head.txt"), "main": D.main.name, "pins_md": str(settings.pins_md),
           "state_dir": str(settings.state), "me": actor,
           "label": settings.label, "accent": settings.accent, "repo": settings.repo,
           "building": D.lock.locked(), "sync": sync,
           "doc": D.key, "doc_name": D.name, "kind": D.kind, "view_only": D.is_pdf, "multi": multi,
           # Is the manuscript newer than the PDF on screen - the server judges this numerically (independent of browser clock/timezone).
           "stale_build": newer > 2, "src_age_s": round(max(0.0, now - sm), 1) if sm else None,
           "src_mtime": sm, "build_src_mtime": build.read_built_src_mtime(D),
           "pages_build": build.cur_pages(D).name,
           "pins_rev": pins_rev(settings.pins_jsonl),
           # build_seq = number of finished builds, last_build = the most recently finished build (kept regardless of any build in progress).
           "build_seq": bstate.get("seq", 0),
           "last_build": bstate.get("last") or {"state": None, "errors": [], "finished_at": None, "seq": 0},
           "build": {"state": bstate["state"], "phase": bstate["phase"], "started_at": bstate.get("started_at")}}
    if multi:                             # staleness/build of other documents - the viewer shows a dot/progress marker on their tabs
        briefs = [doc_brief(d, settings.state) for d in docs]
        out["docs"] = briefs
        out["src_sig"] = ",".join("%s=%.3f" % (d["key"], d["src_mtime"]) for d in briefs)
    return out


def pin_counts(states: Sequence[str]) -> dict[str, int]:
    """The full /api/meta's pin counts from every pin's state (pin_state): n_open, n_done (done only - awaiting review
    is n_review) and n_review, in that order."""
    return {"n_open": states.count("open"), "n_done": states.count("done"), "n_review": states.count("review")}


def outline_labels(D: Doc) -> dict[str, Any]:
    """GET /api/outline-labels for document D: {build, labels} - the name of the page directory on screen and the
    outline rows (limn.outline.toc_labels) of the .aux that same build published next to its PDF. Never the .aux in
    the mutable build copy, which a later failed build may have overwritten. No labels for a view-only document, a
    build without an .aux, an .aux that is a symlink or larger than AUX_MAX_BYTES, or one that cannot be read."""
    pages = build.cur_pages(D)
    result: dict[str, Any] = {"build": pages.name, "labels": []}
    if D.is_pdf:
        return result
    aux = pages / (D.main.stem + ".aux")
    try:
        if aux.is_symlink() or aux.stat().st_size > AUX_MAX_BYTES:
            return result
        source = aux.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result
    result["labels"] = toc_labels(source)
    return result
